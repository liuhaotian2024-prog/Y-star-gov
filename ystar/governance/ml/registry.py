"""
ystar.governance.ml.registry — ConstraintRegistry, ManagedConstraint
v0.41: 从 metalearning.py 拆分，原始行 2547-2713。
"""
from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from ystar.kernel.dimensions import IntentContract

class ManagedConstraint:
    """
    带生命周期状态的约束条目。

    生命周期：
      DRAFT      → 从违规历史/ParameterDiscovery/SemanticInquiry提出
      VERIFIED   → ProposalVerifier数学验证通过（PASS/WARN）
      APPROVED   → 人类确认，可以进入active合约
      ACTIVE     → 已写入active合约，正在执行
      DEPRECATED → 被更严格的规则取代，或主动停用
      REJECTED   → 人类拒绝，永不进入active

    原则：
      只有 APPROVED 的约束才能变成 ACTIVE
      ACTIVE 的约束只能通过显式 deprecate() 停用，不能静默丢失
    """
    id:          str
    dimension:   str
    rule:        str           # e.g. "risk_score < 0.8"
    status:      str = "DRAFT" # DRAFT|VERIFIED|APPROVED|ACTIVE|DEPRECATED|REJECTED
    source:      str = ""      # "metalearning" | "parameter_discovery" | "human" | "semantic_inquiry"
    confidence:  float = 0.0
    created_at:  float = 0.0
    updated_at:  float = 0.0
    notes:       str = ""

    VALID_STATUSES = frozenset(
        ["DRAFT", "VERIFIED", "APPROVED", "ACTIVE", "DEPRECATED", "REJECTED"])
    VALID_TRANSITIONS = {
        "DRAFT":      {"VERIFIED", "REJECTED"},
        "VERIFIED":   {"APPROVED", "REJECTED"},
        "APPROVED":   {"ACTIVE", "REJECTED"},
        "ACTIVE":     {"DEPRECATED"},
        "DEPRECATED": set(),
        "REJECTED":   set(),
    }

    def transition(self, new_status: str, notes: str = "") -> "ManagedConstraint":
        """状态转移，违反规则时抛出ValueError"""
        if new_status not in self.VALID_STATUSES:
            raise ValueError(f"Unknown status: {new_status}")
        allowed = self.VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition {self.status} → {new_status}. "
                f"Allowed: {allowed}"
            )
        import time
        return ManagedConstraint(
            id=self.id, dimension=self.dimension, rule=self.rule,
            status=new_status, source=self.source,
            confidence=self.confidence,
            created_at=self.created_at,
            updated_at=time.time(),
            notes=notes or self.notes,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "dimension": self.dimension,
            "rule": self.rule, "status": self.status,
            "source": self.source, "confidence": self.confidence,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ManagedConstraint":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class ConstraintRegistry:
    """
    约束生命周期注册表。

    管理从提出到激活到废弃的完整生命周期。
    可以序列化到JSON，支持持久化。
    """
    constraints: List[ManagedConstraint] = field(default_factory=list)

    def add(self, constraint: ManagedConstraint) -> None:
        """添加约束（必须是DRAFT状态）"""
        if constraint.status != "DRAFT":
            raise ValueError("新增约束必须是DRAFT状态")
        self.constraints.append(constraint)

    def get(self, constraint_id: str) -> Optional[ManagedConstraint]:
        return next((c for c in self.constraints if c.id == constraint_id), None)

    def by_status(self, status: str) -> List[ManagedConstraint]:
        return [c for c in self.constraints if c.status == status]

    def verify(self, constraint_id: str, notes: str = "") -> ManagedConstraint:
        """标记为已验证（DRAFT→VERIFIED）"""
        return self._transition(constraint_id, "VERIFIED", notes)

    def approve(self, constraint_id: str, notes: str = "") -> ManagedConstraint:
        """人类批准（VERIFIED→APPROVED）"""
        return self._transition(constraint_id, "APPROVED", notes)

    def activate(self, constraint_id: str, notes: str = "") -> ManagedConstraint:
        """写入活跃合约（APPROVED→ACTIVE）"""
        return self._transition(constraint_id, "ACTIVE", notes)

    def deprecate(self, constraint_id: str, notes: str = "") -> ManagedConstraint:
        """停用（ACTIVE→DEPRECATED）"""
        return self._transition(constraint_id, "DEPRECATED", notes)

    def reject(self, constraint_id: str, notes: str = "") -> ManagedConstraint:
        """拒绝（DRAFT/VERIFIED/APPROVED→REJECTED）"""
        return self._transition(constraint_id, "REJECTED", notes)

    def _transition(self, constraint_id: str,
                    new_status: str, notes: str) -> ManagedConstraint:
        c = self.get(constraint_id)
        if c is None:
            raise KeyError(f"Constraint {constraint_id} not found")
        new_c = c.transition(new_status, notes)
        self.constraints = [new_c if x.id == constraint_id else x
                            for x in self.constraints]
        return new_c

    def to_active_contract(self) -> "IntentContract":
        """
        把所有ACTIVE状态的约束编译成一个IntentContract。
        这是约束生命周期和Y*内核的交接点。
        """
        active = self.by_status("ACTIVE")
        deny, inv, opt_inv, vr = [], [], [], {}
        for mc in active:
            if mc.dimension == "deny":
                deny.append(mc.rule)
            elif mc.dimension == "invariant":
                inv.append(mc.rule)
            elif mc.dimension == "optional_invariant":
                opt_inv.append(mc.rule)
            elif mc.dimension == "value_range":
                import re as _re
                m = _re.match(r"(\w+)\s*[<>]=?\s*([\d.]+)", mc.rule)
                if m:
                    param, val = m.group(1), float(m.group(2))
                    if "<" in mc.rule:
                        vr[param] = {"max": val}
                    else:
                        vr[param] = {"min": val}
        from ystar.kernel.dimensions import IntentContract as IC
        return IC(deny=deny, invariant=inv,
                  optional_invariant=opt_inv, value_range=vr)

    def summary(self) -> str:
        from collections import Counter
        counts = Counter(c.status for c in self.constraints)
        lines = ["ConstraintRegistry:"]
        for s in ManagedConstraint.VALID_STATUSES:
            n = counts.get(s, 0)
            if n > 0:
                lines.append(f"  {s:12} {n}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"constraints": [c.to_dict() for c in self.constraints]}

    @classmethod
    def from_dict(cls, d: dict) -> "ConstraintRegistry":
        return cls(constraints=[ManagedConstraint.from_dict(c)
                                 for c in d.get("constraints", [])])

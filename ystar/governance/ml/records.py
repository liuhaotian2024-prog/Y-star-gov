"""
ystar.governance.ml.records — CallRecord, CandidateRule, MetalearnResult
v0.41: 从 metalearning.py 拆分。原始文件行 61-289。
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import Violation

class CallRecord:
    """
    A single recorded function call — CIEU五元组的完整实现（v0.7.0）。

    CIEU = Causal Intent-Experience Unit
    标准五元组：(x_t, u_t, y*_t, y_{t+1}, r_{t+1})

    字段映射：
        seq, func_name:   元数据
        params:           u_t  — 实际动作（函数参数）
        result:           y_{t+1} — 实际结果（函数返回值）
        violations:       r_{t+1} — 反馈（违规列表）
        system_state:     x_t  — 系统状态（调用时的环境上下文，v0.7新增）
        intent_contract:  y*_t — 理想合约：这次调用"应该"满足什么（v0.7新增）
                          语义：规范性的，即使没有被实际执行也要记录
                          来源：prefill()的输出，或ConstitutionalContract的投影
        applied_contract: 实际合约：check()实际用了哪个合约对象（v0.7新增）
                          语义：描述性的，记录实际发生了什么
                          注意：applied_contract不在经典CIEU五元组里，
                          是Y*特有的额外字段，用于捕捉理想与实际的偏差
        contract:         向后兼容字段（deprecated，映射到intent/applied）
        timestamp:        unix时间戳（高阶维度学习需要）
        caller_ctx:       调用者上下文

    y*_t语义定论（v0.7钉死）：
        y*_t = 理想合约（ideal contract）
        记录的是"应该"，不是"实际执行了什么"。
        这是CIEU最核心的分析轴：测量理想(y*_t)和行为(y_{t+1})之间的偏差。
        如果y*_t等于applied_contract，偏差只能反映"合约执行失败"，
        看不到"合约本身就是错的"。
    """
    seq:        int                  # sequence number in the session
    func_name:  str                  # function that was called
    params:     Dict[str, Any]       # u_t — actual parameters / action
    result:     Any                  # y_{t+1} — actual return value
    violations: List[Violation]      # r_{t+1} — violations detected at call time

    # ── v0.7 added: CIEU complete five-tuple fields ────────────────────────────
    system_state:     Dict[str, Any]       = field(default_factory=dict)
    # x_t — system state: environmental context at call time
    # e.g. {"env": "staging", "session_id": "abc", "active_constitution": "sha256:..."}
    # Source: populated by the caller at execution time; Y* does not enforce a format

    intent_contract:  Optional[IntentContract] = None
    # y*_t — ideal contract: what this call "should" satisfy
    # Normative field: should be recorded even if not enforced at runtime
    # Source: output of prefill(), or the result of ConstitutionalContract.merge()

    applied_contract: Optional[IntentContract] = None
    # Applied contract: the contract object actually used by check()
    # Descriptive field: records the contract in effect during actual execution
    # Note: not part of the classic CIEU five-tuple; this is a Y*-specific field

    # ── Backward compatibility ────────────────────────────────────────────────
    contract:   Optional[IntentContract] = None
    # deprecated: use intent_contract and applied_contract instead
    # Backward compatibility: __post_init__ maps these automatically

    timestamp:  float = 0.0          # unix timestamp（高阶维度学习需要）
    caller_ctx: Dict[str, Any] = field(default_factory=dict)  # 调用者上下文

    def __post_init__(self):
        """向后兼容：旧 contract 字段自动映射到新字段。"""
        if self.contract is not None:
            if self.intent_contract is None:
                self.intent_contract = self.contract
            if self.applied_contract is None:
                self.applied_contract = self.contract

    def violation_category(self) -> str:
        """
        判断本次调用属于四种情况中的哪一种。

        情况A: applied == ideal，有violation
          → 理想合约本身有缺陷，metalearning应收紧 intent_contract
        情况B: applied ≠ ideal（实际更宽），有violation
          → 合约在应用时被放宽，执行层问题
        情况C: applied ≠ ideal（实际更严），无violation
          → 过度收紧，可能是误报来源
        情况D: applied == ideal，无violation
          → 正常工作，正样本

        Returns:
            "A_ideal_deficient" / "B_execution_drift" /
            "C_over_tightened"  / "D_normal" / "unknown"
        """
        has_violation = bool(self.violations)
        ideal   = self.intent_contract
        applied = self.applied_contract

        if ideal is None or applied is None:
            return "unknown"

        same_contract = (ideal.hash == applied.hash)

        if has_violation and same_contract:
            return "A_ideal_deficient"
        elif has_violation and not same_contract:
            return "B_execution_drift"
        elif not has_violation and not same_contract:
            return "C_over_tightened"
        else:
            return "D_normal"

    def to_dict(self) -> dict:
        """序列化为CIEU wire format（语言无关）"""
        import json as _json
        d: dict = {
            "seq":       self.seq,
            "func_name": self.func_name,
            "params":    {k: str(v)[:300] for k, v in self.params.items()},
            "result":    {k: str(v)[:300] for k, v in (self.result or {}).items()},
            "violations":[v.to_dict() for v in self.violations],
            "timestamp": self.timestamp,
        }
        if self.intent_contract:
            d["intent_contract"]  = self.intent_contract.to_dict()
        if self.applied_contract:
            d["applied_contract"] = self.applied_contract.to_dict()
        if self.system_state:
            d["system_state"] = self.system_state
        if self.caller_ctx:
            d["caller_ctx"]  = self.caller_ctx
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CallRecord":
        """从CIEU wire format反序列化"""
        from ystar.kernel.dimensions import IntentContract as IC
        from ystar.kernel.engine import Violation as V
        return cls(
            seq            = d.get("seq", 0),
            func_name      = d.get("func_name", ""),
            params         = d.get("params", {}),
            result         = d.get("result", {}),
            violations     = [V.from_dict(v) for v in d.get("violations", [])],
            intent_contract = IC.from_dict(d["intent_contract"])
                              if "intent_contract" in d else None,
            applied_contract = IC.from_dict(d["applied_contract"])
                               if "applied_contract" in d else None,
            system_state   = d.get("system_state", {}),
            timestamp      = d.get("timestamp", 0.0),
            caller_ctx     = d.get("caller_ctx", {}),
        )


@dataclass
class CandidateRule:
    """A constraint rule candidate generated by intervention."""
    id:                 str
    description:        str
    func_name:          str
    dimension:          str            # which IntentContract dimension to add to
    value:              Any            # the value to add
    root_seq:           int            # sequence of the root cause event
    incident_seq:       int            # sequence of the terminal violation
    fp_rate:            float = 1.0   # false positive rate on counterfactual replay
    causal_proof:       str   = ""    # human-readable causal evidence
    violation_category: str   = ""    # v0.7新增: A/B/C/D — 来自哪类情况
    target_layer:       str   = ""    # v0.7新增: "intent"(收紧y*) or "applied"(收紧执行)


@dataclass
class MetalearnResult:
    """Output of the metalearning algorithm."""
    incidents:          List[CallRecord]
    candidates:         List[CandidateRule]
    minimum_cover:      List[CandidateRule]
    contract_additions: IntentContract      # suggested additions to the contract
    dimension_hints:    List[str] = field(default_factory=list)
    # dimension_hints: higher-order dimensions recommended for introduction (output of DimensionDiscovery)
    diagnosis:          Dict[str, int] = field(default_factory=dict)
    # v0.7 added: distribution statistics for the four CIEU situation types
    objective:          Optional[NormativeObjective] = None
    # v0.8 added: objective function used by this learn() call (derived or externally supplied)
    quality:            Optional[ContractQuality] = None
    # v0.8 added: quality assessment of contract_additions
    # v0.7 added: distribution statistics for the four situation types
    # {"A_ideal_deficient": N, "B_execution_drift": N,
    #  "C_over_tightened": N, "D_normal": N, "unknown": N}
    # Lets the user see at a glance which layer the problems are concentrated in

    def explain_diagnosis(self) -> str:
        """以人类可读格式解释诊断结果。"""
        if not self.diagnosis:
            return "No diagnosis available."
        total = sum(self.diagnosis.values())
        if total == 0:
            return "No calls recorded."
        lines = ["CIEU诊断报告:"]
        labels = {
            "A_ideal_deficient": "理想合约缺陷（y*_t本身需要收紧）",
            "B_execution_drift":  "执行层偏离（applied比ideal更宽）",
            "C_over_tightened":   "过度收紧（applied比ideal更严，误报来源）",
            "D_normal":           "正常工作",
            "unknown":            "信息不完整（缺少intent/applied合约）",
        }
        for key, label in labels.items():
            count = self.diagnosis.get(key, 0)
            if count > 0:
                pct = count / total * 100
                lines.append(f"  {label}: {count}次 ({pct:.0f}%)")
        # Provide the primary recommendation
        a = self.diagnosis.get("A_ideal_deficient", 0)
        b = self.diagnosis.get("B_execution_drift", 0)
        if a > 0 and a >= b:
            lines.append("→ 主要建议：收紧 intent_contract（理想合约有缺口）")
        elif b > a:
            lines.append("→ 主要建议：检查合约应用层（执行时合约被放宽）")
        return "\n".join(lines)



# ── v0.8.0: Internal objective function derivation ───────────────────────────
#
# Design principles:
#   1. Purely deterministic: identical history always produces identical NormativeObjective
#   2. Zero LLM dependency: all derivation is arithmetic and statistics; no model calls
#   3. Backward-compatible: the legacy max_fp_rate interface continues to work
#
# Adaptation roadmap (three phases):
#   V08 (current): fixed prior coefficients; objective derived from statistics
#   Future phase 2: coefficients derived from long-term CIEU outcome feedback (requires sufficient history)
#   Future phase 3: confidence intervals tighten; conservative with small samples, adaptive with large samples
#
# The prior coefficients are set by hand — of the same nature as max_fp_rate=0.05.
# "Internal derivation" refers to the derivation mechanism, not the origin of the coefficients themselves.
# TODO: Implementation pending

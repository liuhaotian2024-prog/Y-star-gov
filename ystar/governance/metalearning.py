# STATUS: LEGACY — not on the main governance runtime path
# ystar — Human Intent to Machine Predicate
# Copyright (C) 2026 Haotian Liu
# MIT License
#
# v0.41.0
# Fix: _violation_to_candidate now covers all 8 dimensions (previously only 3.5)
# Fix: _candidates_to_contract outputs all 8 dimensions
# Added: DimensionDiscovery — identifies violation patterns that existing dimensions cannot express
#
# v0.41.0
# Added: NormativeObjective — deterministically derive objective from CIEU history (replaces external max_fp_rate)
# Added: ContractQuality    — self-assessment of contract quality (coverage / precision / completeness)
# Added: score_candidate()  — multi-dimensional candidate scoring (replaces binary pass/fail)
# Upgraded: learn()         — objective parameter; supports auto-derivation or external injection; backward-compatible
#
# v0.9.0
# Added: AdaptiveCoefficients — learnable prior coefficients (phase-2 adaptation)
# Added: RefinementFeedback   — refinement effectiveness records (raw material for coefficient learning)
# Added: update_coefficients() — deterministic coefficient update (derive new coefficients from feedback)
# Added: derive_objective_adaptive() — derive objective using adaptive coefficients
#
# v0.10.0
# Added: YStarLoop — adaptive closed-loop workflow interface
#         assembles learn/record/tighten/feedback into a standard usage pattern
"""
Causal metalearning: tighten intent contracts from violation history.

import logging
_log = logging.getLogger(__name__)

This module is intentionally independent of K9Audit's CIEU format.
It operates on any sequence of (params, result, violations) records.

v0.3.0 metalearning dimension coverage:
  deny          ✓ extract violation patterns
  deny_commands ✓ 提取违规command
  invariant     ✓ 提取违规表达式
  only_paths    ✓ 修复：从路径违规推断允许路径的收紧方向
  only_domains  ✓ 修复：降级为deny（保持原逻辑）
  postcondition ✓ 新增：从postcondition违规提取表达式
  field_deny    ✓ 新增：从field违规提取blocked值
  value_range   ✓ 新增：从数值越界推断更严的边界

同时新增 DimensionDiscovery：
  识别"现有8个维度无法表达的违规模式"，
  提议需要高阶维度（temporal/aggregate/context/resource）。
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ystar.kernel.dimensions import IntentContract, HigherOrderContract, TemporalConstraint, AggregateConstraint
from ystar.kernel.engine import check, CheckResult, Violation


# ── Input record format ───────────────────────────────────────────────────────

@dataclass
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

@dataclass
class NormativeObjective:
    """
    从CIEU历史确定性推导出的目标函数（v0.8.0新增）。

    替代外部传入的 max_fp_rate，让系统自己知道"什么叫更好的合约"。

    字段：
        fp_tolerance:    允许的最大误报率（核心阈值）
        severity_weight: 候选评分中严重度权重
        precision_weight:候选评分中精确度权重
        coverage_weight: 候选评分中覆盖率权重
        derived:         True=从历史推导，False=来自外部max_fp_rate
        derivation_note: 推导过程说明
        sample_size:     推导所用样本量

    先验系数说明（诚实的工程注记）：
        BASE_FP_TOLERANCE = 0.05   无历史时的基准
        HIGH_SEVERITY_PEN = 0.03   严重度高时降低容忍度
        HIGH_DENSITY_PEN  = 0.02   违规密集时降低容忍度
        CAT_A_BONUS       = 0.02   A类为主时略提高容忍度
        这些系数是人工先验，未来第二阶段被CIEU效果反馈替代。
    """
    fp_tolerance:    float
    severity_weight: float = 0.4
    precision_weight:float = 0.4
    coverage_weight: float = 0.2
    derived:         bool  = True
    derivation_note: str   = ""
    sample_size:     int   = 0

    def __str__(self) -> str:
        src = "derived" if self.derived else "external"
        return (f"NormativeObjective(fp_tolerance={self.fp_tolerance:.3f}, "
                f"w=[{self.severity_weight:.2f},{self.precision_weight:.2f},"
                f"{self.coverage_weight:.2f}], source={src}, n={self.sample_size})")


@dataclass
class ContractQuality:
    """
    合约质量自评估（v0.8.0新增）。

    让系统能回答"当前合约有多好"，以及
    "这次refinement让合约变好了还是变坏了"。

    字段：
        coverage_rate:          历史违规中有多少能被合约预防
        false_positive_rate:    安全调用中有多少被误拦
        dimension_completeness: 8个基础维度中有多少被激活
        quality_score:          综合评分（coverage×0.4 + precision×0.4 + completeness×0.2）
        incident_count:         评估用的违规样本数
        safe_count:             评估用的安全调用样本数
        note:                   质量说明
    """
    coverage_rate:          float
    false_positive_rate:    float
    dimension_completeness: float
    quality_score:          float
    incident_count:         int = 0
    safe_count:             int = 0
    note:                   str = ""

    @classmethod
    def evaluate(
        cls,
        contract: IntentContract,
        history:  List["CallRecord"],
    ) -> "ContractQuality":
        """对给定合约在给定历史上做质量评估。"""
        incidents  = [r for r in history if r.violations]
        safe_calls = [r for r in history if not r.violations]

        # coverage_rate
        if incidents:
            blocked = sum(
                1 for r in incidents
                if not check(r.params, r.result, contract).passed
            )
            coverage_rate = blocked / len(incidents)
        else:
            coverage_rate = 1.0

        # false_positive_rate
        if safe_calls:
            fp_count = sum(
                1 for r in safe_calls
                if not check(r.params, r.result, contract).passed
            )
            fp_rate = fp_count / len(safe_calls)
        else:
            fp_rate = 0.0

        # dimension_completeness
        active = sum([
            bool(contract.deny),
            bool(contract.only_paths),
            bool(contract.deny_commands),
            bool(contract.only_domains),
            bool(contract.invariant),
            bool(contract.postcondition),
            bool(contract.field_deny),
            bool(contract.value_range),
        ])
        completeness = active / 8.0

        # quality_score
        precision = 1.0 - fp_rate
        quality   = coverage_rate * 0.4 + precision * 0.4 + completeness * 0.2

        parts = []
        if coverage_rate < 0.5:
            parts.append(f"低覆盖率({coverage_rate:.0%})")
        if fp_rate > 0.1:
            parts.append(f"高误报({fp_rate:.0%})")
        if completeness < 0.25:
            parts.append("维度稀疏")
        note = "、".join(parts) if parts else "质量良好"

        return cls(
            coverage_rate          = coverage_rate,
            false_positive_rate    = fp_rate,
            dimension_completeness = completeness,
            quality_score          = quality,
            incident_count         = len(incidents),
            safe_count             = len(safe_calls),
            note                   = note,
        )

    def is_better_than(self, other: "ContractQuality") -> bool:
        """当前合约质量是否优于另一个合约。"""
        return self.quality_score > other.quality_score

    def __str__(self) -> str:
        return (f"ContractQuality(score={self.quality_score:.3f}, "
                f"coverage={self.coverage_rate:.1%}, "
                f"fp={self.false_positive_rate:.1%}, "
                f"dims={self.dimension_completeness:.1%}, "
                f"n={self.incident_count}+{self.safe_count}, "
                f"note={self.note!r})")


# ── v0.9.0: Phase-2 adaptive coefficients ────────────────────────────────────
#
# Design principles:
#   1. Purely deterministic: identical feedback history always produces identical coefficients
#   2. Highly conservative learning: learning rate derived from sample count; barely moves when n<20
#   3. Backward-compatible: derive_objective() retains its original behaviour;
#      new derive_objective_adaptive() accepts AdaptiveCoefficients
#   4. Zero LLM: all updates are arithmetic rules; no model calls
#
# Three-phase adaptation roadmap (overall plan):
#   V08 (completed): fixed prior coefficients; objective derived from statistics
#   V09 (this version): coefficients deterministically updated from RefinementFeedback (phase 2)
#   Future phase 3: confidence intervals tighten; coefficients carry uncertainty estimates;
#                  wide distribution with small samples, narrow with large samples
#
# Core coefficient-update logic (honest engineering note):
#   The learning signal comes from before/after changes in diagnosis:
#     More class-C → previous fp_tolerance was too low (too aggressive) → lower penalty coefficient (raise tolerance)
#     Class-A not decreasing → previous fp_tolerance was too high (not learning) → raise penalty coefficient (lower tolerance)
#   Update step size is controlled by the learning rate, which is smoothly derived from the sample count.

@dataclass
class AdaptiveCoefficients:
    """
    可学习的先验系数（v0.9.0新增）。

    存储 derive_objective() 里的先验常数，允许这些常数
    随 RefinementFeedback 的积累而确定性地更新。

    字段：
        high_severity_pen:  严重度惩罚（初始0.03）
        high_density_pen:   密度惩罚（初始0.02）
        cat_a_bonus:        A类奖励（初始0.02）
        observation_count:  已观测的反馈次数
        total_history_seen: 用于推导的总CallRecord数
        last_update_note:   上次更新的说明

    初始值 = V08的硬编码先验，语义不变。
    当 observation_count 足够大时，系数向数据驱动方向收紧。

    不变量：
        high_severity_pen ∈ [0.005, 0.08]
        high_density_pen  ∈ [0.005, 0.06]
        cat_a_bonus       ∈ [0.005, 0.05]
    """
    high_severity_pen:  float = 0.03   # V08先验基准
    high_density_pen:   float = 0.02   # V08先验基准
    cat_a_bonus:        float = 0.02   # V08先验基准
    observation_count:  int   = 0
    total_history_seen: int   = 0
    last_update_note:   str   = "initialized from V08 priors"

    def learning_rate(self) -> float:
        """
        从观测数推导学习率。

        设计：
          - n=0:   lr=0.0   （无数据，不更新）
          - n=10:  lr=0.01  （开始有信号，极保守）
          - n=50:  lr=0.05  （中等置信度）
          - n=100: lr=0.10  （上限，避免过激更新）

        公式：lr = min(0.10, n / 1000)
        这意味着需要1000次观测才能达到最大学习率，
        确保系数不会因为少量噪声而剧烈偏移。
        """
        return min(0.10, self.observation_count / 1000.0)

    def confidence(self) -> float:
        """
        系数的置信度（0-1）。
        observation_count=0时为0（完全依赖先验），
        observation_count=200时约为0.5，
        observation_count=1000时趋近1.0。
        """
        return 1.0 - 1.0 / (1.0 + self.observation_count / 200.0)

    def __str__(self) -> str:
        lr   = self.learning_rate()
        conf = self.confidence()
        return (
            f"AdaptiveCoefficients("
            f"severity_pen={self.high_severity_pen:.4f}, "
            f"density_pen={self.high_density_pen:.4f}, "
            f"cat_a_bonus={self.cat_a_bonus:.4f}, "
            f"n={self.observation_count}, "
            f"lr={lr:.4f}, conf={conf:.2f})"
        )


@dataclass
class RefinementFeedback:
    """
    一次refinement周期的效果记录（v0.9.0新增）。

    这是 AdaptiveCoefficients 学习的原材料。
    每当系统应用了一次 learn() 的输出（contract_additions），
    并在之后观察到新的调用历史时，应该记录一条 RefinementFeedback。

    字段：
        objective_used:    本次learn()使用的NormativeObjective
        diagnosis_before:  应用refinement之前的四种情况分布
        diagnosis_after:   应用refinement之后的四种情况分布
        history_size:      本次观测的CallRecord数量
        timestamp:         记录时间

    评估逻辑（在 update_coefficients 里使用）：
        good_refinement  = A类比例下降 且 C类比例不显著上升
        over_aggressive  = C类（过度收紧）比例上升
        under_effective  = A类比例未下降（学不到东西）
    """
    objective_used:   NormativeObjective
    diagnosis_before: Dict[str, int]
    diagnosis_after:  Dict[str, int]
    history_size:     int   = 0
    timestamp:        float = field(default_factory=lambda: __import__('time').time())

    def _frac(self, diagnosis: Dict[str, int], key: str) -> float:
        """某类情况占所有记录的比例（以总callrecord数为分母）。"""
        total = max(sum(diagnosis.values()), 1)
        return diagnosis.get(key, 0) / total

    def delta_cat_A(self) -> float:
        """A类情况比例的变化（负值=改善，正值=变差）。"""
        return (self._frac(self.diagnosis_after,  "A_ideal_deficient")
              - self._frac(self.diagnosis_before, "A_ideal_deficient"))

    def delta_cat_C(self) -> float:
        """C类情况（过度收紧）比例的变化（正值=过激）。"""
        total_after  = max(sum(self.diagnosis_after.values()),  1)
        total_before = max(sum(self.diagnosis_before.values()), 1)
        frac_after  = self.diagnosis_after.get( "C_over_tightened", 0) / total_after
        frac_before = self.diagnosis_before.get("C_over_tightened", 0) / total_before
        return frac_after - frac_before

    def is_over_aggressive(self, threshold: float = 0.05) -> bool:
        """本次refinement是否过于激进（C类显著增多）。"""
        return self.delta_cat_C() > threshold

    def is_under_effective(self, threshold: float = -0.05) -> bool:
        """本次refinement是否效果不足（A类没有减少）。"""
        return self.delta_cat_A() >= threshold  # 没有改善（负值才是改善）


def update_coefficients(
    feedback:     RefinementFeedback,
    current:      AdaptiveCoefficients,
) -> AdaptiveCoefficients:
    """
    从一条 RefinementFeedback 确定性更新 AdaptiveCoefficients（v0.9.0核心函数）。

    给定相同的反馈和当前系数，永远返回相同结果。零LLM，纯算术。

    更新规则：
      1. 过激信号（C类增多）→ 说明上次fp_tolerance太低
         → 降低惩罚系数（让tolerance高一点，不那么严格）
         → high_severity_pen *= (1 - lr * 0.1)
         → high_density_pen  *= (1 - lr * 0.1)

      2. 效果不足（A类未减）→ 说明上次fp_tolerance太高
         → 提高惩罚系数（让tolerance低一点，更严格）
         → high_severity_pen *= (1 + lr * 0.05)

      3. 两种信号都没有 → 系数不变（好的状态不要动）

    学习率从 observation_count 推导，n<20时几乎不动。
    所有系数钳制在合理范围内。

    Args:
        feedback: 一次refinement的效果记录
        current:  当前系数

    Returns:
        AdaptiveCoefficients — 更新后的新系数（不修改原对象）
    """
    lr = current.learning_rate()

    new_sev_pen = current.high_severity_pen
    new_den_pen = current.high_density_pen
    new_cat_a   = current.cat_a_bonus
    adjustments: List[str] = []

    # Signal 1: over-aggressive (more class-C violations)
    if feedback.is_over_aggressive():
        delta_C = feedback.delta_cat_C()
        # Lower penalty coefficient: relax slightly when over-aggressive
        factor = 1.0 - lr * min(0.2, delta_C * 2)
        new_sev_pen = current.high_severity_pen * factor
        new_den_pen = current.high_density_pen  * factor
        adjustments.append(
            f"过激信号(ΔC={delta_C:+.3f}): "
            f"sev_pen×{factor:.4f}, den_pen×{factor:.4f}"
        )

    # Signal 2: under-effective (class-A not decreasing)
    if feedback.is_under_effective():
        delta_A = feedback.delta_cat_A()
        # Raise penalty coefficient: tighten slightly when under-effective
        factor = 1.0 + lr * min(0.1, abs(delta_A))
        new_sev_pen = new_sev_pen * factor
        adjustments.append(
            f"效果不足(ΔA={delta_A:+.3f}): sev_pen×{factor:.4f}"
        )

    # Neither signal: current coefficients deemed adequate; no change
    if not adjustments:
        adjustments.append("无调整信号（系数保持）")

    # Clamp to a reasonable range
    new_sev_pen = max(0.005, min(0.08, new_sev_pen))
    new_den_pen = max(0.005, min(0.06, new_den_pen))
    new_cat_a   = max(0.005, min(0.05, new_cat_a))

    note = (
        f"n_obs={current.observation_count+1}, lr={lr:.4f}, "
        f"over_aggressive={feedback.is_over_aggressive()}, "
        f"under_effective={feedback.is_under_effective()}. "
        + "; ".join(adjustments)
    )

    return AdaptiveCoefficients(
        high_severity_pen  = new_sev_pen,
        high_density_pen   = new_den_pen,
        cat_a_bonus        = new_cat_a,
        observation_count  = current.observation_count + 1,
        total_history_seen = current.total_history_seen + feedback.history_size,
        last_update_note   = note,
    )


def derive_objective_adaptive(
    history:      List["CallRecord"],
    coefficients: AdaptiveCoefficients,
) -> NormativeObjective:
    """
    使用自适应系数推导 NormativeObjective（v0.9.0新增）。

    和 derive_objective() 完全相同的推导逻辑，
    区别只在于使用 AdaptiveCoefficients 里的系数
    而不是 derive_objective() 里的硬编码常数。

    这实现了三阶段自适应路径的第二阶段：
      - 先验系数不再是固定的
      - 它们随 RefinementFeedback 的积累而更新
      - 当 confidence() 低时，系数接近V08先验
      - 当 confidence() 高时，系数反映数据规律

    Args:
        history:      CallRecord列表
        coefficients: 当前自适应系数

    Returns:
        NormativeObjective（derivation_note中会标注系数来源）
    """
    n = len(history)
    if n == 0:
        return NormativeObjective(
            fp_tolerance    = 0.05,
            derived         = True,
            derivation_note = f"空历史，使用基准值0.05 (adaptive, {coefficients})",
            sample_size     = 0,
        )

    incidents  = [r for r in history if r.violations]
    safe_calls = [r for r in history if not r.violations]

    violation_density = len(incidents) / n
    safe_call_density = len(safe_calls) / n

    all_severities = [v.severity for r in incidents for v in r.violations]
    mean_severity  = (sum(all_severities) / len(all_severities)
                      if all_severities else 0.5)

    cat_counts: Dict[str, int] = {}
    for r in history:
        cat = r.violation_category()
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    n_viol     = len(incidents)
    cat_A_frac = cat_counts.get("A_ideal_deficient", 0) / n_viol if n_viol else 0.0

    # ── Use adaptive coefficients (key difference) ───────────────────────────
    BASE = 0.05
    fp_tolerance = BASE
    adjustments: List[str] = []

    if mean_severity > 0.8:
        fp_tolerance -= coefficients.high_severity_pen
        adjustments.append(
            f"高严重度({mean_severity:.2f})"
            f":-{coefficients.high_severity_pen:.4f}"
            f"[conf={coefficients.confidence():.2f}]"
        )
    if violation_density > 0.3:
        fp_tolerance -= coefficients.high_density_pen
        adjustments.append(
            f"高违规密度({violation_density:.0%})"
            f":-{coefficients.high_density_pen:.4f}"
        )
    if cat_A_frac > 0.7:
        fp_tolerance += coefficients.cat_a_bonus
        adjustments.append(
            f"A类为主({cat_A_frac:.0%})"
            f":+{coefficients.cat_a_bonus:.4f}"
        )

    if n < 10:
        blend        = n / 10.0
        fp_tolerance = BASE * (1 - blend) + fp_tolerance * blend
        adjustments.append(f"小样本({n}):混合{blend:.0%}")

    fp_tolerance = max(0.005, min(0.15, fp_tolerance))

    raw_sev  = min(0.6, max(0.2, mean_severity))
    raw_prec = min(0.6, max(0.2, safe_call_density))
    raw_cov  = 0.2
    raw_sum  = raw_sev + raw_prec + raw_cov

    note = (
        f"[adaptive n_obs={coefficients.observation_count}] "
        f"n={n}, viol={len(incidents)}, safe={len(safe_calls)}, "
        f"density={violation_density:.0%}, severity={mean_severity:.2f}. "
        f"base={BASE}"
        + ((" adj:[" + ", ".join(adjustments) + "]") if adjustments else " (无调整)")
        + f" → fp_tol={fp_tolerance:.3f}"
    )

    return NormativeObjective(
        fp_tolerance     = fp_tolerance,
        severity_weight  = raw_sev  / raw_sum,
        precision_weight = raw_prec / raw_sum,
        coverage_weight  = raw_cov  / raw_sum,
        derived          = True,
        derivation_note  = note,
        sample_size      = n,
    )



# 模块级导出，供测试和外部校验使用
_DERIVE_BASE              = 0.030000  # v6.0 10360条
    

def derive_objective(history: List["CallRecord"]) -> NormativeObjective:
    """
    从CIEU历史确定性推导 NormativeObjective（v0.8.0核心函数）。

    给定相同的 history，永远返回相同结果。零LLM，纯算术。

    推导步骤：
      1. violation_density  = 违规次数 / 总次数
      2. mean_severity      = 所有违规的平均严重度
      3. cat_A_fraction     = A类情况（理想合约缺陷）占违规比
      4. safe_call_density  = 安全调用 / 总次数
      5. fp_tolerance 从上述量推导，钳制到 [0.005, 0.15]
      6. 三个评分权重从 mean_severity 和 safe_call_density 推导

    先验系数（固定）：
      BASE=0.05, HIGH_SEVERITY_PEN=0.03, HIGH_DENSITY_PEN=0.02, CAT_A_BONUS=0.02
    """
    n = len(history)
    if n == 0:
        return NormativeObjective(
            fp_tolerance    = 0.05,
            derived         = True,
            derivation_note = "空历史，使用基准值 0.05",
            sample_size     = 0,
        )

    incidents  = [r for r in history if r.violations]
    safe_calls = [r for r in history if not r.violations]

    violation_density = len(incidents) / n
    safe_call_density = len(safe_calls) / n

    all_severities = [v.severity for r in incidents for v in r.violations]
    mean_severity  = (sum(all_severities) / len(all_severities)
                      if all_severities else 0.5)

    cat_counts: Dict[str, int] = {}
    for r in history:
        cat = r.violation_category()
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    n_viol       = len(incidents)
    cat_A_frac   = cat_counts.get("A_ideal_deficient", 0) / n_viol if n_viol else 0.0

    # ── fp_tolerance derivation ───────────────────────────────────────────────
    # 先验常量经 MITRE ATLAS v4.5 预训练更新（566条样本，2026-03）
    # 预训练前: BASE=0.0500  预训练后: BASE=0.0300
    BASE              = 0.0300
    HIGH_SEVERITY_PEN = 0.03
    HIGH_DENSITY_PEN  = 0.02
    CAT_A_BONUS       = 0.02

    fp_tolerance = BASE
    adjustments: List[str] = []

    if mean_severity > 0.8:
        fp_tolerance -= HIGH_SEVERITY_PEN
        adjustments.append(f"高严重度({mean_severity:.2f}):-{HIGH_SEVERITY_PEN}")
    if violation_density > 0.3:
        fp_tolerance -= HIGH_DENSITY_PEN
        adjustments.append(f"高违规密度({violation_density:.0%}):-{HIGH_DENSITY_PEN}")
    if cat_A_frac > 0.7:
        fp_tolerance += CAT_A_BONUS
        adjustments.append(f"A类为主({cat_A_frac:.0%}):+{CAT_A_BONUS}")

    # Small-sample conservatism (blend toward baseline when n<10)
    if n < 10:
        blend        = n / 10.0
        fp_tolerance = BASE * (1 - blend) + fp_tolerance * blend
        adjustments.append(f"小样本({n}):混合{blend:.0%}")

    fp_tolerance = max(0.005, min(0.15, fp_tolerance))

    # ── Derivation of the three weights ──────────────────────────────────────
    raw_sev  = min(0.6, max(0.2, mean_severity))
    raw_prec = min(0.6, max(0.2, safe_call_density))
    raw_cov  = 0.2
    raw_sum  = raw_sev + raw_prec + raw_cov

    note = (
        f"n={n}, viol={len(incidents)}, safe={len(safe_calls)}, "
        f"density={violation_density:.0%}, severity={mean_severity:.2f}, "
        f"cat_A={cat_A_frac:.0%}. base={BASE}"
        + ((" adj:[" + ", ".join(adjustments) + "]") if adjustments else " (无调整)")
        + f" → fp_tol={fp_tolerance:.3f}"
    )

    return NormativeObjective(
        fp_tolerance    = fp_tolerance,
        severity_weight = raw_sev  / raw_sum,
        precision_weight= raw_prec / raw_sum,
        coverage_weight = raw_cov  / raw_sum,
        derived         = True,
        derivation_note = note,
        sample_size     = n,
    )


def score_candidate(
    candidate:  "CandidateRule",
    incidents:  List["CallRecord"],
    safe_calls: List["CallRecord"],
    objective:  NormativeObjective,
) -> float:
    """
    多维候选规则评分（v0.8.0新增）。

    替代原来的二值通过/不通过，给每个候选一个连续质量分。

    评分公式：
      score = severity_weight  × mean_prevented_severity
            + precision_weight × (1 - fp_rate)
            + coverage_weight  × coverage_rate
            + alignment_bonus  （对齐正确层时 +0.05）

    alignment_bonus：
      A类违规 + intent层候选 → +0.05
      B类违规 + applied层候选 → +0.05
    """
    test_contract = _candidate_to_contract(candidate)
    if test_contract is None:
        return 0.0

    func_incidents  = [r for r in incidents  if r.func_name == candidate.func_name]
    func_safe_calls = [r for r in safe_calls if r.func_name == candidate.func_name]

    fp_count = sum(
        1 for r in func_safe_calls
        if not check(r.params, r.result, test_contract).passed
    )
    fp_rate = fp_count / len(func_safe_calls) if func_safe_calls else 0.0
    candidate.fp_rate = fp_rate

    prevented = [
        r for r in func_incidents
        if not check(r.params, r.result, test_contract).passed
    ]
    coverage_rate = len(prevented) / len(func_incidents) if func_incidents else 0.0

    prevented_sevs = [v.severity for r in prevented for v in r.violations]
    mean_sev = sum(prevented_sevs) / len(prevented_sevs) if prevented_sevs else 0.0

    alignment_bonus = 0.0
    if (candidate.violation_category == "A_ideal_deficient"
            and candidate.target_layer == "intent"):
        alignment_bonus = 0.05
    elif (candidate.violation_category == "B_execution_drift"
            and candidate.target_layer == "applied"):
        alignment_bonus = 0.05

    return (objective.severity_weight  * mean_sev
          + objective.precision_weight * (1.0 - fp_rate)
          + objective.coverage_weight  * coverage_rate
          + alignment_bonus)


# ── Core algorithm ────────────────────────────────────────────────────────────

def learn(
    history:       List[CallRecord],
    base_contract: Optional[IntentContract] = None,
    max_fp_rate:   Optional[float] = None,
    objective:     Optional[NormativeObjective] = None,
) -> MetalearnResult:
    """
    Run causal metalearning on a call history.

    v0.3.0: 覆盖全部8个维度 + DimensionDiscovery。
    v0.7.0: 使用完整CIEU五元组，四种情况分析，系统状态驱动根因追踪。
    v0.8.0: 目标函数内部推导。objective参数替代max_fp_rate，
            候选评分从二值改为多维连续评分。

    Args:
        history:       list of CallRecord in chronological order
        base_contract: existing contract (to check for false positives)
        max_fp_rate:   [向后兼容] 外部指定的误报率上限。
                       None（默认）= 从CIEU历史自动推导（v0.8新行为）。
                       传入数值 = 使用该值，等价于旧接口行为。
        objective:     [v0.8新增] 显式传入 NormativeObjective。
                       优先级：objective > max_fp_rate > 自动推导。

    Returns:
        MetalearnResult with suggested contract additions, CIEU diagnosis,
        and objective/quality metadata.
    """
    # ── v0.8: objective resolution (priority: explicit objective > max_fp_rate > auto-derive)
    if objective is not None:
        # Explicitly supplied; use directly
        _objective = objective
    elif max_fp_rate is not None:
        # Backward compatibility: build objective from legacy max_fp_rate parameter
        _objective = NormativeObjective(
            fp_tolerance    = max_fp_rate,
            derived         = False,
            derivation_note = f"外部参数 max_fp_rate={max_fp_rate}",
            sample_size     = len(history),
        )
    else:
        # v0.8 new behaviour: auto-derive from CIEU history
        _objective = derive_objective(history)

    # Step 1: Abduction — find terminal violations
    incidents = [r for r in history if r.violations]

    if not incidents:
        return MetalearnResult(
            incidents=[], candidates=[], minimum_cover=[],
            contract_additions=IntentContract(),
            dimension_hints=[],
            objective=_objective,
        )

    # Step 2: Root trace — keyed by (func_name, dimension, env)
    #
    # v0.7.0 upgrade: add the system_state environment dimension alongside (func_name, dimension).
    # The same type of violation in different environments (staging vs production) often has a different
    # root cause and should not be grouped under the same one.
    # Use the "env" field from system_state as the discrimination key (absent → "unknown").
    root_map: Dict[Tuple[str, str, str], int] = {}

    for incident in incidents:
        env = incident.system_state.get("env", "unknown")
        for v in incident.violations:
            key = (incident.func_name, v.dimension, env)
            if key not in root_map:
                earliest = incident.seq
                for earlier in history:
                    if earlier.seq >= incident.seq:
                        break
                    if earlier.func_name != incident.func_name:
                        continue
                    # Only group as the same root-cause chain when the environment matches
                    earlier_env = earlier.system_state.get("env", "unknown")
                    if earlier_env != env:
                        continue
                    if any(ev.dimension == v.dimension for ev in earlier.violations):
                        earliest = earlier.seq
                        break
                root_map[key] = earliest

    # Step 3: Intervention
    candidates: List[CandidateRule] = []
    seen_constraints: set = set()

    for incident in incidents:
        for violation in incident.violations:
            env      = incident.system_state.get("env", "unknown")
            root_seq = root_map.get(
                (incident.func_name, violation.dimension, env), incident.seq)
            candidate = _violation_to_candidate(violation, incident, root_seq)
            if candidate:
                key = (candidate.func_name, candidate.dimension, str(candidate.value))
                if key not in seen_constraints:
                    seen_constraints.add(key)
                    candidates.append(candidate)

    # Step 4: Counterfactual replay + multi-dimensional scoring (v0.8 upgrade)
    #
    # v0.7 and earlier: binary judgement (prevents AND fp_rate <= threshold)
    # v0.8: score_candidate() multi-dimensional scoring; sort by score, filter by fp_tolerance
    safe_calls = [r for r in history if not r.violations]
    scored_candidates: List[Tuple[float, "CandidateRule"]] = []

    for candidate in candidates:
        test_contract = _candidate_to_contract(candidate)
        if test_contract is None:
            continue

        # Check that it prevents at least one violation (retain this basic requirement)
        prevents = any(
            not check(r.params, r.result, test_contract).passed
            for r in incidents
            if r.func_name == candidate.func_name
        )
        if not prevents:
            continue

        # Multi-dimensional scoring (also computes and sets candidate.fp_rate)
        s = score_candidate(candidate, incidents, safe_calls, _objective)

        # fp_tolerance filter (use the derived objective, not the legacy fixed parameter)
        if candidate.fp_rate <= _objective.fp_tolerance:
            incident_seqs = [i.seq for i in incidents
                             if i.func_name == candidate.func_name]
            candidate.causal_proof = (
                f"Counterfactual: prevents violations at step(s) "
                f"{incident_seqs} — root cause at step #{candidate.root_seq}, "
                f"FP rate {candidate.fp_rate:.1%}, score={s:.3f} "
                f"[fp_tol={_objective.fp_tolerance:.3f}, "
                f"{'derived' if _objective.derived else 'external'}]"
            )
            scored_candidates.append((s, candidate))

    # Sort by score descending (high-score candidates enter minimum cover first)
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    verified_candidates = [c for _, c in scored_candidates]

    # Step 5: Minimum cover
    minimum_cover = _greedy_minimum_cover(verified_candidates, incidents)

    # Step 6: Build contract additions
    additions = _candidates_to_contract(minimum_cover)

    # Step 7: Dimension discovery (added)
    hints = DimensionDiscovery.analyze(history)

    # Step 8: CIEU diagnostic statistics (v0.7 added)
    diagnosis: Dict[str, int] = {
        "A_ideal_deficient": 0,
        "B_execution_drift":  0,
        "C_over_tightened":   0,
        "D_normal":           0,
        "unknown":            0,
    }
    for r in history:
        cat = r.violation_category()
        diagnosis[cat] = diagnosis.get(cat, 0) + 1

    # Step 9: v0.8 — contract quality self-assessment
    quality = ContractQuality.evaluate(additions, history) if not additions.is_empty() else None

    return MetalearnResult(
        incidents=incidents,
        candidates=verified_candidates,
        minimum_cover=minimum_cover,
        contract_additions=additions,
        dimension_hints=hints,
        diagnosis=diagnosis,
        objective=_objective,
        quality=quality,
    )


# ── Violation → Candidate (fix: covers all 8 dimensions) ────────────────────

def _violation_to_candidate(
    violation: Violation,
    incident:  CallRecord,
    root_seq:  int,
) -> Optional[CandidateRule]:
    """
    Convert a violation into a candidate constraint rule.
    v0.3.0: 覆盖全部8个维度。
    v0.7.0: 加入四种情况分析，candidate记录来自哪类情况、应该收紧哪一层。
    """
    dim    = violation.dimension
    actual = violation.actual

    # v0.7: determine which CIEU situation the violation came from
    cat          = incident.violation_category()
    target_layer = "intent" if cat in ("A_ideal_deficient", "unknown") else "applied"
    # Class A: ideal contract is deficient → tighten intent_contract (y*_t)
    # Class B: execution layer deviated → tighten applied_contract
    # unknown: insufficient information → default to tightening intent (conservative)

    # ── 1. deny ──────────────────────────────────────────────────────────────
    # v0.11: prefer violation.actual (structured); fall back to message regex
    if dim == "deny":
        pattern = None
        if violation.actual and isinstance(violation.actual, str):
            stripped = violation.actual.strip("'")
            if stripped:
                pattern = stripped
        if not pattern:
            m = re.search(r"'([^']+)'", violation.message)
            if m:
                pattern = m.group(1)
        if pattern:
            return CandidateRule(
                id=f"block_{incident.func_name}_{violation.field}_{pattern[:20]}",
                description=violation.message or f"Deny '{pattern}' in {incident.func_name}",
                func_name=incident.func_name,
                dimension="deny",
                value=pattern,
                root_seq=root_seq,
                incident_seq=incident.seq,
                violation_category=cat,
                target_layer=target_layer,
            )

    # ── 2. deny_commands ─────────────────────────────────────────────────────
    elif dim == "deny_commands":
        if isinstance(actual, str):
            cmd = actual.split()[0] if actual.split() else actual
            return CandidateRule(
                id=f"block_{incident.func_name}_cmd_{cmd[:20]}",
                description=f"Block command '{actual}' in {incident.func_name}",
                func_name=incident.func_name,
                dimension="deny_commands",
                value=actual[:50],
                root_seq=root_seq,
                incident_seq=incident.seq,
                violation_category=cat,
                target_layer=target_layer,
            )

    # ── 3. invariant ─────────────────────────────────────────────────────────
    # v0.11: prefer constraint field (format: "invariant: expr")
    elif dim == "invariant":
        expr = None
        raw = (violation.constraint or "").strip()
        prefix = "invariant:"
        if raw.lower().startswith(prefix):
            expr = raw[len(prefix):].strip().strip("'")
        if not expr:
            m = re.search(r"Invariant violated: '([^']+)'", violation.message)
            if m:
                expr = m.group(1)
        if not expr:
            m2 = re.search(r"'([^']+)'", violation.message)
            if m2:
                expr = m2.group(1)
        if expr:
            return CandidateRule(
                id=f"invariant_{incident.func_name}_{expr[:20]}",
                description=f"Enforce invariant '{expr}' in {incident.func_name}",
                func_name=incident.func_name,
                dimension="invariant",
                value=expr,
                root_seq=root_seq,
                incident_seq=incident.seq,
                violation_category=cat,
                target_layer=target_layer,
            )

    # ── 3b. optional_invariant ───────────────────────────────────────────────
    elif dim == "optional_invariant":
        expr = None
        raw = (violation.constraint or "").strip()
        if raw.lower().startswith("optional_invariant:"):
            expr = raw[len("optional_invariant:"):].strip().strip("'")
        if not expr:
            m = re.search(r"Optional invariant violated: '([^']+)'", violation.message)
            if m:
                expr = m.group(1)
        if not expr and violation.actual and isinstance(violation.actual, dict):
            pass  # actual is params dict, not the expr — use message fallback
        if not expr:
            m2 = re.search(r"'([^']+)'", violation.message)
            if m2:
                expr = m2.group(1)
        if expr:
            return CandidateRule(
                id          = f"opt_inv_{incident.func_name}_{expr[:20]}",
                description = f"Enforce optional invariant '{expr}' in {incident.func_name}",
                func_name   = incident.func_name,
                dimension   = "optional_invariant",
                value       = expr,
                root_seq    = root_seq,
                incident_seq= incident.seq,
                violation_category=cat,
                target_layer=target_layer,
            )

    # ── 4. only_paths (fix: was previously a no-op) ──────────────────────────
    elif dim == "only_paths":
        # A path violation cannot directly generate a new only_paths whitelist entry
        # (the violation indicates the path should not have been permitted).
        # However, the violating path can be added to deny to prevent recurrence.
        if isinstance(actual, str):
            return CandidateRule(
                id=f"block_{incident.func_name}_path_{actual[:20]}",
                description=f"Deny path '{actual}' in {incident.func_name}",
                func_name=incident.func_name,
                dimension="deny",
                value=actual,
                root_seq=root_seq,
                incident_seq=incident.seq,
            )

    # ── 5. only_domains ──────────────────────────────────────────────────────
    elif dim == "only_domains":
        if isinstance(actual, str):
            return CandidateRule(
                id=f"block_{incident.func_name}_domain_{actual[:20]}",
                description=f"Block domain '{actual}' in {incident.func_name}",
                func_name=incident.func_name,
                dimension="deny",
                value=actual,
                root_seq=root_seq,
                incident_seq=incident.seq,
            )

    # ── 6. postcondition (added) ─────────────────────────────────────────────
    elif dim == "postcondition":
        # v0.11: prefer the constraint field
        expr = None
        raw = (violation.constraint or "").strip()
        if raw.lower().startswith("postcondition:"):
            expr = raw[len("postcondition:"):].strip().strip("'\"")
        if not expr:
            m2 = re.search(r"Postcondition violated: '([^']+)'", violation.message)
            if m2:
                expr = m2.group(1)
        if expr:
            return CandidateRule(
                id=f"postcond_{incident.func_name}_{expr[:20]}",
                description=f"Enforce postcondition '{expr}' in {incident.func_name}",
                func_name=incident.func_name,
                dimension="postcondition",
                value=expr,
                root_seq=root_seq,
                incident_seq=incident.seq,
                violation_category=cat,
                target_layer=target_layer,
            )

    # ── 7. field_deny (added) ────────────────────────────────────────────────
    elif dim == "field_deny":
        m = re.search(r"Value '([^']+)' is blocked in field '([^']+)'",
                      violation.message)
        if m:
            blocked_val = m.group(1)
            field_name  = m.group(2)
            return CandidateRule(
                id=f"fielddeny_{incident.func_name}_{field_name}_{blocked_val[:15]}",
                description=violation.message,
                func_name=incident.func_name,
                dimension="field_deny",
                value={"field": field_name, "blocked": blocked_val},
                root_seq=root_seq,
                incident_seq=incident.seq,
            )

    # ── 8. value_range (added) ───────────────────────────────────────────────
    elif dim == "value_range":
        # Extract parameter name and out-of-bounds direction from the violation message
        m_min = re.search(r"(\w+)=([0-9.\-]+) is below minimum ([0-9.\-]+)",
                          violation.message)
        m_max = re.search(r"(\w+)=([0-9.\-]+) exceeds maximum ([0-9.\-]+)",
                          violation.message)
        if m_min:
            param = m_min.group(1)
            # Suggest tightening the minimum bound to the current actual value + buffer
            current_val = float(m_min.group(2))
            current_min = float(m_min.group(3))
            return CandidateRule(
                id=f"range_{incident.func_name}_{param}_min",
                description=f"Tighten min bound for {param} in {incident.func_name}",
                func_name=incident.func_name,
                dimension="value_range",
                value={"param": param, "min": max(current_min, 0)},
                root_seq=root_seq,
                incident_seq=incident.seq,
            )
        if m_max:
            param = m_max.group(1)
            current_val = float(m_max.group(2))
            current_max = float(m_max.group(3))
            return CandidateRule(
                id=f"range_{incident.func_name}_{param}_max",
                description=f"Tighten max bound for {param} in {incident.func_name}",
                func_name=incident.func_name,
                dimension="value_range",
                value={"param": param, "max": current_max},
                root_seq=root_seq,
                incident_seq=incident.seq,
            )

    return None


def _candidate_to_contract(candidate: CandidateRule) -> Optional[IntentContract]:
    """Build a minimal IntentContract from a single candidate rule."""
    if candidate.dimension == "deny":
        return IntentContract(deny=[str(candidate.value)])
    elif candidate.dimension == "deny_commands":
        return IntentContract(deny_commands=[str(candidate.value)])
    elif candidate.dimension == "invariant":
        return IntentContract(invariant=[str(candidate.value)])
    elif candidate.dimension == "optional_invariant":
        return IntentContract(optional_invariant=[str(candidate.value)])
    elif candidate.dimension == "only_domains":
        return IntentContract(only_domains=[str(candidate.value)])
    elif candidate.dimension == "postcondition":
        return IntentContract(postcondition=[str(candidate.value)])
    elif candidate.dimension == "field_deny":
        v = candidate.value
        if isinstance(v, dict):
            return IntentContract(field_deny={v["field"]: [v["blocked"]]})
    elif candidate.dimension == "value_range":
        v = candidate.value
        if isinstance(v, dict) and "param" in v:
            bounds = {k: val for k, val in v.items() if k != "param"}
            return IntentContract(value_range={v["param"]: bounds})
    return None


def _greedy_minimum_cover(
    candidates: List[CandidateRule],
    incidents:  List[CallRecord],
) -> List[CandidateRule]:
    """Greedy set cover: minimum rules that cover all incidents."""
    incident_seqs = {i.seq for i in incidents}
    covered = set()
    selected = []

    def coverage_count(c: CandidateRule) -> int:
        test = _candidate_to_contract(c)
        if not test:
            return 0
        return sum(
            1 for incident in incidents
            if incident.func_name == c.func_name
            and not check(incident.params, incident.result, test).passed
        )

    for candidate in sorted(candidates, key=coverage_count, reverse=True):
        test = _candidate_to_contract(candidate)
        if not test:
            continue
        newly_covered = {
            incident.seq for incident in incidents
            if incident.func_name == candidate.func_name
            and incident.seq not in covered
            and not check(incident.params, incident.result, test).passed
        }
        if newly_covered:
            covered |= newly_covered
            selected.append(candidate)
        if covered >= incident_seqs:
            break

    return selected


def _candidates_to_contract(candidates: List[CandidateRule]) -> IntentContract:
    """
    Merge multiple candidate rules into a single IntentContract.
    v0.3.0: 覆盖全部8个维度。
    """
    deny:          List[str]            = []
    deny_commands: List[str]            = []
    invariant:     List[str]            = []
    only_domains:  List[str]            = []
    postcondition: List[str]            = []
    field_deny:    Dict[str, List[str]] = {}
    value_range:   Dict[str, Dict]      = {}

    for c in candidates:
        if c.dimension == "deny":
            if str(c.value) not in deny:
                deny.append(str(c.value))
        elif c.dimension == "deny_commands":
            if str(c.value) not in deny_commands:
                deny_commands.append(str(c.value))
        elif c.dimension == "invariant":
            if str(c.value) not in invariant:
                invariant.append(str(c.value))
        elif c.dimension == "only_domains":
            if str(c.value) not in only_domains:
                only_domains.append(str(c.value))
        elif c.dimension == "postcondition":
            if str(c.value) not in postcondition:
                postcondition.append(str(c.value))
        elif c.dimension == "field_deny":
            v = c.value
            if isinstance(v, dict):
                f, b = v["field"], v["blocked"]
                if f not in field_deny:
                    field_deny[f] = []
                if b not in field_deny[f]:
                    field_deny[f].append(b)
        elif c.dimension == "value_range":
            v = c.value
            if isinstance(v, dict) and "param" in v:
                p = v["param"]
                bounds = {k: val for k, val in v.items() if k != "param"}
                if p not in value_range:
                    value_range[p] = bounds
                else:
                    value_range[p].update(bounds)

    return IntentContract(
        deny=deny, deny_commands=deny_commands,
        invariant=invariant, only_domains=only_domains,
        postcondition=postcondition,
        field_deny=field_deny, value_range=value_range,
    )


# ── Dimension Discovery (added) ─────────────────────────────────────────────

class DimensionDiscovery:
    """
    识别现有8个基础维度无法表达的违规模式，
    提议引入高阶维度（temporal/aggregate/context/resource）。

    这是翻译层自我进化的起点：
    不只是在已知维度内填充新值，而是识别"需要新维度"的信号。
    """

    @staticmethod
    def analyze(history: List[CallRecord]) -> List[str]:
        """
        分析调用历史，返回维度建议列表。
        每条建议是人类可读的字符串，描述观察到的模式和建议的高阶维度。
        """
        hints = []

        # Group by function
        by_func: Dict[str, List[CallRecord]] = defaultdict(list)
        for r in history:
            by_func[r.func_name].append(r)

        for func_name, records in by_func.items():
            incidents = [r for r in records if r.violations]
            if not incidents:
                continue

            # Signal 1: repeated violations of the same function in a short window → may need a temporal constraint
            if len(incidents) >= 2 and any(r.timestamp > 0 for r in incidents):
                ts_list = sorted(r.timestamp for r in incidents if r.timestamp > 0)
                if len(ts_list) >= 2:
                    intervals = [ts_list[i+1] - ts_list[i]
                                 for i in range(len(ts_list)-1)]
                    avg_interval = sum(intervals) / len(intervals)
                    if avg_interval < 60:  # 平均间隔不到1分钟
                        hints.append(
                            f"[temporal] '{func_name}': {len(incidents)} violations "
                            f"in rapid succession (avg {avg_interval:.1f}s apart). "
                            f"Consider rate limiting."
                        )

            # Signal 2: numeric parameter consistently accumulates during violations → may need an aggregate constraint
            numeric_params: Dict[str, List[float]] = defaultdict(list)
            for r in incidents:
                for k, v in r.params.items():
                    try:
                        numeric_params[k].append(float(v))
                    except (TypeError, ValueError):
                        # Value is not numeric — skip
                        pass
            for param, values in numeric_params.items():
                if len(values) >= 2:
                    total = sum(values)
                    hints.append(
                        f"[aggregate] '{func_name}.{param}': sum of violating calls "
                        f"= {total:.1f}. Consider aggregate max_sum constraint."
                    )

            # Signal 3: caller_ctx contains env/role fields and env is production during violations → context constraint
            for r in incidents:
                ctx = r.caller_ctx
                if ctx.get("env") in ("production", "prod", "live"):
                    hints.append(
                        f"[context] '{func_name}': violation occurred in "
                        f"env='{ctx.get('env')}'. Consider deny_env constraint."
                    )
                    break

            # Signal 4: violation dimension is type_safety → may need stricter type constraints
            type_violations = [
                v for r in incidents
                for v in r.violations
                if v.dimension == "type_safety"
            ]
            if type_violations:
                hints.append(
                    f"[type_safety] '{func_name}': {len(type_violations)} "
                    f"non-primitive parameter violations. "
                    f"Consider stricter input validation at call site."
                )

        return hints

# ── v0.10.0: Adaptive closed-loop workflow interface ─────────────────────────
#
# Problem: AdaptiveCoefficients, RefinementFeedback, update_coefficients, and
#          derive_objective_adaptive all exist as building blocks, but users do not know
#          when to call which, and there is no standard pattern that connects the output
#          of one learn() call to the input of the next.
#
# YStarLoop solves this: it is a standard "record → tighten → adapt" closed-loop container.
# Users only need to call record() and tighten(); the adaptive coefficients and feedback
# records are maintained internally.
#
# Design principles:
#   1. Zero hidden state: all state fields are public and can be inspected at any time
#   2. Serialisable: all fields are standard Python types and can be persisted
#   3. Optional: users may call the underlying functions directly; YStarLoop is a convenience wrapper only

class YStarLoop:
    """
    自适应闭环工作流接口（v0.10.0新增）。

    把 record → tighten → feedback → adapt 组装成标准使用模式。
    解决了零件存在但使用方式不清晰的问题。

    用法：
        loop = YStarLoop()

        # Record call history
        loop.record(CallRecord(seq=0, func_name="deploy", ...))

        # Run one tightening cycle
        result = loop.tighten()
        print(result.contract_additions)
        print(result.explain_diagnosis())

        # After applying contract_additions to the actual code, continue recording history...
        # On the next tighten() call, the coefficients are automatically adjusted based on the last cycle's effectiveness.

    状态字段（全部公开可检查）：
        coefficients:    当前自适应系数
        history:         完整调用记录
        last_diagnosis:  上次 tighten() 的 diagnosis
        last_result:     上次 tighten() 的 MetalearnResult
        cycle_count:     已完成的收紧周期数
    """

    def __init__(
        self,
        initial_coefficients: Optional[AdaptiveCoefficients] = None,
        base_contract:        Optional[IntentContract]        = None,
    ):
        """
        Args:
            initial_coefficients: 初始系数（None = V08先验）
            base_contract:        现有合约（用于FP率计算）
        """
        self.coefficients:    AdaptiveCoefficients   = (
            initial_coefficients if initial_coefficients is not None
            else AdaptiveCoefficients()
        )
        self.base_contract:   Optional[IntentContract] = base_contract
        self.history:         List[CallRecord]          = []
        self.last_diagnosis:  Dict[str, int]            = {}
        self.last_result:     Optional[MetalearnResult] = None
        self.cycle_count:     int                       = 0

    def record(self, record: CallRecord) -> None:
        """
        记录一次函数调用。

        Args:
            record: CallRecord（包含params/result/violations，
                    ideally也包含intent_contract和system_state）
        """
        self.history.append(record)

    def record_many(self, records: List[CallRecord]) -> None:
        """批量记录调用历史。"""
        self.history.extend(records)

    def tighten(self) -> MetalearnResult:
        """
        运行一次收紧周期。

        步骤：
          1. 从当前历史和自适应系数推导 NormativeObjective
          2. 运行 learn()，得到 MetalearnResult
          3. 如果有上次的 diagnosis，记录反馈并更新系数
          4. 更新 last_diagnosis、last_result、cycle_count

        Returns:
            MetalearnResult — 包含 contract_additions、diagnosis、
                             objective、quality

        注意：
            tighten() 不自动应用 contract_additions，用户需要手动把
            result.contract_additions 集成到实际的函数装饰器中。
            这是刻意的设计：Y* 是翻译层，执行决策属于用户。
        """
        # Step 1: Derive the objective function (using adaptive coefficients)
        objective = derive_objective_adaptive(self.history, self.coefficients)

        # Step 2: Run learn()
        result = learn(
            self.history,
            base_contract = self.base_contract,
            objective     = objective,
        )

        # Step 3: Record feedback and update coefficients (requires the previous diagnosis as "before")
        if self.last_diagnosis:
            feedback = RefinementFeedback(
                objective_used   = objective,
                diagnosis_before = dict(self.last_diagnosis),
                diagnosis_after  = dict(result.diagnosis),
                history_size     = len(self.history),
            )
            self.coefficients = update_coefficients(feedback, self.coefficients)

        # Step 4: Update state
        self.last_diagnosis = dict(result.diagnosis)
        self.last_result    = result
        self.cycle_count   += 1

        return result

    def status(self) -> str:
        """
        当前循环状态的人类可读摘要。
        """
        lines = [
            f"YStarLoop 状态:",
            f"  周期数:     {self.cycle_count}",
            f"  历史记录:   {len(self.history)} 条",
            f"  系数:       {self.coefficients}",
        ]
        if self.last_result:
            lines.append(f"  上次收紧:   {self.last_result.contract_additions}")
            if self.last_result.quality:
                lines.append(f"  合约质量:   {self.last_result.quality}")
        if self.last_diagnosis:
            diag_summary = ", ".join(
                f"{k.split('_')[0]}={v}"
                for k, v in self.last_diagnosis.items()
                if v > 0
            )
            lines.append(f"  诊断分布:   {diag_summary}")
        return "\n".join(lines)

    def reset_history(self) -> None:
        """
        清空调用历史（保留系数）。
        适用于：滑动窗口模式，只保留最近N条记录的场景。
        """
        self.history.clear()
        self.last_diagnosis = {}

    def snapshot(self) -> Dict[str, Any]:
        """
        导出当前状态快照（用于持久化）。

        Returns:
            dict — 包含 coefficients 字段值和 cycle_count
        """
        from dataclasses import asdict
        return {
            "coefficients": {
                "high_severity_pen":  self.coefficients.high_severity_pen,
                "high_density_pen":   self.coefficients.high_density_pen,
                "cat_a_bonus":        self.coefficients.cat_a_bonus,
                "observation_count":  self.coefficients.observation_count,
                "total_history_seen": self.coefficients.total_history_seen,
            },
            "cycle_count":   self.cycle_count,
            "history_size":  len(self.history),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> "YStarLoop":
        """从快照恢复状态（不包含 history，需要重新加载）。"""
        coeffs_data = snapshot.get("coefficients", {})
        coeffs = AdaptiveCoefficients(
            high_severity_pen  = coeffs_data.get("high_severity_pen",  0.03),
            high_density_pen   = coeffs_data.get("high_density_pen",   0.02),
            cat_a_bonus        = coeffs_data.get("cat_a_bonus",        0.02),
            observation_count  = coeffs_data.get("observation_count",  0),
            total_history_seen = coeffs_data.get("total_history_seen", 0),
        )
        loop = cls(initial_coefficients=coeffs)
        loop.cycle_count = snapshot.get("cycle_count", 0)
        return loop



# ── Convenience: learn from JSONL ledger ─────────────────────────────────────

def learn_from_jsonl(
    path:        str,
    func_name:   str   = "",
    max_fp_rate: float = 0.05,
) -> MetalearnResult:
    """
    Load call history from a JSONL file and run metalearning.

    Supports both ystar native format and K9Audit CIEU format.

    Args:
        path:        path to JSONL history file
        func_name:   filter to specific function (empty = all functions)
        max_fp_rate: maximum acceptable false positive rate

    Returns:
        MetalearnResult
    """
    from ystar.kernel.engine import Violation as V

    records: List[CallRecord] = []
    seq = 0

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as e:
                _log.debug(f"Could not parse JSONL line: {e}")
                continue

            # Support K9Audit CIEU format
            # Support K9Audit CIEU format
            u_t   = rec.get("U_t", {})
            r_t   = rec.get("R_t+1", {})
            skill = u_t.get("skill", rec.get("func_name", ""))

            if func_name and func_name not in skill:
                continue

            params     = u_t.get("params", rec.get("params", {}))
            result_val = rec.get("Y_t+1", {}).get("result", None)
            timestamp  = rec.get("timestamp", rec.get("ts", 0.0))
            caller_ctx = rec.get("caller_ctx", {})

            raw_violations = r_t.get("violations", rec.get("violations", []))
            violations = []
            for vd in raw_violations:
                violations.append(V(
                    dimension  = vd.get("type", "deny").lower().replace(
                        "deny_content", "deny").replace("blocklist_hit", "deny_commands"),
                    field      = vd.get("field", ""),
                    message    = vd.get("message", ""),
                    actual     = vd.get("actual", ""),
                    constraint = vd.get("constraint", ""),
                    severity   = vd.get("severity", 0.8),
                ))

            # v0.7: parse CIEU complete five-tuple fields
            # y*_t — ideal contract (K9Audit format: Y_star_t field)
            intent_dict = rec.get("Y_star_t", rec.get("intent_contract", None))
            intent_c = None
            if isinstance(intent_dict, dict):
                from ystar.kernel.dimensions import IntentContract as _IC
                intent_c = _IC.from_dict(intent_dict)

            # applied_contract (the contract actually used by Y*)
            applied_dict = rec.get("applied_contract", None)
            applied_c = None
            if isinstance(applied_dict, dict):
                from ystar.kernel.dimensions import IntentContract as _IC2
                applied_c = _IC2.from_dict(applied_dict)

            # x_t — system state
            system_state = rec.get("X_t", rec.get("system_state", {}))

            records.append(CallRecord(
                seq              = seq,
                func_name        = skill,
                params           = params,
                result           = result_val,
                violations       = violations,
                intent_contract  = intent_c,
                applied_contract = applied_c,
                system_state     = system_state,
                timestamp        = float(timestamp),
                caller_ctx       = caller_ctx,
            ))
            seq += 1

    return learn(records, max_fp_rate=max_fp_rate)


# ══════════════════════════════════════════════════════════════════════════════
# v0.13.0  ParameterDiscovery — automatic discovery of unknown parameters and threshold inference
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParameterHint:
    """
    对一个「从未被任何合约维度覆盖」的参数的发现报告。

    三种情况：
    - NUMERIC_THRESHOLD：参数在安全调用 vs 违规调用里值分布有明显分界
      → 自动推断阈值，建议加入 optional_invariant 或 value_range
    - CATEGORICAL：参数是字符串，某些值只出现在违规调用里
      → 建议加入 deny 或 field_deny
    - OBSERVED_ONLY：参数在历史里出现但无法自动推断规则
      → 提示人工检视
    """
    param_name:      str
    hint_type:       str              # "NUMERIC_THRESHOLD" / "CATEGORICAL" / "OBSERVED_ONLY"
    suggested_rule:  Optional[str]    # e.g. "risk_score < 0.7"
    suggested_dim:   Optional[str]    # "optional_invariant" / "deny" / "value_range"
    safe_values:     List            # 安全调用里的值样本
    violation_values: List           # 违规调用里的值样本
    confidence:      float            # 0.0~1.0，分离度
    evidence:        str              # 人类可读的推断依据

    def explain(self) -> str:
        lines = [
            f"ParameterHint: '{self.param_name}'",
            f"  type:       {self.hint_type}",
            f"  confidence: {self.confidence:.0%}",
        ]
        if self.suggested_rule:
            lines.append("  suggested:  " + str(self.suggested_dim) + '=["'  + str(self.suggested_rule) + '"]' )
        lines.append(f"  evidence:   {self.evidence}")
        if self.safe_values:
            lines.append(f"  safe vals:  {self.safe_values[:5]}")
        if self.violation_values:
            lines.append(f"  viol vals:  {self.violation_values[:5]}")
        return "\n".join(lines)


def discover_parameters(
    history:          List[CallRecord],
    known_contract:   Optional["IntentContract"] = None,
    min_occurrences:  int   = 3,
    min_separation:   float = 0.1,
) -> List[ParameterHint]:
    """
    从调用历史里发现「从未被任何合约维度覆盖」的参数，
    分析其在安全调用 vs 违规调用里的值分布，
    自动推断可能的约束规则。

    工作流：
    1. 收集历史里所有出现过的参数名
    2. 排除「已经被合约覆盖」的参数（在 deny/value_range 等里出现过的）
    3. 对剩余的「未知参数」：
       a. 分离安全调用 vs 违规调用里的值
       b. 如果是数值型：检测安全/违规之间的分界
       c. 如果是字符串型：检测只出现在违规里的值
    4. 返回 ParameterHint 列表，附带置信度和建议规则

    Args:
        history:          CallRecord 列表（含 violations 字段）
        known_contract:   已有的合约（已覆盖的参数不重复提示）
        min_occurrences:  参数在历史里至少出现几次才分析（默认 3）
        min_separation:   数值分离度阈值（默认 0.1）

    Returns:
        ParameterHint 列表，按置信度降序排列
    """
    if not history:
        return []

    # ── 1. Collect all parameter names and their values in safe/violating calls ──────
    safe_param_values:     Dict[str, List] = {}
    viol_param_values:     Dict[str, List] = {}

    for record in history:
        bucket = viol_param_values if record.violations else safe_param_values
        for key, val in record.params.items():
            bucket.setdefault(key, []).append(val)

    all_params = set(safe_param_values) | set(viol_param_values)

    # ── 2. Exclude parameters already covered by the contract ────────────────────────
    covered: set = set()
    if known_contract:
        # Values in the deny list (string patterns)
        for d in known_contract.deny:
            covered.add(d)
        # Parameter names in value_range
        covered.update(known_contract.value_range.keys())
        # Variable names referenced in invariant / optional_invariant
        import re as _re
        for expr in (known_contract.invariant or []) + (known_contract.optional_invariant or []):
            for name in _re.findall(r"\b([a-zA-Z_]\w*)\b", expr):
                covered.add(name)

    uncovered = {p for p in all_params
                 if p not in covered and
                    len(safe_param_values.get(p, []) + viol_param_values.get(p, [])) >= min_occurrences}

    # ── 3. Analyse each uncovered parameter ──────────────────────────────────────
    hints = []

    for param in sorted(uncovered):
        safe_vals = safe_param_values.get(param, [])
        viol_vals = viol_param_values.get(param, [])

        if not viol_vals:
            # Appears only in safe calls; cannot infer violation direction
            hints.append(ParameterHint(
                param_name       = param,
                hint_type        = "OBSERVED_ONLY",
                suggested_rule   = None,
                suggested_dim    = None,
                safe_values      = safe_vals[:5],
                violation_values = [],
                confidence       = 0.0,
                evidence         = f"仅在安全调用里出现（{len(safe_vals)}次），无法推断规则",
            ))
            continue

        # Numeric analysis
        safe_nums  = [v for v in safe_vals  if isinstance(v, (int, float))]
        viol_nums  = [v for v in viol_vals  if isinstance(v, (int, float))]

        if safe_nums and viol_nums:
            max_safe  = max(safe_nums)
            min_safe  = min(safe_nums)
            max_viol  = max(viol_nums)
            min_viol  = min(viol_nums)

            # Compute separability (degree of value-range overlap)
            overlap_lo = max(min_safe, min_viol)
            overlap_hi = min(max_safe, max_viol)
            safe_range = max_safe - min_safe if max_safe > min_safe else 1.0
            viol_range = max_viol - min_viol if max_viol > min_viol else 1.0
            separation = max(0.0, (overlap_lo - overlap_hi) / max(safe_range, viol_range, 1.0))

            if separation >= min_separation or max_safe < min_viol:
                # Clear boundary exists: infer threshold
                if max_safe < min_viol:
                    # Safe values all below violating values → upper-bound rule
                    threshold = (max_safe + min_viol) / 2
                    rule      = f"{param} < {threshold:.4g}"
                    dim       = "optional_invariant"
                    confidence= min(1.0, (min_viol - max_safe) / max(abs(max_viol), 1.0) * 2)
                    evidence  = (f"安全值上限={max_safe:.4g}，违规值下限={min_viol:.4g}，"
                                 f"推断阈值={threshold:.4g}")
                elif min_safe > max_viol:
                    # Safe values all above violating values → lower-bound rule
                    threshold = (min_safe + max_viol) / 2
                    rule      = f"{param} > {threshold:.4g}"
                    dim       = "optional_invariant"
                    confidence= min(1.0, (min_safe - max_viol) / max(abs(max_safe), 1.0) * 2)
                    evidence  = (f"违规值上限={max_viol:.4g}，安全值下限={min_safe:.4g}，"
                                 f"推断阈值={threshold:.4g}")
                else:
                    # Partial overlap but with a separating trend
                    threshold = (max_safe + min_viol) / 2
                    rule      = f"{param} < {threshold:.4g}"
                    dim       = "optional_invariant"
                    confidence= separation * 0.5
                    evidence  = f"部分分离，置信度较低，需人工确认阈值"

                hints.append(ParameterHint(
                    param_name       = param,
                    hint_type        = "NUMERIC_THRESHOLD",
                    suggested_rule   = rule,
                    suggested_dim    = dim,
                    safe_values      = [round(v, 4) for v in safe_nums[:5]],
                    violation_values = [round(v, 4) for v in viol_nums[:5]],
                    confidence       = round(confidence, 3),
                    evidence         = evidence,
                ))
                continue

        # String analysis
        safe_strs = {v for v in safe_vals  if isinstance(v, str)}
        viol_strs = {v for v in viol_vals  if isinstance(v, str)}
        viol_only = viol_strs - safe_strs

        if viol_only:
            confidence = len(viol_only) / max(len(viol_strs), 1)
            hints.append(ParameterHint(
                param_name       = param,
                hint_type        = "CATEGORICAL",
                suggested_rule   = None,
                suggested_dim    = "deny",
                safe_values      = list(safe_strs)[:5],
                violation_values = list(viol_only)[:5],
                confidence       = round(confidence, 3),
                evidence         = f"字符串值 {viol_only} 仅出现在违规调用里",
            ))
            continue

        # Cannot infer
        hints.append(ParameterHint(
            param_name       = param,
            hint_type        = "OBSERVED_ONLY",
            suggested_rule   = None,
            suggested_dim    = None,
            safe_values      = (safe_nums or list(safe_strs))[:5],
            violation_values = (viol_nums or list(viol_strs))[:5],
            confidence       = 0.0,
            evidence         = "值分布重叠，无法自动推断规则，请人工检视",
        ))

    # Sort by confidence descending
    hints.sort(key=lambda h: h.confidence, reverse=True)
    return hints


# ══════════════════════════════════════════════════════════════════════════════
# v0.14.0  SemanticInquiry — semantic inquiry engine
# ══════════════════════════════════════════════════════════════════════════════

# DomainContext 已迁移到 ystar.governance.domain_context
# 为向后兼容，此处保留 re-export
try:
    from ystar.governance.domain_context import DomainContext
except ImportError:
    # 兜底：定义一个极简的占位（仅 GENERIC）
    import enum as _enum
    class DomainContext(_enum.Enum):
        GENERIC = "generic"
        @classmethod
        def from_string(cls, s: str) -> "DomainContext":
            return cls.GENERIC
        def to_prompt_string(self) -> str:
            return ""


def _resolve_domain_context(domain_context) -> str:
    """
    Normalise domain_context to a prompt-ready string.

    Accepts DomainContext enum, any recognised string, or an empty string.
    Unrecognised strings emit a UserWarning and fall back to GENERIC.
    """
    if isinstance(domain_context, DomainContext):
        return domain_context.to_prompt_string()
    if isinstance(domain_context, str):
        if not domain_context:
            return ""
        dc = DomainContext.from_string(domain_context)
        return dc.to_prompt_string()
    # Unexpected type — convert to string and warn
    _warnings.warn(
        f"domain_context expected str or DomainContext, got {type(domain_context).__name__}. "
        f"Converting to string.",
        UserWarning,
        stacklevel=3,
    )
    return str(domain_context)


@dataclass
class SemanticConstraintProposal:
    """
    Inference result produced by the semantic inquiry engine for an unknown parameter.

    Fields
    ------
    param_name             : name of the parameter
    suggested_dim          : recommended constraint dimension
    suggested_rule         : recommended constraint expression
    reasoning              : rationale (LLM explanation)
    confidence             : confidence score (statistical separability × semantic clarity)
    requires_human_approval: always True (design decision: Y* never auto-writes)
    statistical_hint       : the ParameterHint that triggered this inquiry
    """
    param_name:              str
    suggested_dim:           str
    suggested_rule:          Optional[str]
    reasoning:               str
    confidence:              float
    requires_human_approval: bool = True   # always True
    statistical_hint:        Optional["ParameterHint"] = None

    def explain(self) -> str:
        lines = [
            f"SemanticProposal: '{self.param_name}'",
            f"  dimension:   {self.suggested_dim}",
        ]
        if self.suggested_rule:
            lines.append(f"  rule:        {self.suggested_rule}")
        lines.append(f"  confidence:  {self.confidence:.0%}")
        lines.append(f"  reasoning:   {self.reasoning}")
        lines.append(f"  human_approval_required: {self.requires_human_approval}")
        return "\n".join(lines)


def inquire_parameter_semantics(
    param_name:   str,
    hint:         "ParameterHint",
    domain_context = "",
    api_call_fn:  Optional[Any] = None,
) -> SemanticConstraintProposal:
    """
    Call the semantic reasoning engine to understand an unknown parameter
    discovered by statistical analysis.

    This is Y*'s active "seek knowledge" interface.

    Workflow:
    1. discover_parameters() detects that some_param has an anomalous value distribution
    2. inquire_parameter_semantics() is called
    3. The reasoning engine is asked: "In this business context, what does {param_name} represent?
       Values in the violation range appear in failing calls — what threshold is reasonable?"
    4. The reasoning engine returns a meaning explanation and suggested threshold
    5. A SemanticConstraintProposal is generated with requires_human_approval=True
    6. A human must confirm before the constraint is written into the contract

    Args:
        param_name:     parameter name
        hint:           statistical discovery from discover_parameters()
        domain_context: business context description — accepts DomainContext enum or str
                        (e.g. DomainContext.EQUITY_EXECUTION or "equity_execution")
        api_call_fn:    injectable API call function (for testing / mocking);
                        if None, attempts to call the Anthropic API

    Returns:
        SemanticConstraintProposal with requires_human_approval=True
    """
    # Normalise domain_context to a prompt-ready string
    ctx_str = _resolve_domain_context(domain_context)
    # Build the inquiry prompt
    stat_summary = ""
    if hint.safe_values:
        stat_summary += f"Safe calls: {hint.safe_values[:3]}\n"
    if hint.violation_values:
        stat_summary += f"Violation calls: {hint.violation_values[:3]}\n"
    if hint.suggested_rule:
        stat_summary += f"Statistical threshold: {hint.suggested_rule}\n"

    prompt = f"""You are an expert analyzing an AI agent constraint system.

A parameter named '{param_name}' has been observed in function call history but is not covered by any existing constraint.
{"Business context: " + ctx_str if ctx_str else ""}

Statistical analysis shows:
{stat_summary}
The parameter appears to correlate with violations.

Please answer:
1. What does '{param_name}' likely represent in this context?
2. Is the statistical threshold ({hint.suggested_rule or 'not determined'}) reasonable?
3. What constraint rule would you suggest?
4. How confident are you (0-100%)?

Respond in this exact JSON format (no markdown):
{{
  "meaning": "brief explanation of what this parameter represents",
  "rule": "the constraint expression, e.g. param_name < threshold",
  "dimension": "optional_invariant or value_range or deny",
  "confidence": 75,
  "reasoning": "why this threshold makes sense"
}}"""

    # Call the reasoning engine
    if api_call_fn is not None:
        # Injected function (test mode)
        try:
            response_text = api_call_fn(prompt)
        except Exception as e:
            # Injected function failed → fall back to statistical suggestions
            return SemanticConstraintProposal(
                param_name    = param_name,
                suggested_dim = hint.suggested_dim or "optional_invariant",
                suggested_rule = hint.suggested_rule,
                reasoning     = f"[api_call_fn failed: {e}] Using statistical threshold.",
                confidence    = round(hint.confidence * 0.5, 3),
                requires_human_approval = True,
            )
    else:
        # Real API call
        try:
            import urllib.request
            import json as _json

            req_body = _json.dumps({
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
                response_text = data["content"][0]["text"]
        except Exception as e:
            # API unavailable → degrade to statistical suggestions
            return SemanticConstraintProposal(
                param_name       = param_name,
                suggested_dim    = hint.suggested_dim or "optional_invariant",
                suggested_rule   = hint.suggested_rule,
                reasoning        = f"[API unavailable: {e}] Using statistical threshold only.",
                confidence       = hint.confidence * 0.5,  # 降低置信度
                statistical_hint = hint,
            )

    # Parse the reasoning result
    try:
        import json as _json
        import re as _re
        # Strip possible Markdown wrapping
        clean = _re.sub(r"```\w*\n?", "", response_text).strip()
        parsed = _json.loads(clean)

        api_confidence = parsed.get("confidence", 50) / 100.0
        # Geometric mean of semantic confidence × statistical confidence
        combined = (api_confidence * hint.confidence) ** 0.5 if hint.confidence > 0 else api_confidence

        return SemanticConstraintProposal(
            param_name       = param_name,
            suggested_dim    = parsed.get("dimension", "optional_invariant"),
            suggested_rule   = parsed.get("rule", hint.suggested_rule),
            reasoning        = (f"[Meaning] {parsed.get('meaning', '')}. "
                                f"[Reasoning] {parsed.get('reasoning', '')}"),
            confidence       = round(combined, 3),
            statistical_hint = hint,
        )
    except Exception as e:
        # JSON parse failure → degrade to statistical suggestions
        return SemanticConstraintProposal(
            param_name       = param_name,
            suggested_dim    = hint.suggested_dim or "optional_invariant",
            suggested_rule   = hint.suggested_rule,
            reasoning        = f"[Parse error: {e}] Raw: {response_text[:200]}",
            confidence       = hint.confidence * 0.6,
            statistical_hint = hint,
        )


def auto_inquire_all(
    history:         List["CallRecord"],
    known_contract:  Optional["IntentContract"] = None,
    domain_context                              = "",
    api_call_fn:     Optional[Any] = None,
    min_confidence:  float = 0.3,
) -> List[SemanticConstraintProposal]:
    """
    Full automatic semantic inquiry pipeline:
    discover_parameters() → inquire_parameter_semantics() → return annotated proposal list.

    Every high-confidence statistical discovery is sent for semantic inquiry.
    The returned proposals require human confirmation before being written into a contract.

    Args:
        history:        list of CallRecord objects
        known_contract: existing contract (already-covered parameters are skipped)
        domain_context: business context — accepts DomainContext enum or str
                        (e.g. DomainContext.EQUITY_EXECUTION or "equity_execution");
                        unrecognised strings emit a UserWarning and fall back to GENERIC
        api_call_fn:    injectable API function (None = real API call)
        min_confidence: only inquire about discoveries above this confidence threshold

    Returns:
        List of SemanticConstraintProposal objects, sorted by confidence descending;
        each is marked requires_human_approval=True
    """
    # Step 1: Statistical discovery
    hints = discover_parameters(history, known_contract=known_contract)
    worthy = [h for h in hints
              if h.confidence >= min_confidence and h.hint_type != "OBSERVED_ONLY"]

    # Step 2: Semantic inquiry
    proposals = []
    for hint in worthy:
        proposal = inquire_parameter_semantics(
            param_name     = hint.param_name,
            hint           = hint,
            domain_context = domain_context,
            api_call_fn    = api_call_fn,
        )
        proposals.append(proposal)

    proposals.sort(key=lambda p: p.confidence, reverse=True)
    return proposals



# ══════════════════════════════════════════════════════════════════════════════
# v0.14.1  ProposalVerifier — verify LLM hypotheses with pure mathematics
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VerificationReport:
    """
    对一条 SemanticConstraintProposal 的数学验证报告。

    Y* 的确定性验证层：LLM 生成假设，数学验证假设。
    只有通过验证的假设才会带着报告呈给人类。

    验证维度：
    1. empirical_coverage:   这条规则能防止多少历史违规（召回率）
    2. empirical_fp_rate:    这条规则会错误拦截多少合法调用（误报率）
    3. value_range_check:    LLM 建议的阈值是否落在统计分界区间内
    4. counterfactual_proof: 规则能防止哪些具体违规（序号列表）
    5. verdict:              PASS / WARN / FAIL
    6. verdict_reason:       人类可读的判断依据
    """
    param_name:           str
    proposed_rule:        Optional[str]
    empirical_coverage:   float   # 0.0~1.0，越高越好
    empirical_fp_rate:    float   # 0.0~1.0，越低越好
    value_range_check:    bool    # 阈值是否落在统计分界区间
    counterfactual_proof: List[int]  # 被规则防止的违规记录序号
    quality_score:        float
    verdict:              str    # "PASS" / "WARN" / "FAIL"
    verdict_reason:       str
    cieu_evidence_count:  int = 0  # GAP 3: CIEU evidence for similar proposals

    @classmethod
    def _get_verdict(cls,
                     coverage: float,
                     fp_rate:  float,
                     range_ok: bool) -> tuple:
        if coverage >= 0.8 and fp_rate <= 0.05 and range_ok:
            return "PASS", f"coverage={coverage:.0%}, fp={fp_rate:.0%}, 阈值在分界区间内"
        elif coverage >= 0.6 and fp_rate <= 0.15:
            return "WARN", f"coverage={coverage:.0%}, fp={fp_rate:.0%} — 可用但需人工复核"
        else:
            return "FAIL", (f"coverage={coverage:.0%} < 0.6，或 fp={fp_rate:.0%} > 0.15，"
                            f"或阈值在分界区间外 — 建议拒绝")

    def explain(self) -> str:
        lines = [
            f"VerificationReport: '{self.param_name}'",
            f"  proposed_rule:   {self.proposed_rule}",
            f"  coverage:        {self.empirical_coverage:.0%}  （能防止多少历史违规）",
            f"  false_positive:  {self.empirical_fp_rate:.0%}  （错误拦截合法调用比例）",
            f"  value_range_ok:  {self.value_range_check}",
            f"  prevented:       violations {self.counterfactual_proof[:5]}{'...' if len(self.counterfactual_proof)>5 else ''}",
            f"  quality_score:   {self.quality_score:.3f}",
            f"  ── VERDICT: {self.verdict} ──",
            f"  reason:          {self.verdict_reason}",
        ]
        return "\n".join(lines)


def verify_proposal(
    proposal: "SemanticConstraintProposal",
    history:  List["CallRecord"],
    stat_hint: Optional["ParameterHint"] = None,
) -> "VerificationReport":
    """
    用 Y* 的确定性数学工具验证一条 LLM 生成的假设。

    这是整个语义询问架构的关键：
    - LLM 的输出是「不确定的假设」
    - Y* 的验证是「确定性的数学检验」
    - 两者分离，LLM 的不确定性不会污染 Y* 的核心

    如果 LLM 建议的阈值被历史数据否定：verdict=FAIL，
    人类会同时看到「LLM 说这个阈值」和「历史数据说这个阈值不合适」。

    验证步骤：
    1. 把 LLM 建议转为 IntentContract
    2. 用 ContractQuality 计算 coverage / fp_rate
    3. 用反事实重演列出具体防止了哪些违规
    4. 检查阈值是否在统计分界区间内
    5. 综合评定 PASS / WARN / FAIL
    """
    # ── Build candidate contract ─────────────────────────────────────────────
    rule = proposal.suggested_rule
    dim  = proposal.suggested_dim or "optional_invariant"

    if not rule:
        return VerificationReport(
            param_name           = proposal.param_name,
            proposed_rule        = None,
            empirical_coverage   = 0.0,
            empirical_fp_rate    = 1.0,
            value_range_check    = False,
            counterfactual_proof = [],
            quality_score        = 0.0,
            verdict              = "FAIL",
            verdict_reason       = "LLM未能生成具体规则",
        )

    # Build test contract
    if dim == "optional_invariant":
        test_contract = IntentContract(optional_invariant=[rule])
    elif dim == "value_range":
        # Attempt to extract parameter name and bounds from the rule expression
        import re as _re
        m = _re.match(r"(\w+)\s*([<>]=?)\s*([\d.]+)", rule)
        if m:
            pname, op, val = m.group(1), m.group(2), float(m.group(3))
            if "<" in op:
                test_contract = IntentContract(
                    value_range={pname: {"max": val}})
            else:
                test_contract = IntentContract(
                    value_range={pname: {"min": val}})
        else:
            test_contract = IntentContract(optional_invariant=[rule])
    elif dim == "deny":
        # categorical: denial list from violation_values
        hints_vals = (stat_hint.violation_values if stat_hint else [])
        test_contract = IntentContract(deny=hints_vals if hints_vals else [rule])
    else:
        test_contract = IntentContract(optional_invariant=[rule])

    # ── Compute empirical metrics using ContractQuality ──────────────────────
    quality = ContractQuality.evaluate(test_contract, history)

    # ── Counterfactual replay: which specific violations were prevented ───────
    incident_seqs = []
    for record in history:
        if record.violations:
            r = check(record.params, record.result, test_contract)
            if not r.passed:
                incident_seqs.append(record.seq)

    # ── Value-range consistency check ────────────────────────────────────────
    value_range_ok = False
    if stat_hint and stat_hint.hint_type == "NUMERIC_THRESHOLD":
        import re as _re2
        m = _re2.search(r"[<>]=?\s*([\d.]+)", rule)
        if m:
            proposed_thresh = float(m.group(1))
            if stat_hint.safe_values and stat_hint.violation_values:
                max_safe  = max(v for v in stat_hint.safe_values
                                if isinstance(v, (int, float)))
                min_viol  = min(v for v in stat_hint.violation_values
                                if isinstance(v, (int, float)))
                # Threshold should lie within [max_safe, min_viol]
                value_range_ok = max_safe <= proposed_thresh <= min_viol
    elif stat_hint and stat_hint.hint_type == "CATEGORICAL":
        value_range_ok = True  # categorical 不需要值域检查

    # ── Assign PASS / WARN / FAIL rating ────────────────────────────────────
    verdict, reason = VerificationReport._get_verdict(
        quality.coverage_rate,
        quality.false_positive_rate,
        value_range_ok,
    )

    return VerificationReport(
        param_name           = proposal.param_name,
        proposed_rule        = rule,
        empirical_coverage   = quality.coverage_rate,
        empirical_fp_rate    = quality.false_positive_rate,
        value_range_check    = value_range_ok,
        counterfactual_proof = incident_seqs,
        quality_score        = quality.quality_score,
        verdict              = verdict,
        verdict_reason       = reason,
    )


def inquire_and_verify(
    history:        List["CallRecord"],
    known_contract: Optional["IntentContract"] = None,
    domain_context                             = "",
    api_call_fn:    Optional[Any] = None,
    min_confidence: float = 0.3,
) -> List[tuple]:
    """
    Full "inquire → verify" pipeline:

    1. discover_parameters()          — statistical discovery
    2. inquire_parameter_semantics()  — LLM generates a hypothesis (uncertain)
    3. verify_proposal()              — Y* mathematical verification (deterministic)
    4. Return (proposal, report) pairs sorted by mathematical quality score descending

    This is the full "ask but don't blindly trust" architecture:
    LLM suggestions pass through a mathematical verification layer before being
    presented to a human.  The human sees "LLM says X; mathematical verification
    result is Y", not just "LLM says X".

    Args:
        domain_context: accepts DomainContext enum or str (same as auto_inquire_all)

    Returns:
        List of (SemanticConstraintProposal, VerificationReport)
        sorted by VerificationReport.quality_score descending;
        FAIL entries are last but not discarded (kept for human reference)
    """
    # Step 1: Statistical discovery
    hints = discover_parameters(history, known_contract=known_contract)
    worthy = [h for h in hints
              if h.confidence >= min_confidence and h.hint_type != "OBSERVED_ONLY"]

    results = []
    for hint in worthy:
        # Step 2: LLM inquiry (uncertain)
        proposal = inquire_parameter_semantics(
            param_name     = hint.param_name,
            hint           = hint,
            domain_context = domain_context,
            api_call_fn    = api_call_fn,
        )

        # Step 3: Y* mathematical verification (deterministic)
        report = verify_proposal(proposal, history, stat_hint=hint)

        results.append((proposal, report))

    # Sort by mathematical quality score descending; PASS first, FAIL last
    verdict_order = {"PASS": 0, "WARN": 1, "FAIL": 2}
    results.sort(key=lambda x: (verdict_order.get(x[1].verdict, 3),
                                 -x[1].quality_score))
    return results


# ══════════════════════════════════════════════════════════════════════════════
# v0.15.0  ConstraintLifecycle — constraint lifecycle management
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
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

"""
ystar.governance.ml.objectives
NormativeObjective, ContractQuality, AdaptiveCoefficients, RefinementFeedback
v0.41: 从 metalearning.py 拆分，原始行 290-1552。
"""
from __future__ import annotations
import time, json, re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from ystar.kernel.dimensions import IntentContract, HigherOrderContract
from ystar.kernel.dimensions import TemporalConstraint, AggregateConstraint
from ystar.kernel.engine import check, CheckResult, Violation

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


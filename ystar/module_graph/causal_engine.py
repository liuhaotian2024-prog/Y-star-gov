"""
ystar.module_graph.causal_engine — Pearl Level 3 因果推理引擎

用于替代 CompositionPlanner 的纯概率决策。

核心能力：
  Level 2 (干预): do_wire_query(src, tgt) → 预测接线的健康效果
  Level 3 (反事实): counterfactual_query(cycle_history, alternative_plan) → 
                    "如果当时选了不同方案，结果会怎样？"

结构因果模型 (SCM):
  W_t+1 = f(W_t, S_t)           # Path A 的决策
  O_t   = g(W_t, obligations)    # 义务履行由接线决定
  H_t+1 = h(O_t, W_t)           # 健康由义务履行决定
  S_t   = k(H_t)                 # 建议由健康决定

CIEU 历史记录 = SCM 的完整观测数据，支持反事实推断。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import math


@dataclass
class CausalState:
    """一个时间点的完整因果状态。"""
    wired_edges:   List[Tuple[str, str]]  # 当前已接线的边
    health:        str                    # critical/degraded/stable/healthy
    obl_fulfilled: int                    # 已履行的 obligation 数量
    obl_total:     int                    # 总 obligation 数量
    suggestion_type: Optional[str] = None # 当时的 GovernanceSuggestion 类型

    @property
    def fulfillment_rate(self) -> float:
        if self.obl_total == 0: return 0.0
        return self.obl_fulfilled / self.obl_total

    @property
    def health_score(self) -> float:
        return {"healthy": 1.0, "stable": 0.75,
                "degraded": 0.4, "critical": 0.1, "unknown": 0.0}.get(self.health, 0.0)

    def distance_to(self, other: "CausalState") -> float:
        """状态空间距离（用于反事实的最近邻搜索）。"""
        health_diff = abs(self.health_score - other.health_score)
        rate_diff   = abs(self.fulfillment_rate - other.fulfillment_rate)
        wiring_overlap = len(set(map(str, self.wired_edges)) &
                              set(map(str, other.wired_edges)))
        wiring_sim  = wiring_overlap / max(len(self.wired_edges), len(other.wired_edges), 1)
        return health_diff * 0.4 + rate_diff * 0.4 + (1 - wiring_sim) * 0.2


@dataclass
class CausalObservation:
    """一次完整的 PathA 循环观测（用于构建 SCM）。"""
    state_before: CausalState
    state_after:  CausalState
    action_taken: List[Tuple[str, str]]  # 接线的边
    succeeded:    bool
    cycle_id:     str


@dataclass
class DoCalcResult:
    """do-calculus 查询结果。"""
    query:              str    # do(wire(X→Y))
    predicted_health:   str    # 预测的健康状态
    confidence:         float  # 0-1
    causal_chain:       List[str]  # 因果传播路径
    evidence_count:     int    # 支持这个预测的历史观测数
    counterfactual_gain: Optional[float] = None  # 与当前方案相比的预期增益


class CausalEngine:
    """
    Pearl 因果推理引擎。

    维护一个基于 MetaAgentCycle 历史的 SCM，
    支持 do-calculus 查询（Level 2）和反事实推理（Level 3）。

    自主性保证：
    当 confidence >= confidence_threshold 时，Path A 不需要人工确认，
    直接执行因果推理推荐的方案。
    仅当 confidence < threshold 时才请求人工。
    """

    def __init__(self, confidence_threshold: float = 0.65):
        self.confidence_threshold = confidence_threshold
        self._observations: List[CausalObservation] = []

    # ── 更新观测（每次 PathA 循环完成后调用）────────────────────────────────
    def observe(
        self,
        health_before:  str,
        health_after:   str,
        obl_before:     Tuple[int, int],   # (fulfilled, total)
        obl_after:      Tuple[int, int],
        edges_before:   List[Tuple[str,str]],
        edges_after:    List[Tuple[str,str]],
        action_edges:   List[Tuple[str,str]],
        succeeded:      bool,
        cycle_id:       str,
        suggestion_type: Optional[str] = None,
    ) -> None:
        ob = CausalObservation(
            state_before = CausalState(
                wired_edges=edges_before, health=health_before,
                obl_fulfilled=obl_before[0], obl_total=obl_before[1],
                suggestion_type=suggestion_type,
            ),
            state_after = CausalState(
                wired_edges=edges_after, health=health_after,
                obl_fulfilled=obl_after[0], obl_total=obl_after[1],
            ),
            action_taken = action_edges,
            succeeded    = succeeded,
            cycle_id     = cycle_id,
        )
        self._observations.append(ob)

    # ── Level 2：do-calculus 查询 ──────────────────────────────────────────
    def do_wire_query(
        self,
        src_id: str,
        tgt_id: str,
        current_state: Optional[CausalState] = None,
    ) -> DoCalcResult:
        """
        查询：P(H | do(wire(src→tgt)))
        如果执行这条接线，系统健康预期是什么？

        基于历史观测：找到所有执行过类似接线的循环，
        计算接线后健康改善的概率。
        """
        query = f"do(wire({src_id}→{tgt_id}))"

        # 找到执行过包含这条边的接线的历史循环
        relevant = [
            ob for ob in self._observations
            if (src_id, tgt_id) in ob.action_taken
        ]

        if not relevant:
            # 没有直接历史证据：用义务传播路径推断
            return self._infer_from_obligation_chain(src_id, tgt_id, query)

        # ── 综合因果证据（替换原频率统计）──────────────────────────
        # 三个维度：趋势加权 + 效果量 + 差分对照
        n = len(relevant)
        decay = 0.92
        weights = [decay ** (n - 1 - i) for i in range(n)]
        total_w = sum(weights)

        deltas = [ob.state_after.health_score - ob.state_before.health_score
                  for ob in relevant]

        # 维度1：趋势加权成功率 + 趋势斜率调整
        w_success = sum(w * (1.0 if d > 0 else 0.0)
                        for d, w in zip(deltas, weights)) / total_w
        mid = max(1, n // 2)
        early_r = sum(1 for d in deltas[:mid] if d > 0) / mid
        recent_r = sum(1 for d in deltas[mid:] if d > 0) / max(1, n - mid)
        trend_slope = recent_r - early_r
        score_trend = max(0.0, min(1.0, w_success + 0.15 * trend_slope))

        # 维度2：指数加权移动趋势（EWMA slope）
        # 不用平均量——平均量会被历史拖后腿，无法反映当前方向。
        # 用最近窗口的趋势斜率：如果最近几次都在改善，置信度应该高，
        # 即使历史平均值还是负的。
        # 实现：对deltas序列做线性回归（时间加权），取斜率方向。
        if n >= 2:
            # 指数加权线性回归斜率
            x_vals = list(range(n))
            x_mean = sum(x * w for x, w in zip(x_vals, weights)) / total_w
            y_mean = sum(d * w for d, w in zip(deltas, weights)) / total_w
            numerator = sum(w * (x - x_mean) * (d - y_mean)
                           for x, d, w in zip(x_vals, deltas, weights))
            denominator = sum(w * (x - x_mean) ** 2
                              for x, w in zip(x_vals, weights))
            slope = numerator / max(denominator, 1e-9)
            # slope > 0 = 改善趋势, slope < 0 = 恶化趋势
            # 同时考虑最近3个点的方向（防止单点噪声）
            recent_window = min(3, n)
            recent_deltas = deltas[-recent_window:]
            recent_improving = sum(1 for d in recent_deltas if d > 0) / recent_window
            # 综合：slope方向(60%) + 最近窗口改善率(40%)
            score_effect = max(0.0, min(1.0,
                0.6 * (0.5 + slope * 2.0) +  # slope归一化到0-1
                0.4 * recent_improving
            ))
        else:
            # 只有1个观测，用单点delta方向
            score_effect = 1.0 if deltas[0] > 0 else 0.3 if deltas[0] == 0 else 0.0

        # 维度3：差分对照（排除系统自然变化）
        # 同样用趋势而非平均：对照组最近的方向 vs 实验组最近的方向
        not_wired = [ob for ob in self._observations
                     if (src_id, tgt_id) not in ob.action_taken]
        if not_wired:
            ctrl_deltas = [ob.state_after.health_score - ob.state_before.health_score
                           for ob in not_wired]
            ctrl_recent = ctrl_deltas[-min(3, len(ctrl_deltas)):]
            ctrl_trend = sum(1 for d in ctrl_recent if d > 0) / len(ctrl_recent)
            # 实验组最近趋势
            exp_recent = deltas[-min(3, n):]
            exp_trend = sum(1 for d in exp_recent if d > 0) / len(exp_recent)
            # 差分：实验组趋势 - 对照组趋势
            net_trend = exp_trend - ctrl_trend
        else:
            net_trend = 0.0
        score_diff = max(0.0, min(1.0, 0.5 + net_trend * 0.5))

        # 综合置信度（趋势35% + 效果量40% + 差分对照25%）
        confidence = 0.35 * score_trend + 0.40 * score_effect + 0.25 * score_diff

        # 趋势标签（供调用方读取）
        trend_label = ("improving" if trend_slope > 0.1
                       else "degrading" if trend_slope < -0.1 else "stable")

        predicted_health = (
            "stable" if confidence >= 0.7
            else "degraded" if confidence >= 0.4
            else "critical"
        )

        # 追踪因果链：接线 → 义务变化 → 健康变化
        causal_chain = [
            f"do(wire({src_id}→{tgt_id}))",
            f"→ obligation fulfillment change",
            f"→ health: {predicted_health} (p={confidence:.2f})",
        ]

        return DoCalcResult(
            query=query, predicted_health=predicted_health,
            confidence=confidence, causal_chain=causal_chain,
            evidence_count=len(relevant),
        )

    # ── Level 3：反事实查询 ──────────────────────────────────────────────────
    def counterfactual_query(
        self,
        failed_cycle_id: str,
        alternative_edges: List[Tuple[str, str]],
    ) -> DoCalcResult:
        """
        反事实查询：
        "在 cycle X 的相同初始状态下，如果选了不同的接线方案，结果会怎样？"

        Pearl Level 3 的三步法：
          1. Abduction（溯因）：从观测到初始状态的参数
          2. Action（干预）：用 alternative_edges 代替实际动作
          3. Prediction（预测）：用结构方程计算新结果
        """
        # 找到失败的循环
        failed = next(
            (ob for ob in self._observations if ob.cycle_id == failed_cycle_id),
            None,
        )
        if not failed:
            return DoCalcResult(
                query=f"cf(cycle={failed_cycle_id}, alt={alternative_edges})",
                predicted_health="unknown", confidence=0.0,
                causal_chain=["cycle not found"], evidence_count=0,
            )

        # Step 1: Abduction — 确定失败循环的初始状态
        initial_state = failed.state_before

        # Step 2: Action — 用替代方案替换实际动作
        # 找历史中在相似初始状态下执行过这些替代边的循环
        similar_with_alt = []
        for ob in self._observations:
            if ob.cycle_id == failed_cycle_id:
                continue
            state_dist = initial_state.distance_to(ob.state_before)
            has_alt = any(e in ob.action_taken for e in alternative_edges)
            if state_dist < 0.3 and has_alt:
                similar_with_alt.append((state_dist, ob))

        # Step 3: Prediction — 从相似初始状态的替代结果预测
        if not similar_with_alt:
            # 没有直接证据：用因果链推断
            return self._infer_from_obligation_chain(
                alternative_edges[0][0] if alternative_edges else "?",
                alternative_edges[0][1] if alternative_edges else "?",
                f"cf({failed_cycle_id})",
            )

        # 权重：越相似的历史状态权重越高
        weighted_success = sum(
            (1 - dist) * (1 if ob.succeeded else 0)
            for dist, ob in similar_with_alt
        )
        total_weight = sum(1 - dist for dist, ob in similar_with_alt)
        cf_success_prob = weighted_success / max(total_weight, 1e-9)

        # 与实际失败的对比：反事实增益
        actual_success = failed.succeeded
        cf_gain = cf_success_prob - (1.0 if actual_success else 0.0)

        predicted_health = (
            "stable"   if cf_success_prob >= 0.7
            else "degraded" if cf_success_prob >= 0.4
            else "critical"
        )
        causal_chain = [
            f"initial: {initial_state.health} (rate={initial_state.fulfillment_rate:.1%})",
            f"do(alt_wire={alternative_edges})",
            f"similar_states: {len(similar_with_alt)} found (min_dist={similar_with_alt[0][0]:.2f})",
            f"cf_success_prob: {cf_success_prob:.2f}",
            f"predicted: {predicted_health}",
        ]

        return DoCalcResult(
            query=f"cf(cycle={failed_cycle_id}, alt={alternative_edges})",
            predicted_health=predicted_health,
            confidence=cf_success_prob,
            causal_chain=causal_chain,
            evidence_count=len(similar_with_alt),
            counterfactual_gain=cf_gain,
        )

    # ── 自主性判断：是否需要人工确认 ────────────────────────────────────────
    def needs_human_approval(
        self,
        result: DoCalcResult,
        action_is_irreversible: bool = False,
    ) -> Tuple[bool, str]:
        """
        判断是否需要人工确认。

        不需要人工确认的条件（完全自主运行）：
          - confidence >= confidence_threshold
          - 不是不可逆操作
          - 有足够的历史证据

        需要人工确认的条件（仅以下情况）：
          - confidence < confidence_threshold（不确定）
          - action_is_irreversible（写实际代码）
          - evidence_count == 0（没有历史数据）
        """
        if action_is_irreversible:
            return True, "不可逆操作（代码修改）必须人工确认"
        if result.evidence_count == 0:
            return True, "没有历史证据，无法计算置信度"
        if result.confidence < self.confidence_threshold:
            return True, f"置信度 {result.confidence:.2f} < 阈值 {self.confidence_threshold:.2f}"
        return False, f"自主执行 (confidence={result.confidence:.2f} >= {self.confidence_threshold:.2f})"

    # ── 内部：从义务传播链推断 do-calculus（无历史证据时）─────────────────
    def _infer_from_obligation_chain(
        self, src_id: str, tgt_id: str, query: str
    ) -> DoCalcResult:
        """
        无历史证据时，从义务传播链的结构推断接线效果。

        规则（基于 ModuleGraph 的语义标签）：
          - skill_risk → obligation_track：高可能性改善（有漏洞接上了）
          - drift_detection → obligation_track：高可能性改善
          - retro_assess → objective_derive：中等可能性改善
        """
        HIGH_IMPACT_PAIRS = {
            ("SkillProvenance", "OmissionEngine.scan"):    0.80,
            ("ChainDriftDetector", "OmissionEngine.scan"): 0.75,
            ("assess_batch", "derive_objective"):          0.65,
            ("DelegationChain", "apply_finance_pack"):     0.60,
        }
        confidence = HIGH_IMPACT_PAIRS.get((src_id, tgt_id), 0.45)
        predicted   = "stable" if confidence >= 0.7 else "degraded" if confidence >= 0.5 else "critical"

        return DoCalcResult(
            query=query, predicted_health=predicted,
            confidence=confidence,
            causal_chain=[
                f"no history evidence",
                f"structural inference: {src_id} → {tgt_id}",
                f"obligation chain impact: {confidence:.2f}",
            ],
            evidence_count=0,
        )

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    def summary(self) -> str:
        if not self._observations:
            return "CausalEngine: 0 observations"
        success_rate = sum(1 for o in self._observations if o.succeeded) / len(self._observations)
        return (f"CausalEngine: {len(self._observations)} obs, "
                f"success_rate={success_rate:.1%}, "
                f"threshold={self.confidence_threshold:.2f}")

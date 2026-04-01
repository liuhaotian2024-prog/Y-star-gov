# Layer: Foundation
"""
ystar.governance.causal_engine — Pearl Level 2 & 3 因果推理引擎 (Foundation Layer)

Genuine implementation of Judea Pearl's causal hierarchy:
  Level 1 (Association): P(Y|X) — standard conditional probability
  Level 2 (Intervention): P(Y|do(X)) — do-calculus with backdoor adjustment
  Level 3 (Counterfactual): P(Y_x|X=x', Y=y') — SCM-based counterfactuals

This is NOT "Pearl-inspired" heuristics. This is the real thing:
  - Explicit causal DAG with d-separation
  - Backdoor criterion and adjustment formula
  - Structural Causal Model with noise terms
  - Three-step counterfactual: Abduction → Action → Prediction

Structural Causal Model (SCM) for Y*gov:
  W_t+1 = f_W(S_t, U_W)           # Wiring decision = f(suggestions, noise)
  O_t   = f_O(W_t, U_O)           # Obligation fulfillment = f(wiring, noise)
  H_t+1 = f_H(O_t, W_t, U_H)     # Health = f(obligations, wiring, noise)
  S_t   = f_S(H_t, U_S)           # Suggestions = f(health, noise)

Variables: W (Wiring), O (Obligations), H (Health), S (Suggestions)
Within-cycle DAG: S → W → O → H, W → H (direct effect of wiring on health)
Cross-temporal: H_t → S_{t+1} (health drives next cycle's suggestions)

CIEU historical records = complete observational data for the SCM.

Module structure (split for modularity):
  - causal_graph.py: CausalGraph class (DAG, d-separation, backdoor criterion)
  - structural_equation.py: StructuralEquation class + linear algebra helpers
  - counterfactual_engine.py: CounterfactualEngine (three-step procedure)
  - backdoor_adjuster.py: BackdoorAdjuster class
  - causal_discovery.py: CausalDiscovery (PC algorithm) + DirectLiNGAM

References:
  Pearl, J. (2009). Causality: Models, Reasoning, and Inference. 2nd ed.
  Pearl, J. (2000). "The Three Levels of the Causal Hierarchy"
  Pearl, Glymour, Jewell (2016). Causal Inference in Statistics: A Primer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set, FrozenSet

# ── Re-exports from split modules (preserves backward compatibility) ─────────
from ystar.governance.causal_graph import CausalGraph
from ystar.governance.structural_equation import StructuralEquation, _solve_linear_system
from ystar.governance.counterfactual_engine import CounterfactualEngine
from ystar.governance.backdoor_adjuster import BackdoorAdjuster
from ystar.governance.causal_discovery import (
    CausalDiscovery, DirectLiNGAM,
    # Statistical helpers (re-exported for backward compatibility)
    _correlation_matrix, _partial_correlation, _invert_matrix,
    fisher_z_test, _bic_orient_undirected, _marginal_variances,
    _dag_bic_score, _multivar_regression_residual,
    _regression_residual_var, _subsets, _has_cycle,
    _standalone_pc_validation,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures (unchanged API)
# ═══════════════════════════════════════════════════════════════════════════════

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
        """状态空间距离（保留用于向后兼容）。"""
        health_diff = abs(self.health_score - other.health_score)
        rate_diff   = abs(self.fulfillment_rate - other.fulfillment_rate)
        wiring_overlap = len(set(map(str, self.wired_edges)) &
                              set(map(str, other.wired_edges)))
        wiring_sim  = wiring_overlap / max(len(self.wired_edges), len(other.wired_edges), 1)
        return health_diff * 0.4 + rate_diff * 0.4 + (1 - wiring_sim) * 0.2


@dataclass
class CausalObservation:
    """One complete cycle observation (for building the SCM).

    Foundation-layer construct — used by any governance cycle (Path A, Path B,
    GovernanceLoop), not specific to any single line.
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
# CausalEngine — main public API (unchanged signatures)
# ═══════════════════════════════════════════════════════════════════════════════

class CausalEngine:
    """
    Pearl 因果推理引擎 — Genuine Pearl Level 2 & 3.

    This is (to our knowledge) the first production implementation of genuine
    Pearl Level 2 (interventional) and Level 3 (counterfactual) causal reasoning.

    Architecture:
      - CausalGraph: Explicit DAG with d-separation and backdoor criterion
      - BackdoorAdjuster: Real backdoor adjustment formula for do-calculus
      - StructuralEquation: Linear SCM with additive noise terms
      - CounterfactualEngine: Three-step abduction-action-prediction

    The Y*gov SCM has 4 variables (within-cycle DAG, acyclic):
      S (Suggestions) → W (Wiring) → O (Obligations) → H (Health)
                                    ↘                    ↗
                                     └──────────────────┘

    API (unchanged):
      observe()              — Feed CIEU cycle data to build the SCM
      do_wire_query()        — Level 2: P(H | do(W=w)) via backdoor adjustment
      counterfactual_query() — Level 3: SCM-based counterfactual
      needs_human_approval() — Autonomy decision based on causal confidence

    自主性保证：
    当 confidence >= confidence_threshold 时，Path A 不需要人工确认，
    直接执行因果推理推荐的方案。
    仅当 confidence < threshold 时才请求人工。
    """

    # The Y*gov causal DAG (within a single decision cycle).
    #
    # The full SCM is temporal: H_t → S_t → W_{t+1} → O_{t+1} → H_{t+1}.
    # Within one cycle, the DAG is acyclic (required by Pearl's framework):
    #   S → W → O → H, with W → H as a direct effect.
    # The H→S edge is cross-temporal (H_t causes S_{t+1}) and is handled
    # by conditioning on S as an observed exogenous input for each cycle.
    # Default Y*gov governance DAG (S→W→O→H).
    # Override via dag_edges parameter for non-governance domains.
    DEFAULT_DAG_EDGES = {
        'S': ['W'],        # Suggestions cause Wiring decisions
        'W': ['O', 'H'],   # Wiring causes Obligation fulfillment AND Health
        'O': ['H'],        # Obligations cause Health
        # H has no children within a single cycle (H→S is cross-temporal)
    }

    def __init__(
        self,
        confidence_threshold: float = 0.65,
        dag_edges: Optional[Dict[str, list]] = None,
    ):
        self.confidence_threshold = confidence_threshold
        self._observations: List[CausalObservation] = []

        # Pearl Level 2: Causal DAG (configurable for non-governance domains)
        effective_edges = dag_edges if dag_edges is not None else self.DEFAULT_DAG_EDGES
        self._causal_graph = CausalGraph(effective_edges)

        # Pearl Level 2: Backdoor adjustment
        self._adjuster = BackdoorAdjuster(self._causal_graph)

        # Pearl Level 3: Structural equations (derived from DAG)
        all_vars: Set[str] = set(effective_edges.keys())
        for children in effective_edges.values():
            all_vars.update(children)
        self._equations: Dict[str, StructuralEquation] = {}
        for var in sorted(all_vars):
            parents = [p for p, children in effective_edges.items() if var in children]
            self._equations[var] = StructuralEquation(var, parents)
        # Initialize with domain defaults
        for eq in self._equations.values():
            eq._set_domain_defaults()

        # Pearl Level 3: Counterfactual engine
        self._cf_engine = CounterfactualEngine(self._causal_graph, self._equations)

        # Observational data in SCM variable space
        self._scm_data: List[Dict[str, float]] = []

    # ── 更新观测（每次治理循环完成后调用）────────────────────────────────
    # TODO: Comment originally said "PathA cycle" but this is Foundation-layer code.
    # Should be generalized to support any governance loop cycle.
    def observe(
        self,
        health_before:  str,
        health_after:   str,
        obl_before:     Tuple[int, int],   # (fulfilled, total)
        obl_after:      Tuple[int, int],
        edges_before:   List[Tuple[str, str]],
        edges_after:    List[Tuple[str, str]],
        action_edges:   List[Tuple[str, str]],
        succeeded:      bool,
        cycle_id:       str,
        suggestion_type: Optional[str] = None,
    ) -> None:
        ob = CausalObservation(
            state_before=CausalState(
                wired_edges=edges_before, health=health_before,
                obl_fulfilled=obl_before[0], obl_total=obl_before[1],
                suggestion_type=suggestion_type,
            ),
            state_after=CausalState(
                wired_edges=edges_after, health=health_after,
                obl_fulfilled=obl_after[0], obl_total=obl_after[1],
            ),
            action_taken=action_edges,
            succeeded=succeeded,
            cycle_id=cycle_id,
        )
        self._observations.append(ob)

        # Convert observation to SCM variable space
        scm_point = self._observation_to_scm(ob)
        self._scm_data.append(scm_point)

        # Re-fit structural equations when we have enough data
        if len(self._scm_data) >= 2:
            self._fit_equations()

    def _observation_to_scm(self, ob: CausalObservation) -> Dict[str, float]:
        """
        Map a CausalObservation to SCM variable values.

        Mapping:
          W = wiring intensity (number of edges wired, normalized)
          O = obligation fulfillment rate after wiring
          H = health score after wiring
          S = suggestion quality (1.0 if suggestion led to wiring, else 0.5)
        """
        # W: wiring intensity [0, 1]
        n_edges = len(ob.action_taken)
        w = min(1.0, n_edges / max(1, 3))  # Normalize: 3+ edges = max

        # O: fulfillment rate after
        o = ob.state_after.fulfillment_rate

        # H: health score after
        h = ob.state_after.health_score

        # S: suggestion quality proxy
        s = 0.8 if ob.state_before.suggestion_type else 0.4

        return {'W': w, 'O': o, 'H': h, 'S': s}

    def _fit_equations(self) -> None:
        """Re-estimate structural equation parameters from accumulated data."""
        for eq in self._equations.values():
            eq.fit_from_data(self._scm_data)

    # ── Level 2：do-calculus 查询 ──────────────────────────────────────────
    def do_wire_query(
        self,
        src_id: str,
        tgt_id: str,
        current_state: Optional[CausalState] = None,
    ) -> DoCalcResult:
        """
        Query: P(H | do(W=w)) — What is the expected health effect of this wiring?

        Implementation: Genuine Pearl Level 2 using the backdoor adjustment formula.

        Pearl (2009), Theorem 3.3.2:
          P(H | do(W=w)) = Σ_s P(H | W=w, S=s) * P(S=s)

        Where S is the backdoor adjustment set for (W, H) in our DAG.
        (S blocks the backdoor path W ← S ← H through the cycle.)

        Falls back to structural inference when no observational data exists.

        Args:
            src_id: Source module ID
            tgt_id: Target module ID
            current_state: Optional current system state

        Returns:
            DoCalcResult with the causal prediction.
        """
        query = f"do(wire({src_id}→{tgt_id}))"

        # Find relevant observations (those that wired this specific edge)
        relevant = [
            ob for ob in self._observations
            if (src_id, tgt_id) in ob.action_taken
        ]

        if not relevant:
            # No direct historical evidence: structural inference
            return self._infer_from_obligation_chain(src_id, tgt_id, query)

        # ── Pearl Level 2: Backdoor Adjustment ──────────────────────────
        # Treatment: W (wiring), Outcome: H (health)
        # The DAG has path S → W → H and S → W → O → H
        # Backdoor set for (W, H): {S} blocks W ← S ← H

        # Treatment value: high wiring (we're asking "what if we wire this?")
        treatment_value = min(1.0, len(relevant[0].action_taken) / max(1, 3))

        # Use backdoor adjustment if we have SCM data
        if self._scm_data:
            expected_h, bd_confidence = self._adjuster.adjust(
                treatment='W',
                outcome='H',
                treatment_value=treatment_value,
                data=self._scm_data,
            )

            # Map continuous health to label
            predicted_health = self._score_to_health_label(expected_h)

            # Confidence combines backdoor estimate quality with evidence count
            evidence_factor = min(1.0, len(relevant) / 5.0)
            confidence = 0.6 * bd_confidence + 0.4 * evidence_factor

        else:
            # SCM data not yet available: use observation-based estimate
            deltas = [ob.state_after.health_score - ob.state_before.health_score
                      for ob in relevant]
            avg_delta = sum(deltas) / len(deltas)
            base_health = (current_state.health_score if current_state
                           else relevant[-1].state_before.health_score)
            expected_h = max(0.0, min(1.0, base_health + avg_delta))
            predicted_health = self._score_to_health_label(expected_h)
            confidence = min(1.0, len(relevant) / 5.0) * 0.5

        # Causal chain documenting the Pearl reasoning
        backdoor_set = self._causal_graph.find_backdoor_set('W', 'H')
        causal_chain = [
            f"do(wire({src_id}→{tgt_id}))",
            f"→ backdoor adjustment set: {backdoor_set or '∅'}",
            f"→ P(H|do(W={treatment_value:.2f})) = {expected_h:.3f}",
            f"→ health: {predicted_health} (confidence={confidence:.2f})",
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
        Counterfactual query using Pearl's three-step procedure:
        "In the same initial conditions as cycle X, what would have happened
         if we had chosen different wiring?"

        Pearl (2009), Chapter 7:
          Step 1 — Abduction: From the observed cycle data, infer noise terms
                   U_W, U_O, U_H, U_S that explain what we saw.
          Step 2 — Action: Replace W's equation with do(W=w') for the
                   alternative wiring.
          Step 3 — Prediction: Propagate through the SCM with inferred noise
                   to get the counterfactual health.

        This is EXACT for our linear SCM. No nearest-neighbor approximation.

        Args:
            failed_cycle_id: ID of the cycle to reason about
            alternative_edges: The alternative wiring we wish we had done

        Returns:
            DoCalcResult with counterfactual prediction and gain.
        """
        # Find the target cycle
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

        # Convert observed cycle to SCM variable space
        observed = self._observation_to_scm(failed)

        # Counterfactual intervention: different wiring
        cf_wiring = min(1.0, len(alternative_edges) / max(1, 3))

        # ── Pearl Level 3: Three-Step Counterfactual ──────────────────

        # Step 1: Abduction — infer noise terms from what actually happened
        noise_terms = self._cf_engine.abduction(observed)

        # Step 2: Action — set do(W = cf_wiring)
        interventions = self._cf_engine.action({'W': cf_wiring})

        # Step 3: Prediction — propagate with inferred noise
        cf_values = self._cf_engine.prediction(noise_terms, interventions)

        # Extract counterfactual health
        cf_health_score = cf_values['H']
        actual_health_score = observed['H']

        # Counterfactual gain
        cf_gain = cf_health_score - actual_health_score

        predicted_health = self._score_to_health_label(cf_health_score)

        # Confidence based on:
        # 1. How well our SCM fits the data (R^2 proxy)
        # 2. How much data we have
        n = len(self._scm_data)
        data_confidence = min(1.0, n / 5.0)
        # Noise magnitude: smaller noise = better fit = higher confidence
        noise_magnitude = sum(abs(v) for v in noise_terms.values()) / max(len(noise_terms), 1)
        fit_confidence = max(0.0, 1.0 - noise_magnitude)
        confidence = 0.5 * data_confidence + 0.5 * fit_confidence

        causal_chain = [
            f"observed: W={observed['W']:.2f}, O={observed['O']:.2f}, "
            f"H={observed['H']:.2f}, S={observed['S']:.2f}",
            f"abduction: U_W={noise_terms.get('W', 0):.3f}, "
            f"U_O={noise_terms.get('O', 0):.3f}, "
            f"U_H={noise_terms.get('H', 0):.3f}, "
            f"U_S={noise_terms.get('S', 0):.3f}",
            f"action: do(W={cf_wiring:.2f})",
            f"prediction: H_cf={cf_health_score:.3f} "
            f"(actual={actual_health_score:.3f}, gain={cf_gain:+.3f})",
            f"predicted: {predicted_health}",
        ]

        return DoCalcResult(
            query=f"cf(cycle={failed_cycle_id}, alt={alternative_edges})",
            predicted_health=predicted_health,
            confidence=confidence,
            causal_chain=causal_chain,
            evidence_count=len(self._scm_data),
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
        predicted = "stable" if confidence >= 0.7 else "degraded" if confidence >= 0.5 else "critical"

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

    @staticmethod
    def _score_to_health_label(score: float) -> str:
        """Map continuous health score [0,1] to categorical label."""
        if score >= 0.8:
            return "healthy"
        elif score >= 0.5:
            return "stable"
        elif score >= 0.2:
            return "degraded"
        else:
            return "critical"

    @property
    def observation_count(self) -> int:
        return len(self._observations)

    @property
    def causal_graph(self) -> CausalGraph:
        """Expose the causal DAG for inspection."""
        return self._causal_graph

    @property
    def structural_equations(self) -> Dict[str, StructuralEquation]:
        """Expose fitted structural equations for inspection."""
        return dict(self._equations)

    @property
    def counterfactual_engine(self) -> CounterfactualEngine:
        """Expose the counterfactual engine for direct use."""
        return self._cf_engine

    def summary(self) -> str:
        if not self._observations:
            return "CausalEngine: 0 observations"
        success_rate = sum(1 for o in self._observations if o.succeeded) / len(self._observations)
        return (f"CausalEngine: {len(self._observations)} obs, "
                f"success_rate={success_rate:.1%}, "
                f"threshold={self.confidence_threshold:.2f}")

    # ── PC Algorithm: Causal Structure Discovery ─────────────────────────

    def discover_structure(
        self, data: List[Dict[str, float]], alpha: float = 0.05,
        temporal_order: Optional[List[str]] = None,
    ) -> CausalGraph:
        """
        Discover causal structure from data using the PC algorithm.

        Returns a CausalGraph that can replace the hand-specified one.

        Args:
            data: List of observations, each mapping variable names to float values.
            alpha: Significance level for conditional independence tests.
            temporal_order: Optional list of variables in causal time order.

        Returns:
            A CausalGraph inferred from the data.
        """
        discovery = CausalDiscovery(alpha=alpha)
        return discovery.run(data, temporal_order=temporal_order)

    def cieu_to_scm_data(self, cieu_records: List[dict]) -> List[Dict[str, float]]:
        """
        Convert raw CIEU records to CYCLE-LEVEL SCM observations (W, O, H, S).

        The PC algorithm needs one data point per governance cycle, not per
        raw CIEU record.  A cycle is a sequence of events:
          suggestion → check → wire/deny → health assessment.

        For each cycle this method computes:
          W: was a wiring action attempted? (0.0/0.5/1.0)
          O: obligation fulfillment ratio at end of cycle (0–1)
          H: allow/deny ratio within the cycle's events
          S: suggestion confidence that triggered the cycle

        Non-cycle records (doctor self-tests, isolated events) are filtered.

        Args:
            cieu_records: Raw audit records from CIEU.

        Returns:
            List of cycle-level dicts with keys W, O, H, S in [0, 1].
        """
        # ── Step 1: Group records into cycles ──────────────────────────
        cycles = self._group_into_cycles(cieu_records)

        # ── Step 2: Convert each cycle to one SCM data point ──────────
        result: List[Dict[str, float]] = []
        for cycle in cycles:
            point = self._cycle_to_scm_point(cycle)
            if point is not None:
                result.append(point)
        return result

    # ── Cycle grouping helpers ────────────────────────────────────────

    # Event types that mark the START of a new governance cycle
    _CYCLE_START_TYPES = frozenset([
        "suggestion", "governance_suggestion", "suggest",
        "proposal", "check_start", "scan_start",
    ])
    # Event types that mark wiring actions
    _WIRING_TYPES = frozenset([
        "wire", "wiring", "activate", "connect",
        "deny", "reject", "block",
    ])
    # Event types belonging to doctor / self-test (not real cycles)
    _NOISE_TYPES = frozenset([
        "doctor_check", "self_test", "heartbeat", "ping",
    ])

    def _group_into_cycles(
        self, records: List[dict],
    ) -> List[List[dict]]:
        """
        Group CIEU records into governance cycles.

        Heuristic: a new cycle starts when we see a suggestion/check event,
        or when the cycle_id field changes.  Records with noise event types
        are dropped entirely.
        """
        cycles: List[List[dict]] = []
        current: List[dict] = []

        prev_cycle_id: Optional[str] = None

        for rec in records:
            event_type = str(rec.get("event_type", "")).lower()

            # Filter out non-cycle noise records
            if event_type in self._NOISE_TYPES:
                continue

            # Detect cycle boundary via explicit cycle_id
            rec_cycle_id = rec.get("cycle_id") or rec.get("request_id")
            if rec_cycle_id and rec_cycle_id != prev_cycle_id and current:
                cycles.append(current)
                current = []
            prev_cycle_id = rec_cycle_id

            # Detect cycle boundary via event type (suggestion = new cycle)
            if event_type in self._CYCLE_START_TYPES and current:
                cycles.append(current)
                current = []

            current.append(rec)

        # Flush the last cycle
        if current:
            cycles.append(current)

        return cycles

    def _cycle_to_scm_point(
        self, cycle_records: List[dict],
    ) -> Optional[Dict[str, float]]:
        """
        Convert a single cycle's records into one SCM data point.

        Returns None if the cycle is too thin to be meaningful (< 1 event
        with a decision).
        """
        if not cycle_records:
            return None

        # ── W: wiring action attempted? ────────────────────────────────
        wire_attempted = False
        wire_succeeded = False
        for rec in cycle_records:
            et = str(rec.get("event_type", "")).lower()
            decision = str(rec.get("decision", "")).lower()
            if et in self._WIRING_TYPES or decision in ("allow", "deny"):
                wire_attempted = True
                succeeded = rec.get("succeeded", None)
                if succeeded is True or decision == "allow":
                    wire_succeeded = True

        if wire_succeeded:
            w = 1.0
        elif wire_attempted:
            w = 0.5
        else:
            w = 0.0

        # ── O: obligation status at end of cycle ──────────────────────
        obl_fulfilled = 0
        obl_total = 0
        for rec in cycle_records:
            f = rec.get("obl_fulfilled", 0)
            t = rec.get("obl_total", 0)
            if t > 0:
                obl_fulfilled = f
                obl_total = t
            # Also check violations as inverse proxy
            violations = rec.get("violations", rec.get("result", {}).get("violations", []))
            if isinstance(violations, list) and violations and obl_total == 0:
                obl_total = max(len(violations), 1)
                obl_fulfilled = 0
        o = obl_fulfilled / max(obl_total, 1)

        # ── H: health change during cycle (allow/deny ratio) ──────────
        allow_count = 0
        deny_count = 0
        for rec in cycle_records:
            decision = str(rec.get("decision", "")).lower()
            if decision in ("allow", "inconclusive"):
                allow_count += 1
            elif decision in ("deny", "block", "reject"):
                deny_count += 1
        total_decisions = allow_count + deny_count
        h = allow_count / max(total_decisions, 1)

        # ── S: suggestion confidence that triggered this cycle ────────
        s = 0.5  # default if no explicit confidence found
        for rec in cycle_records:
            conf = rec.get("confidence", rec.get("suggestion_confidence"))
            if conf is not None:
                try:
                    s = float(conf)
                except (TypeError, ValueError):
                    pass
                break  # Use the first confidence we find
            # Fallback: drift_detected boosts suggestion signal
            if rec.get("drift_detected"):
                s = 0.7

        return {"W": w, "O": o, "H": h, "S": s}

    def count_cycle_observations(self) -> int:
        """
        Return the number of real cycle-level SCM observations accumulated.

        This is the effective sample size for the PC algorithm; raw CIEU
        record counts would overstate it.
        """
        return len(self._scm_data)

    def learn_structure(
        self, min_observations: int = 30, alpha: float = 0.05,
    ) -> Optional[CausalGraph]:
        """
        Auto-trigger causal structure discovery when enough data exists.

        When we have >= min_observations cycle-level SCM data points, run
        the PC algorithm to discover the causal DAG from data and compare
        it with the hand-specified DAG.

        If the discovered DAG is close (SHD <= 2): boost confidence and
        log "structure confirmed".
        If divergent (SHD > 2): log "structure divergence detected" and
        flag for human review.

        Args:
            min_observations: Minimum cycle observations required.
            alpha: Significance level for conditional independence tests.

        Returns:
            The discovered CausalGraph, or None if not enough data.
        """
        n = len(self._scm_data)
        if n < min_observations:
            return None

        # Run PC algorithm on accumulated cycle-level data
        # Use temporal ordering from governance cycle architecture: S→W→O→H
        discovered = self.discover_structure(
            self._scm_data, alpha=alpha,
            temporal_order=['S', 'W', 'O', 'H'],
        )

        # Compare discovered vs hand-specified DAG
        comparison = self.validate_discovered_vs_specified(
            discovered, self._causal_graph,
        )
        shd = comparison["shd"]

        if shd <= 2:
            # Structure confirmed — boost confidence threshold downward
            # (i.e., we trust the causal model more, so we need less human
            # oversight). Clamp so threshold never goes below 0.3.
            self.confidence_threshold = max(
                0.3, self.confidence_threshold - 0.1,
            )
            self._structure_validation = {
                "status": "confirmed",
                "shd": shd,
                "observations": n,
                "comparison": comparison,
            }
        else:
            # Structure divergence — flag for review
            self._structure_validation = {
                "status": "divergence_detected",
                "shd": shd,
                "observations": n,
                "comparison": comparison,
            }

        return discovered

    def validate_discovered_vs_specified(
        self, discovered: CausalGraph, specified: CausalGraph
    ) -> dict:
        """
        Compare discovered DAG with hand-specified DAG.

        Returns a dict with:
          - matching_edges: edges present in both
          - missing_edges: in specified but not discovered
          - extra_edges: in discovered but not specified
          - shd: Structural Hamming Distance (total mismatches)
        """
        def _edge_set(g: CausalGraph) -> Set[Tuple[str, str]]:
            edges: Set[Tuple[str, str]] = set()
            for node in g.nodes:
                for child in g.children(node):
                    edges.add((node, child))
            return edges

        spec_edges = _edge_set(specified)
        disc_edges = _edge_set(discovered)

        matching = spec_edges & disc_edges
        missing = spec_edges - disc_edges
        extra = disc_edges - spec_edges

        return {
            "matching_edges": sorted(matching),
            "missing_edges": sorted(missing),
            "extra_edges": sorted(extra),
            "shd": len(missing) + len(extra),
        }


if __name__ == "__main__":
    _standalone_pc_validation()

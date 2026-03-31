# Layer: Path B
"""
ystar.path_b.external_governance_loop — External Observation Loop (Layer 3)

Mirrors governance_loop.py but for external agents.

Key difference from internal governance:
- Internal (Path A): observes Y*gov's own ModuleGraph, derives suggestions for self-improvement
- External (Path B): observes external agents' actions, derives constraints for external governance

Integration design:
    ExternalObservation
        → metalearning.learn() discovers violation patterns
        → CausalEngine.counterfactual_query() predicts constraint effectiveness
        → Combined confidence: BOTH must agree for auto-apply
        → Low confidence from either → flag for human review

This is the "who governs the governors" solution:
Path B uses the SAME metalearning + causal reasoning that Path A uses,
but directed at external agents instead of internal modules.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
import time

from ystar.path_b.path_b_agent import (
    ExternalObservation,
    ConstraintBudget,
    observation_to_constraint,
)
from ystar.governance.metalearning import (
    learn,
    CallRecord,
    MetalearnResult,
    ContractQuality,
    AdaptiveCoefficients,
)
from ystar.governance.causal_engine import CausalEngine, DoCalcResult
from ystar.kernel.dimensions import IntentContract


# ── External Governance Observation ───────────────────────────────────────────
@dataclass
class ExternalGovernanceObservation:
    """
    Aggregated observation of external agent behavior over a time window.

    Analog to GovernanceObservation in governance_loop.py, but for external agents.

    Fields:
        agent_id:           external agent identifier
        period_label:       time window label (e.g., "2026-03-26T10:00-11:00")
        violation_rate:     violations / total observations
        severity_avg:       average violation severity
        compliance_rate:    observations without violations / total
        observation_count:  total observations in this period
        pattern_summary:    discovered violation patterns (from metalearning)
    """
    agent_id:           str
    period_label:       str = ""
    violation_rate:     float = 0.0
    severity_avg:       float = 0.0
    compliance_rate:    float = 1.0
    observation_count:  int = 0
    pattern_summary:    Dict[str, int] = field(default_factory=dict)
    timestamp:          float = field(default_factory=time.time)

    def is_healthy(self) -> bool:
        """Quick health check: is this external agent behaving well?"""
        return (
            self.compliance_rate >= 0.9
            and self.severity_avg <= 0.3
        )

    def needs_constraint(self) -> bool:
        """Does this external agent need a constraint?"""
        return (
            self.violation_rate > 0.1
            or self.severity_avg > 0.6
        )

    def to_dict(self) -> dict:
        return {
            "agent_id":           self.agent_id,
            "period_label":       self.period_label,
            "violation_rate":     self.violation_rate,
            "severity_avg":       self.severity_avg,
            "compliance_rate":    self.compliance_rate,
            "observation_count":  self.observation_count,
            "is_healthy":         self.is_healthy(),
            "needs_constraint":   self.needs_constraint(),
        }


# ── Constraint Suggestion with Combined Confidence ────────────────────────────
@dataclass
class ExternalConstraintSuggestion:
    """
    A constraint suggestion for an external agent, with combined confidence
    from metalearning AND causal reasoning.

    This is the key integration point: suggestions need BOTH signals to auto-apply.

    Fields:
        agent_id:              target external agent
        constraint:            proposed IntentContract
        metalearning_confidence: from metalearning.learn() (pattern frequency)
        causal_confidence:     from CausalEngine (counterfactual prediction)
        combined_confidence:   min(metalearning, causal) — conservative combination
        auto_apply:            True if both confidences are high
        rationale:             human-readable explanation
    """
    agent_id:                str
    constraint:              IntentContract
    metalearning_confidence: float = 0.0
    causal_confidence:       float = 0.0
    combined_confidence:     float = 0.0
    auto_apply:              bool = False
    rationale:               str = ""
    evidence_count:          int = 0

    def __post_init__(self):
        # Combined confidence: conservative (min of both)
        # Both signals must agree for high confidence
        self.combined_confidence = min(
            self.metalearning_confidence,
            self.causal_confidence,
        )

    def needs_human_review(self) -> bool:
        """Does this suggestion need human review before applying?"""
        return not self.auto_apply or self.combined_confidence < 0.65


# ── External Governance Loop ──────────────────────────────────────────────────
class ExternalGovernanceLoop:
    """
    External agent governance loop.

    Integrates metalearning + causal reasoning to generate constraint suggestions
    for external agents.

    Architecture:
        1. Collect ExternalObservations (external agent CIEU-like records)
        2. Feed to metalearning.learn() → discover violation patterns
        3. Feed to CausalEngine → counterfactual: "would constraint have prevented violation?"
        4. Combine both signals → generate suggestions
        5. High confidence from BOTH → auto-apply
        6. Low confidence from either → flag for human review

    Usage:
        loop = ExternalGovernanceLoop(cieu_store)

        # Feed observations
        loop.observe(ExternalObservation(...))
        loop.observe(ExternalObservation(...))

        # Generate suggestions
        suggestions = loop.generate_suggestions()

        for sugg in suggestions:
            if sugg.auto_apply:
                apply_constraint(sugg.agent_id, sugg.constraint)
            else:
                request_human_review(sugg)
    """

    def __init__(
        self,
        cieu_store,
        confidence_threshold: float = 0.65,
        max_observations:     int = 1000,
    ):
        self.cieu_store = cieu_store
        self.confidence_threshold = confidence_threshold
        self.max_observations = max_observations

        # Observation history (windowed)
        self._observations: List[ExternalObservation] = []

        # Metalearning integration
        self._coefficients = AdaptiveCoefficients()

        # Causal reasoning integration
        self._causal_engine = CausalEngine(confidence_threshold=confidence_threshold)

        # Budget tracking
        self._budgets: Dict[str, ConstraintBudget] = {}

    def observe(self, observation: ExternalObservation) -> None:
        """
        Record an external observation.
        This is the input stream for the governance loop.
        """
        self._observations.append(observation)

        # Window: keep only recent observations
        if len(self._observations) > self.max_observations:
            self._observations = self._observations[-self.max_observations:]

        # Initialize budget for new agents
        if observation.agent_id not in self._budgets:
            self._budgets[observation.agent_id] = ConstraintBudget(
                agent_id=observation.agent_id
            )

        # Feed to causal engine (build SCM)
        self._feed_to_causal_engine(observation)

    def _feed_to_causal_engine(self, obs: ExternalObservation) -> None:
        """Feed observation to CausalEngine to build structural causal model."""
        # CausalEngine expects health metrics — map violation rate to health
        health_before = "healthy" if not obs.has_violation() else "degraded"
        health_after = health_before  # Will be updated in next observation

        # For external agents, "edges" are active constraints
        active_constraints = [
            (obs.agent_id, c.name) for c in [obs.contract] if c
        ]

        self._causal_engine.observe(
            health_before=health_before,
            health_after=health_after,
            obl_before=(0, 1),  # Simplified: 1 obligation = "behave correctly"
            obl_after=(0 if obs.has_violation() else 1, 1),
            edges_before=[],
            edges_after=active_constraints,
            action_edges=active_constraints,
            succeeded=not obs.has_violation(),
            cycle_id=obs.observation_id,
            suggestion_type="external_constraint",
        )

    def generate_suggestions(self) -> List[ExternalConstraintSuggestion]:
        """
        Generate constraint suggestions for external agents.

        This is where metalearning + causal reasoning integrate.

        Steps:
        1. Group observations by agent
        2. For each agent with violations:
           a. Convert observations to CallRecords (metalearning input format)
           b. Call metalearning.learn() → get violation patterns + confidence
           c. Call CausalEngine.counterfactual_query() → get causal confidence
           d. Combine both → generate suggestion
        3. Return suggestions sorted by combined confidence
        """
        suggestions = []

        # Group by agent
        by_agent: Dict[str, List[ExternalObservation]] = {}
        for obs in self._observations:
            if obs.agent_id not in by_agent:
                by_agent[obs.agent_id] = []
            by_agent[obs.agent_id].append(obs)

        # Generate suggestions for each agent
        for agent_id, obs_list in by_agent.items():
            # Filter: only agents with violations
            violations = [o for o in obs_list if o.has_violation()]
            if not violations:
                continue

            # Get budget
            budget = self._budgets.get(agent_id)
            if not budget or not budget.can_tighten():
                continue  # Insufficient budget

            # Step 1: Metalearning — discover violation patterns
            metalearning_result = self._run_metalearning(agent_id, obs_list)
            if not metalearning_result or not metalearning_result.candidates:
                continue

            # Step 2: Causal reasoning — predict constraint effectiveness
            causal_result = self._run_causal_reasoning(agent_id, violations)

            # Step 3: Combine confidences
            # Metalearning confidence: from candidate fp_rate
            best_candidate = min(
                metalearning_result.candidates,
                key=lambda c: c.fp_rate
            )
            ml_confidence = 1.0 - best_candidate.fp_rate

            # Causal confidence: from counterfactual query
            causal_confidence = causal_result.confidence if causal_result else 0.0

            # Step 4: Generate constraint
            if metalearning_result.contract_additions:
                constraint = metalearning_result.contract_additions
            else:
                # Fallback: derive from observation
                constraint = observation_to_constraint(
                    violations[-1],
                    violations,
                    budget,
                    self.confidence_threshold,
                )

            if not constraint:
                continue

            # Step 5: Create suggestion
            combined_conf = min(ml_confidence, causal_confidence)
            auto_apply = (
                ml_confidence >= self.confidence_threshold
                and causal_confidence >= self.confidence_threshold
            )

            rationale_parts = [
                f"metalearning: {ml_confidence:.2f} ({len(violations)} violations)",
                f"causal: {causal_confidence:.2f}",
            ]
            if causal_result and causal_result.counterfactual_gain:
                rationale_parts.append(
                    f"predicted gain: {causal_result.counterfactual_gain:.2%}"
                )

            suggestion = ExternalConstraintSuggestion(
                agent_id=agent_id,
                constraint=constraint,
                metalearning_confidence=ml_confidence,
                causal_confidence=causal_confidence,
                combined_confidence=combined_conf,
                auto_apply=auto_apply,
                rationale=" | ".join(rationale_parts),
                evidence_count=len(violations),
            )

            suggestions.append(suggestion)

        # Sort by combined confidence (descending)
        suggestions.sort(key=lambda s: s.combined_confidence, reverse=True)
        return suggestions

    def _run_metalearning(
        self,
        agent_id: str,
        observations: List[ExternalObservation],
    ) -> Optional[MetalearnResult]:
        """
        Run metalearning.learn() on external observations.

        Convert ExternalObservations to CallRecords, then call learn().
        """
        # Convert to CallRecords
        call_records = []
        for i, obs in enumerate(observations):
            record = CallRecord(
                seq=i,
                func_name=obs.action_type,
                params=obs.params,
                result=obs.result,
                violations=obs.violations,
                intent_contract=obs.contract,
                applied_contract=obs.contract,
                timestamp=obs.timestamp,
            )
            call_records.append(record)

        if not call_records:
            return None

        # Call metalearning
        try:
            result = learn(
                call_records,
                existing_contract=IntentContract(name=f"external:{agent_id}"),
                coefficients=self._coefficients,
            )
            return result
        except Exception:
            return None

    def _run_causal_reasoning(
        self,
        agent_id: str,
        violations: List[ExternalObservation],
    ) -> Optional[DoCalcResult]:
        """
        Run causal reasoning (counterfactual query) for external agent.

        Question: "If we had applied constraint C, would the violation have been prevented?"
        """
        if not violations:
            return None

        # Take most recent violation
        recent_violation = violations[-1]

        # Hypothetical constraint: what if we had blocked the violating action?
        # Use do_wire_query as analog: "wiring" a constraint to the agent
        result = self._causal_engine.do_wire_query(
            src_id=agent_id,
            tgt_id="constraint_applied",
        )

        return result

    def aggregate_observations(self, agent_id: str) -> ExternalGovernanceObservation:
        """
        Aggregate observations for a single agent into a summary.

        Used for monitoring dashboards and reporting.
        """
        agent_obs = [o for o in self._observations if o.agent_id == agent_id]
        if not agent_obs:
            return ExternalGovernanceObservation(
                agent_id=agent_id,
                period_label="empty",
            )

        violations = [o for o in agent_obs if o.has_violation()]
        violation_rate = len(violations) / len(agent_obs) if agent_obs else 0.0
        compliance_rate = 1.0 - violation_rate

        severity_sum = sum(o.severity_score() for o in violations)
        severity_avg = severity_sum / len(violations) if violations else 0.0

        # Pattern summary: which dimensions are most violated?
        pattern_counts: Dict[str, int] = {}
        for obs in violations:
            for v in obs.violations:
                dim = getattr(v, 'dimension', 'unknown')
                pattern_counts[dim] = pattern_counts.get(dim, 0) + 1

        return ExternalGovernanceObservation(
            agent_id=agent_id,
            period_label=f"observations_{len(agent_obs)}",
            violation_rate=violation_rate,
            severity_avg=severity_avg,
            compliance_rate=compliance_rate,
            observation_count=len(agent_obs),
            pattern_summary=pattern_counts,
        )

    def summary(self) -> dict:
        """Return summary statistics for the external governance loop."""
        agents = set(o.agent_id for o in self._observations)
        violations = [o for o in self._observations if o.has_violation()]

        return {
            "total_observations": len(self._observations),
            "total_violations":   len(violations),
            "violation_rate":     len(violations) / len(self._observations)
                                  if self._observations else 0.0,
            "active_agents":      len(agents),
            "causal_observations": self._causal_engine.observation_count,
            "budget_summary":     {
                agent_id: budget.current_budget
                for agent_id, budget in self._budgets.items()
            },
        }

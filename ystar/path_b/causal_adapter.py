# Layer: Path B
"""
ystar.path_b.causal_adapter -- Maps Path B external governance events to CausalEngine SCM observations.

Pearl L2-L3 integration: Path B governance actions are mapped to the Foundation-layer
CausalEngine's SCM variables (W, O, H, S) so that interventional (L2) and
counterfactual (L3) reasoning can be applied to external governance decisions.

Mapping rationale:
  W (Wiring/Treatment) = governance action intensity (warn..disconnect)
  O (Obligation fulfillment) = compliance rate after action
  H (Health) = violation reduction (before vs after)
  S (Suggestion quality) = observation severity (drives the action)
"""
from __future__ import annotations
from typing import Tuple


class PathBCausalAdapter:
    """Maps Path B external governance events to CausalEngine SCM observations."""

    # Action intensity mapping: stronger actions -> higher W values
    _ACTION_W_MAP = {
        "apply_constraint":     0.25,
        "verify_compliance":    0.15,
        "downgrade_contract":   0.50,
        "freeze_session":       0.75,
        "disconnect_agent":     1.00,
        "require_human_review": 0.10,
        # Shorthand labels used by escalation ladder
        "warn":       0.25,
        "downgrade":  0.50,
        "freeze":     0.75,
        "disconnect": 1.00,
    }

    @staticmethod
    def map_action_to_W(action) -> float:
        """Map an ExternalGovernanceAction (or string) to treatment value W.

        warn=0.25, downgrade=0.5, freeze=0.75, disconnect=1.0
        """
        if hasattr(action, 'value'):
            key = action.value
        else:
            key = str(action)
        return PathBCausalAdapter._ACTION_W_MAP.get(key, 0.25)

    @staticmethod
    def map_compliance_to_O(compliant: bool, violation_count: int) -> float:
        """Compliance fulfillment rate.

        Returns a value in [0, 1] representing how well the external agent
        fulfilled the constraint obligation.
        """
        if compliant:
            return 1.0
        # Partial compliance: fewer violations = higher O
        if violation_count <= 0:
            return 1.0
        return max(0.0, 1.0 - (violation_count * 0.2))

    @staticmethod
    def map_health(before_violations: int, after_violations: int) -> Tuple[str, str]:
        """Map violation counts to health labels (before, after).

        Fewer violations = healthier.
        """
        def _to_label(v: int) -> str:
            if v == 0:
                return "healthy"
            elif v <= 1:
                return "stable"
            elif v <= 3:
                return "degraded"
            else:
                return "critical"
        return _to_label(before_violations), _to_label(after_violations)

    def to_observation_kwargs(self, cycle_data: dict) -> dict:
        """Produce kwargs for CausalEngine.observe().

        Args:
            cycle_data: dict with keys:
                - action: ExternalGovernanceAction or str
                - compliant: bool
                - violation_count_before: int
                - violation_count_after: int
                - cycle_id: str
                - edges_wired: list of (src, tgt) tuples (optional)

        Returns:
            Dict of kwargs suitable for CausalEngine.observe().
        """
        action = cycle_data.get("action", "warn")
        compliant = cycle_data.get("compliant", False)
        v_before = cycle_data.get("violation_count_before", 0)
        v_after = cycle_data.get("violation_count_after", 0)
        cycle_id = cycle_data.get("cycle_id", "unknown")
        edges = cycle_data.get("edges_wired", [])

        health_before, health_after = self.map_health(v_before, v_after)
        obl_rate = self.map_compliance_to_O(compliant, v_after)

        # Map to CausalEngine.observe() kwargs
        return {
            "health_before": health_before,
            "health_after": health_after,
            "obl_before": (0, max(1, v_before)),
            "obl_after": (int(obl_rate * max(1, v_before)), max(1, v_before)),
            "edges_before": [],
            "edges_after": edges,
            "action_edges": edges if edges else [("path_b", action if isinstance(action, str) else action.value)],
            "succeeded": compliant or (v_after < v_before),
            "cycle_id": f"path_b_{cycle_id}",
            "suggestion_type": f"path_b_governance_{action if isinstance(action, str) else action.value}",
        }

# Layer: Foundation
"""
ystar.governance.backdoor_adjuster — Pearl Level 2 backdoor adjustment formula

Split from causal_engine.py for modularity.

Implements the backdoor adjustment formula (Pearl, 2009, Theorem 3.3.2):
  P(Y=y | do(X=x)) = Σ_z P(Y=y | X=x, Z=z) * P(Z=z)
"""
from __future__ import annotations
from typing import List, Dict, Tuple

from ystar.governance.causal_graph import CausalGraph


class BackdoorAdjuster:
    """
    Implements the backdoor adjustment formula (Pearl, 2009, Theorem 3.3.2):

      P(Y=y | do(X=x)) = Σ_z P(Y=y | X=x, Z=z) * P(Z=z)

    Where Z is a valid backdoor adjustment set identified from the causal DAG.

    This transforms an interventional query (Level 2) into a computation
    over observational data (Level 1), which is the key insight of do-calculus.

    For continuous variables, we discretize into bins and compute the sum.
    For our 4-variable system with bounded [0,1] values, this is exact
    up to discretization granularity.
    """

    # Health label boundaries for discretization
    HEALTH_BINS = {
        'critical': (0.0, 0.2),
        'degraded': (0.2, 0.5),
        'stable':   (0.5, 0.8),
        'healthy':  (0.8, 1.01),
    }

    def __init__(self, graph: CausalGraph, n_bins: int = 10):
        self.graph = graph
        self.n_bins = n_bins

    def adjust(
        self,
        treatment: str,
        outcome: str,
        treatment_value: float,
        data: List[Dict[str, float]],
    ) -> Tuple[float, float]:
        """
        Compute P(Y | do(X=x)) using the backdoor adjustment formula.

        Pearl (2009), Theorem 3.3.2:
        If Z satisfies the backdoor criterion relative to (X, Y) in DAG G, then:
          P(Y | do(X=x)) = Σ_z P(Y | X=x, Z=z) * P(Z=z)

        This is the REAL do-calculus, not a weighted heuristic.

        Args:
            treatment: Treatment variable name (e.g., 'W')
            outcome: Outcome variable name (e.g., 'H')
            treatment_value: Value to set treatment to
            data: Observational data [{var: value, ...}, ...]

        Returns:
            (expected_outcome, confidence) where confidence reflects
            the quality of the estimate (based on data coverage).
        """
        if not data:
            return 0.5, 0.0

        # Find valid backdoor adjustment set
        z_set = self.graph.find_backdoor_set(treatment, outcome)
        if z_set is None:
            # No valid adjustment set: fall back to conditional
            return self._conditional_mean(outcome, treatment, treatment_value, data)

        if not z_set:
            # Empty adjustment set: no confounders to adjust for
            # P(Y|do(X=x)) = P(Y|X=x)
            return self._conditional_mean(outcome, treatment, treatment_value, data)

        # Non-empty adjustment set: apply backdoor formula
        # Discretize Z variables into bins
        z_list = sorted(z_set)

        # Build joint distribution over Z
        z_bins = self._discretize_z(z_list, data)

        # Compute: Σ_z P(Y | X=x, Z=z) * P(Z=z)
        total_weight = 0.0
        weighted_outcome = 0.0
        data_points_used = 0

        for z_bin, z_count in z_bins.items():
            p_z = z_count / len(data)

            # Filter data matching X≈x and Z≈z
            matching = self._filter_data(
                data, treatment, treatment_value, z_list, z_bin
            )

            if matching:
                # E[Y | X=x, Z=z]
                mean_y = sum(d[outcome] for d in matching) / len(matching)
                weighted_outcome += mean_y * p_z
                total_weight += p_z
                data_points_used += len(matching)

        if total_weight < 1e-9:
            # No matching data: fall back
            return self._conditional_mean(outcome, treatment, treatment_value, data)

        expected = weighted_outcome / total_weight

        # Confidence based on data coverage and sample size
        coverage = total_weight  # How much of P(Z) space we covered
        sample_confidence = min(1.0, data_points_used / max(5.0, len(data) * 0.3))
        confidence = coverage * sample_confidence

        return expected, confidence

    def _conditional_mean(
        self, outcome: str, condition_var: str,
        condition_val: float, data: List[Dict[str, float]]
    ) -> Tuple[float, float]:
        """Simple conditional mean E[Y | X≈x] as fallback."""
        tolerance = 0.3
        matching = [
            d for d in data
            if abs(d.get(condition_var, 0.0) - condition_val) <= tolerance
        ]
        if not matching:
            # Broader tolerance
            matching = [
                d for d in data
                if abs(d.get(condition_var, 0.0) - condition_val) <= 0.6
            ]
        if not matching:
            return 0.5, 0.0

        mean = sum(d[outcome] for d in matching) / len(matching)
        confidence = min(1.0, len(matching) / max(3.0, len(data) * 0.2))
        return mean, confidence

    def _discretize_z(
        self, z_vars: List[str], data: List[Dict[str, float]]
    ) -> Dict[Tuple[int, ...], int]:
        """Discretize Z variables into bins and count occurrences."""
        bins: Dict[Tuple[int, ...], int] = {}
        for d in data:
            key = tuple(
                min(self.n_bins - 1, int(d.get(v, 0.0) * self.n_bins))
                for v in z_vars
            )
            bins[key] = bins.get(key, 0) + 1
        return bins

    def _filter_data(
        self, data: List[Dict[str, float]],
        treatment: str, treatment_value: float,
        z_vars: List[str], z_bin: Tuple[int, ...]
    ) -> List[Dict[str, float]]:
        """Filter data matching treatment value and Z bin."""
        tolerance = 0.3
        matching = []
        for d in data:
            # Check treatment value match
            if abs(d.get(treatment, 0.0) - treatment_value) > tolerance:
                continue
            # Check Z bin match
            d_bin = tuple(
                min(self.n_bins - 1, int(d.get(v, 0.0) * self.n_bins))
                for v in z_vars
            )
            if d_bin == z_bin:
                matching.append(d)
        return matching

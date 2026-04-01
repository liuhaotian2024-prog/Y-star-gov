# Layer: Foundation
"""
ystar.governance.structural_equation — StructuralEquation + linear algebra helpers

Split from causal_engine.py for modularity.

Implements Pearl Level 3 structural equations with noise terms:
  V_i = f_i(PA_i, U_i)

Each equation maps parent values + noise term to the variable's value.
"""
from __future__ import annotations
from typing import List, Dict, Optional


class StructuralEquation:
    """
    A single structural equation in the SCM: V_i = f_i(PA_i, U_i)

    Each equation maps parent values + noise term to the variable's value.
    The noise term U_i captures all exogenous variation not explained
    by the structural parents.

    Pearl (2009), Definition 7.1.1:
    A structural causal model M = <U, V, F> where:
      U = set of exogenous (noise) variables
      V = set of endogenous variables
      F = set of structural equations {f_i}

    In our SCM:
      f_W(S, U_W): wiring quality = base_from_suggestion_quality + noise
      f_O(W, U_O): obligation fulfillment = base_from_wiring + noise
      f_H(O, W, U_H): health = base_from_obligations_and_wiring + noise
      f_S(H, U_S): suggestion quality = base_from_health + noise

    The structural equations use linear models estimated from data.
    For our 4-variable system, this gives exact (not approximate) answers.
    """

    def __init__(self, name: str, parents: List[str]):
        """
        Args:
            name: Variable name (W, O, H, S)
            parents: Parent variable names in the DAG
        """
        self.name = name
        self.parents = parents
        # Linear coefficients: variable_value = intercept + Σ(coeff_i * parent_i) + noise
        self.intercept: float = 0.0
        self.coefficients: Dict[str, float] = {p: 0.0 for p in parents}

    def evaluate(self, parent_values: Dict[str, float], noise: float) -> float:
        """
        Compute V = f(PA, U).

        Args:
            parent_values: {parent_name: value} for each structural parent
            noise: Exogenous noise term U_i

        Returns:
            The computed value, clamped to [0, 1].
        """
        result = self.intercept
        for parent, coeff in self.coefficients.items():
            result += coeff * parent_values.get(parent, 0.0)
        result += noise
        return max(0.0, min(1.0, result))

    def infer_noise(self, observed_value: float, parent_values: Dict[str, float]) -> float:
        """
        Abduction step: infer noise term from observed data.

        Given V_observed and PA_observed, compute:
          U = V_observed - f(PA_observed, 0)

        This is exact for linear structural equations.

        Pearl (2009), Section 7.1: "The first step of counterfactual
        computation is to use the evidence to update our knowledge
        about the exogenous variables U."
        """
        deterministic = self.intercept
        for parent, coeff in self.coefficients.items():
            deterministic += coeff * parent_values.get(parent, 0.0)
        return observed_value - deterministic

    def fit_from_data(self, data: List[Dict[str, float]]) -> None:
        """
        Estimate structural equation parameters from observational data.

        Uses ordinary least squares for the linear model:
          V = intercept + Σ(coeff_i * PA_i) + U

        For small datasets (< 2 observations), uses domain-knowledge defaults.

        Args:
            data: List of dicts, each with keys for this variable and its parents.
        """
        if len(data) < 2:
            # Insufficient data: use informative priors based on domain knowledge
            self._set_domain_defaults()
            return

        # Extract Y (this variable) and X (parent variables)
        y_vals = [d[self.name] for d in data]
        n = len(y_vals)

        if not self.parents:
            # No parents: V = intercept + U
            self.intercept = sum(y_vals) / n
            return

        # OLS: Y = X * beta where X includes intercept column
        # For our small system (max 2 parents), solve normal equations directly
        # X matrix: [1, parent1, parent2, ...]
        k = len(self.parents) + 1  # +1 for intercept

        # Build X^T X and X^T Y
        xtx = [[0.0] * k for _ in range(k)]
        xty = [0.0] * k

        for d in data:
            row = [1.0] + [d.get(p, 0.0) for p in self.parents]
            y = d[self.name]
            for i in range(k):
                xty[i] += row[i] * y
                for j in range(k):
                    xtx[i][j] += row[i] * row[j]

        # Solve via Gaussian elimination (exact for small k)
        beta = _solve_linear_system(xtx, xty)

        if beta is not None:
            self.intercept = beta[0]
            for i, parent in enumerate(self.parents):
                self.coefficients[parent] = beta[i + 1]
        else:
            # Singular matrix: fall back to domain defaults
            self._set_domain_defaults()

    def _set_domain_defaults(self) -> None:
        """Domain-knowledge default coefficients for Y*gov SCM."""
        defaults = {
            'S': {'intercept': 0.5},                # Exogenous within cycle (mean prior)
            'W': {'intercept': 0.3, 'S': 0.6},     # Wiring heavily influenced by suggestions
            'O': {'intercept': 0.2, 'W': 0.7},     # Obligations driven by wiring
            'H': {'intercept': 0.1, 'O': 0.5, 'W': 0.3},  # Health from obligations + wiring
        }
        if self.name in defaults:
            d = defaults[self.name]
            self.intercept = d.get('intercept', 0.3)
            for p in self.parents:
                self.coefficients[p] = d.get(p, 0.3)
        else:
            self.intercept = 0.3
            for p in self.parents:
                self.coefficients[p] = 0.5

    def __repr__(self) -> str:
        terms = [f"{self.intercept:.2f}"]
        for p, c in self.coefficients.items():
            terms.append(f"{c:.2f}*{p}")
        terms.append(f"U_{self.name}")
        return f"{self.name} = {' + '.join(terms)}"


def _solve_linear_system(a: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """
    Solve Ax = b via Gaussian elimination with partial pivoting.

    For our SCM with at most 3 unknowns (intercept + 2 parents),
    this is exact and fast.

    Returns None if the system is singular.
    """
    n = len(b)
    # Augmented matrix
    aug = [row[:] + [b[i]] for i, row in enumerate(a)]

    for col in range(n):
        # Partial pivoting
        max_row = col
        max_val = abs(aug[col][col])
        for row in range(col + 1, n):
            if abs(aug[row][col]) > max_val:
                max_val = abs(aug[row][col])
                max_row = row
        if max_val < 1e-12:
            return None  # Singular
        aug[col], aug[max_row] = aug[max_row], aug[col]

        # Eliminate below
        for row in range(col + 1, n):
            factor = aug[row][col] / aug[col][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]

    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        if abs(aug[i][i]) < 1e-12:
            return None
        x[i] = aug[i][n]
        for j in range(i + 1, n):
            x[i] -= aug[i][j] * x[j]
        x[i] /= aug[i][i]

    return x

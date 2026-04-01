# Layer: Foundation
"""
ystar.governance.counterfactual_engine — Pearl Level 3 three-step counterfactual

Split from causal_engine.py for modularity.

Implements Pearl's three-step counterfactual procedure (Pearl, 2009, Ch. 7):
  Step 1 — Abduction: Use evidence E=e to determine U (noise terms).
  Step 2 — Action: Modify the model M to M_x by replacing the equation for X with X=x.
  Step 3 — Prediction: Use the modified model M_x with the updated U.
"""
from __future__ import annotations
from typing import Dict

from ystar.governance.causal_graph import CausalGraph
from ystar.governance.structural_equation import StructuralEquation


class CounterfactualEngine:
    """
    Implements Pearl's three-step counterfactual procedure (Pearl, 2009, Ch. 7):

      Step 1 — Abduction: Use evidence E=e to determine U (noise terms).
               For linear SCMs, this is: U_i = V_i_observed - f_i(PA_i_observed, 0)

      Step 2 — Action: Modify the model M to M_x by replacing the equation
               for X with X=x (the intervention).

      Step 3 — Prediction: Use the modified model M_x with the updated U
               to compute the counterfactual outcome.

    This gives EXACT counterfactual answers for our 4-variable linear SCM.
    No nearest-neighbor approximation. No weighted statistics.

    Formal guarantee (Pearl, 2009, Theorem 7.1.7):
    For any SCM M and evidence e, the counterfactual P(Y_x=y | e) is
    uniquely determined by the structural equations and noise distribution.

    Our 4-variable SCM:
      Variables: W (wiring), O (obligations), H (health), S (suggestions)
      Graph: S → W → O → H, W → H
      Each equation: V_i = f_i(PA_i) + U_i (linear with additive noise)
    """

    # Topological order for our SCM
    TOPO_ORDER = ['S', 'W', 'O', 'H']

    def __init__(self, graph: CausalGraph, equations: Dict[str, StructuralEquation]):
        self.graph = graph
        self.equations = equations

    def abduction(self, observed: Dict[str, float]) -> Dict[str, float]:
        """
        Step 1: Infer noise terms from observed data.

        Given a complete observation {W=w, O=o, H=h, S=s},
        compute U_i = V_i - f_i(PA_i, 0) for each variable.

        Args:
            observed: {variable_name: observed_value} for all endogenous variables.

        Returns:
            {variable_name: inferred_noise_term}
        """
        noise_terms: Dict[str, float] = {}
        for var in self.TOPO_ORDER:
            if var not in self.equations:
                continue
            eq = self.equations[var]
            parent_vals = {p: observed.get(p, 0.0) for p in eq.parents}
            noise_terms[var] = eq.infer_noise(observed.get(var, 0.0), parent_vals)
        return noise_terms

    def action(
        self,
        interventions: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Step 2: Define the intervention do(X=x).

        Returns the intervention dict as-is (the modification happens
        in the prediction step by replacing structural equations).

        Args:
            interventions: {variable_name: forced_value}

        Returns:
            The interventions dict (identity — API clarity).
        """
        return dict(interventions)

    def prediction(
        self,
        noise_terms: Dict[str, float],
        interventions: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Step 3: Compute counterfactual outcome under intervention.

        Process variables in topological order. For each variable:
          - If it's intervened on: use the intervention value (replaces equation)
          - Otherwise: evaluate structural equation with inferred noise

        This implements the modified model M_x from Pearl (2009), Def 7.1.4.

        Args:
            noise_terms: From abduction step
            interventions: From action step

        Returns:
            {variable_name: counterfactual_value} for all variables.
        """
        values: Dict[str, float] = {}

        for var in self.TOPO_ORDER:
            if var in interventions:
                # Intervention: replace structural equation with constant
                values[var] = interventions[var]
            elif var in self.equations:
                eq = self.equations[var]
                parent_vals = {p: values.get(p, 0.0) for p in eq.parents}
                noise = noise_terms.get(var, 0.0)
                values[var] = eq.evaluate(parent_vals, noise)
            else:
                values[var] = 0.0

        return values

    def counterfactual(
        self,
        observed: Dict[str, float],
        interventions: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Full three-step counterfactual: "Given that we observed E=e,
        what would Y have been if we had done X=x?"

        Combines abduction, action, and prediction in one call.

        Pearl (2009), Theorem 7.1.7: This procedure gives the unique
        answer to any counterfactual query in a fully specified SCM.

        Args:
            observed: Complete observation {W: w, O: o, H: h, S: s}
            interventions: {variable: forced_value}

        Returns:
            Counterfactual values for all variables.
        """
        # Step 1: Abduction
        noise_terms = self.abduction(observed)
        # Step 2: Action (identity)
        interventions = self.action(interventions)
        # Step 3: Prediction
        return self.prediction(noise_terms, interventions)

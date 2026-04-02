# STATUS: LEGACY — not on the main governance runtime path
"""
ystar.governance.ml_adaptive  —  Adaptive Coefficients & Objective Derivation
Physical sub-module of metalearning.py (was 2858 lines → 6 focused modules).
Canonical import: from ystar.governance.ml_adaptive import ...
"""
from ystar.governance.metalearning import (
    AdaptiveCoefficients, RefinementFeedback, update_coefficients, derive_objective_adaptive, derive_objective, score_candidate,
)

__all__ = ['AdaptiveCoefficients', 'RefinementFeedback', 'update_coefficients', 'derive_objective_adaptive', 'derive_objective', 'score_candidate']

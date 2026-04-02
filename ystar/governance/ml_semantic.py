# STATUS: LEGACY — not on the main governance runtime path
"""
ystar.governance.ml_semantic  —  Semantic Inquiry & Verification
Physical sub-module of metalearning.py (was 2858 lines → 6 focused modules).
Canonical import: from ystar.governance.ml_semantic import ...
"""
from ystar.governance.metalearning import (
    SemanticConstraintProposal, inquire_parameter_semantics, auto_inquire_all, VerificationReport, verify_proposal, inquire_and_verify,
)

__all__ = ['SemanticConstraintProposal', 'inquire_parameter_semantics', 'auto_inquire_all', 'VerificationReport', 'verify_proposal', 'inquire_and_verify']

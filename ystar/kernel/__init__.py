"""
ystar.kernel  —  Kernel Layer (v0.40.0)
========================================
Canonical implementations live here. Root-level ystar/*.py are thin re-exports.
"""
from ystar.kernel.engine import (
    check, CheckResult, Violation,
    EnforcementMode, EnforcementResult, enforce,
)
from ystar.kernel.dimensions import (
    IntentContract, ConstitutionalContract,
    DelegationContract, DelegationChain,
    TemporalConstraint, TemporalContext,
    ExternalContext, AggregateConstraint,
)
from ystar.kernel.merge import merge_contracts

__all__ = [
    "check", "CheckResult", "Violation",
    "EnforcementMode", "EnforcementResult", "enforce",
    "IntentContract", "ConstitutionalContract",
    "DelegationContract", "DelegationChain",
    "TemporalConstraint", "TemporalContext",
    "ExternalContext", "AggregateConstraint",
    "merge_contracts",
]

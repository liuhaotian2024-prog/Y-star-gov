# ystar — Human Intent to Machine Predicate
# Copyright (C) 2026 Haotian Liu
# MIT License
"""
ystar: Formalizing human intent as machine-executable predicates.

The Y*_t intent contract system answers one question:
    "What was this function supposed to do?"

And verifies at runtime:
    "Did it actually do that?"

Usage:

    from ystar import contract, IntentContract, check, prefill

    # Define a contract with the @contract decorator
    @contract(
        deny=[".env", "/etc/"],
        only_paths=["./projects/"],
        deny_commands=["rm -rf", "sudo"],
        invariant=["amount > 0", "amount < 1000000"],
    )
    def transfer_funds(amount: float, recipient: str) -> dict:
        return {"status": "ok", "amount": amount}

    # Or build a contract programmatically
    c = IntentContract(
        deny=[".env"],
        invariant=["amount > 0"],
    )

    # Or auto-prefill from four deterministic sources
    c = prefill(func=transfer_funds)

    # Check a call manually
    result = check({"amount": -100}, {"status": "error"}, c)
    print(result.passed)   # False
    print(result.summary()) # VIOLATION: Invariant violated: 'amount > 0'

    # Learn tighter constraints from violation history
    from ystar import learn_from_jsonl
    result = learn_from_jsonl("~/.ystar/history.jsonl")
    print(result.contract_additions)
"""

from .kernel.dimensions import (
    TemporalContext,
    ScheduledWindow,
    ExternalContext,
    ConstitutionalContract,
    HigherOrderContract,
    TemporalConstraint,
    AggregateConstraint,
    ContextConstraint,
    ResourceConstraint,
    DelegationContract,
    DelegationChain,
    NonceLedger,
    IntentContract,
    normalize_aliases,
    DIMENSION_NAMES,
    DIMENSION_LABELS,
    DIMENSION_HINTS,
    PolicySourceTrust,
)
from .kernel.engine import (
    check,
    CheckResult,
    Violation,
    # v0.15: enforcement modes
    EnforcementMode,
    EnforcementResult,
    enforce,
    ContractViolationError,
)
from .template import from_template, TemplateResult
from .session import Policy, PolicyResult
from .adapters.hook import check_hook   # 轻量 hook 适配层（1-D）
from .templates import get_template, get_template_dict, TEMPLATES
from .kernel.prefill import prefill, PrefillResult
from .governance.metalearning import (
    DimensionDiscovery,
    learn,
    learn_from_jsonl,
    CallRecord,
    CandidateRule,
    MetalearnResult,
    NormativeObjective,
    ContractQuality,
    derive_objective,
    AdaptiveCoefficients,
    RefinementFeedback,
    update_coefficients,
    derive_objective_adaptive,
    YStarLoop,
    discover_parameters,
    ParameterHint,
    SemanticConstraintProposal,
    inquire_parameter_semantics,
    auto_inquire_all,
    VerificationReport,
    verify_proposal,
    inquire_and_verify,
    ManagedConstraint,
    ConstraintRegistry,
    DomainContext,
)

__version__ = "0.48.0"

# ── Canonical layer paths (v0.37.1) ──────────────────────────────────────────
# New code should prefer these import paths:
#   from ystar.kernel         import check, IntentContract
#   from ystar.governance     import OmissionEngine, InterventionEngine
#   from ystar.governance.adaptive   import ConstraintRegistry
#   from ystar.governance.auto_configure import run_governance_auto_configure
#   from ystar.adapters       import OmissionAdapter, DeliveryManager
#   from ystar.products       import run_ab_experiment
#   from ystar.domains.openclaw.accountability_pack import apply_openclaw_accountability_pack
#
# Legacy paths (root-level) remain valid for backward compatibility.
__author__  = "Haotian Liu"
__license__ = "MIT"

# ── Omission Governance Layer (v0.31+) ────────────────────────────────────────
# commission violations → engine.py (checks what was done)
# omission  violations → omission_*.py (checks what was NOT done)
from .governance.omission_models import (
    EntityStatus, ObligationStatus, OmissionType, Severity,
    EscalationPolicy, EscalationAction,
    TrackedEntity, ObligationRecord, GovernanceEvent,
    OmissionViolation, GEventType,
)
from .governance.omission_store import InMemoryOmissionStore, OmissionStore
from .governance.omission_rules import (
    OmissionRule, RuleRegistry, BUILTIN_RULES,
    get_registry, reset_registry,
)
from .governance.omission_engine import OmissionEngine, EngineResult
from .adapters.omission_adapter import OmissionAdapter, create_adapter
from .governance.omission_summary import (
    omission_summary,
    entity_timeline,
    replay              as omission_replay,
    print_summary       as print_omission_summary,
    print_replay        as print_omission_replay,
    chain_breakpoint_analysis,
    obligation_heatmap,
    actor_reliability_report,
)
from .governance.omission_scanner import (
    OmissionScanner,
    ScanReport,
    start_global_scanner,
    stop_global_scanner,
)
# ── v0.33: Active Intervention Layer ─────────────────────────────────────────
from .governance.intervention_models import (
    InterventionLevel,
    InterventionActionType,
    InterventionStatus,
    GateDecision,
    CapabilityRestriction,
    InterventionPulse,
    GateCheckResult,
    InterventionResult,
)
from .governance.intervention_engine import InterventionEngine, PulseStore, GatingPolicy, DEFAULT_GATING_POLICY
# ── v0.36: Governance Loop (P1 meta-learning bridge) ─────────────────────────
from .governance.governance_loop import (
    GovernanceLoop,
    GovernanceObservation,
    GovernanceSuggestion,
    GovernanceTightenResult,
    report_to_observation,
)
# ── v0.34: A/B Experiment Framework ──────────────────────────────────────────
# ── v0.35: Reporting Engine ──────────────────────────────────────────────────
from .governance.reporting import (
    ReportEngine,
    Report,
    ArtifactIntegrity,
    ObligationMetrics,
    OmissionMetrics,
    InterventionMetrics,
    ChainClosureMetrics,
    CIEUMetrics,
)
from .products.omission_experiment import (
    run_ab_experiment,
    run_full_battery,
    print_ab_report,
    print_battery_report,
    ABReport,
    GroupMetrics,
    TrialResult,
)
from .domains.omission_domain_packs import (
    apply_domain_pack,
    apply_finance_pack,
    apply_healthcare_pack,
    apply_devops_pack,
    apply_research_pack,
    list_packs      as list_omission_packs,
)


# ── @contract decorator ───────────────────────────────────────────────────────

import functools as _functools
import json as _json
import logging as _logging
from datetime import datetime as _datetime, timezone as _timezone
from pathlib import Path as _Path
from typing import Any as _Any, Callable as _Callable, Optional as _Optional

_log = _logging.getLogger("ystar")


def contract(func=None, **kwargs) -> _Callable:
    """
    Decorator that enforces an IntentContract on every function call.

    Usage:
        @contract(deny=[".env"], invariant=["amount > 0"])
        def transfer_funds(amount, recipient):
            ...

        @contract  # zero-config: auto-prefill from four sources
        def transfer_funds(amount, recipient):
            ...

    When a violation occurs, it is:
    - Logged to stderr with [ystar] prefix
    - Recorded in the ystar ledger (~/.ystar/history.jsonl) if enabled
    - Raised as a ContractViolationError if strict=True (default: False)

    The function still executes by default (audit mode).
    Set strict=True to block execution on violation.
    """
    strict: bool = kwargs.pop("strict", False)
    ledger: bool = kwargs.pop("ledger", True)

    def decorator(f: _Callable) -> _Callable:
        # Build or load contract
        if kwargs:
            c = normalize_aliases(**kwargs)
        else:
            # Auto-prefill
            c = prefill(func=f)

        if not c.is_empty():
            _log.debug("ystar: contract loaded for %s: %s", f.__name__, c)

        @_functools.wraps(f)
        def wrapper(*args, **kw):
            # Build params dict from positional and keyword args
            import inspect
            try:
                sig    = inspect.signature(f)
                bound  = sig.bind(*args, **kw)
                bound.apply_defaults()
                params = dict(bound.arguments)
            except Exception:
                params = {f"arg{i}": v for i, v in enumerate(args)}
                params.update(kw)

            # Pre-call check (invariant, deny, paths, domains, commands)
            # In decorator context, invariant is treated as optional_invariant:
            # the decorator already knows the function's actual params, so
            # phantom_variable errors (referencing missing params) should not
            # block execution — they indicate an optional numeric guard.
            pre_contract = IntentContract(
                deny              = c.deny,
                only_paths        = c.only_paths,
                deny_commands     = c.deny_commands,
                only_domains      = c.only_domains,
                optional_invariant= c.invariant,   # treat as optional in decorator context
                invariant         = [],             # prevent phantom_variable false-positives
                field_deny        = c.field_deny,
                value_range       = c.value_range,
            )
            pre_result = check(params, None, pre_contract)

            if not pre_result.passed:
                for v in pre_result.violations:
                    _log.warning("[ystar] VIOLATION in %s: %s", f.__name__, v.message)
                    print(f"[ystar] VIOLATION in {f.__name__}: {v.message}")
                _record(f.__name__, params, None, pre_result, ledger)
                if strict:
                    raise ContractViolationError(
                        f.__name__, pre_result.violations)
                # Execute anyway in audit mode
                result = f(*args, **kw)
                _record(f.__name__, params, result,
                        check(params, result, c), ledger)
                return result

            # Execute function
            result = f(*args, **kw)

            # Post-call check (postcondition)
            if c.postcondition:
                post_contract = IntentContract(postcondition=c.postcondition)
                post_result = check(params, result, post_contract)
                if not post_result.passed:
                    for v in post_result.violations:
                        _log.warning("[ystar] VIOLATION in %s: %s",
                                     f.__name__, v.message)
                        print(f"[ystar] VIOLATION in {f.__name__}: {v.message}")
                    _record(f.__name__, params, result, post_result, ledger)
                    if strict:
                        raise ContractViolationError(
                            f.__name__, post_result.violations)
                    return result

            _record(f.__name__, params, result,
                    CheckResult(passed=True), ledger)
            return result

        wrapper._ystar_contract = c
        return wrapper

    if func is not None:
        # @contract used without arguments
        return decorator(func)
    return decorator


def _record(func_name: str, params: dict, result: _Any,
            check_result: CheckResult, enabled: bool) -> None:
    """Write a call record to the ystar ledger."""
    if not enabled:
        return
    try:
        ledger_path = _Path.home() / ".ystar" / "history.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp":  _datetime.now(_timezone.utc).isoformat(),
            "func_name":  func_name,
            "params":     {k: str(v)[:200] for k, v in params.items()},
            "passed":     check_result.passed,
            "violations": [
                {"dimension": v.dimension, "field": v.field,
                 "message": v.message, "severity": v.severity}
                for v in check_result.violations
            ],
        }
        with open(ledger_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


class ContractViolationError(Exception):
    """Raised when a contract is violated in strict mode."""
    def __init__(self, func_name: str, violations: list):
        msgs = "; ".join(v.message for v in violations)
        super().__init__(f"Contract violated in {func_name}: {msgs}")
        self.func_name  = func_name
        self.violations = violations


__all__ = [
    # ── Core contract types ───────────────────────────────────────────────────
    "IntentContract",
    "ConstitutionalContract",
    "normalize_aliases",
    "DIMENSION_NAMES",
    "DIMENSION_LABELS",
    "DIMENSION_HINTS",

    # ── Higher-order dimensions ───────────────────────────────────────────────
    "HigherOrderContract",
    "TemporalConstraint",
    "AggregateConstraint",
    "ContextConstraint",
    "ResourceConstraint",

    # ── Multi-agent delegation (v0.6+) ────────────────────────────────────────
    "DelegationContract",
    "DelegationChain",
    "NonceLedger",

    # ── Runtime check ─────────────────────────────────────────────────────────
    "check",
    "CheckResult",
    "Violation",
    "contract",
    "from_template", "TemplateResult", "Policy", "PolicyResult", "check_hook",
    "get_template", "get_template_dict", "TEMPLATES",
    "ContractViolationError",

    # ── Auto-prefill (v0.4+) ──────────────────────────────────────────────────
    "prefill",
    "PrefillResult",

    # ── Causal metalearning ───────────────────────────────────────────────────
    "learn",
    "learn_from_jsonl",
    "CallRecord",
    "CandidateRule",
    "MetalearnResult",
    "DimensionDiscovery",

    # ── Normative objective (v0.8+) ───────────────────────────────────────────
    "NormativeObjective",
    "ContractQuality",
    "derive_objective",

    # ── Adaptive coefficient learning (v0.9+) ─────────────────────────────────
    "AdaptiveCoefficients",
    "RefinementFeedback",
    "update_coefficients",
    "derive_objective_adaptive",

    # ── Adaptive loop workflow (v0.10+) ───────────────────────────────────────
    "YStarLoop",

    # ── Enforcement modes (v0.15+) ────────────────────────────────────────────
    "EnforcementMode",
    "EnforcementResult",
    "enforce",
    "ContractViolationError",

    # ── Constraint lifecycle (v0.15+) ─────────────────────────────────────────
    "ManagedConstraint",
    "ConstraintRegistry",

    # ── Parameter discovery (v0.13+) ──────────────────────────────────────────
    "discover_parameters",
    "ParameterHint",

    # ── Semantic inquiry (v0.14+) ─────────────────────────────────────────────
    "SemanticConstraintProposal",
    "inquire_parameter_semantics",
    "auto_inquire_all",
    "VerificationReport",
    "verify_proposal",
    "inquire_and_verify",
    "DomainContext",

    # ── Version ───────────────────────────────────────────────────────────────
    "__version__",

    # ── Omission Governance Layer (v0.31+) ────────────────────────────────────
    "EntityStatus", "ObligationStatus", "OmissionType", "Severity",
    "EscalationPolicy", "EscalationAction",
    "TrackedEntity", "ObligationRecord", "GovernanceEvent",
    "OmissionViolation", "GEventType",
    "InMemoryOmissionStore", "OmissionStore",
    "OmissionRule", "RuleRegistry", "BUILTIN_RULES",
    "get_registry", "reset_registry",
    "OmissionEngine", "EngineResult",
    "OmissionAdapter", "create_adapter",
    "omission_summary", "entity_timeline",
    "omission_replay", "print_omission_summary", "print_omission_replay",
    "chain_breakpoint_analysis", "obligation_heatmap", "actor_reliability_report",
    # ── Scanner + Domain Packs (v0.31+) ──────────────────────────────────
    "OmissionScanner", "ScanReport",
    "start_global_scanner", "stop_global_scanner",
    "apply_domain_pack", "apply_finance_pack", "apply_healthcare_pack",
    "apply_devops_pack", "apply_research_pack", "list_omission_packs",
    # ── v0.33: Active Intervention Layer ─────────────────────────────────────
    "InterventionLevel", "InterventionActionType", "InterventionStatus",
    "GateDecision", "CapabilityRestriction",
    "InterventionPulse", "GateCheckResult", "InterventionResult",
    "InterventionEngine", "PulseStore", "GatingPolicy", "DEFAULT_GATING_POLICY",
    # ── v0.36: Governance Loop ────────────────────────────────────────────────
    "GovernanceLoop", "GovernanceObservation", "GovernanceSuggestion",
    "GovernanceTightenResult", "report_to_observation",
    # ── v0.34: A/B Experiment Framework ──────────────────────────────────────
    # ── v0.35: Reporting Engine ──────────────────────────────────────────────
    "ReportEngine", "Report", "ArtifactIntegrity",
    "ObligationMetrics", "OmissionMetrics",
    "InterventionMetrics", "ChainClosureMetrics", "CIEUMetrics",
    "run_ab_experiment", "run_full_battery",
    "print_ab_report", "print_battery_report",
    "ABReport", "GroupMetrics", "TrialResult",
]

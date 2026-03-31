"""
ystar.governance  —  Governance Services Layer
===============================================
v0.41.0

建立在 Kernel 之上的通用治理引擎和服务。

层级规则：
  ✓ 可以依赖：ystar.kernel（含 engine, dimensions）
  ✓ 可以依赖：标准库
  ✗ 不允许：import ystar.domains.*（除 import-time lazy exception）
  ✗ 不允许：import ystar.omission_adapter（adapter 依赖此层，不是反过来）
  ✗ 不允许：import ystar.report_delivery
  ✗ 不允许：import ystar.domains.*（适配层依赖已解耦，只允许依赖注入）

此包是 Governance Services 的稳定 re-export 入口。
"""
# Omission governance
from ystar.governance.omission_models import (
    TrackedEntity, ObligationRecord, GovernanceEvent,
    OmissionViolation, GEventType,
    ObligationStatus, EntityStatus, OmissionType, Severity,
    EscalationPolicy, EscalationAction,
)
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore
from ystar.governance.omission_rules import (
    OmissionRule, RuleRegistry, BUILTIN_RULES,
    get_registry, reset_registry,
    KERNEL_SAFE_DEFAULT_DUE_SECS,
)
from ystar.governance.omission_engine import OmissionEngine, EngineResult
from ystar.governance.omission_scanner import OmissionScanner, ScanReport

# Intervention governance
from ystar.governance.intervention_models import (
    InterventionPulse, GateCheckResult, InterventionResult,
    CapabilityRestriction, InterventionLevel,
    InterventionActionType, InterventionStatus, GateDecision,
)
from ystar.governance.intervention_engine import (
    InterventionEngine, PulseStore, GatingPolicy, DEFAULT_GATING_POLICY,
)

# Reporting (Governance Services side — metrics collection)
from ystar.governance.reporting import (
    ReportEngine, Report,
    ObligationMetrics, OmissionMetrics,
    InterventionMetrics, ChainClosureMetrics, CIEUMetrics,
)

# Summary / replay (Governance Services side)
from ystar.governance.governance_loop import (
    GovernanceLoop,
    GovernanceObservation,
    GovernanceSuggestion,
    GovernanceTightenResult,
    report_to_observation,
)
from ystar.governance.omission_summary import (
    omission_summary, entity_timeline,
    chain_breakpoint_analysis, obligation_heatmap, actor_reliability_report,
)

# Kernel layer — constitutional primitives
from ystar.kernel.dimensions import (
    ConstitutionalContract,
    DelegationChain,
    DelegationContract,
)

# P1: Adaptive / meta-learning surface
from ystar.governance.adaptive import (
    ConstraintRegistry,
    ManagedConstraint,
    AdaptiveCoefficients,
    RefinementFeedback,
    update_coefficients,
    discover_parameters,
    ParameterHint,
)
# Amendment system
from ystar.governance.amendment import AmendmentEngine, AmendmentProposal

# Contract lifecycle
from ystar.governance.contract_lifecycle import ContractLifecycle, ContractDraft

# P3: Auto-configuration
from ystar.governance.auto_configure import (
    run_governance_auto_configure,
    GovernanceAutoConfigureScheduler,
    AUTO_CONFIGURE_FLOOR_SECS,
)

__all__ = [
    # Omission
    "TrackedEntity", "ObligationRecord", "GovernanceEvent",
    "OmissionViolation", "GEventType",
    "ObligationStatus", "EntityStatus", "OmissionType", "Severity",
    "EscalationPolicy", "EscalationAction",
    "InMemoryOmissionStore", "OmissionStore",
    "OmissionRule", "RuleRegistry", "BUILTIN_RULES",
    "get_registry", "reset_registry", "KERNEL_SAFE_DEFAULT_DUE_SECS",
    "OmissionEngine", "EngineResult",
    "OmissionScanner", "ScanReport",
    # Intervention
    "InterventionPulse", "GateCheckResult", "InterventionResult",
    "CapabilityRestriction", "InterventionLevel",
    "InterventionActionType", "InterventionStatus", "GateDecision",
    "InterventionEngine", "PulseStore", "GatingPolicy", "DEFAULT_GATING_POLICY",
    # Reporting
    "ReportEngine", "Report",
    "ObligationMetrics", "OmissionMetrics",
    "InterventionMetrics", "ChainClosureMetrics", "CIEUMetrics",
    # Governance Loop (P1)
    "GovernanceLoop", "GovernanceObservation", "GovernanceSuggestion",
    "GovernanceTightenResult", "report_to_observation",
    # Summary
    "omission_summary", "entity_timeline",
    "chain_breakpoint_analysis", "obligation_heatmap", "actor_reliability_report",
    # Kernel primitives in governance namespace
    "ConstitutionalContract", "DelegationChain", "DelegationContract",
    # Adaptive
    "ConstraintRegistry", "ManagedConstraint", "AdaptiveCoefficients",
    "RefinementFeedback", "update_coefficients",
    "discover_parameters", "ParameterHint",
    # Auto-configure
    "run_governance_auto_configure", "GovernanceAutoConfigureScheduler",
    "AUTO_CONFIGURE_FLOOR_SECS",
    # Amendment
    "AmendmentEngine", "AmendmentProposal",
    # Contract Lifecycle
    "ContractLifecycle", "ContractDraft",
]

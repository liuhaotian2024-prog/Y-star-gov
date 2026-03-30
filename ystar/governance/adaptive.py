"""
ystar.governance.adaptive  —  Governance-Relevant Metalearning Surface
=======================================================================
v0.41.0

"不要重写，直接继续用它作为唯一 meta-learning 主仓。"

metalearning.py 有 2859 行，包含三类不同的能力：
  A. commission 侧学习（CallRecord → tighten → MetalearnResult）
  B. 治理参数发现（discover_parameters, inquire_parameter_semantics）
  C. 约束生命周期管理（ConstraintRegistry, ManagedConstraint）

这个文件是 B + C 的干净入口，供 Governance Services 层使用。
它不重写任何逻辑，只是把正确的接口暴露在正确的命名空间里。

commission 侧（A）通过 YStarLoop 直接访问，不在此处重新暴露。

使用方式：
    # 发现当前生态的关键参数
    from ystar.governance.adaptive import discover_parameters
    hints = discover_parameters(store)

    # 语义查询修复建议
    from ystar.governance.adaptive import inquire_parameter_semantics
    suggestions = inquire_parameter_semantics(context)

    # 受控激活链
    from ystar.governance.adaptive import ConstraintRegistry, ManagedConstraint
    registry = ConstraintRegistry()
"""
from ystar.governance.metalearning import (
    # B. 治理参数发现
    discover_parameters,
    inquire_parameter_semantics,
    auto_inquire_all,
    ParameterHint,
    DomainContext,
    SemanticConstraintProposal,
    VerificationReport,
    verify_proposal,
    inquire_and_verify,

    # C. 约束生命周期管理
    ConstraintRegistry,
    ManagedConstraint,

    # B+C 共用
    AdaptiveCoefficients,
    RefinementFeedback,
    update_coefficients,
)

# GovernanceLoop (bridges A + B + C + omission/intervention)
from ystar.governance.governance_loop import (
    GovernanceLoop,
    GovernanceObservation,
    GovernanceSuggestion,
    GovernanceTightenResult,
    report_to_observation,
)

from ystar.kernel.dimensions import (
    ConstitutionalContract,
    DelegationChain,
)

__all__ = [
    # Parameter discovery
    "discover_parameters",
    "inquire_parameter_semantics",
    "auto_inquire_all",
    "ParameterHint",
    "DomainContext",
    "SemanticConstraintProposal",
    "VerificationReport",
    "verify_proposal",
    "inquire_and_verify",
    # Constraint lifecycle
    "ConstraintRegistry",
    "ManagedConstraint",
    # Adaptive coefficients
    "AdaptiveCoefficients",
    "RefinementFeedback",
    "update_coefficients",
    # Governance loop
    "GovernanceLoop",
    "GovernanceObservation",
    "GovernanceSuggestion",
    "GovernanceTightenResult",
    "report_to_observation",
    # Kernel primitives
    "ConstitutionalContract",
    "DelegationChain",
]

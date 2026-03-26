"""
ystar.governance.proposals  —  Proposal Verification & Semantic Inquiry
=======================================================================
v0.41.0

metalearning.py 的语义查询与提案验证子门面。

暴露：
  - discover_parameters()      : 从历史数据发现关键参数
  - inquire_parameter_semantics(): LLM-assisted 语义修复建议
  - verify_proposal()          : 提案数学验证（无 LLM）
  - SemanticConstraintProposal : 语义约束提案对象
  - VerificationReport         : 验证结果对象

使用方式：
    from ystar.governance.proposals import discover_parameters, verify_proposal
"""
from ystar.governance.metalearning import (
    discover_parameters,
    inquire_parameter_semantics,
    auto_inquire_all,
    verify_proposal,
    inquire_and_verify,
    ParameterHint,
    DomainContext,
    SemanticConstraintProposal,
    VerificationReport,
)

__all__ = [
    "discover_parameters",
    "inquire_parameter_semantics",
    "auto_inquire_all",
    "verify_proposal",
    "inquire_and_verify",
    "ParameterHint",
    "DomainContext",
    "SemanticConstraintProposal",
    "VerificationReport",
]

"""
ystar.governance.ml — metalearning 子模块包
v0.41: 从 2713 行 metalearning.py 拆分而来，保持完全向后兼容

子模块（可直接从此包导入）：
  records    — CallRecord, CandidateRule, MetalearnResult
  objectives — NormativeObjective, ContractQuality, AdaptiveCoefficients, RefinementFeedback
  loop       — YStarLoop
  registry   — ConstraintRegistry, ManagedConstraint

所有符号仍可从 ystar.governance.metalearning 直接导入（向后兼容保证）。
新代码建议从具体子模块导入，职责更清晰：

    # 旧写法（仍然有效）
    from ystar.governance.metalearning import YStarLoop

    # 新写法（v0.41 推荐）
    from ystar.governance.ml.loop import YStarLoop
"""
# 从各子模块重新导出，让 from ystar.governance.ml import X 也能工作
try:
    from ystar.governance.metalearning import (
        CallRecord, CandidateRule, MetalearnResult,
        NormativeObjective, ContractQuality,
        AdaptiveCoefficients, RefinementFeedback,
        YStarLoop,
        ManagedConstraint, ConstraintRegistry,
        DimensionDiscovery, ParameterHint,
        SemanticConstraintProposal, VerificationReport,
    )
except ImportError:
    pass  # 拆分期间允许部分导入失败

__all__ = [
    "CallRecord", "CandidateRule", "MetalearnResult",
    "NormativeObjective", "ContractQuality",
    "AdaptiveCoefficients", "RefinementFeedback",
    "YStarLoop",
    "ManagedConstraint", "ConstraintRegistry",
]

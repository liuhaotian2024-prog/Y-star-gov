# Layer: Intent Compilation
# Responsibility: Rules/needs -> IntentContract compilation only
# Does NOT: execute governance, write enforcement CIEU, command Path A/B
"""
ystar.governance.constraints  —  Constraint Lifecycle Management
================================================================
v0.41.0

metalearning.py 的约束生命周期管理子门面。

ConstraintRegistry 是治理参数变更的受控激活链：
  DRAFT → VERIFIED → APPROVED → ACTIVE → DEPRECATED

暴露：
  - ConstraintRegistry : 约束注册表（含完整生命周期）
  - ManagedConstraint  : 带状态的约束条目

使用方式：
    from ystar.governance.constraints import ConstraintRegistry, ManagedConstraint
    registry = ConstraintRegistry()
    registry.add(ManagedConstraint(id="r1", dimension="governance_timing", ...))
    registry.verify("r1")
    registry.approve("r1")
    registry.activate("r1")
"""
from ystar.governance.metalearning import (
    ConstraintRegistry,
    ManagedConstraint,
)

__all__ = [
    "ConstraintRegistry",
    "ManagedConstraint",
]

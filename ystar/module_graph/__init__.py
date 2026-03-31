"""
ystar.module_graph — Y* 模块图谱

ModuleGraph 是路径 A（元治理智能体）的核心组件：
它把 ystar 的所有可组合单元描述成一个有向图，
每个节点有明确的输入类型、输出类型和治理语义标签，
使得规划器可以搜索"从当前状态到目标状态"的模块组合路径。

这解决了之前组合只依靠人工的问题——
现在系统可以自主发现哪些模块可以接在一起，
以及接在一起会产生什么治理语义。
"""
from ystar.module_graph.graph import ModuleGraph, ModuleNode, ModuleEdge
from ystar.module_graph.registry import MODULE_REGISTRY
from ystar.module_graph.planner import CompositionPlanner, CompositionPlan
from ystar.governance.causal_engine import (
    CausalEngine, DoCalcResult, CausalGraph, StructuralEquation, CounterfactualEngine,
)
from ystar.module_graph.discovery import (
    GapDetector, TypeBasedPlanner, CombinatorialExplorer, DetectedGap
)

__all__ = [
    "ModuleGraph", "ModuleNode", "ModuleEdge",
    "MODULE_REGISTRY",
    "CompositionPlanner", "CompositionPlan",
    "CausalEngine", "DoCalcResult", "CausalGraph", "StructuralEquation", "CounterfactualEngine",
]

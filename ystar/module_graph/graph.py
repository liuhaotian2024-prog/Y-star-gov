"""
ystar.module_graph.graph — 核心图谱数据结构

ModuleNode：一个可组合单元（函数或方法）
  - 输入类型列表
  - 输出类型
  - 治理语义标签
  - 来源数据（来自哪个包/模块）

ModuleEdge：两个节点之间的连接
  - 连接条件（输出类型匹配输入类型）
  - 治理语义（组合后会产生什么新的治理能力）

ModuleGraph：整个图谱
  - 节点注册
  - 边自动推导（类型兼容性）
  - 语义聚合（两个节点组合的治理语义）
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ── 治理语义标签 ──────────────────────────────────────────────────────────────
# 每个模块和组合都有语义标签，标签决定了"这个组合在治理上意味着什么"
GOVERNANCE_TAGS = {
    # 执行层
    "enforcement":      "拦截/放行决策",
    "audit_write":      "写入审计链",
    "contract_check":   "合约维度校验",
    # 检测层
    "drift_detection":  "任务漂移检测",
    "skill_risk":       "技能供应链风险",
    "attribution":      "违规归因",
    # 治理层
    "obligation_track": "承诺义务跟踪",
    "omission_gate":    "遗漏行为阻断",
    "intervention":     "干预与恢复",
    # 学习层
    "meta_learn":       "规则候选发现",
    "objective_derive": "目标函数推导",
    "autotune":         "系数自适应调整",
    "retro_assess":     "历史追溯评估",
    # 报告层
    "report_gen":       "治理报告生成",
    "health_monitor":   "系统健康监测",
    # 合约层
    "contract_build":   "合约构建",
    "contract_prefill": "合约自动填充",
    "domain_pack":      "领域包覆盖",
}


@dataclass
class ModuleNode:
    """一个可组合的 Y* 模块节点。"""
    id:             str                    # 唯一标识，如 "check" / "OmissionEngine.scan"
    module_path:    str                    # Python import 路径
    func_name:      str                    # 函数名或 ClassName.method
    input_types:    List[str]              # 输入类型列表（字符串，支持模糊匹配）
    output_type:    str                    # 主要输出类型
    tags:           List[str]              # 治理语义标签
    description:    str                    # 一句话描述
    side_effects:   List[str] = field(default_factory=list)  # 副作用（如写入 CIEU）
    requires:       List[str] = field(default_factory=list)  # 依赖的其他节点 ID

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def compatible_input(self, output_type: str) -> bool:
        """检查某个输出类型是否能作为本节点的输入。"""
        for inp in self.input_types:
            # 精确匹配或子字符串匹配（如 "List[CallRecord]" 匹配 "CallRecord"）
            if inp == output_type or output_type in inp or inp in output_type:
                return True
        return False


@dataclass
class ModuleEdge:
    """两个节点之间的有向边（A → B 意味着 A 的输出可以喂给 B 的输入）。"""
    source_id:          str
    target_id:          str
    data_type:          str       # 流动的数据类型
    combined_tags:      List[str] # 组合后的治理语义
    governance_meaning: str       # 自然语言描述这条连接的治理含义
    is_wired:           bool = False  # 当前代码库里是否已经接上了


class ModuleGraph:
    """Y* 所有可组合模块的有向图谱。"""

    def __init__(self):
        self._nodes: Dict[str, ModuleNode] = {}
        self._edges: Dict[Tuple[str,str], ModuleEdge] = {}

    # ── 注册 ──────────────────────────────────────────────────────────────────
    def add_node(self, node: ModuleNode) -> None:
        self._nodes[node.id] = node

    def add_edge(self, edge: ModuleEdge) -> None:
        self._edges[(edge.source_id, edge.target_id)] = edge

    # ── 查询 ──────────────────────────────────────────────────────────────────
    def node(self, node_id: str) -> Optional[ModuleNode]:
        return self._nodes.get(node_id)

    def nodes_by_tag(self, tag: str) -> List[ModuleNode]:
        return [n for n in self._nodes.values() if n.has_tag(tag)]

    def edges_from(self, node_id: str) -> List[ModuleEdge]:
        return [e for (s,_), e in self._edges.items() if s == node_id]

    def edges_to(self, node_id: str) -> List[ModuleEdge]:
        return [e for (_,t), e in self._edges.items() if t == node_id]

    def is_wired(self, src_id: str, tgt_id: str) -> bool:
        e = self._edges.get((src_id, tgt_id))
        return e.is_wired if e else False

    # ── 自动推导边（类型兼容性） ──────────────────────────────────────────────
    def auto_derive_edges(self) -> int:
        """
        扫描所有节点对，如果 A 的 output_type 与 B 的 input_types 兼容，
        则自动创建一条 A→B 的边。
        返回新创建的边数量。
        """
        new_edges = 0
        node_list = list(self._nodes.values())
        for src in node_list:
            for tgt in node_list:
                if src.id == tgt.id:
                    continue
                if (src.id, tgt.id) in self._edges:
                    continue
                if tgt.compatible_input(src.output_type):
                    combined_tags = list(set(src.tags + tgt.tags))
                    meaning = (f"{src.description} → {tgt.description}: "
                               f"产生治理能力 [{', '.join(combined_tags[:2])}]")
                    self._edges[(src.id, tgt.id)] = ModuleEdge(
                        source_id          = src.id,
                        target_id          = tgt.id,
                        data_type          = src.output_type,
                        combined_tags      = combined_tags,
                        governance_meaning = meaning,
                        is_wired           = False,
                    )
                    new_edges += 1
        return new_edges

    # ── 统计 ─────────────────────────────────────────────────────────────────
    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def wired_edge_count(self) -> int:
        return sum(1 for e in self._edges.values() if e.is_wired)

    @property
    def unwired_edge_count(self) -> int:
        return self.edge_count - self.wired_edge_count

    def summary(self) -> str:
        return (f"ModuleGraph: {self.node_count} 节点  "
                f"{self.edge_count} 边 ({self.wired_edge_count} 已接 / "
                f"{self.unwired_edge_count} 未接)")

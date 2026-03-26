"""
ystar.module_graph.planner — STRIPS 式模块组合规划器

给定：
  - 一个"缺口描述"（当前合约无法处理的场景）
  - ModuleGraph 注册表

输出：
  - CompositionPlan：一条从"现有状态"到"能覆盖缺口"的模块组合路径

算法：
  1. 从缺口描述推断所需的治理语义标签
  2. 在图中搜索具有这些标签的模块序列
  3. 验证序列的类型兼容性
  4. 返回最短/最高置信度的路径
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set

from ystar.module_graph.graph import ModuleGraph, ModuleNode, ModuleEdge


@dataclass
class CompositionPlan:
    """一个模块组合方案。"""
    nodes:               List[ModuleNode]   # 组合顺序
    edges:               List[ModuleEdge]   # 连接方式
    required_tags:       List[str]          # 目标要求的治理标签
    achieved_tags:       List[str]          # 组合后实际实现的标签
    coverage_score:      float              # 覆盖目标的比例（0-1）
    already_wired:       bool               # 是否在当前代码库中已全部接线
    description:         str                # 自然语言描述

    def missing_tags(self) -> List[str]:
        return [t for t in self.required_tags if t not in self.achieved_tags]

    def new_wiring_needed(self) -> List[str]:
        """返回需要新接线的边描述。"""
        return [
            f"{e.source_id} → {e.target_id}: {e.governance_meaning}"
            for e in self.edges
            if not e.is_wired
        ]


# ── 缺口描述 → 所需治理标签 ──────────────────────────────────────────────────
# 把自然语言描述的缺口映射到需要的治理能力标签
GAP_TO_TAGS: Dict[str, List[str]] = {
    # 中文缺口描述
    "高风险技能未跟踪":          ["skill_risk", "obligation_track"],
    "agent漂移未产生义务":        ["drift_detection", "obligation_track"],
    "委托层级与时限不匹配":        ["enforcement", "domain_pack"],
    "历史数据未喂入治理":          ["retro_assess", "meta_learn"],
    "规则建议未回写":             ["meta_learn", "contract_build"],
    "日报数据未驱动规则":          ["report_gen", "meta_learn"],
    "追溯未接目标函数":           ["retro_assess", "objective_derive"],
    "技能风险未触发review义务":    ["skill_risk", "obligation_track", "intervention"],
    # GovernanceSuggestion.suggestion_type 映射
    "tighten_timing":            ["obligation_track", "omission_gate"],
    "focus_rule":                ["obligation_track", "omission_gate"],
    "reduce_by_20_percent":      ["obligation_track", "enforcement"],
    "domain_pack_override":      ["domain_pack", "enforcement"],
    "skill_risk_tracking":       ["skill_risk", "obligation_track"],
    "drift_obligation":          ["drift_detection", "obligation_track"],
    "delegation_pack":           ["enforcement", "domain_pack"],
    "retro_objective":           ["retro_assess", "objective_derive"],
    # GovernanceSuggestion.target_rule_id 映射
    "HARD_OVERDUE":              ["obligation_track", "omission_gate"],
    "rule_a_delegation":         ["enforcement", "domain_pack"],
    "SkillProvenance":           ["skill_risk", "obligation_track"],
    "ChainDriftDetector":        ["drift_detection", "obligation_track"],
    "DelegationChain":           ["enforcement", "domain_pack"],
    "assess_batch":              ["retro_assess", "objective_derive"],
}


class CompositionPlanner:
    """
    给定一个缺口描述，在 ModuleGraph 中搜索最优组合方案。

    算法是启发式的广度优先搜索：
      1. 把缺口转成目标标签集合
      2. 找所有有相关标签的节点子集
      3. 验证子集内的类型兼容性
      4. 按覆盖率 + 已接线比例排序
      5. 返回 top-N 方案
    """

    def __init__(self, graph: ModuleGraph):
        self.graph = graph

    def plan(
        self,
        gap_description: str,
        max_nodes: int = 4,
        top_n: int = 3,
    ) -> List[CompositionPlan]:
        """
        为给定缺口生成最多 top_n 个组合方案。

        Args:
            gap_description: 自然语言缺口描述（或已知缺口的键名）
            max_nodes:       组合路径最多包含几个节点
            top_n:           返回几个候选方案

        Returns:
            按 coverage_score 降序排列的方案列表
        """
        # Step 1: 推断目标标签
        required_tags = self._infer_tags(gap_description)
        if not required_tags:
            return []

        # Step 2: 找所有有目标标签的节点
        relevant_nodes: Dict[str, ModuleNode] = {}
        for tag in required_tags:
            for node in self.graph.nodes_by_tag(tag):
                relevant_nodes[node.id] = node

        if not relevant_nodes:
            return []

        # Step 3: 生成候选组合（长度 1-max_nodes）
        candidates = []
        node_list = list(relevant_nodes.values())

        # 单节点
        for n in node_list:
            plan = self._make_plan([n], required_tags)
            if plan.coverage_score > 0:
                candidates.append(plan)

        # 双节点（相互有边的对）
        for i, n1 in enumerate(node_list):
            for n2 in node_list[i+1:]:
                e12 = self.graph._edges.get((n1.id, n2.id))
                e21 = self.graph._edges.get((n2.id, n1.id))
                if e12:
                    plan = self._make_plan([n1, n2], required_tags, [e12])
                    candidates.append(plan)
                if e21:
                    plan = self._make_plan([n2, n1], required_tags, [e21])
                    candidates.append(plan)

        # 三节点链
        if max_nodes >= 3:
            for n1 in node_list:
                for n2 in node_list:
                    if n1.id == n2.id: continue
                    e12 = self.graph._edges.get((n1.id, n2.id))
                    if not e12: continue
                    for n3 in node_list:
                        if n3.id in (n1.id, n2.id): continue
                        e23 = self.graph._edges.get((n2.id, n3.id))
                        if not e23: continue
                        plan = self._make_plan([n1, n2, n3], required_tags, [e12, e23])
                        candidates.append(plan)

        # Step 4: 排序并去重
        seen = set()
        unique = []
        for p in sorted(candidates, key=lambda x: (x.coverage_score, x.already_wired), reverse=True):
            key = tuple(n.id for n in p.nodes)
            if key not in seen:
                seen.add(key)
                unique.append(p)

        return unique[:top_n]

    def _infer_tags(self, description: str) -> List[str]:
        """把描述转成治理标签列表。"""
        # 精确匹配已知缺口
        if description in GAP_TO_TAGS:
            return GAP_TO_TAGS[description]
        # 关键词匹配
        tags = set()
        desc_lower = description.lower()
        keyword_map = {
            "skill":        "skill_risk",
            "漂移":          "drift_detection",
            "drift":        "drift_detection",
            "obligation":   "obligation_track",
            "义务":          "obligation_track",
            "tighten":      "obligation_track",
            "timing":       "obligation_track",
            "overdue":      "omission_gate",
            "omission":     "omission_gate",
            "focus_rule":   "omission_gate",
            "learn":        "meta_learn",
            "学习":          "meta_learn",
            "domain":       "domain_pack",
            "pack":         "domain_pack",
            "领域":          "domain_pack",
            "report":       "report_gen",
            "报告":          "report_gen",
            "retro":        "retro_assess",
            "历史":          "retro_assess",
            "enforce":      "enforcement",
            "check":        "contract_check",
            "prefill":      "contract_prefill",
            "delegation":   "enforcement",
            "chain":        "enforcement",
        }
        for kw, tag in keyword_map.items():
            if kw in desc_lower:
                tags.add(tag)
        return list(tags)

    def _make_plan(
        self,
        nodes: List[ModuleNode],
        required_tags: List[str],
        edges: Optional[List[ModuleEdge]] = None,
    ) -> CompositionPlan:
        """把节点列表转成 CompositionPlan。"""
        edges = edges or []
        achieved = list({t for n in nodes for t in n.tags})
        covered = [t for t in required_tags if t in achieved]
        score = len(covered) / max(len(required_tags), 1)
        all_wired = all(e.is_wired for e in edges)
        desc_parts = [f"{n.id}({n.description[:20]})" for n in nodes]
        description = " → ".join(desc_parts)
        return CompositionPlan(
            nodes=nodes, edges=edges,
            required_tags=required_tags, achieved_tags=achieved,
            coverage_score=score, already_wired=all_wired,
            description=description,
        )

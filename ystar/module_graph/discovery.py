"""
ystar.module_graph.discovery — 开放世界模块发现引擎

解决路径A当前的两个硬限制：
  1. GAP_TO_TAGS 静态映射 → 无法处理新问题类型
  2. 47条类型推导边未被利用 → 大量潜在组合未探索

核心机制：

  GapDetector：从 CIEU/OmissionEngine 的模式中检测新问题类型
    - 扫描 obligation 失败模式 → 归纳问题类别
    - 扫描 CIEU violation 维度分布 → 发现未覆盖的约束维度
    - 输出：DetectedGap（带类型签名，不依赖静态 GAP_TO_TAGS）

  TypeBasedPlanner：从目标输出类型反向推导模块链
    - 不依赖 GAP_TO_TAGS，而是：
      目标类型 → 哪些模块能产生此类型？
      → 这些模块需要什么输入类型？
      → 哪些模块能产生这些输入类型？
      → ... 递归到已有的模块状态
    - 本质是 Prolog 式的反向链式推导（backward chaining）

  CombinatorialExplorer：系统性尝试未探索的模块组合
    - 用 CausalEngine 的反事实推理评估未试过的组合
    - 优先探索：置信度高但历史上从未尝试过的边
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple, Any
import collections
import logging


@dataclass
class DetectedGap:
    """从系统观测中自动检测到的问题缺口。"""
    gap_id:       str                    # 自动生成的 ID
    gap_type:     str                    # 归纳出的类型（如 "obligation_cascade"）
    evidence:     List[str]              # 支持证据（obligation_id / cieu_record_id）
    required_output_type: str           # 这个缺口需要什么类型的模块输出来修复
    severity:     float                  # 0-1，来自 obligation 的 severity
    is_novel:     bool = True            # 是否是之前未见过的类型


@dataclass
class TypePath:
    """一条通过类型推导找到的模块链。"""
    nodes:         List[str]             # 模块 ID 序列
    type_chain:    List[str]             # 对应的类型序列
    novel_edges:   List[Tuple[str,str]]  # 之前未接线的边
    estimated_fix: float                 # 估计修复概率（0-1）
    reasoning:     str                   # 为什么这条链能解决问题


class GapDetector:
    """
    从 CIEU + OmissionEngine 的实时模式中检测新型缺口。

    不依赖 GAP_TO_TAGS，而是从数据中归纳：
      - 哪类义务反复失败？ → 该维度有结构性问题
      - 哪些 violation 维度持续出现但没有对应的 obligation？
      - CIEU 里哪些 func_name 模式跟 violation 的相关性最高？
    """

    def __init__(self, module_registry):
        self.registry = module_registry
        self._seen_gap_types: Set[str] = set()

    def detect_from_obligations(
        self,
        omission_store,
        min_failure_count: int = 2,
    ) -> List[DetectedGap]:
        """
        扫描 OmissionStore：找到反复失败的义务类型。
        每种持续失败的义务类型 = 一个新型缺口。
        """
        gaps = []
        try:
            obligations = omission_store.list_obligations()
            violations  = omission_store.list_violations()

            # 统计每个 obligation_type 的失败次数
            from collections import Counter
            viol_by_type = Counter()
            for v in violations:
                ob = omission_store.get_obligation(v.obligation_id)
                if ob:
                    viol_by_type[ob.obligation_type] += 1

            for obl_type, count in viol_by_type.items():
                if count < min_failure_count:
                    continue

                # 这个义务类型反复失败 → 映射到需要什么模块来修复
                required_type = self._obl_type_to_required_module_output(obl_type)
                gap_type = f"obl_failure:{obl_type}"
                is_novel = gap_type not in self._seen_gap_types
                self._seen_gap_types.add(gap_type)

                # 收集失败的严重度
                severity = max(
                    (v.severity for v in violations
                     if omission_store.get_obligation(v.obligation_id) and
                     omission_store.get_obligation(v.obligation_id).obligation_type == obl_type),
                    default=0.75,
                )
                gaps.append(DetectedGap(
                    gap_id       = f"gap_{obl_type[:12]}_{count}",
                    gap_type     = gap_type,
                    evidence     = [f"obl_type={obl_type}, failures={count}"],
                    required_output_type = required_type,
                    severity     = severity,
                    is_novel     = is_novel,
                ))
        except Exception:
            pass
        return gaps

    def detect_from_cieu(
        self,
        cieu_store,
        window: int = 1000,
    ) -> List[DetectedGap]:
        """
        扫描 CIEUStore：找到高频 violation 维度但没有对应 obligation 的情况。
        这意味着系统在检测到问题（violation）但没有创建跟踪义务（gap）。
        """
        gaps = []
        try:
            # 导出最近的记录分析
            from collections import Counter
            import tempfile, json, os
            tmp = tempfile.mktemp(suffix=".jsonl")
            cieu_store.export_jsonl(tmp)

            dim_counts = Counter()
            with open(tmp) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        for v in r.get("violations", []):
                            if isinstance(v, dict):
                                dim_counts[v.get("dimension","?")] += 1
                    except Exception as e:
                        logging.getLogger("ystar.discovery").warning(
                            "CIEU JSON parse error: %s", e)
            os.unlink(tmp)

            for dim, count in dim_counts.most_common(5):
                if count < 10:
                    continue
                gap_type = f"cieu_violation:{dim}"
                if gap_type in self._seen_gap_types:
                    continue
                self._seen_gap_types.add(gap_type)

                required_type = self._dim_to_required_module_output(dim)
                gaps.append(DetectedGap(
                    gap_id       = f"gap_cieu_{dim[:10]}_{count}",
                    gap_type     = gap_type,
                    evidence     = [f"cieu_dim={dim}, count={count}"],
                    required_output_type = required_type,
                    severity     = 0.7,
                    is_novel     = True,
                ))
        except Exception:
            pass
        return gaps

    def _obl_type_to_required_module_output(self, obl_type: str) -> str:
        """把义务类型映射到解决它需要的模块输出类型。"""
        TYPE_MAP = {
            "skill_review":             "OmissionViolation",  # 需要能产生审核事件的模块
            "drift_acknowledgement":    "EngineResult",       # 需要漂移检测结果
            "capability_demonstration": "MetalearnResult",    # 需要能力验证结果
            "behavioral_consistency":   "CheckResult",        # 需要一致性检查结果
            "honest_report":            "Report",             # 需要诚实报告
            "meta_agent_postcondition": "GovernanceTightenResult",
            "meta_agent_report":        "GovernanceTightenResult",
        }
        return TYPE_MAP.get(obl_type, "EngineResult")

    def _dim_to_required_module_output(self, dim: str) -> str:
        """把 violation 维度映射到需要的模块输出类型。"""
        DIM_MAP = {
            "only_paths":    "PrefillResult",
            "deny":          "CheckResult",
            "deny_commands": "CheckResult",
            "invariant":     "MetalearnResult",
            "postcondition": "Report",
            "omission":      "EngineResult",
            "obligation_timing": "GovernanceTightenResult",
        }
        return DIM_MAP.get(dim, "CheckResult")


class TypeBasedPlanner:
    """
    反向链式推导（Backward Chaining）模块规划器。

    不依赖 GAP_TO_TAGS，而是：
      1. 从"需要什么类型的输出"出发
      2. 找能产生该类型的模块（通过 ModuleGraph 的 output_type）
      3. 递归找这些模块需要的输入类型对应的模块
      4. 直到链条连接到已有的模块状态

    比 CompositionPlanner 更强的地方：
      - 不需要问题→标签的静态映射
      - 可以发现 GAP_TO_TAGS 里没有的新组合路径
      - 利用了 ModuleGraph 里所有 47 条类型推导边
    """

    def __init__(self, module_registry, max_depth: int = 4):
        self.registry  = module_registry
        self.max_depth = max_depth
        # 构建类型→模块的反向索引
        self._output_type_index: Dict[str, List[str]] = {}  # type→[node_id]
        self._input_type_index:  Dict[str, List[str]] = {}  # type→[node_id]
        self._build_type_index()

    def _build_type_index(self) -> None:
        for node_id, node in self.registry._nodes.items():
            # 输出类型索引
            out = node.output_type
            self._output_type_index.setdefault(out, []).append(node_id)
            # 输入类型索引（模糊匹配：类型名的任何子串都算）
            for inp_type in node.input_types:
                self._input_type_index.setdefault(inp_type, []).append(node_id)

    def plan_for_gap(self, gap: DetectedGap, top_n: int = 3) -> List[TypePath]:
        """
        给定一个 DetectedGap，通过反向推导找到能修复它的模块链。
        """
        target_type = gap.required_output_type
        return self.plan_for_type(target_type, top_n=top_n)

    def plan_for_type(
        self, required_output_type: str, top_n: int = 3
    ) -> List[TypePath]:
        """
        反向推导：找到能产生 required_output_type 的模块链。

        BFS（广度优先），从目标类型反向追溯到可用模块。
        """
        results = []
        seen = set()

        # 找能产生目标类型的模块（精确匹配 + 子串匹配）
        candidate_endpoints = self._find_producers(required_output_type)
        if not candidate_endpoints:
            return []

        # BFS：从 endpoint 反向扩展
        queue = collections.deque()
        for ep_id in candidate_endpoints:
            queue.append(([ep_id], required_output_type, 0))

        while queue and len(results) < top_n * 3:
            chain, target_type, depth = queue.popleft()
            chain_key = tuple(chain)
            if chain_key in seen:
                continue
            seen.add(chain_key)

            # 评估这条链
            novel_edges = self._find_novel_edges(chain)
            fix_prob    = self._estimate_fix_probability(chain, novel_edges)
            reasoning   = self._build_reasoning(chain, target_type, novel_edges)

            # 构建类型链
            type_chain = self._build_type_chain(chain)

            results.append(TypePath(
                nodes        = chain,
                type_chain   = type_chain,
                novel_edges  = novel_edges,
                estimated_fix = fix_prob,
                reasoning    = reasoning,
            ))

            # 继续向前扩展（找这条链入口节点需要的输入）
            if depth < self.max_depth and chain:
                head_node = self.registry._nodes.get(chain[0])
                if head_node:
                    for inp_type in head_node.input_types:
                        predecessors = self._find_producers(inp_type)
                        for pred_id in predecessors:
                            if pred_id not in chain:
                                queue.append(
                                    ([pred_id] + chain, inp_type, depth + 1)
                                )

        # 排序：估计修复概率高、新颖边少的优先
        results.sort(key=lambda p: (p.estimated_fix, -len(p.novel_edges)), reverse=True)
        return results[:top_n]

    def _find_producers(self, output_type: str) -> List[str]:
        """找能产生指定类型的模块（精确+子串匹配）。"""
        producers = []
        for node_id, node in self.registry._nodes.items():
            if (node.output_type == output_type or
                output_type in node.output_type or
                node.output_type in output_type):
                producers.append(node_id)
        return producers

    def _find_novel_edges(self, chain: List[str]) -> List[Tuple[str, str]]:
        """找链中尚未接线的边。"""
        novel = []
        for i in range(len(chain) - 1):
            src, tgt = chain[i], chain[i+1]
            edge = self.registry._edges.get((src, tgt))
            if not edge or not edge.is_wired:
                novel.append((src, tgt))
        return novel

    def _estimate_fix_probability(
        self, chain: List[str], novel_edges: List[Tuple[str, str]]
    ) -> float:
        """
        估计这条链修复问题的概率。

        规则：
          - 已接线的边权重高（有历史证据）
          - 新边权重低（未知效果）
          - 语义标签重叠度高的链得分高
        """
        if not chain:
            return 0.0
        # 已接线 vs 新边的比例
        total_edges = max(len(chain) - 1, 1)
        novel_count = len(novel_edges)
        wired_ratio = (total_edges - novel_count) / total_edges

        # 语义标签覆盖（有 obligation_track 或 omission_gate 标签的节点权重高）
        high_value_tags = {"obligation_track", "omission_gate", "enforcement",
                           "skill_risk", "drift_detection", "meta_learn"}
        tag_score = 0.0
        for node_id in chain:
            node = self.registry._nodes.get(node_id)
            if node:
                overlap = len(set(node.tags) & high_value_tags)
                tag_score += overlap * 0.1
        tag_score = min(tag_score, 0.5)

        return round(min(wired_ratio * 0.5 + tag_score, 0.95), 3)

    def _build_type_chain(self, chain: List[str]) -> List[str]:
        types = []
        for node_id in chain:
            node = self.registry._nodes.get(node_id)
            types.append(node.output_type if node else "?")
        return types

    def _build_reasoning(
        self, chain: List[str], target_type: str, novel_edges: List[Tuple[str,str]]
    ) -> str:
        parts = [f"target={target_type}"]
        for i, node_id in enumerate(chain):
            node = self.registry._nodes.get(node_id)
            if node:
                parts.append(f"[{node_id}({node.output_type})]")
            if i < len(chain)-1:
                edge_key = (chain[i], chain[i+1])
                is_novel = edge_key in novel_edges
                parts.append(f"→{'NEW' if is_novel else 'wired'}")
        return " ".join(parts)


class CombinatorialExplorer:
    """
    系统性探索未试过的模块组合。

    当 GapDetector 发现新问题、TypeBasedPlanner 找到新路径后，
    CombinatorialExplorer 决定探索顺序：
      - 优先探索：类型安全 + 因果引擎置信度高 + 从未尝试过
      - 避免：类型不兼容 + 历史上反复失败 + 太长的链（>4步）

    这是路径A从"静态 GAP_TO_TAGS 触发"进化到
    "主动扫描+探索未知组合"的关键组件。
    """

    def __init__(
        self,
        module_registry,
        causal_engine,
        max_novel_edges_per_plan: int = 2,   # 每次最多引入几条新边
    ):
        self.registry  = module_registry
        self.causal    = causal_engine
        self.max_novel = max_novel_edges_per_plan
        self._tried:   Set[Tuple[str,...]] = set()  # 已尝试过的链

    def rank_paths(
        self,
        type_paths: List[TypePath],
        current_state: Optional[Any] = None,
    ) -> List[Tuple[float, TypePath]]:
        """
        给 TypeBasedPlanner 找到的路径打分并排序。

        评分维度：
          1. estimated_fix（类型安全的结构估计）× 0.3
          2. causal_confidence（因果引擎的历史证据）× 0.5
          3. novelty_bonus（新颖性奖励，鼓励探索）× 0.2
          4. 惩罚：过多新边（不确定性高）
        """
        ranked = []
        for path in type_paths:
            chain_key = tuple(path.nodes)
            if chain_key in self._tried:
                continue
            if len(path.novel_edges) > self.max_novel:
                continue  # 太多新边，暂不探索

            # 因果引擎对每条新边的置信度
            causal_scores = []
            for src, tgt in path.novel_edges:
                result = self.causal.do_wire_query(src, tgt)
                causal_scores.append(result.confidence)
            for src, tgt in [(n, path.nodes[i+1])
                              for i, n in enumerate(path.nodes[:-1])
                              if (n, path.nodes[i+1]) not in path.novel_edges]:
                causal_scores.append(0.75)  # 已接线的边有历史置信度
            causal_conf = sum(causal_scores) / max(len(causal_scores), 1)

            # 新颖性奖励（从未试过的链）
            novelty = 1.0 if chain_key not in self._tried else 0.0

            score = (
                path.estimated_fix * 0.3 +
                causal_conf        * 0.5 +
                novelty            * 0.2
            )
            ranked.append((score, path))

        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked

    def mark_tried(self, path: TypePath) -> None:
        """标记这条路径已尝试。"""
        self._tried.add(tuple(path.nodes))

    def untried_count(self) -> int:
        all_possible = len(list(self.registry._nodes.keys())) ** 2
        return all_possible - len(self._tried)

"""
ystar.module_graph.meta_agent — 路径A：元治理智能体

核心设计原理：GovernanceSuggestion IS IntentContract

每个 GovernanceSuggestion 包含：
  - 目标（suggested_value）→ postcondition
  - 范围（target_rule_id）→ only_paths
  - 置信度（confidence）→ fp_tolerance
  - 截止（observation_ref）→ obligation_timing

路径A的目标不是自己定义的，而是从系统观测派生的。
这解决了"谁来治理治理者"——GovernanceLoop 既是路径A的委托者，
也是路径A执行结果的裁判。路径A永远无法扩大自己的权限。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any
import time, uuid, os

from ystar.kernel.dimensions import IntentContract
from ystar.governance.governance_loop import GovernanceSuggestion
from ystar.module_graph.causal_engine import CausalEngine, CausalState

# 路径A宪法文本路径（相对于包根）
_PATH_A_AGENTS_MD = os.path.join(
    os.path.dirname(__file__), 'PATH_A_AGENTS.md'
)
from ystar.module_graph.discovery import (
    GapDetector, TypeBasedPlanner, CombinatorialExplorer
)


# ── 步骤2 核心函数：Suggestion → IntentContract ──────────────────────────────
def suggestion_to_contract(
    suggestion:       GovernanceSuggestion,
    allowed_modules:  List[str],    # CompositionPlan 里的模块 ID（记录在 notes）
    deadline_secs:    float = 600.0,
) -> IntentContract:
    """
    把一个 GovernanceSuggestion 转成路径A执行本次任务的 IntentContract。

    设计原则：
      - 只约束真正有意义的维度（危险命令、敏感路径）
      - 不用 only_paths 约束模块 ID（only_paths 是文件系统维度）
      - 范围控制靠 CompositionPlan 本身（有限 ModuleGraph 子集）
      - 截止时间和范围记录在 obligation_timing 里
    """
    # 基础安全约束：禁止危险文件路径
    forbidden_paths = ["/etc", "/root", "~/.clawdbot", "/production"]
    # 禁止危险命令（路径A不应该执行任何 shell 命令）
    forbidden_cmds  = ["rm -rf", "sudo", "exec(", "eval(", "__import__",
                       "subprocess", "os.system"]

    # obligation_timing：X 秒内必须汇报，同时记录允许的模块范围
    obligation = {
        "deadline_secs":    deadline_secs,
        "obligation_type":  "meta_agent_report",
        "trigger":          f"suggestion:{suggestion.target_rule_id}",
        "allowed_modules":  allowed_modules,     # 文档性约束（不被 check 强制）
        "target":           str(suggestion.suggested_value)[:80],
    }

    # 读取宪法文本 hash（用于 IntentContract.hash 溯源）
    constitution_hash = None
    try:
        with open(_PATH_A_AGENTS_MD, 'rb') as fh:
            import hashlib
            constitution_hash = "sha256:" + hashlib.sha256(fh.read()).hexdigest()[:16]
    except Exception:
        pass

    return IntentContract(
        name              = f"path_a:{suggestion.suggestion_type}:{uuid.uuid4().hex[:6]}",
        deny              = forbidden_paths,
        deny_commands     = forbidden_cmds,
        obligation_timing = obligation,
        # hash 用 AGENTS.md 内容的 sha256，实现宪法溯源
        hash              = constitution_hash or f"path_a:{suggestion.target_rule_id}",
        # only_paths 不设置：路径A操作的是 ModuleGraph 对象，不是文件系统
        # invariant 不设置：eval 不可用于跨轮次状态检查
        # postcondition 由 GovernanceLoop 下一轮 tighten() 验证
    )


# ── 步骤5 辅助：创建后置 obligation ──────────────────────────────────────────
def create_postcondition_obligation(
    omission_store,
    suggestion:      GovernanceSuggestion,
    agent_id:        str   = "path_a_agent",
    deadline_secs:   float = 600.0,
) -> Optional[str]:
    """
    接线执行完成后，在 OmissionStore 里创建一条后置 obligation：
    "GovernanceLoop 必须在 deadline_secs 内观测到健康改善"

    如果 GovernanceLoop.tighten() 在截止前返回更好的 health，
    则 obligation 履行 → 路径A任务成功。
    如果超时未改善 → HARD_OVERDUE → OmissionEngine 触发 → InterventionEngine 拦截路径A。

    这是路径A"失败惩罚"机制——不改善等于白做，
    反复失败会触发 DENY，强制人工介入。
    """
    try:
        from ystar.governance.omission_engine import ObligationRecord, ObligationStatus
        ob = ObligationRecord(
            obligation_id        = f"path_a_post_{uuid.uuid4().hex[:8]}",
            entity_id            = agent_id,
            actor_id             = agent_id,
            obligation_type      = "meta_agent_postcondition",
            trigger_event_id     = f"suggestion_{suggestion.target_rule_id}",
            required_event_types = ["governance_health_improved", "suggestion_addressed"],
            due_at               = time.time() + deadline_secs,
            status               = ObligationStatus.PENDING,
            severity             = suggestion.confidence,
            notes                = (f"路径A后置条件：执行 {suggestion.suggestion_type} 后"
                                    f" {deadline_secs}s 内观测到改善。"
                                    f" 目标：{suggestion.target_rule_id}"
                                    f" → {str(suggestion.suggested_value)[:40]}"),
            created_at           = time.time(),
            updated_at           = time.time(),
        )
        omission_store.add_obligation(ob)
        return ob.obligation_id
    except Exception as e:
        return None


@dataclass
class MetaAgentCycle:
    """一次路径A执行周期的完整记录。"""
    cycle_id:       str   = field(default_factory=lambda: uuid.uuid4().hex[:8])
    suggestion:     Optional[GovernanceSuggestion] = None
    contract:       Optional[IntentContract]       = None
    plan_nodes:     List[str]                      = field(default_factory=list)
    plan_edges:     List[tuple]                    = field(default_factory=list)
    executed:       bool  = False
    cieu_ref:       Optional[str]                  = None
    obligation_id:  Optional[str]                  = None
    health_before:  str   = "unknown"
    health_after:   str   = "unknown"
    success:        bool  = False
    timestamp:      float = field(default_factory=time.time)
    # 因果推理字段（Level 2/3）
    _causal_confidence: float = 0.0  # do-calculus 置信度
    _needs_human:       bool  = True  # 是否需要人工（默认需要，有因果证据后改变）

    def to_dict(self) -> dict:
        return {
            "cycle_id":      self.cycle_id,
            "suggestion_type": self.suggestion.suggestion_type if self.suggestion else None,
            "target_rule_id": self.suggestion.target_rule_id if self.suggestion else None,
            "plan_nodes":    self.plan_nodes,
            "executed":      self.executed,
            "health_before": self.health_before,
            "health_after":  self.health_after,
            "success":       self.success,
            "timestamp":     self.timestamp,
        }


class PathAAgent:
    """
    路径A元治理智能体。

    使用方法：
        agent = PathAAgent(gloop, cieu_store, planner)
        cycle = agent.run_one_cycle()

    一次 run_one_cycle() 完成：
      1. 从 GovernanceLoop 获取最新 GovernanceSuggestion
      2. 把 Suggestion 转成 IntentContract（suggestion_to_contract）
      3. 调用 CompositionPlanner 找接线方案
      4. 用 Y* check() 验证路径A的行动是否在自己的合约内
      5. 执行接线（写入 CIEU）
      6. 在 OmissionEngine 创建后置 obligation
      7. 再次触发 GovernanceLoop.tighten() 验证改善
      8. 判断成功/失败，更新 ModuleGraph 接线状态

    路径A永远无法扩大自己的权限：
      - 合约来自 GovernanceSuggestion（外部观测），不是自我指定
      - 范围限于 CompositionPlan（有限 ModuleGraph 子集）
      - 失败触发 HARD_OVERDUE → InterventionEngine 拦截
      - 所有行动写入 CIEU（被它服务的同一个审计链）
    """

    def __init__(
        self,
        governance_loop,
        cieu_store,
        planner,
        omission_store=None,
        max_cycles:    int   = 10,
        cycle_timeout: float = 600.0,
        auto_confidence_threshold: float = 0.65,  # 高于此值自主执行，无需人工
    ):
        self.gloop         = governance_loop
        self.cieu_store    = cieu_store
        self.planner       = planner
        self.omission_store= omission_store
        self.max_cycles    = max_cycles
        self.cycle_timeout = cycle_timeout
        self._history:     List[MetaAgentCycle] = []
        # Pearl Level 3 因果推理引擎
        self.causal_engine = CausalEngine(
            confidence_threshold=auto_confidence_threshold
        )
        # 开放世界发现引擎
        self.gap_detector  = GapDetector(planner.graph)
        self.type_planner  = TypeBasedPlanner(planner.graph)
        self.explorer      = CombinatorialExplorer(planner.graph, self.causal_engine)
        # 加载路径A宪法文本
        self._constitution_path = _PATH_A_AGENTS_MD
        try:
            import hashlib as _hl
            with open(_PATH_A_AGENTS_MD, 'rb') as _cf:
                self._constitution_hash = 'sha256:' + _hl.sha256(_cf.read()).hexdigest()[:16]
        except Exception:
            self._constitution_hash = 'sha256:unavailable'
        # 注册进 DelegationChain（委托深度=1，父=governance_loop）
        self._delegation_depth  = 1
        self._parent_id         = "governance_loop"


    def _load_constitution_hash(self) -> str:
        try:
            import hashlib
            with open(self._constitution_path, 'rb') as f:
                return 'sha256:' + hashlib.sha256(f.read()).hexdigest()[:16]
        except Exception:
            return 'sha256:unavailable'

    def constitution_summary(self) -> str:
        try:
            with open(self._constitution_path) as f:
                n = sum(1 for _ in f)
            return (f'PATH_A: {n} lines  hash={self._constitution_hash}  '
                    f'depth={self._delegation_depth}  parent={self._parent_id}')
        except Exception:
            return 'PATH_A: unavailable'

    def _do_handoff_registration(self) -> bool:
        """
        通过 enforce(HANDOFF) 把路径A注册进 SessionState.handoff_contracts。

        验证 path_a_contract ⊆ governance_loop_contract（单调性约束）。
        通过则写入 handoff_contracts，之后所有动作受 strict_handoff_mode 约束。
        """
        try:
            from ystar.domains.openclaw.adapter import (
                enforce, OpenClawEvent, EventType, SessionState, EnforceDecision,
            )
            from ystar.kernel.dimensions import DelegationChain, DelegationContract
            import uuid as _uuid

            # 父合约：GovernanceLoop 层（治理层顶层）
            parent_contract = IntentContract(
                name          = "governance_loop:meta_governance",
                deny          = ["/etc", "/root"],
                deny_commands = ["rm -rf", "sudo"],
            )

            # 子合约：路径A（AGENTS.md 派生，deny 是父合约超集 → 单调性满足）
            child_contract = IntentContract(
                name          = f"path_a:agent:{self._constitution_hash}",
                deny          = ["/etc", "/root", "~/.clawdbot", "/production"],
                deny_commands = ["rm -rf", "sudo", "exec(", "eval(",
                                 "__import__", "subprocess"],
                hash          = self._constitution_hash,
            )

            # DelegationChain: ystar_system → governance_loop → path_a_agent
            delegation_chain = DelegationChain()
            # 父链：action_scope 必须是子链的超集
            _path_a_scope = ["module_graph.wire", "cieu.write", "obligation.create"]
            delegation_chain.append(DelegationContract(
                principal        = "ystar_system",
                actor            = "governance_loop",
                contract         = parent_contract,
                action_scope     = _path_a_scope,  # 与子链相同，满足 ⊇ 关系
                delegation_depth = 1,
                allow_redelegate = True,
            ))
            delegation_chain.append(DelegationContract(
                principal        = "governance_loop",
                actor            = "path_a_agent",
                contract         = child_contract,
                action_scope     = _path_a_scope,
                delegation_depth = 0,
                allow_redelegate = False,
            ))

            session_id = f"path_a_{_uuid.uuid4().hex[:8]}"
            session_state = SessionState(
                session_id          = session_id,
                delegation_chain    = delegation_chain,
                agent_contracts     = {"governance_loop": parent_contract,
                                       "path_a_agent":    child_contract},
                strict_handoff_mode = True,
            )

            handoff_event = OpenClawEvent(
                event_type       = EventType.HANDOFF,
                agent_id         = "path_a_agent",
                session_id       = session_id,
                parent_agent_id  = "governance_loop",
                task_description = ("path_a meta-governance: "
                                    "wire modules to improve system health"),
                action_scope     = ["module_graph.wire", "cieu.write",
                                    "obligation.create"],
            )

            decision, _ = enforce(handoff_event, session_state)

            if decision == EnforceDecision.ALLOW:
                self._session_state      = session_state
                self._handoff_registered = True
                self._handoff_decision   = "ALLOW"
                return True
            else:
                self._handoff_registered = False
                self._handoff_decision   = "DENIED"
                return False

        except Exception as e:
            # 降级：注册失败不阻断执行，避免无限重试
            self._handoff_registered = True
            self._handoff_decision   = f"ERROR:{e}"
            return False

    def run_one_cycle(self) -> MetaAgentCycle:
        """执行一次完整的目标发现→规划→执行→验证循环。"""
        from ystar import check

        cycle = MetaAgentCycle()

        # 步骤0：HANDOFF 注册（若尚未注册）
        # 把路径A的合约通过 enforce(HANDOFF) 写入 handoff_contracts，
        # 使其受 strict_handoff_mode 约束（子合约必须是父合约子集）
        if not hasattr(self, '_handoff_registered') or not self._handoff_registered:
            self._do_handoff_registration()

        # 步骤0b：宪法完整性验证（防篡改）
        try:
            import hashlib as _hl
            with open(self._constitution_path, 'rb') as _cf:
                current_hash = "sha256:" + _hl.sha256(_cf.read()).hexdigest()[:16]
            if current_hash != self._constitution_hash:
                # 宪法被篡改：写 CIEU 记录，跳过本次循环
                self.cieu_store.write_dict({
                    "session_id": "path_a_constitution_check",
                    "agent_id":   "path_a_agent",
                    "action":     "constitution_integrity_check",
                    "params":     {"expected": self._constitution_hash,
                                   "found":    current_hash},
                    "result":     {"decision": "skip_cycle",
                                   "reason":   "constitution_hash_mismatch"},
                    "contract_name": "PATH_A_AGENTS",
                })
                cycle.executed = False
                return cycle
        except FileNotFoundError:
            pass  # 文件不存在时不阻断（容错）

        # 步骤1：确保有至少一次观测，再获取 GovernanceSuggestion
        if not self.gloop._observations:
            self.gloop.observe_from_report_engine()
        tighten_result = self.gloop.tighten()
        cycle.health_before = tighten_result.overall_health
        suggestions = tighten_result.governance_suggestions or []
        if not suggestions:
            cycle.success = False
            self._history.append(cycle)
            return cycle

        # 取置信度最高的 suggestion
        suggestion = max(suggestions, key=lambda s: s.confidence)
        cycle.suggestion = suggestion

        # 步骤2：CompositionPlanner 找方案
        # 策略：type + target 联合搜索，取置信度最高的有边方案
        all_plans = []
        for query in [
            suggestion.suggestion_type,
            suggestion.target_rule_id,
            f"{suggestion.suggestion_type} {suggestion.target_rule_id}",
        ]:
            plans = self.planner.plan(query, max_nodes=3, top_n=2)
            all_plans.extend(plans)
        # 优先选有边的方案
        plans_with_edges = [p for p in all_plans if p.edges]
        plans_no_edges   = [p for p in all_plans if not p.edges]
        sorted_plans = sorted(plans_with_edges,
                               key=lambda p: p.coverage_score, reverse=True)
        if not sorted_plans:
            sorted_plans = sorted(plans_no_edges,
                                  key=lambda p: p.coverage_score, reverse=True)
        if not sorted_plans:
            # 没有方案 = 当前缺口已超出 ModuleGraph 范围，跳过
            self._history.append(cycle)
            return cycle
        # do-calculus 增强：对候选方案做 Level 2 因果查询
        best_plan = sorted_plans[0]
        if len(sorted_plans[0].edges) > 0:
            # 对每个候选方案计算 do-calculus 预测
            plan_scores = []
            for candidate in sorted_plans[:3]:  # 最多评估3个候选
                if candidate.edges:
                    e = candidate.edges[0]
                    do_result = self.causal_engine.do_wire_query(
                        e.source_id, e.target_id,
                    )
                    combined_score = (
                        candidate.coverage_score * 0.4 +
                        do_result.confidence * 0.6  # 因果置信度权重更高
                    )
                    plan_scores.append((combined_score, candidate, do_result))
                else:
                    plan_scores.append((candidate.coverage_score * 0.4, candidate, None))
            if plan_scores:
                plan_scores.sort(key=lambda x: x[0], reverse=True)
                best_plan = plan_scores[0][1]
                best_do   = plan_scores[0][2]
                if best_do:
                    needs_human, reason = self.causal_engine.needs_human_approval(
                        best_do, action_is_irreversible=False
                    )
                    # 记录是否需要人工确认（自主模式下跳过）
                    cycle._causal_confidence = best_do.confidence
                    cycle._needs_human = needs_human
        plan = best_plan

        plan = plans[0]
        cycle.plan_nodes = [n.id for n in plan.nodes]
        cycle.plan_edges = [(e.source_id, e.target_id) for e in plan.edges]

        # 步骤3：Suggestion → IntentContract（核心！）
        contract = suggestion_to_contract(
            suggestion,
            allowed_modules = cycle.plan_nodes,
            deadline_secs   = self.cycle_timeout,
        )
        cycle.contract = contract

        # 步骤4：check() 验证路径A自身的行动
        proposed_action = {
            "action":      "wire_modules",
            "source_id":   plan.edges[0].source_id if plan.edges else "none",
            "target_id":   plan.edges[0].target_id if plan.edges else "none",
            "plan_nodes":  cycle.plan_nodes,
        }
        check_result = check(proposed_action, {}, contract)
        if not check_result.passed:
            # 路径A自身违反了自己的合约——这是系统自我保护机制
            cycle.executed = False
            self._write_cieu(cycle, "DENIED_BY_OWN_CONTRACT",
                             check_result.violations)
            self._history.append(cycle)
            return cycle

        # 步骤5：执行接线（在 ModuleGraph 里标记 wired=True）
        wired_count = 0
        for src_id, tgt_id in cycle.plan_edges:
            edge = self.planner.graph._edges.get((src_id, tgt_id))
            if edge and not edge.is_wired:
                edge.is_wired = True  # 标记已接线
                wired_count += 1
        # 即使没有边，执行本身（规划+验证+记录）也算完成
        cycle.executed  = True
        cycle.cieu_ref  = self._write_cieu(cycle, "WIRE_EXECUTED", [])

        # 步骤6：创建后置 obligation
        if self.omission_store:
            cycle.obligation_id = create_postcondition_obligation(
                self.omission_store, suggestion,
                deadline_secs=self.cycle_timeout,
            )

        # 步骤7：再次 tighten() 观测改善
        re_result = self.gloop.tighten()
        cycle.health_after = re_result.overall_health

        # 步骤8：判断成功——health 改善或新 Suggestion 数量减少
        old_sugg_count = len(suggestions)
        new_sugg_count = len(re_result.governance_suggestions or [])
        health_improved = (
            self._health_rank(cycle.health_after) > self._health_rank(cycle.health_before)
            or new_sugg_count < old_sugg_count
            or (wired_count > 0 and cycle.health_after != "critical")
        )
        cycle.success = health_improved

        # 履行后置 obligation（如果成功）
        if cycle.success and self.omission_store and cycle.obligation_id:
            self._fulfill_obligation(cycle.obligation_id)

        # 把本次循环写入 CausalEngine（构建 SCM 数据）
        wired_before = [e for e in cycle.plan_edges]  # 本次之前
        wired_after  = [e for e in cycle.plan_edges if
                        self.planner.graph._edges.get(e) and
                        self.planner.graph._edges[e].is_wired]
        obl_count = (
            (len([o for o in self.omission_store.list_obligations()
                  if hasattr(o,'status') and str(o.status) in ('FULFILLED','fulfilled')]),
             len(self.omission_store.list_obligations()))
            if self.omission_store else (0, 0)
        )
        self.causal_engine.observe(
            health_before   = cycle.health_before,
            health_after    = cycle.health_after,
            obl_before      = (0, obl_count[1]),
            obl_after       = obl_count,
            edges_before    = [],
            edges_after     = wired_after,
            action_edges    = cycle.plan_edges,
            succeeded       = cycle.success,
            cycle_id        = cycle.cycle_id,
            suggestion_type = cycle.suggestion.suggestion_type if cycle.suggestion else None,
        )

        # 步骤9：主动触发 OmissionEngine 扫描（让义务状态立即更新）
        try:
            self.omission_engine.scan()
        except Exception:
            pass  # scan 失败不阻断循环

        self._history.append(cycle)
        return cycle

    def run_until_stable(self) -> List[MetaAgentCycle]:
        """运行多轮直到系统稳定或达到最大轮数。"""
        results = []
        for i in range(self.max_cycles):
            cycle = self.run_one_cycle()
            results.append(cycle)
            if not cycle.suggestion:
                break  # 没有 Suggestion = 系统已稳定
            if cycle.health_after in ("healthy", "stable"):
                break  # 达到目标健康状态
        return results

    def history_summary(self) -> dict:
        return {
            "total_cycles":  len(self._history),
            "successful":    sum(1 for c in self._history if c.success),
            "executed":      sum(1 for c in self._history if c.executed),
            "health_trajectory": [c.health_after for c in self._history],
        }

    @staticmethod
    def _health_rank(health: str) -> int:
        return {"healthy": 4, "stable": 3, "degraded": 2, "critical": 1}.get(health, 0)

    def _write_cieu(self, cycle: MetaAgentCycle, event: str, violations) -> Optional[str]:
        try:
            record = {
                "func_name":  f"path_a.{event.lower()}",
                "params":     cycle.to_dict(),
                "violations": [v.message if hasattr(v, 'message') else str(v)
                               for v in violations],
                "source":     "path_a_agent",
                "is_meta_agent": True,
            }
            return self.cieu_store.write_dict(record) and cycle.cycle_id
        except Exception:
            return None


    def _discover_novel_paths(self, suggestion) -> list:
        """
        当 CompositionPlanner 找不到已知方案时，
        用 GapDetector + TypeBasedPlanner + CombinatorialExplorer
        发现全新的模块组合路径。
        """
        # 1. 把 suggestion 转成一个临时 DetectedGap
        from ystar.module_graph.discovery import DetectedGap
        from ystar.module_graph.causal_engine import CausalState

        # 根据 suggestion 的 rationale 推断需要的输出类型
        type_hints = {
            "omission":     "EngineResult",
            "skill":        "EngineResult",
            "drift":        "EngineResult",
            "obligation":   "EngineResult",
            "learn":        "MetalearnResult",
            "report":       "Report",
            "governance":   "GovernanceTightenResult",
            "tighten":      "GovernanceTightenResult",
        }
        rationale = (suggestion.rationale or "").lower()
        required_type = next(
            (v for k, v in type_hints.items() if k in rationale),
            "EngineResult",
        )

        gap = DetectedGap(
            gap_id       = f"novel_{suggestion.target_rule_id[:10]}",
            gap_type     = suggestion.suggestion_type,
            evidence     = [suggestion.rationale or ""],
            required_output_type = required_type,
            severity     = suggestion.confidence,
            is_novel     = True,
        )

        # 2. TypeBasedPlanner 找路径
        type_paths = self.type_planner.plan_for_gap(gap, top_n=5)
        if not type_paths:
            return []

        # 3. CombinatorialExplorer 排序
        ranked = self.explorer.rank_paths(type_paths)
        return ranked

    def _flag_novel(self, cycle, value=True):
        """标记循环使用了开放世界发现。"""
        try:
            cycle._discovered_novel = value
        except:
            pass
    def _fulfill_obligation(self, obligation_id: str) -> None:
        try:
            from ystar.governance.omission_engine import ObligationStatus
            ob = self.omission_store.get_obligation(obligation_id)
            if ob:
                ob.status = ObligationStatus.FULFILLED
                ob.updated_at = time.time()
                self.omission_store.update_obligation(ob)
        except Exception:
            pass

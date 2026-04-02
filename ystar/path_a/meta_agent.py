# Layer: Path A
"""
ystar.path_a.meta_agent — 路径A：元治理智能体 (Layer 2 — Path A)

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
from enum import Enum
from typing import Optional, List, Tuple, Any, Callable, Dict
import time, uuid, os

from ystar.kernel.dimensions import IntentContract
from ystar.kernel.scope_encoding import encode_module_scope
from ystar.kernel.contract_provider import ConstitutionProvider
from ystar.governance.suggestion_policy import GovernanceSuggestion
from ystar.governance.causal_engine import CausalEngine, CausalState, DoCalcResult
from ystar.governance.amendment import AmendmentEngine

# 路径A宪法文本路径（相对于包根）
# TODO: Constitution loading should eventually go through the Intent Compilation
# line (nl_to_contract / prefill) rather than being loaded directly here.
# For now, direct loading is acceptable since Path A needs its constitution at
# import time for hash verification.
_PATH_A_AGENTS_MD = os.path.join(
    os.path.dirname(__file__), 'PATH_A_AGENTS.md'
)
from ystar.module_graph.discovery import (
    GapDetector, TypeBasedPlanner, CombinatorialExplorer
)
from ystar.governance.omission_engine import OmissionEngine


# ── T16: Activation Protocol ABI ─────────────────────────────────────────────
# Explicit activation modes for module wiring.  Every activation writes to CIEU
# with the protocol used, so auditors can distinguish full runtime activation
# from graph-only bookkeeping.
class ActivationProtocol(Enum):
    """Which activation path was taken when wiring a module edge."""
    FULL_ACTIVATE = "full_activate"   # module.activate() succeeded
    ON_WIRED      = "on_wired"        # module.on_wired(src, tgt) succeeded
    GRAPH_ONLY    = "graph_only"      # no activation function found; wiring is structural only


@dataclass
class PathAPolicy:
    """Unified failure policy for single-track Path A.

    Each field specifies the response when that subsystem fails:
      skip    — fail-closed, skip this cycle
      abort   — fail-closed, hard stop
      rollback — undo + record
      warn    — fail-soft, observable in CIEU
      suspend — pause execution until human acknowledges
    """
    suggestion_failure:    str = "skip"       # fail-closed
    handoff_failure:       str = "abort"      # fail-closed
    contract_failure:      str = "abort"      # fail-closed
    check_failure:         str = "abort"      # fail-closed
    activation_failure:    str = "rollback"   # rollback + record
    omission_scan_failure: str = "warn"       # fail-soft + observable
    constitution_mismatch: str = "skip"       # hard stop
    human_review:          str = "suspend"    # pause execution
    # Configurable defaults (F1: extracted from hardcoded values)
    default_forbidden_paths:    List[str] = field(default_factory=lambda: ["/etc", "/root", "~/.clawdbot", "/production"])
    default_forbidden_commands: List[str] = field(default_factory=lambda: ["rm -rf", "sudo", "exec(", "eval(", "__import__", "subprocess", "os.system"])
    default_deadline_secs:      float = 600.0
    auto_confidence_threshold:  float = 0.65
    # C6: Causal policy (Pearl L2-L3 integration)
    causal_l2_before_wiring:       bool  = True
    causal_l3_on_failure:          bool  = True
    causal_human_gate_threshold:   float = 0.65


# ── 步骤2 核心函数：Suggestion → IntentContract ──────────────────────────────
def suggestion_to_contract(
    suggestion:       GovernanceSuggestion,
    allowed_modules:  List[str],    # CompositionPlan 里的模块 ID（Gap 2: 现在被强制执行）
    deadline_secs:    float = 600.0,
    policy:           Optional[PathAPolicy] = None,
) -> IntentContract:
    """
    把一个 GovernanceSuggestion 转成路径A执行本次任务的 IntentContract。

    设计原则：
      - 只约束真正有意义的维度（危险命令、敏感路径）
      - Gap 2 修复：allowed_modules 现在通过 only_paths 强制执行
      - 范围控制靠 CompositionPlan 本身（有限 ModuleGraph 子集）
      - 截止时间和范围记录在 obligation_timing 里
    """
    # F1: Read safety constraints from policy object (configurable, not hardcoded)
    _policy = policy or PathAPolicy()
    forbidden_paths = list(_policy.default_forbidden_paths)
    forbidden_cmds  = list(_policy.default_forbidden_commands)
    # Use policy deadline unless caller overrides explicitly
    effective_deadline = deadline_secs if deadline_secs != 600.0 else _policy.default_deadline_secs

    # obligation_timing：X 秒内必须汇报，同时记录允许的模块范围
    obligation = {
        "deadline_secs":    effective_deadline,
        "obligation_type":  "meta_agent_report",
        "trigger":          f"suggestion:{suggestion.target_rule_id}",
        "allowed_modules":  allowed_modules,
        "target":           str(suggestion.suggested_value)[:80],
    }

    # 读取宪法文本 hash（用于 IntentContract.hash 溯源）— via ConstitutionProvider
    constitution_hash = None
    try:
        _provider = ConstitutionProvider()
        _bundle = _provider.resolve(_PATH_A_AGENTS_MD)
        if _bundle.source_hash:
            constitution_hash = "sha256:" + _bundle.source_hash[:16]
    except Exception:
        pass

    # Gap 2 修复：将 allowed_modules 作为强制约束放入 only_paths
    # 使用 scope_encoding 模块的统一编码（不再使用 inline f-string）
    module_constraints = encode_module_scope(allowed_modules)

    return IntentContract(
        name              = f"path_a:{suggestion.suggestion_type}:{uuid.uuid4().hex[:6]}",
        deny              = forbidden_paths,
        deny_commands     = forbidden_cmds,
        obligation_timing = obligation,
        # hash 用 AGENTS.md 内容的 sha256，实现宪法溯源
        hash              = constitution_hash or f"path_a:{suggestion.target_rule_id}",
        # Gap 2: only_paths 现在包含模块范围约束
        only_paths        = module_constraints if allowed_modules else None,
        # Note: postcondition left empty. Health improvement is enforced
        # post-execution at step 8 (strict success criteria) and via
        # create_postcondition_obligation(). Including it here would cause
        # check() to evaluate it pre-execution with empty output, always failing.
        postcondition     = [],
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
    # Gap 1: 运行时激活记录
    runtime_activated:  List[str] = field(default_factory=list)  # 成功激活的模块
    activation_failed:  List[str] = field(default_factory=list)  # 激活失败的模块
    # Gap 5: INCONCLUSIVE 状态支持
    inconclusive:       bool  = False  # 既未成功也未失败
    inconclusive_reason: Optional[str] = None
    # C5: Counterfactual review on failure (Pearl L3)
    counterfactual_review: Optional[Any] = None

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
        policy:        Optional[PathAPolicy] = None,
        constitution_provider: Optional[Callable[[str], str]] = None,
        amendment_engine: Optional[AmendmentEngine] = None,
    ):
        self.gloop         = governance_loop
        self.cieu_store    = cieu_store
        self.planner       = planner
        self.omission_store= omission_store
        self.max_cycles    = max_cycles
        self.cycle_timeout = cycle_timeout
        self._history:     List[MetaAgentCycle] = []
        # Unified failure policy (must be set early — other init code reads from it)
        self.policy = policy or PathAPolicy()
        # Pearl Level 3 因果推理引擎
        # F1: Use policy threshold if caller didn't override the default
        _effective_threshold = auto_confidence_threshold if auto_confidence_threshold != 0.65 else self.policy.auto_confidence_threshold
        self.causal_engine = CausalEngine(
            confidence_threshold=_effective_threshold
        )
        # 开放世界发现引擎
        self.gap_detector  = GapDetector(planner.graph)
        self.type_planner  = TypeBasedPlanner(planner.graph)
        self.explorer      = CombinatorialExplorer(planner.graph, self.causal_engine)
        # BUG 2 FIX: Initialize omission_engine from omission_store
        self.omission_engine = OmissionEngine(store=self.omission_store, cieu_store=self.cieu_store) if self.omission_store else None
        # 加载路径A宪法文本 — via ConstitutionProvider (fail-closed: no direct file fallback)
        self._constitution_path = _PATH_A_AGENTS_MD
        try:
            _init_provider = ConstitutionProvider()
            _init_bundle = _init_provider.resolve(_PATH_A_AGENTS_MD)
            if _init_bundle.source_hash:
                self._constitution_hash = 'sha256:' + _init_bundle.source_hash[:16]
            else:
                self._constitution_hash = 'sha256:unavailable'
        except Exception:
            self._constitution_hash = 'sha256:unavailable'
        # 注册进 DelegationChain（委托深度=1，父=governance_loop）
        self._delegation_depth  = 1
        self._parent_id         = "governance_loop"
        # Gap 3: Handoff registration tracking (fail-closed)
        self._handoff_registered = False
        self._handoff_retry_count = 0
        self._handoff_max_retries = 2
        self._inconclusive_count = 0  # Gap 5: Track inconclusive cycles
        # Fix 6.2: human review gate — blocks execution until acknowledged
        self._human_review_required = False
        # Constitution provider is the primary path; direct file loading is deprecated fallback
        # N2: Use ConstitutionProvider as the canonical constitution access path
        if constitution_provider is not None:
            self._constitution_provider = constitution_provider
        else:
            _default_provider = ConstitutionProvider()
            # Return hash in the same format as the legacy code: 'sha256:' + first 16 hex chars
            def _provider_fn(path):
                full_hash = _default_provider.get_hash(path)
                if full_hash:
                    return 'sha256:' + full_hash[:16]
                return 'sha256:unavailable'
            self._constitution_provider = _provider_fn
        self._amendment_engine = amendment_engine


    def _load_constitution_hash(self) -> str:
        # Constitution provider is the ONLY path — fail-closed (no direct file fallback)
        if self._constitution_provider is not None:
            try:
                h = self._constitution_provider(self._constitution_path)
                if h:
                    return h
            except Exception:
                pass
        # Fail-closed: if provider is absent or fails, return unavailable
        return 'sha256:unavailable'

    def constitution_summary(self) -> str:
        try:
            _provider = ConstitutionProvider()
            _bundle = _provider.resolve(self._constitution_path)
            return (f'PATH_A: hash={self._constitution_hash}  '
                    f'valid={_bundle.is_valid()}  '
                    f'depth={self._delegation_depth}  parent={self._parent_id}')
        except Exception:
            return 'PATH_A: unavailable'

    def _apply_runtime_wiring(
        self,
        cycle: MetaAgentCycle,
        edges_to_wire: List[Tuple[str, str]]
    ) -> Tuple[List[str], List[str]]:
        """
        Gap 1 修复：将图接线应用到运行时系统。

        在 ModuleGraph 里设置 is_wired=True 后，调用目标模块的激活函数
        （如果存在），使系统真正重新配置。

        返回值：(成功激活的模块列表, 失败的模块列表)
        """
        activated = []
        failed = []

        for src_id, tgt_id in edges_to_wire:
            edge = self.planner.graph._edges.get((src_id, tgt_id))
            if not edge:
                continue

            target_node = self.planner.graph._nodes.get(tgt_id)
            if not target_node:
                failed.append(tgt_id)
                continue

            # 尝试激活目标模块（如果有 activation 方法）
            try:
                # BUG 3 FIX: Unified activation protocol
                # 1. Try activate() method (REAL activation)
                # 2. Try on_wired(source_id, target_id) hook (hook-style activation)
                # 3. If module is a Python path, import and check for either
                # 4. If none available, graph_only (log clearly)
                activation_status = "graph_only"  # 默认：仅图接线

                # 尝试真实激活
                if target_node.module_path:
                    try:
                        import importlib
                        module = importlib.import_module(target_node.module_path)

                        # Protocol 1: Check for activate() method
                        if hasattr(module, 'activate') and callable(getattr(module, 'activate')):
                            activate_fn = getattr(module, 'activate')
                            activate_fn()  # 调用真实激活
                            activation_status = "real_activated_via_activate"
                        # Protocol 2: Check for on_wired() hook
                        elif hasattr(module, 'on_wired') and callable(getattr(module, 'on_wired')):
                            on_wired_fn = getattr(module, 'on_wired')
                            on_wired_fn(src_id, tgt_id)  # 调用 hook-style 激活
                            activation_status = "real_activated_via_on_wired"
                        else:
                            # 模块存在但没有 activate() 或 on_wired()，这是正常情况
                            activation_status = "graph_only_no_activation_protocol"
                    except ImportError as ie:
                        # 模块不可导入（可能是虚拟节点），图接线仍然有效
                        activation_status = f"graph_only_import_failed:{str(ie)[:50]}"
                    except Exception as act_err:
                        # activate() 或 on_wired() 调用失败 - 这是真正的错误
                        raise Exception(f"activation protocol failed: {act_err}")

                # T16: Map activation_status to ActivationProtocol enum
                if activation_status.startswith("real_activated_via_activate"):
                    protocol_used = ActivationProtocol.FULL_ACTIVATE
                elif activation_status.startswith("real_activated_via_on_wired"):
                    protocol_used = ActivationProtocol.ON_WIRED
                else:
                    protocol_used = ActivationProtocol.GRAPH_ONLY

                has_activation_protocol = protocol_used != ActivationProtocol.GRAPH_ONLY

                # Single-track distinction: graph_only → PARTIAL_ACTIVATION
                # Modules without activate() or on_wired() are graph-wired but
                # NOT fully activated. CIEU records this clearly via
                # activation_level field.
                activation_level = (
                    "FULL_ACTIVATION" if has_activation_protocol
                    else "PARTIAL_ACTIVATION"
                )

                # T16: GRAPH_ONLY produces partial_activation_warning, not
                # normal success event — auditors see this clearly in CIEU.
                cieu_event_type = (
                    "partial_activation_warning"
                    if protocol_used == ActivationProtocol.GRAPH_ONLY
                    else "runtime_activation"
                )

                activation_record = self._make_cieu_record(
                    event_type=cieu_event_type,
                    action="runtime_activation",
                    decision="allow",
                    params={
                        "source": src_id,
                        "target": tgt_id,
                        "module_path": target_node.module_path,
                        "func_name": target_node.func_name,
                        "has_activation_protocol": has_activation_protocol,
                        "activation_protocol": protocol_used.value,  # T16: log protocol
                    },
                    result={
                        "status": activation_status,
                        "activation_level": activation_level,
                        "activation_protocol": protocol_used.value,  # T16
                    },
                    cycle=cycle,
                )
                self.cieu_store.write_dict(activation_record)
                activated.append(tgt_id)

            except Exception as e:
                # 激活失败：回滚 is_wired，记录到 CIEU
                edge.is_wired = False
                failed.append(tgt_id)

                failure_record = self._make_cieu_record(
                    event_type="activation_failed",
                    action="activation_failed",
                    decision="deny",
                    params={
                        "source": src_id,
                        "target": tgt_id,
                        "error": str(e),
                    },
                    result={"status": "rollback", "reason": str(e)},
                    cycle=cycle,
                )
                self.cieu_store.write_dict(failure_record)

        return activated, failed

    def _do_handoff_registration(self) -> bool:
        """
        Gap 3 修复：fail-closed handoff registration。

        通过 enforce(HANDOFF) 把路径A注册进 SessionState.handoff_contracts。
        验证 path_a_contract ⊆ governance_loop_contract（单调性约束）。

        修复：如果注册失败，_handoff_registered = False，阻止执行。
        支持最多 2 次重试，重试失败后硬失败。
        """
        try:
            from ystar.domains.openclaw.adapter import (
                enforce, OpenClawEvent, EventType, SessionState, EnforceDecision,
            )
            from ystar.kernel.dimensions import DelegationChain, DelegationContract
            from ystar.governance.delegation_policy import build_path_a_handoff
            import uuid as _uuid

            # N6: Use delegation_policy to build contracts instead of inline assembly
            _handoff_data = build_path_a_handoff(
                constitution_bundle=None,  # hash already loaded
                path_a_policy=self.policy,
            )
            parent_contract = _handoff_data["parent_contract"]
            child_contract = _handoff_data["child_contract"]
            # Override hash with our loaded constitution hash
            child_contract.hash = self._constitution_hash
            child_contract.name = f"path_a:agent:{self._constitution_hash}"
            _parent_scope = _handoff_data["parent_scope"]
            _child_scope = _handoff_data["child_scope"]

            # DelegationChain: ystar_system → governance_loop → path_a_agent
            delegation_chain = DelegationChain()
            # Fix 4.1: child action_scope is STRICT SUBSET of parent
            delegation_chain.append(DelegationContract(
                principal        = "ystar_system",
                actor            = "governance_loop",
                contract         = parent_contract,
                action_scope     = _parent_scope,
                delegation_depth = 1,
                allow_redelegate = True,
            ))
            delegation_chain.append(DelegationContract(
                principal        = "governance_loop",
                actor            = "path_a_agent",
                contract         = child_contract,
                action_scope     = _child_scope,
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
                self._handoff_retry_count = 0  # 重置重试计数
                return True
            else:
                # Gap 3: fail-closed - 拒绝则不注册
                self._handoff_registered = False
                self._handoff_decision   = "DENIED"
                return False

        except Exception as e:
            # Gap 3: fail-closed - 异常也不注册
            self._handoff_registered = False
            self._handoff_decision   = f"ERROR:{e}"
            # 写入 CIEU 记录失败原因
            try:
                # Use a minimal cycle placeholder for pre-cycle CIEU writes
                _stub = MetaAgentCycle()
                self.cieu_store.write_dict(self._make_cieu_record(
                    event_type="handoff_registration",
                    action="handoff_registration",
                    decision="deny",
                    params={"retry_count": self._handoff_retry_count},
                    result={"decision": "FAILED", "error": str(e)},
                    cycle=_stub,
                ))
            except Exception as e2:
                _log.error("Failed to write handoff CIEU record: %s", e2)
            return False

    def run_one_cycle(self) -> MetaAgentCycle:
        """执行一次完整的目标发现→规划→执行→验证循环。"""
        from ystar import check

        cycle = MetaAgentCycle()

        # Unified policy reference for failure handling
        policy = self.policy

        # Fix 6.2: refuse to execute if human review is pending
        # policy.human_review == "suspend"
        if self._human_review_required:
            cycle.executed = False
            cycle.success = False
            cycle.inconclusive = True
            cycle.inconclusive_reason = (
                "BLOCKED: human review required. "
                "Call acknowledge_human_review() to resume."
            )
            self._history.append(cycle)
            return cycle

        # 步骤0：HANDOFF 注册（若尚未注册）—— Gap 3: fail-closed
        # 把路径A的合约通过 enforce(HANDOFF) 写入 handoff_contracts，
        # 使其受 strict_handoff_mode 约束（子合约必须是父合约子集）
        if not hasattr(self, '_handoff_registered') or not self._handoff_registered:
            registration_success = self._do_handoff_registration()

            # Gap 3: 注册失败则中止执行 (policy.handoff_failure == "abort")
            if not registration_success:
                self._handoff_retry_count += 1

                # 超过最大重试次数，硬失败
                if self._handoff_retry_count > self._handoff_max_retries:
                    self.cieu_store.write_dict(self._make_cieu_record(
                        event_type="handoff_failed",
                        action="handoff_failed_hard",
                        decision="deny",
                        params={"retry_count": self._handoff_retry_count},
                        result={"decision": "ABORT", "reason": "max_retries_exceeded"},
                        cycle=cycle,
                    ))
                    cycle.executed = False
                    cycle.success = False
                    self._history.append(cycle)
                    return cycle

                # 未超过重试次数，记录并中止本次循环
                self.cieu_store.write_dict(self._make_cieu_record(
                    event_type="handoff_failed",
                    action="handoff_failed",
                    decision="deny",
                    params={"retry_count": self._handoff_retry_count},
                    result={"decision": "ABORT", "reason": "handoff_registration_failed"},
                    cycle=cycle,
                ))
                cycle.executed = False
                cycle.success = False
                self._history.append(cycle)
                return cycle

        # 步骤0b：宪法完整性验证（防篡改）+ Amendment Response Chain
        try:
            current_hash = self._load_constitution_hash()
            if current_hash != self._constitution_hash:
                # Check if there's an approved amendment for this document
                amendment_authorized = False
                if self._amendment_engine is not None:
                    amendment_authorized = self._amendment_engine.has_approved_amendment(
                        "PATH_A_AGENTS.md", current_hash,
                    )

                if amendment_authorized:
                    # Amendment was approved: accept the new hash
                    self._constitution_hash = current_hash
                    self.cieu_store.write_dict(self._make_cieu_record(
                        event_type="constitution_amended",
                        action="constitution_amended",
                        decision="allow",
                        params={"new_hash": current_hash},
                        result={"decision": "accept_amendment"},
                        cycle=cycle,
                    ))
                else:
                    # Unauthorized change: abort + write CIEU
                    self.cieu_store.write_dict(self._make_cieu_record(
                        event_type="unauthorized_constitution_change",
                        action="constitution_integrity_check",
                        decision="deny",
                        params={"expected": self._constitution_hash,
                                "found":    current_hash},
                        result={"decision": "skip_cycle",
                                "reason":   "unauthorized_constitution_change"},
                        cycle=cycle,
                    ))
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
            # policy.suggestion_failure == "skip"
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
            # FIX: top_n=2 was truncating multi-node plans with edges.
            # Single-node plans (no edges, already_wired=True) ranked first,
            # pushing 2-node plans (with edges, already_wired=False) to 3rd position.
            # Use top_n=5 to ensure edge-bearing plans are not lost.
            plans = self.planner.plan(query, max_nodes=3, top_n=5)
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
        # ── T5: Causal Governance — plan selection is fully driven by
        # do_wire_query scores.  The combined_score formula weights causal
        # confidence at 0.6 vs coverage at 0.4, so the causal ranking is
        # the dominant factor in best_plan selection.
        best_plan = sorted_plans[0]
        _causal_evidence: Dict[str, Any] = {}  # T5: structured evidence for CIEU
        if len(sorted_plans[0].edges) > 0:
            plan_scores = []
            for candidate in sorted_plans[:3]:  # evaluate top-3 candidates
                if candidate.edges:
                    e = candidate.edges[0]
                    do_result = self.causal_engine.do_wire_query(
                        e.source_id, e.target_id,
                    )
                    combined_score = (
                        candidate.coverage_score * 0.4 +
                        do_result.confidence * 0.6  # causal confidence dominates
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
                    cycle._causal_confidence = best_do.confidence
                    cycle._needs_human = needs_human

                    # ── T5: Structured causal evidence dict ──────────────
                    # Written into CIEU so auditors can trace exactly WHY a
                    # plan was selected and whether causal evidence was
                    # sufficient to bypass the human gate.
                    _causal_evidence = {
                        "do_query": best_do.query,
                        "predicted_health": best_do.predicted_health,
                        "confidence": best_do.confidence,
                        "evidence_count": best_do.evidence_count,
                        "counterfactual_gain": best_do.counterfactual_gain,
                        "causal_chain": best_do.causal_chain,
                        "needs_human": needs_human,
                        "human_reason": reason,
                    }

                    # ── T5: causal_confidence → human_gate linkage ───────
                    # When causal_confidence >= auto_confidence_threshold the
                    # human gate is bypassed (needs_human=False).  When it is
                    # below the threshold, needs_human=True and the cycle
                    # will NOT auto-execute irreversible actions.
                    # This linkage is the core trust mechanism: only
                    # sufficient causal evidence earns autonomy.

        # BUG 1 FIX: Use the causal-selected best_plan, not plans[0]
        plan = best_plan
        cycle.plan_nodes = [n.id for n in plan.nodes]
        cycle.plan_edges = [(e.source_id, e.target_id) for e in plan.edges]

        # 步骤3：Suggestion → IntentContract（核心！）
        contract = suggestion_to_contract(
            suggestion,
            allowed_modules = cycle.plan_nodes,
            deadline_secs   = self.cycle_timeout,
            policy          = self.policy,
        )
        cycle.contract = contract

        # 步骤4：check() 验证路径A自身的行动 —— Gap 2: 强制模块范围
        # Early return if plan has no edges — nothing to wire
        if not plan.edges:
            cycle.executed = False
            self._write_cieu(cycle, "NO_EDGES_TO_WIRE", [
                "Plan has no edges; nothing to wire"
            ])
            self._history.append(cycle)
            return cycle

        proposed_action = {
            "action":      "wire_modules",
            "source_id":   plan.edges[0].source_id,
            "target_id":   plan.edges[0].target_id,
            "plan_nodes":  cycle.plan_nodes,
        }

        # Module scope validation consolidated into check() via module: prefix
        # in only_paths (see engine.py). No manual loop needed here — check()
        # is the single source of truth for module scope enforcement.

        # 调用标准 check() 进行其他维度验证
        check_result = check(proposed_action, {}, contract)
        if not check_result.passed:
            # policy.check_failure == "abort" — 路径A自身违反了自己的合约
            cycle.executed = False
            self._write_cieu(cycle, "DENIED_BY_OWN_CONTRACT",
                             check_result.violations)
            self._history.append(cycle)
            return cycle

        # 步骤5：执行接线（在 ModuleGraph 里标记 wired=True）—— Gap 1: 添加运行时激活
        wired_count = 0
        edges_to_activate = []

        for src_id, tgt_id in cycle.plan_edges:
            edge = self.planner.graph._edges.get((src_id, tgt_id))
            if edge and not edge.is_wired:
                edge.is_wired = True  # 标记已接线
                wired_count += 1
                edges_to_activate.append((src_id, tgt_id))

        # Gap 1: 应用运行时激活
        if edges_to_activate:
            activated, failed = self._apply_runtime_wiring(cycle, edges_to_activate)
            cycle.runtime_activated = activated
            cycle.activation_failed = failed

            # policy.activation_failure == "rollback" — 回滚 + 记录
            if failed:
                self._write_cieu(cycle, "ACTIVATION_FAILED", failed)
                # 部分失败不算完全执行
                wired_count -= len(failed)

        # 即使没有边，执行本身（规划+验证+记录）也算完成
        cycle.executed  = True
        cycle.cieu_ref  = self._write_cieu(cycle, "WIRE_EXECUTED", [])

        # T5: Write structured causal evidence to CIEU alongside the wiring record
        if _causal_evidence:
            self.cieu_store.write_dict(self._make_cieu_record(
                event_type="causal_evidence",
                action="causal_plan_selection",
                decision="allow",
                params={"plan_nodes": cycle.plan_nodes,
                        "plan_edges": cycle.plan_edges},
                result={"causal_evidence": _causal_evidence},
                cycle=cycle,
            ))

        # Fix 5.2: CIEU record for wiring_success when all edges wired
        if edges_to_activate and not cycle.activation_failed:
            self.cieu_store.write_dict(self._make_cieu_record(
                event_type="wiring_success",
                action="wiring_success",
                decision="allow",
                params={"wired_count": wired_count,
                        "edges": [(s, t) for s, t in edges_to_activate]},
                result={"activated": cycle.runtime_activated},
                cycle=cycle,
            ))

        # 步骤6：创建后置 obligation
        if self.omission_store:
            cycle.obligation_id = create_postcondition_obligation(
                self.omission_store, suggestion,
                deadline_secs=self.cycle_timeout,
            )

        # 步骤7：再次 tighten() 观测改善
        re_result = self.gloop.tighten()
        cycle.health_after = re_result.overall_health

        # 步骤8：判断成功 —— Gap 5: 收紧成功标准
        old_sugg_count = len(suggestions)
        new_sugg_count = len(re_result.governance_suggestions or [])

        health_before_score = self._health_rank(cycle.health_before)
        health_after_score = self._health_rank(cycle.health_after)
        health_improvement = health_after_score - health_before_score
        suggestion_reduction = old_sugg_count - new_sugg_count

        # Gap 5: 严格成功标准 - 必须满足以下之一：
        # 1. 健康分数提升 >= 1 (one rank level)
        # 2. Suggestion 数量减少 >= 1
        health_improved = (health_improvement >= 1) or (suggestion_reduction >= 1)

        # Fix 6.1: Clarify wiring + no improvement = FAILURE not INCONCLUSIVE
        # Per constitution: "Structural actions alone do NOT constitute success."
        # INCONCLUSIVE is reserved for cases where no wiring was attempted
        # (e.g., planner found paths but check() denied them).
        if not health_improved:
            if wired_count == 0 and health_improvement >= 0 and suggestion_reduction >= 0:
                # No wiring attempted but also no degradation → INCONCLUSIVE
                cycle.inconclusive = True
                cycle.inconclusive_reason = (
                    f"No wiring attempted, no measurable change: "
                    f"health {cycle.health_before}→{cycle.health_after}, "
                    f"suggestions {old_sugg_count}→{new_sugg_count}"
                )
                self._inconclusive_count += 1

                # 3 次连续 INCONCLUSIVE 触发人工审查 (Fix 6.2)
                if self._inconclusive_count >= 3:
                    self.cieu_store.write_dict(self._make_cieu_record(
                        event_type="inconclusive_threshold",
                        action="inconclusive_threshold",
                        decision="escalate",
                        params={"consecutive_count": self._inconclusive_count},
                        result={"decision": "HUMAN_REVIEW_REQUIRED"},
                        cycle=cycle,
                    ))
                    # Fix 6.2: enforce the threshold — block further execution
                    self._human_review_required = True
            else:
                # Wiring happened but no improvement → FAILURE (Fix 6.1)
                cycle.success = False
                cycle.inconclusive = False
                self._inconclusive_count = 0
                # Fix 6.3: explicitly fail obligation on cycle failure
                if self.omission_store and cycle.obligation_id:
                    self._fail_obligation(cycle.obligation_id)

                # C5: Counterfactual review on failure — "what if we had chosen differently?"
                if (self.policy.causal_l3_on_failure
                        and len(self.causal_engine._observations) > 1
                        and cycle.plan_edges):
                    try:
                        # Try counterfactual: what if we had chosen a different plan?
                        # Use an alternative set of edges (reverse of what was tried)
                        alternative_edges = [(t, s) for s, t in cycle.plan_edges]
                        cf_result = self.causal_engine.counterfactual_query(
                            cycle.cycle_id, alternative_edges
                        )
                        cycle.counterfactual_review = cf_result
                        self._write_cieu(cycle, "counterfactual_review", [
                            f"cf_gain={cf_result.counterfactual_gain}",
                            f"cf_health={cf_result.predicted_health}",
                            f"cf_confidence={cf_result.confidence}",
                        ])
                    except Exception:
                        pass  # L3 review failed; don't block cycle
        else:
            # 成功：重置计数, clear inconclusive to prevent state leakage
            cycle.success = True
            cycle.inconclusive = False
            self._inconclusive_count = 0
            # Fix 5.2: CIEU record for health_improved
            self.cieu_store.write_dict(self._make_cieu_record(
                event_type="health_improved",
                action="health_improved",
                decision="allow",
                params={"health_before": cycle.health_before,
                        "health_after": cycle.health_after,
                        "suggestion_reduction": suggestion_reduction},
                result={"improvement": health_improvement},
                cycle=cycle,
            ))

        # 履行后置 obligation（如果成功）
        if cycle.success and self.omission_store and cycle.obligation_id:
            self._fulfill_obligation(cycle.obligation_id)
            # Fix 5.2: CIEU record for obligation_fulfilled
            self.cieu_store.write_dict(self._make_cieu_record(
                event_type="obligation_fulfilled",
                action="obligation_fulfilled",
                decision="allow",
                params={"obligation_id": cycle.obligation_id},
                result={"status": "fulfilled"},
                cycle=cycle,
            ))

        # 把本次循环写入 CausalEngine（构建 SCM 数据）
        # Gap 5: INCONCLUSIVE 循环不计入 succeeded 统计，避免混淆因果推断
        wired_before = [e for e in cycle.plan_edges]  # 本次之前
        wired_after  = [e for e in cycle.plan_edges if
                        self.planner.graph._edges.get(e) and
                        self.planner.graph._edges[e].is_wired]
        try:
            obl_count = (
                (len([o for o in self.omission_store.list_obligations()
                      if hasattr(o,'status') and str(o.status) in ('FULFILLED','fulfilled')]),
                 len(self.omission_store.list_obligations()))
                if self.omission_store else (0, 0)
            )
        except Exception:
            obl_count = (0, 0)

        # Gap 5: INCONCLUSIVE 循环记录到 CausalEngine，但不影响因果置信度
        # 只有明确成功或失败的循环才用于训练 SCM
        if not cycle.inconclusive:
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
        # BUG 2 FIX: Check if omission_engine exists before calling scan()
        if self.omission_engine:
            try:
                scan_result = self.omission_engine.scan()

                # ── Pearl Integration 3: OmissionEngine violations → CausalEngine ──
                # Feed obligation fulfillment/violation data as causal evidence:
                #   Obligation fulfilled → health maintained/improved (positive obs)
                #   Obligation violated → health degraded (negative obs)
                # This creates a causal link: obligation_fulfillment → health
                if self.omission_store:
                    try:
                        obligations = self.omission_store.list_obligations()
                        for ob in obligations:
                            ob_status = str(getattr(ob, 'status', '')).lower()
                            ob_id = getattr(ob, 'obligation_id', 'unknown')
                            entity_id = getattr(ob, 'entity_id', 'unknown')

                            if ob_status in ('fulfilled',):
                                # Fulfilled obligation → positive causal evidence
                                self.causal_engine.observe(
                                    health_before=cycle.health_before,
                                    health_after=cycle.health_after,
                                    obl_before=(0, 1),
                                    obl_after=(1, 1),
                                    edges_before=[],
                                    edges_after=[(entity_id, ob_id)],
                                    action_edges=[(entity_id, ob_id)],
                                    succeeded=True,
                                    cycle_id=f"obl_fulfilled_{ob_id}",
                                    suggestion_type="obligation_fulfilled",
                                )
                            elif ob_status in ('hard_overdue', 'soft_overdue',
                                               'failed'):
                                # Violated obligation → negative causal evidence
                                self.causal_engine.observe(
                                    health_before=cycle.health_before,
                                    health_after="degraded",
                                    obl_before=(0, 1),
                                    obl_after=(0, 1),
                                    edges_before=[],
                                    edges_after=[],
                                    action_edges=[(entity_id, ob_id)],
                                    succeeded=False,
                                    cycle_id=f"obl_violated_{ob_id}",
                                    suggestion_type="obligation_violated",
                                )
                    except Exception:
                        pass  # Causal feed failed; don't block cycle

            except Exception:
                pass  # policy.omission_scan_failure == "warn" — fail-soft

        # Fix 4.3: Reset handoff retry state after cycle completes
        # (success or failure), so the next cycle starts fresh.
        # Sticky count is only for consecutive handoff failures within run_one_cycle.
        self._handoff_retry_count = 0

        self._history.append(cycle)
        return cycle

    def pull_observations(self) -> List[Any]:
        """
        P1-3: Pull observations from GovernanceLoop instead of waiting for push.

        Path A sovereignty: actively pull latest observations from governance_loop
        to decide whether intervention is needed, rather than passively receiving
        suggestions from tighten().

        Returns:
            List of GovernanceObservation objects from governance_loop
        """
        if not hasattr(self.gloop, '_observations'):
            return []
        return list(self.gloop._observations)

    def evaluate_suggestion(self, suggestion: GovernanceSuggestion) -> bool:
        """
        P1-3: Path A autonomously decides whether to execute a suggestion.

        Decision criteria:
        - confidence >= policy.auto_confidence_threshold (default 0.65)
        - suggestion_type in supported types (wire, tighten, observe, etc.)
        - no conflicting human review gate

        Args:
            suggestion: GovernanceSuggestion to evaluate

        Returns:
            True if suggestion should be executed, False otherwise
        """
        # Reject low-confidence suggestions
        if suggestion.confidence < self.policy.auto_confidence_threshold:
            return False

        # Reject if human review is pending
        if self._human_review_required:
            return False

        # Accept only known suggestion types
        supported_types = {"wire", "tighten", "observe", "relax", "rewire", "review"}
        if suggestion.suggestion_type not in supported_types:
            return False

        return True

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

    # ── Fix 5.1: Standardized CIEU record helper ──────────────────────────────
    def _make_cieu_record(
        self,
        event_type: str,
        action: str,
        decision: str,
        params: dict,
        result: dict,
        cycle: MetaAgentCycle,
    ) -> dict:
        """
        Produce a consistent CIEU record with all required fields.
        Fix 5.1 + 5.3: every record has session_id, agent_id, event_type,
        action, decision, passed, params, result, contract_name.
        """
        passed = decision in ("allow", "inconclusive")
        return {
            "session_id":    cycle.cycle_id,
            "agent_id":      "path_a_agent",
            "event_type":    event_type,
            "action":        action,
            "decision":      decision,
            "passed":        passed,
            "params":        params,
            "result":        result,
            "contract_name": (cycle.contract.name
                              if cycle.contract else "unknown"),
        }

    def _write_cieu(self, cycle: MetaAgentCycle, event: str, violations) -> Optional[str]:
        try:
            viol_list = [v.message if hasattr(v, 'message') else str(v)
                         for v in violations]
            decision = "deny" if viol_list else "allow"
            record = self._make_cieu_record(
                event_type=f"path_a.{event.lower()}",
                action=event.lower(),
                decision=decision,
                params=cycle.to_dict(),
                result={"violations": viol_list},
                cycle=cycle,
            )
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
        from ystar.governance.causal_engine import CausalState

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
        except Exception as e:
            _log.warning("Failed to flag novel discovery: %s", e)
    def acknowledge_human_review(self) -> None:
        """Fix 6.2: Reset the human review gate so execution can resume."""
        self._human_review_required = False
        self._inconclusive_count = 0

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

    def propose_amendment(
        self,
        amendment_text: str,
        rationale: str,
        proposer: str = "path_a_agent",
    ) -> dict:
        """
        Propose a constitution amendment through the governed Path A process.

        The proposal is validated via check() like any other Path A action,
        and recorded in CIEU with event_type 'constitution_amendment_proposed'.
        Actual modification requires Board (human) approval — this method
        only creates and records the proposal.

        Args:
            amendment_text: The proposed change to PATH_A_AGENTS.md.
            rationale: Why this amendment is needed.
            proposer: Who is proposing (default: path_a_agent).

        Returns:
            dict with proposal_id, status, and any violations.
        """
        from ystar import check

        proposal_id = uuid.uuid4().hex[:8]
        cycle = MetaAgentCycle()

        # Build a contract for this amendment proposal action
        contract = suggestion_to_contract(
            GovernanceSuggestion(
                target_rule_id="constitution",
                suggestion_type="amendment",
                suggested_value=amendment_text[:200],
                confidence=0.5,
                rationale=rationale,
                observation_ref="amendment_proposal",
            ),
            allowed_modules=["constitution"],
            deadline_secs=self.cycle_timeout,
            policy=self.policy,
        )

        # Validate the proposal through check() — even constitution changes
        # must pass governance
        proposed_action = {
            "action": "propose_amendment",
            "amendment_text": amendment_text[:500],
            "rationale": rationale,
            "proposer": proposer,
        }
        check_result = check(proposed_action, {}, contract)

        if not check_result.passed:
            # Proposal itself violates governance — record and reject
            self.cieu_store.write_dict(self._make_cieu_record(
                event_type="constitution_amendment_proposed",
                action="propose_amendment",
                decision="deny",
                params={
                    "proposal_id": proposal_id,
                    "amendment_text": amendment_text[:200],
                    "rationale": rationale,
                    "proposer": proposer,
                },
                result={
                    "status": "rejected_by_check",
                    "violations": [
                        v.message if hasattr(v, 'message') else str(v)
                        for v in check_result.violations
                    ],
                },
                cycle=cycle,
            ))
            return {
                "proposal_id": proposal_id,
                "status": "rejected",
                "reason": "check_failed",
                "violations": [
                    v.message if hasattr(v, 'message') else str(v)
                    for v in check_result.violations
                ],
            }

        # Proposal passes check — record it, but actual modification
        # requires Board approval
        self.cieu_store.write_dict(self._make_cieu_record(
            event_type="constitution_amendment_proposed",
            action="propose_amendment",
            decision="allow",
            params={
                "proposal_id": proposal_id,
                "amendment_text": amendment_text[:200],
                "rationale": rationale,
                "proposer": proposer,
                "constitution_hash": self._constitution_hash,
            },
            result={
                "status": "proposed_awaiting_board",
                "requires": "board_approval",
            },
            cycle=cycle,
        ))

        self._history.append(cycle)
        return {
            "proposal_id": proposal_id,
            "status": "proposed",
            "requires": "board_approval",
            "constitution_hash": self._constitution_hash,
        }

    def _fail_obligation(self, obligation_id: str) -> None:
        """Fix 6.3: Explicitly mark obligation as FAILED on cycle failure."""
        try:
            from ystar.governance.omission_engine import ObligationStatus
            ob = self.omission_store.get_obligation(obligation_id)
            if ob:
                ob.status = ObligationStatus.FAILED
                ob.updated_at = time.time()
                self.omission_store.update_obligation(ob)
        except Exception:
            pass

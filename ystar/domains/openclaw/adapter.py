"""
OpenClaw × Y*  Adapter  v1.0.0
==============================

把真实 OpenClaw 运行时事件流转换为 Y* 可检查的结构化参数，
并把 check() 结果回送到执行链。

架构：
    OpenClaw Runtime Event
            ↓  extract_params()
    {file_path, action, patch_summary, ...}
            ↓  resolve_effective_contract()
    IntentContract  (从实际委托链解析，不是静态角色模板)
            ↓  check()
    CheckResult  + CIEU CallRecord
            ↓  enforce()
    "allow" | "deny" | "escalate"

与 v0.24.0 核心的关键接口：
    - IntentContract.is_subset_of()  →  链级单调性验证
    - DelegationChain.validate()     →  委托链完整性验证
    - check()                        →  局部动作边界验证
    - CallRecord                     →  CIEU 五元组审计记录
"""

from __future__ import annotations
import logging
import uuid

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

from ystar import check, CallRecord
from ystar.kernel.dimensions import (
    IntentContract,
    DelegationContract,
    DelegationChain,
)
from ystar.domains.openclaw import OpenClawDomainPack

# ── 向内核注入 OpenClaw 专属的语义参数名 ─────────────────────────────────────
# OpenClaw 事件有 task_intent / patch_summary 等字段，
# 这些字段的值语义上是「描述文本」而非「文件路径」。
# 内核不能硬编码这些名字——由适配层在 import 时注入。
try:
    from ystar.kernel.engine import register_non_path_params as _reg_non_path
    _reg_non_path({"task_intent", "patch_summary", "task_description",
                   "task_scope", "drift_reason", "session_goal"})
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════════════
# 1. Event Schema  —  OpenClaw 运行时事件的结构化定义
# ═══════════════════════════════════════════════════════════════════════

class EventType(str, Enum):
    """OpenClaw 产生的所有事件类型。"""

    # 工具执行
    FILE_READ         = "file_read"
    FILE_WRITE        = "file_write"
    CMD_EXEC          = "cmd_exec"
    WEB_FETCH         = "web_fetch"
    CODE_EXEC         = "code_exec"

    # Agent 生命周期
    SUBAGENT_SPAWN    = "subagent_spawn"
    HANDOFF           = "handoff"
    AGENT_TERMINATE   = "agent_terminate"

    # Session / 线程
    SESSION_START     = "session_start"
    SESSION_RESUME    = "session_resume"
    CONTEXT_INHERIT   = "context_inherit"

    # Skill 生命周期
    SKILL_INSTALL     = "skill_install"
    SKILL_LOAD        = "skill_load"
    SKILL_INVOKE      = "skill_invoke"

    # MCP
    MCP_TOOL_CALL     = "mcp_tool_call"
    MCP_RESOURCE_READ = "mcp_resource_read"


class EnforceDecision(str, Enum):
    ALLOW    = "allow"
    DENY     = "deny"
    ESCALATE = "escalate"   # 需要人工介入（如 SAE 超阈值、危险命令）


@dataclass
class OpenClawEvent:
    """
    OpenClaw 运行时事件的标准化表示。

    所有字段均为可选，因为不同 EventType 携带不同字段。
    adapter 通过 extract_params() 把相关字段转成 check() 可理解的 params dict。

    IMPORTANT: 必须使用关键字参数，避免字段顺序陷阱。
    timestamp 是第4个字段，task_ticket_id 是第17个字段。
    正确: OpenClawEvent(event_type=..., task_ticket_id="T-001", ...)
    错误: OpenClawEvent(EventType.X, "agent", "sess", "T-001", ...)  # T-001 进入 timestamp!
    """

    event_type:      EventType
    agent_id:        str                        # 产生事件的 agent 身份
    session_id:      str                        # 当前会话 ID
    timestamp:       float = field(default_factory=time.time)

    # ── 工具执行字段 ──────────────────────────────────────────────────
    file_path:       Optional[str] = None       # FILE_READ / FILE_WRITE
    command:         Optional[str] = None       # CMD_EXEC
    url:             Optional[str] = None       # WEB_FETCH
    code:            Optional[str] = None       # CODE_EXEC
    patch_summary:   Optional[str] = None       # FILE_WRITE 的变更描述
    tool_name:       Optional[str] = None       # MCP_TOOL_CALL
    tool_args:       Dict[str, Any] = field(default_factory=dict)

    # ── Agent 生命周期字段 ────────────────────────────────────────────
    parent_agent_id: Optional[str] = None       # SUBAGENT_SPAWN / HANDOFF 的委托方
    child_agent_id:  Optional[str] = None       # SUBAGENT_SPAWN 的被委托方
    task_description:Optional[str] = None       # 任务描述（用于语义检查）
    action_scope:    List[str] = field(default_factory=list)  # 声明的 action 范围

    # ── Skill 字段 ────────────────────────────────────────────────────
    skill_name:      Optional[str] = None
    skill_source:    Optional[str] = None       # "local" | "clawhub" | url

    # ── 上下文元数据 ──────────────────────────────────────────────────
    task_ticket_id:  Optional[str] = None
    session_auth:    bool = True
    extra:           Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# 2. 参数提取器  —  OpenClawEvent → check() params dict
# ═══════════════════════════════════════════════════════════════════════

def extract_params(event: OpenClawEvent) -> Dict[str, Any]:
    """
    把 OpenClaw 事件转换为 Y* check() 可理解的结构化参数。

    这是 adapter 最关键的映射层。不同事件类型提取不同字段。
    公共字段（task_ticket、session_auth）在所有事件里都出现。
    """

    # 公共上下文字段——所有合约的宪法层都会检查这些
    base: Dict[str, Any] = {
        "action":               event.event_type.value,
        "agent_id":             event.agent_id,
        "session_id":           event.session_id,
        "task_ticket_exists":   event.task_ticket_id is not None,
        "session_authenticated": event.session_auth,
        "timestamp":            event.timestamp,
    }

    if event.event_type == EventType.FILE_WRITE:
        base.update({
            "file_path":     event.file_path or "",
            "patch_summary": event.patch_summary or "",
        })

    elif event.event_type == EventType.FILE_READ:
        base.update({
            "file_path": event.file_path or "",
        })

    elif event.event_type == EventType.CMD_EXEC:
        base.update({
            "command": event.command or "",
        })

    elif event.event_type == EventType.WEB_FETCH:
        base.update({
            "url": event.url or "",
        })

    elif event.event_type == EventType.CODE_EXEC:
        base.update({
            "code_length": len(event.code or ""),
        })

    elif event.event_type == EventType.SUBAGENT_SPAWN:
        base.update({
            "parent_agent_id":  event.parent_agent_id or "",
            "child_agent_id":   event.child_agent_id or "",
            # 同时提供两个 key 保持向后兼容：
            # task_intent 是原始 key（已注册为非路径参数）
            # task_description 是标准 key（与 HANDOFF 保持一致）
            "task_intent":      event.task_description or "",
            "task_description": event.task_description or "",
            "action_scope":     event.action_scope,
        })

    elif event.event_type == EventType.HANDOFF:
        base.update({
            "from_agent":       event.parent_agent_id or "",
            "to_agent":         event.agent_id,
            "action_scope":     event.action_scope,
            "task_description": event.task_description or "",
        })

    elif event.event_type == EventType.SKILL_INVOKE:
        base.update({
            "skill_name": event.skill_name or "",
            "tool_name":  event.tool_name  or "",
        })

    elif event.event_type == EventType.MCP_TOOL_CALL:
        args = event.tool_args or {}
        base.update({
            "tool_name": event.tool_name or "",
            "url":       args.get("url", ""),
        })
        # 把 tool_args 里的路径/URL 类参数提升到顶层——
        # 使 only_paths / deny 约束能正常覆盖 MCP 工具调用
        # 路径类参数名（与 kernel engine._PATH_PARAM_NAMES 保持一致）
        _PATH_KEYS = {"path", "file", "filepath", "file_path", "dest",
                      "src", "source", "target", "output", "input",
                      "dir", "folder", "directory"}
        _URL_KEYS  = {"url", "endpoint", "uri", "href", "host"}
        for k, v in args.items():
            if k.lower() in _PATH_KEYS and v:
                base.setdefault("file_path", str(v))   # 首个路径参数
            if k.lower() in _URL_KEYS and v:
                base["url"] = str(v)

    # 附加 extra 字段（允许调用方注入自定义参数）
    base.update(event.extra)
    return base


# ═══════════════════════════════════════════════════════════════════════
# 3. 有效合约解析器  —  不是查静态角色模板，而是解析委托链上的实际合约
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SessionState:
    """
    追踪一个 OpenClaw session 里的完整委托链状态。

    这是 resolve_effective_contract() 的核心数据来源。
    在真实集成里，这个对象从 OpenClaw Gateway 的 session store 里获取。
    在测试/仿真里，可以手动构建。
    """

    session_id:       str
    pack:             Optional[OpenClawDomainPack] = None  # Fix 1: Optional, default None
    delegation_chain: Optional[DelegationChain] = None   # 完整委托链
    agent_contracts:  Dict[str, IntentContract] = field(default_factory=dict)
    # agent_id → 该 agent 实际持有的 IntentContract（动态合约，非静态模板）
    lineage:          Optional["SessionLineage"] = None   # sub-agent 生成树
    max_agent_depth:  int = 5                             # 最大嵌套深度限制
    trusted_skill_sources: List[str] = field(
        default_factory=lambda: ["local", "verified", "internal"]
    )  # 白名单 skill 来源

    # ── 核心安全字段 ──────────────────────────────────────────────────
    # handoff_contracts：只有经过 enforce(HANDOFF) 验证的合约才能写入
    # 任何动作的执行都只从这里取合约，取不到就 DENY
    # agent_contracts 降级为"初始化缓存"，不再作为运行时权威来源
    handoff_contracts: Dict[str, IntentContract] = field(default_factory=dict)

    # strict_handoff_mode：True 时强制所有 agent 必须通过 HANDOFF 才能执行动作
    # False 时保持向后兼容（测试/仿真用），从 agent_contracts 和链上 fallback
    strict_handoff_mode: bool = False

    # ── 可选治理引擎（Edge 1/2/3 接线后启用）────────────────────────────────
    # 默认 None，不影响任何现有测试；设置后自动触发 obligation 创建
    omission_engine:         Optional[Any] = None   # OmissionEngine 实例
    omission_rule_registry:  Optional[Any] = None   # RuleRegistry（domain packs）

    def get_contract_for(self, agent_id: str) -> Optional[IntentContract]:
        """
        解析 agent_id 的有效 IntentContract。

        strict_handoff_mode=True（生产环境）：
          只返回经过 enforce(HANDOFF) 验证写入的 handoff_contracts。
          取不到 → 返回 None → enforce() 将 DENY。
          这是唯一能堵住"绕过 HANDOFF 直接替换合约"攻击的方式。

        strict_handoff_mode=False（默认/测试兼容）：
          优先级：handoff_contracts > agent_contracts > DelegationChain > 角色模板
          保持向后兼容，不破坏现有测试。
        """
        # strict 模式：只信任经过 HANDOFF 验证的合约
        if self.strict_handoff_mode:
            return self.handoff_contracts.get(agent_id)

        # 兼容模式（默认）：
        # 1. 优先：经 HANDOFF 验证的合约
        if agent_id in self.handoff_contracts:
            return self.handoff_contracts[agent_id]

        # 2. 初始化缓存（仅用于测试/仿真）
        if agent_id in self.agent_contracts:
            return self.agent_contracts[agent_id]

        # 3. 从委托链里找
        if self.delegation_chain:
            for link in self.delegation_chain.links:
                if link.actor == agent_id:
                    self.agent_contracts[agent_id] = link.contract
                    return link.contract

        # 3.5. principal として chain に登録されている場合
        # （planner は actor でなく principal なので 3 では取れない）
        if self.delegation_chain:
            for link in self.delegation_chain.links:
                if link.principal == agent_id:
                    # planner の有効合約 = 最初の link の contract の constraints を継承
                    principal_c = IntentContract(
                        deny          = link.contract.deny,
                        deny_commands = link.contract.deny_commands,
                        only_paths    = link.contract.only_paths,
                        only_domains  = link.contract.only_domains,
                        invariant     = link.contract.invariant,
                        field_deny    = link.contract.field_deny,
                        value_range   = link.contract.value_range,
                        name          = f"{agent_id}_principal",
                    )
                    self.agent_contracts[agent_id] = principal_c
                    return principal_c

        # 4. Fallback：角色模板
        role_map = {
            "planner": "planner", "planner_agent": "planner",
            "coder": "coder",     "coder_agent":   "coder",
            "tester": "tester",   "tester_agent":  "tester",
            "reviewer": "reviewer","reviewer_agent":"reviewer",
            "researcher": "researcher","researcher_agent":"researcher",
            "release": "release", "release_agent": "release",
        }
        role = role_map.get(agent_id.lower())
        if role:
            return self.pack.make_contract(role)

        return None

    def register_handoff_contract(
        self,
        agent_id: str,
        contract: IntentContract,
    ) -> None:
        """
        将经过 HANDOFF 验证的合约写入 handoff_contracts。
        只有 enforce() 内部的 HANDOFF 路径可以调用这个方法。
        外部代码不应直接调用，只能通过触发 HANDOFF 事件来更新合约。
        """
        self.handoff_contracts[agent_id] = contract

    def record_handoff(
        self,
        from_agent: str,
        to_agent:   str,
        contract:   IntentContract,
        grant:      Optional[DelegationContract] = None,
    ) -> None:
        """
        记录一次 handoff，更新 to_agent 的实际合约。
        同时验证单调性：新合约必须是父合约的子集。
        """
        parent_contract = self.get_contract_for(from_agent)
        if parent_contract is not None:
            ok, viols = contract.is_subset_of(parent_contract)
            if not ok:
                # 记录漂移但不抛出异常——让 enforce() 决定如何处理
                self.agent_contracts[f"__drift__{to_agent}"] = contract
                raise DelegationDriftError(
                    f"Handoff from {from_agent!r} to {to_agent!r}: "
                    f"contract is not a subset of parent. "
                    f"Violations: {viols}"
                )
        self.agent_contracts[to_agent] = contract


class DelegationDriftError(Exception):
    """handoff 过程中约束被放宽时抛出。"""
    pass


def resolve_effective_contract(
    event:         OpenClawEvent,
    session_state: SessionState,
) -> Tuple[Optional[IntentContract], Optional[str]]:
    """
    解析当前 event 对应的有效 IntentContract。

    返回 (contract, error_reason)
    - contract=None, error_reason 非空 → 无法解析合约，应拒绝
    - contract 非空, error_reason=None → 正常路径
    """
    contract = session_state.get_contract_for(event.agent_id)
    if contract is not None:
        return contract, None

    # planner は chain の principal だが actor ではないため get_contract_for で取れない。
    # chain の最初の link.contract（planner が coder に委譲したもの）を
    # planner の有効合約として使う（同じ only_paths / only_domains を持つ）
    if session_state.delegation_chain:
        for link in session_state.delegation_chain.links:
            if link.principal == event.agent_id:
                parent_c = IntentContract(
                    deny          = link.contract.deny,
                    deny_commands = link.contract.deny_commands,
                    only_paths    = link.contract.only_paths,
                    only_domains  = link.contract.only_domains,
                    invariant     = link.contract.invariant,
                    field_deny    = link.contract.field_deny,
                    value_range   = link.contract.value_range,
                    name          = f"{event.agent_id}_principal",
                )
                return parent_c, None

    return None, f"No contract found for agent '{event.agent_id}'"
    return contract, None


# ═══════════════════════════════════════════════════════════════════════
# 4. CIEU 记录器  —  完整五元组 + 委托链溯源
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class OpenClawCIEU:
    """
    OpenClaw 场景下的 CIEU 扩展记录。
    在标准 CallRecord 之上增加 OpenClaw 特有的上下文字段。

    v0.28.0: event_id (UUID) + seq_global (μs monotonic) for production ordering.
    """

    call_record:     CallRecord              # Y* 标准五元组
    event:           OpenClawEvent           # 原始事件
    decision:        EnforceDecision
    parent_agent_id: Optional[str] = None   # 委托方 agent
    chain_depth:     int = 0                # 在委托链中的深度
    drift_detected:  bool = False
    drift_details:   Optional[str] = None
    # v0.28.0: production ordering — UUID for dedup, μs timestamp for ordering
    event_id:        str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    seq_global:      int = field(
        default_factory=lambda: int(time.time() * 1_000_000)
    )

    def to_dict(self) -> dict:
        return {
            "event_id":        self.event_id,
            "seq_global":      self.seq_global,
            "session_id":      self.event.session_id,
            "agent_id":        self.event.agent_id,
            "event_type":      self.event.event_type.value,
            "timestamp":       self.event.timestamp,
            "decision":        self.decision.value,
            "passed":          len(self.call_record.violations) == 0,
            "violations":      [
                {"dimension": v.dimension, "message": v.message}
                for v in self.call_record.violations
            ],
            "parent_agent":    self.parent_agent_id,
            "chain_depth":     self.chain_depth,
            "drift_detected":  self.drift_detected,
            "drift_details":   self.drift_details,
            "contract_hash":   (self.call_record.intent_contract.hash
                                if self.call_record.intent_contract else None),
        }


_cieu_log: List[OpenClawCIEU] = []   # 进程内日志（メモリ内、セッション終了で消える）

# CIEU 自動永続化設定
_auto_persist_store = None   # None のとき自動永続化しない

# ── Omission Governance 自動連携 ─────────────────────────────────────────────
_omission_adapter = None   # None のとき omission governance 無効

def configure_omission_governance(
    db_path: Optional[str] = ".ystar_omission.db",
    adapter: Optional["Any"] = None,
) -> None:
    """
    enforce() が OpenClawEvent を自動的に Omission Governance Engine に送るよう設定する。

    一度呼ぶだけで以降の全 SUBAGENT_SPAWN / HANDOFF / 各イベントが
    omission governance 層に自動供給される。

    使用方法：
        from ystar.domains.openclaw.adapter import configure_omission_governance
        configure_omission_governance()          # デフォルト .ystar_omission.db
        configure_omission_governance(adapter=my_adapter)  # 既存 adapter を使う

    引数：
        db_path: SQLite ストアパス（None = in-memory）
        adapter: 既存 OmissionAdapter インスタンス（指定時は db_path を無視）
    """
    global _omission_adapter
    try:
        if adapter is not None:
            _omission_adapter = adapter
            return
        from ystar.adapters.omission_adapter import create_adapter
        if db_path is not None:
            from ystar.governance.omission_store import OmissionStore
            store = OmissionStore(db_path=db_path)
            _omission_adapter = create_adapter(store=store)
        else:
            _omission_adapter = create_adapter()
    except ImportError:
        pass   # omission layer が使えない場合は静かに無視

def get_omission_adapter() -> Optional["Any"]:
    """現在の OmissionAdapter を返す（未設定なら None）。"""
    return _omission_adapter

def _auto_feed_omission(event: "OpenClawEvent") -> None:
    """
    enforce() から自動呼び出し：
    1. omission engine にイベントを供給する（既存）
    2. intervention engine に fulfillment 通知を送る（C1: v0.34新規）
       ← actor が obligation 履行イベントを送ったとき、干預を自動解除する
    """
    if _omission_adapter is None:
        return
    try:
        result = _omission_adapter.ingest_openclaw_event(event, source="openclaw_auto")
        # C1: auto-resolve intervention pulses for fulfilled obligations
        if _intervention_engine is not None and result and result.fulfilled:
            for ob in result.fulfilled:
                try:
                    _intervention_engine.resolve_for_actor(
                        actor_id               = ob.actor_id,
                        fulfilled_obligation_id= ob.obligation_id,
                    )
                except Exception:
                    pass
    except Exception:
        pass   # omission 処理失敗は runtime を止めない

# ── Intervention Engine 自動連携 ─────────────────────────────────────────────
_intervention_engine = None

# P2: GatingPolicy 已移至 Domain Pack（正确层级）
# adapter 从 accountability_pack 获取策略，不再自己定义
def _make_openclaw_gating_policy() -> "Any":
    """
    从 OpenClaw Domain Pack 获取 GatingPolicy。
    策略定义已从 adapter 层移至 accountability_pack.py（P2 分层修复）。
    Adapter 只负责获取，不负责定义。
    """
    try:
        from ystar.domains.openclaw.accountability_pack import get_openclaw_gating_policy
        return get_openclaw_gating_policy()
    except ImportError:
        try:
            from ystar.governance.intervention_engine import DEFAULT_GATING_POLICY
            return DEFAULT_GATING_POLICY
        except ImportError:
            return None


def configure_intervention_engine(engine: Optional["Any"] = None) -> None:
    """
    enforce() の obligation-first gate を有効化する。

    configure_omission_governance() の後に呼ぶ。engine を省略した場合は
    自動で OmissionAdapter から取得する。

    v0.36: 自動的に OpenClaw GatingPolicy を注入する。
    これにより "subagent_spawn" などの OpenClaw 専有動作が
    正しく gate される。核心引擎は汚染されない。

    使用方法：
        configure_omission_governance()
        configure_intervention_engine()   # gate 有効化（OpenClaw policy 自動注入）
    """
    global _intervention_engine
    if engine is not None:
        _intervention_engine = engine
        return
    try:
        from ystar.governance.intervention_engine import InterventionEngine
        omission_adapter = get_omission_adapter()
        openclaw_policy  = _make_openclaw_gating_policy()
        if omission_adapter:
            _intervention_engine = InterventionEngine(
                omission_store = omission_adapter.engine.store,
                cieu_store     = _auto_persist_store,
                gating_policy  = openclaw_policy,   # v0.36: inject OpenClaw policy
            )
    except ImportError:
        pass

def get_intervention_engine() -> Optional["Any"]:
    return _intervention_engine

def _run_gate_check(event: "OpenClawEvent") -> Optional["Any"]:
    """obligation-first gate — enforce() 入口で呼ぶ。"""
    if _intervention_engine is None:
        return None
    try:
        return _intervention_engine.gate_check(
            actor_id    = event.agent_id,
            action_type = event.event_type.value
                          if hasattr(event.event_type, "value") else str(event.event_type),
        )
    except Exception:
        return None


def configure_auto_persist(db_path: str = ".ystar_cieu.db") -> None:
    """
    enforce() が CIEU を自動的に SQLite に書き込むよう設定する。

    呼び出すだけで以降の全 enforce() 呼び出しが SQLite に永続化される。
    外部でセッション管理不要。

    使用方法：
        from ystar.domains.openclaw.adapter import configure_auto_persist
        configure_auto_persist()           # デフォルト .ystar_cieu.db
        configure_auto_persist("prod.db")  # カスタムパス
    """
    global _auto_persist_store
    try:
        from ystar.governance.cieu_store import CIEUStore
        _auto_persist_store = CIEUStore(db_path)
    except ImportError:
        _log.warning("CIEUStore not available — auto-persist disabled")

def _auto_write_cieu(record: "OpenClawCIEU") -> None:
    """CIEU レコードを自動永続化（configure_auto_persist() が呼ばれた場合）。"""
    if _auto_persist_store is not None:
        try:
            _auto_persist_store.write(record)
        except Exception as e:
            _log.error("CIEU auto-persist failed: %s", e, exc_info=True)


def get_cieu_log() -> List[OpenClawCIEU]:
    return list(_cieu_log)


def clear_cieu_log() -> None:
    _cieu_log.clear()


# ═══════════════════════════════════════════════════════════════════════
# 5. 治理职责分解函数 — Independent Governance Capabilities
# ═══════════════════════════════════════════════════════════════════════


def validate_delegation_chain(
    event:         OpenClawEvent,
    session_state: SessionState,
) -> Tuple[bool, Optional[str], Optional[IntentContract], Optional[IntentContract]]:
    """
    Validate HANDOFF delegation chain monotonicity.

    Checks that child contracts are proper subsets of parent contracts,
    and that the delegation chain itself is structurally valid.

    Args:
        event:         OpenClawEvent with event_type == HANDOFF
        session_state: Current session state with delegation chain

    Returns:
        Tuple of (is_valid, error_message, parent_contract, child_contract)
        - is_valid: True if delegation is valid, False otherwise
        - error_message: None if valid, error description if invalid
        - parent_contract: The parent's grant contract (for logging)
        - child_contract: The child's contract (for logging)

    Example:
        valid, error, parent_c, child_c = validate_delegation_chain(event, state)
        if not valid:
            print(f"Delegation violation: {error}")
    """
    drift_error = None
    chain_errors = []

    # Verify delegation chain structural integrity
    if session_state.delegation_chain:
        chain_errors = session_state.delegation_chain.validate()

    # HANDOFF contract resolution priority:
    # Parent contract: from delegation chain link (trusted source)
    # Child contract: from delegation chain first (trusted), then handoff_contracts
    parent_contract = _resolve_parent_grant_contract(
        event.parent_agent_id or "", event.agent_id,
        session_state
    )

    # Child contract: prefer delegation chain (trusted), fallback to handoff_contracts
    child_contract = None
    if session_state.delegation_chain:
        for link in session_state.delegation_chain.links:
            if link.actor == event.agent_id:
                child_contract = link.contract
                break
    if child_contract is None:
        child_contract = session_state.handoff_contracts.get(event.agent_id)
    if child_contract is None and not session_state.strict_handoff_mode:
        child_contract = session_state.get_contract_for(event.agent_id)

    # Check monotonicity: child ⊆ parent
    if parent_contract and child_contract:
        ok, viols = child_contract.is_subset_of(parent_contract)
        if not ok:
            drift_error = f"Contract drift: {'; '.join(viols)}"

    errors_combined = chain_errors + ([drift_error] if drift_error else [])
    is_valid = not bool(errors_combined)
    error_message = "; ".join(errors_combined) if errors_combined else None

    return is_valid, error_message, parent_contract, child_contract


def detect_spawn_drift(
    event:         OpenClawEvent,
    session_state: SessionState,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Detect goal drift in SUBAGENT_SPAWN events.

    Performs three-layer drift detection:
    1. Lineage depth check (max agent depth enforcement)
    2. Single-hop goal drift detection (v2 algorithm)
    3. Chain-level cumulative drift detection (ChainDriftDetector)

    Args:
        event:         OpenClawEvent with event_type == SUBAGENT_SPAWN
        session_state: Current session state with lineage tracking

    Returns:
        Tuple of (drifted, drift_reason, drift_category)
        - drifted: True if any drift detected
        - drift_reason: Human-readable description of the drift
        - drift_category: Category tag (e.g., "depth", "goal", "chain")

    Example:
        drifted, reason, category = detect_spawn_drift(event, state)
        if drifted:
            print(f"[{category}] Drift detected: {reason}")
    """
    # Layer 1: Lineage tracking + depth enforcement
    if session_state.lineage is not None:
        node = session_state.lineage.register_spawn(
            agent_id         = event.child_agent_id or event.agent_id,
            parent_agent_id  = event.parent_agent_id,
            task_description = event.task_description,
            action_scope     = event.action_scope,
        )
        depth_err = session_state.lineage.check_max_depth(
            session_state.max_agent_depth
        )
        if depth_err:
            return True, depth_err, "depth"

    # Layer 2: Single-hop goal drift detection (v2)
    parent_node = (
        session_state.lineage.nodes.get(event.parent_agent_id or "")
        if session_state.lineage else None
    )
    parent_scope = parent_node.action_scope if parent_node else event.action_scope
    drifted, drift_reason, drift_category = detect_goal_drift_v2(
        event.task_description or "", parent_scope
    )
    if drifted:
        formatted_reason = (
            drift_reason if (drift_reason or "").startswith(f"[{drift_category}]")
            else f"[{drift_category}] {drift_reason}"
        ) if drift_category else drift_reason
        return True, formatted_reason, drift_category or "goal"

    # Layer 3: Chain-level cumulative drift detection
    chain_detector = get_chain_detector(event.session_id)

    # Register root task from SessionLineage (first time only)
    if session_state.lineage and not chain_detector._chain:
        for agent_id_lin, node_lin in session_state.lineage.nodes.items():
            if node_lin.parent_agent_id is None:  # root node
                chain_detector.register_task(
                    agent_id         = agent_id_lin,
                    task_description = node_lin.task_description or "",
                    action_scope     = node_lin.action_scope or [],
                    parent_id        = None,
                    depth            = 0,
                )
                break

    # Register current task to chain
    chain_detector.register_task(
        agent_id         = event.agent_id,
        task_description = event.task_description or "",
        action_scope     = event.action_scope or [],
        parent_id        = event.parent_agent_id,
        depth            = len(chain_detector._chain),
    )

    # Detect chain-level drift
    chain_drifted, chain_reason, chain_category = chain_detector.detect(
        current_task  = event.task_description or "",
        current_scope = event.action_scope or [],
        agent_id      = event.agent_id,
        parent_id     = event.parent_agent_id,
    )
    if chain_drifted:
        return True, f"[{chain_category}] {chain_reason}", chain_category

    # No drift detected
    return False, None, None


def check_skill_risk(
    event: OpenClawEvent,
) -> Tuple[bool, Optional[str]]:
    """
    Assess supply chain risk for skill installation/loading.

    Evaluates whether a skill poses security or provenance risks based on
    its source, name, and other metadata. High-risk skills may be denied
    or escalated for manual approval.

    Args:
        event: OpenClawEvent with event_type in (SKILL_INSTALL, SKILL_LOAD)

    Returns:
        Tuple of (is_safe, risk_reason)
        - is_safe: True if skill is safe to use, False if risky
        - risk_reason: None if safe, description of risk if unsafe

    Example:
        is_safe, reason = check_skill_risk(event)
        if not is_safe:
            if "approval" in reason:
                decision = "ESCALATE"  # needs manual approval
            else:
                decision = "DENY"      # block immediately
    """
    is_safe, risk_reason = assess_skill_risk(
        event.skill_name or "", event.skill_source or "unknown"
    )
    return is_safe, risk_reason


# ═══════════════════════════════════════════════════════════════════════
# 5. 执行反馈器  —  主入口
# ═══════════════════════════════════════════════════════════════════════

def enforce(
    event:         OpenClawEvent,
    session_state: SessionState,
    seq:           int = 0,
) -> Tuple[EnforceDecision, List["OpenClawCIEU"]]:
    """
    OpenClaw × Y* 完整治理入口（多 Agent 会话场景）。

    ┌─────────────────────────────────────────────────────────────┐
    │  轻量接入（推荐新用户）：使用 adapters/hook.py 的 check_hook()  │
    │                                                              │
    │    from ystar.adapters.hook import check_hook                │
    │    response = check_hook(hook_payload, policy)               │
    │                                                              │
    │  完整治理（多 Agent 委托链场景）：使用本函数                    │
    └─────────────────────────────────────────────────────────────┘

    enforce() 比 check_hook() 多做以下事情（均需 SessionState）：
      · HANDOFF 委托链单调性验证（子合约必须是父合约子集）
      · SUBAGENT_SPAWN lineage 追踪 + goal drift 检测（三层）
      · DelegationChain.validate() 全链完整性检查
      · Skill 供应链风险评估（SkillProvenance）
      · Omission Governance 事件自动注入
      · Intervention Gate（obligation-first 门控）
      · CIEU 记录生成（OpenClawCIEU 五元组）

    这些治理职责通过 session_state 共享状态，不可简单拆分。
    如需独立使用某项能力，见 governance/ 层的对应模块。

    Returns:
        (EnforceDecision, List[OpenClawCIEU])
        - EnforceDecision: allow / deny / escalate
        - List[OpenClawCIEU]: 本次产生的 CIEU 记录
    """
    cieu_records: List[OpenClawCIEU] = []

    # ── Omission Governance: 全イベントを自動供給 ──────────────────
    _auto_feed_omission(event)

    # ── v0.33 Intervention Gate: obligation-first gating ─────────
    _gate = _run_gate_check(event)
    if _gate is not None:
        from ystar.governance.intervention_models import GateDecision
        if _gate.decision == GateDecision.DENY:

            # ── v0.50 DEADLOCK FIX: Exempt actions that fulfill obligations ──
            # When obligation is overdue, blocking ALL tool calls creates a
            # deadlock: the agent cannot write the report that would fulfill
            # the obligation. Exempt actions that plausibly serve fulfillment:
            #   - file_read: reading info is never harmful, always needed
            #   - file_write to reports/: writing progress report = fulfilling
            #   - mcp_tool_call: gov MCP tools (query/fulfill obligations)
            #   - ToolSearch-mapped calls: schema lookup, not a real write
            _exempt = False
            _etype = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
            _fpath = (event.file_path or "").replace("\\", "/")

            if _etype == "file_read":
                _exempt = True  # Read never harmful
            elif _etype == "file_write" and _fpath:
                # Allow writes to reports/ (= obligation fulfillment)
                import os as _os
                try:
                    _repo = _os.environ.get("YSTAR_COMPANY_ROOT", "")
                    if _repo:
                        _rel = _os.path.relpath(_fpath, _repo).replace("\\", "/")
                    else:
                        _rel = _fpath
                except ValueError:
                    _rel = _fpath
                if _rel.startswith("reports/") or "/reports/" in _fpath:
                    _exempt = True
            elif _etype == "mcp_tool_call":
                _exempt = True  # Gov MCP tools needed to query/fulfill obligations

            if _exempt:
                _log.info(
                    "Obligation gate EXEMPT: %s %s (overdue obligation: %s +%.0fs)",
                    _etype, _fpath or "", _gate.blocking_omission_type, _gate.overdue_secs,
                )
            else:
                # ── Original DENY path ──
                _gate_detail = (
                    f"intervention_gate: actor '{event.agent_id}' has hard_overdue "
                    f"obligation '{_gate.blocking_omission_type}' "
                    f"(+{_gate.overdue_secs:.0f}s). "
                    f"Suggested: {_gate.suggested_action}"
                )
                rec = OpenClawCIEU(
                    call_record = CallRecord(
                        seq=seq, func_name=event.event_type.value,
                        params=extract_params(event), result={},
                        violations=[], intent_contract=IntentContract(name="intervention_gate"),
                    ),
                    event         = event,
                    decision      = EnforceDecision.DENY,
                    drift_detected= True,
                    drift_details = _gate_detail,
                )
                _cieu_log.append(rec)
                _auto_write_cieu(rec)
                # C2: also write to omission CIEU if available (unified audit trail)
                if _omission_adapter is not None:
                    try:
                        import time as _t, uuid as _u
                        from ystar.governance.omission_models import GovernanceEvent as _GE, GEventType as _GET
                        _ge = _GE(
                            event_type  = _GET.OBLIGATION_GATE_DENY,
                            entity_id   = event.session_id or event.agent_id,
                            actor_id    = event.agent_id,
                            ts          = _t.time(),
                            payload     = {
                                "blocked_action":       event.event_type.value,
                                "blocking_omission":    _gate.blocking_omission_type,
                                "overdue_secs":         _gate.overdue_secs,
                                "pulse_id":             _gate.pulse_id,
                            },
                            source      = "intervention_gate",
                        )
                        _omission_adapter.engine.store.add_event(_ge)
                    except Exception:
                        pass
                cieu_records.append(rec)
                return EnforceDecision.DENY, cieu_records

    # ── 特殊路径：HANDOFF 触发委托链单调性验证 ──────────────────────
    if event.event_type == EventType.HANDOFF:
        # Use extracted validation function
        is_valid, error_message, parent_contract, child_contract = validate_delegation_chain(
            event, session_state
        )
        drift_detected = not is_valid

        # HANDOFF 验证通过 → 将合约写入 handoff_contracts（权威来源）
        # 只有这里能写入，外部代码无法绕过
        if not drift_detected and child_contract is not None:
            session_state.register_handoff_contract(event.agent_id, child_contract)

        # 构造 CIEU 记录
        params = extract_params(event)
        dummy_contract = child_contract or IntentContract(name="unknown")
        result = check(params, {}, dummy_contract)

        cr = CallRecord(
            seq            = seq,
            func_name      = f"handoff.{event.parent_agent_id}->{event.agent_id}",
            params         = params,
            result         = {"validation_error": error_message},
            violations     = result.violations,
            intent_contract= dummy_contract,
        )

        decision = EnforceDecision.DENY if drift_detected else EnforceDecision.ALLOW
        rec = OpenClawCIEU(
            call_record     = cr,
            event           = event,
            decision        = decision,
            parent_agent_id = event.parent_agent_id,
            drift_detected  = drift_detected,
            drift_details   = error_message,
        )
        _cieu_log.append(rec)
        _auto_write_cieu(rec)
        cieu_records.append(rec)
        return decision, cieu_records

    # ── Skill 供应链风险检查（主线 A.1）────────────────────────────
    if event.event_type in (EventType.SKILL_INSTALL, EventType.SKILL_LOAD):
        # Use extracted skill risk assessment function
        is_safe, risk_reason = check_skill_risk(event)
        if not is_safe:
            rec = OpenClawCIEU(
                call_record = CallRecord(
                    seq=seq, func_name=event.event_type.value,
                    params=extract_params(event), result={},
                    violations=[],
                    intent_contract=IntentContract(name="skill_guard"),
                ),
                event         = event,
                decision      = (EnforceDecision.ESCALATE
                                 if "approval" in (risk_reason or "")
                                 else EnforceDecision.DENY),
                drift_details = risk_reason,
            )
            _cieu_log.append(rec)
            _auto_write_cieu(rec)
            cieu_records.append(rec)
            # ── Edge 1 WIRED: SkillProvenance → OmissionEngine.scan ──────────
            # 高风险技能 → 自动创建 review obligation
            # 这关闭了 ModuleGraph 中 skill_risk → obligation_track 的缺口
            if session_state.omission_engine is not None:
                _create_skill_review_obligation(
                    omission_engine = session_state.omission_engine,
                    skill_name      = event.skill_name or "unknown",
                    risk_reason     = risk_reason or "high-risk skill",
                    seq             = seq,
                )
            return rec.decision, cieu_records

    # ── Subagent spawn：lineage 追踪 + goal drift 检测（主线 A.2 + B）──
    if event.event_type == EventType.SUBAGENT_SPAWN:
        # Use extracted spawn drift detection function
        drifted, drift_reason, drift_category = detect_spawn_drift(event, session_state)

        if drifted:
            # Determine guard name based on category
            guard_name = {
                "depth": "depth_guard",
                "goal": "goal_guard",
                "chain": "chain_drift_guard",
            }.get(drift_category or "", "goal_guard")

            func_name = "subagent_spawn.chain" if drift_category == "chain" else "subagent_spawn"

            rec = OpenClawCIEU(
                call_record=CallRecord(
                    seq=seq, func_name=func_name,
                    params=extract_params(event), result={},
                    violations=[], intent_contract=IntentContract(name=guard_name),
                ),
                event=event, decision=EnforceDecision.DENY,
                drift_detected=True,
                drift_details=drift_reason,
            )
            _cieu_log.append(rec)
            _auto_write_cieu(rec)
            cieu_records.append(rec)

            # ── Edge 2 WIRED: ChainDriftDetector → OmissionEngine.scan ───────
            # Chain drift → create "drift_acknowledgement" obligation
            if drift_category == "chain" and session_state.omission_engine is not None:
                _create_drift_tracking_obligation(
                    omission_engine = session_state.omission_engine,
                    agent_id        = event.agent_id,
                    drift_type      = drift_reason or "chain drift",
                    seq             = seq,
                )

            return EnforceDecision.DENY, cieu_records

    # ── Fix 7: DelegationChain.validate() on SPAWN ────────────────
    # SUBAGENT_SPAWN 必须通过委托链单调性检查，检测到违规立即 DENY
    if event.event_type == EventType.SUBAGENT_SPAWN and session_state.delegation_chain:
        # ── Edge 3 WIRED: DelegationChain → apply_finance/devops_pack ────────
        # 委托深度 ≥ 3 时自动应用更严格的领域包
        # 解决"深层子 agent 绕过顶层合约"的风险
        _depth = getattr(session_state.delegation_chain, "depth", 0)
        if _depth >= 3 and session_state.omission_rule_registry is not None:
            try:
                from ystar.domains.omission_domain_packs import apply_devops_pack
                apply_devops_pack(
                    registry = session_state.omission_rule_registry,
                    strict   = True,
                )
            except Exception:
                pass  # domain pack 不可用时静默跳过
        chain_errors = session_state.delegation_chain.validate()
        if chain_errors:
            _detail = "delegation_chain invalid: " + "; ".join(chain_errors)
            rec = OpenClawCIEU(
                call_record=CallRecord(
                    seq=seq, func_name="subagent_spawn.delegation_chain",
                    params=extract_params(event), result={},
                    violations=[], intent_contract=IntentContract(name="delegation_chain_guard"),
                ),
                event=event, decision=EnforceDecision.DENY,
                drift_detected=True,
                drift_details=_detail,
            )
            _cieu_log.append(rec)
            _auto_write_cieu(rec)
            cieu_records.append(rec)
            return EnforceDecision.DENY, cieu_records

    # ── 通用路径：提取参数 → 解析合约 → check() ─────────────────────
    contract, err = resolve_effective_contract(event, session_state)

    if contract is None:
        # 无法解析合约 → 默认拒绝（fail-closed）
        rec = OpenClawCIEU(
            call_record = CallRecord(
                seq=seq, func_name=event.event_type.value,
                params=extract_params(event), result={},
                violations=[], intent_contract=IntentContract(name="unknown"),
            ),
            event    = event,
            decision = EnforceDecision.DENY,
            drift_details = f"No contract: {err}",
        )
        _cieu_log.append(rec)
        _auto_write_cieu(rec)
        cieu_records.append(rec)
        return EnforceDecision.DENY, cieu_records

    params = extract_params(event)
    result = check(params, {}, contract)

    # 决策逻辑：
    # - passed → ALLOW
    # - violated + severity触发升级条件 → ESCALATE（需人工介入）
    # - violated → DENY
    if result.passed:
        decision = EnforceDecision.ALLOW
    elif any(v.dimension == "value_range" for v in result.violations):
        # value_range 违规通常意味着数值越界，需要升级而非直接拒绝
        decision = EnforceDecision.ESCALATE
    else:
        decision = EnforceDecision.DENY

    cr = CallRecord(
        seq             = seq,
        func_name       = event.event_type.value,
        params          = params,
        result          = {},
        violations      = result.violations,
        intent_contract = contract,
    )

    rec = OpenClawCIEU(
        call_record     = cr,
        event           = event,
        decision        = decision,
        parent_agent_id = event.parent_agent_id,
        chain_depth     = _get_chain_depth(event.agent_id, session_state),
    )
    _cieu_log.append(rec)
    _auto_write_cieu(rec)
    cieu_records.append(rec)
    return decision, cieu_records


def _get_chain_depth(agent_id: str, state: SessionState) -> int:
    """从委托链里找 agent 的深度（0=origin）。"""
    if not state.delegation_chain:
        return 0
    for i, link in enumerate(state.delegation_chain.links):
        if link.actor == agent_id:
            return i + 1
    return 0


def _resolve_parent_grant_contract(
    parent_agent_id: str,
    child_agent_id:  str,
    state:           SessionState,
) -> Optional[IntentContract]:
    """
    解析父 agent 实际授权给子 agent 的合约（link.contract）。

    正确语义：
      HANDOFF 的单调性检查应比较 child_contract ⊆ parent_grant_contract
      其中 parent_grant_contract = chain 里 principal==parent_agent_id 的 link.contract
      这是父 agent "向子 agent 颁发的授权"，而不是父 agent 自己的角色合约。

    举例：
      planner → coder_agent: link.contract = coder_inherited (含 ./src/payments)
      coder_agent → tester_agent: link.contract = tester_inherited
      HANDOFF 检查 tester_inherited ⊆ coder_inherited ✓
    """
    if state.delegation_chain:
        # 找 principal==parent_agent_id 的授权 link
        for link in state.delegation_chain.links:
            if link.principal == parent_agent_id and link.actor == child_agent_id:
                return link.contract
        # 找 actor==child_agent_id 的 link（找到其被授权的合约）
        for link in state.delegation_chain.links:
            if link.actor == child_agent_id:
                return link.contract

    # fallback：用父 agent 的角色模板
    return state.get_contract_for(parent_agent_id)


# ═══════════════════════════════════════════════════════════════════════
# 便利函数：快速构建 SessionState
# ═══════════════════════════════════════════════════════════════════════

def make_session(
    session_id:      str,
    allowed_paths:   Optional[List[str]] = None,
    allowed_domains: Optional[List[str]] = None,
    pack:            Optional[OpenClawDomainPack] = None,
    chain:           Optional[DelegationChain] = None,
    strict:          bool = False,
) -> SessionState:
    """
    快速构建一个 SessionState。

    allowed_paths:   planner 批准的文件范围
    allowed_domains: 允许的外部域名白名单。
                     指定后，researcher 以外的 agent 也会受到域名限制。
                     不指定则使用默认的 doc_domains（researcher专用）。
    strict:          True 时启用 strict_handoff_mode（生产环境推荐）
    chain:           已有的委托链（可选）
    """
    from ystar.domains.openclaw import make_openclaw_chain

    if pack is None:
        pack = OpenClawDomainPack(workspace_root="./workspace")

    if chain is None and allowed_paths is not None:
        chain = make_openclaw_chain(
            pack,
            allowed_paths=allowed_paths,
            allowed_domains=allowed_domains or [],
        )

    state = SessionState(
        session_id          = session_id,
        pack                = pack,
        delegation_chain    = chain,
        strict_handoff_mode = strict,
    )
    return state


# ═══════════════════════════════════════════════════════════════════════
# 主线 A.1  Skill 供应链风险评估
# ═══════════════════════════════════════════════════════════════════════
# ChatGPT 报告: ClawHub 2,857个skill中约12%恶意，含数据泄露/提示注入
# 现在对 SKILL_INSTALL 做结构化风险评估

SKILL_RISK_HIGH    = {"clawhub", "npm", "pip", "unknown"}    # 高风险来源
SKILL_RISK_LOW     = {"local", "verified", "internal"}        # 低风险来源

# 已知恶意/高风险 skill 关键词
# 原始规则 + MITRE ATLAS v4.5 预训练扩充（155技术+52案例，2026-03）
SKILL_DENY_PATTERNS = [
    # 原始规则
    "exfil", "keylog", "reverse_shell", "exec_eval",
    "base64_decode_exec", "pickle_load_remote",
    "prompt_inject", "jailbreak",
    # ATLAS 预训练新增（exfiltration/execution/evasion/persistence 战术）
    "inject", "backdoor", "bypass", "evasion",
    "adversarial", "malware", "poison", "shell",
    # ClawHavoc 真实攻击命名模式（2026-01）
    "stealer", "harvester", "dumper", "exfiltrator",
    "credential_tool", "token_grab", "wallet_steal",
]

# ESCALATE 级别关键词（来源可疑但未确认恶意）
SKILL_ESCALATE_PATTERNS = [
    "reconn", "staging", "lateral", "discover_",
    "scan_", "enum_", "probe_",
]


@dataclass
class SkillProvenance:
    """
    Skill 供应链的完整 provenance 记录 (v0.28.0)。
    ChatGPT 建议的 "skill provenance sealing" 实现。
    """
    name:           str
    source:         str
    version:        Optional[str] = None
    content_hash:   Optional[str] = None   # SHA256 of skill content
    publisher:      Optional[str] = None
    install_chain:  List[str] = field(default_factory=list)

    def risk_level(self) -> str:
        _, reason = assess_skill_risk(
            self.name, self.source, self.version, self.publisher)
        if reason is None:            return "safe"
        if "approval" in reason:      return "escalate"
        return "deny"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "source": self.source,
            "version": self.version, "content_hash": self.content_hash,
            "publisher": self.publisher, "install_chain": self.install_chain,
            "risk_level": self.risk_level(),
        }


def assess_skill_risk(
    skill_name:   str,
    skill_source: str,
    version:      Optional[str] = None,
    publisher:    Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    评估 skill 供应链风险 (v0.28.0: version/publisher 追加)。
    返回 (is_safe, risk_reason)。
    """
    source_lower = (skill_source or "unknown").lower()
    name_lower   = (skill_name or "").lower()

    for pattern in SKILL_DENY_PATTERNS:
        if pattern in name_lower:
            return False, f"Skill name matches known malicious pattern: '{pattern}'"

    if source_lower in SKILL_RISK_HIGH:
        ver_info = f" (v{version})" if version else " (no version — pinning required)"
        return False, f"Skill source '{skill_source}' requires human approval{ver_info}"

    if publisher is None and source_lower not in SKILL_RISK_LOW:
        return False, f"Skill '{skill_name}' has no verified publisher — requires approval"

    return True, None

# ═══════════════════════════════════════════════════════════════════════
# 主线 A.2  Goal Drift 检测
# ═══════════════════════════════════════════════════════════════════════
# ChatGPT 报告: 语义投机目前只覆盖 patch_summary 关键词，
# 深层 goal drift（任务目标本身被偷换）还没有检测手段。
#
# 实现思路：
#   每次 SUBAGENT_SPAWN 或 HANDOFF 时，检查子任务描述
#   是否在父任务的授权 action_scope 语义范围内。
#   用 field_deny + action_scope 约束组合检测。

# 任务目标漂移的语义信号（任务从"修bug"滑向"改架构/改部署"）
GOAL_DRIFT_SIGNALS = [
    # 从"修复"滑向"重构/重设计"
    "refactor entire", "redesign", "rewrite from scratch",
    "change architecture", "migrate to",
    # 从"测试"滑向"跳过测试"
    "skip all tests", "disable ci", "bypass tests",
    # 从"修bug"滑向"改部署/改基础设施"
    "modify production", "update deployment", "change infra",
    "alter database schema", "drop table",
    # 从"代码改动"滑向"权限提升"
    "grant admin", "elevate privilege", "add sudo",
    "modify .env", "change credentials",
    # 数据外泄类
    "exfiltrate", "exfil", "send data to", "upload to external",
    "leak", "steal data", "export all",
    # 后门/持久化类
    "install backdoor", "backdoor", "persistence mechanism",
    "remote access", "reverse shell", "command and control",
    # 监控破坏类
    "disable security", "disable monitoring", "disable logging",
    "disable audit", "turn off logging", "bypass monitoring",
    "disable firewall", "disable antivirus",
    # 审计追踪破坏类
    "overwrite audit", "delete logs", "clear logs",
    "remove audit trail", "wipe logs", "tamper with logs",
    # 容器/系统级提权
    "escalate privilege", "escalate privileges", "escalate container",
    "container escape", "privilege escalation", "privilege esc",
    "escape sandbox", "break out of",
    # 敏感系统文件访问
    "/etc/shadow", "/etc/sudoers", "id_rsa", ".ssh/authorized_keys",
    "private key", "access shadow",
    # 横向渗透
    "lateral movement", "pivot to", "spread to other",
]


def _tokenize(text: str) -> set:
    """把文本拆成小写单词集合，用于词级匹配（抗变形攻击）。"""
    import re
    return set(re.findall(r'\b[a-z]+\b', text.lower()))


def _tokens_contain_pair(tokens: set, word_a: str, word_b: str) -> bool:
    """检查 tokens 里是否同时含有 word_a 和 word_b 的词根。"""
    # 简单词根匹配：检查 token 是否以目标词开头（cover: log/logs, test/tests）
    def matches(token_set, word):
        return any(t == word or t.startswith(word) for t in token_set)
    return matches(tokens, word_a) and matches(tokens, word_b)


# 词级配对信号（不依赖子字符串顺序，抗插词攻击）
_TOKEN_PAIR_SIGNALS: List[Tuple[str, str, str]] = [
    # (word_a, word_b, category)
    ("delete",   "test",    "evidence_tampering"),
    ("remove",   "test",    "evidence_tampering"),
    ("skip",     "test",    "evidence_tampering"),
    ("wipe",     "test",    "evidence_tampering"),
    ("bypass",   "test",    "evidence_tampering"),
    ("clear",    "log",     "evidence_tampering"),
    ("delete",   "log",     "evidence_tampering"),
    ("wipe",     "log",     "evidence_tampering"),
    ("erase",    "log",     "evidence_tampering"),
    ("remove",   "log",     "evidence_tampering"),
    ("clean",    "log",     "evidence_tampering"),   # "clean up log files"
    ("clear",    "audit",   "evidence_tampering"),
    ("delete",   "audit",   "evidence_tampering"),
    ("wipe",     "audit",   "evidence_tampering"),
    ("remove",   "audit",   "evidence_tampering"),
    ("hide",     "error",   "goal_substitution"),
    ("suppress", "warning", "goal_substitution"),
    ("suppress", "error",   "goal_substitution"),
    ("grant",    "admin",   "authority_escalation"),
    ("grant",    "sudo",    "authority_escalation"),
    ("elevate",  "privilege","authority_escalation"),
    ("push",     "production","scope_expansion"),
    ("deploy",   "production","scope_expansion"),
    ("modify",   "production","scope_expansion"),
    ("send",     "credential","data_exfiltration"),
    ("export",   "credential","data_exfiltration"),
    ("dump",     "database",  "data_exfiltration"),
    ("install",  "backdoor",  "backdoor_persistence"),
    ("add",      "backdoor",  "backdoor_persistence"),
    ("plant",    "backdoor",  "backdoor_persistence"),
]


def detect_goal_drift(
    task_description: str,
    original_scope:   List[str],
) -> Tuple[bool, Optional[str]]:
    """
    检测子任务描述是否偏离原始 action_scope。

    v2 改进：词级匹配（抗插词/变形攻击）+ 原有子字符串检测双保险。
    返回 (drifted, reason)。
    """
    if not task_description:
        return False, None

    desc_lower = task_description.lower()
    tokens     = _tokenize(task_description)

    # ── 层 1：原有子字符串信号（62 条）────────────────────────────────
    for signal in GOAL_DRIFT_SIGNALS:
        if signal in desc_lower:
            return True, f"Goal drift signal detected: '{signal}' in task description"

    # ── 层 2：词级配对信号（新增，抗变形）────────────────────────────
    for word_a, word_b, category in _TOKEN_PAIR_SIGNALS:
        if _tokens_contain_pair(tokens, word_a, word_b):
            return True, (
                f"[{category}] Token-pair drift detected: "
                f"'{word_a}' + '{word_b}' in task description"
            )

    # ── 层 3：scope vs task 动词越界（原有逻辑，精化）────────────────
    if original_scope:
        scope_str = " ".join(original_scope).lower()
        # deploy 到 production/prod/live 才告警，staging/qa/dev 属正常流程
        if "deploy" in desc_lower and "deploy" not in scope_str:
            prod_signals = ["production", "prod ", "live environment", "live server"]
            if any(p in desc_lower for p in prod_signals):
                return True, "Task deploys to production but action_scope does not include deploy"
        # database 只在有写入/导出/删除意图时才告警，只读查询是合法的
        if "database" in desc_lower and "database" not in scope_str:
            db_danger = ["dump", "drop", "delete from", "truncate",
                         "export database", "database backup to external"]
            if any(d in desc_lower for d in db_danger):
                return True, "Task performs dangerous database operation outside scope"

    return False, None


# ── 语义归一化层（LLM 辅助，只升级不阻断）──────────────────────────────

_SEMANTIC_DRIFT_PROMPT = """You are a security analyzer for AI agent governance.

Given a task description, determine if it semantically matches any of these dangerous patterns:
1. evidence_tampering: deleting/clearing logs, audit trails, test results, history records
2. authority_escalation: gaining elevated permissions, admin access, root, sudo
3. goal_substitution: hiding errors, suppressing warnings, making tests pass by removing them
4. data_exfiltration: sending sensitive data outside, exporting credentials, database dumps
5. backdoor_persistence: installing backdoors, remote access, persistence mechanisms
6. scope_expansion: accessing systems/files outside the original task scope

Task description: "{task}"
Original task scope: {scope}

Respond with ONLY a JSON object:
{{"category": "<category_name or null>", "confidence": <0.0-1.0>, "reason": "<brief explanation>"}}

If none of the patterns apply, return: {{"category": null, "confidence": 0.0, "reason": "benign"}}"""


def _semantic_drift_check(
    task_description: str,
    original_scope:   List[str],
    api_call_fn:      Any,
) -> Tuple[Optional[str], float, str]:
    """
    用 LLM 做语义漂移分类。

    返回 (category_or_None, confidence, reason)。
    这是不确定层——只产出"怀疑"信号，不直接阻断。
    """
    import json as _json
    try:
        prompt = _SEMANTIC_DRIFT_PROMPT.format(
            task  = task_description[:300],
            scope = original_scope or [],
        )
        raw = api_call_fn(prompt)
        # 清理 markdown 代码块
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        obj = _json.loads(raw)
        cat  = obj.get("category")
        conf = float(obj.get("confidence", 0.0))
        why  = obj.get("reason", "")
        if cat and cat != "null":
            return cat, conf, why
        return None, 0.0, why
    except Exception:
        return None, 0.0, "parse_error"


def detect_goal_drift_semantic(
    task_description: str,
    original_scope:   List[str],
    api_call_fn:      Any = None,
    confidence_threshold: float = 0.75,
) -> Tuple[bool, Optional[str], Optional[str], str]:
    """
    完整语义漂移检测：确定性层 + LLM 语义层。

    检测优先级：
      1. 确定性词级检测（阻断）
      2. LLM 语义分类（高置信度 → 升级，低置信度 → 警告）

    Args:
        task_description:     当前任务描述
        original_scope:       父 agent 的授权 action_scope
        api_call_fn:          LLM 调用函数（None = 跳过语义层）
        confidence_threshold: LLM 置信度高于此值才升级（默认 0.75）

    Returns:
        (drifted, reason, category, action)
        action: "block" | "escalate" | "warn" | "allow"
    """
    # ── 确定性层（阻断）─────────────────────────────────────────────
    drifted, reason = detect_goal_drift(task_description, original_scope)
    if drifted:
        return True, reason, "deterministic", "block"

    # ── 语义层（仅当有 api_call_fn）──────────────────────────────────
    if api_call_fn is None:
        return False, None, None, "allow"

    category, confidence, llm_reason = _semantic_drift_check(
        task_description, original_scope, api_call_fn
    )

    if category is None:
        return False, None, None, "allow"

    if confidence >= confidence_threshold:
        # 高置信度 → 升级人工审批（不自动阻断，LLM 不确定）
        return (
            True,
            f"[semantic/{category}] LLM detected drift (confidence={confidence:.0%}): {llm_reason}",
            category,
            "escalate",
        )
    elif confidence >= 0.5:
        # 中置信度 → 警告记录
        return (
            False,
            f"[semantic/warn/{category}] Low-confidence drift signal: {llm_reason}",
            category,
            "warn",
        )

    return False, None, None, "allow"




# ═══════════════════════════════════════════════════════════════════════
# 主线 B  Session Lineage 追踪
# ═══════════════════════════════════════════════════════════════════════
# ChatGPT 报告: sub-agent spawn链条、session/thread继承还没有结构化追踪
# 现在为 SessionState 增加 lineage 能力

@dataclass
class AgentLineageNode:
    """委托链里的单个节点——记录谁生成了谁、带了什么任务。"""
    agent_id:        str
    parent_agent_id: Optional[str]
    spawned_at:      float
    task_description:Optional[str]
    action_scope:    List[str]
    depth:           int            # 从 session origin 算起的深度


class SessionLineage:
    """
    追踪一个 OpenClaw session 里的完整 agent 生成树。

    这解决了 ChatGPT 指出的问题：
    "Y* 目前只能看到局部动作，看不到 sub-agent spawn 链条。"
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.nodes: Dict[str, AgentLineageNode] = {}
        self.root_agent: Optional[str] = None

    def register_spawn(
        self,
        agent_id:         str,
        parent_agent_id:  Optional[str],
        task_description: Optional[str] = None,
        action_scope:     Optional[List[str]] = None,
    ) -> AgentLineageNode:
        """记录一次 agent 生成事件。"""
        parent_depth = 0
        if parent_agent_id and parent_agent_id in self.nodes:
            parent_depth = self.nodes[parent_agent_id].depth

        node = AgentLineageNode(
            agent_id         = agent_id,
            parent_agent_id  = parent_agent_id,
            spawned_at       = time.time(),
            task_description = task_description,
            action_scope     = action_scope or [],
            depth            = parent_depth + 1,
        )
        self.nodes[agent_id] = node

        if parent_agent_id is None:
            self.root_agent = agent_id

        return node

    def get_ancestry(self, agent_id: str) -> List[str]:
        """返回从 root 到 agent_id 的完整祖先链。"""
        path = []
        current = agent_id
        while current:
            path.append(current)
            node = self.nodes.get(current)
            current = node.parent_agent_id if node else None
        return list(reversed(path))

    def get_depth(self, agent_id: str) -> int:
        node = self.nodes.get(agent_id)
        return node.depth if node else 0

    def check_max_depth(self, max_depth: int = 5) -> Optional[str]:
        """检查是否有 agent 超过最大嵌套深度（防止无限 spawn）。"""
        for agent_id, node in self.nodes.items():
            if node.depth > max_depth:
                return (
                    f"Agent '{agent_id}' at depth {node.depth} "
                    f"exceeds max_depth={max_depth}"
                )
        return None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "root_agent": self.root_agent,
            "nodes": {
                aid: {
                    "parent":      n.parent_agent_id,
                    "depth":       n.depth,
                    "task":        n.task_description,
                    "scope":       n.action_scope,
                    "spawned_at":  n.spawned_at,
                }
                for aid, n in self.nodes.items()
            },
        }


# ═══════════════════════════════════════════════════════════════════════
# P1: CIEU Replay  —  違反記録の再生・分析
# ═══════════════════════════════════════════════════════════════════════

def replay_cieu(
    records: Optional[List["OpenClawCIEU"]] = None,
    filter_decision: Optional[str] = None,
) -> dict:
    """
    CIEU 記録を再生して分析サマリーを返す。

    ChatGPT 評価「CIEU が溜まっても分析できない」への回答。

    Args:
        records: 分析対象。None のとき session log 全体を使用。
        filter_decision: "deny" | "escalate" | "allow" でフィルタ。

    Returns:
        {
          "total": int,
          "by_decision": {"allow": N, "deny": N, "escalate": N},
          "by_event_type": {"file_write": N, ...},
          "by_agent": {"coder_agent": N, ...},
          "violations": [{"dimension": str, "count": int, "examples": [str]}],
          "drift_events": [{"agent": str, "detail": str}],
          "timeline": [{"seq": int, "agent": str, "decision": str, "event": str}],
        }
    """
    from collections import Counter, defaultdict

    source = records if records is not None else get_cieu_log()
    if filter_decision:
        source = [r for r in source if r.decision.value == filter_decision.lower()]

    by_decision: Counter = Counter()
    by_event:    Counter = Counter()
    by_agent:    Counter = Counter()
    viol_dim:    Counter = Counter()
    viol_msgs:   dict    = defaultdict(list)
    drift_events: List[dict] = []
    timeline:     List[dict] = []

    for i, rec in enumerate(source):
        by_decision[rec.decision.value] += 1
        by_event[rec.event.event_type.value] += 1
        by_agent[rec.event.agent_id] += 1

        for v in rec.call_record.violations:
            if v.dimension != "phantom_variable":
                viol_dim[v.dimension] += 1
                viol_msgs[v.dimension].append(v.message[:60])

        if rec.drift_detected:
            drift_events.append({
                "agent":  rec.event.agent_id,
                "detail": (rec.drift_details or "")[:80],
            })

        timeline.append({
            "seq":      i + 1,
            "agent":    rec.event.agent_id,
            "decision": rec.decision.value,
            "event":    rec.event.event_type.value,
            "file":     rec.event.file_path or rec.event.command or rec.event.url or "",
        })

    violations_summary = [
        {
            "dimension": dim,
            "count":     count,
            "examples":  viol_msgs[dim][:3],
        }
        for dim, count in viol_dim.most_common(10)
    ]

    return {
        "total":       len(source),
        "by_decision": dict(by_decision),
        "by_event_type": dict(by_event),
        "by_agent":    dict(by_agent),
        "violations":  violations_summary,
        "drift_events": drift_events,
        "timeline":    timeline,
    }


def persist_cieu_log(
    path: str = ".ystar_cieu.jsonl",
    deduplicate: bool = True,
) -> int:
    """
    現在のセッション CIEU ログをファイルに永続化する。

    v0.28.0: event_id による重複排除 + seq_global による順序保証。
    concurrent append は OS レベルの append-only で安全（POSIX保証）。

    Returns: 書き込んだレコード数。
    """
    import json
    from pathlib import Path

    log = get_cieu_log()
    if not log:
        return 0

    # 重複排除：既存ファイルの event_id を読み込む
    existing_ids: set = set()
    if deduplicate and Path(path).exists():
        try:
            with open(path) as f:
                for line in f:
                    try:
                        existing_ids.add(json.loads(line).get("event_id",""))
                    except Exception:
                        pass
        except Exception:
            pass

    written = 0
    with open(path, "a") as f:
        for rec in log:
            if deduplicate and rec.event_id in existing_ids:
                continue  # 重複スキップ
            entry = rec.to_dict()
            # to_dict()にないフィールドを補完
            if "file_path" not in entry:
                entry["file"] = rec.event.file_path or rec.event.command or ""
            f.write(json.dumps(entry, default=str) + "\n")
            written += 1
    return written


# ═══════════════════════════════════════════════════════════════════════
# P1: Richer Goal Drift  —  より深い目標偷換の検出
# ═══════════════════════════════════════════════════════════════════════

# 既存の GOAL_DRIFT_SIGNALS を拡張
_EXTENDED_DRIFT_SIGNALS = {
    # 范围扩大类
    "scope_expansion": [
        "refactor entire", "redesign", "rewrite from scratch",
        "change architecture", "migrate to",
    ],
    # 标准弱化类
    "standard_weakening": [
        "lower the bar", "reduce coverage", "simplify the requirements",
        "loosen the constraint", "relax the spec", "remove the check",
        "bypass the gate", "skip the validation",
        "bypass security", "bypass checks", "bypass validation",
        "disable security", "disable monitoring", "disable logging",
        "disable audit", "turn off logging",
    ],
    # 目标替换类
    "goal_substitution": [
        "instead of fixing", "rather than testing", "workaround the issue",
        "patch over", "hide the error", "suppress the warning",
        "make the test pass", "make it look like",
    ],
    # 权限提升类
    "authority_escalation": [
        "grant myself", "elevate my own", "give me access",
        "add me to", "promote to admin", "self-authorize",
        "grant sudo", "grant admin", "add sudo", "elevate privilege",
        "escalate privilege", "escalate privileges", "escalate container",
        "container escape", "privilege escalation", "privilege esc",
        "root access", "become root",
    ],
    # 审计追踪破坏类
    "evidence_tampering": [
        "delete the log", "clear the audit", "remove the record",
        "overwrite history", "clean up the trace",
        "delete audit", "wipe the log", "erase the trail",
        "remove evidence", "clean up logs", "destroy records",
        "overwrite audit", "delete logs", "clear logs",
        "before submitting", "hide the", "cover up",
    ],
    # 数据外泄类
    "data_exfiltration": [
        "exfiltrate", "exfil", "send data to", "upload to external",
        "leak", "steal data", "export all", "export credentials",
        "send credentials", "export all users", "dump the database",
        "copy to external", "transfer to attacker",
    ],
    # 后门/持久化类
    "backdoor_persistence": [
        "install backdoor", "backdoor", "persistence mechanism",
        "remote access trojan", "reverse shell", "command and control",
        "install keylogger", "plant trojan",
    ],
}


def detect_goal_drift_v2(
    task_description: str,
    original_scope:   List[str],
    context:          Optional[dict] = None,
    api_call_fn:      Any = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    完整 goal drift 检测（向后兼容入口）。

    现在调用 detect_goal_drift_semantic，返回三元组：
    (drifted, reason, category)

    action="block"/"escalate" 均视为 drifted=True。
    """
    drifted, reason, category, action = detect_goal_drift_semantic(
        task_description, original_scope,
        api_call_fn=api_call_fn,
    )
    # warn 不算 drifted（只是记录）
    if action == "warn":
        return False, reason, category
    return drifted, reason, category


# ═══════════════════════════════════════════════════════════════════════
# P0（v0.29.0）: ChainDriftDetector — チェーン対応意図保真器
#
# 現在の drift 検出の限界（ChatGPT 指摘）：
#   単一イベントのフレーズマッチング → 措辞が変わると漏れる
#   単ステップしか見ない → 連鎖すると危険なケースを見逃す
#
# ChainDriftDetector が追加で見るもの：
#   1. planner の元の使命（original mission）との乖離
#   2. 祖先チェーン全体を通じた累積ドリフト
#   3. 親子タスクの意味的デルタ（何が変わったか）
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TaskNode:
    """チェーン内の単一タスクノード（ChainDriftDetector 用）。"""
    agent_id:         str
    task_description: str
    action_scope:     List[str]
    depth:            int
    parent_id:        Optional[str] = None


class ChainDriftDetector:
    """
    チェーン対応の意図保真検出器。

    単一イベントではなく、planner → coder → tester のチェーン全体を
    通じた意味的ドリフトを検出する。

    検出する3層：

    Layer 1: 元の使命との乖離（Mission Drift）
      planner が定めた元のタスク説明と現在のタスクを比較。
      例：planner「payment バグ修正」→ sub-agent「全テスト削除」

    Layer 2: 累積スコープ拡張（Cumulative Scope Expansion）
      各ホップで少しずつ広がる場合も検出。
      1ホップ: "./src/payments" → "./src" （微小な拡張）
      2ホップ: "./src" → "./"          （さらに拡張）
      合計:    "./src/payments" → "./"   （重大な拡張）

    Layer 3: 禁止キーワードの組み合わせ（Compound Signal）
      単体では無害なキーワードが組み合わさると危険な場合。
      例："fix" + "before review" + "production" の組み合わせ
    """

    # 元の使命を破壊する可能性があるシグナル（measure vs original）
    _MISSION_VIOLATION_SIGNALS = [
        # 原始规则 (14 条)
        ("delete", "test"),
        ("remove", "test"),
        ("skip", "test"),
        ("bypass", "test"),
        ("push", "production"),
        ("deploy", "without review"),
        ("modify", "production"),
        ("delete", "log"),
        ("clear", "audit"),
        ("hide", "error"),
        ("suppress", "warning"),
        ("grant", "admin"),
        ("elevate", "privilege"),
        ("self", "authorize"),
        # MITRE ATLAS v4.5 预训练扩充 (243 条，2026-03)
        ("evade", "malware"),
        ("evade", "test"),
        ("evade", "production"),
        ("bypass", "production"),
        ("deploy", "test"),
        ("deploy", "production"),
        ("poison", "file"),
        ("bypass", "malware"),
        ("bypass", "file"),
        ("evade", "file"),
        ("evade", "shell"),
        ("evade", "privilege"),
        ("send", "privilege"),
        ("deploy", "credential"),
        ("deploy", "token"),
        ("deploy", "password"),
        ("deploy", "key"),
        ("deploy", "audit"),
        ("deploy", "privilege"),
        ("clear", "credential"),
        ("clear", "token"),
        ("clear", "password"),
        ("clear", "key"),
        ("clear", "privilege"),
        ("clear", "production"),
        ("bypass", "email"),
        ("evade", "email"),
        ("inject", "backdoor"),
        ("inject", "payload"),
        ("backdoor", "backdoor"),
        ("backdoor", "payload"),
        ("deploy", "backdoor"),
        ("deploy", "payload"),
        ("extract", "key"),
        ("bypass", "backdoor"),
        ("bypass", "payload"),
        ("bypass", "log"),
        ("inject", "log"),
        ("backdoor", "log"),
        ("poison", "payload"),
        ("deploy", "malware"),
        ("deploy", "file"),
        ("clear", "malware"),
        ("clear", "review"),
        ("extract", "malware"),
        ("extract", "file"),
        ("send", "malware"),
        ("send", "file"),
        ("extract", "payload"),
        ("steal", "log"),
        ("steal", "file"),
        ("inject", "key"),
        ("inject", "test"),
        ("exfil", "file"),
        ("delete", "permission"),
        ("delete", "review"),
        ("delete", "file"),
        ("grant", "permission"),
        ("grant", "review"),
        ("grant", "file"),
        ("exfiltrate", "file"),
        ("install", "file"),
        ("exfiltrate", "permission"),
        ("exfil", "permission"),
        ("inject", "permission"),
        ("exfiltrate", "secret"),
        ("exfiltrate", "log"),
        ("exfil", "secret"),
        ("exfil", "log"),
        ("inject", "secret"),
        ("steal", "production"),
        ("exploit", "production"),
        ("exfiltrate", "credential"),
        ("exfiltrate", "shell"),
        ("exfil", "credential"),
        ("exfil", "shell"),
        ("persist", "credential"),
        ("persist", "shell"),
        ("leak", "email"),
        ("inject", "email"),
        ("send", "email"),
        ("inject", "file"),
        ("send", "payload"),
        ("send", "log"),
        ("exploit", "payload"),
        ("exploit", "email"),
        ("poison", "malware"),
        ("deploy", "permission"),
        ("corrupt", "shell"),
        ("corrupt", "malware"),
        ("corrupt", "payload"),
        ("corrupt", "file"),
        ("grant", "shell"),
        ("grant", "malware"),
        ("grant", "payload"),
        ("remove", "shell"),
        ("remove", "malware"),
        ("remove", "payload"),
        ("remove", "file"),
        ("move", "shell"),
        ("move", "malware"),
        ("move", "payload"),
        ("move", "file"),
        ("evade", "payload"),
        ("evade", "credential"),
        ("evade", "log"),
        ("steal", "credential"),
        ("inject", "privilege"),
        ("bypass", "key"),
        ("exfiltrate", "key"),
        ("exfiltrate", "payload"),
        ("exfil", "key"),
        ("exfil", "payload"),
        ("extract", "token"),
        ("bypass", "token"),
        ("inject", "token"),
        ("poison", "token"),
        ("persist", "token"),
        ("send", "token"),
        ("exfiltrate", "email"),
        ("exfil", "email"),
        ("exfil", "privilege"),
        ("exploit", "privilege"),
        ("grant", "privilege"),
        ("poison", "log"),
        ("persist", "payload"),
        ("persist", "log"),
        ("poison", "backdoor"),
        ("backdoor", "file"),
        ("evade", "review"),
        ("exfil", "backdoor"),
        ("exfil", "production"),
        ("backdoor", "production"),
        ("exfiltrate", "backdoor"),
        ("exfiltrate", "malware"),
        ("exfil", "malware"),
        ("backdoor", "shell"),
        ("backdoor", "malware"),
        ("exfiltrate", "test"),
        ("exfil", "test"),
        ("inject", "malware"),
        ("install", "malware"),
        ("install", "email"),
        ("inject", "credential"),
        ("inject", "shell"),
        ("poison", "shell"),
        ("clear", "shell"),
        ("delete", "shell"),
        ("delete", "root"),
        ("bypass", "shell"),
        ("bypass", "root"),
        ("inject", "root"),
        ("delete", "token"),
        ("delete", "c2"),
        ("deploy", "c2"),
        ("deploy", "log"),
        ("clear", "c2"),
        ("clear", "log"),
        ("clear", "file"),
        ("inject", "c2"),
        ("exfil", "token"),
        ("exfil", "root"),
        ("bypass", "credential"),
        ("send", "credential"),
        ("send", "key"),
        ("send", "root"),
        ("exfiltrate", "token"),
        ("poison", "review"),
        ("steal", "backdoor"),
        ("steal", "malware"),
        ("steal", "payload"),
        ("backdoor", "credential"),
        ("install", "credential"),
        ("install", "backdoor"),
        ("install", "payload"),
        ("steal", "token"),
        ("steal", "key"),
        ("steal", "shell"),
        ("disable", "token"),
        ("disable", "key"),
        ("disable", "shell"),
        ("disable", "log"),
        ("disable", "payload"),
        ("install", "permission"),
        ("install", "test"),
        ("persist", "file"),
        ("deploy", "email"),
        ("steal", "email"),
        ("backdoor", "email"),
        ("poison", "key"),
        ("grant", "credential"),
        ("grant", "password"),
        ("grant", "key"),
        ("grant", "production"),
        ("persist", "malware"),
        ("install", "admin"),
        ("install", "shell"),
        ("install", "c2"),
        ("install", "log"),
        ("bypass", "privilege"),
        ("persist", "privilege"),
        ("exploit", "malware"),
        ("exploit", "log"),
        ("exploit", "test"),
        ("remove", "log"),
        ("move", "log"),
        ("move", "test"),
        ("poison", "email"),
        ("exploit", "key"),
        ("delete", "key"),
        ("persist", "key"),
        ("disable", "file"),
        ("extract", "credential"),
        ("extract", "secret"),
        ("deploy", "secret"),
        ("exploit", "credential"),
        ("send", "test"),
        ("leak", "credential"),
        ("extract", "shell"),
        ("extract", "admin"),
        ("lateral", "credential"),
        ("lateral", "token"),
        ("lateral", "shell"),
        ("lateral", "admin"),
        ("move", "credential"),
        ("move", "token"),
        ("move", "admin"),
        ("extract", "password"),
        ("lateral", "password"),
        ("lateral", "key"),
        ("move", "password"),
        ("move", "key"),
        ("bypass", "password"),
        ("persist", "email"),
        ("evade", "key"),
        ("steal", "c2"),
        ("persist", "backdoor"),
        ("persist", "c2"),
        ("backdoor", "c2"),
        ("destroy", "file"),
        ("disable", "permission"),
        ("exploit", "file"),
        ("grant", "c2"),
        # 真实事件补充 (5 条，2025-2026)
        ("delete", "email"),
        ("purchase", "item"),
        ("bypass", "review"),
        ("send", "secret"),
        ("delete", "production"),
        # Who&When ICML 2025 多智能体失败日志提炼（88对，2025）
        # MAST FM06/FM10 验证遗漏模式补充（2025）
        ("skip", "verification"),
        ("skip", "validation"),
        ("skip", "check"),
        ("skip", "confirmation"),
        ("miss", "verification"),
        ("miss", "validation"),
        ("omit", "verification"),
        ("fail", "verification"),
        ("fail", "validation"),
        ("incorrect", "verification"),
        ("wrong", "verification"),
        ("incorrect", "result"),
        ("fail", "format"),
        ("fail", "result"),
        ("fail", "step"),
        ("incorrect", "format"),
        ("incorrect", "result"),
        ("incorrect", "step"),
        ("fail", "format"),
        ("fail", "result"),
        ("fail", "step"),
        ("incorrect", "format"),
        ("incorrect", "result"),
        ("incorrect", "step"),
        ("fail", "verification"),
        ("fail", "format"),
        ("incorrect", "format"),
        ("incorrect", "verification"),
        ("incorrect", "result"),
        ("fail", "verification"),
        ("fail", "result"),
        ("miss", "result"),
        ("incorrect", "output"),
        ("incorrect", "format"),
        ("incorrect", "result"),
        ("fail", "format"),
        ("fail", "result"),
        ("fail", "step"),
        ("incorrect", "format"),
        ("incorrect", "result"),
        ("incorrect", "step"),
        ("incorrect", "format"),
        ("incorrect", "step"),
        ("incorrect", "step"),
        ("fail", "result"),
        ("fail", "verification"),
        ("fail", "result"),
        ("incorrect", "answer"),
        ("incorrect", "output"),
        ("incorrect", "format"),
        ("incorrect", "answer"),
        ("incorrect", "output"),
        ("incorrect", "step"),
        ("incorrect", "verification"),
        ("incorrect", "answer"),
        ("incorrect", "result"),
        ("wrong", "result"),
        ("incorrect", "result"),
        ("incorrect", "verification"),
        ("incorrect", "answer"),
        ("fail", "format"),
        ("incorrect", "format"),
        ("incorrect", "format"),
        ("incorrect", "format"),
        ("incorrect", "format"),
        ("fail", "format"),
        ("fail", "result"),
        ("wrong", "answer"),
        ("incorrect", "answer"),
        ("miss", "result"),
        ("incorrect", "result"),
        ("incorrect", "result"),
        ("incorrect", "result"),
        ("fail", "check"),
        ("fail", "result"),
        ("wrong", "format"),
        ("wrong", "answer"),
        ("wrong", "result"),
        ("wrong", "result"),
        ("fail", "format"),
        ("fail", "format"),
        ("fail", "answer"),
        ("fail", "step"),
        ("wrong", "format"),
        ("wrong", "answer"),
        ("wrong", "step"),
        ("incorrect", "format"),
        ("incorrect", "answer"),
        ("incorrect", "step"),
        ("fail", "result"),
        ("fail", "step"),
        ("wrong", "result"),
        ("wrong", "step"),
        ("fail", "step"),
        ("incorrect", "format"),
        ("fail", "format"),
        ("miss", "check"),
        ("miss", "format"),
        ("miss", "result"),

    ]

    # 累積しきい値（ホップ数 × 拡張スコア）
    _CUMULATIVE_DRIFT_THRESHOLD = 2.5  # v0.29.1: 2→2.5（正常拡張の誤検出を減らす）

    # ミッション関連の正当なスコープ拡張（これらはドリフトではない）
    _LEGITIMATE_SCOPE_ADDITIONS = {
        "./tests", "./test", "./tests/", "./test/",   # テスト追加は常に正当
        "./docs", "./docs/", "./documentation/",       # ドキュメント更新は正当
        "./scripts",                                   # ビルドスクリプトは正当
    }

    def __init__(self, lineage: Optional[SessionLineage] = None, mission_statement: Optional[str] = None):
        self._chain: List[TaskNode] = []
        self._lineage = lineage
        self._mission_statement = mission_statement

    def register_task(
        self,
        agent_id:         str,
        task_description: str,
        action_scope:     List[str],
        parent_id:        Optional[str] = None,
        depth:            int = 0,
    ) -> None:
        """新タスクをチェーンに登録。"""
        self._chain.append(TaskNode(
            agent_id         = agent_id,
            task_description = task_description,
            action_scope     = action_scope,
            depth            = depth,
            parent_id        = parent_id,
        ))

    def detect(
        self,
        current_task:   str,
        current_scope:  List[str],
        agent_id:       str,
        parent_id:      Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        チェーン全体を考慮してドリフトを検出する。

        Returns: (drifted, reason, category)
        """
        if not current_task:
            return False, None, None

        task_lower = current_task.lower()

        # Layer 1: 元の使命との比較
        root = self._get_root_task()
        if root and root.task_description:
            mission_drift = self._check_mission_violation(
                current_task, root.task_description
            )
            if mission_drift:
                return True, mission_drift, "mission_violation"

        # Layer 2: 累積スコープ拡張
        if parent_id:
            parent = self._find_node(parent_id)
            if parent:
                cumulative_score = self._score_scope_expansion(
                    parent.action_scope, current_scope
                )
                # チェーン全体の累積スコアも加算
                chain_score = self._total_chain_expansion_score()
                total = cumulative_score + chain_score
                if total >= self._CUMULATIVE_DRIFT_THRESHOLD:
                    return (
                        True,
                        f"Cumulative scope expansion detected "
                        f"(score={total:.1f}): "
                        f"{parent.action_scope} → {current_scope}",
                        "cumulative_scope_expansion",
                    )

        # Layer 3: 禁止キーワードの組み合わせ（complex patterns）
        compound = self._check_compound_signals(task_lower)
        if compound:
            return True, compound, "compound_signal"

        # Layer 4: 单词级高危信号（来自 _EXTENDED_DRIFT_SIGNALS）
        for category, signals in _EXTENDED_DRIFT_SIGNALS.items():
            for signal in signals:
                if signal in task_lower:
                    return (
                        True,
                        f"[{category}] High-risk signal '{signal}' in task description",
                        category,
                    )

        return False, None, None

    def _get_root_task(self) -> Optional[TaskNode]:
        if not self._chain:
            return None
        # depth=0 または最初のノード
        for node in self._chain:
            if node.depth == 0 or node.parent_id is None:
                return node
        return self._chain[0]

    def _find_node(self, agent_id: str) -> Optional[TaskNode]:
        for node in reversed(self._chain):
            if node.agent_id == agent_id:
                return node
        return None

    def _check_mission_violation(
        self, current_task: str, original_mission: str
    ) -> Optional[str]:
        """元の使命と現在のタスクが矛盾するか確認。"""
        current_lower  = current_task.lower()
        original_lower = original_mission.lower()

        for sig_a, sig_b in self._MISSION_VIOLATION_SIGNALS:
            if sig_a in current_lower and sig_b in current_lower:
                # 元の使命にもこのパターンがあれば OK（同じ意図）
                if sig_a in original_lower and sig_b in original_lower:
                    continue
                return (
                    f"Task violates original mission: "
                    f"'{sig_a}' + '{sig_b}' found in "
                    f"'{current_task[:60]}' "
                    f"but original mission was: '{original_mission[:60]}'"
                )
        return None

    def _score_scope_expansion(
        self, parent_scope: List[str], child_scope: List[str]
    ) -> float:
        """スコープ拡張のスコアを算出（0=変化なし、高い=危険）。"""
        if not parent_scope or not child_scope:
            return 0.0

        # 子スコープが親スコープより広い場合にスコアを付与
        # 豁免リストにあるパスは拡張スコアを加算しない（正当な拡張）
        child_scope_filtered = [
            cs for cs in child_scope
            if not any(
                cs.rstrip("/") == leg.rstrip("/")
                for leg in self._LEGITIMATE_SCOPE_ADDITIONS
            )
        ]
        if not child_scope_filtered:
            return 0.0
        child_scope = child_scope_filtered

        score = 0.0
        for cs in child_scope:
            is_within_any_parent = any(
                cs == ps or cs.startswith(ps.rstrip("/") + "/")
                for ps in parent_scope
            )
            if not is_within_any_parent:
                # 完全に外側にある場合は高スコア
                score += 1.5
            for ps in parent_scope:
                if ps.startswith(cs.rstrip("/") + "/"):
                    # 子が親より広い（例：./src > ./src/payments）
                    score += 0.8
        return score

    def _total_chain_expansion_score(self) -> float:
        """チェーン全体の累積拡張スコア。"""
        if len(self._chain) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(self._chain)):
            total += self._score_scope_expansion(
                self._chain[i-1].action_scope,
                self._chain[i].action_scope,
            )
        return total

    def _check_compound_signals(self, task_lower: str) -> Optional[str]:
        """危険なキーワードの組み合わせを検出。"""
        compound_patterns = [
            # "操作" + "レビューなし" + "本番"
            (["fix", "patch", "push", "handle", "deploy", "apply"],
             ["without review", "skip review", "no review", "before review",
              "without going through", "bypass review", "directly to"],
             ["production", "prod", "live", "live environment"]),
            # "変更" + "テストなし" + "本番"
            (["modify", "change", "update", "edit", "fix"],
             ["no test", "skip test", "without test", "untested"],
             ["production", "prod", "deploy", "release"]),
            # "削除/クリア" + "ログ/監査"
            (["delete", "remove", "clear", "wipe", "clean up", "erase"],
             ["log", "audit", "trace", "record", "evidence", "trail"],
             []),  # これらの組み合わせは単独でも危険
        ]
        # group_c が空の場合は a + b の組み合わせだけで判定
        extended_patterns = compound_patterns
        for group_a, group_b, group_c in extended_patterns:
            has_a = any(s in task_lower for s in group_a)
            has_b = any(s in task_lower for s in group_b)
            has_c = not group_c or any(s in task_lower for s in group_c)
            if has_a and has_b and has_c:
                matched_b = [s for s in group_b if s in task_lower][:1]
                matched_c = [s for s in group_c if s in task_lower][:1] if group_c else []
                context   = matched_b + matched_c
                return (
                    f"Compound risk signal: "
                    f"dangerous keyword combination detected "
                    f"({context})"
                )
        return None

    def analyze(self, chain_events: list) -> dict:
        """
        F3 链级 drift 批量分析接口（供 GovernanceLoop.detect_chain_drift() 调用）。

        Args:
            chain_events: list of dicts with keys:
                agent_id (str), action (str),
                scope (list, optional), parent_id (str, optional)

        Returns:
            dict: drift_detected, drift_type, severity, details
        """
        self._chain = []  # reset for fresh analysis

        for i, ev in enumerate(chain_events):
            self.register_task(
                agent_id         = ev.get("agent_id", f"agent_{i}"),
                task_description = ev.get("action", ""),
                action_scope     = ev.get("scope", []),
                parent_id        = ev.get("parent_id"),
                depth            = i,
            )

        if not self._chain:
            return {"drift_detected": False}

        # Run detection on the last task in the chain
        last = self._chain[-1]
        drifted, reason, category = self.detect(
            current_task  = last.task_description,
            current_scope = last.action_scope,
            agent_id      = last.agent_id,
            parent_id     = last.parent_id,
        )

        return {
            "drift_detected": drifted,
            "drift_type":     category,
            "severity":       "high" if drifted else "none",
            "details": {
                "reason":     reason,
                "chain_depth": len(self._chain),
                "last_agent":  last.agent_id,
            },
        }


# セッションごとの ChainDriftDetector を管理
_chain_detectors: Dict[str, ChainDriftDetector] = {}

def get_chain_detector(session_id: str) -> ChainDriftDetector:
    if session_id not in _chain_detectors:
        _chain_detectors[session_id] = ChainDriftDetector()
    return _chain_detectors[session_id]

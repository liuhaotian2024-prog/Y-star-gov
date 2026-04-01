# Layer: Foundation
"""
ystar.adapters.hook  —  OpenClaw hook 纯翻译层  v0.41.0
=========================================================

适配层的唯一职责：格式翻译。
  输入：OpenClaw PreToolUse hook payload（dict）
  输出：{"action": "block"|"", "message": "..."}

执行深度自动升级：
  有 .ystar_session.json → 走 enforce()（完整治理路径）
                             委托链验证 + 漂移检测 + CIEU 五元组
  无 .ystar_session.json → 走 Policy.check()（轻量路径）+ 基础 CIEU

用户接口零变化，行为根据上下文自动选择深度。

三个判断问题验证这个文件属于适配层：
  Q1: 给 LangChain 用要改吗？     → 要改（OpenClaw 专属格式）✓ 适配层
  Q2: 需要记住上一次发生了什么？  → 不需要 ✓ 适配层
  Q3: 翻译格式还是判断对错？      → 翻译格式 ✓ 适配层

治理逻辑（Omission/Lineage/Drift/Gate）在 domains/openclaw/adapter.py。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import logging
import sys

from ystar.session import Policy, PolicyResult

_log = logging.getLogger("ystar.hook")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*hook] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.WARNING)


# ── 角色写路径边界（来自 AGENTS.md "Write Access" 节）─────────────────────
# only_paths 不能用于此目的（它会同时限制读操作）
# 所以写路径检查在 hook 层单独执行，仅对 Write/Edit/MultiEdit 生效
# 路径用 / 格式，检查时做 normpath

_AGENT_WRITE_PATHS: Dict[str, list] = {
    "ystar-ceo": ["./reports/"],
    "ystar-cto": [
        "./src/", "./tests/", "./products/ystar-gov/", "./products/",
        "./docs/", ".github/", "CHANGELOG.md",
        # CTO 也有 Y*gov 源码仓库的写权限
        "C:/Users/liuha/OneDrive/桌面/Y-star-gov/",
    ],
    "ystar-cmo": ["./content/", "./marketing/"],
    "ystar-cso": ["./sales/"],
    "ystar-cfo": ["./finance/", "./reports/"],
}

# 写操作工具名
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}


# ── Agent 身份检测 ──────────────────────────────────────────────────────────

def _detect_agent_id(hook_payload: Dict[str, Any]) -> str:
    """
    从多个来源检测当前操作的 agent 身份。

    优先级：
    1. hook_payload 里的 agent_id 字段
    2. 环境变量 YSTAR_AGENT_ID
    3. 环境变量 CLAUDE_AGENT_NAME（Claude Code 可能设置）
    4. .ystar_active_agent 文件（agent 在 session start 时写入）
    5. 回退到 "agent"
    """
    # 1. payload
    aid = hook_payload.get("agent_id", "")
    if aid and aid != "agent":
        return aid

    # 2. env: YSTAR_AGENT_ID
    aid = os.environ.get("YSTAR_AGENT_ID", "")
    if aid:
        return aid

    # 3. env: CLAUDE_AGENT_NAME
    aid = os.environ.get("CLAUDE_AGENT_NAME", "")
    if aid:
        return aid

    # 4. marker file
    marker = Path(".ystar_active_agent")
    if marker.exists():
        try:
            content = marker.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception:
            pass

    return "agent"


def _check_write_boundary(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """
    对 Write/Edit/MultiEdit 工具强制执行角色写路径边界。

    如果 who 有定义写路径限制且文件不在允许范围内，返回 deny PolicyResult。
    否则返回 None（放行）。
    """
    if tool_name not in _WRITE_TOOLS:
        return None

    allowed = _AGENT_WRITE_PATHS.get(who)
    if not allowed:
        return None   # 未定义边界的 agent 不受限

    file_path = params.get("file_path", "")
    if not file_path:
        return None

    # 归一化路径（处理 Windows 反斜杠）
    norm_target = os.path.normpath(os.path.abspath(file_path))

    for ap in allowed:
        norm_allowed = os.path.normpath(os.path.abspath(ap))
        if norm_target == norm_allowed or norm_target.startswith(norm_allowed + os.sep):
            return None   # 在允许范围内

    return PolicyResult(
        allowed=False,
        reason=(
            f"Write boundary violation: agent '{who}' cannot write to '{file_path}'. "
            f"Allowed write paths: {allowed}"
        ),
        who=who,
        what=tool_name,
        violations=[],
    )


# ── 工具名 → Y* 参数字段的映射 ────────────────────────────────────────────

_TOOL_PARAMS: Dict[str, str] = {
    # tool_name prefix  → 主要参数字段
    "Write":            "file_path",
    "Edit":             "file_path",
    "MultiEdit":        "file_path",
    "Read":             "file_path",
    "Glob":             "file_path",
    "Grep":             "file_path",
    "LS":               "file_path",
    "Bash":             "command",
    "WebFetch":         "url",
    "WebSearch":        "url",
    "Task":             "command",
    "TodoWrite":        "file_path",
    "NotebookEdit":     "file_path",
}


def _extract_params(tool_name: str, tool_input: dict) -> dict:
    """
    把 OpenClaw tool_input 翻译成 Y* check() 能理解的 params dict。

    规则：
    - 根据 tool_name 找主要字段（file_path / command / url）
    - tool_input 里的路径/URL/命令类参数自动提升到顶层
    - 其余字段原样透传（让 invariant / value_range 能访问）
    """
    params: Dict[str, Any] = {
        "action":    tool_name,
        "tool_name": tool_name,
    }

    # 主要字段：根据工具类型映射
    primary_field = None
    for prefix, field in _TOOL_PARAMS.items():
        if tool_name.startswith(prefix):
            primary_field = field
            break

    if primary_field == "file_path":
        params["file_path"] = (
            tool_input.get("path") or
            tool_input.get("file_path") or
            tool_input.get("pattern") or
            tool_input.get("directory") or ""
        )
    elif primary_field == "command":
        params["command"] = (
            tool_input.get("command") or
            tool_input.get("cmd") or
            tool_input.get("description") or ""
        )
    elif primary_field == "url":
        params["url"] = (
            tool_input.get("url") or
            tool_input.get("query") or ""
        )

    # MCP 工具：mcp__ 前缀
    if tool_name.startswith("mcp__"):
        _PATH_KEYS = {"path", "file", "filepath", "file_path",
                      "dest", "src", "source", "target"}
        _URL_KEYS  = {"url", "endpoint", "uri", "href"}
        for k, v in tool_input.items():
            if k.lower() in _PATH_KEYS and v:
                params.setdefault("file_path", str(v))
            if k.lower() in _URL_KEYS and v:
                params["url"] = str(v)

    # 透传其余字段（amount / risk_approved / 等业务参数）
    for k, v in tool_input.items():
        params.setdefault(k, v)

    return params


def _result_to_response(result: PolicyResult) -> Dict[str, Any]:
    """
    把 Y* PolicyResult 翻译成 OpenClaw hook 响应格式。

    OpenClaw 期望：
      允许 → {} 或 {"action": null}
      拒绝 → {"action": "block", "message": "..."}
    """
    if result.allowed:
        return {}

    # 取第一条违规消息作为拒绝原因
    msg = result.reason or "Blocked by Y* policy"
    return {
        "action":  "block",
        "message": f"[Y*] {msg}",
        "violations": [
            {"dimension": v.dimension, "message": v.message}
            for v in result.violations
        ],
    }


# ── 主入口：纯翻译函数 ────────────────────────────────────────────────────

def _load_session_config(search_dirs: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """
    查找并加载 .ystar_session.json。
    ystar init 完成后写入此文件，check_hook 启动时自动读取。
    """
    dirs = search_dirs or [os.getcwd(), str(Path.home())]
    for d in dirs:
        p = Path(d) / ".ystar_session.json"
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def _write_cieu(
    who: str, tool_name: str, params: dict,
    result: PolicyResult, session_id: str,
    contract_hash: str, cieu_db: str,
) -> None:
    """把 check 结果写入 CIEU 数据库（静默失败，不影响执行路径）。"""
    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(cieu_db)
        store.write_dict({
            "session_id":    session_id,
            "agent_id":      who,
            "event_type":    tool_name,
            "decision":      "allow" if result.allowed else "deny",
            "passed":        result.allowed,
            "violations":    [{"dimension": v.dimension, "message": v.message}
                              for v in (result.violations or [])],
            "params":        params,
            "contract_hash": contract_hash,
        })
    except Exception:
        pass   # CIEU 写入失败不影响 hook 的阻断/放行决策


def check_hook(
    hook_payload: Dict[str, Any],
    policy: Policy,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    处理一个 OpenClaw PreToolUse hook，返回 hook 响应。

    执行深度根据上下文自动选择，用户无需配置：

    有 .ystar_session.json（ystar init 已运行）：
      → enforce()：委托链验证 + 漂移检测 + CIEU 五元组 + Omission 注入
    无 .ystar_session.json：
      → Policy.check()：规则检查 + 基础 CIEU 写入

    Args:
        hook_payload: OpenClaw 发来的原始 hook dict
        policy:       Policy 对象（从 Policy.from_agents_md() 获得）
        agent_id:     覆盖 payload 里的 agent_id（可选）

    Returns:
        {} 表示允许，{"action":"block",...} 表示拒绝
    """
    tool_name  = hook_payload.get("tool_name", "")
    tool_input = hook_payload.get("tool_input", {})

    # ── P0-2: 检测 agent 身份 ──────────────────────────────────────
    who = agent_id or _detect_agent_id(hook_payload)
    session_id_payload = hook_payload.get("session_id", "")

    # 若 agent_id 未在 Policy 里注册，回退到 "agent" fallback
    if who not in policy:
        if "agent" in policy:
            who = "agent"
        else:
            registered = list(policy._rules.keys())
            if registered:
                who = registered[0]

    # ── P0-1: 写路径边界检查（仅 Write/Edit/MultiEdit）──────────────
    params_early = _extract_params(tool_name, tool_input)
    write_deny = _check_write_boundary(who, tool_name, params_early)
    if write_deny is not None:
        # 写入 CIEU 记录（deny）
        cieu_db = ".ystar_cieu.db"
        session_cfg_early = _load_session_config()
        if session_cfg_early:
            cieu_db = session_cfg_early.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, write_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY write boundary: %s → %s (%s)",
                     who, params_early.get("file_path", "?"), write_deny.reason)
        return _result_to_response(write_deny)

    # ── 尝试完整治理路径（有 session 配置时自动升级）────────────────
    session_cfg = _load_session_config()
    if session_cfg:
        try:
            response = _check_hook_full(
                hook_payload, policy, who, tool_name, tool_input,
                session_id_payload or session_cfg.get("session_id", ""),
                session_cfg,
            )
            return response
        except Exception as exc:
            # P0-3: 不再静默降级 — 记录错误以便诊断
            _log.error("Full governance path failed, degrading to light path: %s", exc)

    # ── 轻量路径（无 session 或完整路径失败）────────────────────────
    params   = _extract_params(tool_name, tool_input)
    result   = policy.check(who, tool_name, **params)

    # 即使是轻量路径，也写入基础 CIEU（有 .ystar_cieu.db 时）
    cieu_db = session_cfg.get("cieu_db", ".ystar_cieu.db") if session_cfg else ".ystar_cieu.db"
    contract = policy._rules.get(who)
    contract_hash = contract.hash if contract else ""
    _write_cieu(who, tool_name, params, result,
                session_id_payload or "unknown", contract_hash, cieu_db)

    # ── NEW: Process obligation triggers after check() ──────────────────────
    # If the check passed (ALLOW), check for any triggered obligations
    if result.allowed:
        _process_obligation_triggers(
            tool_name, tool_input, who,
            session_id_payload or "unknown",
            result
        )

    # ── Orchestrator: feed advanced governance subsystems ─────────────────
    _run_orchestrator(who, tool_name, params, result, session_cfg)

    return _result_to_response(result)


def _check_hook_full(
    hook_payload: Dict[str, Any],
    policy: Policy,
    who: str,
    tool_name: str,
    tool_input: dict,
    session_id: str,
    session_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    完整治理路径：enforce() + CIEU + 委托链 + 漂移检测 + omission 时限。
    内部函数，由 check_hook 在有 session 时自动调用。
    """
    from ystar.domains.openclaw.adapter import (
        enforce, SessionState, OpenClawEvent, EventType,
        configure_auto_persist, configure_omission_governance,
    )
    from ystar.kernel.dimensions import normalize_aliases

    # 构建 SessionState（从 policy 的合约继承）
    agent_contracts = dict(policy._rules)  # IntentContract per agent

    # ── 从 session 加载委托链（支持 SUBAGENT_SPAWN / HANDOFF 单调性验证）──
    # 链由用户在 init 时定义，序列化进 session.json，这里反序列化
    delegation_chain = None
    try:
        from ystar.kernel.dimensions import DelegationChain as _DC
        chain_data = session_cfg.get("delegation_chain") if session_cfg else None
        if chain_data:
            delegation_chain = _DC.from_dict(chain_data)
    except Exception:
        pass

    state = SessionState(
        session_id      = session_id,
        agent_contracts = agent_contracts,
        delegation_chain= delegation_chain,   # None 时跳过单调性检查
    )

    # 委托链存在时自动验证（多跳级联验证）
    if state.delegation_chain is not None:
        errors = state.delegation_chain.validate()
        if errors:
            return {
                "action":  "block",
                "message": f"[Y*] Delegation chain violation: {errors[0]}",
            }

    # 配置 CIEU 自动持久化
    cieu_db = session_cfg.get("cieu_db", ".ystar_cieu.db")
    configure_auto_persist(cieu_db)

    # 从 session 合约里读取 obligation_timing，配置 omission engine（按角色过滤）
    _setup_omission_from_contract(session_cfg, cieu_db, agent_id=who)

    # ── tool_name → EventType（含委托类事件）───────────────────────────
    _EVENT_MAP = {
        "Write": EventType.FILE_WRITE,    "Edit": EventType.FILE_WRITE,
        "MultiEdit": EventType.FILE_WRITE,"Read": EventType.FILE_READ,
        "Bash": EventType.CMD_EXEC,     "WebFetch": EventType.WEB_FETCH,
        "WebSearch": EventType.WEB_FETCH, "Task": EventType.CMD_EXEC,
        "Glob": EventType.FILE_READ,      "Grep": EventType.FILE_READ,
        "LS":   EventType.FILE_READ,
        # 委托类事件：触发 enforce() 里的单调性验证
        "subagent_spawn": EventType.SUBAGENT_SPAWN,
        "handoff":        EventType.HANDOFF,
        "SubagentSpawn":  EventType.SUBAGENT_SPAWN,
        "Handoff":        EventType.HANDOFF,
    }
    etype = _EVENT_MAP.get(tool_name, EventType.FILE_WRITE)

    params    = _extract_params(tool_name, tool_input)
    file_path = params.get("file_path")
    command   = params.get("command")
    url       = params.get("url")

    event = OpenClawEvent(
        event_type    = etype,
        agent_id      = who,
        session_id    = session_id,
        task_ticket_id= hook_payload.get("task_ticket_id", ""),
        file_path     = file_path,
        command       = command,
        url           = url,
    )

    decision, cieu_records = enforce(event, state)

    from ystar.domains.openclaw.adapter import EnforceDecision
    if decision in (EnforceDecision.DENY, EnforceDecision.ESCALATE):
        # ── 构建 block message：violation 原因 + gate 的 suggested_action ──
        reason = ""
        suggested = ""

        # 从 CIEU 记录里取违规原因
        if cieu_records and cieu_records[0].call_record:
            viols = cieu_records[0].call_record.violations
            if viols:
                reason = f"[Y*] {viols[0].message}"

        # 从 drift_details 里取 gate 的 suggested_action（义务超时阻断时）
        if cieu_records and cieu_records[0].drift_details:
            dd = cieu_records[0].drift_details
            if "Suggested:" in dd:
                suggested = dd[dd.index("Suggested:") + len("Suggested:"):].strip()

        if not reason:
            reason = f"[Y*] agent '{who}' action denied by governance"

        message = reason
        if suggested and suggested != "None":
            message = f"{reason}\n\n{suggested}"

        # ── NEW: Process DENY triggers (Trigger #7: Failure Case Documentation) ──
        _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)

        # ── Orchestrator: feed advanced governance subsystems (DENY path) ────
        _run_orchestrator(who, tool_name, params, decision, session_cfg)

        return {"action": "block", "message": message}

    # ── NEW: Process ALLOW triggers (full path) ──────────────────────────────
    _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)

    # ── Orchestrator: feed advanced governance subsystems (ALLOW path) ────
    _run_orchestrator(who, tool_name, params, decision, session_cfg)

    return {}


# 缓存：避免每次 hook 都重建 omission adapter
_omission_cache_key: Optional[str] = None


def _filter_obligations_by_agent(
    session_cfg: Dict[str, Any],
    contract_dict: dict,
    agent_id: str,
) -> dict:
    """
    根据 obligation_agent_scope 过滤 obligation_timing，
    只保留属于当前 agent 的义务。

    scope 格式：{"rule_id": ["ystar-cto"]}
    "*" 表示适用于所有 agent。
    无 scope 配置 → 全部保留（向后兼容）。
    """
    scope = session_cfg.get("obligation_agent_scope")
    if not scope:
        return contract_dict   # 无 scope → 向后兼容，全部保留

    timing = contract_dict.get("obligation_timing", {})
    if not timing:
        return contract_dict

    filtered = {}
    for rule_id, timeout in timing.items():
        agents = scope.get(rule_id, ["*"])
        if "*" in agents or agent_id in agents:
            filtered[rule_id] = timeout

    result = dict(contract_dict)
    result["obligation_timing"] = filtered
    return result


def _setup_omission_from_contract(
    session_cfg: Dict[str, Any],
    cieu_db: str,
    agent_id: str = "agent",
) -> None:
    """
    从 session 合约的 obligation_timing 配置 omission engine。

    v0.49: 支持 obligation_agent_scope — 只注册属于当前 agent 的义务。
    缓存 key = session_id + agent_id，不同 agent 可以有不同的义务集。

    omission 违规事件同时写入 CIEUStore，形成统一的因果日志。
    """
    global _omission_cache_key

    session_id = session_cfg.get("session_id", "")
    cache_key = f"{session_id}:{agent_id}"
    if cache_key and cache_key == _omission_cache_key:
        return   # 同一 session + agent，已经配置过

    try:
        from ystar.domains.openclaw.adapter import configure_omission_governance
        from ystar.governance.omission_rules import reset_registry
        from ystar.domains.openclaw.accountability_pack import (
            apply_openclaw_accountability_pack
        )
        from ystar.adapters.omission_adapter import create_adapter
        from ystar.kernel.dimensions import IntentContract
        from ystar.governance.cieu_store import CIEUStore

        # 从 session 合约里构建 IntentContract（含 obligation_timing）
        contract_dict = session_cfg.get("contract") or {}

        # ── P1-2: 按角色过滤义务 ──────────────────────────────────────
        contract_dict = _filter_obligations_by_agent(
            session_cfg, contract_dict, agent_id
        )
        n_total = len(session_cfg.get("contract", {}).get("obligation_timing", {}))
        n_active = len(contract_dict.get("obligation_timing", {}))
        if n_total != n_active:
            _log.info("Obligation scoping: %s gets %d/%d obligations",
                      agent_id, n_active, n_total)

        try:
            contract = IntentContract.from_dict(contract_dict)
        except Exception:
            contract = None

        # 配置带合约时限的 omission registry
        registry = reset_registry()
        apply_openclaw_accountability_pack(registry, contract=contract)

        # 配置持久化 store
        try:
            from ystar.governance.omission_store import OmissionStore
            store = OmissionStore(db_path=cieu_db.replace(".db", "_omission.db"))
        except Exception:
            from ystar.governance.omission_store import InMemoryOmissionStore
            store = InMemoryOmissionStore()

        # ── 关键：把真实的 CIEUStore 传入，让 omission 违规写入统一日志 ──
        try:
            cieu_store = CIEUStore(cieu_db)
        except Exception:
            cieu_store = None

        adapter = create_adapter(store=store, registry=registry,
                                 cieu_store=cieu_store)
        configure_omission_governance(adapter=adapter)

        # ── 关键1：启用 obligation-first gate ────────────────────────────
        # OmissionEngine 检测到违规 → InterventionEngine 产生 INTERRUPT_GATE 脉冲
        # → _run_gate_check 在下次 enforce() 时返回 DENY
        try:
            from ystar.domains.openclaw.adapter import (
                configure_intervention_engine, get_omission_adapter
            )
            configure_intervention_engine()
        except Exception:
            pass

        # ── 关键2：接通 scan→pulse 链路 ──────────────────────────────────
        # OmissionEngine.scan() 产生 violation 后必须推给 InterventionEngine
        # 否则 pulse_store 里永远没有 INTERRUPT_GATE 脉冲，gate 永远不触发
        # 方法：给 engine.scan 包一个 wrapper，violations 自动转发
        try:
            from ystar.domains.openclaw.adapter import (
                _intervention_engine as _ie_ref
            )
            import ystar.domains.openclaw.adapter as _oc_mod

            _original_scan = adapter.engine.scan

            def _scan_with_gate_forward(now=None):
                result = _original_scan(now=now)
                # 转发 violations → InterventionEngine 产生 INTERRUPT_GATE 脉冲
                ie = _oc_mod._intervention_engine
                if ie is not None and result.violations:
                    try:
                        ie.process_violations(result.violations)
                    except Exception:
                        pass
                return result

            adapter.engine.scan = _scan_with_gate_forward
        except Exception:
            pass

        _omission_cache_key = cache_key

    except Exception as exc:
        _log.error("Omission engine setup failed: %s", exc)


# ── Orchestrator Integration ──────────────────────────────────────────────


def _run_orchestrator(
    who: str,
    tool_name: str,
    params: dict,
    check_result: Any,
    session_cfg: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Feed the Orchestrator after each hook call.

    The orchestrator coordinates:
      - InterventionEngine scan→pulse chain (every ~10 calls)
      - GovernanceLoop meta-learning cycle (every ~50 calls)
      - Path A self-governance (when health is degraded)
      - CausalEngine advisory (on high-risk tools)

    All failures are silently caught — the orchestrator never blocks the hook.
    """
    try:
        from ystar.adapters.orchestrator import get_orchestrator
        orch = get_orchestrator()
        orch.on_hook_call(
            agent_id=who,
            tool_name=tool_name,
            params=params,
            check_result=check_result,
            session_cfg=session_cfg,
        )
    except Exception:
        pass  # Orchestrator failure never blocks the hook


# ── ObligationTrigger Integration ──────────────────────────────────────────


def _process_obligation_triggers(
    tool_name: str,
    tool_input: dict,
    agent_id: str,
    session_id: str,
    check_result: Optional[Any] = None,
) -> None:
    """
    Check for and create any triggered obligations after a tool call.

    This function is called AFTER check() returns, whether ALLOW or DENY.
    - For ALLOW: creates obligations like "update knowledge after web_search"
    - For DENY: creates obligations like "document failure case"

    Args:
        tool_name:     Name of the tool being called
        tool_input:    Parameters passed to the tool
        agent_id:      ID of the agent making the call
        session_id:    Current session ID
        check_result:  Result from policy check (PolicyResult or EnforceDecision)
    """
    try:
        from ystar.governance.obligation_triggers import (
            get_trigger_registry, match_triggers, create_obligation_from_trigger
        )
        from ystar.adapters.omission_adapter import get_omission_adapter

        # Get trigger registry
        registry = get_trigger_registry()
        if not registry:
            return

        # Get omission adapter
        adapter = get_omission_adapter()
        if not adapter:
            return

        # Match triggers against this tool call
        triggers = match_triggers(registry, tool_name, tool_input, agent_id, check_result)

        # Create obligations for each matched trigger
        for trigger in triggers:
            # Special handling for content accuracy review trigger (#9)
            # Only create obligation if writing to content/ or marketing/
            if trigger.trigger_id == "content_accuracy_review":
                file_path = tool_input.get("file_path") or tool_input.get("path") or ""
                if not ("content/" in file_path or "marketing/" in file_path):
                    continue

            create_obligation_from_trigger(
                trigger=trigger,
                agent_id=agent_id,
                session_id=session_id,
                omission_adapter=adapter,
                tool_name=tool_name,
                tool_input=tool_input,
            )

    except Exception:
        pass  # Trigger processing failure does not block the tool call


# Layer: Foundation
"""
Runtime Ingress Controller — the single entry point for all tool-call governance.

Despite the filename 'hook.py', this module is the runtime ingress controller, not a thin adapter.

ystar.adapters.hook  —  Runtime Ingress Controller  v0.48.0
============================================================

Runtime Ingress Controller的职责：
  输入：OpenClaw PreToolUse hook payload（dict）
  输出：{"action": "block"|"", "message": "..."}

执行深度自动升级：
  有 .ystar_session.json → 走 enforce()（完整治理路径）
                             委托链验证 + 漂移检测 + CIEU 五元组
  无 .ystar_session.json → 走 Policy.check()（轻量路径）+ 基础 CIEU

用户接口零变化，行为根据上下文自动选择深度。

职责边界：
  Q1: 给 LangChain 用要改吗？     → 要改（OpenClaw 专属格式）
  Q2: 需要记住上一次发生了什么？  → 不需要
  Q3: 翻译格式还是判断对错？      → 翻译格式

治理逻辑（Omission/Lineage/Drift/Gate）在 domains/openclaw/adapter.py。

P1-5 拆分完成（1208行→4文件）：
  - identity_detector.py: agent 身份检测、session config 加载
  - boundary_enforcer.py: 边界检查（immutable/write/tool restrictions）
  - cieu_writer.py: CIEU 记录写入（boot + events）
  - hook.py: 主入口 check_hook()、参数翻译、orchestrator 集成
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, Optional

from ystar.session import Policy, PolicyResult

# ── P1-5: Import from extracted modules ────────────────────────────────
from ystar.adapters.identity_detector import (
    _detect_agent_id,
    _load_session_config,
)
from ystar.adapters.boundary_enforcer import (
    _check_immutable_paths,
    _check_restricted_write_paths,
    _check_write_boundary,
    _check_tool_restriction,
    _check_behavior_rules,
    _check_task_type_symbols,
    _extract_write_paths_from_bash,
    # Re-export for backward compatibility (tests import from hook.py)
    _load_write_paths_from_agents_md,
    _ensure_write_paths_loaded,
    _AGENT_WRITE_PATHS,
)
from ystar.adapters.cieu_writer import (
    _write_boot_record,
    _write_cieu,
)

_log = logging.getLogger("ystar.hook")


# ── Deny-phrases config loader (configurable blocklist, no hardcoded strings) ──
_deny_phrases_cache: list = None  # type: ignore[assignment]


def _load_deny_phrases() -> list:
    """Load deny-phrases from workspace yaml config.

    Returns empty list if:
    - workspace_config unavailable (product standalone install)
    - yaml file does not exist
    - yaml parse fails

    This ensures Y*gov product never blocks phrases unless explicitly configured
    by the deploying workspace.
    """
    global _deny_phrases_cache
    if _deny_phrases_cache is not None:
        return _deny_phrases_cache

    try:
        from ystar.workspace_config import get_labs_workspace
        ws = get_labs_workspace()
        if ws is None:
            _deny_phrases_cache = []
            return _deny_phrases_cache
        yaml_path = ws / "knowledge" / "shared" / "deny_phrases.yaml"
        if not yaml_path.is_file():
            yaml_path = ws / "governance" / "deny_phrases.yaml"
        if not yaml_path.is_file():
            _deny_phrases_cache = []
            return _deny_phrases_cache
        import yaml as _yaml
        data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        _deny_phrases_cache = data.get("phrases", []) if isinstance(data, dict) else []
        return _deny_phrases_cache
    except Exception:
        _deny_phrases_cache = []
        return _deny_phrases_cache

if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*hook] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.WARNING)


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

    # ── Agent tool: set .ystar_active_agent to subagent_type ──────────────
    # CZL-MARKER-PER-SESSION-ISOLATION (2026-04-19): Write to per-session
    # marker file when session ID is available, plus global for backward compat.
    #
    # CZL-SPAWN-PPID-MARKER-FIX v2 (2026-04-24): IMPORTANT — do NOT write to
    # the caller's ppid marker here. All subagents within the same Claude Code
    # session share the same PPID as the root process. Writing the subagent's
    # identity to ppid_{PPID} clobbers the root process (CEO) identity, causing
    # identity cross-contamination.
    #
    # Instead, write only:
    #   1. Global .ystar_active_agent (backward compat, last-writer-wins)
    #   2. Named .ystar_active_agent.subagent_{name} breadcrumb (child lookup)
    #   3. Per-session marker via CLAUDE_SESSION_ID (if available)
    #
    # The child subagent resolves identity via payload.agent_type (authoritative,
    # set by Claude Code for every subagent tool call) — see hook_wrapper.py
    # CZL-SPAWN-PPID-MARKER-FIX v2 block.
    if tool_name == "Agent":
        subagent_type = tool_input.get("subagent_type")
        if subagent_type:
            try:
                _cwd = os.getcwd()
                active_agent_path = os.path.join(_cwd, ".ystar_active_agent")

                # Resolve the scripts/ directory for marker writes
                # (hook_wrapper.py reads from scripts/, not necessarily cwd)
                _scripts_dir = os.path.join(_cwd, "scripts")
                if not os.path.isdir(_scripts_dir):
                    # Try YSTAR_REPO_ROOT
                    _rr = os.environ.get("YSTAR_REPO_ROOT", "")
                    if _rr:
                        _scripts_dir = os.path.join(_rr, "scripts")
                    if not os.path.isdir(_scripts_dir):
                        # Try workspace_config
                        try:
                            from ystar.workspace_config import get_labs_workspace
                            _ws = get_labs_workspace()
                            if _ws:
                                _scripts_dir = str(_ws / "scripts")
                        except Exception:
                            pass
                _write_dirs = [_cwd]
                if os.path.isdir(_scripts_dir) and _scripts_dir != _cwd:
                    _write_dirs.append(_scripts_dir)

                # Map subagent_type to canonical governance ID for consistency
                try:
                    from ystar.adapters.identity_detector import _map_agent_type
                    _canonical = _map_agent_type(subagent_type)
                except Exception:
                    _canonical = subagent_type

                # Per-session marker via CLAUDE_SESSION_ID only (NOT ppid)
                _sid_for_agent = os.environ.get("CLAUDE_SESSION_ID", "").strip()
                _per_session_path = None
                if _sid_for_agent:
                    _sanitized = "".join(c for c in _sid_for_agent if c.isalnum() or c in "-_")
                    if _sanitized:
                        _per_session_path = os.path.join(_cwd, f".ystar_active_agent.{_sanitized}")
                # Write per-session marker if available
                if _per_session_path:
                    with open(_per_session_path, "w") as f:
                        f.write(_canonical)
                    active_agent_path = _per_session_path  # for CIEU event

                # Write to all target directories (cwd + scripts/)
                for _wd in _write_dirs:
                    try:
                        # Global marker for backward compat
                        with open(os.path.join(_wd, ".ystar_active_agent"), "w") as f:
                            f.write(_canonical)
                        # Named subagent marker — child can look this up
                        # by its own agent_type from the payload
                        _safe_name = "".join(
                            c for c in subagent_type if c.isalnum() or c in "-_"
                        )
                        if _safe_name:
                            _named_path = os.path.join(
                                _wd, f".ystar_active_agent.subagent_{_safe_name}"
                            )
                            with open(_named_path, "w") as f:
                                f.write(_canonical)
                    except Exception:
                        pass  # Non-fatal

                # Emit CIEU event
                from ystar.governance.cieu_store import CIEUStore
                cieu_db = ".ystar_cieu.db"
                try:
                    store = CIEUStore(cieu_db)
                    store.write_dict({
                        "session_id":    "unknown",  # Will be overwritten by caller if known
                        "agent_id":      _canonical,
                        "event_type":    "AGENT_IDENTITY_SET",
                        "decision":      "allow",
                        "passed":        True,
                        "file_path":     active_agent_path,
                        "evidence_grade": "action",
                        "params":        {"subagent_type": subagent_type,
                                         "canonical": _canonical,
                                         "per_session": _per_session_path is not None,
                                         "write_dirs": _write_dirs},
                    })
                    _log.info("AGENT_IDENTITY_SET: .ystar_active_agent -> %s (canonical=%s, per_session=%s)",
                             subagent_type, _canonical, _per_session_path is not None)
                except Exception as e:
                    _log.error("Failed to write AGENT_IDENTITY_SET event: %s", e)
            except Exception as e:
                _log.error("Failed to set .ystar_active_agent: %s", e)

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
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"[Y*] {msg}",
            "violations": [
                {"dimension": v.dimension, "message": v.message}
                for v in result.violations
            ],
        }
    }


def _try_extract_guidance(cieu_records) -> "Optional[GuidancePayload]":
    """
    CZL-ARCH-11a: Extract GuidancePayload from CIEU records if present.

    Checks two sources:
    1. A `.guidance` attribute on the first CIEU record (structured path)
    2. JSON-encoded GuidancePayload in drift_details (serialized fallback)

    Returns None if no guidance is found or if invoke_cmd is empty.
    """
    from ystar.domains.openclaw.adapter import GuidancePayload

    if not cieu_records:
        return None

    rec = cieu_records[0]

    # Path 1: structured attribute (future-proof — when enforce() attaches GuidancePayload directly)
    gp = getattr(rec, "guidance", None)
    if isinstance(gp, GuidancePayload) and gp.invoke_cmd:
        return gp

    # Path 2: JSON in drift_details (e.g. '{"invoke_cmd": "ystar doctor", ...}')
    dd = getattr(rec, "drift_details", None)
    if dd and isinstance(dd, str):
        try:
            data = json.loads(dd)
            if isinstance(data, dict) and data.get("invoke_cmd"):
                return GuidancePayload(
                    invoke_cmd=data["invoke_cmd"],
                    fix_command_args=data.get("fix_command_args", {}),
                    then_retry_original=data.get("then_retry_original", False),
                    rule_ref=data.get("rule_ref"),
                    docs_ref=data.get("docs_ref"),
                )
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _emit_auto_invoke_cieu(
    agent_id: str,
    tool_name: str,
    invoke_cmd: str,
    success: bool,
    session_id: str = "",
    session_cfg: Optional[Dict[str, Any]] = None,
    error: str = "",
) -> None:
    """
    CZL-ARCH-11a: Emit AUTO_INVOKE_APPLIED CIEU event.
    """
    try:
        from ystar.governance.cieu_store import CIEUStore
        cieu_db = (session_cfg or {}).get("cieu_db", ".ystar_cieu.db")
        store = CIEUStore(cieu_db)
        store.record({
            "event_type": "AUTO_INVOKE_APPLIED",
            "agent_id": agent_id,
            "session_id": session_id,
            "tool_name": tool_name,
            "invoke_cmd": invoke_cmd,
            "success": success,
            "error": error,
            "timestamp": time.time(),
        })
    except Exception as exc:
        _log.debug("[ARCH-11a] Failed to emit AUTO_INVOKE_APPLIED CIEU: %s", exc)


def _compute_effective_contract(delegation_chain_dict: dict, agent_id: str) -> dict:
    """
    Compute effective contract for specified agent (intersection of all contracts in path).

    Logic:
    1. Find agent's authorization path from delegation chain
    2. Compute intersection of all contracts in path (strictest constraints)
    3. Return merged contract dict

    Args:
        delegation_chain_dict: delegation_chain field from session.json
        agent_id: current agent executing tool call

    Returns:
        Effective contract dict representation
    """
    from ystar.kernel.dimensions import DelegationChain, IntentContract

    # Deserialize DelegationChain
    try:
        chain = DelegationChain.from_dict(delegation_chain_dict)
    except Exception as e:
        _log.warning(f"Failed to parse delegation chain: {e}")
        return {}

    # Find authorization path
    path = chain.find_path(agent_id)

    if not path:
        _log.warning(f"Agent {agent_id} not found in delegation chain")
        return {}

    # Merge all contracts in path (take intersection)
    effective = None

    for delegation_contract in path:
        contract = delegation_contract.contract

        if effective is None:
            effective = contract
        else:
            # Take intersection: stricter constraints
            effective = _merge_contracts_strict(effective, contract)

    return effective.to_dict() if effective else {}


def _merge_contracts_strict(c1: "IntentContract", c2: "IntentContract") -> "IntentContract":
    """
    Merge two contracts, taking strictest constraints (intersection).

    Rules:
    - deny: union (deny if either denies)
    - only_paths: intersection (allow only if both allow)
    - deny_commands: union
    - only_domains: intersection
    - invariant: union (all conditions must be satisfied)
    - value_range: intersection (narrower range)

    Note: This is monotonic shrinking operation - result is never looser than either input.
    """
    from ystar.kernel.dimensions import IntentContract

    # deny: union
    merged_deny = list(set(c1.deny) | set(c2.deny))

    # only_paths: intersection (allow only if both allow)
    if c1.only_paths and c2.only_paths:
        # Both have restrictions, take intersection (path prefix matching)
        merged_only_paths = _intersect_path_prefixes(c1.only_paths, c2.only_paths)
    elif c1.only_paths:
        merged_only_paths = c1.only_paths
    elif c2.only_paths:
        merged_only_paths = c2.only_paths
    else:
        merged_only_paths = []

    # deny_commands: union
    merged_deny_commands = list(set(c1.deny_commands) | set(c2.deny_commands))

    # only_domains: intersection
    if c1.only_domains and c2.only_domains:
        merged_only_domains = list(set(c1.only_domains) & set(c2.only_domains))
    elif c1.only_domains:
        merged_only_domains = c1.only_domains
    elif c2.only_domains:
        merged_only_domains = c2.only_domains
    else:
        merged_only_domains = []

    # invariant: union (all conditions must be satisfied)
    merged_invariant = list(set(c1.invariant) | set(c2.invariant))

    # value_range: take intersection (narrower range)
    merged_value_range = _merge_value_ranges(c1.value_range, c2.value_range)

    return IntentContract(
        name=f"merged({c1.name},{c2.name})",
        deny=merged_deny,
        only_paths=merged_only_paths,
        deny_commands=merged_deny_commands,
        only_domains=merged_only_domains,
        invariant=merged_invariant,
        value_range=merged_value_range,
    )


def _intersect_path_prefixes(paths1: list, paths2: list) -> list:
    """
    Path prefix intersection.
    Keep only paths allowed by both sides.
    """
    result = []
    for p1 in paths1:
        for p2 in paths2:
            # If p1 is prefix of p2, or p2 is prefix of p1, keep the longer one
            if p1.startswith(p2):
                result.append(p1)
            elif p2.startswith(p1):
                result.append(p2)
    return list(set(result))


def _merge_value_ranges(vr1: dict, vr2: dict) -> dict:
    """
    value_range intersection (narrower range).

    Example:
    vr1 = {"file_size": {"max": 1000}}
    vr2 = {"file_size": {"max": 500}}
    result = {"file_size": {"max": 500}}  # take stricter one
    """
    merged = {}

    all_keys = set(vr1.keys()) | set(vr2.keys())

    for key in all_keys:
        range1 = vr1.get(key, {})
        range2 = vr2.get(key, {})

        merged_range = {}

        # min: take larger (stricter)
        if "min" in range1 or "min" in range2:
            mins = [range1.get("min"), range2.get("min")]
            mins = [m for m in mins if m is not None]
            if mins:
                merged_range["min"] = max(mins)

        # max: take smaller (stricter)
        if "max" in range1 or "max" in range2:
            maxs = [range1.get("max"), range2.get("max")]
            maxs = [m for m in maxs if m is not None]
            if maxs:
                merged_range["max"] = min(maxs)

        if merged_range:
            merged[key] = merged_range

    return merged


def check_hook(
    hook_payload: Dict[str, Any],
    policy: Optional[Policy] = None,
    agent_id: Optional[str] = None,
    agents_md_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    处理一个 OpenClaw PreToolUse hook，返回 hook 响应。

    执行深度根据上下文自动选择，用户无需配置：

    有 .ystar_session.json（ystar init 已运行）：
      → enforce()：委托链验证 + 漂移检测 + CIEU 五元组 + Omission 注入
    无 .ystar_session.json：
      → Policy.check()：规则检查 + 基础 CIEU 写入

    Task 2: Policy compilation is now cached internally. If policy is None,
    check_hook will build it from AGENTS.md with session-level caching.

    Args:
        hook_payload:   OpenClaw 发来的原始 hook dict
        policy:         Policy 对象（可选，为 None 时自动从 AGENTS.md 构建）
        agent_id:       覆盖 payload 里的 agent_id（可选）
        agents_md_path: AGENTS.md 路径（可选，默认为 cwd/AGENTS.md）

    Returns:
        {} 表示允许，{"action":"block",...} 表示拒绝
    """
    tool_name  = hook_payload.get("tool_name", "")
    tool_input = hook_payload.get("tool_input", {})

    # ── Task 2: Build Policy with caching if not provided ──────────────────
    if policy is None:
        policy = _get_or_build_policy(agents_md_path)

    if policy is None:
        # No AGENTS.md found, create empty policy
        policy = Policy({})

    # ── P0-2: 检测 agent 身份 ──────────────────────────────────────
    who = agent_id or _detect_agent_id(hook_payload)
    session_id_payload = hook_payload.get("session_id", "")

    # ── Directive #024: CIEU Boot Record（首次调用时写入）──────────
    session_cfg_boot = _load_session_config_cached()
    cieu_db_boot = session_cfg_boot.get("cieu_db", ".ystar_cieu.db") if session_cfg_boot else ".ystar_cieu.db"
    _write_boot_record(who, session_id_payload or "unknown", cieu_db_boot)

    # ── P0-0: 不可変路径检查（AGENTS.md / .claude/agents/*.md）──────
    # CZL-KERNEL-OVERRIDE-PRE-FALLBACK: Run immutable check BEFORE policy-
    # membership fallback so that override_roles (from session.json) is
    # consulted on the original detected identity, not a rewritten alias.
    # Without this ordering, roles like "secretary" get rewritten to "agent"
    # by the fallback (because they lack an AGENTS.md policy block) and the
    # override_roles=["secretary"] declaration becomes structurally unreachable.
    params_early = _extract_params(tool_name, tool_input)
    immutable_deny = _check_immutable_paths(tool_name, params_early, who)
    if immutable_deny is not None:
        cieu_db = ".ystar_cieu.db"
        session_cfg_imm = _load_session_config_cached()
        if session_cfg_imm:
            cieu_db = session_cfg_imm.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, immutable_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY immutable path: %s → %s", who, params_early.get("file_path", "?"))
        return _result_to_response(immutable_deny)

    # ── P0-0.25-PRE-FALLBACK: 受限写路径检查（原始 who，未 fallback 前）──
    # CZL-KERNEL-OVERRIDE-PRE-FALLBACK-PHASE-2: Apply the same override-
    # before-fallback logic to restricted_write_paths that Phase 1 applied
    # to immutable_paths. Without this, secretary writing AGENTS.md deadlocks
    # because secretary-not-in-policy → fallback→agent → restricted_deny.
    # The restricted_write_paths config (e.g. {"AGENTS.md": ["secretary"]})
    # must be checked with the ORIGINAL who identity before fallback rewrites
    # it to "agent" or "cto".
    restricted_deny_early = _check_restricted_write_paths(tool_name, params_early, who)
    if restricted_deny_early is not None:
        cieu_db = ".ystar_cieu.db"
        session_cfg_rst_early = _load_session_config_cached()
        if session_cfg_rst_early:
            cieu_db = session_cfg_rst_early.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, restricted_deny_early,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY restricted write path (pre-fallback): %s → %s", who, params_early.get("file_path", "?"))
        return _result_to_response(restricted_deny_early)

    # 若 agent_id 未在 Policy 里注册，按层级 alias fallback
    # CZL-ARCH-1-followup (2026-04-18): eng-* 子角色继承 cto 权限，
    # 避免因 AGENTS.md 未显式注册每个 engineer 而回退到 "agent" 盲拒。
    # 原逻辑：who not in policy → who = "agent" → blanket deny (lock-death root).
    if who not in policy:
        # eng-* sub-roles inherit from cto (engineering manager)
        if who.startswith("eng-") and "cto" in policy:
            who = "cto"
        # unknown fallback to "agent" (blanket-deny) still available
        elif "agent" in policy:
            who = "agent"
        else:
            registered = list(policy._rules.keys())
            if registered:
                who = registered[0]

    # NOTE (CZL-KERNEL-OVERRIDE-PRE-FALLBACK-PHASE-2): The restricted_write_paths
    # check was REMOVED from this post-fallback position. It now runs exclusively
    # at line 521 with the ORIGINAL who identity. Rationale: restricted_write_paths
    # config declares which roles CAN write specific paths (e.g. AGENTS.md: ["secretary"]).
    # Re-checking after fallback would incorrectly deny allowed roles whose identity
    # was rewritten (secretary → agent). The path set is identical pre/post fallback,
    # so there is no coverage gap from removing the post-fallback check.

    # ── P0-0.5: 工具限制检查（allowed/disallowed tools）──────────────
    tool_deny = _check_tool_restriction(who, tool_name)
    if tool_deny is not None:
        cieu_db = ".ystar_cieu.db"
        session_cfg_td = _load_session_config_cached()
        if session_cfg_td:
            cieu_db = session_cfg_td.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, tool_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY tool restriction: %s → %s", who, tool_name)
        return _result_to_response(tool_deny)

    # ── P0-0.6: Agent behavior rules check ──────────────────────────────
    # Load session config once and pass to behavior rules check
    session_cfg_early = _load_session_config_cached()
    behavior_deny = _check_behavior_rules(who, tool_name, params_early, session_cfg=session_cfg_early)
    if behavior_deny is not None:
        cieu_db = ".ystar_cieu.db"
        if session_cfg_early:
            cieu_db = session_cfg_early.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, behavior_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY behavior rule: %s → %s (%s)", who, tool_name, behavior_deny.reason)
        return _result_to_response(behavior_deny)

    # ── P0-0.7: Symbol sync system (task type checkpoint) ──────────────
    symbol_deny = _check_task_type_symbols(who, tool_name, params_early)
    if symbol_deny is not None:
        cieu_db = ".ystar_cieu.db"
        if session_cfg_early:
            cieu_db = session_cfg_early.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, symbol_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY symbol checkpoint: %s → %s (%s)", who, tool_name, symbol_deny.reason)
        return _result_to_response(symbol_deny)

    # ── P0-1: 写路径边界检查（仅 Write/Edit/MultiEdit）──────────────
    write_deny = _check_write_boundary(who, tool_name, params_early)
    if write_deny is not None:
        # 写入 CIEU 记录（deny）
        cieu_db = ".ystar_cieu.db"
        session_cfg_early = _load_session_config_cached()
        if session_cfg_early:
            cieu_db = session_cfg_early.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, write_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY write boundary: %s → %s (%s)",
                     who, params_early.get("file_path", "?"), write_deny.reason)
        return _result_to_response(write_deny)

    # ── P0-1.5: Bash 命令写路径检查 ──────────────────────────────────
    if tool_name == "Bash":
        command = params_early.get("command", "")
        if command:
            bash_write_paths = _extract_write_paths_from_bash(command)
            for path in bash_write_paths:
                # 检查不可变路径
                immutable_result = _check_immutable_paths(
                    "Write",  # 视为写操作
                    {"file_path": path}
                )
                if immutable_result is not None:
                    cieu_db = ".ystar_cieu.db"
                    session_cfg_bash = _load_session_config_cached()
                    if session_cfg_bash:
                        cieu_db = session_cfg_bash.get("cieu_db", cieu_db)
                    contract = policy._rules.get(who)
                    _write_cieu(who, tool_name, params_early, immutable_result,
                                session_id_payload or "unknown",
                                contract.hash if contract else "", cieu_db)
                    _log.warning("DENY Bash command (immutable path): %s → %s", who, path)
                    return _result_to_response(immutable_result)

                # 检查受限写路径
                restricted_result = _check_restricted_write_paths(
                    "Write",  # 视为写操作
                    {"file_path": path},
                    who
                )
                if restricted_result is not None:
                    cieu_db = ".ystar_cieu.db"
                    session_cfg_bash_r = _load_session_config_cached()
                    if session_cfg_bash_r:
                        cieu_db = session_cfg_bash_r.get("cieu_db", cieu_db)
                    contract = policy._rules.get(who)
                    _write_cieu(who, tool_name, params_early, restricted_result,
                                session_id_payload or "unknown",
                                contract.hash if contract else "", cieu_db)
                    _log.warning("DENY Bash command (restricted path): %s → %s", who, path)
                    return _result_to_response(restricted_result)

                # 检查写边界
                boundary_result = _check_write_boundary(
                    who, "Write",  # 视为写操作
                    {"file_path": path}
                )
                if boundary_result is not None:
                    cieu_db = ".ystar_cieu.db"
                    session_cfg_bash2 = _load_session_config_cached()
                    if session_cfg_bash2:
                        cieu_db = session_cfg_bash2.get("cieu_db", cieu_db)
                    contract = policy._rules.get(who)
                    _write_cieu(who, tool_name, params_early, boundary_result,
                                session_id_payload or "unknown",
                                contract.hash if contract else "", cieu_db)
                    _log.warning("DENY Bash command (write boundary): %s → %s", who, path)
                    return _result_to_response(boundary_result)

    # ── P0-1.6: Bash command content deny scan ─────────────────────────
    # Scans the entire command string against the contract's deny list
    # and deny_commands. Catches: cat /etc/passwd, curl http://evil.com,
    # python -c "os.system(...)", sudo, eval, exec, etc.
    # This closes the gap where the full governance path (OpenClaw enforce)
    # only checks structured fields (file_path, url) but not raw command text.
    if tool_name == "Bash":
        command = params_early.get("command", "")
        if command:
            contract = policy._rules.get(who)
            if contract is not None:
                from ystar import check as _check_fn
                cmd_result = _check_fn(
                    params={"command": command, "tool_name": "Bash"},
                    result={},
                    contract=contract,
                )
                if not cmd_result.passed:
                    violation_msg = cmd_result.violations[0].message if cmd_result.violations else "deny"
                    # Write CIEU record directly (cmd_result is CheckResult, not PolicyResult)
                    cieu_db = ".ystar_cieu.db"
                    session_cfg_cmd = _load_session_config_cached()
                    if session_cfg_cmd:
                        cieu_db = session_cfg_cmd.get("cieu_db", cieu_db)
                    try:
                        from ystar.governance.cieu_store import CIEUStore as _CS
                        _cs = _CS(cieu_db)
                        _cs.write_dict({
                            "session_id": session_id_payload or "unknown",
                            "agent_id": who,
                            "event_type": tool_name,
                            "decision": "deny",
                            "passed": False,
                            "command": command[:500],
                            "contract_hash": contract.hash if contract else "",
                            "violations": json.dumps([
                                {"dimension": v.dimension, "message": v.message}
                                for v in cmd_result.violations
                            ]),
                        })
                    except Exception:
                        pass
                    _log.warning(
                        "DENY Bash command content: %s → %s (%s)",
                        who, command[:80], violation_msg,
                    )
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"[Y*] {violation_msg}",
                            "violations": [
                                {"dimension": v.dimension, "message": v.message}
                                for v in cmd_result.violations
                            ],
                        }
                    }

    # ── LESSON_READ tracking (eng-governance 2026-04-15, 蒸馏 verification Layer 1) ──
    # 匹配 knowledge/*/lessons/*.md, emit LESSON_READ CIEU event
    if tool_name == "Read":
        _file_path = params_early.get("file_path", "")
        if _file_path and "/lessons/" in _file_path and _file_path.endswith(".md"):
            try:
                import re as _re
                with open(_file_path, "r", encoding="utf-8") as _f:
                    _content = _f.read(500)
                _fm = _re.match(r'^---\n(.*?)\n---', _content, _re.DOTALL)
                if _fm:
                    _id_m = _re.search(r'^lesson_id:\s*(\S+)', _fm.group(1), _re.MULTILINE)
                    if _id_m:
                        _cieu_db = ".ystar_cieu.db"
                        _scfg = _load_session_config_cached()
                        if _scfg:
                            _cieu_db = _scfg.get("cieu_db", _cieu_db)
                        from ystar.governance.cieu_store import CIEUStore as _CS_LR
                        _CS_LR(_cieu_db).write_dict({
                            "session_id": session_id_payload or "unknown",
                            "agent_id": who,
                            "event_type": "LESSON_READ",
                            "decision": "allow",
                            "passed": True,
                            "file_path": _file_path,
                            "evidence_grade": "action",
                            "params_json": '{"lesson_id":"' + _id_m.group(1) + '"}',
                        })
            except Exception:
                pass  # fail-open for observability path

    # ── I1: 外部CLAUDE.md读取检测 ──────────────────────────────────
    if tool_name == "Read":
        file_path = params_early.get("file_path", "")
        if file_path and "CLAUDE.md" in file_path:
            # 检查是否在当前工作目录之外
            from pathlib import Path
            try:
                current_dir = Path(os.getcwd()).resolve()
                read_path = Path(file_path).resolve()

                # 如果读取的CLAUDE.md不在当前目录或子目录下，记录为外部读取
                if not str(read_path).startswith(str(current_dir)):
                    cieu_db = ".ystar_cieu.db"
                    session_cfg_ext = _load_session_config_cached()
                    if session_cfg_ext:
                        cieu_db = session_cfg_ext.get("cieu_db", cieu_db)

                    # 写入external_config_read事件
                    from ystar.governance.cieu_store import CIEUStore
                    try:
                        store = CIEUStore(cieu_db)
                        store.write_dict({
                            "session_id":    session_id_payload or "unknown",
                            "agent_id":      who,
                            "event_type":    "external_config_read",
                            "decision":      "allow",  # 不阻止，只记录
                            "passed":        True,
                            "file_path":     str(read_path),
                            "evidence_grade": "observation",
                            "params":        {"file_path": str(read_path), "external": True},
                        })
                        _log.warning("EXTERNAL CONFIG READ: %s → %s (context poisoning risk)",
                                   who, str(read_path))
                    except Exception as e:
                        _log.error("Failed to write external_config_read event: %s", e)
            except Exception as e:
                _log.error("Failed to check external CLAUDE.md read: %s", e)

    # ── 尝试完整治理路径（有 session 配置时自动升级）────────────────
    session_cfg = _load_session_config_cached()
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
    # ── Runtime contracts: merge deny/relax layers into effective contract ──
    _apply_runtime_contracts(policy, who)

    params   = _extract_params(tool_name, tool_input)
    result   = policy.check(who, tool_name, **params)

    # 即使是轻量路径，也写入基础 CIEU（有 .ystar_cieu.db 时）
    cieu_db = session_cfg.get("cieu_db", ".ystar_cieu.db") if session_cfg else ".ystar_cieu.db"
    contract = policy._rules.get(who)
    contract_hash = contract.hash if contract else ""
    _write_cieu(who, tool_name, params, result,
                session_id_payload or "unknown", contract_hash, cieu_db)

    # ── router._WRITE_PATTERNS 兜底（Board 2026-04-14 指令: 两套黑名单打通）──
    if result.allowed and tool_name == "Bash":
        command = params.get("command", "")
        try:
            from gov_mcp.router import _SHELL_WRITE_PATTERNS, _PYTHON_WRITE_PATTERNS
            all_patterns = list(_SHELL_WRITE_PATTERNS) + list(_PYTHON_WRITE_PATTERNS)
            for pat in all_patterns:
                if pat.search(command):
                    result = PolicyResult(
                        allowed=False,
                        reason=f"router._WRITE_PATTERNS matched: {pat.pattern}",
                        who=who,
                        what=tool_name,
                    )
                    _log.warning("[router-bridge] blocked by %s: %s", pat.pattern, command[:80])
                    # Re-write CIEU as deny
                    _write_cieu(who, tool_name, params, result,
                                session_id_payload or "unknown", contract_hash, cieu_db)
                    break
        except ImportError as e:
            _log.warning("[router-bridge] fail-open (cannot import router): %s", e)

    # ── CEO AVOIDANCE DRIFT enforcement (Board 2026-04-14: CIEU always-on) ──
    # spec: reports/ceo_avoidance_enforcement_20260414.md
    # 行: hook 层 enforce CEO 不许出 "推别的"/"换到"/"defer"/"重启" 等 phrase
    if result.allowed and who == "ceo":
        AVOIDANCE_PHRASES = _load_avoidance_phrases()
        scan_text = " ".join(
            str(v) for v in params.values() if isinstance(v, (str, int, float))
        )[:8000]
        scan_lower = scan_text.lower()
        for phrase in AVOIDANCE_PHRASES:
            if phrase.lower() in scan_lower:
                result = PolicyResult(
                    allowed=False,
                    reason=f"CEO_AVOIDANCE_DRIFT: phrase '{phrase}' detected. Continue current task or escalate per ceo_avoidance_enforcement_20260414.md.",
                    who=who,
                    what=tool_name,
                )
                _log.warning("[avoidance] CEO blocked on phrase '%s' in %s tool", phrase, tool_name)
                _write_cieu(who, tool_name, params, result,
                            session_id_payload or "unknown", contract_hash, cieu_db)
                break

    # ── CIEU MARKER enforcement (Board 2026-04-15: K9 v2 unified protocol §7) ──
    # spec: reports/k9_upgrade_daily_patrol_spec_20260415.md §7.1
    # Iron Rule 1.6: CEO + sub-agent 每层必 emit CIEU 5-tuple (Y*/Xt/U/Yt+1/Rt+1)
    # Check: tool call params (command/description/file_path/content) 含任一 marker → pass
    #        否则 → deny
    if result.allowed and who in ("ceo", "cto", "cmo", "cso", "cfo",
                                   "eng-kernel", "eng-governance", "eng-platform", "eng-domains"):
        REQUIRED_MARKERS = ["Y*", "Xt", "Yt+1", "Rt+1"]  # U is implicit in action
        scan_text = " ".join(
            str(v) for v in params.values() if isinstance(v, (str, int, float))
        )[:8000]

        # Count how many markers present
        markers_found = [m for m in REQUIRED_MARKERS if m in scan_text]

        # Require at least 2 markers (relaxed from 4 for practical execution)
        # Full 5-tuple (Y*/Xt/U/Yt+1/Rt+1) ideal, but U implicit in tool call itself
        if len(markers_found) < 2:
            result = PolicyResult(
                allowed=False,
                reason=f"CIEU_MARKER_MISSING: Iron Rule 1.6 requires CIEU 5-tuple markers (Y*/Xt/U/Yt+1/Rt+1) in tool call. Found {markers_found}. Unified protocol §7 mandatory per Board 2026-04-15.",
                who=who,
                what=tool_name,
            )
            _log.warning("[cieu-marker] %s blocked: only %d/4 markers found in %s tool",
                         who, len(markers_found), tool_name)
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

    # ── CZL-ARCH-14: REWRITE — auto-correct false-positive denials (light path) ──
    if not result.allowed:
        try:
            from ystar.rules.auto_rewrite import auto_rewrite_detector, auto_rewrite_executor
            transform = auto_rewrite_detector(tool_name, params)
            if transform is not None:
                rewrite_meta = auto_rewrite_executor(transform, tool_name, params)
                # Emit REWRITE_APPLIED CIEU event
                try:
                    from ystar.governance.cieu_store import CIEUStore as _CS_RW_L
                    _CS_RW_L(cieu_db).write_dict({
                        "session_id": session_id_payload or "unknown",
                        "agent_id": who,
                        "event_type": "REWRITE_APPLIED",
                        "decision": "rewrite",
                        "passed": True,
                        "tool_name": tool_name,
                        "evidence_grade": "governance_rewrite",
                        "params_json": json.dumps({
                            "rewrite_mode": transform.mode,
                            "safe_reason": transform.safe_reason,
                            "original_decision": "deny",
                        }),
                    })
                except Exception:
                    pass
                _log.info(
                    "[ARCH-14] REWRITE_APPLIED (light): mode=%s agent=%s tool=%s",
                    transform.mode, who, tool_name,
                )
                response = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": (
                            f"[Y*gov REWRITE] Auto-corrected: {transform.mode}. "
                            f"{transform.safe_reason}. Original would have been: deny."
                        ),
                    }
                }
                _feed_path_b(who, tool_name, params, response, session_id_payload)
                return response
        except ImportError:
            pass
        except Exception as _rw_light_exc:
            _log.warning("[ARCH-14] REWRITE light path failed: %s", _rw_light_exc)

    # ── Orchestrator: feed advanced governance subsystems ─────────────────
    _run_orchestrator(who, tool_name, params, result, session_cfg)

    # ── Path B: feed observation for metalearning ────────────────────────
    response = _result_to_response(result)
    _feed_path_b(who, tool_name, params, response, session_id_payload)

    return response


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
            if delegation_chain.root is not None:
                _log.info("Delegation chain loaded: tree mode with root=%s", delegation_chain.root.actor)
            else:
                _log.info("Delegation chain loaded: %d links", len(delegation_chain.links))
    except Exception as exc:
        _log.warning("Failed to load delegation chain from session: %s", exc)

    # ── NEW: Compute effective contract from delegation chain path ──
    # If delegation chain exists (tree mode), compute path-based effective contract
    if delegation_chain and delegation_chain.root is not None:
        chain_dict = session_cfg.get("delegation_chain")
        if chain_dict:
            effective_contract_dict = _compute_effective_contract(chain_dict, who)
            if effective_contract_dict:
                from ystar.kernel.dimensions import IntentContract
                effective_contract = IntentContract.from_dict(effective_contract_dict, name=f"{who}_effective")
                # Replace agent's contract with effective (merged) contract
                agent_contracts[who] = effective_contract
                _log.info("Using effective contract for %s (merged from delegation chain path)", who)

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
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"[Y*] Delegation chain violation: {errors[0]}",
                }
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
        "ToolSearch": EventType.FILE_READ,  # Schema lookup, not a write
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

    # ── Helper: extract reason + suggested_action from CIEU records ──
    def _extract_reason_and_suggested() -> tuple:
        reason = ""
        suggested = ""
        if cieu_records and cieu_records[0].call_record:
            viols = cieu_records[0].call_record.violations
            if viols:
                reason = f"[Y*] {viols[0].message}"
        if cieu_records and cieu_records[0].drift_details:
            dd = cieu_records[0].drift_details
            if "Suggested:" in dd:
                suggested = dd[dd.index("Suggested:") + len("Suggested:"):].strip()
        return reason, suggested

    # ── CZL-ARCH-14: REWRITE — auto-correct false-positive denials ─────
    # Check BEFORE DENY branch: if a safe transform matches, override the
    # deny with an ALLOW + REWRITE_APPLIED CIEU event.
    if decision in (EnforceDecision.DENY, EnforceDecision.REWRITE):
        try:
            from ystar.rules.auto_rewrite import auto_rewrite_detector, auto_rewrite_executor
            transform = auto_rewrite_detector(tool_name, params)
            if transform is not None:
                rewrite_meta = auto_rewrite_executor(transform, tool_name, params)
                # Emit REWRITE_APPLIED CIEU event
                try:
                    from ystar.governance.cieu_store import CIEUStore as _CS_RW
                    _rw_db = session_cfg.get("cieu_db", ".ystar_cieu.db")
                    _CS_RW(_rw_db).write_dict({
                        "session_id": session_id,
                        "agent_id": who,
                        "event_type": "REWRITE_APPLIED",
                        "decision": "rewrite",
                        "passed": True,
                        "tool_name": tool_name,
                        "evidence_grade": "governance_rewrite",
                        "params_json": json.dumps({
                            "rewrite_mode": transform.mode,
                            "safe_reason": transform.safe_reason,
                            "original_decision": str(decision.value),
                        }),
                    })
                except Exception as _rw_cieu_exc:
                    _log.debug("[ARCH-14] CIEU write failed: %s", _rw_cieu_exc)

                _log.info(
                    "[ARCH-14] REWRITE_APPLIED: mode=%s agent=%s tool=%s reason=%s",
                    transform.mode, who, tool_name, transform.safe_reason,
                )
                _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)
                _run_orchestrator(who, tool_name, params, decision, session_cfg)
                rewrite_response = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": (
                            f"[Y*gov REWRITE] Auto-corrected: {transform.mode}. "
                            f"{transform.safe_reason}. Original would have been: {decision.value}."
                        ),
                    }
                }
                _feed_path_b(who, tool_name, params, rewrite_response, session_id)
                return rewrite_response
        except ImportError:
            _log.debug("[ARCH-14] auto_rewrite module not available, skipping")
        except Exception as _rw_exc:
            _log.warning("[ARCH-14] REWRITE check failed: %s", _rw_exc)

    # ── CZL-P1-c: Three independent decision branches ──────────────────

    if decision == EnforceDecision.DENY:
        reason, suggested = _extract_reason_and_suggested()
        if not reason:
            reason = f"[Y*] agent '{who}' action denied by governance"
        message = reason
        if suggested and suggested != "None":
            message = f"{reason}\n\n{suggested}"

        _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)
        _run_orchestrator(who, tool_name, params, decision, session_cfg)

        deny_response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        }
        _feed_path_b(who, tool_name, params, deny_response, session_id)
        return deny_response

    if decision == EnforceDecision.ESCALATE:
        reason, suggested = _extract_reason_and_suggested()
        if not reason:
            reason = f"[Y*] agent '{who}' action escalated — requires human intervention"
        message = reason
        if suggested and suggested != "None":
            message = f"{reason}\n\n{suggested}"

        _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)
        _run_orchestrator(who, tool_name, params, decision, session_cfg)

        escalate_response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        }
        _feed_path_b(who, tool_name, params, escalate_response, session_id)
        return escalate_response

    if decision == EnforceDecision.REDIRECT:
        # CZL-P1-c: REDIRECT returns allow + structured fix instructions
        # so the agent sees the message but is NOT blocked.
        reason, suggested = _extract_reason_and_suggested()
        violation_desc = reason or f"agent '{who}' identity/state needs correction"

        # Build structured REDIRECT message with 3 required sections
        fix_command = suggested if suggested and suggested != "None" else (
            f'echo "{who}" > {os.environ.get("YSTAR_REPO_ROOT", ".")}/.ystar_active_agent && retry'
        )

        # ── CZL-ARCH-11a: Mandatory Invoke — auto-upgrade REDIRECT → INVOKE ──
        guidance = _try_extract_guidance(cieu_records)
        if guidance and guidance.invoke_cmd and guidance.then_retry_original:
            invoke_cmd = guidance.invoke_cmd
            invoke_args = guidance.fix_command_args or {}
            try:
                cmd_parts = [invoke_cmd] + [
                    f"--{k}={v}" for k, v in invoke_args.items()
                ]
                proc = subprocess.run(
                    cmd_parts, capture_output=True, text=True, timeout=30,
                )
                if proc.returncode == 0:
                    # Invoke succeeded — upgrade to ALLOW + retry original
                    _log.info(
                        "[ARCH-11a] AUTO_INVOKE succeeded: cmd=%s tool=%s agent=%s",
                        invoke_cmd, tool_name, who,
                    )
                    _emit_auto_invoke_cieu(
                        who, tool_name, invoke_cmd, success=True,
                        session_id=session_id, session_cfg=session_cfg,
                    )
                    _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)
                    _run_orchestrator(who, tool_name, params, decision, session_cfg)
                    allow_response = {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "allow",
                            "permissionDecisionReason": (
                                f"AUTO_INVOKED: {invoke_cmd} succeeded, retrying. "
                                f"Original violation: {violation_desc}"
                            ),
                        }
                    }
                    _feed_path_b(who, tool_name, params, allow_response, session_id)
                    return allow_response
                else:
                    # Invoke failed — stay REDIRECT with error detail
                    err_msg = (proc.stderr or proc.stdout or "unknown error")[:200]
                    _log.warning(
                        "[ARCH-11a] AUTO_INVOKE failed: cmd=%s rc=%d err=%s",
                        invoke_cmd, proc.returncode, err_msg,
                    )
                    _emit_auto_invoke_cieu(
                        who, tool_name, invoke_cmd, success=False,
                        session_id=session_id, session_cfg=session_cfg,
                        error=err_msg,
                    )
            except Exception as exc:
                err_msg = str(exc)[:200]
                _log.warning(
                    "[ARCH-11a] AUTO_INVOKE exception: cmd=%s err=%s",
                    invoke_cmd, err_msg,
                )
                _emit_auto_invoke_cieu(
                    who, tool_name, invoke_cmd, success=False,
                    session_id=session_id, session_cfg=session_cfg,
                    error=err_msg,
                )
            # Fall through to normal REDIRECT if invoke failed/errored
            fix_command = f"{fix_command}\nAUTO_INVOKE_FAILED: {invoke_cmd} — manual fix needed"

        # ── CZL-ARCH-11b: REDIRECT ignore detector via OmissionEngine ──
        # When we reach here, either GuidancePayload was absent (no auto-invoke)
        # or auto-invoke failed. Create obligation to track REDIRECT compliance.
        try:
            from ystar.governance.omission_engine import OmissionEngine
            from ystar.governance.omission_store import InMemoryOmissionStore
            import uuid as _uuid_11b
            _redirect_id = str(_uuid_11b.uuid4())
            _oe = OmissionEngine(store=InMemoryOmissionStore())
            _oe.register_redirect_obligation(
                agent_id=who,
                redirect_id=_redirect_id,
                ttl_actions=3,
                entity_id=session_id or "session",
                redirect_reason=violation_desc[:200],
            )
            _log.info(
                "[ARCH-11b] Registered redirect obligation: agent=%s id=%s",
                who, _redirect_id,
            )
        except Exception as _11b_exc:
            _log.warning("[ARCH-11b] Failed to register redirect obligation: %s", _11b_exc)

        redirect_message = (
            f"[Y*] REDIRECT: {violation_desc}\n"
            f"FIX_COMMAND: {fix_command}\n"
            f"THEN_RETRY: {tool_name} {(params.get('file_path') or params.get('command') or '')[:120]}"
        )

        _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)
        _run_orchestrator(who, tool_name, params, decision, session_cfg)

        redirect_response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": redirect_message,
            }
        }
        _feed_path_b(who, tool_name, params, redirect_response, session_id)
        return redirect_response

    # ── NEW: Process ALLOW triggers (full path) ──────────────────────────────
    _process_obligation_triggers(tool_name, tool_input, who, session_id, decision)

    # ── Orchestrator: feed advanced governance subsystems (ALLOW path) ────
    _run_orchestrator(who, tool_name, params, decision, session_cfg)

    # ── CEO AVOIDANCE DRIFT enforcement (FULL PATH, CTO 2026-04-15 stress test P0 fix) ──
    # Bug: commit 4997d6c only added AVOIDANCE to light path; full path early-returned never reaching it
    if who == "ceo":
        AVOIDANCE_PHRASES = _load_avoidance_phrases()
        scan_text = " ".join(
            str(v) for v in params.values() if isinstance(v, (str, int, float))
        )[:8000]
        scan_lower = scan_text.lower()
        for phrase in AVOIDANCE_PHRASES:
            if phrase.lower() in scan_lower:
                deny_msg = f"CEO_AVOIDANCE_DRIFT: phrase '{phrase}' detected (full path). Continue current task or escalate per ceo_avoidance_enforcement_20260414.md."
                _log.warning("[avoidance-full] CEO blocked on phrase '%s' in %s tool", phrase, tool_name)
                cieu_db = session_cfg.get("cieu_db", ".ystar_cieu.db") if session_cfg else ".ystar_cieu.db"
                contract = policy._rules.get(who)
                deny_result = PolicyResult(allowed=False, reason=deny_msg, who=who, what=tool_name)
                _write_cieu(who, tool_name, params, deny_result,
                            session_id, contract.hash if contract else "", cieu_db)
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"[Y*] {deny_msg}",
                    }
                }

    # ── Path B: feed observation for metalearning ────────────────────────
    _feed_path_b(who, tool_name, params, {}, session_id)

    return {}


# ── Task 2: Session-level Caching ──────────────────────────────────────────
# Policy cache: session_id → (Policy, mtime of AGENTS.md)
# Avoids recompiling Policy from AGENTS.md on every hook call
_policy_cache: Dict[str, tuple[Policy, float]] = {}

# Session config cache: config_path → (config_dict, mtime)
# Avoids re-parsing .ystar_session.json on every hook call
_session_cache: Dict[str, tuple[Dict[str, Any], float]] = {}

# 缓存：避免每次 hook 都重建 omission adapter
_omission_cache_key: Optional[str] = None

# AGENTS.md mtime cache: avoid repeated stat() during I/O storms (A025-E1 fix)
# Key: agents_md_path, Value: (last_check_time, cached_mtime)
_agents_md_mtime_cache: Dict[str, tuple[float, float]] = {}


def _load_session_config_cached() -> Optional[Dict[str, Any]]:
    """
    Load session config with mtime-based caching.

    Task 2: Add session level cache to avoid re-parsing .ystar_session.json
    on every hook call in the same session.
    """
    from pathlib import Path

    # Find .ystar_session.json in cwd or home
    dirs = [os.getcwd(), str(Path.home())]
    cfg_path = None
    for d in dirs:
        p = Path(d) / ".ystar_session.json"
        if p.exists():
            cfg_path = str(p)
            break

    if not cfg_path:
        return None

    # Check cache
    try:
        current_mtime = os.path.getmtime(cfg_path)
        if cfg_path in _session_cache:
            cached_cfg, cached_mtime = _session_cache[cfg_path]
            if current_mtime == cached_mtime:
                return cached_cfg  # Return cached config

        # Load and cache (call the original uncached function)
        cfg = _load_session_config()
        if cfg:
            _session_cache[cfg_path] = (cfg, current_mtime)
        return cfg
    except Exception:
        # Fall back to uncached load
        return _load_session_config()


def _get_or_build_policy(agents_md_path: Optional[str] = None) -> Optional[Policy]:
    """
    Get Policy from cache or build from AGENTS.md with mtime-based caching.

    Task 2: Session-level Policy cache to avoid recompiling on every hook call.

    Cache key: agents_md_path (normalized absolute path)
    Cache invalidation: when AGENTS.md mtime changes

    Returns:
        Policy object, or None if AGENTS.md doesn't exist
    """
    from pathlib import Path

    # Determine AGENTS.md path
    if agents_md_path is None:
        agents_md_path = os.path.join(os.getcwd(), "AGENTS.md")

    # Normalize to absolute path for consistent cache key
    agents_md_path = os.path.abspath(agents_md_path)

    # Check if file exists
    if not os.path.exists(agents_md_path):
        return None

    # Check cache with I/O storm mitigation (A025-E1)
    # Only stat() AGENTS.md once per second to avoid directory lock contention
    try:
        import time
        now = time.time()

        # Fast path: use cached mtime if checked <1s ago
        if agents_md_path in _agents_md_mtime_cache:
            last_check, cached_mtime = _agents_md_mtime_cache[agents_md_path]
            if now - last_check < 1.0:  # Checked within last second
                if agents_md_path in _policy_cache:
                    cached_policy, policy_cached_mtime = _policy_cache[agents_md_path]
                    if cached_mtime == policy_cached_mtime:
                        return cached_policy

        # Slow path: actually stat the file
        current_mtime = os.path.getmtime(agents_md_path)
        _agents_md_mtime_cache[agents_md_path] = (now, current_mtime)

        if agents_md_path in _policy_cache:
            cached_policy, cached_mtime = _policy_cache[agents_md_path]
            if current_mtime == cached_mtime:
                _log.debug("Policy cache HIT for %s", agents_md_path)
                return cached_policy

        # Cache miss or stale — rebuild Policy
        _log.debug("Policy cache MISS for %s, rebuilding", agents_md_path)
        policy = Policy.from_agents_md_multi(agents_md_path)
        _policy_cache[agents_md_path] = (policy, current_mtime)
        return policy

    except Exception as exc:
        _log.warning("Failed to build Policy from %s: %s", agents_md_path, exc)
        return None


def _filter_obligations_by_agent(
    session_cfg: Dict[str, Any],
    contract_dict: dict,
    agent_id: str,
) -> dict:
    """
    根据 obligation_agent_scope 过滤 obligation_timing，
    只保留属于当前 agent 的义务。

    scope 格式：{"rule_id": ["agent_role_name"]}
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

    P0 Performance: 优化后只在首次调用时加载，后续调用直接返回。
    这避免了每次 hook 调用都重新注册 60 条 obligation 规则。

    omission 违规事件同时写入 CIEUStore，形成统一的因果日志。
    """
    global _omission_cache_key

    session_id = session_cfg.get("session_id", "")
    cache_key = f"{session_id}:{agent_id}"
    if cache_key and cache_key == _omission_cache_key:
        _log.debug("Omission setup cache hit for %s", cache_key)
        return   # 同一 session + agent，已经配置过

    _log.debug("Omission setup cache miss, initializing for %s", cache_key)
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
        except Exception as e:
            _log.warning("Failed to parse IntentContract: %s", e)
            contract = None

        # 配置带合约时限的 omission registry
        registry = reset_registry()
        n_builtin_rules = len(registry.all_enabled())
        apply_openclaw_accountability_pack(registry, contract=contract)

        # [P0-INSTRUMENTATION] Log obligation timing configuration
        _log.info("Omission setup: %d builtin rules configured", n_builtin_rules)
        if contract and hasattr(contract, 'obligation_timing'):
            timing_config = getattr(contract, 'obligation_timing', {})
            if timing_config:
                _log.info("Contract obligation_timing: %d entries", len(timing_config))

        # 配置持久化 store
        try:
            from ystar.governance.omission_store import OmissionStore
            store = OmissionStore(db_path=cieu_db.replace(".db", "_omission.db"))
        except Exception as e:
            _log.warning("OmissionStore unavailable, using in-memory fallback: %s", e)
            from ystar.governance.omission_store import InMemoryOmissionStore
            store = InMemoryOmissionStore()

        # ── 关键：把真实的 CIEUStore 传入，让 omission 违规写入统一日志 ──
        try:
            cieu_store = CIEUStore(cieu_db)
        except Exception as e:
            _log.warning("CIEUStore initialization failed: %s", e)
            cieu_store = None

        adapter = create_adapter(store=store, registry=registry,
                                 cieu_store=cieu_store)
        configure_omission_governance(adapter=adapter)

        # ── P0 FIX: Register obligations from contract timing ────────────────
        # Root cause: store was created but nobody added ObligationRecords to it.
        # This caused scan() to return 0 violations → GovernanceLoop produced 0 output.
        try:
            from ystar.governance.omission_models import ObligationRecord, ObligationStatus

            obligation_timing_config = contract_dict.get("obligation_timing", {})
            if obligation_timing_config:
                now = time.time()
                n_registered = 0

                # Map obligation keys to rule IDs (same as accountability_pack.py)
                _KEY_TO_RULE = {
                    "delegation": "rule_a_delegation",
                    "acknowledgement": "rule_b_acknowledgement",
                    "status_update": "rule_c_status_update",
                    "result_publication": "rule_d_result_publication",
                    "upstream_notification": "rule_e_upstream_notification",
                    "escalation": "rule_f_escalation",
                    "closure": "rule_g_closure",
                    "ack": "rule_b_acknowledgement",
                    "complete": "rule_c_status_update",
                    "completion": "rule_c_status_update",
                    "notify": "rule_e_upstream_notification",
                    "close": "rule_g_closure",
                }

                for key, due_within_secs in obligation_timing_config.items():
                    # Map known OpenClaw keys to rule IDs; for custom keys
                    # (e.g. p0_bug_fix, session_boot), use the key directly.
                    rule_id = _KEY_TO_RULE.get(key, key)
                    if rule_id and isinstance(due_within_secs, (int, float)) and due_within_secs > 0:
                        # Get timing from registry (already configured by accountability_pack)
                        rule = registry.get(rule_id)
                        grace = 0.0
                        hard_overdue = due_within_secs
                        if rule:
                            grace = rule.grace_period_secs
                            hard_overdue = rule.hard_overdue_secs or due_within_secs

                        # Create obligation record
                        ob = ObligationRecord(
                            entity_id=session_id,
                            actor_id=agent_id,
                            obligation_type=rule_id,
                            due_at=now + due_within_secs,
                            grace_period_secs=grace,
                            hard_overdue_secs=hard_overdue,
                            status=ObligationStatus.PENDING,
                            notes=f"Initial obligation from contract timing: {key}",
                        )
                        store.add_obligation(ob)
                        n_registered += 1

                if n_registered > 0:
                    _log.info("Registered %d initial obligations from contract timing", n_registered)
        except Exception as e:
            _log.warning("Failed to register initial obligations: %s", e)

        # ── 关键1：启用 obligation-first gate ────────────────────────────
        # OmissionEngine 检测到违规 → InterventionEngine 产生 INTERRUPT_GATE 脉冲
        # → _run_gate_check 在下次 enforce() 时返回 DENY
        try:
            from ystar.domains.openclaw.adapter import (
                configure_intervention_engine, get_omission_adapter
            )
            configure_intervention_engine()
        except Exception as e:
            _log.warning("Failed to configure intervention engine: %s", e)

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

        # ── P0-INSTRUMENTATION: Log setup completion ────────────────────────
        n_rules_final = len(registry.all_enabled())
        n_entities = len(store.list_entities()) if store else 0
        n_obligations = len(store.pending_obligations()) if store else 0

        _log.info("Omission setup complete: %d rules, %d entities, %d obligations",
                  n_rules_final, n_entities, n_obligations)

        # Record CIEU event for observability
        if cieu_store is not None:
            try:
                cieu_store.write({
                    "event_id": str(uuid.uuid4()),
                    "seq_global": int(time.time() * 1_000_000),
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "event_type": "omission_setup_complete",
                    "created_at": time.time(),
                    "decision": "allow",
                    "passed": 1,
                    "params": {
                        "n_rules_enabled": n_rules_final,
                        "n_entities": n_entities,
                        "n_obligations": n_obligations,
                        "n_timing_overrides": n_active,
                        "store_type": store.__class__.__name__,
                    },
                })
            except Exception as e:
                _log.warning("Failed to log omission_setup_complete to CIEU: %s", e)

        _omission_cache_key = cache_key

    except Exception as exc:
        _log.error("Omission engine setup failed: %s", exc)
        # Log failure to CIEU for debugging
        try:
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                fail_store = CIEUStore(cieu_db)
                fail_store.write({
                    "event_id": str(uuid.uuid4()),
                    "seq_global": int(time.time() * 1_000_000),
                    "session_id": session_cfg.get("session_id", ""),
                    "agent_id": agent_id,
                    "event_type": "omission_setup_failed",
                    "created_at": time.time(),
                    "decision": "deny",
                    "passed": 0,
                    "params": {"error": str(exc)},
                })
        except Exception:
            pass


# ── Runtime Contract Merge ────────────────────────────────────────────────


def _apply_runtime_contracts(policy: Policy, who: str) -> None:
    """
    Merge runtime deny/relax contracts into the policy for *who*.

    Loads .ystar_runtime_deny.json and .ystar_runtime_relax.json from cwd,
    merges them with the session contract using merge_contracts(), and
    replaces the contract in the policy object.

    Fail-safe: any error is logged and the original policy is unchanged.
    """
    try:
        from ystar.adapters.runtime_contracts import (
            load_runtime_deny,
            load_runtime_relax,
            merge_contracts,
        )

        deny = load_runtime_deny(os.getcwd())
        relax = load_runtime_relax(os.getcwd())

        if deny is None and relax is None:
            return  # No runtime contracts -- nothing to merge

        session_contract = policy._rules.get(who)
        if session_contract is None:
            return  # No contract for this agent -- skip

        effective = merge_contracts(session_contract, deny, relax)
        policy._rules[who] = effective
        _log.debug("Runtime contracts merged for %s (deny=%s, relax=%s)",
                    who, deny is not None, relax is not None)
    except Exception as exc:
        _log.debug("Runtime contract merge failed (non-critical): %s", exc)


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


# ── Path B Feed ──────────────────────────────────────────────────────────────


def _feed_path_b(
    agent_id: str,
    tool_name: str,
    params: dict,
    result: dict,
    session_id: Optional[str],
) -> None:
    """
    Feed an ExternalObservation to PathBAgent (fail-safe).

    Called after every hook decision (ALLOW or DENY) to give Path B the
    data it needs for metalearning and runtime constraint generation.

    This function MUST NOT affect check_hook()'s return value -- all
    exceptions are caught and logged at debug level.
    """
    try:
        from ystar.adapters.orchestrator import get_orchestrator
        orch = get_orchestrator()
        if orch is None:
            return

        # PathBAgent may not be initialised yet
        path_b = getattr(orch, "_path_b_agent", None)
        if path_b is None:
            return

        from ystar.path_b.path_b_agent import ExternalObservation

        violations = []
        if isinstance(result, dict) and result.get("action") == "block":
            violations = [result]

        obs = ExternalObservation(
            agent_id=agent_id,
            session_id=session_id or "unknown",
            action_type="tool_call",
            params={"tool": tool_name, **(params or {})},
            result=result,
            violations=violations,
        )
        path_b.observe(obs)
    except Exception as e:
        _log.debug("Path B feed failed (non-critical): %s", e)


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
            # Generic path pattern matching for Write/Edit triggers
            # Check if this trigger requires path pattern matching
            scfg = _load_session_config_cached()
            trigger_patterns = None
            if scfg:
                trigger_patterns = scfg.get("trigger_path_patterns", {}).get(
                    trigger.trigger_id)

            # If trigger has path patterns configured, verify file path matches
            if trigger_patterns and tool_name in ("Write", "Edit"):
                file_path = tool_input.get("file_path") or tool_input.get("path") or ""
                if not any(p in file_path for p in trigger_patterns):
                    continue  # Skip this trigger, path doesn't match

            # Special handling for pre_commit_test trigger
            if trigger.trigger_id == "pre_commit_test":
                # Only fire if command contains "git commit"
                command = tool_input.get("command", "")
                if "git commit" not in command:
                    continue
                # Check if pytest was run recently (within last 120 seconds)
                # This is a simplified check - in production would query CIEU DB
                # For now, create the obligation and let omission engine track it

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


# ═══════════════════════════════════════════════════════════════════════
# ARCH-6: handle_hook_event — thin entry point for v2 hook adapter
# ═══════════════════════════════════════════════════════════════════════


def _read_marker_fallback() -> Optional[str]:
    """Read agent identity from marker files, mirroring hook_wrapper v1 lines 167-253.

    Fallback chain: per-session (CLAUDE_SESSION_ID) → per-session (PPID) →
    global newest (scripts/.ystar_active_agent vs repo-root/.ystar_active_agent).

    Returns the marker content string, or None if no marker found.

    Added post-INC-2026-04-23: v2 thin adapter path lacked this chain,
    causing agent to resolve as "agent"/"guest" → session_start_protocol_incomplete
    DENY-all → fail-closed deadlock for ~3 hours.
    """
    _repo_root = os.environ.get("YSTAR_REPO_ROOT", "")
    if not _repo_root:
        # Heuristic: workspace_config or cwd-based detection
        try:
            from ystar.workspace_config import get_labs_workspace
            ws = get_labs_workspace()
            if ws:
                _repo_root = str(ws)
        except Exception:
            pass

    _scripts_dir = os.path.join(_repo_root, "scripts") if _repo_root else ""

    # 1. Per-session marker via CLAUDE_SESSION_ID
    _sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if _sid:
        _sanitized = "".join(c for c in _sid if c.isalnum() or c in "-_")
        if _sanitized:
            for base in [_repo_root, _scripts_dir]:
                if not base:
                    continue
                _path = os.path.join(base, f".ystar_active_agent.{_sanitized}")
                try:
                    content = open(_path, "r", encoding="utf-8").read().strip()
                    if content:
                        _log.debug("[marker-fallback] per-session (%s): '%s'", _sanitized, content)
                        return content
                except FileNotFoundError:
                    pass

    # 2. Per-session marker via PPID
    _ppid = os.environ.get("PPID", "")
    if not _ppid:
        try:
            _ppid = str(os.getppid())
        except Exception:
            _ppid = ""
    if _ppid and _ppid != "1":
        for base in [_repo_root, _scripts_dir]:
            if not base:
                continue
            _path = os.path.join(base, f".ystar_active_agent.ppid_{_ppid}")
            try:
                content = open(_path, "r", encoding="utf-8").read().strip()
                if content:
                    _log.debug("[marker-fallback] per-ppid (%s): '%s'", _ppid, content)
                    return content
            except FileNotFoundError:
                pass

    # 3. Global marker — pick newest of repo-root and scripts/ variants
    _candidates = []
    for base in [_repo_root, _scripts_dir]:
        if not base:
            continue
        _path = os.path.join(base, ".ystar_active_agent")
        try:
            _st = os.stat(_path)
            content = open(_path, "r", encoding="utf-8").read().strip()
            if content:
                _candidates.append((_st.st_mtime, content))
        except FileNotFoundError:
            pass
    if _candidates:
        _candidates.sort(reverse=True)
        return _candidates[0][1]

    return None


def _load_rules_from_dir(rules_dir: str) -> None:
    """
    Load router rules from a directory of .py files.

    Delegates to ``RouterRegistry.load_rules_dir`` (ARCH-4 canonical).
    This thin wrapper exists so ``handle_hook_event`` callers don't change.
    """
    from ystar.governance.router_registry import get_default_registry

    get_default_registry().load_rules_dir(rules_dir)


def handle_hook_event(
    payload: Dict[str, Any],
    *,
    rules_dir: Optional[str] = None,
    policy: Optional[Policy] = None,
) -> Dict[str, Any]:
    """
    Unified hook entry point for the v2 thin adapter (ARCH-6).

    This function:
      1. Optionally loads router rules from ``rules_dir``
      2. Runs matching router rules (Layer 3) before check_hook
      3. If any rule returns non-allow, returns that decision immediately
      4. Otherwise falls through to check_hook (Layers 2+1)

    Args:
        payload:    Raw hook payload dict (OpenClaw / Claude Code format).
        rules_dir:  Path to directory of .py files containing RouterRule
                    definitions.  Each file should export
                    ``RULES = [RouterRule(...)]``.
                    If None, no external rules are loaded (built-in rules only).
        policy:     Optional Policy object.  Passed through to check_hook.

    Returns:
        Hook response dict.  ``{}`` means allow,
        ``{"hookSpecificOutput": ...}`` means deny/redirect.
    """
    from ystar.governance.router_registry import get_default_registry

    # ── INC-2026-04-23: Marker fallback chain (ported from hook_wrapper v1) ──
    # When Claude Code sends agent_id="" and agent_type="agent" (root process
    # defaults), _detect_agent_id falls through to priority 7 (marker files)
    # or returns "guest".  The v1 path in hook_wrapper.py (lines 167-253)
    # pre-injects the marker into payload.agent_id so priority 1 resolves
    # correctly.  Without this, the session_start_protocol_incomplete rule
    # sees who="agent"/"guest" and DENY-all → fail-closed deadlock.
    # See: reports/incidents/2026-04-23-hook-fail-closed-deadlock.md
    #
    # CZL-SPAWN-PPID-MARKER-FIX (2026-04-24): Check agent_type FIRST.
    # For subagents, Claude Code sets agent_type to the definition name
    # (e.g. "Leo-Kernel"). This is authoritative and must take priority
    # over stale ppid markers that resolve to "ceo".
    _v2_aid = payload.get("agent_id", "")
    _v2_atype = payload.get("agent_type", "")

    # Priority 0: agent_type from payload (subagent identity)
    _v2_resolved = False
    if _v2_atype and _v2_atype not in ("", "agent", None):
        try:
            from ystar.adapters.identity_detector import _map_agent_type
            _v2_mapped = _map_agent_type(_v2_atype)
            if _v2_mapped and _v2_mapped not in ("agent", "guest"):
                payload["agent_id"] = _v2_mapped
                _v2_resolved = True
                _log.info("[v2-ppid-fix] Subagent identity from agent_type='%s' -> '%s'",
                         _v2_atype, _v2_mapped)
        except Exception as _v2_map_exc:
            _log.warning("[v2-ppid-fix] Failed to map agent_type: %s", _v2_map_exc)

    # Priority 1: marker fallback (for root process only)
    if not _v2_resolved and (not _v2_aid or _v2_aid == "agent"):
        # Try marker fallback chain: per-session → per-ppid → global newest
        _v2_marker = _read_marker_fallback()
        if _v2_marker and _v2_marker != "agent":
            payload["agent_id"] = _v2_marker
            if _v2_atype in ("", "agent", None):
                payload.pop("agent_type", None)
            _log.info("[v2-marker] Payload agent_id overridden to '%s' from marker fallback", _v2_marker)

    # ── CEO Constitutional Deny (ported from hook_wrapper v1) ────────────
    # CEO must not write directly to Y-star-gov product source.
    # This enforcement was previously only in hook_wrapper.py's v1 slow path;
    # v2 thin adapter must replicate it before router rules or check_hook.
    # LABS_ALIAS: CEO identity aliases loaded from session config
    from ystar.adapters.identity_detector import _load_alias_map as _la
    _ceo_aliases = tuple(k for k, v in _la().items() if v == "ceo")
    _CEO_IDENTITIES = ("ceo",) + _ceo_aliases
    _tool = payload.get("tool_name", "")
    _agent = payload.get("agent_id", "")
    if _tool in ("Write", "Edit", "NotebookEdit") and _agent in _CEO_IDENTITIES:
        _fp = payload.get("tool_input", {}).get("file_path", "")
        _ceo_deny_patterns = ["Y-star-gov/ystar/", "Y-star-gov\\ystar\\", "/src/ystar/"]
        for _dp in _ceo_deny_patterns:
            if _dp in _fp:
                _log.warning("DENY CEO constitutional (v2): %s → %s", _agent, _fp)
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"[Y*gov CONSTITUTIONAL] CEO禁止直接写代码。"
                            f"文件 {_fp} 属于CTO管辖范围。请派工程师执行。"
                        ),
                    }
                }

    # Register built-in rules (idempotent — already-registered rules skipped)
    try:
        from ystar.rules.break_glass import register_break_glass_rule
        register_break_glass_rule()
    except Exception:
        pass  # Graceful degradation if rules package unavailable
    try:
        from ystar.rules.next_action_inject import register_next_action_rule
        register_next_action_rule()
    except Exception:
        pass
    try:
        from ystar.rules.per_rule_detectors import register_builtin_rules
        register_builtin_rules()
    except Exception:
        pass

    # Load external rules (idempotent — already-registered rules are skipped)
    if rules_dir:
        _load_rules_from_dir(rules_dir)

    # Run router rules (Layer 3) — if any match and return non-allow, short-circuit
    registry = get_default_registry()
    matches = registry.find_matching_rules(payload)
    if matches:
        results = registry.execute_rules(payload, rules=matches, stop_on_non_allow=True)
        for rr in results:
            if rr.decision == "deny":
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"[Y*gov router:{rr.rule_id}] {rr.message}"
                        ),
                    }
                }
            elif rr.decision == "redirect":
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"[Y*gov REDIRECT:{rr.rule_id}] {rr.message}"
                        ),
                    }
                }
            elif rr.decision == "allow" and rr.rule_id == "builtin.break_glass":
                # Break-glass (ARCH-5): bypass ALL enforcement including check_hook
                return {}
            elif rr.decision == "inject":
                # Inject context — proceed to check_hook; injected context
                # is logged for downstream consumption.
                _log.info(
                    "Router inject from %s: %s",
                    rr.rule_id, rr.injected_context[:80],
                )

    # Fall through to existing check_hook (Layer 2 + Layer 1)
    return check_hook(payload, policy=policy)


_avoidance_phrases_cache: list = None  # type: ignore[assignment]


def _load_avoidance_phrases() -> list:
    """Load avoidance-phrases from workspace yaml config.

    This is intentionally separate from _load_deny_phrases():
    - deny_phrases.yaml: explicit deploying-workspace hard deny list
    - avoidance_phrases.yaml: softer legacy/config-driven phrase list

    Returns empty list if workspace config is unavailable, workspace is None,
    yaml file does not exist, or yaml parsing fails.
    """
    global _avoidance_phrases_cache
    if _avoidance_phrases_cache is not None:
        return _avoidance_phrases_cache

    try:
        from ystar.workspace_config import get_labs_workspace
        ws = get_labs_workspace()
        if ws is None:
            _avoidance_phrases_cache = []
            return _avoidance_phrases_cache

        yaml_path = ws / "knowledge" / "shared" / "avoidance_phrases.yaml"
        if not yaml_path.is_file():
            yaml_path = ws / "governance" / "avoidance_phrases.yaml"
        if not yaml_path.is_file():
            _avoidance_phrases_cache = []
            return _avoidance_phrases_cache

        import yaml as _yaml
        data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        _avoidance_phrases_cache = data.get("phrases", []) if isinstance(data, dict) else []
        return _avoidance_phrases_cache
    except Exception:
        _avoidance_phrases_cache = []
        return _avoidance_phrases_cache

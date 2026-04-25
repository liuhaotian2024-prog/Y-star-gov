# Layer: Foundation
"""
ystar.adapters.identity_detector  —  Agent Identity Detection  v0.48.0
========================================================================

Agent 身份检测模块，从 hook.py 拆分而来（P1-5）。

职责：
  - 检测当前操作的 agent 身份（_detect_agent_id）
  - 加载 session config（_load_session_config）

从多个来源检测 agent_id 优先级：
  1. hook_payload 里的 agent_id 字段
  2. 环境变量 YSTAR_AGENT_ID
  3. 环境变量 CLAUDE_AGENT_NAME
  4. .ystar_active_agent 文件
  5. 回退到 "agent"
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_log = logging.getLogger("ystar.identity")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*identity] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.WARNING)

# ── P0 Performance: Session config cache ────────────────────────────────
# hook_wrapper.py can inject cached session config here to avoid re-reading
# .ystar_session.json on every hook call.
_SESSION_CONFIG_CACHE: Optional[Dict[str, Any]] = None


# ── Agent Type → Governance ID Mapping ──────────────────────────────────
# Agent type → governance ID mapping
# Claude Code agents use "Name-Role" format, governance uses short IDs
# Note: Replace placeholder names with your organization's agent names
_AGENT_TYPE_MAP = {
    # C-suite agents (generic naming)
    "Agent-CEO": "ceo",
    "Agent-CTO": "cto",
    "Agent-CMO": "cmo",
    "Agent-CFO": "cfo",
    "Agent-CSO": "cso",
    "Agent-Secretary": "secretary",
    # Engineering agents (generic naming)
    "Agent-Kernel": "eng-kernel",
    "Agent-Platform": "eng-platform",
    "Agent-Governance": "eng-governance",
    "Agent-Domains": "eng-domains",
    "Agent-Research": "jinjin",
    "Agent-Security": "eng-security",
    "Agent-ML": "eng-ml",
    "Agent-Performance": "eng-perf",
    "Agent-Compliance": "eng-compliance",

    # Y* Bridge Labs canonical staff aliases (backward compatibility)
    "Samantha-Secretary": "secretary",
    "Maya-Governance": "eng-governance",
    "Ryan-Platform": "eng-platform",
    "Ethan-CTO": "cto",
    "Leo-Kernel": "eng-kernel",
    "Jordan-Domains": "eng-domains",
    "Alex-Security": "eng-security",
    "Priya-ML": "eng-ml",
    "Carlos-Performance": "eng-perf",
    "Elena-Compliance": "eng-compliance",

    # Legacy format support (role IDs)
    "ystar-ceo": "ceo",
    "ystar-cto": "cto",
    "ystar-cmo": "cmo",
    "ystar-cfo": "cfo",
    "ystar-cso": "cso",
    "eng-kernel": "eng-kernel",
    "eng-platform": "eng-platform",
    "eng-governance": "eng-governance",
    "eng-domains": "eng-domains",
    "eng-data": "eng-data",
    "eng-security": "eng-security",
    "eng-ml": "eng-ml",
    "eng-perf": "eng-perf",
    "eng-compliance": "eng-compliance",
    # Organization-specific agent names (e.g., "Alice-CTO", "Bob-Kernel")
    # should be injected via .ystar_session.json "agent_aliases" field,
    # NOT hardcoded here. See _load_alias_map() for the runtime injection point.
}


def _load_alias_map() -> Dict[str, str]:
    """
    CZL-ARCH-1 (2026-04-18): Load agent aliases from .ystar_session.json.

    Returns dict of custom_name -> canonical_id. Gracefully returns {} if
    session file missing, unreadable, or lacks 'agent_aliases' field.
    """
    try:
        repo_root = os.environ.get("YSTAR_REPO_ROOT", "")
        if repo_root:
            session_path = Path(repo_root) / ".ystar_session.json"
        else:
            session_path = Path(".ystar_session.json")
        if not session_path.exists():
            return {}
        with open(session_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        aliases = cfg.get("agent_aliases", {})
        if isinstance(aliases, dict):
            return aliases
        _log.warning(".ystar_session.json agent_aliases is not a dict, ignoring")
        return {}
    except Exception as e:
        _log.debug("Failed to load agent_aliases: %s", e)
        return {}


def _map_agent_type(agent_type: str) -> str:
    """
    Map Claude Code agent_type to Y*gov governance ID.

    CZL-ARCH-1 (2026-04-18) resolution chain:
    1. Exact match in _AGENT_TYPE_MAP
    2. Session-config agent_aliases override
    3. Case-insensitive match after normalizing separators
    4. Fuzzy match via difflib.get_close_matches (cutoff 0.75)
    5. Log warning + return as-is (caller decides final fallback)
    """
    if not agent_type:
        return agent_type
    # 1. Exact match (built-in map)
    if agent_type in _AGENT_TYPE_MAP:
        return _AGENT_TYPE_MAP[agent_type]
    # 2. Session-config alias override
    aliases = _load_alias_map()
    if agent_type in aliases:
        return aliases[agent_type]
    # 3. Case-insensitive, normalize separators (space/underscore -> hyphen)
    lower = agent_type.lower().replace("ystar-", "").replace(" ", "-").replace("_", "-")
    for key, val in _AGENT_TYPE_MAP.items():
        if key.lower().replace(" ", "-").replace("_", "-") == lower:
            return val
    for key, val in aliases.items():
        if key.lower().replace(" ", "-").replace("_", "-") == lower:
            return val
    # 4. Fuzzy match (difflib) against combined key set
    try:
        import difflib
        candidates = list(_AGENT_TYPE_MAP.keys()) + list(aliases.keys())
        matches = difflib.get_close_matches(agent_type, candidates, n=1, cutoff=0.75)
        if matches:
            matched_key = matches[0]
            resolved = _AGENT_TYPE_MAP.get(matched_key) or aliases.get(matched_key)
            if resolved:
                _log.warning(
                    "Fuzzy-matched agent_type '%s' -> '%s' -> '%s'",
                    agent_type, matched_key, resolved,
                )
                return resolved
    except Exception as e:
        _log.debug("Fuzzy match failed: %s", e)
    # 5. No match — log warning + return as-is
    _log.warning("Unknown agent_type '%s' — not in map/aliases/fuzzy, returning as-is", agent_type)
    return agent_type


def _detect_agent_id(hook_payload: Dict[str, Any]) -> str:
    """
    从多个来源检测当前操作的 agent 身份。

    优先级（AMENDMENT-015 Layer 1 更新）：
    1. hook_payload 里的 agent_id 字段
    1.5. hook_payload 里的 agent_type 字段 (Claude Code subagents)
    2. 环境变量 YSTAR_AGENT_ID
    3. 环境变量 CLAUDE_AGENT_NAME（Claude Code 可能设置）
    4. session_id 提取（格式 "agentName_sessionId"）
    5. transcript_path 提取
    6. .ystar_session.json (single source of truth, reads agent_stack)
    7. DEPRECATED: .ystar_active_agent 文件（向后兼容，优先级降至最低）
    8. 回退到 "guest" (CZL-ARCH-1, 2026-04-18 — read-only default, replaces "agent")
    """
    # 1. payload.agent_id — CZL-ARCH-1-followup (2026-04-18): map through
    # _map_agent_type so literal pushed names (e.g. alias-based agent names)
    # resolve to canonical governance IDs ("eng-platform", "eng-kernel")
    # before being returned. Skip if mapping degenerates to generic "agent"
    # so we continue to priority 2+ like the 1.5 filter.
    aid = hook_payload.get("agent_id", "")
    if aid and aid != "agent":
        mapped = _map_agent_type(aid)
        if mapped and mapped != "agent":
            _log.debug("Agent ID from payload.agent_id: %s (mapped from %s)", mapped, aid)
            return mapped
        _log.debug("payload.agent_id '%s' mapped to generic '%s' — continuing detection", aid, mapped)

    # 1.5 payload: agent_type (Claude Code injects this for subagents)
    # CZL-P1-b Fix: If _map_agent_type returns "agent" (generic/unknown),
    # do NOT early return — continue to priority 3+ for better detection.
    agent_type = hook_payload.get("agent_type", "")
    if agent_type:
        mapped = _map_agent_type(agent_type)
        if mapped and mapped != "agent":
            _log.debug("Agent ID from payload.agent_type: %s (mapped from %s)", mapped, agent_type)
            return mapped
        _log.debug("payload.agent_type '%s' mapped to generic '%s' — continuing detection", agent_type, mapped)

    # 2. env: YSTAR_AGENT_ID
    aid = os.environ.get("YSTAR_AGENT_ID", "")
    if aid:
        _log.debug("Agent ID from YSTAR_AGENT_ID env: %s", aid)
        return aid

    # 3. env: CLAUDE_AGENT_NAME
    aid = os.environ.get("CLAUDE_AGENT_NAME", "")
    if aid:
        _log.debug("Agent ID from CLAUDE_AGENT_NAME env: %s", aid)
        return aid

    # 4. session_id extraction (format: "agentName_sessionId")
    session_id = hook_payload.get("session_id", "")
    if session_id and "_" in session_id:
        parts = session_id.split("_", 1)
        if parts[0] and parts[0] != "agent":
            _log.debug("Agent ID extracted from session_id: %s (from %s)", parts[0], session_id)
            return parts[0]
        else:
            _log.debug("session_id present but no agent name extracted: %s", session_id)

    # 5. transcript_path extraction
    transcript_path = hook_payload.get("transcript_path", "")
    if transcript_path:
        # Example: /path/to/agents/ceo/transcript.md or .claude/agents/cto.md
        path_obj = Path(transcript_path)
        # Try parent directory name first
        parent_name = path_obj.parent.name
        if parent_name and parent_name not in ["agents", ".", "", "claude"]:
            _log.debug("Agent ID extracted from transcript_path parent: %s (from %s)", parent_name, transcript_path)
            return parent_name
        # Try filename without extension
        stem = path_obj.stem
        if stem and stem != "transcript" and stem != "agent":
            _log.debug("Agent ID extracted from transcript_path stem: %s (from %s)", stem, transcript_path)
            return stem
        _log.debug("transcript_path present but no agent name extracted: %s", transcript_path)

    # 6. session config (Layer 1: single source of truth per AMENDMENT-015)
    # AMENDMENT-016: Resilient fallback — schema validation errors should not crash identity detection
    try:
        from ystar.session import current_agent
        agent_from_session = current_agent()
        if agent_from_session != "agent":
            _log.debug("Agent ID from session config: %s", agent_from_session)
            return agent_from_session
    except ValueError as e:
        # Schema validation errors are non-fatal — fall through to next priority
        _log.warning("Session config schema validation failed (non-fatal): %s", str(e)[:100])
    except Exception as e:
        _log.debug("Failed to read agent from session config: %s", e)

    # 7. DEPRECATED: marker file (.ystar_active_agent)
    # Kept for backward compatibility during migration, but session config takes precedence
    # AMENDMENT-016: Check both repo root and scripts/ subdirectory, map agent types
    # CZL-P1-b Fix: Use absolute paths via YSTAR_REPO_ROOT env when available.
    # When not set, fall back to cwd-relative paths (preserves backward compat + test isolation).
    #
    # CZL-MARKER-PER-SESSION-ISOLATION (2026-04-19): Check per-session marker
    # files FIRST (.ystar_active_agent.<session_id>), then fall back to global.
    # This prevents N concurrent sub-agents from seeing each other's identity.
    _repo_root = os.environ.get("YSTAR_REPO_ROOT", "")
    _marker_candidates: list = []

    # Per-session markers (highest priority within marker-file detection)
    _session_id_for_marker = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if _session_id_for_marker:
        _sanitized_sid = "".join(c for c in _session_id_for_marker if c.isalnum() or c in "-_")
        if _sanitized_sid:
            if _repo_root:
                _marker_candidates.append(Path(_repo_root) / f".ystar_active_agent.{_sanitized_sid}")
                _marker_candidates.append(Path(_repo_root) / "scripts" / f".ystar_active_agent.{_sanitized_sid}")
            else:
                _marker_candidates.append(Path(f".ystar_active_agent.{_sanitized_sid}"))
                _marker_candidates.append(Path("scripts") / f".ystar_active_agent.{_sanitized_sid}")

    # PPID-based per-session markers
    _ppid_for_marker = os.environ.get("PPID", "")
    if not _ppid_for_marker:
        try:
            _ppid_for_marker = str(os.getppid())
        except Exception:
            _ppid_for_marker = ""
    if _ppid_for_marker and _ppid_for_marker != "1":
        _ppid_suffix = f"ppid_{_ppid_for_marker}"
        if _repo_root:
            _marker_candidates.append(Path(_repo_root) / f".ystar_active_agent.{_ppid_suffix}")
            _marker_candidates.append(Path(_repo_root) / "scripts" / f".ystar_active_agent.{_ppid_suffix}")
        else:
            _marker_candidates.append(Path(f".ystar_active_agent.{_ppid_suffix}"))
            _marker_candidates.append(Path("scripts") / f".ystar_active_agent.{_ppid_suffix}")

    # Global markers (backward compat, lowest priority)
    if _repo_root:
        _marker_candidates.append(Path(_repo_root) / ".ystar_active_agent")
        _marker_candidates.append(Path(_repo_root) / "scripts" / ".ystar_active_agent")
    else:
        _marker_candidates.append(Path(".ystar_active_agent"))
        _marker_candidates.append(Path("scripts") / ".ystar_active_agent")

    for marker_path in _marker_candidates:
        if marker_path.exists():
            try:
                content = marker_path.read_text(encoding="utf-8").strip()
                if content:
                    # Map agent type (e.g., alias-based names -> canonical IDs via session config)
                    mapped = _map_agent_type(content)
                    if mapped and mapped != "agent":
                        _log.warning("Agent ID from DEPRECATED marker file %s (use session config instead): %s (mapped from %s)", marker_path, mapped, content)
                        return mapped
                    _log.debug("Marker file %s content '%s' mapped to generic '%s' -- skipping", marker_path, content, mapped)
            except Exception as e:
                _log.warning("Failed to read agent marker file %s: %s", marker_path, e)

    # CZL-ARCH-1 (2026-04-18): Final fallback returns "guest" instead of "agent".
    # Rationale: "agent" in the policy space means "unknown/default" which historically
    # triggered blanket deny → recursive lock-death with no escape hatch. "guest" should
    # be wired in the policy as read-only (Read/Grep/Glob allowed, Bash/Write/Edit/Agent
    # denied), giving the system a non-destructive default identity that lets agents at
    # least observe state and find their way out of identity ambiguity.
    _log.warning("All agent ID detection methods failed, falling back to 'guest' (read-only)")
    return "guest"


def _load_session_config(search_dirs: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """
    查找并加载 .ystar_session.json。
    ystar init 完成后写入此文件，check_hook 启动时自动读取。

    P0 Performance: 支持从 _SESSION_CONFIG_CACHE 读取（hook_wrapper 注入）。
    """
    global _SESSION_CONFIG_CACHE

    # Check cache first (injected by hook_wrapper.py for performance)
    if _SESSION_CONFIG_CACHE is not None:
        _log.debug("Session config loaded from in-memory cache")
        return _SESSION_CONFIG_CACHE

    # CZL-P1-b Fix: Prefer YSTAR_REPO_ROOT env for absolute path resolution.
    # Fall back to os.getcwd() for backward compat (tests, legacy setups).
    _repo_root = os.environ.get("YSTAR_REPO_ROOT", "")
    _default_dirs = []
    if _repo_root:
        _default_dirs.append(_repo_root)
    else:
        _default_dirs.append(os.getcwd())
    _default_dirs.append(str(Path.home()))
    dirs = search_dirs or _default_dirs
    for d in dirs:
        p = Path(d) / ".ystar_session.json"
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                _log.warning("Failed to parse session config from %s: %s", p, e)
    return None


__all__ = [
    "_detect_agent_id",
    "_load_session_config",
    "_map_agent_type",
    "_AGENT_TYPE_MAP",
]

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
_AGENT_TYPE_MAP = {
    "Aiden-CEO": "ceo",
    "Ethan-CTO": "cto",
    "Sofia-CMO": "cmo",
    "Marco-CFO": "cfo",
    "Zara-CSO": "cso",
    "Samantha-Secretary": "secretary",
    "Leo-Kernel": "eng-kernel",
    "Ryan-Platform": "eng-platform",
    "Maya-Governance": "eng-governance",
    "Jordan-Domains": "eng-domains",
    "Jinjin-Research": "jinjin",
    # Legacy format support
    "ystar-ceo": "ceo",
    "ystar-cto": "cto",
    "ystar-cmo": "cmo",
    "ystar-cfo": "cfo",
    "ystar-cso": "cso",
    "eng-kernel": "eng-kernel",
    "eng-platform": "eng-platform",
    "eng-governance": "eng-governance",
    "eng-domains": "eng-domains",
}


def _map_agent_type(agent_type: str) -> str:
    """Map Claude Code agent_type to Y*gov governance ID."""
    if agent_type in _AGENT_TYPE_MAP:
        return _AGENT_TYPE_MAP[agent_type]
    # Fallback: try lowercase, strip common prefixes
    lower = agent_type.lower().replace("ystar-", "")
    for key, val in _AGENT_TYPE_MAP.items():
        if key.lower() == lower:
            return val
    return agent_type  # Return as-is if no mapping found


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
    8. 回退到 "agent"
    """
    # 1. payload
    aid = hook_payload.get("agent_id", "")
    if aid and aid != "agent":
        _log.debug("Agent ID from payload.agent_id: %s", aid)
        return aid

    # 1.5 payload: agent_type (Claude Code injects this for subagents)
    agent_type = hook_payload.get("agent_type", "")
    if agent_type:
        mapped = _map_agent_type(agent_type)
        _log.debug("Agent ID from payload.agent_type: %s (mapped from %s)", mapped, agent_type)
        return mapped

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
    try:
        from ystar.session import current_agent
        agent_from_session = current_agent()
        if agent_from_session != "agent":
            _log.debug("Agent ID from session config: %s", agent_from_session)
            return agent_from_session
    except Exception as e:
        _log.debug("Failed to read agent from session config: %s", e)

    # 7. DEPRECATED: marker file (.ystar_active_agent)
    # Kept for backward compatibility during migration, but session config takes precedence
    marker = Path(".ystar_active_agent")
    if marker.exists():
        try:
            content = marker.read_text(encoding="utf-8").strip()
            if content:
                _log.warning("Agent ID from DEPRECATED marker file (use session config instead): %s", content)
                return content
        except Exception as e:
            _log.warning("Failed to read agent marker file: %s", e)

    _log.debug("All agent ID detection methods failed, falling back to 'agent'")
    return "agent"


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

    dirs = search_dirs or [os.getcwd(), str(Path.home())]
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

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
        except Exception as e:
            _log.warning("Failed to read agent marker file: %s", e)

    return "agent"


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
            except Exception as e:
                _log.warning("Failed to parse session config from %s: %s", p, e)
    return None


__all__ = [
    "_detect_agent_id",
    "_load_session_config",
]

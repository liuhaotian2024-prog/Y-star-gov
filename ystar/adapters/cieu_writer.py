# Layer: Foundation
"""
ystar.adapters.cieu_writer  —  CIEU Recording  v0.48.0
========================================================

CIEU 写入模块，从 hook.py 拆分而来（P1-5）。

职责：
  - 写入 CIEU 五元组记录（_write_cieu）
  - 写入 HOOK_BOOT 记录（_write_boot_record）

设计原则：
  - 所有写入操作静默失败（不影响执行路径）
  - 记录 Context, Intent, Execution, Utility, Outcome
  - HOOK_BOOT 记录证明 hook 已激活（Directive #024）
"""
from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ystar.session import PolicyResult

_log = logging.getLogger("ystar.cieu")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*cieu] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.WARNING)


# ── CIEU Boot Record ─────────────────────────────────────────────────────
# Directive #024: 第一次被调用时写一条 HOOK_BOOT 记录
# 如果 CIEU 里没有 HOOK_BOOT → hook 从未被激活

_HOOK_BOOTED: bool = False


def _write_boot_record(who: str, session_id: str, cieu_db: str) -> None:
    """第一次hook调用时写一条boot记录，证明hook在运行。"""
    global _HOOK_BOOTED
    if _HOOK_BOOTED:
        return
    _HOOK_BOOTED = True
    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(cieu_db)
        store.write_dict({
            "session_id":    session_id,
            "agent_id":      who,
            "event_type":    "HOOK_BOOT",
            "decision":      "info",
            "passed":        True,
            "violations":    [],
            "params":        {"boot_time": time.time(), "message": "Y*gov hook activated"},
            "contract_hash": "",
            "evidence_grade": "ops",  # [P2-3] HOOK_BOOT 是运维诊断事件
        })
        _log.info("HOOK_BOOT record written — CIEU is alive")
    except Exception as e:
        _log.error("Failed to write HOOK_BOOT record: %s", e)


def _write_cieu(
    who: str, tool_name: str, params: dict,
    result: "PolicyResult", session_id: str,
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
            "evidence_grade": "decision",  # [P2-3] hook allow/deny 是决策级证据
        })

        # [Closure-1] CIEU → memory.db event bridge
        _trigger_memory_ingest(who, tool_name, params, result, session_id, cieu_db)

    except Exception as e:
        _log.error("CIEU write failed (non-fatal): %s", e, exc_info=True)


def _write_session_lifecycle(
    event_type: str,
    who: str,
    session_id: str,
    cieu_db: str,
    extra_params: dict | None = None,
) -> None:
    """Write a session-lifecycle CIEU event (Board 2026-04-11).

    Valid event_type values:
      session_start, session_close, continuation_loaded,
      obligation_check, boot_protocol_completed.

    Silent-fail like _write_cieu — must never break the execution path.
    """
    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(cieu_db)
        store.write_dict({
            "session_id":    session_id,
            "agent_id":      who,
            "event_type":    event_type,
            "decision":      "info",
            "passed":        True,
            "violations":    [],
            "params":        {"ts": time.time(), **(extra_params or {})},
            "contract_hash": "",
            "evidence_grade": "session_lifecycle",
        })
        _log.info("Session lifecycle event written: %s", event_type)
    except Exception as e:
        _log.error("session lifecycle write failed (non-fatal): %s", e)


def _resolve_memory_db(cieu_db: str) -> str:
    """
    Resolve memory.db path from CIEU db path.

    Convention: .ystar_cieu.db → .ystar_memory.db (same directory)
    """
    from pathlib import Path
    cieu_path = Path(cieu_db)
    return str(cieu_path.parent / ".ystar_memory.db")


def _trigger_memory_ingest(
    who: str, tool_name: str, params: dict,
    result: "PolicyResult", session_id: str,
    cieu_db: str,
) -> None:
    """
    Trigger memory ingest based on CIEU event (Closure-1).

    Fail-open: all exceptions are caught and logged, never raised.
    """
    try:
        from ystar.memory.ingest import enqueue

        # Build event dict matching ingest.should_ingest schema
        event = {
            "event_type": tool_name,
            "decision": "allow" if result.allowed else "deny",
            "violations": [
                {
                    "dimension": v.dimension,
                    "severity": getattr(v, "severity", 0.0),
                    "message": v.message,
                }
                for v in (result.violations or [])
            ],
            "params": params,
            "agent_id": who,
            "session_id": session_id,
            "cieu_ref": None,  # Could be rowid from store.write_dict if it returns one
        }

        memory_db_path = _resolve_memory_db(cieu_db)
        enqueue(event, memory_db_path)

    except Exception as e:
        # Fail-open: memory ingest failure should never break the CIEU write path
        _log.debug("Memory ingest trigger failed (non-fatal): %s", e)


__all__ = [
    "_write_boot_record",
    "_write_cieu",
    "_write_session_lifecycle",
]

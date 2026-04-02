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
        })
    except Exception as e:
        _log.error("CIEU write failed (non-fatal): %s", e, exc_info=True)


__all__ = [
    "_write_boot_record",
    "_write_cieu",
]

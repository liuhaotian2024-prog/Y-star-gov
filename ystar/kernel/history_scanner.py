# ystar/kernel/history_scanner.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
ystar.kernel.history_scanner  —  通用历史行为扫描入口  v0.41.0
==============================================================

核心层职责：按优先级尝试各种历史来源，返回 ToolCallRecord 列表。
调用方（CLI / 测试 / 其他工具）只需调 scan_history()，
不需要知道数据来自哪个 adapter。

三个判断问题验证归属：
  Q1 给 LangChain 用要改吗？  → 不用改（框架无关的调度逻辑）→ 核心层 ✓
  Q2 需要记住历史吗？          → 不需要 → 核心层 ✓
  Q3 翻译格式还是判断对错？    → 调度/聚合 → 核心层 ✓

扩展方式：
  加新框架只需在 adapters/ 里加一个新 scanner，
  然后在 _try_scanners() 里加一行。
  核心层、治理层、CLI 不需要改动。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from .retroactive import ToolCallRecord


# ── 扫描来源枚举 ──────────────────────────────────────────────────────────

SOURCES = {
    "claude_code": "Claude Code（~/.claude/projects/）",
    "openclaw":    "OpenClaw 日志",
    "jsonl":       "通用 JSONL 文件",
}


# ── 各 adapter 的扫描尝试函数 ─────────────────────────────────────────────

def _try_claude_code(
    days_back: int,
    max_records: int,
) -> Tuple[List[ToolCallRecord], str]:
    """尝试扫描 Claude Code 历史会话。"""
    try:
        from ystar.adapters.claude_code_scanner import (
            find_claude_projects_dir, scan_sessions
        )
        projects_dir = find_claude_projects_dir()
        if projects_dir is None:
            return [], ""
        records = scan_sessions(projects_dir, days_back=days_back,
                                max_records=max_records)
        if records:
            return records, f"claude_code:{projects_dir}"
        return [], ""
    except ImportError:
        return [], ""
    except Exception:
        return [], ""


def _try_openclaw(
    days_back: int,
    max_records: int,
) -> Tuple[List[ToolCallRecord], str]:
    """
    尝试扫描 OpenClaw 日志。

    占位实现：OpenClaw 日志格式需要单独的 adapter（待实现）。
    现在返回空列表，不影响其他来源。
    """
    # TODO: ystar/adapters/openclaw_scanner.py
    # from ystar.adapters.openclaw_scanner import scan_openclaw_logs
    # return scan_openclaw_logs(days_back=days_back, max_records=max_records)
    return [], ""


def _try_jsonl(
    jsonl_path: Optional[str],
    max_records: int,
) -> Tuple[List[ToolCallRecord], str]:
    """
    尝试解析用户指定的 JSONL 文件。

    格式要求：每行包含 tool_name + tool_input + 可选的 timestamp。
    兼容 ~/.ystar/history.jsonl 格式。
    """
    if not jsonl_path:
        return [], ""
    try:
        import json, time
        from pathlib import Path
        p = Path(jsonl_path).expanduser()
        if not p.exists():
            return [], ""

        records = []
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # ~/.ystar/history.jsonl 格式
                # {"timestamp": "...", "func_name": "...", "params": {...}, ...}
                tool_name = (obj.get("tool_name") or
                             obj.get("func_name") or
                             obj.get("event_type") or "unknown")
                tool_input = (obj.get("tool_input") or
                              obj.get("params") or {})
                ts_raw = obj.get("timestamp", "")
                ts = 0.0
                if ts_raw:
                    try:
                        from ystar.adapters.claude_code_scanner import _parse_timestamp
                        ts = _parse_timestamp(str(ts_raw))
                    except Exception:
                        pass

                records.append(ToolCallRecord(
                    tool_name   = str(tool_name),
                    tool_input  = tool_input if isinstance(tool_input, dict) else {},
                    timestamp   = ts,
                    session_id  = "jsonl-import",
                    source_file = str(p),
                    agent_id    = obj.get("agent_id", "unknown"),
                    event_type  = str(tool_name),
                ))
                if len(records) >= max_records:
                    break

        return records, f"jsonl:{jsonl_path}"
    except Exception:
        return [], ""


# ── 通用入口 ──────────────────────────────────────────────────────────────

def scan_history(
    days_back:   int  = 30,
    max_records: int  = 5000,
    jsonl_path:  Optional[str] = None,
    sources:     Optional[List[str]] = None,
) -> Tuple[List[ToolCallRecord], str, str]:
    """
    按优先级尝试各种历史来源，返回第一个有数据的结果。

    这是 CLI 和其他调用方的唯一入口，不需要知道底层用了哪个 adapter。

    Args:
        days_back:    扫描最近 N 天（0 = 全部历史）
        max_records:  最多返回多少条记录
        jsonl_path:   显式指定 JSONL 文件路径（优先于自动探测）
        sources:      指定尝试哪些来源（None = 全部按优先级）

    Returns:
        (records, source_id, description)
        - records:     ToolCallRecord 列表（空列表 = 没有历史数据）
        - source_id:   数据来源标识符（"claude_code:..." / "jsonl:..." / ""）
        - description: 人类可读的来源说明
    """
    enabled = sources or list(SOURCES.keys())

    # 显式 JSONL 路径最优先
    if jsonl_path:
        records, src = _try_jsonl(jsonl_path, max_records)
        if records:
            return records, src, f"JSONL 文件: {jsonl_path}"

    # 按顺序尝试其他来源
    order = [s for s in ["claude_code", "openclaw"] if s in enabled]

    for source in order:
        if source == "claude_code":
            records, src = _try_claude_code(days_back, max_records)
            if records:
                return records, src, SOURCES["claude_code"]

        elif source == "openclaw":
            records, src = _try_openclaw(days_back, max_records)
            if records:
                return records, src, SOURCES["openclaw"]

    return [], "", ""


def available_sources() -> List[Dict[str, Any]]:
    """
    探测当前环境中哪些历史来源可用（用于 ystar init 的提示）。
    """
    result = []

    # Claude Code
    try:
        from ystar.adapters.claude_code_scanner import (
            find_claude_projects_dir, find_session_files
        )
        d = find_claude_projects_dir()
        if d:
            files = find_session_files(d, days_back=30)
            result.append({
                "source":       "claude_code",
                "label":        SOURCES["claude_code"],
                "available":    True,
                "file_count":   len(files),
                "path":         str(d),
            })
        else:
            result.append({
                "source":    "claude_code",
                "label":     SOURCES["claude_code"],
                "available": False,
                "reason":    "~/.claude/projects/ 不存在",
            })
    except Exception as e:
        result.append({
            "source":    "claude_code",
            "label":     SOURCES["claude_code"],
            "available": False,
            "reason":    str(e),
        })

    # OpenClaw（占位）
    result.append({
        "source":    "openclaw",
        "label":     SOURCES["openclaw"],
        "available": False,
        "reason":    "OpenClaw scanner 待实现（ystar/adapters/openclaw_scanner.py）",
    })

    return result

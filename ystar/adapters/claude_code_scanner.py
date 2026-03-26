# ystar/adapters/claude_code_scanner.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
ystar.adapters.claude_code_scanner  —  Claude Code 会话日志解析器  v0.41.0
============================================================================

适配层职责：把 Claude Code JSONL 会话文件翻译成 Y* 通用格式。

三个判断问题验证归属：
  Q1 给 LangChain 用要改吗？  → 要改（LangChain 用不同的 trace 格式）→ 适配层 ✓
  Q2 需要记住历史吗？          → 不需要 → 适配层 ✓
  Q3 翻译格式还是判断对错？    → 翻译格式 → 适配层 ✓

不做的事：
  - 不运行 check()，不判断合规性
  - 不写入任何数据库
  - 不做业务逻辑判断
  - 不依赖 Y* kernel 以外的模块

输出格式（ToolCallRecord）是 kernel/retroactive.py 的输入，
kernel 层和 adapter 层之间的契约接口。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

# ToolCallRecord 定义在核心层，这里只 import 使用
from ystar.kernel.retroactive import ToolCallRecord


# ── tool_name → event_type 映射（仅用于分类，不影响判断逻辑）─────────────

_TOOL_TO_EVENT_TYPE: Dict[str, str] = {
    "Write":        "file_write",
    "Edit":         "file_edit",
    "MultiEdit":    "file_edit",
    "Read":         "file_read",
    "Glob":         "file_list",
    "Grep":         "file_search",
    "LS":           "file_list",
    "Bash":         "command_exec",
    "WebFetch":     "web_fetch",
    "WebSearch":    "web_search",
    "Task":         "task_spawn",
    "TodoWrite":    "file_write",
    "NotebookEdit": "file_edit",
}


def _derive_event_type(tool_name: str) -> str:
    """从工具名推断事件类型，mcp__ 前缀的工具统一归类为 mcp_tool_call。"""
    if tool_name.startswith("mcp__"):
        return "mcp_tool_call"
    return _TOOL_TO_EVENT_TYPE.get(tool_name, "tool_call")


def _extract_primary_field(tool_name: str, tool_input: dict) -> tuple:
    """
    从 tool_input 里提取主要字段（file_path / command / url）。
    只做字段提取，不做任何业务判断。
    """
    file_path = command = url = None

    if tool_name in ("Write", "Edit", "MultiEdit", "Read",
                     "Glob", "Grep", "LS", "TodoWrite", "NotebookEdit"):
        file_path = (tool_input.get("path") or
                     tool_input.get("file_path") or
                     tool_input.get("pattern") or
                     tool_input.get("directory") or "")

    elif tool_name in ("Bash",):
        command = (tool_input.get("command") or
                   tool_input.get("cmd") or "")

    elif tool_name in ("WebFetch", "WebSearch"):
        url = (tool_input.get("url") or
               tool_input.get("query") or "")

    elif tool_name.startswith("mcp__"):
        # MCP 工具：尝试常见字段名
        for k in ("path", "file", "filepath", "file_path", "dest", "src"):
            if tool_input.get(k):
                file_path = str(tool_input[k])
                break
        for k in ("url", "endpoint", "uri"):
            if tool_input.get(k):
                url = str(tool_input[k])
                break

    return file_path, command, url


# ── 路径查找 ──────────────────────────────────────────────────────────────

def find_claude_projects_dir() -> Optional[Path]:
    """
    查找 Claude Code 的会话历史目录。

    标准位置：
      ~/.claude/projects/          （Linux / macOS）
      ~/AppData/Roaming/claude/projects/  （Windows，部分版本）
    """
    candidates = [
        Path.home() / ".claude" / "projects",
        Path.home() / "AppData" / "Roaming" / "claude" / "projects",
        Path.home() / "Library" / "Application Support" / "Claude" / "projects",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return None


def find_session_files(
    projects_dir: Optional[Path] = None,
    days_back: int = 30,
    cwd_filter: Optional[str] = None,
) -> List[Path]:
    """
    列出 Claude Code 会话 JSONL 文件。

    Args:
        projects_dir: ~/.claude/projects/ 路径（None = 自动查找）
        days_back:    只扫描最近 N 天的文件（0 = 全部）
        cwd_filter:   只扫描当前工作目录对应的会话（None = 全部）

    Returns:
        .jsonl 文件路径列表，按修改时间降序
    """
    if projects_dir is None:
        projects_dir = find_claude_projects_dir()
    if projects_dir is None:
        return []

    import time
    cutoff = time.time() - days_back * 86400 if days_back > 0 else 0

    # cwd_filter 转成 Claude Code 的目录编码格式
    cwd_encoded = None
    if cwd_filter:
        cwd_encoded = re.sub(r"[^a-zA-Z0-9]", "-", cwd_filter)

    result = []
    for jsonl_file in projects_dir.rglob("*.jsonl"):
        # 跳过 summary 文件（通常以 "summary-" 开头）
        if jsonl_file.stem.startswith("summary"):
            continue
        # 时间过滤
        if days_back > 0 and jsonl_file.stat().st_mtime < cutoff:
            continue
        # cwd 过滤
        if cwd_encoded:
            parent_name = jsonl_file.parent.name
            if cwd_encoded not in parent_name:
                continue
        result.append(jsonl_file)

    return sorted(result, key=lambda p: p.stat().st_mtime, reverse=True)


# ── JSONL 解析 ────────────────────────────────────────────────────────────

def _parse_timestamp(ts_str: str) -> float:
    """ISO 8601 时间戳 → Unix float。解析失败返回 0.0。"""
    if not ts_str:
        return 0.0
    try:
        import datetime
        # 处理各种格式：2026-03-04T16:59:22.000Z / 2026-03-04T16:59:22+00:00
        ts_str = ts_str.rstrip("Z") + "+00:00" if ts_str.endswith("Z") else ts_str
        dt = datetime.datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except Exception:
        return 0.0


def parse_session_file(jsonl_path: Path) -> Iterator[ToolCallRecord]:
    """
    解析一个 Claude Code 会话 JSONL 文件，提取所有工具调用记录。

    只产出 type=="assistant" 且 content 里有 type=="tool_use" 的记录。
    其他行（user 消息、text 响应等）静默跳过。
    """
    # 从文件名提取 session_id（UUID 格式的文件名）
    session_id = jsonl_path.stem
    source_file = str(jsonl_path)

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # 只处理 assistant 消息
                if obj.get("type") != "assistant":
                    continue

                msg = obj.get("message", {})
                if msg.get("role") != "assistant":
                    continue

                ts = _parse_timestamp(obj.get("timestamp", ""))
                content = msg.get("content", [])

                # content 可能是字符串（旧格式）或列表（新格式）
                if isinstance(content, str):
                    continue
                if not isinstance(content, list):
                    continue

                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") != "tool_use":
                        continue

                    tool_name  = item.get("name", "")
                    tool_input = item.get("input", {})

                    if not tool_name or not isinstance(tool_input, dict):
                        continue

                    file_path, command, url = _extract_primary_field(
                        tool_name, tool_input
                    )

                    yield ToolCallRecord(
                        tool_name   = tool_name,
                        tool_input  = tool_input,
                        timestamp   = ts,
                        session_id  = session_id,
                        source_file = source_file,
                        event_type  = _derive_event_type(tool_name),
                        file_path   = file_path,
                        command     = command,
                        url         = url,
                    )

    except (OSError, PermissionError):
        # 文件不可读时静默跳过，不中断整个扫描
        return


def scan_sessions(
    projects_dir: Optional[Path] = None,
    days_back: int = 30,
    cwd_filter: Optional[str] = None,
    max_records: int = 5000,
) -> List[ToolCallRecord]:
    """
    扫描 Claude Code 历史会话，返回工具调用记录列表。

    这是适配层的主入口函数。

    Args:
        projects_dir: ~/.claude/projects/（None = 自动查找）
        days_back:    扫描范围（天数，0 = 全部历史）
        cwd_filter:   工作目录过滤（None = 所有项目）
        max_records:  最多返回 N 条记录，避免内存爆炸

    Returns:
        ToolCallRecord 列表，按时间升序
    """
    files = find_session_files(projects_dir, days_back, cwd_filter)
    records: List[ToolCallRecord] = []

    for jsonl_file in files:
        for record in parse_session_file(jsonl_file):
            records.append(record)
            if len(records) >= max_records:
                break
        if len(records) >= max_records:
            break

    # 按时间升序排列（最旧的在前，符合因果顺序）
    records.sort(key=lambda r: r.timestamp)
    return records


def scan_summary(records: List[ToolCallRecord]) -> Dict[str, Any]:
    """生成扫描摘要（用于展示给用户确认）。"""
    if not records:
        return {"total": 0}

    from collections import Counter
    tool_counts = Counter(r.tool_name for r in records)
    sessions    = len({r.session_id for r in records})
    import datetime
    if records[0].timestamp > 0:
        oldest = datetime.datetime.fromtimestamp(records[0].timestamp).strftime("%Y-%m-%d")
        newest = datetime.datetime.fromtimestamp(records[-1].timestamp).strftime("%Y-%m-%d")
    else:
        oldest = newest = "未知"

    return {
        "total":         len(records),
        "sessions":      sessions,
        "date_range":    f"{oldest} → {newest}",
        "top_tools":     tool_counts.most_common(5),
        "write_count":   tool_counts.get("Write", 0) + tool_counts.get("Edit", 0),
        "bash_count":    tool_counts.get("Bash", 0),
        "fetch_count":   tool_counts.get("WebFetch", 0) + tool_counts.get("WebSearch", 0),
    }

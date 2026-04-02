# Layer: Foundation
"""
ystar.adapters.boundary_enforcer  —  Boundary Enforcement  v0.48.0
===================================================================

边界检查模块，从 hook.py 拆分而来（P1-5）。

职责：
  - 不可变路径检查（_check_immutable_paths）
  - 写路径边界检查（_check_write_boundary）
  - 工具限制检查（_check_tool_restriction）
  - 从 AGENTS.md 加载路径/工具配置
  - Bash 命令写路径提取

设计原则：
  - 所有边界检查返回 Optional[PolicyResult]
  - None 表示放行，PolicyResult(allowed=False) 表示拦截
  - 优先从 session config 加载，回退到 AGENTS.md
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ystar.session import PolicyResult

_log = logging.getLogger("ystar.boundary")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*boundary] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.WARNING)


# ── 全局状态（懒加载）────────────────────────────────────────────────────
_AGENT_WRITE_PATHS: Dict[str, list] = {}  # agent → [allowed write paths]
_WRITE_PATHS_LOADED: bool = False

_AGENT_ALLOWED_TOOLS: Dict[str, list] = {}    # agent → [allowed tool names]
_AGENT_DISALLOWED_TOOLS: Dict[str, list] = {}  # agent → [forbidden tool names]
_TOOL_RESTRICTIONS_LOADED: bool = False

# 写操作工具名
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}

# 不可变路径：治理宪章文件，任何角色都不得写入
_IMMUTABLE_PATTERNS = [
    "AGENTS.md",
    ".claude/agents/",
]


# ── 不可变路径检查 ────────────────────────────────────────────────────────
def _check_immutable_paths(tool_name: str, params: dict) -> Optional[PolicyResult]:
    """
    拦截对治理宪章文件的写入（AGENTS.md, .claude/agents/*.md）。
    在 _check_write_boundary 之前调用，优先级最高。
    """
    if tool_name not in _WRITE_TOOLS:
        return None

    file_path = params.get("file_path", "")
    if not file_path:
        return None

    norm = os.path.normpath(file_path).replace("\\", "/")
    basename = os.path.basename(norm)

    for pattern in _IMMUTABLE_PATTERNS:
        if pattern.endswith("/"):
            # 目录前缀匹配
            if f"/{pattern}" in f"/{norm}/" or norm.startswith(pattern):
                return PolicyResult(
                    allowed=False,
                    reason=(
                        f"Immutable path violation: '{file_path}' is a governance "
                        f"charter file and cannot be modified by any agent."
                    ),
                    who="*",
                    what=tool_name,
                    violations=[],
                )
        else:
            # 文件名精确匹配
            if basename == pattern:
                return PolicyResult(
                    allowed=False,
                    reason=(
                        f"Immutable path violation: '{file_path}' is a governance "
                        f"charter file and cannot be modified by any agent."
                    ),
                    who="*",
                    what=tool_name,
                    violations=[],
                )
    return None


# ── AGENTS.md 解析：Write Paths ─────────────────────────────────────────
def _load_write_paths_from_agents_md() -> Dict[str, list]:
    """
    从 AGENTS.md 动态解析每个角色的 Write Access 路径。
    通用机制：适用于任何 AGENTS.md，不依赖特定角色名。
    """
    result: Dict[str, list] = {}

    # 尝试多个位置
    for candidate in [Path("AGENTS.md"), Path.cwd() / "AGENTS.md"]:
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8")
            break
    else:
        return result

    # 按 "## XXX Agent" 分割
    sections = re.split(r"\n## ", text)
    for section in sections:
        role_match = re.match(
            r"(\w[\w\s]*?)\s*Agent\s*(?:\(.*?\))?\s*\n", section)
        if not role_match:
            continue

        agent_key = role_match.group(1).strip().lower()

        # 提取 "### Write Access" 下的路径列表
        wa_match = re.search(
            r"###\s*Write Access\s*\n((?:\s*-\s*.+\n)+)", section)
        if wa_match:
            paths = []
            for line in wa_match.group(1).strip().splitlines():
                item = line.strip().lstrip("- ").strip()
                # 提取路径部分（去掉括号内的说明）
                path_part = re.sub(r"\s*\(.*?\)\s*$", "", item).strip()
                if path_part and not path_part.startswith("GitHub"):
                    paths.append(path_part)
            if paths:
                result[agent_key] = paths

    return result


def _ensure_write_paths_loaded():
    """确保写路径已从 session config 或 AGENTS.md 加载（懒加载，只加载一次）。

    优先级（路径统一架构 — Directive #024补充）：
    1. .ystar_session.json 中的 agent_write_paths（最权威，init生成）
    2. AGENTS.md 动态解析（回退方案）
    """
    global _AGENT_WRITE_PATHS, _WRITE_PATHS_LOADED
    if _WRITE_PATHS_LOADED:
        return
    # Import here to avoid circular dependency
    from ystar.adapters.identity_detector import _load_session_config

    # 1. 优先从 session config 加载（单一真相源）
    session_cfg = _load_session_config()
    if session_cfg and "agent_write_paths" in session_cfg:
        _AGENT_WRITE_PATHS = session_cfg["agent_write_paths"]
        _log.info("Write paths loaded from session config for %d agents",
                  len(_AGENT_WRITE_PATHS))
    else:
        # 2. 回退：从 AGENTS.md 动态解析
        _AGENT_WRITE_PATHS = _load_write_paths_from_agents_md()
        if _AGENT_WRITE_PATHS:
            _log.info("Write paths loaded from AGENTS.md for %d agents",
                      len(_AGENT_WRITE_PATHS))
        else:
            _log.warning("No write paths loaded — no session config or AGENTS.md found")
    _WRITE_PATHS_LOADED = True


def _check_write_boundary(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """
    对 Write/Edit/MultiEdit 工具强制执行角色写路径边界。

    写路径从 AGENTS.md 或 session config 动态加载（通用机制）。
    如果 who 有定义写路径限制且文件不在允许范围内，返回 deny PolicyResult。
    否则返回 None（放行）。
    """
    if tool_name not in _WRITE_TOOLS:
        return None

    _ensure_write_paths_loaded()
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


# ── AGENTS.md 解析：Tool Restrictions ───────────────────────────────────
def _load_tool_restrictions_from_agents_md() -> Tuple[Dict[str, list], Dict[str, list]]:
    """
    从 AGENTS.md 动态解析每个角色的 Allowed/Forbidden 工具列表。
    返回 (allowed_tools_dict, disallowed_tools_dict)。
    """
    allowed: Dict[str, list] = {}
    disallowed: Dict[str, list] = {}

    for candidate in [Path("AGENTS.md"), Path.cwd() / "AGENTS.md"]:
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8")
            break
    else:
        return allowed, disallowed

    # 按 "### " 分割子 agent 段落
    sections = re.split(r"\n### ", text)
    for section in sections:
        # 匹配角色名（如 "code-reviewer", "test-runner"）
        role_match = re.match(r"([\w-]+)(?:\s*\(.*?\))?\s*\n", section)
        if not role_match:
            continue
        agent_key = role_match.group(1).strip().lower()

        for line in section.splitlines():
            line_stripped = line.strip().lstrip("- ").strip()
            # "Allowed: Read, Grep, Glob"
            m_allowed = re.match(r"Allowed:\s*(.+)", line_stripped)
            if m_allowed:
                tools = [t.strip().split("(")[0].strip()
                         for t in m_allowed.group(1).split(",")]
                allowed.setdefault(agent_key, []).extend(
                    t for t in tools if t)
            # "Forbidden: Write, Edit, Bash"
            m_forbidden = re.match(r"Forbidden:\s*(.+)", line_stripped)
            if m_forbidden:
                tools = [t.strip().split("(")[0].strip()
                         for t in m_forbidden.group(1).split(",")]
                disallowed.setdefault(agent_key, []).extend(
                    t for t in tools if t)

    return allowed, disallowed


def _ensure_tool_restrictions_loaded():
    """确保工具限制已加载（懒加载）。优先 session config，回退 AGENTS.md。"""
    global _AGENT_ALLOWED_TOOLS, _AGENT_DISALLOWED_TOOLS, _TOOL_RESTRICTIONS_LOADED
    if _TOOL_RESTRICTIONS_LOADED:
        return

    from ystar.adapters.identity_detector import _load_session_config

    session_cfg = _load_session_config()
    if session_cfg and "agent_allowed_tools" in session_cfg:
        _AGENT_ALLOWED_TOOLS = session_cfg["agent_allowed_tools"]
        _AGENT_DISALLOWED_TOOLS = session_cfg.get("agent_disallowed_tools", {})
        _log.info("Tool restrictions loaded from session config")
    else:
        _AGENT_ALLOWED_TOOLS, _AGENT_DISALLOWED_TOOLS = (
            _load_tool_restrictions_from_agents_md()
        )
        if _AGENT_ALLOWED_TOOLS or _AGENT_DISALLOWED_TOOLS:
            _log.info("Tool restrictions loaded from AGENTS.md")
    _TOOL_RESTRICTIONS_LOADED = True


def _check_tool_restriction(
    who: str, tool_name: str
) -> Optional[PolicyResult]:
    """
    检查 agent 是否被允许使用该工具。
    - 如果 who 有 allowed_tools 定义，tool_name 必须在列表中
    - 如果 who 有 disallowed_tools 定义，tool_name 不能在列表中
    """
    _ensure_tool_restrictions_loaded()

    # disallowed_tools 检查（显式禁止）
    forbidden = _AGENT_DISALLOWED_TOOLS.get(who)
    if forbidden and tool_name in forbidden:
        return PolicyResult(
            allowed=False,
            reason=(
                f"Tool restriction: agent '{who}' is forbidden from using "
                f"tool '{tool_name}'. Disallowed tools: {forbidden}"
            ),
            who=who,
            what=tool_name,
            violations=[],
        )

    # allowed_tools 检查（白名单模式）
    allowed = _AGENT_ALLOWED_TOOLS.get(who)
    if allowed and tool_name not in allowed:
        return PolicyResult(
            allowed=False,
            reason=(
                f"Tool restriction: agent '{who}' may only use tools "
                f"{allowed}, but tried to use '{tool_name}'."
            ),
            who=who,
            what=tool_name,
            violations=[],
        )

    return None


# ── Bash 命令写路径提取 ───────────────────────────────────────────────────
def _extract_write_paths_from_bash(command: str) -> list:
    """
    从 Bash 命令中提取所有写操作的目标路径。

    支持的写操作模式：
    - 重定向：> file, >> file
    - tee 命令：tee file1 file2
    - cp 命令：cp src dest
    - mv 命令：mv src dest

    Returns:
        写操作目标路径列表（去重后）
    """
    paths = []

    # 1. 提取重定向的目标路径：> 和 >>
    # 匹配 > file 或 >> file（处理引号和空格）
    # 先匹配带双引号的路径
    redirect_double_quote = r'>>?\s+"([^"]+)"'
    for match in re.finditer(redirect_double_quote, command):
        paths.append(match.group(1))

    # 然后匹配带单引号的路径
    redirect_single_quote = r">>?\s+'([^']+)'"
    for match in re.finditer(redirect_single_quote, command):
        paths.append(match.group(1))

    # 最后匹配不带引号的路径
    redirect_no_quote = r'>>?\s+([^\s;|&<>"\']+)'
    for match in re.finditer(redirect_no_quote, command):
        path = match.group(1)
        # 跳过已经被引号模式匹配的路径
        if path and not path.startswith('"') and not path.startswith("'"):
            paths.append(path)

    # 2. 提取 tee 命令的参数路径
    # tee [-a] file1 file2 ...
    tee_pattern = r'\btee\s+(?:-a\s+)?(.+?)(?:\s*[|;&]|$)'
    for match in re.finditer(tee_pattern, command):
        args_str = match.group(1).strip()
        # 使用 shlex 来正确解析带引号的路径
        try:
            args = shlex.split(args_str)
            for arg in args:
                # 跳过选项参数
                if not arg.startswith('-') and arg:
                    paths.append(arg)
        except ValueError:
            # shlex 解析失败时使用简单分割
            for arg in args_str.split():
                arg = arg.strip('\'"')
                if not arg.startswith('-') and arg:
                    paths.append(arg)

    # 3. 提取 cp 命令的目标路径（最后一个参数）
    # cp [-options] src... dest
    cp_pattern = r'\bcp\s+(?:-\w+\s+)*(.+?)(?:\s*[;&|]|$)'
    for match in re.finditer(cp_pattern, command):
        args_str = match.group(1).strip()
        try:
            args = shlex.split(args_str)
            if args:
                # 目标路径是最后一个参数
                paths.append(args[-1])
        except ValueError:
            args = args_str.split()
            if args:
                paths.append(args[-1].strip('\'"'))

    # 4. 提取 mv 命令的目标路径（最后一个参数）
    # mv [-options] src... dest
    mv_pattern = r'\bmv\s+(?:-\w+\s+)*(.+?)(?:\s*[;&|]|$)'
    for match in re.finditer(mv_pattern, command):
        args_str = match.group(1).strip()
        try:
            args = shlex.split(args_str)
            if args:
                # 目标路径是最后一个参数
                paths.append(args[-1])
        except ValueError:
            args = args_str.split()
            if args:
                paths.append(args[-1].strip('\'"'))

    # 归一化路径：处理 MSYS/Cygwin 格式 (/c/Users/... → C:\Users\...)
    # 以及 Windows 反斜杠/正斜杠混用
    normalized = []
    for p in paths:
        p = p.strip()
        if not p:
            continue
        # MSYS 路径转换: /c/path → C:\path, /d/path → D:\path
        if len(p) >= 3 and p[0] == '/' and p[1].isalpha() and p[2] == '/':
            p = p[1].upper() + ':' + p[2:]
        p = os.path.normpath(p)
        normalized.append(p)

    # 去重并返回
    return list(set(normalized))


__all__ = [
    "_check_immutable_paths",
    "_check_write_boundary",
    "_check_tool_restriction",
    "_load_write_paths_from_agents_md",
    "_load_tool_restrictions_from_agents_md",
    "_ensure_write_paths_loaded",
    "_ensure_tool_restrictions_loaded",
    "_extract_write_paths_from_bash",
]

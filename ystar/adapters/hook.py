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


# ── 角色写路径边界（动态从 AGENTS.md 或 session config 加载）────────────
# only_paths 不能用于此目的（它会同时限制读操作）
# 所以写路径检查在 hook 层单独执行，仅对 Write/Edit/MultiEdit 生效

_AGENT_WRITE_PATHS: Dict[str, list] = {}  # 动态填充，不硬编码
_WRITE_PATHS_LOADED: bool = False

# ── 工具限制（动态从 AGENTS.md 或 session config 加载）────────────────────
_AGENT_ALLOWED_TOOLS: Dict[str, list] = {}    # agent → [allowed tool names]
_AGENT_DISALLOWED_TOOLS: Dict[str, list] = {}  # agent → [forbidden tool names]
_TOOL_RESTRICTIONS_LOADED: bool = False

# 写操作工具名
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}

# ── 不可变路径：治理宪章文件，任何角色都不得写入 ──────────────────────────
_IMMUTABLE_PATTERNS = [
    "AGENTS.md",
    ".claude/agents/",
]


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


def _load_write_paths_from_agents_md() -> Dict[str, list]:
    """
    从 AGENTS.md 动态解析每个角色的 Write Access 路径。
    通用机制：适用于任何 AGENTS.md，不依赖特定角色名。
    """
    import re
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


def _load_tool_restrictions_from_agents_md() -> Tuple[Dict[str, list], Dict[str, list]]:
    """
    从 AGENTS.md 动态解析每个角色的 Allowed/Forbidden 工具列表。
    返回 (allowed_tools_dict, disallowed_tools_dict)。
    """
    import re
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


def _ensure_write_paths_loaded():
    """确保写路径已从 session config 或 AGENTS.md 加载（懒加载，只加载一次）。

    优先级（路径统一架构 — Directive #024补充）：
    1. .ystar_session.json 中的 agent_write_paths（最权威，init生成）
    2. AGENTS.md 动态解析（回退方案）
    """
    global _AGENT_WRITE_PATHS, _WRITE_PATHS_LOADED
    if _WRITE_PATHS_LOADED:
        return
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
    import re
    import shlex

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

    # 去重并返回
    return list(set(paths))


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

    # ── Directive #024: CIEU Boot Record（首次调用时写入）──────────
    session_cfg_boot = _load_session_config()
    cieu_db_boot = session_cfg_boot.get("cieu_db", ".ystar_cieu.db") if session_cfg_boot else ".ystar_cieu.db"
    _write_boot_record(who, session_id_payload or "unknown", cieu_db_boot)

    # 若 agent_id 未在 Policy 里注册，回退到 "agent" fallback
    if who not in policy:
        if "agent" in policy:
            who = "agent"
        else:
            registered = list(policy._rules.keys())
            if registered:
                who = registered[0]

    # ── P0-0: 不可变路径检查（AGENTS.md / .claude/agents/*.md）──────
    params_early = _extract_params(tool_name, tool_input)
    immutable_deny = _check_immutable_paths(tool_name, params_early)
    if immutable_deny is not None:
        cieu_db = ".ystar_cieu.db"
        session_cfg_imm = _load_session_config()
        if session_cfg_imm:
            cieu_db = session_cfg_imm.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, immutable_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY immutable path: %s → %s", who, params_early.get("file_path", "?"))
        return _result_to_response(immutable_deny)

    # ── P0-0.5: 工具限制检查（allowed/disallowed tools）──────────────
    tool_deny = _check_tool_restriction(who, tool_name)
    if tool_deny is not None:
        cieu_db = ".ystar_cieu.db"
        session_cfg_td = _load_session_config()
        if session_cfg_td:
            cieu_db = session_cfg_td.get("cieu_db", cieu_db)
        contract = policy._rules.get(who)
        _write_cieu(who, tool_name, params_early, tool_deny,
                    session_id_payload or "unknown",
                    contract.hash if contract else "", cieu_db)
        _log.warning("DENY tool restriction: %s → %s", who, tool_name)
        return _result_to_response(tool_deny)

    # ── P0-1: 写路径边界检查（仅 Write/Edit/MultiEdit）──────────────
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
                    session_cfg_bash = _load_session_config()
                    if session_cfg_bash:
                        cieu_db = session_cfg_bash.get("cieu_db", cieu_db)
                    contract = policy._rules.get(who)
                    _write_cieu(who, tool_name, params_early, immutable_result,
                                session_id_payload or "unknown",
                                contract.hash if contract else "", cieu_db)
                    _log.warning("DENY Bash command (immutable path): %s → %s", who, path)
                    return _result_to_response(immutable_result)

                # 检查写边界
                boundary_result = _check_write_boundary(
                    who, "Write",  # 视为写操作
                    {"file_path": path}
                )
                if boundary_result is not None:
                    cieu_db = ".ystar_cieu.db"
                    session_cfg_bash2 = _load_session_config()
                    if session_cfg_bash2:
                        cieu_db = session_cfg_bash2.get("cieu_db", cieu_db)
                    contract = policy._rules.get(who)
                    _write_cieu(who, tool_name, params_early, boundary_result,
                                session_id_payload or "unknown",
                                contract.hash if contract else "", cieu_db)
                    _log.warning("DENY Bash command (write boundary): %s → %s", who, path)
                    return _result_to_response(boundary_result)

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
            # Content accuracy review trigger: only fire if writing to
            # paths owned by the agent's write boundary (from session config).
            # This avoids hardcoding specific directory names.
            if trigger.trigger_id == "content_accuracy_review":
                file_path = tool_input.get("file_path") or tool_input.get("path") or ""
                trigger_patterns = None
                scfg = _load_session_config()
                if scfg:
                    trigger_patterns = scfg.get("trigger_path_patterns", {}).get(
                        "content_accuracy_review")
                if trigger_patterns:
                    if not any(p in file_path for p in trigger_patterns):
                        continue
                # If no patterns configured, let the trigger fire for all writes

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


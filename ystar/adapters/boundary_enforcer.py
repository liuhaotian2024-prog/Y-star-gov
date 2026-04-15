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
import time
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
_RESTRICTED_WRITE_PATHS: Dict[str, list] = {}  # path_pattern → [allowed roles]
_RESTRICTED_WRITE_LOADED: bool = False

_AGENT_ALLOWED_TOOLS: Dict[str, list] = {}    # agent → [allowed tool names]
_AGENT_DISALLOWED_TOOLS: Dict[str, list] = {}  # agent → [forbidden tool names]
_TOOL_RESTRICTIONS_LOADED: bool = False

# 写操作工具名
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}

# Git push always denied (both CEO modes respect this)
GIT_PUSH_ALWAYS_DENIED = True

# Agent dispatch tracking (for parallel_dispatch_required rule)
_AGENT_DISPATCH_HISTORY: Dict[str, list] = {}  # agent_name → [(timestamp, target_agent), ...]
_PARALLEL_DISPATCH_WINDOW = 60  # seconds: window for detecting serial dispatches
_SERIAL_DISPATCH_GAP = 30  # seconds: max gap between dispatches to consider "serial"


# ── CROBA (Contract-Reinforced Onboarding Boundary Awareness) M6 ─────────────
def _inject_contract_on_high_risk_write(who: str, file_path: str, tool_name: str):
    """
    CROBA M6: Inject full IntentContract rule text into agent prompt on high-risk write.

    When agent attempts write outside allowed paths, inject AGENTS.md contract section
    into next prompt so agent sees boundary before next action (not after violation).

    Mechanism: Write to /tmp/ystar_contract_inject_{agent}.txt, which hook daemon
    can append to UserPromptSubmit hook on next turn.
    """
    try:
        # Read agent's contract from AGENTS.md
        agents_md = Path(os.path.expanduser("~/.openclaw/workspace/ystar-company/AGENTS.md"))
        if not agents_md.exists():
            return

        content = agents_md.read_text()

        # Extract agent's section (simple heuristic: find ## {agent} heading)
        agent_section = ""
        in_section = False
        for line in content.splitlines():
            if line.startswith("## ") and who.lower() in line.lower():
                in_section = True
            elif line.startswith("## ") and in_section:
                break  # End of agent's section
            if in_section:
                agent_section += line + "\n"

        if not agent_section:
            return

        # Write to injection file
        inject_file = Path(f"/tmp/ystar_contract_inject_{who}.txt")
        inject_file.write_text(f"""
--- BOUNDARY VIOLATION DETECTED —---
You attempted: {tool_name}("{file_path}")
This path is OUTSIDE your allowed write scope.

Your contract from AGENTS.md:
{agent_section}

Before proceeding, verify your action respects your role boundaries.
If this requires cross-boundary write, delegate to the responsible agent.
""")

        _log.info(f"[CROBA] Contract injection prepared for {who} at {inject_file}")

    except Exception as e:
        _log.warning(f"[CROBA] Contract injection failed: {e}")


# ── Agent Mode Manager Integration ────────────────────────────────────────────
def _get_current_mode(agent_id: str = "ceo") -> Dict[str, Any]:
    """
    Get current agent mode, validate expiry, auto-revoke if expired.

    Args:
        agent_id: Agent identifier (default "ceo" for backward compat)

    Returns mode state dict with keys: mode, entered_at, expires_at, trigger, etc.
    Mode can be: standard, autonomous, break_glass
    """
    import json

    mode_file = Path(fos.path.expanduser("~/.openclaw/workspace/ystar-company/.ystar_{agent_id}_mode.json"))

    if not mode_file.exists():
        return {
            "mode": "standard",
            "entered_at": None,
            "expires_at": None,
            "trigger": None
        }

    try:
        with open(mode_file) as f:
            state = json.load(f)

        # Check expiry (break_glass has hard cap)
        if state.get("expires_at"):
            import time
            if time.time() > state["expires_at"]:
                # Auto-revoke expired mode
                _log.info(f"CEO mode {state['mode']} expired, auto-revoking to standard")
                return {
                    "mode": "standard",
                    "entered_at": None,
                    "expires_at": None,
                    "trigger": None
                }

        return state

    except (json.JSONDecodeError, IOError) as e:
        _log.warning(f"Failed to read agent mode file for {agent_id}: {e}, defaulting to standard")
        return {"mode": "standard", "entered_at": None, "expires_at": None, "trigger": None}


# ── 不可变路径配置加载 ────────────────────────────────────────────────────
def _get_immutable_config() -> Tuple[list, list]:
    """
    从 session config 读取 immutable_paths 配置。

    Returns:
        (patterns, override_roles) 元组
        - patterns: 不可变路径模式列表（默认 ["AGENTS.md", ".claude/agents/"]）
        - override_roles: 允许覆盖不可变限制的角色列表（默认 []）
    """
    from ystar.adapters.identity_detector import _load_session_config

    cfg = _load_session_config()
    immutable = cfg.get("immutable_paths", {}) if cfg else {}

    patterns = immutable.get("patterns", ["AGENTS.md", ".claude/agents/"])
    override_roles = immutable.get("override_roles", [])

    return patterns, override_roles


# ── Safemode Check (AMENDMENT-015 Layer 4) ────────────────────────────────
def _is_safemode_active(check_name: Optional[str] = None) -> bool:
    """
    Check if safemode is active (Board override).

    Args:
        check_name: Optional check name to bypass (e.g., "restricted_write_paths")

    Returns:
        True if safemode is active and applies to this check
    """
    if os.environ.get("YSTAR_SAFEMODE") != "1":
        return False

    # Check expiry
    expires_str = os.environ.get("YSTAR_SAFEMODE_EXPIRES", "0")
    try:
        expires = float(expires_str)
        if time.time() > expires:
            _log.warning("Safemode expired, governance restored")
            return False
    except ValueError:
        pass

    # Check if specific bypass requested
    bypass = os.environ.get("YSTAR_SAFEMODE_BYPASS", "")
    if bypass and check_name and bypass != check_name:
        return False  # Not bypassing this specific check

    return True


# ── 不可变路径检查 ────────────────────────────────────────────────────────
def _check_immutable_paths(
    tool_name: str, params: dict, who: str = ""
) -> Optional[PolicyResult]:
    """
    拦截对治理宪章文件的写入（AGENTS.md, .claude/agents/*.md）。
    在 _check_write_boundary 之前调用，优先级最高。

    Args:
        tool_name: 工具名称
        params: 工具参数
        who: 调用者身份（角色名）

    Returns:
        None 表示放行，PolicyResult(allowed=False) 表示拦截
    """
    # Safemode bypass (Layer 4)
    if _is_safemode_active("immutable_paths"):
        _log.warning(f"SAFEMODE: Bypassing immutable_paths check for {params.get('file_path', '')}")
        return None

    if tool_name not in _WRITE_TOOLS:
        return None

    file_path = params.get("file_path", "")
    if not file_path:
        return None

    patterns, override_roles = _get_immutable_config()

    # 如果调用者在 override_roles 中，直接放行
    if who and who in override_roles:
        return None

    norm = os.path.normpath(file_path).replace("\\", "/")
    basename = os.path.basename(norm)

    for pattern in patterns:
        if pattern.endswith("/"):
            # 目录前缀匹配
            if f"/{pattern}" in f"/{norm}/" or norm.startswith(pattern):
                # AMENDMENT-012: Remediation for immutable path violations
                from ystar.session import Remediation
                remediation = Remediation(
                    wrong_action=f'{tool_name}(file_path="{file_path}", ...)',
                    correct_steps=[
                        '# Immutable paths cannot be modified by agents',
                        '# If change is needed: escalate to Board',
                        '# Board can use Board shell override or modify .ystar_session.json immutable_paths config',
                        f'# Override roles (if any): {override_roles}',
                    ],
                    skill_ref="knowledge/secretary/skills/immutable_governance.md",
                    lesson_ref=None,  # Constitutional constraint, not incident-driven
                    rule_name="immutable_paths",
                    rule_context="Governance charter files (AGENTS.md, .claude/agents/) are immutable to preserve team DNA and prevent drift.",
                )
                return PolicyResult(
                    allowed=False,
                    reason=(
                        f"Immutable path violation: '{file_path}' is a governance "
                        f"charter file and cannot be modified by any agent."
                    ),
                    who="*",
                    what=tool_name,
                    violations=[],
                    remediation=remediation,
                )
        else:
            # 文件名精确匹配
            if basename == pattern:
                from ystar.session import Remediation
                remediation = Remediation(
                    wrong_action=f'{tool_name}(file_path="{file_path}", ...)',
                    correct_steps=[
                        '# Immutable paths cannot be modified by agents',
                        '# If change is needed: escalate to Board',
                        '# Board can use Board shell override or modify .ystar_session.json immutable_paths config',
                        f'# Override roles (if any): {override_roles}',
                    ],
                    skill_ref="knowledge/secretary/skills/immutable_governance.md",
                    lesson_ref=None,
                    rule_name="immutable_paths",
                    rule_context="Governance charter files are immutable to preserve team DNA.",
                )
                return PolicyResult(
                    allowed=False,
                    reason=(
                        f"Immutable path violation: '{file_path}' is a governance "
                        f"charter file and cannot be modified by any agent."
                    ),
                    who="*",
                    what=tool_name,
                    violations=[],
                    remediation=remediation,
                )
    return None


# ── 受限写路径检查（restricted_write_paths）────────────────────────────
def _ensure_restricted_write_loaded():
    """从 session config 加载 restricted_write_paths（懒加载，只加载一次）。

    restricted_write_paths 定义哪些路径只有特定角色可以写入。
    与 immutable_paths 不同：immutable 几乎所有人不能写；restricted 只有指定角色可以写。
    """
    global _RESTRICTED_WRITE_PATHS, _RESTRICTED_WRITE_LOADED
    if _RESTRICTED_WRITE_LOADED:
        return
    from ystar.adapters.identity_detector import _load_session_config

    session_cfg = _load_session_config()
    if session_cfg and "restricted_write_paths" in session_cfg:
        _RESTRICTED_WRITE_PATHS = session_cfg["restricted_write_paths"]
        _log.info("Restricted write paths loaded: %d entries",
                  len(_RESTRICTED_WRITE_PATHS))
    _RESTRICTED_WRITE_LOADED = True


def _check_restricted_write_paths(
    tool_name: str, params: dict, who: str = ""
) -> Optional[PolicyResult]:
    """
    检查写入路径是否受限于特定角色。

    restricted_write_paths 配置格式（在 .ystar_session.json 中）：
        {
            ".ystar_active_agent": ["secretary"],
            ".ystar_session.json": ["secretary"],
            "AGENTS.md": ["secretary"],
            ".claude/agents/": ["secretary"]
        }

    匹配逻辑：
    - 如果 pattern 以 "/" 结尾 → 目录前缀匹配
    - 否则 → 文件名精确匹配
    - 如果当前 agent 不在允许列表中 → DENY

    在 _check_immutable_paths 之后、_check_write_boundary 之前调用。
    """
    if tool_name not in _WRITE_TOOLS:
        return None

    file_path = params.get("file_path", "")
    if not file_path:
        return None

    _ensure_restricted_write_loaded()
    if not _RESTRICTED_WRITE_PATHS:
        return None

    norm = os.path.normpath(file_path).replace("\\", "/")
    basename = os.path.basename(norm)

    for pattern, allowed_roles in _RESTRICTED_WRITE_PATHS.items():
        matched = False
        if pattern.endswith("/"):
            # 目录前缀匹配
            if f"/{pattern}" in f"/{norm}/" or norm.startswith(pattern):
                matched = True
        else:
            # 文件名精确匹配
            if basename == pattern or norm.endswith(f"/{pattern}"):
                matched = True

        if matched:
            if who and who in allowed_roles:
                return None  # 在允许列表中，放行
            return PolicyResult(
                allowed=False,
                reason=(
                    f"Restricted write path violation: '{file_path}' can only be "
                    f"written by roles {allowed_roles}, but current agent is "
                    f"'{who or 'unknown'}'."
                ),
                who=who or "*",
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

    CEO Mode Integration:
    - autonomous mode: expand to Y-star-gov/, gov-mcp/, scripts/
    - break_glass mode: expand to .claude/agents/ additionally
    """
    if tool_name not in _WRITE_TOOLS:
        return None

    _ensure_write_paths_loaded()
    allowed = _AGENT_WRITE_PATHS.get(who)
    if not allowed:
        return None   # 未定义边界的 agent 不受限

    # Agent mode expansion (CEO or other agents in elevated modes)
    if who.lower() in ("ceo", "aiden-ceo", "aiden"):
        mode_state = _get_current_mode(agent_id="ceo")
        mode = mode_state.get("mode", "standard")

        if mode in ("autonomous", "break_glass"):
            # Expand CEO write paths
            expanded = list(allowed)
            autonomous_paths = [
                os.path.expanduser("~/.openclaw/workspace/Y-star-gov/"),
                os.path.expanduser("~/.openclaw/workspace/gov-mcp/"),
                os.path.expanduser("~/.openclaw/workspace/ystar-company/scripts/")
            ]
            for p in autonomous_paths:
                if p not in expanded:
                    expanded.append(p)

            if mode == "break_glass":
                break_glass_path = os.path.expanduser("~/.openclaw/workspace/ystar-company/.claude/agents/")
                if break_glass_path not in expanded:
                    expanded.append(break_glass_path)

            allowed = expanded

    file_path = params.get("file_path", "")
    if not file_path:
        return None

    # 归一化路径（处理 Windows 反斜杠）
    norm_target = os.path.normpath(os.path.abspath(file_path))

    for ap in allowed:
        norm_allowed = os.path.normpath(os.path.abspath(ap))
        if norm_target == norm_allowed or norm_target.startswith(norm_allowed + os.sep):
            return None   # 在允许范围内

    # AMENDMENT-012: Structured remediation for write boundary violations
    from ystar.session import Remediation

    # CROBA (M6): Inject full contract rule text into agent prompt on high-risk write
    _inject_contract_on_high_risk_write(who, file_path, tool_name)

    # Determine which engineer scope this belongs to
    scope_map = {
        "ystar/kernel/": "eng-kernel (Leo Chen)",
        "ystar/governance/": "eng-governance (Maya Patel)",
        "ystar/adapters/": "eng-platform (Ryan Park)",
        "ystar/_hook": "eng-platform (Ryan Park)",
        "ystar/_cli": "eng-platform (Ryan Park)",
        "ystar/domains/": "eng-domains (Jordan Lee)",
        "ystar/patterns/": "eng-domains (Jordan Lee)",
        "ystar/templates/": "eng-domains (Jordan Lee)",
    }

    responsible_engineer = "CTO (for delegation)"
    for path_prefix, engineer in scope_map.items():
        if path_prefix in file_path:
            responsible_engineer = engineer
            break

    remediation = Remediation(
        wrong_action=f'{tool_name}(file_path="{file_path}", ...)',
        correct_steps=[
            f'# {who} write scope: {allowed}',
            f'# For {file_path}: delegate to {responsible_engineer}',
            'invoke("Agent", agent="cto", task="...")',
            '# Or escalate to Board if requires immutable path override',
        ],
        skill_ref=f"knowledge/{who}/skills/{who}_scope.md" if who.startswith("eng-") else "knowledge/ceo/skills/ceo_delegation_chain.md",
        lesson_ref="knowledge/eng-domains/lessons/scope_violation_2026_04_12.md",
        rule_name="write_boundary_violation",
        rule_context=f"Each agent owns specific write paths. Cross-boundary edits go via delegation.",
    )

    return PolicyResult(
        allowed=False,
        reason=(
            f"Write boundary violation: agent '{who}' cannot write to '{file_path}'. "
            f"Allowed write paths: {allowed}"
        ),
        who=who,
        what=tool_name,
        violations=[],
        remediation=remediation,
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



# FIX-3: path-like filter — reject tokens that clearly aren't filesystem paths.
# Root cause: the cp/mv/tee regexes are greedy and can capture SQL fragments
# like "strftime(" from `sqlite3 db "... strftime('%s','now') ..."` invocations.
# A token is treated as a path only if it:
#   - contains no shell metacharacters (parens, %, quotes, $, backticks)
#   - either contains / or . or - or _, or is a bareword starting with a letter
_FIX3_FORBIDDEN_CHARS = set("()%`$\"'\n\t")

def _looks_like_path(token: str) -> bool:
    if not token:
        return False
    if any(c in _FIX3_FORBIDDEN_CHARS for c in token):
        return False
    # Reject things that look like SQL function calls or inline code fragments.
    if token.endswith("("):
        return False
    # Accept if clearly path-shaped.
    if "/" in token or "\\" in token or "." in token or "-" in token or "_" in token:
        return True
    # Bare identifiers: only accept if reasonable file-name length.
    return token.isidentifier() and 1 <= len(token) <= 64

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

    # 去重并返回 (FIX-3: drop tokens that don't look like filesystem paths)
    return list({p for p in normalized if _looks_like_path(p)})


# ── Agent Behavior Rules ─────────────────────────────────────────────────
# Sentinel value to distinguish "not provided" from "explicitly None"
_SENTINEL = object()

# Session state tracking for behavior rules
_SESSION_TOOL_CALLS: list = []  # Track all tool calls in session
_SESSION_START_TIME: float = 0.0
_SESSION_FILE_EDITS: dict = {}  # file_path -> timestamp of last edit
_SESSION_DOCUMENTS_CREATED: dict = {}  # file_path -> timestamp of creation

# ── Session lifecycle auto-emitters (Board 2026-04-11) ──
_PROTOCOL_STATE: dict = {}  # session_id -> set[str] of emitted events


def _hydrate_protocol_state(session_id: str, cieu_db: str = ".ystar_cieu.db") -> None:
    """Populate _PROTOCOL_STATE[session_id] from CIEU on first access per session."""
    if session_id in _PROTOCOL_STATE:
        return
    _PROTOCOL_STATE[session_id] = set()
    try:
        import sqlite3
        conn = sqlite3.connect(cieu_db)
        cur = conn.execute(
            "SELECT event_type FROM cieu_events WHERE session_id = ? AND event_type IN "
            "('session_start', 'continuation_loaded', 'obligation_check', 'boot_protocol_completed')",
            (session_id,)
        )
        for (et,) in cur.fetchall():
            _PROTOCOL_STATE[session_id].add(et)
        conn.close()
    except Exception:
        pass  # silent — never break the hook path


def _emit_once(session_id: str, event: str, who: str,
               cieu_db: str = ".ystar_cieu.db", extra: dict | None = None) -> None:
    seen = _PROTOCOL_STATE.setdefault(session_id, set())
    if event in seen:
        return
    seen.add(event)
    try:
        from ystar.adapters.cieu_writer import _write_session_lifecycle
        _write_session_lifecycle(event, who, session_id, cieu_db, extra or {})
    except Exception as _e:
        _log.error("lifecycle emit failed: %s", _e)


_BOOT_PROTOCOL_WHITELIST_TOOLS = {
    "mcp__gov-mcp__gov_obligations",
    "mcp__gov-mcp__gov_session_info",
    "mcp__gov-mcp__gov_health",
    "mcp__gov-mcp__gov_check",
    "mcp__gov-mcp__gov_doctor",
    "ToolSearch",
}


def _check_session_start_protocol_completed(
    who: str, tool_name: str, params: dict, session_cfg: Any = _SENTINEL
) -> Optional["PolicyResult"]:
    """DENY any non-protocol action until session_start + continuation_loaded
    + obligation_check all appear in CIEU for the current session.

    Whitelist (always allowed):
      - gov-mcp obligations/session_info/health/check/doctor
      - ToolSearch (harness bookkeeping)
      - Bash running governance_boot.sh or session_close_yml.py
      - Read of memory/continuation.{json,md}, memory/session_handoff.md,
        or .ystar_session.json
    """
    try:
        # Use injected session_cfg if provided (for testing), otherwise load fresh
        if session_cfg is _SENTINEL:
            from ystar.adapters.identity_detector import _load_session_config
            cfg = _load_session_config()
        else:
            cfg = session_cfg

        if cfg is None:
            # No session config → test mode or uninitialized session → skip protocol check
            return None
        sid = cfg.get("session_id")
        if not sid or sid == "unknown" or sid.startswith("test_"):
            # No valid session_id OR test session → skip protocol check
            return None
    except Exception:
        return None

    _hydrate_protocol_state(sid)
    seen = _PROTOCOL_STATE.get(sid, set())

    if "boot_protocol_completed" in seen:
        return None  # fast path

    # Whitelist tool names
    if tool_name in _BOOT_PROTOCOL_WHITELIST_TOOLS:
        return None
    if tool_name == "Bash":
        cmd = str(params.get("command", ""))
        if "governance_boot.sh" in cmd or "session_close_yml.py" in cmd:
            return None
    if tool_name == "Read":
        fp = str(params.get("file_path", "")).replace("\\", "/")
        if (fp.endswith("memory/continuation.json")
                or fp.endswith("memory/continuation.md")
                or fp.endswith("memory/session_handoff.md")
                or fp.endswith(".ystar_session.json")):
            return None

    missing = [e for e in ("session_start", "continuation_loaded", "obligation_check")
               if e not in seen]
    if not missing:
        return None  # all three present, boot_protocol_completed will fire

    reason = (
        f"Session start protocol incomplete. Missing: {missing}. "
        f"Required: 1.run governance_boot.sh 2.read memory/continuation.json 3.check obligations. "
        f"Tool '{tool_name}' blocked for agent '{who}'."
    )
    try:
        _record_behavior_rule_cieu(
            who=who,
            rule_name="session_start_protocol_completed",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params=params,
        )
    except Exception:
        pass

    from ystar.session import PolicyResult
    return PolicyResult(allowed=False, reason=reason, who=who, what=tool_name, violations=[])


def _get_behavior_rules_config() -> Optional[dict]:
    """Get session config for behavior rules (for testability)."""
    from ystar.adapters.identity_detector import _load_session_config
    return _load_session_config()


def _record_behavior_rule_cieu(
    who: str,
    rule_name: str,
    event_type: str,
    decision: str,
    passed: bool,
    reason: str,
    params: dict,
    cieu_db: str = ".ystar_cieu.db",
) -> None:
    """
    Record behavior rule check to CIEU database.

    Args:
        who: Agent ID
        rule_name: Name of the behavior rule
        event_type: CIEU event type (BEHAVIOR_RULE_VIOLATION or BEHAVIOR_RULE_WARNING)
        decision: Decision made (DENY, WARNING, ALLOW)
        passed: Whether the rule passed
        reason: Explanation
        params: Additional context parameters
        cieu_db: Path to CIEU database

    CEO Mode Integration:
    - break_glass mode: add elevated=true to CIEU event
    """
    try:
        from ystar.adapters.identity_detector import _load_session_config
        from ystar.governance.cieu_store import CIEUStore

        cfg = _load_session_config()
        session_id = cfg.get("session_id", "unknown") if cfg else "unknown"

        # Check if in break_glass mode (for elevated tagging)
        elevated = False
        if who.lower() in ("ceo", "aiden-ceo", "aiden"):
            mode_state = _get_current_mode(agent_id="ceo")
            if mode_state.get("mode") == "break_glass":
                elevated = True

        cieu_params = {
            "rule": rule_name,
            "reason": reason,
            **params
        }
        if elevated:
            cieu_params["elevated"] = True

        store = CIEUStore(cieu_db)
        store.write_dict({
            "session_id": session_id,
            "agent_id": who,
            "event_type": event_type,
            "decision": decision.lower(),
            "passed": passed,
            "violations": [{"dimension": rule_name, "message": reason}] if not passed else [],
            "params": cieu_params,
            "contract_hash": "",
            "evidence_grade": "behavior",
        })
        _log.info(f"Behavior rule CIEU recorded: {rule_name} -> {decision}{' [elevated]' if elevated else ''}")
    except Exception as e:
        _log.error(f"Failed to write behavior rule CIEU: {e}")


def _track_tool_call(who: str, tool_name: str, params: dict) -> None:
    """Track tool call for behavior analysis."""
    global _SESSION_TOOL_CALLS, _SESSION_START_TIME

    if _SESSION_START_TIME == 0.0:
        _SESSION_START_TIME = time.time()

    _SESSION_TOOL_CALLS.append({
        "who": who,
        "tool": tool_name,
        "params": params,
        "timestamp": time.time()
    })


def _check_autonomous_mission_requires_article_11(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 9: autonomous_mission_requires_article_11

    If agent dispatches a task with autonomous/全自主/第十一条 keywords,
    must have complete 7-layer cognitive construction beforehand.

    Detection: Check if task contains autonomous keywords
    Check: Look for Layer 0-7 evidence in recent tool calls
    Action: DENY if missing complete 7-layer construction
    """
    if not agent_rules.get("autonomous_mission_requires_article_11"):
        return None

    # Only check Agent tool dispatches
    if tool_name != "Agent":
        return None

    task_desc = params.get("task", "")
    autonomous_keywords = [
        "autonomous", "全自主", "第十一条", "自主任务",
        "Autonomous Mission", "Article 11"
    ]

    if not any(kw in task_desc for kw in autonomous_keywords):
        return None

    # Check for 7-layer construction in recent tool calls or outputs
    # Look for Layer 0-7 or 第0层-第7层 mentions
    layer_keywords = []
    for i in range(8):
        layer_keywords.extend([f"Layer {i}", f"第{i}层"])

    found_layers = set()
    for call in _SESSION_TOOL_CALLS[-50:]:  # Check last 50 tool calls
        call_params = call.get("params", {})
        # Check in Write/Edit content
        if call["tool"] in ["Write", "Edit"]:
            content = call_params.get("content", "") + call_params.get("new_string", "")
            for i in range(8):
                if f"Layer {i}" in content or f"第{i}层" in content:
                    found_layers.add(i)

    missing_layers = set(range(8)) - found_layers

    if missing_layers:
        reason = (
            f"Autonomous mission requires complete Article 11 cognitive construction "
            f"(Layers 0-7). Missing layers: {sorted(missing_layers)}. "
            f"Complete the 7-layer construction before dispatching autonomous missions."
        )
        try:
            _record_behavior_rule_cieu(
                who=who,
                rule_name="autonomous_mission_requires_article_11",
                event_type="BEHAVIOR_RULE_VIOLATION",
                decision="DENY",
                passed=False,
                reason=reason,
                params={"missing_layers": list(missing_layers), "task": task_desc}
            )
        except Exception as e:
            _log.warning(f"Failed to record CIEU for autonomous_mission: {e}")

        return PolicyResult(
            allowed=False,
            reason=reason,
            who=who,
            what=tool_name,
            violations=[],
        )

    # All layers present - ALLOW and record success
    try:
        _record_behavior_rule_cieu(
            who=who,
            rule_name="autonomous_mission_requires_article_11",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="ALLOW",
            passed=True,
            reason="Complete 7-layer cognitive construction verified",
            params={"found_layers": list(found_layers), "task": task_desc}
        )
    except Exception as e:
        _log.warning(f"Failed to record CIEU for autonomous_mission success: {e}")

    return None


def _check_ceo_substantive_response_requires_article_11_trace(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule: ceo_substantive_response_requires_article_11_trace (AMENDMENT-013)

    CEO substantive responses (strategic decisions, reports, dispatches) must
    include Article 11 cognitive trace markers (L0-L7 or "第十一条" or "12层").

    Trigger conditions (any one):
    - agent_id == "ceo"
    - AND tool_call is Write/Edit to reports/ or knowledge/ceo/ OR tool_call is Agent (dispatch)
    - AND params contain strategic keywords: decide, plan, design, analyze, propose, 决策, 设计, 分析, 提议, 战略, 架构
    - OR content length > 500 chars (for writes/edits)

    Detection: Check if content contains Article 11 markers
    Action: WARN (not DENY) - emit CIEU event for audit trail, CEO self-corrects
    """
    if not agent_rules.get("article_11_always_on_substantive"):
        return None

    # Only applies to CEO
    if who != "ceo":
        return None

    # Check if this is a substantive response
    is_substantive = False
    content = ""

    # Strategic keywords
    strategic_keywords = [
        "decide", "plan", "design", "analyze", "propose",
        "决策", "设计", "分析", "提议", "战略", "架构"
    ]

    if tool_name in ["Write", "Edit"]:
        file_path = params.get("file_path", "")
        content = params.get("content", "") or params.get("new_string", "")

        # Check if writing to strategic paths
        if any(p in file_path for p in ["reports/", "knowledge/ceo/"]):
            # Check strategic keywords or length
            if any(kw in content for kw in strategic_keywords) or len(content) > 500:
                is_substantive = True

    elif tool_name == "Agent":
        # Dispatch is substantive
        is_substantive = True
        content = params.get("task", "") + params.get("instructions", "")

    if not is_substantive:
        return None

    # Check for Article 11 markers
    article_11_markers = [
        "L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7",
        "第0层", "第1层", "第2层", "第3层", "第4层", "第5层", "第6层", "第7层",
        "第十一条", "12层", "Article 11"
    ]

    has_marker = any(marker in content for marker in article_11_markers)

    event_type = "ARTICLE_11_INVOKED" if has_marker else "ARTICLE_11_OMITTED"

    try:
        _record_behavior_rule_cieu(
            who=who,
            rule_name="ceo_substantive_response_requires_article_11_trace",
            event_type="BEHAVIOR_RULE_WARNING",
            decision="WARN" if not has_marker else "PASS",
            passed=has_marker,
            reason=(
                "CEO substantive response includes Article 11 trace" if has_marker
                else "CEO substantive response missing Article 11 trace (L0-L7 markers)"
            ),
            params={
                "tool": tool_name,
                "has_marker": has_marker,
                "content_length": len(content),
                "event_type": event_type
            }
        )
    except Exception as e:
        _log.warning(f"Failed to record CIEU for article_11_trace: {e}")

    # Always return None (WARNING only, no block)
    return None


def _check_must_dispatch_via_cto(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 1: must_dispatch_via_cto (already implemented)

    CEO cannot use Agent tool to spawn eng-* agents directly.
    Must delegate to CTO first.

    CEO Mode Integration:
    - autonomous/break_glass modes: bypass this rule (CEO self-drive)

    AMENDMENT-012: Returns remediation with correct delegation steps.
    """
    if not agent_rules.get("must_dispatch_via_cto"):
        return None

    # Agent elevated modes bypass must_dispatch
    if who.lower() in ("ceo", "aiden-ceo", "aiden"):
        mode_state = _get_current_mode(agent_id="ceo")
        mode = mode_state.get("mode", "standard")
        if mode in ("autonomous", "break_glass"):
            _log.info(f"must_dispatch_via_cto bypassed for CEO in {mode} mode")
            return None  # allow

    if tool_name == "Agent":
        target_agent = params.get("subagent_type") or params.get("agent", "")
        _eng_prefixes = ("eng-", "Leo-", "Maya-", "Ryan-", "Jordan-")
        if target_agent.startswith(_eng_prefixes):
            reason = (
                f"Behavior rule violation: agent '{who}' must dispatch "
                f"engineering tasks via CTO, cannot directly spawn '{target_agent}'. "
                f"Use gov_delegate to delegate to CTO first."
            )

            # AMENDMENT-012: Structured remediation
            from ystar.session import Remediation
            task_desc = params.get("task", "...")
            remediation = Remediation(
                wrong_action=f'invoke("Agent", agent="{target_agent}", task="{task_desc[:50]}...")',
                correct_steps=[
                    f'invoke("Agent", agent="cto", task="{task_desc[:50]}...")',
                    'CTO will delegate to appropriate engineer (eng-kernel/platform/governance/domains)',
                    '(Alternative: write task card to .claude/tasks/cto-xxx.md for async queue)',
                ],
                skill_ref="knowledge/ceo/skills/ceo_delegation_chain.md",
                lesson_ref="knowledge/ceo/lessons/ceo_越权派工_2026_04_13.md",
                rule_name="must_dispatch_via_cto",
                rule_context="CEO is strategic coordinator, not technical dispatcher. CTO owns all engineering work allocation.",
            )

            try:
                _record_behavior_rule_cieu(
                    who=who,
                    rule_name="must_dispatch_via_cto",
                    event_type="BEHAVIOR_RULE_VIOLATION",
                    decision="DENY",
                    passed=False,
                    reason=reason,
                    params={"target_agent": target_agent}
                )
            except Exception as e:
                _log.warning(f"Failed to record CIEU for must_dispatch_via_cto: {e}")

            return PolicyResult(
                allowed=False,
                reason=reason,
                who=who,
                what=tool_name,
                violations=[],
                remediation=remediation,
            )

    return None


def _check_parallel_dispatch_required(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule: parallel_dispatch_required (DENY)

    CEO/CTO must dispatch multiple engineers in the same batch (parallel Agent calls),
    not sequentially in separate messages.

    Detection:
    - Track Agent tool calls per dispatcher (who) with timestamps
    - If dispatcher makes 2nd Agent call within SERIAL_DISPATCH_GAP seconds
      AND the calls are NOT in the same batch → DENY

    Batch detection:
    - Same batch = calls happen within <1 second (same tool_use block in Claude Code)
    - Serial = calls separated by >1 second but <30 seconds

    Exemption:
    - Different targets separated by >30s = allowed (different battle/context)
    """
    if not agent_rules.get("parallel_dispatch_required"):
        return None

    if tool_name != "Agent":
        return None

    target_agent = params.get("subagent_type") or params.get("agent", "")
    if not target_agent:
        return None

    # Only enforce for CEO and CTO dispatching engineers
    if who.lower() not in ("ceo", "aiden-ceo", "aiden", "cto", "ethan-cto", "ethan"):
        return None

    now = time.time()

    # Clean old history (keep only last 60s)
    if who in _AGENT_DISPATCH_HISTORY:
        _AGENT_DISPATCH_HISTORY[who] = [
            (ts, tgt) for ts, tgt in _AGENT_DISPATCH_HISTORY[who]
            if now - ts < _PARALLEL_DISPATCH_WINDOW
        ]
    else:
        _AGENT_DISPATCH_HISTORY[who] = []

    history = _AGENT_DISPATCH_HISTORY[who]

    # Check if there's a recent dispatch (within SERIAL_DISPATCH_GAP)
    if history:
        last_ts, last_target = history[-1]
        gap = now - last_ts

        # If gap is <1s, consider it same batch → OK
        if gap < 1.0:
            _log.info(f"parallel_dispatch: {who} → {target_agent} in same batch (gap={gap:.2f}s)")
            _AGENT_DISPATCH_HISTORY[who].append((now, target_agent))
            return None  # allow

        # If gap is ≥1s but <SERIAL_DISPATCH_GAP → DENY (serial dispatch detected)
        if gap < _SERIAL_DISPATCH_GAP:
            reason = (
                f"Behavior rule violation: agent '{who}' must dispatch multiple engineers "
                f"in the same message batch (parallel Agent calls), not sequentially. "
                f"Previous dispatch to '{last_target}' was {gap:.1f}s ago. "
                f"To fix: combine both Agent calls in one message using multiple tool_use blocks."
            )
            try:
                _record_behavior_rule_cieu(
                    who=who,
                    rule_name="parallel_dispatch_required",
                    event_type="BEHAVIOR_RULE_VIOLATION",
                    decision="DENY",
                    passed=False,
                    reason=reason,
                    params={
                        "current_target": target_agent,
                        "previous_target": last_target,
                        "gap_seconds": gap
                    }
                )
            except Exception as e:
                _log.warning(f"Failed to record CIEU for parallel_dispatch_required: {e}")

            return PolicyResult(
                allowed=False,
                reason=reason,
                who=who,
                what=tool_name,
                violations=[]
            )

    # Record this dispatch
    _AGENT_DISPATCH_HISTORY[who].append((now, target_agent))

    # If this is the first dispatch in window or gap >30s → allow
    return None


def _check_verification_before_assertion(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 2: verification_before_assertion

    Agent cannot assert impossibility without prior verification attempts.

    Detection: Write/Edit content contains "impossible", "can't", "不可能", "做不到"
    Check: Recent tool calls include verification attempts (Read/Grep/Bash)
    Action: WARNING if no verification found
    """
    if not agent_rules.get("verification_before_assertion"):
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    content = params.get("content", "") + params.get("new_string", "")
    assertion_keywords = [
        "impossible", "can't", "cannot", "不可能", "做不到",
        "没有这个能力", "无法", "not possible"
    ]

    if not any(kw in content.lower() for kw in assertion_keywords):
        return None

    # Check for verification attempts in recent tool calls
    recent_verifications = [
        call for call in _SESSION_TOOL_CALLS[-20:]
        if call["tool"] in ["Read", "Grep", "Bash", "Glob"]
    ]

    if not recent_verifications:
        reason = (
            f"Behavior rule warning: agent '{who}' asserted impossibility "
            f"without prior verification attempts. Consider using Read/Grep/Bash "
            f"to verify before making assertions."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="verification_before_assertion",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="WARNING",
            passed=False,
            reason=reason,
            params={"content_snippet": content[:200]}
        )
        _log.warning(reason)

    # Return None to allow (don't block, just warn via CIEU)
    return None


def _check_root_cause_fix_required(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 3: root_cause_fix_required

    After fixing a bug (editing code), must have prevention actions.

    Detection: Edit to a code file (.py, .js, .ts, etc.)
    Check: Within 30 minutes, write test or lesson or update docs
    Action: WARNING (checked in post-hook or delayed check)
    """
    if not agent_rules.get("root_cause_fix_required"):
        return None

    if tool_name not in ["Edit", "Write"]:
        return None

    file_path = params.get("file_path", "")
    code_extensions = [".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".c"]

    if not any(file_path.endswith(ext) for ext in code_extensions):
        return None

    # Track the edit
    _SESSION_FILE_EDITS[file_path] = time.time()

    # Check if there are recent test/lesson writes
    recent_prevention = [
        call for call in _SESSION_TOOL_CALLS[-20:]
        if call["tool"] in ["Write", "Edit"]
        and ("test" in call["params"].get("file_path", "").lower()
             or "lesson" in call["params"].get("file_path", "").lower()
             or "doc" in call["params"].get("file_path", "").lower())
    ]

    if not recent_prevention:
        reason = (
            f"Behavior rule warning: agent '{who}' edited code file '{file_path}' "
            f"but no prevention actions detected (tests, lessons, docs). "
            f"Consider adding tests or documenting the fix to prevent recurrence."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="root_cause_fix_required",
            event_type="BEHAVIOR_RULE_WARNING",
            decision="WARNING",
            passed=False,
            reason=reason,
            params={"file_path": file_path}
        )
        _log.warning(reason)

    return None


def _check_document_requires_execution_plan(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 4: document_requires_execution_plan

    Creating policy/protocol docs must be followed by execution.

    Detection: Write/Edit .md file with protocol/rule/framework keywords
    Check: Within 30 minutes, Agent dispatch or code modification
    Action: WARNING (checked in delayed check)
    """
    if not agent_rules.get("document_requires_execution_plan"):
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    file_path = params.get("file_path", "")
    if not file_path.endswith(".md"):
        return None

    # B2 fix 2026-04-12: exclude Claude Code auto-memory paths —
    # these are agent self-memory, not policy documents.
    if "/memory/" in file_path or file_path.endswith("/MEMORY.md"):
        return None

    content = params.get("content", "") + params.get("new_string", "")
    policy_keywords = [
        "协议", "protocol", "mechanism", "规则", "rule",
        "框架", "framework", "policy", "governance"
    ]

    if not any(kw in content.lower() for kw in policy_keywords):
        return None

    # Track document creation
    _SESSION_DOCUMENTS_CREATED[file_path] = time.time()

    # Check for execution actions in recent calls
    recent_execution = [
        call for call in _SESSION_TOOL_CALLS[-20:]
        if call["tool"] == "Agent"
        or (call["tool"] in ["Edit", "Write"]
            and not call["params"].get("file_path", "").endswith(".md"))
    ]

    if not recent_execution:
        reason = (
            f"Behavior rule warning: agent '{who}' created policy document "
            f"'{file_path}' but no execution actions detected. "
            f"Consider dispatching tasks or implementing the protocol."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="document_requires_execution_plan",
            event_type="BEHAVIOR_RULE_WARNING",
            decision="WARN",
            passed=False,
            reason=reason,
            params={"file_path": file_path}
        )
        _log.warning(reason)

    return None


def _check_no_fabrication(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 5: no_fabrication

    Agent cannot cite data/statistics without verification.

    Detection: Write/Edit with numbers, percentages, dollar amounts
    Check: Recent Read/Grep/Bash data queries
    Action: WARNING if no data verification found
    """
    if not agent_rules.get("no_fabrication"):
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    content = params.get("content", "") + params.get("new_string", "")

    # Check for statistics/numbers
    import re
    has_stats = (
        re.search(r'\d+%', content)  # Percentages
        or re.search(r'\$\d+', content)  # Dollar amounts
        or re.search(r'\d+\s*(users|customers|records|events)', content)  # Counts
    )

    if not has_stats:
        return None

    # Check for data verification in recent calls
    recent_data_queries = [
        call for call in _SESSION_TOOL_CALLS[-20:]
        if call["tool"] in ["Read", "Grep", "Bash"]
    ]

    if not recent_data_queries:
        reason = (
            f"Behavior rule warning: agent '{who}' included statistics/data "
            f"without prior verification queries. Consider using Read/Grep/Bash "
            f"to verify data before citing it."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="no_fabrication",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"content_snippet": content[:200]}
        )
        _log.warning(reason)

    return None


def _check_counterfactual_before_major_decision(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 6: counterfactual_before_major_decision

    Major decisions (Level 2/3) require counterfactual analysis.

    Detection: Agent dispatch or Write decision document
    Check: Recent tool calls contain counterfactual keywords
    Action: WARNING if no counterfactual found
    """
    if not agent_rules.get("counterfactual_before_major_decision"):
        return None

    is_major_decision = (
        (tool_name == "Agent" and "Level 2" in params.get("task", "")
         or "Level 3" in params.get("task", ""))
        or (tool_name in ["Write", "Edit"]
            and "decision" in params.get("file_path", "").lower())
    )

    if not is_major_decision:
        return None

    # Check for counterfactual analysis
    counterfactual_keywords = [
        "如果", "what if", "假设", "counterfactual",
        "alternative", "反事实", "如果不", "instead"
    ]

    has_counterfactual = False
    for call in _SESSION_TOOL_CALLS[-30:]:
        call_params = call.get("params", {})
        content = str(call_params.get("content", "")) + str(call_params.get("new_string", ""))
        if any(kw in content.lower() for kw in counterfactual_keywords):
            has_counterfactual = True
            break

    if not has_counterfactual:
        reason = (
            f"Behavior rule warning: agent '{who}' making major decision "
            f"without counterfactual analysis. Consider exploring alternatives "
            f"and 'what if' scenarios before proceeding."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="counterfactual_before_major_decision",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"tool": tool_name}
        )
        _log.warning(reason)

    return None


def _check_must_check_health_on_session_start(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 7: must_check_health_on_session_start

    First 5 tool calls of session must include health checks.

    Detection: Session tool call count < 5
    Check: Health check tools in first 5 calls (Read learning_report, CIEU, gov_health)
    Action: WARNING if no health check by call #5
    """
    if not agent_rules.get("must_check_health_on_session_start"):
        return None

    call_count = len(_SESSION_TOOL_CALLS)

    # Only check at call #5
    if call_count != 5:
        return None

    # Check if any of first 5 calls were health checks
    health_patterns = [
        "learning_report", "cieu", "gov_health", "doctor",
        "handoff", "status", "obligation"
    ]

    has_health_check = False
    for call in _SESSION_TOOL_CALLS[:5]:
        tool = call["tool"].lower()
        params_str = str(call["params"]).lower()

        if any(pattern in tool or pattern in params_str for pattern in health_patterns):
            has_health_check = True
            break

    if not has_health_check:
        reason = (
            f"Behavior rule warning: agent '{who}' completed 5 tool calls "
            f"without health check. First 5 calls should include reading "
            f"learning_report, CIEU status, or governance health."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="must_check_health_on_session_start",
            event_type="BEHAVIOR_RULE_WARNING",
            decision="WARNING",
            passed=False,
            reason=reason,
            params={"call_count": call_count}
        )
        _log.warning(reason)

    return None


def _check_completion_requires_cieu_audit(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 10: completion_requires_cieu_audit

    Before marking task as complete, must audit CIEU to confirm Rt=0.

    Detection: Write/Edit with completion markers (e.g., "完成", "done", "completed")
    Check: Recent CIEU audit calls (gov_audit, gov_check, Read .ystar_cieu.db)
    Action: WARNING if no CIEU audit found before completion claim
    """
    if not agent_rules.get("completion_requires_cieu_audit"):
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    content = params.get("content", "") + params.get("new_string", "")
    completion_keywords = [
        "完成", "done", "completed", "finished", "任务完成",
        "Task completed", "Mission accomplished", "All done",
        "Rt=0", "residue=0", "零残留"
    ]

    # Check if content contains completion markers
    if not any(kw in content for kw in completion_keywords):
        return None

    # Check for CIEU audit in recent tool calls
    recent_audits = [
        call for call in _SESSION_TOOL_CALLS[-20:]
        if (call["tool"] in ["Bash", "Read"]
            and ("cieu" in str(call["params"]).lower()
                 or "gov_audit" in str(call["params"]).lower()
                 or "gov_check" in str(call["params"]).lower()))
        or (call["tool"].startswith("mcp__gov-mcp__gov_audit")
            or call["tool"].startswith("mcp__gov-mcp__gov_check"))
    ]

    if not recent_audits:
        reason = (
            f"Behavior rule warning: agent '{who}' claiming task completion "
            f"without CIEU audit. Before marking complete, run 'gov_audit' "
            f"or check CIEU database to confirm Rt=0 (zero residue)."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="completion_requires_cieu_audit",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"content_snippet": content[:200]}
        )
        _log.warning(reason)

    return None


def _check_pre_commit_requires_test(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 11: pre_commit_requires_test (CTO + eng-*)

    Git commit must be preceded by successful test run in same session.

    Detection: Bash command contains "git commit"
    Check: Recent tool calls include test run (pytest, npm test, etc.)
    Action: DENY if no test run found
    """
    if not agent_rules.get("pre_commit_requires_test"):
        return None

    if tool_name != "Bash":
        return None

    command = params.get("command", "")
    if "git commit" not in command:
        return None

    # Check for test runs in recent session
    test_patterns = ["pytest", "python -m pytest", "npm test", "cargo test", "go test"]
    recent_tests = [
        call for call in _SESSION_TOOL_CALLS[-30:]
        if call["tool"] == "Bash" and any(pattern in call["params"].get("command", "") for pattern in test_patterns)
    ]

    if not recent_tests:
        reason = (
            f"Behavior rule violation: agent '{who}' attempting git commit "
            f"without running tests first. Run pytest or equivalent before committing."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="pre_commit_requires_test",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"command": command[:200]}
        )
        return PolicyResult(
            allowed=False,
            reason=reason,
            who=who,
            what=tool_name,
            violations=[],
        )

    return None


def _check_source_first_fixes(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 12: source_first_fixes (CTO + eng-*)

    Bug fixes must be made in source repository, not site-packages.

    Detection: Write/Edit to site-packages/ or .venv/ or venv/ paths
    Action: DENY with message to fix in source repo
    """
    if not agent_rules.get("source_first_fixes"):
        return None

    if tool_name not in _WRITE_TOOLS:
        return None

    file_path = params.get("file_path", "")
    forbidden_patterns = [
        "site-packages/",
        ".venv/",
        "venv/",
        "env/lib/python",
        "lib/python3",
        "/dist-packages/",
    ]

    norm_path = os.path.normpath(file_path).replace("\\", "/")

    for pattern in forbidden_patterns:
        if pattern in norm_path:
            reason = (
                f"Behavior rule violation: agent '{who}' attempting to edit "
                f"installed package at '{file_path}'. Bug fixes must be made in "
                f"the source repository (e.g., Y-star-gov/), then rebuilt and reinstalled."
            )
            _record_behavior_rule_cieu(
                who=who,
                rule_name="source_first_fixes",
                event_type="BEHAVIOR_RULE_VIOLATION",
                decision="DENY",
                passed=False,
                reason=reason,
                params={"file_path": file_path}
            )
            return PolicyResult(
                allowed=False,
                reason=reason,
                who=who,
                what=tool_name,
                violations=[],
            )

    return None


def _check_directive_decompose_timeout(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 13: directive_decompose_timeout (CEO)

    Board directives must be decomposed to DIRECTIVE_TRACKER.md within N minutes.

    Detection: Write to DIRECTIVE_TRACKER.md
    Check: Track time delta from session start (proxy for directive receipt)
    Action: WARNING if decomposition took too long
    """
    timeout_minutes = agent_rules.get("directive_decompose_within_minutes")
    if not timeout_minutes:
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    file_path = params.get("file_path", "")
    if "DIRECTIVE_TRACKER" not in file_path:
        return None

    # Check time since session start
    elapsed_seconds = time.time() - _SESSION_START_TIME
    elapsed_minutes = elapsed_seconds / 60

    if elapsed_minutes > timeout_minutes:
        reason = (
            f"Behavior rule warning: agent '{who}' decomposed directive to "
            f"DIRECTIVE_TRACKER.md after {elapsed_minutes:.1f} minutes "
            f"(timeout: {timeout_minutes} minutes). Board directives should be "
            f"decomposed immediately."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="directive_decompose_timeout",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"elapsed_minutes": elapsed_minutes, "timeout_minutes": timeout_minutes}
        )
        _log.warning(reason)

    return None


def _check_content_length_check(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 14: content_length_check (CMO)

    Content for external platforms must respect platform limits.

    Detection: Write to content/outreach/ or marketing/social/
    Check: Content length against known platform limits
    Action: WARNING if content exceeds limits
    """
    if not agent_rules.get("content_length_check"):
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    file_path = params.get("file_path", "")
    norm_path = os.path.normpath(file_path).replace("\\", "/")

    # Platform-specific paths and limits
    platform_limits = {
        "twitter": (280, ["twitter/", "x.com/"]),
        "linkedin": (3000, ["linkedin/"]),
        "hackernews": (None, ["hackernews/", "hn/"]),  # No hard limit but conciseness valued
    }

    content = params.get("content", "") + params.get("new_string", "")

    for platform, (limit, path_patterns) in platform_limits.items():
        if any(pattern in norm_path for pattern in path_patterns):
            if limit and len(content) > limit:
                reason = (
                    f"Behavior rule warning: agent '{who}' writing {platform} content "
                    f"({len(content)} chars) exceeding platform limit ({limit} chars). "
                    f"Consider shortening or splitting into thread."
                )
                _record_behavior_rule_cieu(
                    who=who,
                    rule_name="content_length_check",
                    event_type="BEHAVIOR_RULE_VIOLATION",
                    decision="DENY",
                    passed=False,
                    reason=reason,
                    params={
                        "platform": platform,
                        "content_length": len(content),
                        "limit": limit
                    }
                )
                _log.warning(reason)

    return None


def _check_board_approval_before_publish(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 15: board_approval_before_publish (CMO, CSO)

    External posts/outreach require Board approval marker before publishing.

    Detection: Write to content/outreach/ or marketing/social/
    Check: Content contains approval marker (e.g., [BOARD_APPROVED])
    Action: DENY if no approval marker found
    """
    if not agent_rules.get("board_approval_before_publish"):
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    file_path = params.get("file_path", "")
    norm_path = os.path.normpath(file_path).replace("\\", "/")

    # Paths requiring approval
    approval_paths = ["content/outreach/", "marketing/social/", "sales/outreach/"]

    if not any(pattern in norm_path for pattern in approval_paths):
        return None

    content = params.get("content", "") + params.get("new_string", "")
    approval_markers = [
        "[BOARD_APPROVED]",
        "[APPROVED]",
        "Board approved:",
        "Approved by Board",
    ]

    if not any(marker in content for marker in approval_markers):
        reason = (
            f"Behavior rule violation: agent '{who}' attempting to write external "
            f"content to '{file_path}' without Board approval marker. "
            f"Add [BOARD_APPROVED] marker or submit for approval first."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="board_approval_before_publish",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"file_path": file_path, "content_length": len(content)}
        )
        return PolicyResult(
            allowed=False,
            reason=reason,
            who=who,
            what=tool_name,
            violations=[],
        )

    return None


def _check_real_conversation_count_required(
    who: str, tool_name: str, params: dict, agent_rules: dict
) -> Optional[PolicyResult]:
    """
    Rule 16: real_conversation_count_required (CSO)

    Daily reports must include real external conversation count.

    Detection: Write to reports/daily/ or reports/cso/
    Check: Content contains conversation count (e.g., "conversations: N")
    Action: WARNING if no conversation count found
    """
    if not agent_rules.get("real_conversation_count_required"):
        return None

    if tool_name not in ["Write", "Edit"]:
        return None

    file_path = params.get("file_path", "")
    norm_path = os.path.normpath(file_path).replace("\\", "/")

    # Paths requiring conversation count
    report_paths = ["reports/daily/", "reports/cso/", "reports/autonomous/"]

    if not any(pattern in norm_path for pattern in report_paths):
        return None

    content = params.get("content", "") + params.get("new_string", "")

    # Check for conversation count patterns
    conversation_patterns = [
        r"conversations?:\s*\d+",
        r"外部对话:\s*\d+",
        r"real conversations?:\s*\d+",
        r"talked to \d+ (people|users|customers)",
        r"与\s*\d+\s*(人|用户|客户)",
    ]

    import re
    has_conversation_count = any(
        re.search(pattern, content, re.IGNORECASE)
        for pattern in conversation_patterns
    )

    if not has_conversation_count:
        reason = (
            f"Behavior rule warning: agent '{who}' writing report to '{file_path}' "
            f"without real conversation count. CSO reports must include "
            f"'conversations: N' to track external engagement."
        )
        _record_behavior_rule_cieu(
            who=who,
            rule_name="real_conversation_count_required",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"file_path": file_path}
        )
        _log.warning(reason)

    return None


def _check_behavior_rules(
    who: str, tool_name: str, params: dict, session_cfg: Any = _SENTINEL
) -> Optional[PolicyResult]:
    """
    Check agent-specific behavior rules from session config.

    Implemented rules:
    1. must_dispatch_via_cto: CEO cannot spawn eng-* directly (DENY)
    2. verification_before_assertion: Cannot assert impossibility without verification (WARNING)
    3. root_cause_fix_required: Bug fixes must have prevention actions (WARNING)
    4. document_requires_execution_plan: Policy docs must be followed by execution (WARNING)
    5. no_fabrication: Cannot cite data without verification (WARNING)
    6. counterfactual_before_major_decision: Major decisions need counterfactual (WARNING)
    7. must_check_health_on_session_start: First 5 calls include health check (WARNING)
    8. extract_board_values_on_session_close: (Checked at session end)
    9. autonomous_mission_requires_article_11: Autonomous tasks need 7-layer construction (DENY)
    10. completion_requires_cieu_audit: Task completion must audit CIEU for Rt=0 (WARNING)
    11. pre_commit_requires_test: Git commit requires test run (DENY)
    12. source_first_fixes: Bug fixes in source repo, not site-packages (DENY)
    13. directive_decompose_timeout: Directive decomposition within N minutes (WARNING)
    14. content_length_check: Content respects platform limits (WARNING)
    15. board_approval_before_publish: External content needs approval (DENY)
    16. real_conversation_count_required: Reports include conversation count (WARNING)

    Args:
        who: Agent ID
        tool_name: Tool being called
        params: Tool parameters
        session_cfg: Optional session config dict (for testing/injection).

    Returns:
        None if allowed, PolicyResult(allowed=False) if rule violated
    """
    # Track this tool call
    _track_tool_call(who, tool_name, params)

    # ── Session lifecycle auto-detection (Board 2026-04-11) ──
    # Runs regardless of per-agent rules cfg
    try:
        from ystar.adapters.identity_detector import _load_session_config
        _cfg_lc = _load_session_config()
        if _cfg_lc is None:
            # No session config → test mode → skip session lifecycle tracking
            _sid = None
        else:
            _sid = _cfg_lc.get("session_id", "unknown")
    except Exception:
        _sid = "unknown"
    # Skip session lifecycle tracking in test mode (_sid is None)
    if _sid is not None:
        _hydrate_protocol_state(_sid)

        # Detector 1: continuation_loaded
        if tool_name == "Read":
            _fp = str(params.get("file_path", "")).replace("\\", "/")
            if _fp.endswith("memory/continuation.json") or _fp.endswith("memory/continuation.md"):
                _emit_once(_sid, "continuation_loaded", who, extra={"file": _fp})

        # Detector 2: obligation_check
        if tool_name == "mcp__gov-mcp__gov_obligations":
            _emit_once(_sid, "obligation_check", who, extra={"tool": tool_name})
        elif tool_name == "Read" and "omission" in str(params.get("file_path", "")).lower():
            _emit_once(_sid, "obligation_check", who,
                       extra={"tool": tool_name, "via": "omission_db_read"})

        # Detector 3: boot_protocol_completed (all three present)
        _seen = _PROTOCOL_STATE.get(_sid, set())
        if {"session_start", "continuation_loaded", "obligation_check"}.issubset(_seen) \
                and "boot_protocol_completed" not in _seen:
            _emit_once(_sid, "boot_protocol_completed", who)

        # ── NEW DENY rule: session start protocol must complete ──
        protocol_deny = _check_session_start_protocol_completed(who, tool_name, params, session_cfg)
        if protocol_deny is not None:
            return protocol_deny

    cfg = _get_behavior_rules_config() if session_cfg is _SENTINEL else session_cfg
    if not cfg:
        return None

    behavior_rules = cfg.get("agent_behavior_rules", {})
    if not behavior_rules:
        return None

    agent_rules = behavior_rules.get(who, {})
    if not agent_rules:
        return None

    # Check rules in priority order (DENY rules first, then WARNING rules)

    # DENY rules (can block execution)
    deny_result = _check_autonomous_mission_requires_article_11(who, tool_name, params, agent_rules)
    if deny_result is not None:
        return deny_result

    deny_result = _check_must_dispatch_via_cto(who, tool_name, params, agent_rules)
    if deny_result is not None:
        return deny_result

    deny_result = _check_parallel_dispatch_required(who, tool_name, params, agent_rules)
    if deny_result is not None:
        return deny_result

    deny_result = _check_pre_commit_requires_test(who, tool_name, params, agent_rules)
    if deny_result is not None:
        return deny_result

    deny_result = _check_source_first_fixes(who, tool_name, params, agent_rules)
    if deny_result is not None:
        return deny_result

    deny_result = _check_board_approval_before_publish(who, tool_name, params, agent_rules)
    if deny_result is not None:
        return deny_result

    # WARNING rules (log but don't block)
    _check_ceo_substantive_response_requires_article_11_trace(who, tool_name, params, agent_rules)
    _check_verification_before_assertion(who, tool_name, params, agent_rules)
    _check_root_cause_fix_required(who, tool_name, params, agent_rules)
    _check_document_requires_execution_plan(who, tool_name, params, agent_rules)
    _check_no_fabrication(who, tool_name, params, agent_rules)
    _check_counterfactual_before_major_decision(who, tool_name, params, agent_rules)
    _check_must_check_health_on_session_start(who, tool_name, params, agent_rules)
    _check_completion_requires_cieu_audit(who, tool_name, params, agent_rules)
    _check_directive_decompose_timeout(who, tool_name, params, agent_rules)
    _check_content_length_check(who, tool_name, params, agent_rules)
    _check_real_conversation_count_required(who, tool_name, params, agent_rules)

    return None


def _check_task_type_symbols(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """
    Symbol Sync System: check that required checkpoint symbols exist in CIEU
    before allowing execution actions.

    Flow:
    1. Query CIEU for active intent (INTENT_RECORDED with no INTENT_COMPLETED) for this agent
    2. If no active intent, skip (not in a tracked task)
    3. Get task_type from intent's params
    4. Look up required symbols for this task_type from session config
    5. Query CIEU for LAYER_COMPLETED events matching this intent's entity_id
    6. If any required symbols missing, DENY with list of what's missing
    """
    # Only check on execution actions (Write, Edit, Bash, Agent)
    execution_tools = {"Write", "Edit", "Bash", "Agent", "NotebookEdit"}
    if tool_name not in execution_tools:
        return None

    try:
        from ystar.adapters.identity_detector import _load_session_config
        cfg = _load_session_config()
        if not cfg:
            return None

        task_type_symbols = cfg.get("task_type_symbols")
        if not task_type_symbols:
            return None

        # Query CIEU for active intent
        import sqlite3
        import json as _json_mod
        cieu_db = cfg.get("cieu_db", ".ystar_cieu.db")
        if not os.path.exists(cieu_db):
            return None

        conn = sqlite3.connect(cieu_db, timeout=2)

        # Find most recent active intent for this agent
        # Active = INTENT_RECORDED exists but no matching INTENT_COMPLETED
        row = conn.execute("""
            SELECT event_id, params_json, task_description
            FROM cieu_events
            WHERE agent_id = ?
            AND event_type = 'INTENT_RECORDED'
            AND event_id NOT IN (
                SELECT COALESCE(json_extract(params_json, '$.intent_id'), '')
                FROM cieu_events
                WHERE event_type = 'INTENT_COMPLETED' AND agent_id = ?
            )
            ORDER BY created_at DESC LIMIT 1
        """, (who, who)).fetchone()

        if not row:
            conn.close()
            return None  # No active intent, skip

        intent_event_id, params_json_str, task_desc = row

        # Parse intent params to get task_type
        try:
            intent_params = _json_mod.loads(params_json_str) if params_json_str else {}
        except Exception:
            intent_params = {}

        task_type = intent_params.get("task_type", "")
        if not task_type or task_type not in task_type_symbols:
            conn.close()
            return None  # Unknown task type, skip

        required = task_type_symbols[task_type].get("required", [])
        if not required:
            conn.close()
            return None

        # Get entity_id for this intent
        entity_id = intent_params.get("entity_id", intent_event_id)

        # Query CIEU for completed layer symbols
        completed_rows = conn.execute("""
            SELECT DISTINCT json_extract(params_json, '$.symbol')
            FROM cieu_events
            WHERE event_type = 'LAYER_COMPLETED'
            AND (json_extract(params_json, '$.entity_id') = ? OR task_description LIKE ?)
            AND agent_id = ?
        """, (entity_id, f"%{entity_id}%", who)).fetchall()

        conn.close()

        completed_symbols = {r[0] for r in completed_rows if r[0]}
        missing = [s for s in required if s not in completed_symbols]

        if missing:
            completed_count = len(required) - len(missing)
            reason = (
                f"Symbol checkpoint: task '{task_type}' requires {len(required)} layers, "
                f"{completed_count} completed, {len(missing)} missing: {missing}. "
                f"Complete these steps and write LAYER_COMPLETED events to CIEU before executing."
            )
            return PolicyResult(
                allowed=False,
                reason=reason,
                who=who,
                what=tool_name,
                violations=[],
            )

        return None  # All symbols present, allow

    except Exception as e:
        _log.debug(f"Symbol check error (fail-open): {e}")
        return None  # Fail-open on errors to not block normal work


# ======================================================================
# Governance-Gap Enforcement Rules (ACTION-1, ACTION-3, CIEU-1,
# IMMUT-3, PUB-3, BOOT-1, DIR-1)
# ======================================================================


def _check_no_email_to_humans(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """ACTION-1: no_email_to_humans (WARNING only, never blocks)."""
    triggered = False
    detail = ""

    if tool_name == "Bash":
        cmd = params.get("command", "")
        email_patterns = [
            r"\bsendmail\b", r"\bmail\s+-s\b", r"\bmutt\b",
            r"\bcurl\b.*\bsmtp\b", r"\bpython.*\bsmtplib\b",
            r"\bsendgrid\b", r"\bmailgun\b", r"\bpostmark\b",
            r"\bnodemailer\b",
        ]
        for pat in email_patterns:
            if re.search(pat, cmd, re.IGNORECASE):
                triggered = True
                detail = "Bash command matches email pattern: " + pat
                break

    tool_lower = tool_name.lower()
    if any(kw in tool_lower for kw in ("mail", "gmail", "email", "smtp")):
        triggered = True
        detail = "MCP tool name matches email keyword: " + tool_name

    if triggered:
        reason = (
            "ACTION-1 WARNING: Detected possible email to humans. " + detail + ". "
            "Board is evaluating tiered email authorization. Proceeding with warning."
        )
        try:
            _record_behavior_rule_cieu(
                who=who,
                rule_name="ACTION-1_no_email_to_humans",
                event_type="BEHAVIOR_RULE_WARNING",
                decision="WARNING",
                passed=False,
                reason=reason,
                params={"tool": tool_name, "detail": detail},
            )
        except Exception as e:
            _log.warning("Failed to record CIEU for ACTION-1: %s" % e)
        _log.warning(reason)

    return None


def _check_merge_to_main_requires_board_approval(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """ACTION-3: merge_to_main_requires_approval (DENY)."""
    if tool_name != "Bash":
        return None

    cmd = params.get("command", "")
    merge_patterns = [
        r"git\s+merge\s+.*\bmain\b",
        r"git\s+merge\s+.*\bmaster\b",
        r"git\s+push\s+.*\bmain\b",
        r"git\s+push\s+.*\bmaster\b",
        r"git\s+push\s+origin\s+main\b",
        r"git\s+push\s+origin\s+master\b",
    ]

    if not any(re.search(p, cmd, re.IGNORECASE) for p in merge_patterns):
        return None

    try:
        import sqlite3
        from ystar.adapters.identity_detector import _load_session_config
        cfg = _load_session_config()
        cieu_db = cfg.get("cieu_db", ".ystar_cieu.db") if cfg else ".ystar_cieu.db"

        if os.path.exists(cieu_db):
            conn = sqlite3.connect(cieu_db, timeout=2)
            cutoff = time.time() - 86400
            row = conn.execute(
                "SELECT event_id FROM cieu_events"
                " WHERE event_type IN ('BOARD_APPROVED', 'BOARD_APPROVAL')"
                " AND created_at > datetime(cast(? as text), 'unixepoch')"
                " ORDER BY created_at DESC LIMIT 1",
                (cutoff,)
            ).fetchone()
            conn.close()
            if row:
                return None
    except Exception as e:
        _log.warning("ACTION-3 CIEU query error (fail-safe DENY): %s" % e)

    reason = (
        "ACTION-3 DENY: git merge/push to main requires Board approval. "
        "No BOARD_APPROVED event found in CIEU within 24h. "
        "Get Board approval before merging to main."
    )
    try:
        _record_behavior_rule_cieu(
            who=who,
            rule_name="ACTION-3_merge_main_board_approval",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"command": cmd},
        )
    except Exception as e:
        _log.warning("Failed to record CIEU for ACTION-3: %s" % e)

    return PolicyResult(
        allowed=False,
        reason=reason,
        who=who,
        what=tool_name,
        violations=[],
    )


def _check_cieu_archive_before_delete(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """CIEU-1: cieu_archive_before_delete (DENY)."""
    target_file = ".ystar_cieu.db"
    triggered = False

    if tool_name == "Bash":
        cmd = params.get("command", "")
        delete_patterns = [
            r"\brm\b.*" + re.escape(target_file),
            r">\s*" + re.escape(target_file),
            r"\btruncate\b.*" + re.escape(target_file),
            r"sqlite3\s+.*" + re.escape(target_file) + r".*\b(DELETE|DROP)\b",
        ]
        if any(re.search(p, cmd, re.IGNORECASE) for p in delete_patterns):
            triggered = True

    elif tool_name in ("Write", "Edit"):
        file_path = params.get("file_path", "")
        if target_file in file_path:
            triggered = True

    if not triggered:
        return None

    try:
        import sqlite3
        from ystar.adapters.identity_detector import _load_session_config
        cfg = _load_session_config()
        cieu_db = cfg.get("cieu_db", target_file) if cfg else target_file

        if os.path.exists(cieu_db):
            conn = sqlite3.connect(cieu_db, timeout=2)
            cutoff = time.time() - 3600
            row = conn.execute(
                "SELECT event_id FROM cieu_events"
                " WHERE event_type IN ('ARCHIVE_COMPLETED', 'CIEU_ARCHIVED')"
                " AND created_at > datetime(cast(? as text), 'unixepoch')"
                " ORDER BY created_at DESC LIMIT 1",
                (cutoff,)
            ).fetchone()
            conn.close()
            if row:
                return None
    except Exception as e:
        _log.warning("CIEU-1 query error (fail-safe DENY): %s" % e)

    reason = (
        "CIEU-1 DENY: Cannot delete/truncate .ystar_cieu.db without archiving first. "
        "No ARCHIVE_COMPLETED or CIEU_ARCHIVED event found within 1h. "
        "Run archive before deleting CIEU data."
    )
    try:
        _record_behavior_rule_cieu(
            who=who,
            rule_name="CIEU-1_archive_before_delete",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"tool": tool_name},
        )
    except Exception as e:
        _log.warning("Failed to record CIEU for CIEU-1: %s" % e)

    return PolicyResult(
        allowed=False,
        reason=reason,
        who=who,
        what=tool_name,
        violations=[],
    )


def _check_knowledge_cases_append_only(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """IMMUT-3: knowledge_cases_append_only (DENY)."""
    if tool_name not in ("Write", "Edit"):
        return None

    file_path = params.get("file_path", "")
    if "knowledge/cases/" not in file_path:
        return None

    if tool_name == "Edit":
        reason = (
            "IMMUT-3 DENY: knowledge/cases/ files are append-only. "
            "Edit (modify existing content) is not allowed. "
            "Create a new case file instead of modifying existing ones."
        )
        try:
            _record_behavior_rule_cieu(
                who=who,
                rule_name="IMMUT-3_knowledge_cases_append_only",
                event_type="BEHAVIOR_RULE_VIOLATION",
                decision="DENY",
                passed=False,
                reason=reason,
                params={"file_path": file_path, "tool": tool_name},
            )
        except Exception as e:
            _log.warning("Failed to record CIEU for IMMUT-3: %s" % e)

        return PolicyResult(
            allowed=False,
            reason=reason,
            who=who,
            what=tool_name,
            violations=[],
        )

    if tool_name == "Write" and os.path.exists(file_path):
        reason = (
            "IMMUT-3 DENY: knowledge/cases/ files are append-only. "
            "File already exists: " + file_path + ". "
            "Write to a new file instead of overwriting existing case files."
        )
        try:
            _record_behavior_rule_cieu(
                who=who,
                rule_name="IMMUT-3_knowledge_cases_append_only",
                event_type="BEHAVIOR_RULE_VIOLATION",
                decision="DENY",
                passed=False,
                reason=reason,
                params={"file_path": file_path, "tool": tool_name},
            )
        except Exception as e:
            _log.warning("Failed to record CIEU for IMMUT-3: %s" % e)

        return PolicyResult(
            allowed=False,
            reason=reason,
            who=who,
            what=tool_name,
            violations=[],
        )

    return None


def _check_publish_requires_cieu_validation(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """PUB-3: publish_requires_cieu_record (DENY)."""
    if tool_name != "Bash":
        return None

    cmd = params.get("command", "")
    publish_patterns = [
        r"\bnpm\s+publish\b",
        r"\btwine\s+upload\b",
        r"\bgh\s+release\s+create\b",
        r"\bdocker\s+push\b",
        r"\bwrangler\s+(deploy|publish)\b",
        r"\bvercel\s+--prod\b",
        r"\bpython\s+setup\.py\s+upload\b",
    ]

    if not any(re.search(p, cmd, re.IGNORECASE) for p in publish_patterns):
        return None

    try:
        import sqlite3
        from ystar.adapters.identity_detector import _load_session_config
        cfg = _load_session_config()
        cieu_db = cfg.get("cieu_db", ".ystar_cieu.db") if cfg else ".ystar_cieu.db"

        if os.path.exists(cieu_db):
            conn = sqlite3.connect(cieu_db, timeout=2)
            cutoff = time.time() - 3600
            row = conn.execute(
                "SELECT event_id FROM cieu_events"
                " WHERE event_type IN ("
                "  'PUBLISH_VALIDATED', 'QUALITY_CHECK_PASSED',"
                "  'BOARD_APPROVED', 'RELEASE_APPROVED'"
                " )"
                " AND created_at > datetime(cast(? as text), 'unixepoch')"
                " ORDER BY created_at DESC LIMIT 1",
                (cutoff,)
            ).fetchone()
            conn.close()
            if row:
                return None
    except Exception as e:
        _log.warning("PUB-3 CIEU query error (fail-safe DENY): %s" % e)

    reason = (
        "PUB-3 DENY: Publishing requires CIEU validation record. "
        "No PUBLISH_VALIDATED, QUALITY_CHECK_PASSED, BOARD_APPROVED, "
        "or RELEASE_APPROVED event found within 1h. "
        "Complete quality checks before publishing."
    )
    try:
        _record_behavior_rule_cieu(
            who=who,
            rule_name="PUB-3_publish_requires_cieu_validation",
            event_type="BEHAVIOR_RULE_VIOLATION",
            decision="DENY",
            passed=False,
            reason=reason,
            params={"command": cmd},
        )
    except Exception as e:
        _log.warning("Failed to record CIEU for PUB-3: %s" % e)

    return PolicyResult(
        allowed=False,
        reason=reason,
        who=who,
        what=tool_name,
        violations=[],
    )


def _check_no_multiple_choice(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """BOOT-1: no_multiple_choice (WARNING only, never blocks)."""
    if tool_name not in ("Write", "Edit"):
        return None

    content = params.get("content", "") + params.get("new_string", "")
    if not content:
        return None

    board_keywords = ["\u8001\u5927", "Board", "\u8bf7\u9009\u62e9",
                      "please choose", "pick one", "which option"]
    if not any(kw.lower() in content.lower() for kw in board_keywords):
        return None

    option_patterns = [
        r"(?m)^\s*[1-9]\.\s+\S",
        r"(?m)^\s*[A-D]\)\s+\S",
        "\u9009\u9879[1-9]",
        r"Option\s+[1-9]",
        r"(?m)^\s*-\s+\*\*[A-D]\b",
    ]
    if not any(re.search(p, content) for p in option_patterns):
        return None

    reason = (
        "BOOT-1 WARNING: Detected multiple-choice pattern in output to Board. "
        "Agents should provide direct recommendations, not option menus."
    )
    try:
        _record_behavior_rule_cieu(
            who=who,
            rule_name="BOOT-1_no_multiple_choice",
            event_type="BEHAVIOR_RULE_WARNING",
            decision="WARNING",
            passed=False,
            reason=reason,
            params={"tool": tool_name},
        )
    except Exception as e:
        _log.warning("Failed to record CIEU for BOOT-1: %s" % e)
    _log.warning(reason)

    return None


def _check_directive_must_record_to_tracker(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """DIR-1: directive_tracker_required (WARNING only, never blocks)."""
    directive_keywords = [
        "Board\u6307\u4ee4", "\u8001\u5927\u8bf4", "directive",
        "Board\u8981\u6c42", "Board decision",
    ]

    text_to_check = ""
    if tool_name == "Agent":
        text_to_check = params.get("task", "") + params.get("prompt", "")
    elif tool_name in ("Write", "Edit"):
        text_to_check = (
            params.get("content", "") + params.get("new_string", "")
        )
    elif tool_name == "Bash":
        text_to_check = params.get("command", "")

    if not text_to_check:
        return None

    if not any(kw.lower() in text_to_check.lower() for kw in directive_keywords):
        return None

    tracker_updated = False
    for call in _SESSION_TOOL_CALLS[-30:]:
        if call.get("tool") in ("Write", "Edit"):
            fp = call.get("params", {}).get("file_path", "")
            if "DIRECTIVE_TRACKER" in fp.upper():
                tracker_updated = True
                break

    if not tracker_updated:
        reason = (
            "DIR-1 WARNING: Board directive detected but no DIRECTIVE_TRACKER "
            "update found in recent tool calls. Record the directive to the tracker."
        )
        try:
            _record_behavior_rule_cieu(
                who=who,
                rule_name="DIR-1_directive_tracker_required",
                event_type="BEHAVIOR_RULE_WARNING",
                decision="WARNING",
                passed=False,
                reason=reason,
                params={"tool": tool_name},
            )
        except Exception as e:
            _log.warning("Failed to record CIEU for DIR-1: %s" % e)
        _log.warning(reason)

    return None


def _check_governance_gap_rules(
    who: str, tool_name: str, params: dict
) -> Optional[PolicyResult]:
    """Run all governance-gap enforcement checks."""
    for check_fn in [
        _check_no_email_to_humans,
        _check_merge_to_main_requires_board_approval,
        _check_cieu_archive_before_delete,
        _check_knowledge_cases_append_only,
        _check_publish_requires_cieu_validation,
    ]:
        result = check_fn(who, tool_name, params)
        if result is not None:
            return result

    _check_no_multiple_choice(who, tool_name, params)
    _check_directive_must_record_to_tracker(who, tool_name, params)

    return None


__all__ = [
    "_get_immutable_config",
    "_check_immutable_paths",
    "_check_restricted_write_paths",
    "_check_write_boundary",
    "_check_tool_restriction",
    "_check_behavior_rules",
    "_check_task_type_symbols",
    "_load_write_paths_from_agents_md",
    "_load_tool_restrictions_from_agents_md",
    "_ensure_write_paths_loaded",
    "_ensure_restricted_write_loaded",
    "_ensure_tool_restrictions_loaded",
    "_extract_write_paths_from_bash",
    "_check_governance_gap_rules",
    "_check_merge_to_main_requires_board_approval",
    "_check_cieu_archive_before_delete",
    "_check_knowledge_cases_append_only",
    "_check_no_email_to_humans",
    "_check_no_multiple_choice",
    "_check_publish_requires_cieu_validation",
    "_check_directive_must_record_to_tracker",
]

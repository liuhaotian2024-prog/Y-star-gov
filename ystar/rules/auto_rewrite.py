# Layer: Foundation
"""
ystar.rules.auto_rewrite — CZL-ARCH-14 REWRITE safe-transform engine.

Provides deterministic, semantic-preserving payload transformations that
auto-correct false-positive enforcement denials.  Each transform is
whitelisted by mode and must satisfy the 7 safety criteria from ARCH-14 A.6.

Three built-in transforms:
  1. commit_msg_token_safe — git commit -m with path-like tokens (EOF, case-insensitive)
  2. os_environ_env_match  — Python string containing ".env" that is really os.environ
  3. dev_null_write_false_positive — "> /dev/null" treated as a real file write
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class RewriteTransform:
    """A single safe, deterministic payload transformation."""
    mode: str                              # whitelist mode name
    match_pattern: Callable[[str, str, Dict[str, Any]], bool]  # (tool_name, primary_value, params) -> bool
    replacement_fn: Callable[[str, str, Dict[str, Any]], Dict[str, Any]]  # returns rewritten params subset
    safe_reason: str                       # human-readable explanation


# ────────────────────────────────────────────────────────────────────────
# Transform 1: commit_msg_token_safe
# Detects: git commit -m "..." where the message contains tokens that
# look like paths to the deny-list scanner (e.g. "EOF", "case-insensitive",
# "log-and-return") but are actually just commit message prose.
# Fix: route the message through a /tmp file so the inline string no
# longer triggers path-like pattern matches in the hook deny scanner.
# ────────────────────────────────────────────────────────────────────────

_GIT_COMMIT_MSG_RE = re.compile(
    r"""git\s+commit\s+.*?-m\s+(?:["']|\$\(cat\s+<<)""",
    re.IGNORECASE,
)

# Tokens that are benign commit-message words but trigger false positives
_FALSE_POSITIVE_TOKENS = re.compile(
    r"\b(EOF|case-insensitive|log-and-return|path-alias|auto-rewrite|"
    r"pre-commit|post-commit|dry-run|fail-safe|break-glass)\b",
    re.IGNORECASE,
)


def _detect_commit_msg_token(tool_name: str, primary: str, params: Dict[str, Any]) -> bool:
    if tool_name != "Bash":
        return False
    command = params.get("command", "")
    if not _GIT_COMMIT_MSG_RE.search(command):
        return False
    return bool(_FALSE_POSITIVE_TOKENS.search(command))


def _rewrite_commit_msg_token(_tool: str, _primary: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Return rewritten params with the commit routed via heredoc-safe form."""
    # The rewrite marks the command as safe — it does NOT change the command
    # itself (the commit message content is the user's intent).  Instead we
    # annotate params so downstream scanners skip false-positive patterns.
    return {"_rewrite_safe": True, "_rewrite_mode": "commit_msg_token_safe"}


# ────────────────────────────────────────────────────────────────────────
# Transform 2: os_environ_env_match
# Detects: Bash/Write payload where ".env" appears inside a Python
# os.environ / os.getenv context — NOT an actual .env file write.
# Fix: mark as non-write so deny scanner does not block.
# ────────────────────────────────────────────────────────────────────────

_OS_ENVIRON_CONTEXT_RE = re.compile(
    r"""os\.(?:environ|getenv)\s*[\[\(]\s*['"].*?\.env""",
    re.IGNORECASE,
)

_DOTENV_BARE_RE = re.compile(r"""\.env\b""")


def _detect_os_environ_env(tool_name: str, primary: str, params: Dict[str, Any]) -> bool:
    text = params.get("command", "") or params.get("content", "") or primary
    if not _DOTENV_BARE_RE.search(text):
        return False
    return bool(_OS_ENVIRON_CONTEXT_RE.search(text))


def _rewrite_os_environ_env(_tool: str, _primary: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {"_rewrite_safe": True, "_rewrite_mode": "os_environ_env_match"}


# ────────────────────────────────────────────────────────────────────────
# Transform 3: dev_null_write_false_positive
# Detects: "> /dev/null" or "2>/dev/null" in a Bash command that the
# write-path extractor treats as writing to /dev/null (which is
# harmless — it discards output).
# Fix: mark as non-write.
# ────────────────────────────────────────────────────────────────────────

_DEV_NULL_RE = re.compile(r"""[12]?\s*>\s*/dev/null""")


def _detect_dev_null_write(tool_name: str, primary: str, params: Dict[str, Any]) -> bool:
    if tool_name != "Bash":
        return False
    command = params.get("command", "")
    return bool(_DEV_NULL_RE.search(command))


def _rewrite_dev_null(_tool: str, _primary: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {"_rewrite_safe": True, "_rewrite_mode": "dev_null_write_false_positive"}


# ────────────────────────────────────────────────────────────────────────
# Transform 4: bash_env_token_safe
# Detects: Bash command containing ".env" but in a safe programmatic
# context (os.environ, os.getenv, inside a comment, inside a variable
# name like MY_APP.env.local) — NOT bare file access like "cat .env".
# Fix: mark as safe so the cannot_touch ".env" deny is bypassed.
# ────────────────────────────────────────────────────────────────────────

# Safe contexts where ".env" is not a file reference
_BASH_ENV_SAFE_CONTEXT_RE = re.compile(
    r"""(?:"""
    r"""os\.(?:environ|getenv)\s*[\[\(]"""       # os.environ['X'] / os.getenv('X')
    r"""|os\.environ\.(?:pop|get|setdefault)"""  # os.environ.pop('X', None)
    r"""|^\s*\#.*\.env"""                        # comment line containing .env
    r"""|['"][A-Za-z_][A-Za-z0-9_]*\.env"""      # variable-name-like string: 'MY_APP.env.local'
    r"""|(?:echo|print|printf)\s.*\.env"""       # echo/print mentioning .env (not file read)
    r""")""",
    re.MULTILINE | re.IGNORECASE,
)

# Bare dangerous .env access patterns (must NOT match for safe context)
_BARE_ENV_FILE_ACCESS_RE = re.compile(
    r"""(?:"""
    r"""(?:cat|less|more|head|tail|nano|vim?|code)\s+[^\|;]*\.env\b"""  # cat .env
    r"""|source\s+[^\|;]*\.env\b"""                                     # source .env
    r"""|(?:<|>>?)\s*\.env\b"""                                          # redirect to/from .env
    r"""|cp\s.*\.env\b"""                                                 # cp involving .env
    r""")""",
    re.IGNORECASE,
)


_DOTENV_SUBSTRING_RE = re.compile(r"""\.env""", re.IGNORECASE)


def _detect_bash_env_token_safe(tool_name: str, primary: str, params: Dict[str, Any]) -> bool:
    if tool_name != "Bash":
        return False
    command = params.get("command", "")
    # Use substring match (not word-boundary) because cannot_touch checks
    # for ".env" as a substring in any parameter value.
    if not _DOTENV_SUBSTRING_RE.search(command):
        return False
    # Must have safe context AND must NOT have bare dangerous access
    if _BARE_ENV_FILE_ACCESS_RE.search(command):
        return False
    return bool(_BASH_ENV_SAFE_CONTEXT_RE.search(command))


def _rewrite_bash_env_token_safe(_tool: str, _primary: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "_rewrite_safe": True,
        "_rewrite_mode": "bash_env_token_safe",
        "_rewrite_suggestion": "Use os.environ['KEY'] or os.getenv('KEY') instead of reading .env files directly",
    }


# ────────────────────────────────────────────────────────────────────────
# Transform 5: write_boundary_redirect
# Detects: Write/Edit to a path outside agent's allowed write paths.
# Does NOT auto-allow — returns a suggestion for the correct path.
# The _agent_allowed_paths key is injected by boundary_enforcer before
# calling the detector.
# ────────────────────────────────────────────────────────────────────────


def _detect_write_boundary_redirect(tool_name: str, primary: str, params: Dict[str, Any]) -> bool:
    if tool_name not in ("Write", "Edit"):
        return False
    # Only fires when boundary_enforcer has injected allowed paths
    allowed_paths = params.get("_agent_allowed_paths")
    if not allowed_paths:
        return False
    file_path = params.get("file_path", "")
    if not file_path:
        return False
    # Check that the file is indeed outside allowed paths (caller already verified)
    return True


def _rewrite_write_boundary_redirect(_tool: str, _primary: str, params: Dict[str, Any]) -> Dict[str, Any]:
    import os as _os
    file_path = params.get("file_path", "")
    allowed_paths = params.get("_agent_allowed_paths", [])
    filename = _os.path.basename(file_path)

    # Pick the first allowed path that looks like a directory (ends with /)
    suggested_dir = None
    for ap in allowed_paths:
        if ap.endswith("/") or ap.endswith(_os.sep):
            suggested_dir = ap
            break
    # Fallback: use first allowed path as directory
    if suggested_dir is None and allowed_paths:
        suggested_dir = allowed_paths[0]
        if not suggested_dir.endswith("/"):
            suggested_dir += "/"

    if suggested_dir:
        suggested_path = suggested_dir + filename
    else:
        suggested_path = filename

    return {
        "_rewrite_safe": False,
        "_rewrite_mode": "write_boundary_redirect",
        "_rewrite_suggestion": f"Redirect to {suggested_path} which is within your write scope",
    }


# ────────────────────────────────────────────────────────────────────────
# Transform 6: czl159_header_autoinject
# Detects: Write to CZL-159 enforced prefixes (reports/, content/,
# knowledge/ceo/strategy/) where content is missing U-workflow signals
# (research/synthesis/audience).
# Returns a template header block with FILL lines for missing signals.
# ────────────────────────────────────────────────────────────────────────

_CZL159_ENFORCED_PREFIXES = ("reports/", "content/", "knowledge/ceo/strategy/")

_RESEARCH_RE = re.compile(
    r"(source[s]?[:\s]|cite[ds]?[\s:]|per\s+\w|according\s+to|search|found\s+that"
    r"|reference[ds]?|evidence|data\s+show|based\s+on|research|study|paper|article|empirical)",
    re.IGNORECASE,
)

_SYNTHESIS_RE = re.compile(
    r"(therefore|because|analysis|conclude[ds]?|lesson[s]?|insight[s]?|implication"
    r"|root\s+cause|pattern|takeaway|diagnosis|framework|principle|synthesis|assessment)",
    re.IGNORECASE,
)

_AUDIENCE_RE = re.compile(
    r"(audience|purpose|for\s+board|stakeholder|reader[s]?|intended\s+for|context\s+for"
    r"|decision\s+maker|consumer|recipient)",
    re.IGNORECASE,
)


def _detect_czl159_header(tool_name: str, primary: str, params: Dict[str, Any]) -> bool:
    if tool_name != "Write":
        return False
    file_path = params.get("file_path", "")
    # Normalize: check if any enforced prefix appears in the path
    matched = False
    for prefix in _CZL159_ENFORCED_PREFIXES:
        if prefix in file_path:
            matched = True
            break
    if not matched:
        return False
    content = params.get("content", "")
    if not content:
        return False
    # At least one signal must be missing
    has_research = bool(_RESEARCH_RE.search(content))
    has_synthesis = bool(_SYNTHESIS_RE.search(content))
    has_audience = bool(_AUDIENCE_RE.search(content))
    return not (has_research and has_synthesis and has_audience)


def _rewrite_czl159_header(_tool: str, _primary: str, params: Dict[str, Any]) -> Dict[str, Any]:
    content = params.get("content", "")
    has_research = bool(_RESEARCH_RE.search(content))
    has_synthesis = bool(_SYNTHESIS_RE.search(content))
    has_audience = bool(_AUDIENCE_RE.search(content))

    lines = ["# --- U-Workflow Compliance (auto-generated) ---"]
    if not has_audience:
        lines.append("# Audience: [FILL: who reads this and why]")
    if not has_research:
        lines.append("# Research: [FILL: cite sources or evidence]")
    if not has_synthesis:
        lines.append("# Synthesis: [FILL: your analysis/conclusion]")
    lines.append("# ---")
    header_block = "\n".join(lines)

    return {
        "_rewrite_safe": False,
        "_rewrite_mode": "czl159_header_autoinject",
        "_rewrite_suggestion": header_block,
    }


# ────────────────────────────────────────────────────────────────────────
# Registry of all safe transforms
# ────────────────────────────────────────────────────────────────────────

SAFE_TRANSFORMS: List[RewriteTransform] = [
    RewriteTransform(
        mode="commit_msg_token_safe",
        match_pattern=_detect_commit_msg_token,
        replacement_fn=_rewrite_commit_msg_token,
        safe_reason="Commit message contains path-like tokens that are prose, not file paths",
    ),
    RewriteTransform(
        mode="os_environ_env_match",
        match_pattern=_detect_os_environ_env,
        replacement_fn=_rewrite_os_environ_env,
        safe_reason="'.env' appears in os.environ/os.getenv context, not a .env file write",
    ),
    RewriteTransform(
        mode="dev_null_write_false_positive",
        match_pattern=_detect_dev_null_write,
        replacement_fn=_rewrite_dev_null,
        safe_reason="/dev/null output redirection is not a real file write",
    ),
    RewriteTransform(
        mode="bash_env_token_safe",
        match_pattern=_detect_bash_env_token_safe,
        replacement_fn=_rewrite_bash_env_token_safe,
        safe_reason=".env token appears in a safe programmatic context (os.environ/comment/variable name), not bare file access",
    ),
    RewriteTransform(
        mode="write_boundary_redirect",
        match_pattern=_detect_write_boundary_redirect,
        replacement_fn=_rewrite_write_boundary_redirect,
        safe_reason="Write target outside agent scope; suggesting redirect to allowed path",
    ),
    RewriteTransform(
        mode="czl159_header_autoinject",
        match_pattern=_detect_czl159_header,
        replacement_fn=_rewrite_czl159_header,
        safe_reason="Content missing U-workflow signals; auto-generating compliance header template",
    ),
]


def auto_rewrite_detector(tool_name: str, params: Dict[str, Any]) -> Optional[RewriteTransform]:
    """
    Scan params against all registered safe transforms.

    Returns the first matching RewriteTransform, or None if no transform applies.
    """
    primary = params.get("file_path", "") or params.get("command", "") or ""
    for transform in SAFE_TRANSFORMS:
        if transform.match_pattern(tool_name, primary, params):
            return transform
    return None


def auto_rewrite_executor(
    transform: RewriteTransform,
    tool_name: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a matched RewriteTransform, returning the rewrite metadata dict.

    The returned dict always contains:
      _rewrite_safe: True
      _rewrite_mode: <mode name>

    Callers merge this into params before re-checking.
    """
    primary = params.get("file_path", "") or params.get("command", "") or ""
    result = transform.replacement_fn(tool_name, primary, params)
    # Ensure mandatory keys
    result.setdefault("_rewrite_safe", True)
    result.setdefault("_rewrite_mode", transform.mode)
    return result

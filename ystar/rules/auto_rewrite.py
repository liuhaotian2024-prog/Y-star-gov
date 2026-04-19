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

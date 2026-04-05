"""GOV MCP deterministic command router — rule-based, no LLM.

Classifies commands as deterministic (safe to auto-execute) or
non-deterministic (must go through LLM) using structural analysis.

A command is deterministic iff ALL of:
  1. Root binary is in a known safe command family
  2. No write side-effects detected (no file mutation, no network egress)
  3. Not in the always_deny blacklist

A command is non-deterministic if ANY of:
  1. Root binary is unknown
  2. Write side-effects detected
  3. Output requires semantic interpretation (interactive commands)
"""
from __future__ import annotations

import re
import shlex
from typing import Any, Dict, List, Optional, Tuple


# ── Known command families ──────────────────────────────────────────────────
# Each family: set of base command names → (read_only, description)

_READ_ONLY_FAMILIES: Dict[str, str] = {
    # Version control (read ops)
    "git":      "version control",
    # Testing
    "pytest":   "test runner",
    "python":   "python interpreter",
    "python3":  "python interpreter",
    "python3.11": "python interpreter",
    "python3.12": "python interpreter",
    "python3.13": "python interpreter",
    # Package info
    "pip":      "package manager",
    "pip3":     "package manager",
    # Text processing
    "grep":     "text search",
    "egrep":    "text search",
    "fgrep":    "text search",
    "head":     "text viewer",
    "tail":     "text viewer",
    "cat":      "text viewer",
    "less":     "text viewer",
    "more":     "text viewer",
    "wc":       "text counter",
    "sort":     "text sorter",
    "uniq":     "text filter",
    "cut":      "text cutter",
    "tr":       "text translator",
    "awk":      "text processor",
    "sed":      "text processor",
    "diff":     "text differ",
    "comm":     "text comparer",
    "strings":  "binary text extractor",
    "jq":       "json processor",
    "yq":       "yaml processor",
    "xxd":      "hex viewer",
    # File inspection
    "ls":       "file lister",
    "dir":      "file lister",
    "find":     "file finder",
    "tree":     "directory tree",
    "file":     "file type",
    "stat":     "file status",
    "du":       "disk usage",
    "df":       "disk free",
    "wc":       "word count",
    "md5sum":   "checksum",
    "sha256sum": "checksum",
    "shasum":   "checksum",
    # System info
    "pwd":      "working directory",
    "which":    "binary locator",
    "where":    "binary locator",
    "whoami":   "user info",
    "hostname": "host info",
    "uname":    "system info",
    "date":     "date/time",
    "uptime":   "uptime",
    "env":      "environment",
    "printenv": "environment",
    "echo":     "output",
    "printf":   "output",
    "true":     "no-op",
    "false":    "no-op",
    "test":     "condition",
    # Build (read-only queries)
    "make":     "build system",
    "cargo":    "rust build",
    "npm":      "node packages",
    "node":     "node runtime",
    "go":       "go runtime",
    # Y*gov
    "ystar":    "governance cli",
    # Windows compat
    "findstr":  "text search",
    "type":     "text viewer",
    "ver":      "version",
    "systeminfo": "system info",
}

# ── Write side-effect indicators ────────────────────────────────────────────

# Git subcommands that mutate state
_GIT_WRITE_SUBCOMMANDS = {
    "push", "commit", "merge", "rebase", "reset", "revert", "cherry-pick",
    "stash", "tag", "branch", "checkout", "switch", "restore", "clean",
    "rm", "mv", "init", "clone", "pull", "fetch", "am", "apply",
}

# Git subcommands that are read-only
_GIT_READ_SUBCOMMANDS = {
    "status", "log", "diff", "show", "branch", "describe", "rev-parse",
    "rev-list", "shortlog", "blame", "grep", "bisect", "remote",
    "config", "ls-files", "ls-tree", "cat-file", "name-rev",
    "for-each-ref", "count-objects", "fsck", "reflog",
}

# pip subcommands that are read-only
_PIP_READ_SUBCOMMANDS = {"list", "show", "freeze", "check", "search", "config"}

# Python -c is read-only if no obvious writes
_PYTHON_WRITE_PATTERNS = [
    re.compile(r"open\s*\(.+['\"]w['\"]"),           # open(..., 'w')
    re.compile(r"\.write\s*\("),                       # .write(
    re.compile(r"os\.(remove|unlink|rename|makedirs)"),
    re.compile(r"shutil\.(rmtree|move|copy)"),
    re.compile(r"subprocess\.(run|call|Popen)"),
    re.compile(r"requests\.(post|put|delete|patch)"),
    re.compile(r"urllib"),
]

# Shell write operators
_SHELL_WRITE_PATTERNS = [
    re.compile(r"[^|]>\s"),         # redirect > (but not |>)
    re.compile(r">>"),              # append >>
    re.compile(r"\btee\b"),         # tee writes to file
    re.compile(r"\bsudo\b"),        # sudo escalation
    re.compile(r"\brm\b"),          # remove
    re.compile(r"\bmkdir\b"),       # create dir
    re.compile(r"\btouch\b"),       # create file
    re.compile(r"\bchmod\b"),       # change permissions
    re.compile(r"\bchown\b"),       # change owner
    re.compile(r"\bcp\b"),          # copy
    re.compile(r"\bmv\b"),          # move
    re.compile(r"\bcurl\b"),        # network
    re.compile(r"\bwget\b"),        # network
    re.compile(r"\bssh\b"),         # remote
    re.compile(r"\bscp\b"),         # remote copy
    re.compile(r"\brsync\b"),       # remote sync
    re.compile(r"\bkill\b"),        # process control
    re.compile(r"\bpkill\b"),       # process control
]

# npm/cargo subcommands that write
_NPM_WRITE_SUBCOMMANDS = {"install", "uninstall", "update", "publish", "init", "run", "start"}
_CARGO_WRITE_SUBCOMMANDS = {"build", "run", "install", "publish", "clean", "new", "init"}

# make with no target or specific read-only targets
_MAKE_READ_TARGETS = {"", "-n", "--dry-run", "help", "print-%", "check", "test", "lint"}

# Interactive commands that need LLM interpretation
_INTERACTIVE_COMMANDS = {
    "vim", "vi", "nano", "emacs", "less", "more", "top", "htop",
    "python", "python3", "node", "irb", "ghci",  # without -c flag
}


# ── Main classifier ────────────────────────────────────────────────────────

def is_deterministic(
    command: str,
    always_deny: List[str] | None = None,
) -> Tuple[bool, str]:
    """Classify a command as deterministic or non-deterministic.

    Returns:
        (is_deterministic: bool, reason: str)
    """
    cmd = command.strip()
    if not cmd:
        return False, "empty command"

    # Phase 0: always_deny blacklist
    if always_deny:
        for pattern in always_deny:
            if pattern in cmd:
                return False, f"blacklisted: contains '{pattern}'"

    # Phase 1: Extract root binary
    root, args_str = _extract_root(cmd)
    if root is None:
        return False, "cannot parse command"

    # Phase 2: Check shell write operators in the full command
    # (pipes are ok, redirects are not)
    for pat in _SHELL_WRITE_PATTERNS:
        if pat.search(cmd):
            # Exception: grep/find/etc piped into wc/sort/head is read-only
            # Only flag if the write pattern is in the LAST pipeline segment
            last_segment = cmd.split("|")[-1].strip()
            if pat.search(last_segment):
                return False, f"write side-effect: {pat.pattern}"

    # Phase 3: Known family check
    if root not in _READ_ONLY_FAMILIES:
        return False, f"unknown command: '{root}'"

    # Phase 4: Subcommand-level analysis for complex tools
    reason = _check_subcommand(root, args_str, cmd)
    if reason:
        return False, reason

    # All checks passed
    family = _READ_ONLY_FAMILIES[root]
    return True, f"deterministic: {root} ({family})"


def _extract_root(cmd: str) -> Tuple[Optional[str], str]:
    """Extract the root binary name from a command string."""
    # Handle pipes: classify based on the FIRST command
    first_segment = cmd.split("|")[0].strip()

    # Handle env vars prefix: VAR=val cmd args
    segment = re.sub(r"^\w+=\S+\s+", "", first_segment)

    # Handle command substitution wrappers
    segment = segment.lstrip("(").rstrip(")")

    try:
        parts = shlex.split(segment)
    except ValueError:
        # Fallback for unparseable commands
        parts = segment.split()

    if not parts:
        return None, ""

    # Extract binary name from path
    binary = parts[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    args_str = " ".join(parts[1:]) if len(parts) > 1 else ""

    return binary, args_str


def _check_subcommand(root: str, args_str: str, full_cmd: str) -> Optional[str]:
    """Check subcommand-level safety. Returns reason string if unsafe, None if ok."""
    args_parts = args_str.split() if args_str else []
    subcmd = args_parts[0] if args_parts else ""

    if root == "git":
        # git branch -v is read-only, git branch <name> creates
        if subcmd == "branch":
            # Read-only if: no args after flags, or just -v/-a/--list
            non_flag = [a for a in args_parts[1:] if not a.startswith("-")]
            flag_only = all(a in ("-v", "-a", "--list", "-r", "--merged", "--no-merged", "--verbose")
                          for a in args_parts[1:] if a.startswith("-"))
            if non_flag and flag_only:
                return "git branch with name arg is a write operation"

        if subcmd in _GIT_WRITE_SUBCOMMANDS and subcmd not in _GIT_READ_SUBCOMMANDS:
            return f"git {subcmd} has write side-effects"
        # git subcommands not in either list: treat as unknown → deny
        if subcmd and subcmd not in _GIT_READ_SUBCOMMANDS and subcmd not in _GIT_WRITE_SUBCOMMANDS:
            if not subcmd.startswith("-"):
                return f"unknown git subcommand: {subcmd}"

    elif root in ("pip", "pip3"):
        if subcmd == "install":
            return "pip install has write side-effects"
        if subcmd not in _PIP_READ_SUBCOMMANDS and subcmd:
            if not subcmd.startswith("-"):
                return f"pip {subcmd} may have side-effects"

    elif root in ("python", "python3", "python3.11", "python3.12", "python3.13"):
        if "-c" in args_parts:
            # Check inline code for write patterns
            c_idx = args_parts.index("-c")
            code = " ".join(args_parts[c_idx + 1:]) if c_idx + 1 < len(args_parts) else ""
            # Also check full command for code after -c
            c_match = re.search(r"-c\s+['\"](.+?)['\"]", full_cmd)
            if c_match:
                code = c_match.group(1)
            for pat in _PYTHON_WRITE_PATTERNS:
                if pat.search(code) or pat.search(full_cmd):
                    return f"python -c contains write pattern: {pat.pattern}"
            return None
        elif "-m" in args_parts:
            m_idx = args_parts.index("-m")
            module = args_parts[m_idx + 1] if m_idx + 1 < len(args_parts) else ""
            if module in ("pytest", "pip"):
                return None  # handled by pytest/pip logic
            return f"python -m {module}: unknown module"
        elif "--version" in args_parts or "-V" in args_parts:
            return None
        else:
            # Bare python/python3 = interactive REPL
            return "interactive Python REPL requires LLM"

    elif root in ("npm",):
        if subcmd in _NPM_WRITE_SUBCOMMANDS:
            return f"npm {subcmd} has write side-effects"

    elif root in ("cargo",):
        if subcmd in _CARGO_WRITE_SUBCOMMANDS:
            return f"cargo {subcmd} has write side-effects"

    elif root == "make":
        if subcmd and subcmd not in _MAKE_READ_TARGETS and not subcmd.startswith("-"):
            return f"make {subcmd} may have side-effects"

    elif root == "sed":
        # sed is read-only by default, but -i is in-place (write)
        if "-i" in args_parts:
            return "sed -i has write side-effects"

    elif root == "awk":
        # awk can redirect output but default is stdout (read-only)
        if ">" in full_cmd.split("|")[-1]:
            return "awk with redirect has write side-effects"

    return None

"""
ystar.governance.directive_evaluator  --  Directive Liveness Evaluator  v1.0.0
===============================================================================

Evaluates whether governance directives (pauses, blocks, bans, obligations)
are still LIVE, have been RELEASED, or are AMBIGUOUS.

Every directive decomposes into 3 components:
  - Trigger: What present concern motivated this?
  - Release: What event lifts this?
  - Scope:   What actions does this cover?

A directive is LIVE iff:
  (Trigger still present) AND (Release condition not yet met) AND (Action in scope)

Phase 1: Deterministic primitives only. No LLM judgment (Ethan ruling #4).

CEO spec: reports/ceo/governance/directive_liveness_evaluator_v1.md
CTO ruling: reports/cto/CZL-GOV-LIVE-EVAL-ruling.md
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_log = logging.getLogger("ystar.directive_evaluator")


# ════════════════════════════════════════════════════════════════════════
# 1. Verdict Enum
# ════════════════════════════════════════════════════════════════════════

class Verdict(Enum):
    """Directive liveness verdict."""
    LIVE = "LIVE"           # Directive is still in force
    RELEASED = "RELEASED"   # All conditions met, directive no longer applies
    AMBIGUOUS = "AMBIGUOUS" # Insufficient data to determine


# ════════════════════════════════════════════════════════════════════════
# 2. Directive Dataclass
# ════════════════════════════════════════════════════════════════════════

@dataclass
class Directive:
    """
    A governance directive with 3 components + evaluator state.

    trigger: dict with 'statement', 'check' (optional), 'current_state'
    release: dict with 'statement', 'check' (optional), 'current_state'
    scope:   dict with 'statement', 'covers' (list), 'pattern' (optional)
    evaluator: dict with 'last_run', 'verdict', 'evidence', 'requires_human_ack'
    """
    directive_id: str
    issued_at: str
    issued_by: str
    trigger: Dict[str, Any] = field(default_factory=dict)
    release: Dict[str, Any] = field(default_factory=dict)
    scope: Dict[str, Any] = field(default_factory=dict)
    evaluator: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Directive":
        """Construct from a JSON-deserialized dict."""
        return cls(
            directive_id=d.get("directive_id", ""),
            issued_at=d.get("issued_at", ""),
            issued_by=d.get("issued_by", ""),
            trigger=d.get("trigger", {}),
            release=d.get("release", {}),
            scope=d.get("scope", {}),
            evaluator=d.get("evaluator", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "directive_id": self.directive_id,
            "issued_at": self.issued_at,
            "issued_by": self.issued_by,
            "trigger": self.trigger,
            "release": self.release,
            "scope": self.scope,
            "evaluator": self.evaluator,
        }


# ════════════════════════════════════════════════════════════════════════
# 3. Check Primitives (7 deterministic, side-effect-free)
# ════════════════════════════════════════════════════════════════════════

def doc_exists(path: str, min_status: str = "L0", base_dirs: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Check if a document exists and meets minimum maturity status.

    Args:
        path: Relative or absolute path to the document.
        min_status: Minimum maturity tag (L0-L5). Checks file content for [LN] tag.
        base_dirs: List of base directories to resolve relative paths against.

    Returns:
        (passed, evidence_string)
    """
    if base_dirs is None:
        base_dirs = ["."]

    resolved = None
    for base in base_dirs:
        candidate = os.path.join(base, path) if not os.path.isabs(path) else path
        if os.path.isfile(candidate):
            resolved = candidate
            break

    if resolved is None:
        return False, f"doc_exists FAIL: {path} not found"

    # Check min_status by scanning file for [LN] tag
    if min_status and min_status != "L0":
        try:
            with open(resolved, "r", errors="replace") as f:
                content = f.read(8192)  # Read first 8KB for status tag
            # Extract all L-tags
            tags = re.findall(r"\[L(\d)\]", content)
            if not tags:
                # Also check for "Status: [L1]" or "L1 SPEC" patterns
                status_match = re.search(r"(?:Status|status|maturity)[:\s]*\[?L(\d)", content)
                if status_match:
                    tags = [status_match.group(1)]
            if not tags:
                return False, f"doc_exists WARN: {path} exists but no L-tag found (min required: {min_status})"
            max_level = max(int(t) for t in tags)
            required_level = int(min_status[1]) if len(min_status) > 1 else 0
            if max_level < required_level:
                return False, f"doc_exists FAIL: {path} at L{max_level}, requires {min_status}"
        except Exception as e:
            return False, f"doc_exists ERROR: failed to read {path}: {e}"

    return True, f"doc_exists PASS: {path} found"


def task_completed(
    atomic_id: str,
    board_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Check if a whiteboard task is marked completed.

    Args:
        atomic_id: The task's atomic_id on the dispatch board.
        board_path: Path to dispatch_board.json.

    Returns:
        (passed, evidence_string)
    """
    if board_path is None:
        board_path = os.environ.get(
            "YSTAR_DISPATCH_BOARD",
            "governance/dispatch_board.json",
        )

    if not os.path.isfile(board_path):
        return False, f"task_completed FAIL: board file not found at {board_path}"

    try:
        with open(board_path, "r") as f:
            board = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, f"task_completed ERROR: cannot read board: {e}"

    tasks = board.get("tasks", [])
    task = next((t for t in tasks if t.get("atomic_id") == atomic_id), None)

    if task is None:
        return False, f"task_completed FAIL: task {atomic_id} not found on board"

    if task.get("status") == "completed":
        return True, f"task_completed PASS: {atomic_id} completed at {task.get('completed_at', 'unknown')}"

    return False, f"task_completed FAIL: {atomic_id} status={task.get('status', 'unknown')}"


def file_mtime_after(path: str, iso_timestamp: str, base_dirs: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Check if a file was modified after a given ISO timestamp.

    Args:
        path: File path (relative or absolute).
        iso_timestamp: ISO-8601 timestamp string (e.g. "2026-04-18T22:00:00Z").
        base_dirs: List of base directories for relative path resolution.

    Returns:
        (passed, evidence_string)
    """
    from datetime import datetime, timezone

    if base_dirs is None:
        base_dirs = ["."]

    resolved = None
    for base in base_dirs:
        candidate = os.path.join(base, path) if not os.path.isabs(path) else path
        if os.path.isfile(candidate):
            resolved = candidate
            break

    if resolved is None:
        return False, f"file_mtime_after FAIL: {path} not found"

    try:
        mtime = os.path.getmtime(resolved)
        # Parse ISO timestamp
        ts_str = iso_timestamp.replace("Z", "+00:00")
        threshold = datetime.fromisoformat(ts_str).timestamp()

        if mtime > threshold:
            return True, f"file_mtime_after PASS: {path} modified after {iso_timestamp}"
        else:
            return False, f"file_mtime_after FAIL: {path} last modified before {iso_timestamp}"
    except Exception as e:
        return False, f"file_mtime_after ERROR: {e}"


def git_commit_matches(
    repo: str,
    pattern: str,
    since: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Check if a git commit with message matching pattern exists.

    Args:
        repo: Path to git repository.
        pattern: Regex pattern to match against commit messages.
        since: ISO timestamp; only check commits after this date.

    Returns:
        (passed, evidence_string)
    """
    if not os.path.isdir(repo):
        return False, f"git_commit_matches FAIL: repo {repo} not found"

    cmd = ["git", "-C", repo, "log", "--oneline", "--all", "-100"]
    if since:
        cmd.extend(["--since", since])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False, f"git_commit_matches ERROR: git log failed: {result.stderr.strip()}"

        compiled = re.compile(pattern, re.IGNORECASE)
        for line in result.stdout.splitlines():
            if compiled.search(line):
                return True, f"git_commit_matches PASS: found commit matching '{pattern}': {line.strip()}"

        return False, f"git_commit_matches FAIL: no commit matching '{pattern}' in last 100 commits"

    except subprocess.TimeoutExpired:
        return False, f"git_commit_matches ERROR: git log timed out"
    except Exception as e:
        return False, f"git_commit_matches ERROR: {e}"


def obligation_closed(
    obligation_id: str,
    omission_db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Check if an OmissionEngine obligation is no longer pending.

    Args:
        obligation_id: The obligation identifier.
        omission_db_path: Path to the omission database.

    Returns:
        (passed, evidence_string)
    """
    if omission_db_path is None:
        omission_db_path = os.environ.get(
            "YSTAR_OMISSION_DB",
            ".ystar_cieu_omission.db",
        )

    if not os.path.isfile(omission_db_path):
        return False, f"obligation_closed FAIL: omission DB not found at {omission_db_path}"

    try:
        import sqlite3
        conn = sqlite3.connect(omission_db_path)
        cursor = conn.cursor()

        # Check if obligation exists and its status
        cursor.execute(
            "SELECT status FROM obligations WHERE obligation_id = ?",
            (obligation_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            # Obligation not found — could mean it was never created or already purged
            return False, f"obligation_closed FAIL: obligation {obligation_id} not found in DB"

        status = row[0]
        if status in ("closed", "resolved", "fulfilled"):
            return True, f"obligation_closed PASS: {obligation_id} status={status}"
        else:
            return False, f"obligation_closed FAIL: {obligation_id} status={status}"

    except Exception as e:
        return False, f"obligation_closed ERROR: {e}"


def cieu_event_absent(
    event_type: str,
    hours: float = 24.0,
    cieu_db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Check if no CIEU event of given type occurred in the last N hours.

    A True result means the event is absent (good for release conditions
    like "no violations in 24h").

    Args:
        event_type: CIEU event type to search for.
        hours: Lookback window in hours.
        cieu_db_path: Path to CIEU database.

    Returns:
        (passed, evidence_string)
    """
    if cieu_db_path is None:
        cieu_db_path = os.environ.get(
            "YSTAR_CIEU_DB",
            ".ystar_cieu.db",
        )

    if not os.path.isfile(cieu_db_path):
        # No DB = no events = absent
        return True, f"cieu_event_absent PASS: no CIEU DB found, event {event_type} trivially absent"

    try:
        import sqlite3
        conn = sqlite3.connect(cieu_db_path)
        cursor = conn.cursor()

        cutoff = time.time() - (hours * 3600)

        cursor.execute(
            "SELECT COUNT(*) FROM cieu_events WHERE event_type = ? AND created_at > ?",
            (event_type, cutoff),
        )
        count = cursor.fetchone()[0]
        conn.close()

        if count == 0:
            return True, f"cieu_event_absent PASS: 0 {event_type} events in last {hours}h"
        else:
            return False, f"cieu_event_absent FAIL: {count} {event_type} events in last {hours}h"

    except Exception as e:
        # Fail-safe: if we cannot check, treat event as present (conservative)
        return False, f"cieu_event_absent ERROR: {e}"


def manual_ack(
    acker: str,
    note: Optional[str] = None,
    directive_data: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Check if a manual acknowledgment has been captured.

    In Phase 1, this checks the evaluator.manual_ack field in the directive
    annotation itself. A True result means someone explicitly acknowledged
    the directive's release.

    Args:
        acker: Expected acknowledger (e.g. "Board", "CTO").
        note: Optional note content to verify.
        directive_data: The full directive dict (evaluator section checked).

    Returns:
        (passed, evidence_string)
    """
    if directive_data is None:
        return False, f"manual_ack FAIL: no directive data provided"

    evaluator = directive_data.get("evaluator", {})
    ack_data = evaluator.get("manual_ack", {})

    if not ack_data:
        return False, f"manual_ack FAIL: no manual_ack recorded for directive"

    ack_by = ack_data.get("acked_by", "")
    if ack_by.lower() != acker.lower():
        return False, f"manual_ack FAIL: acked by '{ack_by}', expected '{acker}'"

    return True, f"manual_ack PASS: acknowledged by {ack_by}"


def fg_rule_is_expired(
    rule_name: str,
    rules_yaml_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Check if a ForgetGuard rule's dry_run_until has expired.

    Per Ethan ruling #3: Phase 1 evaluator can read FG state but does not
    modify FG enforcement. This primitive enables directives to reference
    FG temporal state.

    Args:
        rule_name: ForgetGuard rule name.
        rules_yaml_path: Path to forget_guard_rules.yaml.

    Returns:
        (passed=True if expired, evidence_string)
    """
    if rules_yaml_path is None:
        # Try common locations. Prefer the canonical Y-star-gov copy (product core)
        # over company-side copies which may be subsets.
        from ystar.workspace_config import get_labs_workspace, get_gov_root
        _ws = get_labs_workspace()
        _gov = get_gov_root()
        candidates = [
            # Colocated with this module (most reliable)
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "forget_guard_rules.yaml"),
            # Config-driven paths (product core first)
            str(_gov / "ystar" / "governance" / "forget_guard_rules.yaml") if _gov else None,
            str(_ws / "governance" / "forget_guard_rules.yaml") if _ws else None,
            # Relative paths
            "ystar/governance/forget_guard_rules.yaml",
            "governance/forget_guard_rules.yaml",
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                rules_yaml_path = c
                break

    if not rules_yaml_path or not os.path.isfile(rules_yaml_path):
        return False, f"fg_rule_is_expired FAIL: rules YAML not found"

    try:
        import yaml
    except ImportError:
        # Fallback: parse with regex for dry_run_until
        return _fg_rule_expired_regex(rule_name, rules_yaml_path)

    try:
        with open(rules_yaml_path, "r") as f:
            data = yaml.safe_load(f)

        rules = data.get("rules", []) if isinstance(data, dict) else []
        rule = next((r for r in rules if r.get("name") == rule_name), None)

        if rule is None:
            return False, f"fg_rule_is_expired FAIL: rule '{rule_name}' not found"

        dru = rule.get("dry_run_until")
        if dru is None:
            return False, f"fg_rule_is_expired FAIL: rule '{rule_name}' has no dry_run_until (permanent)"

        try:
            dru_ts = float(dru)
        except (ValueError, TypeError):
            return False, f"fg_rule_is_expired FAIL: dry_run_until '{dru}' is not a valid timestamp"

        now = time.time()
        if now > dru_ts:
            return True, f"fg_rule_is_expired PASS: rule '{rule_name}' dry_run_until {dru_ts} < now {now:.0f}"
        else:
            remaining_hours = (dru_ts - now) / 3600
            return False, f"fg_rule_is_expired FAIL: rule '{rule_name}' still in dry_run ({remaining_hours:.1f}h remaining)"

    except Exception as e:
        return False, f"fg_rule_is_expired ERROR: {e}"


def _fg_rule_expired_regex(rule_name: str, path: str) -> Tuple[bool, str]:
    """Regex fallback for fg_rule_is_expired when PyYAML not available."""
    try:
        with open(path, "r") as f:
            content = f.read()

        # Find the rule block
        pattern = rf"name:\s*{re.escape(rule_name)}.*?dry_run_until:\s*(\d+)"
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            return False, f"fg_rule_is_expired FAIL: rule '{rule_name}' or dry_run_until not found via regex"

        dru_ts = float(match.group(1))
        now = time.time()
        if now > dru_ts:
            return True, f"fg_rule_is_expired PASS (regex): '{rule_name}' expired"
        else:
            return False, f"fg_rule_is_expired FAIL (regex): '{rule_name}' not yet expired"
    except Exception as e:
        return False, f"fg_rule_is_expired ERROR (regex): {e}"


# ════════════════════════════════════════════════════════════════════════
# 4. Primitive Registry
# ════════════════════════════════════════════════════════════════════════

# Maps check type names to their implementation functions
PRIMITIVE_REGISTRY: Dict[str, Callable] = {
    "doc_exists": doc_exists,
    "task_completed": task_completed,
    "file_mtime_after": file_mtime_after,
    "git_commit_matches": git_commit_matches,
    "obligation_closed": obligation_closed,
    "cieu_event_absent": cieu_event_absent,
    "manual_ack": manual_ack,
    "fg_rule_is_expired": fg_rule_is_expired,
}


# ════════════════════════════════════════════════════════════════════════
# 5. Evaluator Engine
# ════════════════════════════════════════════════════════════════════════

def _run_check(
    check: Dict[str, Any],
    directive_data: Optional[Dict[str, Any]] = None,
    base_dirs: Optional[List[str]] = None,
    board_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Run a single check primitive from a check dict.

    The check dict must have a 'type' key matching a PRIMITIVE_REGISTRY entry.
    Other keys are passed as kwargs to the primitive.
    """
    check_type = check.get("type", "")
    if check_type not in PRIMITIVE_REGISTRY:
        return False, f"Unknown check type: {check_type}"

    fn = PRIMITIVE_REGISTRY[check_type]

    # Build kwargs from check dict minus 'type'
    kwargs = {k: v for k, v in check.items() if k != "type"}

    # Inject context-specific args
    if check_type == "doc_exists" and base_dirs:
        kwargs.setdefault("base_dirs", base_dirs)
    elif check_type == "file_mtime_after" and base_dirs:
        kwargs.setdefault("base_dirs", base_dirs)
    elif check_type == "task_completed" and board_path:
        kwargs.setdefault("board_path", board_path)
    elif check_type == "manual_ack" and directive_data:
        kwargs.setdefault("directive_data", directive_data)

    try:
        return fn(**kwargs)
    except TypeError as e:
        return False, f"Check {check_type} arg error: {e}"


def evaluate(
    directive_dict: Dict[str, Any],
    base_dirs: Optional[List[str]] = None,
    board_path: Optional[str] = None,
) -> Tuple[Verdict, List[str]]:
    """
    Evaluate a directive's liveness.

    A directive is:
      LIVE      — trigger present AND release not met
      RELEASED  — release condition met (trigger resolved or release check passes)
      AMBIGUOUS — insufficient data from primitives

    Phase 1: Deterministic only. No LLM judgment.

    Args:
        directive_dict: Full directive JSON dict.
        base_dirs: Base directories for file resolution.
        board_path: Path to dispatch_board.json.

    Returns:
        (verdict, evidence_list)
    """
    evidence: List[str] = []

    trigger = directive_dict.get("trigger", {})
    release = directive_dict.get("release", {})
    directive_id = directive_dict.get("directive_id", "unknown")

    # ── Evaluate trigger component ──
    trigger_state = trigger.get("current_state", "ambiguous")
    trigger_check = trigger.get("check")
    trigger_resolved = False

    if trigger_state == "resolved":
        trigger_resolved = True
        evidence.append(f"trigger: pre-marked as resolved")
    elif trigger_check:
        passed, msg = _run_check(
            trigger_check,
            directive_data=directive_dict,
            base_dirs=base_dirs,
            board_path=board_path,
        )
        evidence.append(f"trigger check: {msg}")
        # For trigger: if the check passes, the trigger concern EXISTS
        # (e.g., doc_exists for the problem description — if doc exists,
        # concern is documented = present). The trigger.check semantics
        # depend on context. Default: trigger_resolved = check passed
        # (the concern that triggered the directive has been addressed).
        if passed:
            trigger_resolved = True
    elif trigger_state == "present":
        trigger_resolved = False
        evidence.append(f"trigger: pre-marked as present")
    else:
        evidence.append(f"trigger: state={trigger_state}, no check defined")

    # ── Evaluate release component ──
    release_state = release.get("current_state", "ambiguous")
    release_check = release.get("check")
    release_met = False

    if release_state == "met":
        release_met = True
        evidence.append(f"release: pre-marked as met")
    elif release_check:
        passed, msg = _run_check(
            release_check,
            directive_data=directive_dict,
            base_dirs=base_dirs,
            board_path=board_path,
        )
        evidence.append(f"release check: {msg}")
        release_met = passed
    elif release_state == "unmet":
        release_met = False
        evidence.append(f"release: pre-marked as unmet")
    else:
        evidence.append(f"release: state={release_state}, no check defined")

    # ── Compose verdict ──
    # Fail-safe: default to LIVE (Ethan ruling #4 conservative default)
    trigger_determined = trigger_state in ("present", "resolved") or trigger_check is not None
    release_determined = release_state in ("met", "unmet") or release_check is not None

    if release_met:
        # Release condition met -> directive released
        verdict = Verdict.RELEASED
        evidence.append(f"VERDICT: RELEASED — release condition met for {directive_id}")
    elif trigger_resolved and not release_met and release_determined:
        # Trigger resolved but release not met is unusual —
        # trigger was addressed but formal release condition still unmet
        verdict = Verdict.AMBIGUOUS
        evidence.append(f"VERDICT: AMBIGUOUS — trigger resolved but release not formally met")
    elif not trigger_determined and not release_determined:
        # No checks defined at all
        verdict = Verdict.AMBIGUOUS
        evidence.append(f"VERDICT: AMBIGUOUS — no checks defined for trigger or release")
    elif not release_met:
        # Release not met -> directive still in force
        verdict = Verdict.LIVE
        evidence.append(f"VERDICT: LIVE — release condition not met for {directive_id}")
    else:
        verdict = Verdict.AMBIGUOUS
        evidence.append(f"VERDICT: AMBIGUOUS — indeterminate state")

    return verdict, evidence


# ════════════════════════════════════════════════════════════════════════
# 6. Directive Loader (filesystem JSON store)
# ════════════════════════════════════════════════════════════════════════

def load_directives_from_dir(directives_dir: str) -> List[Dict[str, Any]]:
    """
    Load all directive annotation JSON files from a directory.

    Per Ethan Ruling #2: Phase 1 uses filesystem JSON, one file per directive.

    Args:
        directives_dir: Path to governance/directives/ directory.

    Returns:
        List of directive dicts.
    """
    if not os.path.isdir(directives_dir):
        _log.warning("Directives directory not found: %s", directives_dir)
        return []

    directives = []
    for fpath in sorted(glob.glob(os.path.join(directives_dir, "*.json"))):
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            data["_source_file"] = fpath
            directives.append(data)
        except (json.JSONDecodeError, OSError) as e:
            _log.warning("Failed to load directive from %s: %s", fpath, e)

    return directives


def evaluate_all(
    directives_dir: str,
    base_dirs: Optional[List[str]] = None,
    board_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Load and evaluate all directives from a directory.

    Returns list of dicts: {directive_id, verdict, evidence, source_file}
    """
    directives = load_directives_from_dir(directives_dir)
    results = []

    for d in directives:
        verdict, evidence = evaluate(d, base_dirs=base_dirs, board_path=board_path)
        results.append({
            "directive_id": d.get("directive_id", "unknown"),
            "verdict": verdict.value,
            "evidence": evidence,
            "source_file": d.get("_source_file", ""),
            "requires_human_ack": d.get("evaluator", {}).get("requires_human_ack", False),
            "issued_by": d.get("issued_by", ""),
        })

    return results


def print_summary(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Print a human-readable summary of evaluation results.

    Returns counts dict: {LIVE: n, RELEASED: n, AMBIGUOUS: n}
    """
    counts: Dict[str, int] = {"LIVE": 0, "RELEASED": 0, "AMBIGUOUS": 0}

    for r in results:
        v = r["verdict"]
        counts[v] = counts.get(v, 0) + 1

    total = len(results)
    print(f"  Directive Liveness: {total} directives evaluated")
    print(f"    LIVE={counts['LIVE']}  RELEASED={counts['RELEASED']}  AMBIGUOUS={counts['AMBIGUOUS']}")

    for r in results:
        marker = {"LIVE": "[!]", "RELEASED": "[v]", "AMBIGUOUS": "[?]"}
        print(f"    {marker.get(r['verdict'], '[ ]')} {r['directive_id']}: {r['verdict']}")

    return counts


__all__ = [
    "Verdict",
    "Directive",
    "doc_exists",
    "task_completed",
    "file_mtime_after",
    "git_commit_matches",
    "obligation_closed",
    "cieu_event_absent",
    "manual_ack",
    "fg_rule_is_expired",
    "PRIMITIVE_REGISTRY",
    "evaluate",
    "load_directives_from_dir",
    "evaluate_all",
    "print_summary",
]

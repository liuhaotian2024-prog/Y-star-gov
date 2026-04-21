# ystar/adapters/hooks/stop_hook.py
"""
Y*gov Stop/UserPromptSubmit Hook — K9-RT Warning Injector

Lifecycle: Triggered on UserPromptSubmit event (when user sends next prompt).
Behavior:
  1. Read `.ystar_warning_queue.json` (written by k9_rt_sentinel.py)
  2. Inject warnings as <system-reminder> XML blocks into session context
  3. Archive processed warnings to `.ystar_warning_queue_archive.json`
  4. Clear queue file (truncate to empty)

Failure modes:
  - Queue file missing → silent pass (no warnings to inject)
  - Corrupt JSON → log error, skip injection, do NOT crash session
  - Archive write fail → log warning, continue (warnings re-injected next prompt OK for MVP)

Integration Point:
  OpenClaw `.claude/hooks/on_user_prompt_submit.py` should call:
    from ystar.adapters.hooks import inject_warnings_to_session
    inject_warnings_to_session()

Schema Contract:
  Input (queue): warning schema (see k9_rt_fuse_dispatch_plan_20260416.md Appendix B)
  Output: <system-reminder> XML blocks appended to session context

Platform Engineer: eng-platform
Version: 1.1 (added CZL Gate 1/2 correction injection)
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Import CZL validators (Gate 1/2)
try:
    from ystar.kernel.czl_protocol import validate_dispatch, validate_receipt
except ImportError:
    # Graceful degradation if czl_protocol not available
    validate_dispatch = None
    validate_receipt = None

_log = logging.getLogger("ystar.hooks.stop")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*stop] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)


# ── File Paths ────────────────────────────────────────────────────────────

def _get_queue_file() -> Path:
    """Resolve queue file path (allows runtime override for testing)."""
    return Path.cwd() / ".ystar_warning_queue.json"

def _get_archive_file() -> Path:
    """Resolve archive file path (allows runtime override for testing)."""
    return Path.cwd() / ".ystar_warning_queue_archive.json"

def _get_observe_log() -> Path:
    """Resolve observe log path (allows runtime override for testing)."""
    return Path.cwd() / "scripts" / "hook_observe.log"


# ── Warning Schema (k9_rt_sentinel contract) ─────────────────────────────

# Expected fields per warning entry:
#   {
#     "task_id": "uuid",
#     "violation_type": "rt_not_closed" | "3d_role_mismatch",
#     "details": "str (human-readable violation description)",
#     "rt_value": 0.42,
#     "timestamp": "ISO8601",
#     "agent_id": "str",
#     "role_tags": {"producer": "str", "executor": "str", "governed": "str"}
#   }


# ── Main Entry Point ──────────────────────────────────────────────────────

def inject_warnings_to_session() -> Optional[str]:
    """
    UserPromptSubmit hook entry point.

    Returns:
        str: <system-reminder> XML blocks to inject (or None if no warnings)
    """
    queue_file = _get_queue_file()
    if not queue_file.exists():
        # Silent pass — no warnings in queue
        return None

    warnings = _read_queue()
    if not warnings:
        return None

    # Generate <system-reminder> blocks
    xml_blocks = [_format_warning_xml(w) for w in warnings]
    injection_text = "\n\n".join(xml_blocks)

    # Archive processed warnings
    _archive_warnings(warnings)

    # Clear queue (truncate to empty)
    _clear_queue()

    _log.info(f"Injected {len(warnings)} K9-RT warning(s) into session context")
    return injection_text


# ── Queue I/O Helpers ─────────────────────────────────────────────────────

def _read_queue() -> list[dict]:
    """
    Read warning queue from `.ystar_warning_queue.json`.

    Auto-detects format:
    - JSON array: `[{...}, {...}]`
    - JSON-lines: `{...}\n{...}\n`

    Returns:
        List of warning dicts. Empty list if file missing or corrupt.
    """
    queue_file = _get_queue_file()
    try:
        with open(queue_file, "r", encoding="utf-8") as f:
            content = f.read()
            if not content.strip():
                return []

            # Try JSON array first (backward compatibility)
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return [data]
                else:
                    _log_error(f"Queue file format invalid (expected list or dict): {type(data)}")
                    return []
            except json.JSONDecodeError:
                # Fall back to JSON-lines format (sentinel append-only)
                warnings = []
                for line in content.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        warnings.append(json.loads(line))
                    except json.JSONDecodeError as line_err:
                        _log_error(f"JSON-lines parse failed on line: {line_err}")
                return warnings

    except Exception as e:
        _log_error(f"Queue read failed: {e}")
        return []


def _archive_warnings(warnings: list[dict]) -> None:
    """
    Append processed warnings to archive file with `processed_at` timestamp.
    """
    archive_file = _get_archive_file()
    try:
        # Load existing archive (if any)
        archive = []
        if archive_file.exists():
            try:
                with open(archive_file, "r", encoding="utf-8") as f:
                    archive = json.load(f)
                    if not isinstance(archive, list):
                        archive = []
            except json.JSONDecodeError:
                archive = []

        # Add processed_at timestamp to each warning
        now = datetime.now(timezone.utc).isoformat()
        for w in warnings:
            w["processed_at"] = now
            archive.append(w)

        # Write archive atomically
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(archive, f, indent=2, ensure_ascii=False)
    except Exception as e:
        # Non-fatal — log warning but continue (warnings will be re-injected next prompt)
        _log.warning(f"Archive write failed: {e}")


def _clear_queue() -> None:
    """Truncate queue file to empty."""
    queue_file = _get_queue_file()
    try:
        queue_file.write_text("[]", encoding="utf-8")
    except Exception as e:
        _log.warning(f"Queue clear failed: {e}")


# ── XML Formatting ────────────────────────────────────────────────────────

def _format_warning_xml(warning: dict) -> str:
    """
    Format single warning as <system-reminder> XML block.

    Template:
        <system-reminder>
        ⚠️ K9-RT Sentinel detected unresolved gap:
        Task: {task_id}
        Violation: {violation_type}
        Details: {details}
        Rt+1 = {rt_value} (must reach 0.0 for closure)
        Agent: {agent_id} (Producer={producer}, Executor={executor})
        </system-reminder>
    """
    task_id = warning.get("task_id", "unknown")
    violation_type = warning.get("violation_type", "unknown")
    details = warning.get("details", "No details provided")
    rt_value = warning.get("rt_value", "N/A")
    agent_id = warning.get("agent_id", "unknown")

    role_tags = warning.get("role_tags", {})
    producer = role_tags.get("producer", "unknown")
    executor = role_tags.get("executor", "unknown")

    return f"""<system-reminder>
⚠️ K9-RT Sentinel detected unresolved gap:
Task: {task_id}
Violation: {violation_type}
Details: {details}
Rt+1 = {rt_value} (must reach 0.0 for closure)
Agent: {agent_id} (Producer={producer}, Executor={executor})
</system-reminder>"""


# ── Logging Helpers ───────────────────────────────────────────────────────

def _log_error(msg: str) -> None:
    """Log error to both stderr and hook_observe.log."""
    _log.error(msg)
    observe_log = _get_observe_log()
    try:
        observe_log.parent.mkdir(parents=True, exist_ok=True)
        with open(observe_log, "a", encoding="utf-8") as f:
            timestamp = datetime.now(timezone.utc).isoformat()
            f.write(f"[{timestamp}] STOP_HOOK_ERROR: {msg}\n")
    except Exception:
        pass  # Fail silently — logging failure should not crash hook


# ── CZL Gate 1/2 Injection ────────────────────────────────────────────────

def inject_czl_corrections(
    prompt_text: str = None,
    receipt_text: str = None,
    artifacts_expected: list[Path] = None,
) -> Optional[str]:
    """
    CZL Gate 1/2 correction injector.

    Validates dispatch prompts (Gate 1) or sub-agent receipts (Gate 2) against
    CZL Unified Communication Protocol v1.0.

    Args:
        prompt_text: CEO/CTO dispatch prompt (for Gate 1 validation)
        receipt_text: Sub-agent receipt text (for Gate 2 validation)
        artifacts_expected: Paths that MUST exist if receipt claims Rt+1=0

    Returns:
        str: <system-reminder> correction block (or None if valid)

    Integration Points:
        - Gate 1 (dispatch): Call before Agent tool spawns sub-agent
        - Gate 2 (receipt): Call after sub-agent Stop event returns receipt

    CIEU Events Emitted:
        - CZL_DISPATCH_REJECTED (Gate 1 fail)
        - CZL_RECEIPT_REJECTED (Gate 2 fail)
    """
    # Check if CZL validators available
    if validate_dispatch is None or validate_receipt is None:
        _log.warning("CZL validators not available (czl_protocol import failed)")
        return None

    # Gate 1: Dispatch pre-validation
    if prompt_text:
        missing_sections = validate_dispatch(prompt_text)
        if missing_sections:
            _emit_cieu_event("CZL_DISPATCH_REJECTED", {
                "missing_sections": missing_sections,
                "prompt_length": len(prompt_text),
            })
            return _format_dispatch_correction_xml(missing_sections)

    # Gate 2: Receipt post-validation (empirical artifact check)
    if receipt_text and artifacts_expected is not None:
        is_valid, actual_rt = validate_receipt(
            receipt=receipt_text,
            artifacts_expected=artifacts_expected,
        )
        if not is_valid:
            _emit_cieu_event("CZL_RECEIPT_REJECTED", {
                "actual_rt_plus_1": actual_rt,
                "artifacts_expected": [str(p) for p in artifacts_expected],
                "artifacts_missing": [str(p) for p in artifacts_expected if not p.exists()],
            })
            return _format_receipt_rejection_xml(actual_rt, artifacts_expected, receipt_text)

    # Valid dispatch/receipt → silent pass
    return None


def _format_dispatch_correction_xml(missing_sections: list[str]) -> str:
    """
    Format Gate 1 failure as <system-reminder> correction block.

    Template:
        <system-reminder>
        🚫 CZL Gate 1 Rejection — Dispatch Missing Required Sections

        Cannot spawn sub-agent: CZL Unified Communication Protocol v1.0
        requires 5-tuple structure (Y*/Xt/U/Yt+1/Rt+1).

        Missing or invalid sections:
        - Xt (pre-state)
        - U (actions list)

        Fix dispatch prompt before calling Agent tool. See:
        ystar/kernel/czl_protocol.py — validate_dispatch() for requirements.
        </system-reminder>
    """
    sections_list = "\n".join(f"  - {s}" for s in missing_sections)
    return f"""<system-reminder>
🚫 CZL Gate 1 Rejection — Dispatch Missing Required Sections

Cannot spawn sub-agent: CZL Unified Communication Protocol v1.0
requires 5-tuple structure (Y*/Xt/U/Yt+1/Rt+1).

Missing or invalid sections:
{sections_list}

Fix dispatch prompt before calling Agent tool. See:
ystar/kernel/czl_protocol.py — validate_dispatch() for requirements.
</system-reminder>"""


def _format_receipt_rejection_xml(
    actual_rt: float,
    artifacts_expected: list[Path],
    receipt_text: str,
) -> str:
    """
    Format Gate 2 failure as <system-reminder> rejection block.

    Template:
        <system-reminder>
        ⚠️ CZL Gate 2 Rejection — Receipt Rt+1 Gap Detected

        Sub-agent claimed completion, but empirical verification failed:
        - Actual Rt+1 = 1.5 (NOT 0.0 as claimed)
        - Missing artifacts: governance/czl_unified_communication_protocol_v1.md
        - Receipt lacked bash verification output (ls, wc -l, pytest, etc.)

        DO NOT report this task as complete. Re-dispatch or escalate.
        </system-reminder>
    """
    missing_artifacts = [str(p) for p in artifacts_expected if not p.exists()]
    missing_artifacts_str = "\n".join(f"  - {a}" for a in missing_artifacts) if missing_artifacts else "  (all artifacts present)"

    # Check if receipt has bash verification
    has_bash_verification = any(
        marker in receipt_text
        for marker in ["ls -la", "wc -l", "pytest", "git diff --stat"]
    )

    verification_note = "" if has_bash_verification else "\n- Receipt lacked bash verification output (ls, wc -l, pytest, etc.)"

    return f"""<system-reminder>
⚠️ CZL Gate 2 Rejection — Receipt Rt+1 Gap Detected

Sub-agent claimed completion, but empirical verification failed:
- Actual Rt+1 = {actual_rt} (NOT 0.0 as claimed)
- Missing artifacts:
{missing_artifacts_str}{verification_note}

DO NOT report this task as complete. Re-dispatch or escalate.
</system-reminder>"""


def _emit_cieu_event(event_type: str, metadata: dict) -> None:
    """
    Emit CIEU event to .ystar_cieu.db for audit trail.

    Args:
        event_type: "CZL_DISPATCH_REJECTED" or "CZL_RECEIPT_REJECTED"
        metadata: Event-specific data dict
    """
    try:
        # Lazy import to avoid dependency on CIEU infrastructure at hook load time
        from ystar.kernel.cieu import emit

        emit(
            event_type=event_type,
            agent_id="stop_hook",
            **metadata,
        )
    except ImportError:
        # Graceful degradation if CIEU infrastructure not available
        _log.warning(f"CIEU event {event_type} not emitted (cieu module not available)")
    except Exception as e:
        _log.warning(f"CIEU event {event_type} emission failed: {e}")


# ── E2: Auto-Validate ALL Sub-Agent Receipts (CZL Gate 2 Generalized) ────

def auto_validate_subagent_receipt(
    receipt_text: str,
    declared_artifacts: list[Path] | None = None,
) -> dict:
    """
    E2: Generalized CZL Gate 2 receipt validation that runs on ALL sub-agent returns.

    Extracts artifact paths from receipt prose (regex: wrote|created|landed *.ext),
    runs czl_protocol.validate_receipt() against them, emits CIEU RECEIPT_AUTO_VALIDATED.

    Args:
        receipt_text: Sub-agent's final receipt/report text
        declared_artifacts: Optional explicit artifact list (if CZL-declared in dispatch)
                           If None, auto-extract from prose.

    Returns:
        dict with keys:
            is_valid: bool (True if all artifacts exist + receipt has bash verification)
            missing_artifacts: list[Path] (paths that don't exist)
            claimed_rt: float | None (parsed from "Rt+1 = X" in receipt)
            actual_rt: float (empirical gap from validate_receipt)
            validation_status: "pass" | "fail" | "no_artifacts_to_check"

    CIEU Events Emitted:
        - RECEIPT_AUTO_VALIDATED (always emitted, includes verdict + gap)

    Example usage (called by hook infrastructure after sub-agent Stop event):
        >>> result = auto_validate_subagent_receipt(subagent_reply)
        >>> if not result["is_valid"]:
        ...     inject_correction_to_ceo(result)
    """
    # Step 1: Extract artifact paths from prose if not explicitly declared
    if declared_artifacts is None:
        declared_artifacts = _extract_artifact_paths_from_prose(receipt_text)

    # Handle empty artifact case gracefully
    if not declared_artifacts:
        _emit_cieu_event("RECEIPT_AUTO_VALIDATED", {
            "validation_status": "no_artifacts_to_check",
            "claimed_rt": None,
            "actual_rt": 0.0,
        })
        return {
            "is_valid": True,  # No artifacts to check → pass (not a deliverable task)
            "missing_artifacts": [],
            "claimed_rt": None,
            "actual_rt": 0.0,
            "validation_status": "no_artifacts_to_check",
        }

    # Step 2: Run empirical validation via czl_protocol.validate_receipt()
    if validate_receipt is None:
        _log.warning("CZL validate_receipt not available (czl_protocol import failed)")
        return {
            "is_valid": False,
            "missing_artifacts": [],
            "claimed_rt": None,
            "actual_rt": 999.0,
            "validation_status": "validator_unavailable",
        }

    is_valid, actual_rt = validate_receipt(
        receipt=receipt_text,
        artifacts_expected=declared_artifacts,
    )

    # Step 3: Extract claimed Rt+1 from receipt text (supports both "=" and ":" formats)
    claimed_rt_match = re.search(r"Rt\+1.*?[=:]\s*([\d.]+)", receipt_text)
    claimed_rt = float(claimed_rt_match.group(1)) if claimed_rt_match else None

    # Step 4: Identify missing artifacts
    missing_artifacts = [p for p in declared_artifacts if not p.exists()]

    # Step 5: Emit CIEU event with validation verdict
    validation_status = "pass" if is_valid else "fail"
    _emit_cieu_event("RECEIPT_AUTO_VALIDATED", {
        "validation_status": validation_status,
        "claimed_rt": claimed_rt,
        "actual_rt": actual_rt,
        "artifacts_expected": [str(p) for p in declared_artifacts],
        "artifacts_missing": [str(p) for p in missing_artifacts],
    })

    # Step 6: Extract 5-tuple and auto-emit RT_MEASUREMENT if present
    five_tuple = _extract_5tuple_from_receipt(receipt_text)
    if five_tuple is not None:
        _emit_rt_measurement_from_receipt(five_tuple, actual_rt)

    return {
        "is_valid": is_valid,
        "missing_artifacts": missing_artifacts,
        "claimed_rt": claimed_rt,
        "actual_rt": actual_rt,
        "validation_status": validation_status,
    }


def _extract_artifact_paths_from_prose(receipt_text: str) -> list[Path]:
    r"""
    Extract artifact file paths from sub-agent receipt prose.

    Regex patterns:
        - "wrote <path>"
        - "created <path>"
        - "landed <path>"
        - "shipped <path>"
        - "Artifacts:\n- <path>" or "Files: <path>"
        - Backtick-wrapped paths: `<path>`
        - "Created at <path>" or "Modified to <path>"
        - Absolute paths: /Users/... or C:\Users\... (CZL-80 Q3 fix)
        - Followed by file extension: .py, .md, .yaml, .json, .txt, .sh

    Returns:
        List of Path objects extracted from prose (may include non-existent paths)

    Example:
        >>> paths = _extract_artifact_paths_from_prose(
        ...     "I wrote ystar/adapters/hooks/stop_hook.py and created tests/test_hook.py"
        ... )
        >>> # Returns [Path("ystar/adapters/hooks/stop_hook.py"), Path("tests/test_hook.py")]
    """
    all_matches = []

    # Common file extensions to recognize
    ext_pattern = r"(?:py|md|yaml|yml|json|txt|sh|toml|cfg|ini|rst|log|xml|html|css|js|ts|tsx|jsx)"

    # Pattern 1: action verb + path with known extension
    pattern1 = rf"(?:wrote|created|landed|shipped|edited|modified)\s+([a-zA-Z0-9_/.+-]+\.{ext_pattern})"
    all_matches.extend(re.findall(pattern1, receipt_text, re.IGNORECASE))

    # Pattern 2: bullet-point paths (captures each bullet line independently)
    pattern2 = rf"^\s*[-*]\s+([a-zA-Z0-9_/.+-]+\.{ext_pattern})"
    all_matches.extend(re.findall(pattern2, receipt_text, re.MULTILINE))

    # Pattern 3: backtick-wrapped paths
    pattern3 = rf"`([a-zA-Z0-9_/.+-]+\.{ext_pattern})`"
    all_matches.extend(re.findall(pattern3, receipt_text))

    # Pattern 4: "Created at" / "Modified to" / "Wrote to" with path
    pattern4 = rf"(?:created|modified|wrote)\s+(?:at|to)\s+([a-zA-Z0-9_/.+-]+\.{ext_pattern})"
    all_matches.extend(re.findall(pattern4, receipt_text, re.IGNORECASE))

    # Pattern 5: Absolute paths (Unix /path/to/file.ext or Windows C:/path/to/file.ext)
    # CZL-80 Q3 fix: Sub-agent receipts often use absolute paths from tool outputs
    # CZL-80 Q4 precision fix: Negative lookbehind prevents substring capture (e.g. "/kernel/rt.py" from "ystar/kernel/rt.py")
    pattern5 = rf"(?<![/\w])(?:/[\w/.+-]+|[A-Z]:[/\\][\w/\\. +-]+)\.{ext_pattern}\b"
    all_matches.extend(re.findall(pattern5, receipt_text))

    # De-duplicate and convert to Path objects
    unique_paths = list(set(all_matches))
    return [Path(p) for p in unique_paths]


def _extract_5tuple_from_receipt(receipt_text: str) -> dict | None:
    """
    Extract CIEU 5-tuple (Y*, Xt, U, Yt+1, Rt+1) from receipt text.

    Returns:
        dict with keys {y_star, x_t, u, y_t_plus_1, rt_value} or None if not found

    Example receipt format:
        **Y***: Some ideal contract
        **Xt**: Pre-state
        **U**: (1) action1 (2) action2
        **Yt+1**: Post-state
        **Rt+1**: 0
    """
    # Extract each section using multiline regex
    y_star_match = re.search(r"\*\*Y\*?\*\*[:\s]+(.+?)(?=\n\*\*|$)", receipt_text, re.DOTALL | re.IGNORECASE)
    x_t_match = re.search(r"\*\*Xt\*\*[:\s]+(.+?)(?=\n\*\*|$)", receipt_text, re.DOTALL | re.IGNORECASE)
    u_match = re.search(r"\*\*U\*\*[:\s]+(.+?)(?=\n\*\*|$)", receipt_text, re.DOTALL | re.IGNORECASE)
    y_t_plus_1_match = re.search(r"\*\*Yt\+1\*\*[:\s]+(.+?)(?=\n\*\*|$)", receipt_text, re.DOTALL | re.IGNORECASE)
    rt_match = re.search(r"\*\*Rt\+1\*\*[:\s]+([\d.]+)", receipt_text, re.IGNORECASE)

    # All 5 fields must be present
    if not all([y_star_match, x_t_match, u_match, y_t_plus_1_match, rt_match]):
        return None

    # Parse U into list of actions (splits on numbered items like "(1)" or "1.")
    u_text = u_match.group(1).strip()
    u_actions = re.split(r"\(\d+\)|\d+\.", u_text)
    u_actions = [a.strip() for a in u_actions if a.strip()]

    return {
        "y_star": y_star_match.group(1).strip(),
        "x_t": x_t_match.group(1).strip(),
        "u": u_actions,
        "y_t_plus_1": y_t_plus_1_match.group(1).strip(),
        "rt_value": float(rt_match.group(1)),
    }


def _emit_rt_measurement_from_receipt(five_tuple: dict, actual_rt: float) -> None:
    """
    Auto-emit RT_MEASUREMENT CIEU event from parsed 5-tuple receipt.

    Args:
        five_tuple: dict from _extract_5tuple_from_receipt
        actual_rt: Empirical Rt value from validate_receipt
    """
    try:
        # Lazy import to avoid circular dependency
        from ystar.kernel.rt_measurement import emit_rt_measurement

        # Generate task_id from current agent + timestamp
        try:
            from scripts._cieu_helpers import _get_canonical_agent
            agent_id = _get_canonical_agent()
        except ImportError:
            agent_id = "stop_hook"

        task_id = f"{agent_id}_receipt_{int(time.time())}"

        # Emit with actual_rt (empirical gap takes precedence over claimed Rt+1)
        emit_rt_measurement(
            task_id=task_id,
            y_star=five_tuple["y_star"],
            x_t=five_tuple["x_t"],
            u=five_tuple["u"],
            y_t_plus_1=five_tuple["y_t_plus_1"],
            rt_value=actual_rt,  # Use empirical gap, not claimed
            role_tags={
                "producer": agent_id,
                "executor": agent_id,
                "governed": agent_id,
            },
            agent_id=agent_id,
        )
    except Exception as e:
        _log.warning(f"RT_MEASUREMENT auto-emit failed: {e}")


# ── CZL-153: Auto-Verify Receipt Artifacts (eng-kernel) ──────────────────

def verify_receipt_artifacts(receipt_text: str) -> dict:
    """
    CZL-153 P0: Auto-verify artifacts claimed in sub-agent receipts.

    Extracts file paths from receipt prose, checks each with os.path.exists(),
    emits RECEIPT_ARTIFACT_MISSING event for any missing artifacts.

    Args:
        receipt_text: Sub-agent receipt text (full message or notification block)

    Returns:
        dict with keys:
            paths_claimed: list[str] (all paths extracted from receipt)
            paths_verified: list[str] (paths that exist)
            paths_missing: list[str] (paths that DON'T exist)
            verification_passed: bool (True if all claimed paths exist)

    CIEU Events Emitted:
        - RECEIPT_ARTIFACT_MISSING (per missing path, includes path + receipt excerpt)

    Example usage:
        >>> result = verify_receipt_artifacts(subagent_receipt)
        >>> if not result["verification_passed"]:
        ...     log.warning(f"Missing: {result['paths_missing']}")

    Design:
        - Uses existing _extract_artifact_paths_from_prose() regex engine
        - os.path.exists() on each extracted path
        - Emits one CIEU event PER missing path (not batch) for audit granularity
        - Graceful skip if no paths extracted (not all receipts claim artifacts)
    """
    # Extract paths using existing regex engine
    claimed_paths = _extract_artifact_paths_from_prose(receipt_text)

    # Handle no-paths case gracefully (not all receipts claim file artifacts)
    if not claimed_paths:
        return {
            "paths_claimed": [],
            "paths_verified": [],
            "paths_missing": [],
            "verification_passed": True,  # No claims = no violations
        }

    # Check each path with os.path.exists()
    paths_verified = []
    paths_missing = []

    for path in claimed_paths:
        if path.exists():
            paths_verified.append(str(path))
        else:
            paths_missing.append(str(path))

            # Emit one CIEU event per missing path (granular audit trail)
            # Extract 100-char receipt excerpt around path mention for context
            path_str = str(path)
            try:
                idx = receipt_text.index(path_str)
                excerpt_start = max(0, idx - 50)
                excerpt_end = min(len(receipt_text), idx + len(path_str) + 50)
                receipt_excerpt = receipt_text[excerpt_start:excerpt_end]
            except ValueError:
                # Path not found in receipt (edge case: absolute vs relative)
                receipt_excerpt = f"(path {path_str} not found in receipt text)"

            _emit_cieu_event("RECEIPT_ARTIFACT_MISSING", {
                "path": path_str,
                "receipt_excerpt": receipt_excerpt,
                "receipt_length": len(receipt_text),
            })

    # Return verification summary
    return {
        "paths_claimed": [str(p) for p in claimed_paths],
        "paths_verified": paths_verified,
        "paths_missing": paths_missing,
        "verification_passed": len(paths_missing) == 0,
    }


# ── Coordinator Audit Injector (Meta-level Gate) ─────────────────────────

def scan_action_promises(reply_text: str, tool_use_count: int = 0, agent_id: str = "ceo") -> dict:
    """
    ARCH-11c: Detect "say != do" — action promises in reply without tool_uses.

    Scans reply text for promise phrases ("NOW doing X", "dispatching Y",
    "I am spawning Z", etc). If promise count > tool_use count, creates an
    OmissionEngine obligation via register_action_promise_obligation().

    Args:
        reply_text:      Agent's reply text to scan
        tool_use_count:  Number of tool_uses in the same turn
        agent_id:        Agent whose reply is being scanned

    Returns:
        dict with keys:
            promises_detected: list[str] (matched promise phrases)
            promise_count:     int
            tool_use_count:    int
            deficit:           int (promises - tool_uses, 0 if no deficit)
            obligation_created: bool
            warning:           str | None (system-reminder XML if deficit > 0)
    """
    import re as _re
    import uuid as _uuid

    ACTION_PROMISE_PATTERNS = [
        _re.compile(r'NOW\s+(做|执行|dispatching|spawning|running|fixing)', _re.IGNORECASE),
        _re.compile(r'我立刻'),
        _re.compile(r'I am (doing|dispatching|spawning|running|executing|fixing)', _re.IGNORECASE),
        _re.compile(r'正在(执行|派|做|跑|修)'),
        _re.compile(r'dispatching\s+\w+', _re.IGNORECASE),
        _re.compile(r'spawning\s+\w+', _re.IGNORECASE),
        _re.compile(r'(立即|马上)(执行|开始|做|派)', _re.IGNORECASE),
    ]

    matched = []
    for pattern in ACTION_PROMISE_PATTERNS:
        m = pattern.search(reply_text)
        if m:
            matched.append(m.group(0))

    deficit = max(0, len(matched) - tool_use_count)

    result = {
        "promises_detected": matched,
        "promise_count": len(matched),
        "tool_use_count": tool_use_count,
        "deficit": deficit,
        "obligation_created": False,
        "warning": None,
    }

    if deficit <= 0 or not matched:
        return result

    # Register obligation via OmissionEngine
    reply_id = str(_uuid.uuid4())
    try:
        from ystar.governance.omission_engine import OmissionEngine
        from ystar.governance.omission_store import InMemoryOmissionStore

        engine = OmissionEngine(store=InMemoryOmissionStore())
        engine.register_action_promise_obligation(
            agent_id=agent_id,
            reply_id=reply_id,
            promise_phrases=matched,
            tool_use_count=tool_use_count,
            ttl_replies=1,
        )
        result["obligation_created"] = True
    except Exception as e:
        _log.warning(f"[ARCH-11c] OmissionEngine registration failed: {e}")

    # Build warning
    result["warning"] = (
        f"<system-reminder>ARCH-11c ACTION_PROMISE_WITHOUT_TOOL_USE: "
        f"Reply contains {len(matched)} action promise(s) "
        f"[{', '.join(matched)}] but only {tool_use_count} tool_use(s). "
        f"OmissionEngine obligation created (reply_id={reply_id}). "
        f"Next reply without matching tool_uses will be blocked. "
        f"Execute promised actions or retract claims.</system-reminder>"
    )

    # Emit CIEU event
    _emit_cieu_event("ACTION_PROMISE_WITHOUT_TOOL_USE", {
        "promise_agent_id": agent_id,
        "promises": matched,
        "promise_count": len(matched),
        "tool_use_count": tool_use_count,
        "deficit": deficit,
        "reply_id": reply_id,
    })

    return result


def inject_coordinator_audit_warning(
    reply_text: str,
    taskstate: list[dict] | None = None,
) -> Optional[str]:
    """
    CZL Meta-Gate: Validate coordinator (CEO/CTO) closure claims against task state.

    Triggered on Stop hook BEFORE reply delivery to detect:
    - CEO claiming "wave 收敛" while 12+ pending tasks exist
    - CTO claiming "all green" while test failures pending
    - Coordinator summaries with closure language but Rt+1 > 0

    Args:
        reply_text: CEO/CTO reply text (full message)
        taskstate: Optional list of task dicts with {id, status, description}.
                  If None, no validation performed (graceful skip).

    Returns:
        str: <system-reminder> warning block (or None if no violation)

    CIEU Events Emitted:
        - COORDINATOR_SUMMARY_DRIFT_DETECTED (on violation)

    Integration Point:
        OpenClaw `.claude/hooks/on_stop.py` should call after reply composition:
            correction = inject_coordinator_audit_warning(reply_text, taskstate)
            if correction:
                append_to_reply(correction)

    Example usage:
        >>> warning = inject_coordinator_audit_warning(
        ...     reply_text="今晚 wave 完整收敛...",
        ...     taskstate=[{"id": "T1", "status": "pending", "description": "Fix bug"}]
        ... )
        >>> # Returns <system-reminder> if closure claim detected with unjustified pending
    """
    # Import coordinator_audit helper
    try:
        from ystar.governance.coordinator_audit import check_summary_rt_drift
    except ImportError:
        _log.warning("coordinator_audit module not available (governance package not installed)")
        return None

    # Skip validation if no taskstate provided (graceful degradation)
    if taskstate is None:
        return None

    # Run coordinator audit check
    violation = check_summary_rt_drift(reply_text, taskstate)
    if not violation:
        # No closure claim or all pending tasks justified → silent pass
        return None

    # Extract violation details
    claim_phrase = violation.get("claim_phrase", "unknown")
    pending_count = violation.get("pending_count", 0)
    unjustified_ids = violation.get("unjustified_pending_ids", [])

    # Emit CIEU event for audit trail
    _emit_cieu_event("COORDINATOR_SUMMARY_DRIFT_DETECTED", {
        "claim_phrase": claim_phrase,
        "pending_count": pending_count,
        "unjustified_pending_ids": unjustified_ids,
        "reply_length": len(reply_text),
    })

    # Format warning XML
    unjustified_ids_str = ", ".join(unjustified_ids[:5])  # Limit to first 5 IDs
    if len(unjustified_ids) > 5:
        unjustified_ids_str += f"... (+ {len(unjustified_ids) - 5} more)"

    return f"""<system-reminder>
⚠️ CZL Meta-Gate Violation: Coordinator Summary Rt Drift

Reply claimed "{claim_phrase}" but {pending_count} pending task(s) remain unjustified.

Unjustified pending IDs: {unjustified_ids_str}

Coordinator closure language requires Rt+1 = 0.0 OR explicit deferral rationale
("defer Phase 2", "Board-blocked", "pending Board approval").

DO NOT claim closure until all tasks are either:
  1. Completed (status != "pending")
  2. Explicitly deferred with Board-approved rationale

See: ystar/governance/coordinator_audit.py — check_summary_rt_drift()
</system-reminder>"""

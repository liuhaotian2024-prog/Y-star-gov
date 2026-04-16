"""
ystar/governance/charter_drift.py
==================================

Charter drift detection helper for ForgetGuard mid-session compliance.

SCOPE: Detect when charter files (AGENTS.md, CLAUDE.md, governance/*.md, .claude/agents/*.md)
       are modified after session_start_ts, indicating silent constitutional drift risk.

INTEGRATION: ForgetGuard rule `charter_drift_mid_session` (warn) calls this helper,
             emits CIEU `CHARTER_DRIFT_DETECTED` per drifted file.

INVOCATION: Scheduled via governance loop or hook daemon background scan.
            Session start timestamp sourced from .ystar_session.json or governance_boot.sh.

Author: Maya Patel (eng-governance)
Date: 2026-04-16
"""
import os
from pathlib import Path
from typing import List, Dict, Optional
import time


def detect_charter_drift(
    reference_paths: Optional[List[str]] = None,
    session_start_ts: float = 0.0,
    workspace_root: Optional[Path] = None
) -> List[Dict[str, any]]:
    """
    Detect charter files modified after session start.

    Args:
        reference_paths: List of file/glob patterns to monitor. Defaults to:
            - AGENTS.md
            - CLAUDE.md
            - governance/*.md
            - .claude/agents/*.md
        session_start_ts: Unix timestamp (seconds). Files modified after this timestamp
                          are flagged as drifted. Default 0.0 (all files drift).
        workspace_root: Base directory for resolving relative paths. Defaults to
                        parent of ystar/ package (ystar-company repo).

    Returns:
        List of drift events, each dict containing:
            {
                "path": str,                    # Relative path to drifted file
                "previous_mtime": float,        # File mtime (Unix timestamp)
                "current_mtime": float,         # Alias for previous_mtime (same value)
                "session_start_ts": float,      # Session start baseline
                "drift_seconds": float,         # current_mtime - session_start_ts
                "diff_summary": str             # Git diff --stat or "git unavailable"
            }

    Example:
        >>> drifted = detect_charter_drift(reference_paths=["AGENTS.md"], session_start_ts=time.time()-300)
        >>> print(drifted)
        [{"path": "AGENTS.md", "previous_mtime": 1744932000.0, ...}]
    """
    if workspace_root is None:
        # Infer workspace root: ystar/governance/charter_drift.py -> ../../.. (ystar-company)
        workspace_root = Path(__file__).resolve().parent.parent.parent.parent / "ystar-company"
        if not workspace_root.exists():
            # Fallback: current working directory
            workspace_root = Path.cwd()

    if reference_paths is None:
        reference_paths = [
            "AGENTS.md",
            "CLAUDE.md",
            "governance/*.md",
            ".claude/agents/*.md"
        ]

    drift_events = []

    for pattern in reference_paths:
        # Resolve glob patterns
        if "*" in pattern:
            matches = list(workspace_root.glob(pattern))
        else:
            # Single file path
            candidate = workspace_root / pattern
            matches = [candidate] if candidate.exists() else []

        for file_path in matches:
            if not file_path.is_file():
                continue  # Skip directories

            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                continue  # File unreadable or deleted, skip gracefully

            if mtime > session_start_ts:
                # File drifted after session start
                diff_summary = _get_diff_summary(file_path, workspace_root)
                drift_events.append({
                    "path": str(file_path.relative_to(workspace_root)),
                    "previous_mtime": mtime,
                    "current_mtime": mtime,
                    "session_start_ts": session_start_ts,
                    "drift_seconds": mtime - session_start_ts,
                    "diff_summary": diff_summary
                })

    return drift_events


def _get_diff_summary(file_path: Path, workspace_root: Path) -> str:
    """
    Fetch git diff --stat for the drifted file.

    Args:
        file_path: Absolute path to the drifted file.
        workspace_root: Git repository root.

    Returns:
        Git diff summary string or "git unavailable" if git command fails.
    """
    try:
        import subprocess
        relative_path = file_path.relative_to(workspace_root)
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD", str(relative_path)],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            # No diff (file not committed yet or no changes in index)
            return "no git diff (possibly new/unstaged file)"
    except Exception:
        return "git unavailable"


if __name__ == "__main__":
    # CLI test: detect drift from 5 minutes ago
    import sys
    baseline_ts = time.time() - 300  # 5 minutes ago
    drifted = detect_charter_drift(session_start_ts=baseline_ts)
    if drifted:
        print(f"Detected {len(drifted)} drifted charter file(s):")
        for event in drifted:
            print(f"  {event['path']} (+{event['drift_seconds']:.1f}s)")
            print(f"    {event['diff_summary']}")
    else:
        print("No charter drift detected.")
    sys.exit(0 if not drifted else 1)

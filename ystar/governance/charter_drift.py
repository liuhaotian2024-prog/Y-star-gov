"""
ystar/governance/charter_drift.py
==================================

Charter drift detection helper for ForgetGuard mid-session compliance.

SCOPE: Detect when charter files (AGENTS.md, CLAUDE.md, governance/*.md, .claude/agents/*.md)
       are modified via SHA256 content hash comparison (replaces mtime-based detection).

INTEGRATION: ForgetGuard rule `charter_drift_mid_session` (warn) calls this helper,
             emits CIEU `CHARTER_DRIFT_DETECTED` per drifted file.

INVOCATION: Scheduled via governance loop or hook daemon background scan.
            Baseline hashes stored in .charter_baseline_hashes.json at session start.

RATIONALE: mtime-only detection causes false positives (touch/filesystem ops without content change).
           SHA256 content hash comparison eliminates false positives (CZL-85, Issue #27).

Author: eng-governance
Date: 2026-04-16
"""
import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
import time


def detect_charter_drift(
    reference_paths: Optional[List[str]] = None,
    session_start_ts: float = 0.0,
    workspace_root: Optional[Path] = None
) -> List[Dict[str, any]]:
    """
    Detect charter files modified via SHA256 content hash comparison.

    Args:
        reference_paths: List of file/glob patterns to monitor. Defaults to:
            - AGENTS.md
            - CLAUDE.md
            - governance/*.md
            - .claude/agents/*.md
        session_start_ts: Deprecated (kept for backward compat). Not used in hash-based detection.
        workspace_root: Base directory for resolving relative paths. Defaults to
                        parent of ystar/ package (ystar-company repo).

    Returns:
        List of drift events, each dict containing:
            {
                "path": str,                    # Relative path to drifted file
                "previous_hash": str,           # SHA256 baseline hash (hex)
                "current_hash": str,            # SHA256 current hash (hex)
                "session_start_ts": float,      # Session start baseline (deprecated)
                "hash_changed": bool,           # True if content changed
                "diff_summary": str             # Git diff --stat or "git unavailable"
            }

    Example:
        >>> drifted = detect_charter_drift(reference_paths=["AGENTS.md"])
        >>> print(drifted)
        [{"path": "AGENTS.md", "previous_hash": "abc123...", "current_hash": "def456...", ...}]
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

    # Load baseline hashes (or create if missing)
    baseline_file = workspace_root / ".charter_baseline_hashes.json"
    baselines = _load_baseline_hashes(baseline_file)

    drift_events = []
    updated_baselines = {}

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
                current_hash = _compute_file_hash(file_path)
            except OSError:
                continue  # File unreadable or deleted, skip gracefully

            rel_path = str(file_path.relative_to(workspace_root))
            baseline_hash = baselines.get(rel_path)

            if baseline_hash is None:
                # First scan: record baseline hash, skip drift check
                updated_baselines[rel_path] = current_hash
                continue

            if current_hash != baseline_hash:
                # Content changed: true drift
                diff_summary = _get_diff_summary(file_path, workspace_root)
                drift_events.append({
                    "path": rel_path,
                    "previous_hash": baseline_hash,
                    "current_hash": current_hash,
                    "session_start_ts": session_start_ts,  # Deprecated field
                    "hash_changed": True,
                    "diff_summary": diff_summary
                })
                updated_baselines[rel_path] = current_hash  # Update baseline
            else:
                # No content change: no drift
                updated_baselines[rel_path] = baseline_hash  # Preserve baseline

    # Save updated baselines (merge with existing)
    _save_baseline_hashes(baseline_file, {**baselines, **updated_baselines})

    return drift_events


def _compute_file_hash(file_path: Path) -> str:
    """
    Compute SHA256 hash of file content.

    Args:
        file_path: Absolute path to the file.

    Returns:
        SHA256 hash (hex string).
    """
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        # Read in chunks to handle large files efficiently
        for chunk in iter(lambda: f.read(65536), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def _load_baseline_hashes(baseline_file: Path) -> Dict[str, str]:
    """
    Load baseline hashes from JSON file.

    Args:
        baseline_file: Path to .charter_baseline_hashes.json.

    Returns:
        Dict mapping relative file paths to SHA256 hashes.
    """
    if not baseline_file.exists():
        return {}
    try:
        with open(baseline_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_baseline_hashes(baseline_file: Path, baselines: Dict[str, str]) -> None:
    """
    Save baseline hashes to JSON file.

    Args:
        baseline_file: Path to .charter_baseline_hashes.json.
        baselines: Dict mapping relative file paths to SHA256 hashes.
    """
    try:
        with open(baseline_file, 'w') as f:
            json.dump(baselines, f, indent=2, sort_keys=True)
    except OSError:
        pass  # Graceful failure if file cannot be written


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
    # CLI test: detect drift via SHA256 content hash
    import sys
    drifted = detect_charter_drift()
    if drifted:
        print(f"Detected {len(drifted)} drifted charter file(s):")
        for event in drifted:
            print(f"  {event['path']} (hash: {event['previous_hash'][:8]}... -> {event['current_hash'][:8]}...)")
            print(f"    {event['diff_summary']}")
    else:
        print("No charter drift detected.")
    sys.exit(0 if not drifted else 1)

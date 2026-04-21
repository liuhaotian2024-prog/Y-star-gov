"""
enforcement_observer.py — Auto-Enforcement Meta-Observer

Scans governance charters + CIEU drift events → detects enforcement gaps
using 6 criteria framework (spec: governance/auto_enforce_meta.md).

Usage:
    from ystar.governance.enforcement_observer import scan_pending_enforcement_candidates
    candidates = scan_pending_enforcement_candidates()
    for c in candidates:
        print(c["rule_id"], c["priority"], c["criteria_met"])
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from ystar.governance.cieu_store import CIEUStore
except ImportError:
    CIEUStore = None  # type: ignore


# ── Constants ──────────────────────────────────────────────────────────

# Lookback window for recurrence detection (30 days)
RECURRENCE_WINDOW_DAYS = 30

# Governance file scan roots (relative to ystar-company repo)
GOVERNANCE_ROOTS = [
    "governance/",
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/agents/",
]

# Constitutional keyword patterns (C2 criterion)
CONSTITUTIONAL_PATTERNS = [
    r"\bIron Rule\b",
    r"\bConstitutional\b",
    r"\bBoard \d{4}-\d{2}-\d{2}\b",
    r"\bnon-violable\b",
]

# Severity high/critical keywords (C3 criterion)
SEVERITY_PATTERNS = [
    r"severity:\s*(P0|P1|critical)",
    r"# severity:\s*(P0|P1|critical)",
]

# Self-referential governance keywords (C6 criterion)
META_GOVERNANCE_PATTERNS = [
    r"Atomic Dispatch",
    r"L-tag",
    r"CIEU",
    r"enforcement",
    r"governance loop",
    r"Rt\+1",
]


@dataclass
class RuleCandidate:
    """Enforcement gap candidate extracted from governance files."""
    rule_id: str
    source: str
    text_snippet: str  # first 200 chars for context
    heading: str = ""  # original heading text (for criteria matching)


# ── C1: Recurrence Detection ───────────────────────────────────────────

def _check_recurrence(rule_id: str, cieu: CIEUStore | None) -> tuple[bool, float]:
    """
    Return (has_recurrence, last_violation_ts).
    Queries CIEU for drift events mentioning rule_id in violations array.
    """
    if cieu is None:
        return False, 0.0

    cutoff = time.time() - (RECURRENCE_WINDOW_DAYS * 86400)
    try:
        # Query with broad pattern to get drift events
        # Note: for testing, mock will return whatever is set in query.return_value
        all_rows = cieu.query(pattern=rule_id, limit=500)
        violations_found = []
        for row in all_rows:
            # Filter for drift event_type (optional check, may not be set in mock)
            # Only skip if event_type is explicitly set AND doesn't contain DRIFT
            if hasattr(row, 'event_type') and row.event_type:
                if isinstance(row.event_type, str) and 'DRIFT' not in row.event_type.upper():
                    continue
            if hasattr(row, 'created_at') and row.created_at and row.created_at < cutoff:
                continue
            # Parse violations array
            violations_raw = getattr(row, 'violations', None)
            try:
                violations = json.loads(violations_raw or "[]")
            except (json.JSONDecodeError, TypeError):
                violations = []
            # Check if rule_id appears in any violation dict
            for v in violations:
                if isinstance(v, dict) and v.get("rule_id") == rule_id:
                    ts = getattr(row, 'created_at', 0.0) or 0.0
                    violations_found.append(ts)
        if violations_found:
            return True, max(violations_found)
        return False, 0.0
    except Exception:
        return False, 0.0


# ── C2: Constitutional Weight ──────────────────────────────────────────

def _check_constitutional(text: str) -> bool:
    """Return True if text contains constitutional keywords."""
    for pattern in CONSTITUTIONAL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# ── C3: Failure Cost ≥P1 ───────────────────────────────────────────────

def _check_severity(text: str) -> bool:
    """Return True if text contains severity: P0/P1/critical annotation."""
    for pattern in SEVERITY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# ── C4: Detectability (ForgetGuard rule exists) ────────────────────────

def _check_detectability(rule_id: str, session_config: dict | None) -> bool:
    """
    Return True if rule_id has a ForgetGuard entry.
    session_config expected from .ystar_session.json.
    """
    if session_config is None:
        return False
    # ForgetGuard rules stored under agents[*].rule_sets[*].rules[*]
    agents = session_config.get("agents", [])
    # Normalize rule_id for fuzzy matching (remove underscores, lowercase)
    rule_id_normalized = rule_id.lower().replace("_", "")
    for agent in agents:
        rule_sets = agent.get("rule_sets", [])
        for rs in rule_sets:
            rules = rs.get("rules", [])
            for r in rules:
                # Fuzzy match: either direction (rule_id in name OR name in rule_id)
                name = r.get("name", "").lower().replace("_", "")
                if rule_id_normalized in name or name in rule_id_normalized:
                    return True
    return False


# ── C5: Self-Comply Gap ────────────────────────────────────────────────

def _check_self_comply_gap(rule_id: str, cieu: CIEUStore | None, agent_id: str) -> bool:
    """
    Return True if agent_id violated its own rule (e.g., CEO violates CEO rule).
    Heuristic: if rule_id contains agent_id substring (case-insensitive).
    """
    if cieu is None:
        return False
    # Simple heuristic: rule_id like "CEO_DISPATCH_SELF_CHECK" and agent_id="ceo"
    if agent_id.lower() in rule_id.lower():
        # Check if any drift record exists with this agent_id
        try:
            drift_rows = cieu.query(pattern=rule_id, limit=100)
            for row in drift_rows:
                if row.agent_id and row.agent_id.lower() == agent_id.lower():
                    return True
        except Exception:
            pass
    return False


# ── C6: Self-Referential (meta-governance) ─────────────────────────────

def _check_meta_governance(text: str) -> bool:
    """Return True if text governs enforcement/governance itself."""
    for pattern in META_GOVERNANCE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


# ── Rule Extraction from Governance Files ──────────────────────────────

def _extract_rule_candidates(repo_root: Path) -> list[RuleCandidate]:
    """
    Scan governance files for rule-like blocks.
    Heuristic: any heading containing "Rule" or "Iron Rule" or "Constitutional".
    """
    candidates = []
    for root_rel in GOVERNANCE_ROOTS:
        root_path = repo_root / root_rel
        if not root_path.exists():
            continue
        # If single file, process directly
        if root_path.is_file():
            _scan_file(root_path, candidates, repo_root)
        # If directory, recurse
        elif root_path.is_dir():
            for md_file in root_path.rglob("*.md"):
                _scan_file(md_file, candidates, repo_root)
    return candidates


def _scan_file(file_path: Path, candidates: list[RuleCandidate], repo_root: Path) -> None:
    """Extract rule blocks from a single markdown file."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    # Find headings like "## Iron Rule 0", "### CEO Dispatch Self-Check", etc.
    # Pattern: line starts with #+ followed by text containing "Rule" or "Constitutional"
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        if not any(kw in heading for kw in ["Rule", "Constitutional", "Obligation", "Doctrine"]):
            continue
        # Extract rule_id from heading (normalize to uppercase with underscores)
        rule_id = re.sub(r"\W+", "_", heading).strip("_").upper()
        # Grab next 200 chars as context
        snippet_start = i + 1
        snippet_lines = lines[snippet_start:snippet_start + 5]
        snippet = "\n".join(snippet_lines)[:200]
        # Use repo_root for relative path calculation
        try:
            source_path = str(file_path.relative_to(repo_root))
        except ValueError:
            source_path = file_path.name  # fallback if not under repo_root
        candidates.append(RuleCandidate(
            rule_id=rule_id,
            source=source_path,
            text_snippet=snippet,
            heading=heading,
        ))


# ── Decision Tree ──────────────────────────────────────────────────────

def _apply_decision_tree(
    candidate: RuleCandidate,
    criteria_met: list[str],
    rt_score: int,
    last_violation_ts: float,
) -> dict[str, Any]:
    """
    Apply 6-criteria decision tree from spec.
    Returns dict with priority, gap_type, recommended_engineer.
    """
    count = len(criteria_met)
    if count < 3:
        return {"priority": "SKIP"}

    # Default fields
    priority = "P1"  # 3 criteria
    gap_type = "unknown"
    recommended_engineer = "eng-platform"  # default (hook engineer)

    if count >= 4:
        priority = "P0"

    # Determine gap type from context (simplified heuristic)
    if "C4_detectability" in criteria_met:
        # Rule has ForgetGuard entry but still fails → likely warn→deny promotion
        gap_type = "promotion_warn_to_deny"
        recommended_engineer = "eng-governance"
    elif rt_score >= 2:
        # High Rt+1 score → missing runtime enforcement
        gap_type = "L3_runtime"
        recommended_engineer = "eng-platform"
    elif "C2_constitutional" in criteria_met and "C5_self_comply" in criteria_met:
        # Constitutional + self-comply gap → Board escalation
        priority = "BOARD_ESCALATE"
        gap_type = "constitutional_self_comply"
        recommended_engineer = "Board"

    return {
        "priority": priority,
        "gap_type": gap_type,
        "recommended_engineer": recommended_engineer,
    }


# ── Main API ───────────────────────────────────────────────────────────

def scan_pending_enforcement_candidates(
    db_path: str = ".ystar_cieu.db",
    repo_root: str | None = None,
) -> list[dict[str, Any]]:
    """
    Scan governance files + CIEU drift events → return enforcement gap candidates.

    Returns:
        List of dicts with schema:
        {
            "rule_id": str,
            "source": str,
            "criteria_met": list[str],  # e.g., ["C1_recurrence", "C2_constitutional"]
            "criteria_count": int,
            "priority": str,  # "P0" | "P1" | "SKIP" | "BOARD_ESCALATE"
            "rt_score": int,
            "last_violation_ts": float,
            "recommended_engineer": str,
            "gap_type": str,
        }
    """
    # Determine repo root (ystar-company)
    if repo_root is None:
        # Assume this module is in Y-star-gov/ystar/governance/
        # and ystar-company is sibling at ../../../ystar-company/
        this_file = Path(__file__).resolve()
        repo_root_path = this_file.parents[3] / "ystar-company"
        if not repo_root_path.exists():
            # Fallback: current working directory
            repo_root_path = Path.cwd()
    else:
        repo_root_path = Path(repo_root)

    # Load CIEU store
    cieu_path = repo_root_path / db_path
    cieu: CIEUStore | None = None
    if CIEUStore is not None and cieu_path.exists():
        try:
            cieu = CIEUStore(db_path=str(cieu_path))
        except Exception:
            pass

    # Load session config for C4 (detectability)
    session_config_path = repo_root_path / ".ystar_session.json"
    session_config: dict | None = None
    if session_config_path.exists():
        try:
            session_config = json.loads(session_config_path.read_text())
        except Exception:
            pass

    # Extract rule candidates from governance files
    rule_candidates = _extract_rule_candidates(repo_root_path)

    results = []
    for candidate in rule_candidates:
        # Evaluate 6 criteria
        criteria_met = []

        # C1: Recurrence
        has_recurrence, last_viol_ts = _check_recurrence(candidate.rule_id, cieu)
        if has_recurrence:
            criteria_met.append("C1_recurrence")

        # C2: Constitutional
        # Combine heading + snippet for full context
        full_text = (candidate.heading + "\n" + candidate.text_snippet) if hasattr(candidate, 'heading') else candidate.text_snippet
        if _check_constitutional(full_text):
            criteria_met.append("C2_constitutional")

        # C3: Severity
        if _check_severity(full_text):
            criteria_met.append("C3_severity")

        # C4: Detectability
        if _check_detectability(candidate.rule_id, session_config):
            criteria_met.append("C4_detectability")

        # C5: Self-comply gap (check all agent IDs)
        # For simplicity, check common role IDs
        for agent_id in ["ceo", "cto", "cmo", "cso", "cfo"]:
            if _check_self_comply_gap(candidate.rule_id, cieu, agent_id):
                criteria_met.append("C5_self_comply")
                break

        # C6: Meta-governance
        if _check_meta_governance(full_text):
            criteria_met.append("C6_meta_governance")

        # Decision tree
        # Note: rt_score would come from Universal Audit matrix; hardcoded 0 here as fallback
        rt_score = 0  # TODO: integrate with audit reports if available
        decision = _apply_decision_tree(candidate, criteria_met, rt_score, last_viol_ts)

        if decision["priority"] == "SKIP":
            continue

        results.append({
            "rule_id": candidate.rule_id,
            "source": candidate.source,
            "criteria_met": criteria_met,
            "criteria_count": len(criteria_met),
            "priority": decision["priority"],
            "rt_score": rt_score,
            "last_violation_ts": last_viol_ts,
            "recommended_engineer": decision["recommended_engineer"],
            "gap_type": decision["gap_type"],
        })

    # Sort by priority (P0 > BOARD_ESCALATE > P1)
    priority_rank = {"P0": 0, "BOARD_ESCALATE": 1, "P1": 2, "SKIP": 9}
    results.sort(key=lambda x: (priority_rank.get(x["priority"], 9), -x["criteria_count"]))

    return results

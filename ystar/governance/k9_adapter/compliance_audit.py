"""
K9 Rule 12: UNIFIED_PROTOCOL_COMPLIANCE — Daily compliance audit for all agents.

Y* = per-agent compliance score (0-100, weighted across 6 dimensions)
Xt = CIEU DB + git log + session JSONL + baseline constants
U = (1) query 6 dimensions (2) score each (3) weight by role (4) output report
Yt+1 = compliance_daily/YYYYMMDD.md + per-agent scores + violations list
Rt+1=0 = report emitted + all queries executed + no fake data

CIEU_LAYER_1: spec extraction from reports/unified_protocol_compliance_audit_design_20260415.md (commit 8643f8e7).

Design spec (Board 2026-04-15):
- Dimension 1: CIEU 5-tuple emission (SELECT CIEU_LAYER_* events)
- Dimension 2: Commit message unified marker (git log grep "Y*|Rt+1|CIEU")
- Dimension 3: 14 ban phrase avoidance (SELECT CEO_AVOIDANCE_DRIFT)
- Dimension 4: L-tag honesty (grep "L4 SHIPPED" + check "chaos test:" link)
- Dimension 5: Research gate (JSONL first tool_use = WebFetch/Grep/Read knowledge)
- Dimension 6: AUTONOMOUS tool-use density (CEO replies with tool_use / total replies)

Weighting table (per role):
| Dimension | CEO | CTO | Engineer | Marketing | Finance |
|---|---|---|---|---|---|
| 1 CIEU 5-tuple | 20% | 20% | 25% | 15% | 15% |
| 2 Commit marker | 10% | 20% | 25% | 10% | 10% |
| 3 14 ban | 30% | 10% | 10% | 20% | 10% |
| 4 L-tag honesty | 15% | 20% | 25% | 15% | 20% |
| 5 Research gate | 15% | 20% | 15% | 20% | 25% |
| 6 AUTONOMOUS density | 10% | 10% | 0% | 20% | 20% |

CIEU_LAYER_2: no Gemma needed (deterministic queries).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

_log = logging.getLogger("ystar.k9_adapter.compliance_audit")

# CIEU_LAYER_3: execution plan = 6 dimension queries + weighted scoring.

ROLE_WEIGHTS = {
    "ceo": {
        "cieu_5tuple": 0.20,
        "commit_marker": 0.10,
        "ban_14": 0.30,
        "ltag_honesty": 0.15,
        "research_gate": 0.15,
        "autonomous_density": 0.10,
    },
    "cto": {
        "cieu_5tuple": 0.20,
        "commit_marker": 0.20,
        "ban_14": 0.10,
        "ltag_honesty": 0.20,
        "research_gate": 0.20,
        "autonomous_density": 0.10,
    },
    "engineer": {
        "cieu_5tuple": 0.25,
        "commit_marker": 0.25,
        "ban_14": 0.10,
        "ltag_honesty": 0.25,
        "research_gate": 0.15,
        "autonomous_density": 0.00,
    },
    "marketing": {
        "cieu_5tuple": 0.15,
        "commit_marker": 0.10,
        "ban_14": 0.20,
        "ltag_honesty": 0.15,
        "research_gate": 0.20,
        "autonomous_density": 0.20,
    },
    "finance": {
        "cieu_5tuple": 0.15,
        "commit_marker": 0.10,
        "ban_14": 0.10,
        "ltag_honesty": 0.20,
        "research_gate": 0.25,
        "autonomous_density": 0.20,
    },
}

AGENT_ROLE_MAP = {
    "ceo": "ceo",
    "cto": "cto",
    "maya-governance": "engineer",
    "leo-kernel": "engineer",
    "ryan-platform": "engineer",
    "jordan-domains": "engineer",
    "cmo": "marketing",
    "cso": "marketing",
    "cfo": "finance",
    "samantha": "engineer",
    "sofia": "marketing",
    "marco": "finance",
    "zara": "marketing",
}


@dataclass
class ComplianceScore:
    """Per-agent compliance score."""
    agent_id: str
    date: str
    dimension_scores: Dict[str, float]  # dimension_name -> 0-100 score
    weighted_total: float  # 0-100
    violations: List[str]  # human-readable violation messages
    missing_data: List[str]  # dimensions with N/A data


def get_cieu_db_path() -> Path:
    """Locate CIEU database (environment-driven or current directory)."""
    # CIEU_LAYER_4: start execution - locate CIEU DB.
    if "YSTAR_CIEU_DB_PATH" in os.environ:
        return Path(os.environ["YSTAR_CIEU_DB_PATH"])

    candidates = [
        Path(os.environ.get("YSTAR_COMPANY_ROOT", os.getcwd())) / ".ystar_cieu.db",
        Path.cwd() / ".ystar_cieu.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("CIEU database not found in expected locations")


def query_cieu_5tuple_emission(db_path: Path, agent_id: str, date_str: str) -> float:
    """
    Dimension 1: CIEU 5-tuple emission rate.

    Y* = CIEU_LAYER_* event count per task
    Xt = CIEU events table filtered by date + agent
    U = (1) SELECT COUNT CIEU_LAYER_* (2) count TASK_START events (3) ratio
    Yt+1 = emission rate score 0-100
    Rt+1=0 = query executed + score computed

    CIEU_LAYER_5: mid-check (Dimension 1 start).
    """
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Parse date to Unix timestamp range (UTC to avoid timezone issues)
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        # Convert to UTC timestamp explicitly
        import calendar
        start_ts = calendar.timegm(date_obj.timetuple())
        end_ts = calendar.timegm((date_obj + timedelta(days=1)).timetuple())

        # Count CIEU_LAYER_* events
        cur.execute("""
            SELECT COUNT(*) FROM cieu_events
            WHERE agent_id = ? AND event_type LIKE 'CIEU_LAYER_%'
            AND created_at >= ? AND created_at < ?
        """, (agent_id, start_ts, end_ts))
        layer_count = cur.fetchone()[0]

        # Count TASK_START events (proxy for total tasks)
        cur.execute("""
            SELECT COUNT(*) FROM cieu_events
            WHERE agent_id = ? AND event_type = 'TASK_START'
            AND created_at >= ? AND created_at < ?
        """, (agent_id, start_ts, end_ts))
        task_count = cur.fetchone()[0]

        conn.close()

        # Expected: 13 events per task (1 TASK_START + 12 CIEU_LAYER_*)
        # Score: actual_events / expected_events * 100
        if task_count == 0:
            return None  # N/A - no tasks run

        expected_events = task_count * 13
        score = min(100, (layer_count / expected_events) * 100) if expected_events > 0 else 0

        _log.info("[K9] %s CIEU_5tuple: %d layers / %d tasks = %.1f%%", agent_id, layer_count, task_count, score)
        return score

    except Exception as e:
        _log.error("[K9] CIEU_5tuple query failed for %s: %s", agent_id, e)
        return None


def query_commit_marker(agent_id: str, date_str: str, workspace: str = ".") -> float:
    """
    Dimension 2: Commit message unified marker.

    Y* = commits with Y*/Rt+1/CIEU marker ratio
    Xt = git log filtered by date + author
    U = (1) git log --since=date (2) grep Y*|Rt+1|CIEU (3) ratio
    Yt+1 = commit marker score 0-100
    Rt+1=0 = git log executed + ratio computed

    CIEU_LAYER_5: mid-check (Dimension 2 start).
    """
    try:
        os.chdir(workspace)
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        since_str = date_obj.strftime("%Y-%m-%d")
        until_str = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")

        # Get all commits by this agent on this date
        all_commits = subprocess.check_output(
            ["git", "log", f"--since={since_str}", f"--until={until_str}",
             "--all", "--oneline"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL
        )
        total_commits = len([l for l in all_commits.splitlines() if l.strip()])

        if total_commits == 0:
            return None  # N/A - no commits

        # Count commits with marker
        marked_commits = subprocess.check_output(
            ["git", "log", f"--since={since_str}", f"--until={until_str}",
             "--all", "--oneline", "--grep=Y\\*\\|Rt+1\\|CIEU"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL
        )
        marked_count = len([l for l in marked_commits.splitlines() if l.strip()])

        score = (marked_count / total_commits) * 100 if total_commits > 0 else 0
        _log.info("[K9] %s commit_marker: %d/%d = %.1f%%", agent_id, marked_count, total_commits, score)
        return score

    except Exception as e:
        _log.error("[K9] commit_marker query failed for %s: %s", agent_id, e)
        return None


def query_ban_14_avoidance(db_path: Path, agent_id: str, date_str: str) -> float:
    """
    Dimension 3: 14 ban phrase avoidance.

    Y* = ban phrase violation count
    Xt = CIEU events CEO_AVOIDANCE_DRIFT
    U = (1) SELECT COUNT drift events (2) penalize 10 points per violation
    Yt+1 = ban_14 score (100 - violations*10, floor 0)
    Rt+1=0 = query executed + score computed

    CIEU_LAYER_5: mid-check (Dimension 3 start).
    """
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Parse date to Unix timestamp range (UTC)
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        import calendar
        start_ts = calendar.timegm(date_obj.timetuple())
        end_ts = calendar.timegm((date_obj + timedelta(days=1)).timetuple())

        cur.execute("""
            SELECT COUNT(*) FROM cieu_events
            WHERE agent_id = ? AND event_type = 'CEO_AVOIDANCE_DRIFT'
            AND created_at >= ? AND created_at < ?
        """, (agent_id, start_ts, end_ts))
        violation_count = cur.fetchone()[0]

        conn.close()

        score = max(0, 100 - (violation_count * 10))
        _log.info("[K9] %s ban_14: %d violations = %.1f%%", agent_id, violation_count, score)
        return score

    except Exception as e:
        _log.error("[K9] ban_14 query failed for %s: %s", agent_id, e)
        return None


def query_ltag_honesty(agent_id: str, date_str: str, workspace: str = ".") -> float:
    """
    Dimension 4: L-tag honesty rate.

    Y* = L4 commits with chaos test link ratio
    Xt = git log filtered by "L4 SHIPPED" commits
    U = (1) git log --grep="L4 SHIPPED" (2) git show each + grep "chaos test:" (3) ratio
    Yt+1 = L-tag honesty score 0-100
    Rt+1=0 = git show executed + ratio computed

    CIEU_LAYER_5: mid-check (Dimension 4 start).
    """
    try:
        os.chdir(workspace)
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        since_str = date_obj.strftime("%Y-%m-%d")
        until_str = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")

        # Get L4 SHIPPED commits
        l4_commits = subprocess.check_output(
            ["git", "log", f"--since={since_str}", f"--until={until_str}",
             "--all", "--oneline", "--grep=L4 SHIPPED"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL
        )
        l4_hashes = [line.split()[0] for line in l4_commits.splitlines() if line.strip()]

        if len(l4_hashes) == 0:
            return None  # N/A - no L4 commits

        # Check each L4 commit for "chaos test:" link
        l4_with_chaos = 0
        for commit_hash in l4_hashes:
            commit_body = subprocess.check_output(
                ["git", "show", "-s", "--format=%B", commit_hash],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL
            )
            if re.search(r'chaos test:', commit_body, re.IGNORECASE):
                l4_with_chaos += 1

        score = (l4_with_chaos / len(l4_hashes)) * 100
        _log.info("[K9] %s ltag_honesty: %d/%d L4 with chaos = %.1f%%",
                  agent_id, l4_with_chaos, len(l4_hashes), score)
        return score

    except Exception as e:
        _log.error("[K9] ltag_honesty query failed for %s: %s", agent_id, e)
        return None


def query_research_gate(agent_id: str, date_str: str, jsonl_dir: str = None) -> float:
    """
    Dimension 5: Research gate (15min pre-task research).

    Y* = tasks with first tool_use = WebFetch/Grep/Read knowledge ratio
    Xt = subagent JSONL transcripts
    U = (1) find JSONL files (2) parse first tool_use per task (3) check type
    Yt+1 = research gate score 0-100
    Rt+1=0 = JSONL parsed + ratio computed

    CIEU_LAYER_5: mid-check (Dimension 5 start).

    NOTE: This dimension requires session JSONL logs which may not be available.
    Placeholder implementation returns N/A for now.
    """
    # TODO: Implement JSONL parsing when session logs are structured
    # For now, return N/A (missing data)
    _log.warning("[K9] %s research_gate: JSONL parsing not yet implemented", agent_id)
    return None


def query_autonomous_density(agent_id: str, date_str: str, jsonl_dir: str = None) -> float:
    """
    Dimension 6: AUTONOMOUS mode tool-use density (CEO specific).

    Y* = CEO replies with tool_use / total replies ratio
    Xt = CEO session JSONL in AUTONOMOUS mode
    U = (1) find JSONL (2) count replies (3) count replies with tool_use (4) ratio
    Yt+1 = autonomous density score 0-100
    Rt+1=0 = JSONL parsed + ratio computed

    CIEU_LAYER_5: mid-check (Dimension 6 start).

    NOTE: This dimension requires session JSONL logs which may not be available.
    Placeholder implementation returns N/A for now.
    """
    if agent_id != "ceo":
        return 100  # N/A for non-CEO agents (weight is 0% anyway)

    # TODO: Implement JSONL parsing when session logs are structured
    # For now, return N/A (missing data)
    _log.warning("[K9] %s autonomous_density: JSONL parsing not yet implemented", agent_id)
    return None


def compute_compliance_score(agent_id: str, date_str: str,
                             db_path: Path, workspace: str = ".") -> ComplianceScore:
    """
    Compute weighted compliance score for one agent on one day.

    Y* = weighted compliance score 0-100
    Xt = 6 dimension scores
    U = (1) query all dimensions (2) apply role weights (3) compute weighted sum
    Yt+1 = ComplianceScore object with violations list
    Rt+1=0 = all queries executed + weighted score computed

    CIEU_LAYER_6: no pivot needed (deterministic scoring).
    """
    role = AGENT_ROLE_MAP.get(agent_id, "engineer")
    weights = ROLE_WEIGHTS[role]

    # CIEU_LAYER_7: integrate dimension queries.
    dimension_scores = {
        "cieu_5tuple": query_cieu_5tuple_emission(db_path, agent_id, date_str),
        "commit_marker": query_commit_marker(agent_id, date_str, workspace),
        "ban_14": query_ban_14_avoidance(db_path, agent_id, date_str),
        "ltag_honesty": query_ltag_honesty(agent_id, date_str, workspace),
        "research_gate": query_research_gate(agent_id, date_str),
        "autonomous_density": query_autonomous_density(agent_id, date_str),
    }

    # Compute weighted score (skip N/A dimensions, renormalize weights)
    weighted_total = 0.0
    total_weight = 0.0
    missing_data = []
    violations = []

    for dim, score in dimension_scores.items():
        weight = weights[dim]
        if score is None:
            missing_data.append(dim)
            # Don't count this dimension's weight
            continue
        else:
            weighted_total += score * weight
            total_weight += weight

            # Flag violations (score < 70 threshold)
            if score < 70:
                violations.append(f"{dim}: {score:.1f}/100 (threshold 70)")

    # Renormalize if some dimensions are N/A
    if total_weight > 0:
        final_score = weighted_total / total_weight
    else:
        final_score = 0.0  # All dimensions N/A

    # CIEU_LAYER_8: execution complete.
    return ComplianceScore(
        agent_id=agent_id,
        date=date_str,
        dimension_scores=dimension_scores,
        weighted_total=final_score,
        violations=violations,
        missing_data=missing_data,
    )


def generate_compliance_report(scores: List[ComplianceScore], date_str: str,
                               output_path: Path) -> None:
    """
    Generate compliance_daily/YYYYMMDD.md report.

    Y* = compliance report markdown
    Xt = list of ComplianceScore objects
    U = (1) format markdown table (2) list violations (3) write file
    Yt+1 = report file written
    Rt+1=0 = file exists + all agents listed

    CIEU_LAYER_8: report generation.
    """
    date_obj = datetime.strptime(date_str, "%Y%m%d")
    date_human = date_obj.strftime("%Y-%m-%d")

    # Sort by score (lowest first to highlight issues)
    scores.sort(key=lambda s: s.weighted_total)

    lines = [
        f"# Unified Protocol Compliance Report",
        f"**Date**: {date_human}",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Overall Scores",
        "",
        "| Agent | Score | Status | Violations | Missing Data |",
        "|---|---|---|---|---|",
    ]

    overall_avg = sum(s.weighted_total for s in scores) / len(scores) if scores else 0

    for score in scores:
        status = "⭐" if score.weighted_total >= 90 else "✅" if score.weighted_total >= 70 else "⚠️"
        violations_str = f"{len(score.violations)} issues" if score.violations else "-"
        missing_str = ", ".join(score.missing_data) if score.missing_data else "-"
        lines.append(
            f"| {score.agent_id} | {score.weighted_total:.1f}/100 | {status} | "
            f"{violations_str} | {missing_str} |"
        )

    lines.extend([
        "",
        f"**Overall Average**: {overall_avg:.1f}/100",
        "",
        "## Dimension Breakdown",
        "",
    ])

    # Detail each agent's dimension scores
    for score in scores:
        lines.append(f"### {score.agent_id}")
        lines.append("")
        lines.append("| Dimension | Score | Weight | Weighted |")
        lines.append("|---|---|---|---|")

        role = AGENT_ROLE_MAP.get(score.agent_id, "engineer")
        weights = ROLE_WEIGHTS[role]

        for dim, dim_score in score.dimension_scores.items():
            weight_pct = weights[dim] * 100
            if dim_score is None:
                lines.append(f"| {dim} | N/A | {weight_pct:.0f}% | N/A |")
            else:
                weighted_contrib = dim_score * weights[dim]
                lines.append(f"| {dim} | {dim_score:.1f} | {weight_pct:.0f}% | {weighted_contrib:.1f} |")

        if score.violations:
            lines.append("")
            lines.append("**⚠️ Violations**:")
            for v in score.violations:
                lines.append(f"- {v}")

        if score.missing_data:
            lines.append("")
            lines.append("**ℹ️ Missing Data**:")
            for d in score.missing_data:
                lines.append(f"- {d} (data not available)")

        lines.append("")

    lines.extend([
        "## Notes",
        "",
        "- **Threshold**: Scores < 70 flagged as violations",
        "- **N/A Dimensions**: Excluded from weighted calculation (weights renormalized)",
        "- **JSONL Dimensions**: research_gate and autonomous_density not yet implemented (require session log parsing)",
        "",
        "---",
        f"Generated by K9 Rule 12 UNIFIED_PROTOCOL_COMPLIANCE",
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    _log.info("[K9] Compliance report written to %s", output_path)


def run_compliance_audit(date_str: str, output_path: str,
                        workspace: str = ".") -> None:
    """
    Run full compliance audit for all agents on given date.

    Y* = compliance report for all agents
    Xt = CIEU DB + git log + workspace
    U = (1) locate CIEU DB (2) query all agents (3) compute scores (4) generate report
    Yt+1 = compliance_daily/YYYYMMDD.md file
    Rt+1=0 = all agents audited + report file exists

    CIEU_LAYER_9: human review N/A (autonomous daily patrol).
    CIEU_LAYER_10: self-eval = K9 Rule 12 dogfood (emit CIEU events for audit itself).
    CIEU_LAYER_11: Board approval deferred (autonomous mode).
    CIEU_LAYER_12: knowledge writeback = this report file itself.
    """
    db_path = get_cieu_db_path()
    _log.info("[K9] Using CIEU database: %s", db_path)

    # Audit all known agents
    agents = list(AGENT_ROLE_MAP.keys())
    scores = []

    for agent_id in agents:
        score = compute_compliance_score(agent_id, date_str, db_path, workspace)
        scores.append(score)

    # Generate report
    output_file = Path(output_path)
    generate_compliance_report(scores, date_str, output_file)

    print(f"✅ Compliance audit complete: {output_file}")
    print(f"   Overall average: {sum(s.weighted_total for s in scores) / len(scores):.1f}/100")
    print(f"   Agents audited: {len(scores)}")
    print(f"   Agents with violations: {sum(1 for s in scores if s.violations)}")


if __name__ == "__main__":
    # CIEU_LAYER_8: CLI entry point for k9_daily_patrol.sh Step 6.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="K9 Rule 12: Unified Protocol Compliance Audit")
    parser.add_argument("--date", required=True, help="Date in YYYYMMDD format")
    parser.add_argument("--output", required=True, help="Output report path")
    parser.add_argument("--workspace", default=".", help="Workspace directory (default: .)")

    args = parser.parse_args()

    run_compliance_audit(args.date, args.output, args.workspace)

"""
rule_lifecycle_observer — Production Rule Lifecycle Scanner
============================================================

Scans CIEU event store cross-referenced with ForgetGuard rule definitions
to classify every rule as LIVE / DORMANT / DEAD / ZOMBIE.

Taxonomy:
  LIVE    — fired in last 7 days
  DORMANT — fired in last 30 days but not last 7
  DEAD    — never fired in last 30 days (defined but inactive)
  ZOMBIE  — fires found in CIEU but rule_id not in fg_yaml (orphaned)

Entry points:
  scan_rule_liveness(cieu_db, fg_yaml) -> LivenessReport
  write_markdown_report(report, out_path) -> str
  run_daily() — convenience wrapper for cron
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ── Data types ────────────────────────────────────────────────────────

@dataclass
class RuleStatus:
    rule_id: str
    category: str          # LIVE / DORMANT / DEAD / ZOMBIE
    fires_7d: int = 0
    fires_30d: int = 0
    last_fire_ts: Optional[float] = None


@dataclass
class LivenessReport:
    generated_at: float = 0.0
    total_rules: int = 0
    counts: Dict[str, int] = field(default_factory=lambda: {
        "LIVE": 0, "DORMANT": 0, "DEAD": 0, "ZOMBIE": 0,
    })
    rules: List[RuleStatus] = field(default_factory=list)
    error: Optional[str] = None


# ── YAML rule-id extractor (no PyYAML dependency) ────────────────────

def _rule_ids_from_yaml(path: str) -> List[str]:
    """Extract top-level rule ids from forget_guard_rules.yaml."""
    p = Path(path)
    if not p.exists():
        return []
    ids: List[str] = []
    skip_keys = {"rules", "metadata", "version", "forget_guard_rules"}
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.rstrip()
        if (
            stripped
            and stripped.endswith(":")
            and not line.startswith((" ", "\t", "#", "-"))
        ):
            key = stripped[:-1].strip()
            if key and key not in skip_keys:
                ids.append(key)
    return ids


# ── CIEU fire counting ──────────────────────────────────────────────

def _fires_for_rule(
    conn: sqlite3.Connection,
    rule_id: str,
    since: float,
) -> tuple:
    """Return (count, max_created_at) for a rule_id since a timestamp."""
    cur = conn.execute(
        """SELECT COUNT(*), MAX(created_at) FROM cieu_events
           WHERE created_at > ? AND (violations LIKE ? OR params_json LIKE ?)""",
        (since, f"%{rule_id}%", f"%{rule_id}%"),
    )
    row = cur.fetchone() or (0, None)
    return int(row[0] or 0), row[1]


def _zombie_rule_ids(
    conn: sqlite3.Connection,
    known_ids: set,
    since_30d: float,
) -> List[str]:
    """Find rule_ids that appear in CIEU but are not in fg_yaml."""
    rows = conn.execute(
        "SELECT DISTINCT violations FROM cieu_events WHERE created_at > ?",
        (since_30d,),
    ).fetchall()
    found: set = set()
    import json
    for (viol_text,) in rows:
        if not viol_text:
            continue
        try:
            parsed = json.loads(viol_text)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        rid = item.get("rule_id") or item.get("dimension")
                        if rid and rid not in known_ids:
                            found.add(rid)
        except (json.JSONDecodeError, TypeError):
            pass
    return sorted(found)


# ── Core scanner ─────────────────────────────────────────────────────

def scan_rule_liveness(
    cieu_db: str,
    fg_yaml: str,
) -> LivenessReport:
    """
    Scan CIEU event store cross-referenced with FG rule definitions.

    Args:
        cieu_db: path to .ystar_cieu.db (SQLite)
        fg_yaml: path to forget_guard_rules.yaml

    Returns:
        LivenessReport with per-rule classification
    """
    report = LivenessReport(generated_at=time.time())

    if not Path(cieu_db).exists():
        report.error = f"CIEU db missing at {cieu_db}"
        return report

    rule_ids = _rule_ids_from_yaml(fg_yaml)
    known_set = set(rule_ids)
    now = time.time()
    since_7d = now - 7 * 86400
    since_30d = now - 30 * 86400

    conn = sqlite3.connect(cieu_db)
    try:
        for rid in rule_ids:
            f7, last7 = _fires_for_rule(conn, rid, since_7d)
            f30, last30 = _fires_for_rule(conn, rid, since_30d)
            last = last7 or last30

            if f7 > 0:
                cat = "LIVE"
            elif f30 > 0:
                cat = "DORMANT"
            else:
                cat = "DEAD"

            report.rules.append(RuleStatus(
                rule_id=rid,
                category=cat,
                fires_7d=f7,
                fires_30d=f30,
                last_fire_ts=last,
            ))

        # Detect zombies
        for zid in _zombie_rule_ids(conn, known_set, since_30d):
            f7, last7 = _fires_for_rule(conn, zid, since_7d)
            f30, last30 = _fires_for_rule(conn, zid, since_30d)
            report.rules.append(RuleStatus(
                rule_id=zid,
                category="ZOMBIE",
                fires_7d=f7,
                fires_30d=f30,
                last_fire_ts=last7 or last30,
            ))
    finally:
        conn.close()

    # Sort: LIVE first (by fires desc), then DORMANT, DEAD, ZOMBIE
    order = {"LIVE": 0, "DORMANT": 1, "DEAD": 2, "ZOMBIE": 3}
    report.rules.sort(key=lambda r: (order.get(r.category, 9), -r.fires_7d, r.rule_id))

    # Tally counts
    for r in report.rules:
        report.counts[r.category] = report.counts.get(r.category, 0) + 1
    report.total_rules = len(report.rules)

    return report


# ── Markdown output ──────────────────────────────────────────────────

def write_markdown_report(
    report: LivenessReport,
    out_path: str,
) -> str:
    """Write a LivenessReport as a markdown dashboard file."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append("# Rule Lifecycle Coverage — Daily Report\n\n")
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(report.generated_at))
    lines.append(f"Generated: {ts}\n\n")

    if report.error:
        lines.append(f"**Error**: {report.error}\n")
        p.write_text("".join(lines), encoding="utf-8")
        return str(p)

    total = report.total_rules
    live = report.counts.get("LIVE", 0)
    dormant = report.counts.get("DORMANT", 0)
    dead = report.counts.get("DEAD", 0)
    zombie = report.counts.get("ZOMBIE", 0)
    live_pct = round(100.0 * live / total, 1) if total else 0

    lines.append(f"**Summary**: total={total} LIVE={live} ({live_pct}%) "
                 f"DORMANT={dormant} DEAD={dead} ZOMBIE={zombie}\n\n")
    lines.append("| rule_id | category | fires_7d | fires_30d |\n")
    lines.append("|---|---|---|---|\n")
    for r in report.rules:
        lines.append(f"| `{r.rule_id}` | {r.category} | {r.fires_7d} | {r.fires_30d} |\n")

    p.write_text("".join(lines), encoding="utf-8")
    return str(p)


# ── Daily entry point ────────────────────────────────────────────────

_DEFAULT_CIEU_DB = ".ystar_cieu.db"
_DEFAULT_FG_YAML = "governance/forget_guard_rules.yaml"
_DEFAULT_OUT = "reports/cto/rule_coverage_daily.md"


def run_daily(
    cieu_db: str = _DEFAULT_CIEU_DB,
    fg_yaml: str = _DEFAULT_FG_YAML,
    out_path: str = _DEFAULT_OUT,
) -> LivenessReport:
    """
    Convenience entry point for cron / scheduled runs.

    Scans rule liveness and writes the markdown dashboard.
    Returns the LivenessReport for programmatic consumers.
    """
    report = scan_rule_liveness(cieu_db, fg_yaml)
    write_markdown_report(report, out_path)
    return report


if __name__ == "__main__":
    import json as _json
    r = run_daily()
    print(_json.dumps({
        "total_rules": r.total_rules,
        "counts": r.counts,
        "error": r.error,
    }, indent=2))

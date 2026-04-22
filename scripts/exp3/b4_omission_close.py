"""
Audience: Experiment 3 B4 axis -- Omission obligation closure rate.
Research basis: omission DB has 17314 obligations (108 pending, 176 soft_overdue, 17030 hard_overdue).
Synthesis: query obligations table for status distribution, compute closure_rate = fulfilled / total. Target > 80%.
Purpose: emit per-run JSON so harness launcher aggregates across 8 axes.

Exit codes: 0 pass / 1 fail (below target) / 2 harness error.
"""
import json, sqlite3, sys, time
from pathlib import Path

OMISSION_DB = Path("/Users/haotianliu/.openclaw/workspace/ystar-company/.ystar_cieu_omission.db")
REPORT_DIR = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/ceo/exp3_b4")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_CLOSURE = 0.80
CLOSURE_FLOOR = 0.50


def main():
    if not OMISSION_DB.exists():
        return {"error": f"Omission DB missing at {OMISSION_DB}"}, 2
    conn = sqlite3.connect(f"file:{OMISSION_DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT status, count(*) FROM obligations GROUP BY status").fetchall()
    status_dist = {r[0]: r[1] for r in rows}
    total = sum(status_dist.values())
    fulfilled_keys = {"fulfilled", "completed", "closed", "resolved"}
    fulfilled = sum(v for k, v in status_dist.items() if k.lower() in fulfilled_keys)
    pending = status_dist.get("pending", 0)
    soft_overdue = status_dist.get("soft_overdue", 0)
    hard_overdue = status_dist.get("hard_overdue", 0)
    open_count = pending + soft_overdue + hard_overdue
    entity_rows = conn.execute("SELECT status, count(*) FROM entities GROUP BY status").fetchall()
    entity_dist = {r[0]: r[1] for r in entity_rows}
    violation_count = conn.execute("SELECT count(*) FROM omission_violations").fetchone()[0]
    closure_rate = (fulfilled / total) if total else None
    if closure_rate is None:
        verdict = "inconclusive"
    elif closure_rate >= TARGET_CLOSURE:
        verdict = "pass"
    elif closure_rate < CLOSURE_FLOOR:
        verdict = "fail"
    else:
        verdict = "partial"
    result = {
        "axis": "B4_omission_closure", "timestamp": int(time.time()),
        "target_closure": TARGET_CLOSURE, "total_obligations": total,
        "fulfilled": fulfilled, "pending": pending,
        "soft_overdue": soft_overdue, "hard_overdue": hard_overdue,
        "open_count": open_count, "closure_rate": closure_rate,
        "entity_status_dist": entity_dist, "violation_count": violation_count,
        "obligation_status_dist": status_dist, "verdict": verdict,
    }
    out_path = REPORT_DIR / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result, (1 if verdict == "fail" else 0)


if __name__ == "__main__":
    result, rc = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(rc)

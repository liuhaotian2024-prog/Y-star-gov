"""
Audience: Experiment 3 B6 axis -- CIEU event growth rate.
Research basis: CIEU DB has 350k+ events across 20+ distinct types.
Synthesis: count events and distinct types in rolling 2h window. Target > 500 events AND > 20 distinct types.
Purpose: emit per-run JSON so harness launcher aggregates across 8 axes.

Exit codes: 0 pass / 1 fail (below targets) / 2 harness error.
"""
import json, sqlite3, sys, time
from pathlib import Path

CIEU_DB = Path("/Users/haotianliu/.openclaw/workspace/ystar-company/.ystar_cieu.db")
REPORT_DIR = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/ceo/exp3_b6")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

WINDOW_SECONDS = 2 * 60 * 60
TARGET_EVENT_COUNT = 500
TARGET_DISTINCT_TYPES = 20
EVENT_COUNT_FLOOR = 100
DISTINCT_TYPES_FLOOR = 5


def main():
    if not CIEU_DB.exists():
        return {"error": f"CIEU DB missing at {CIEU_DB}"}, 2
    conn = sqlite3.connect(f"file:{CIEU_DB}?mode=ro", uri=True)
    cutoff = time.time() - WINDOW_SECONDS
    total_count = conn.execute(
        "SELECT count(*) FROM cieu_events WHERE created_at >= ?", (cutoff,)
    ).fetchone()[0]
    type_rows = conn.execute(
        "SELECT event_type, count(*) c FROM cieu_events "
        "WHERE created_at >= ? GROUP BY event_type ORDER BY c DESC", (cutoff,)
    ).fetchall()
    type_dist = {r[0] or "(empty)": r[1] for r in type_rows}
    distinct_types = len(type_dist)
    agent_rows = conn.execute(
        "SELECT agent_id, count(*) c FROM cieu_events "
        "WHERE created_at >= ? GROUP BY agent_id ORDER BY c DESC", (cutoff,)
    ).fetchall()
    agent_dist = {r[0] or "(empty)": r[1] for r in agent_rows}
    decision_rows = conn.execute(
        "SELECT decision, count(*) c FROM cieu_events "
        "WHERE created_at >= ? GROUP BY decision ORDER BY c DESC", (cutoff,)
    ).fetchall()
    decision_dist = {r[0] or "(empty)": r[1] for r in decision_rows}
    count_ok = total_count >= TARGET_EVENT_COUNT
    types_ok = distinct_types >= TARGET_DISTINCT_TYPES
    count_low = total_count < EVENT_COUNT_FLOOR
    types_low = distinct_types < DISTINCT_TYPES_FLOOR
    if count_ok and types_ok:
        verdict = "pass"
    elif count_low or types_low:
        verdict = "fail"
    elif total_count == 0:
        verdict = "inconclusive"
    else:
        verdict = "partial"
    result = {
        "axis": "B6_cieu_growth", "timestamp": int(time.time()),
        "window_seconds": WINDOW_SECONDS,
        "target_event_count": TARGET_EVENT_COUNT,
        "target_distinct_types": TARGET_DISTINCT_TYPES,
        "total_events_in_window": total_count,
        "distinct_event_types": distinct_types,
        "event_type_distribution_top10": dict(list(type_dist.items())[:10]),
        "agent_distribution": agent_dist,
        "decision_distribution": decision_dist,
        "verdict": verdict,
    }
    out_path = REPORT_DIR / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result, (1 if verdict == "fail" else 0)


if __name__ == "__main__":
    result, rc = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(rc)

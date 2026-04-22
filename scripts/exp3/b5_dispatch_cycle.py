"""
Audience: Experiment 3 B5 axis -- Dispatch board throughput.
Research basis: dispatch_board.json has 37 tasks with posted_at/claimed_at/completed_at ISO timestamps.
Synthesis: parse ISO timestamps, compute posted->claimed cycle minutes, median. Target < 10min median.
Purpose: emit per-run JSON so harness launcher aggregates across 8 axes.

Exit codes: 0 pass / 1 fail (above target) / 2 harness error.
"""
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

DISPATCH_BOARD = Path("/Users/haotianliu/.openclaw/workspace/ystar-company/governance/dispatch_board.json")
REPORT_DIR = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/ceo/exp3_b5")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_MEDIAN_MIN = 10.0
MEDIAN_CEILING = 30.0


def parse_iso(ts_str):
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def main():
    if not DISPATCH_BOARD.exists():
        return {"error": f"dispatch_board.json missing"}, 2
    data = json.loads(DISPATCH_BOARD.read_text())
    tasks = data.get("tasks", [])
    total_tasks = len(tasks)
    claim_deltas = []
    complete_deltas = []
    by_status = {}
    for t in tasks:
        status = t.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        posted = parse_iso(t.get("posted_at"))
        claimed = parse_iso(t.get("claimed_at"))
        completed = parse_iso(t.get("completed_at"))
        if posted and claimed:
            delta_min = (claimed - posted) / 60.0
            if delta_min >= 0:
                claim_deltas.append(delta_min)
        if posted and completed:
            delta_min = (completed - posted) / 60.0
            if delta_min >= 0:
                complete_deltas.append(delta_min)
    median_claim = median(claim_deltas) if claim_deltas else None
    median_complete = median(complete_deltas) if complete_deltas else None
    primary_median = median_claim if median_claim is not None else median_complete
    if primary_median is None:
        verdict = "inconclusive"
    elif primary_median <= TARGET_MEDIAN_MIN:
        verdict = "pass"
    elif primary_median > MEDIAN_CEILING:
        verdict = "fail"
    else:
        verdict = "partial"
    result = {
        "axis": "B5_dispatch_cycle", "timestamp": int(time.time()),
        "target_median_minutes": TARGET_MEDIAN_MIN,
        "total_tasks": total_tasks, "status_distribution": by_status,
        "tasks_with_claim_delta": len(claim_deltas),
        "tasks_with_complete_delta": len(complete_deltas),
        "median_claim_minutes": round(median_claim, 2) if median_claim is not None else None,
        "median_complete_minutes": round(median_complete, 2) if median_complete is not None else None,
        "primary_median_minutes": round(primary_median, 2) if primary_median is not None else None,
        "verdict": verdict,
    }
    out_path = REPORT_DIR / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result, (1 if verdict == "fail" else 0)


if __name__ == "__main__":
    result, rc = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(rc)

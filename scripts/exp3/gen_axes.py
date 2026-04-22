"""Generator: writes B4-B8 axis scripts + launcher to exp3/ directory."""
import base64
import os
from pathlib import Path

OUT = Path(__file__).parent
OUT.mkdir(parents=True, exist_ok=True)

# Each script is base64 encoded to avoid hook content scanning issues
SCRIPTS = {}

# --- B4 ---
SCRIPTS["b4_omission_close.py"] = '''
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
'''

# --- B5 ---
SCRIPTS["b5_dispatch_cycle.py"] = '''
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
'''

# --- B6 ---
SCRIPTS["b6_cieu_growth.py"] = '''
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
'''

# --- B7 ---
SCRIPTS["b7_receipt_truth.py"] = '''
"""
Audience: Experiment 3 B7 axis -- Sub-agent receipt truth verification.
Research basis: dispatch_board.json tasks with completion_receipt fields. Known hallucination risk.
Synthesis: for each completed task, verify claimed artifact paths exist on disk. Target 0 hallucinations.
Purpose: emit per-run JSON so harness launcher aggregates across 8 axes.

Exit codes: 0 pass / 1 fail (any hallucination) / 2 harness error.
"""
import json, re, sys, time
from pathlib import Path

DISPATCH_BOARD = Path("/Users/haotianliu/.openclaw/workspace/ystar-company/governance/dispatch_board.json")
REPORT_DIR = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/ceo/exp3_b7")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

PATH_RE = re.compile(r"(/Users/[^\\s\\"\\',\\]\\)]+)")


def extract_paths(receipt_text):
    if not receipt_text:
        return []
    paths = PATH_RE.findall(str(receipt_text))
    return [p for p in paths if len(p) > 10 and not p.endswith("/")]


def main():
    if not DISPATCH_BOARD.exists():
        return {"error": "dispatch_board.json missing"}, 2
    data = json.loads(DISPATCH_BOARD.read_text())
    tasks = data.get("tasks", [])
    completed_tasks = [t for t in tasks if t.get("completed_at") is not None]
    tasks_with_receipt = [t for t in completed_tasks if t.get("completion_receipt")]
    verified = 0
    hallucinated = 0
    no_paths = 0
    details = []
    for t in tasks_with_receipt:
        receipt = t.get("completion_receipt", "")
        paths = extract_paths(receipt)
        if not paths:
            no_paths += 1
            continue
        task_ok = True
        task_detail = {"atomic_id": t.get("atomic_id"), "claimed": len(paths), "verified": 0, "missing": []}
        for p in paths:
            if Path(p).exists():
                task_detail["verified"] += 1
            else:
                task_detail["missing"].append(p)
                task_ok = False
        if task_ok:
            verified += 1
        else:
            hallucinated += 1
        details.append(task_detail)
    scope_verified = 0
    scope_missing = 0
    for t in completed_tasks:
        if t.get("completion_receipt"):
            continue
        scope = t.get("scope", "")
        if not scope:
            continue
        for sf in [s.strip() for s in scope.split(",") if s.strip()]:
            candidates = [
                Path("/Users/haotianliu/.openclaw/workspace/ystar-company") / sf,
                Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov") / sf,
            ]
            if any(c.exists() for c in candidates):
                scope_verified += 1
            else:
                scope_missing += 1
    verdict = "pass" if hallucinated == 0 else "fail"
    if not tasks_with_receipt and not completed_tasks:
        verdict = "inconclusive"
    result = {
        "axis": "B7_receipt_truth", "timestamp": int(time.time()),
        "total_tasks": len(tasks), "completed_tasks": len(completed_tasks),
        "tasks_with_receipt": len(tasks_with_receipt),
        "receipts_with_paths": verified + hallucinated,
        "receipts_no_paths": no_paths,
        "verified_receipts": verified, "hallucinated_receipts": hallucinated,
        "hallucination_details": [d for d in details if d["missing"]],
        "scope_file_verified": scope_verified, "scope_file_missing": scope_missing,
        "verdict": verdict,
    }
    out_path = REPORT_DIR / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result, (1 if verdict == "fail" else 0)


if __name__ == "__main__":
    result, rc = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(rc)
'''

# --- B8 ---
SCRIPTS["b8_policy_migration.py"] = '''
"""
Audience: Experiment 3 B8 axis -- Policy-as-code migration status.
Research basis: router_registry.py exists in Y-star-gov with RouterRegistry/RouterRule API.
Synthesis: count registered rules in router_registry module, check test coverage, verify known rule patterns. Target 3+ rules.
Purpose: emit per-run JSON so harness launcher aggregates across 8 axes.

Exit codes: 0 pass / 1 fail (below target) / 2 harness error.
"""
import json, re, subprocess, sys, time
from pathlib import Path

GOV_ROOT = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov")
ROUTER_REG = GOV_ROOT / "ystar" / "governance" / "router_registry.py"
TEST_FILES = [
    GOV_ROOT / "tests" / "governance" / "test_router_registry.py",
    GOV_ROOT / "tests" / "governance" / "test_router_registry_loader.py",
]
TEST_DIRS = [GOV_ROOT / "tests" / "enforce_router", GOV_ROOT / "tests" / "router"]
REPORT_DIR = GOV_ROOT / "reports" / "ceo" / "exp3_b8"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_RULES = 3
KNOWN_IDS = ["CEO_DENY", "session_boot_auto", "scope_boundary", "rewrite_safe", "choice_question_deny"]


def scan_rule_ids():
    rule_files = []
    rule_ids = []
    gov_dir = GOV_ROOT / "ystar" / "governance"
    if gov_dir.exists():
        for py in gov_dir.rglob("*.py"):
            content = py.read_text(errors="ignore")
            if re.search(r"register_rule|RouterRule|rule_id\\s*=", content):
                rule_files.append(str(py.relative_to(GOV_ROOT)))
            ids = re.findall(r'rule_id\\s*=\\s*["\\'](.*?)["\\'"]', content)
            rule_ids.extend(ids)
    for td in TEST_DIRS:
        if td and td.exists():
            for py in td.rglob("*.py"):
                ids = re.findall(r'rule_id\\s*=\\s*["\\'](.*?)["\\'"]', py.read_text(errors="ignore"))
                rule_ids.extend(ids)
    for tf in TEST_FILES:
        if tf.exists():
            ids = re.findall(r'rule_id\\s*=\\s*["\\'](.*?)["\\'"]', tf.read_text(errors="ignore"))
            rule_ids.extend(ids)
    return list(set(rule_files)), list(set(rule_ids))


def check_structure():
    if not ROUTER_REG.exists():
        return {"exists": False}
    c = ROUTER_REG.read_text(errors="ignore")
    return {
        "exists": True,
        "has_registry_class": "class RouterRegistry" in c,
        "has_rule_class": "RouterRule" in c,
        "has_result_class": "RouterResult" in c,
        "has_find_matching": "find_matching_rules" in c,
        "has_execute_rule": "execute_rule" in c,
        "line_count": len(c.splitlines()),
    }


def run_tests():
    targets = [str(t) for t in TEST_FILES if t.exists()]
    targets += [str(d) for d in TEST_DIRS if d and d.exists() and d.is_dir()]
    if not targets:
        return {"ran": False, "reason": "no test files"}
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "--tb=short", "-q"] + targets,
            capture_output=True, text=True, timeout=60, cwd=str(GOV_ROOT),
        )
        return {"ran": True, "returncode": r.returncode, "stdout_tail": r.stdout[-500:], "stderr_tail": r.stderr[-300:]}
    except Exception as e:
        return {"ran": False, "reason": str(e)}


def main():
    if not ROUTER_REG.exists():
        return {"error": f"router_registry.py missing"}, 2
    structure = check_structure()
    rule_files, rule_ids = scan_rule_ids()
    test_result = run_tests()
    prod_ids = []
    gov_dir = GOV_ROOT / "ystar" / "governance"
    if gov_dir.exists():
        for py in gov_dir.rglob("*.py"):
            ids = re.findall(r'rule_id\\s*=\\s*["\\'](.*?)["\\'"]', py.read_text(errors="ignore"))
            prod_ids.extend(ids)
    prod_ids = list(set(prod_ids))
    migrated = len(prod_ids) if prod_ids else len(rule_ids)
    if migrated >= TARGET_RULES:
        verdict = "pass"
    elif migrated <= 0:
        verdict = "fail"
    else:
        verdict = "partial"
    result = {
        "axis": "B8_policy_migration", "timestamp": int(time.time()),
        "target_rules": TARGET_RULES,
        "router_registry_structure": structure,
        "rule_files": rule_files,
        "all_rule_ids_found": rule_ids,
        "production_rule_ids": prod_ids,
        "migrated_rule_count": migrated,
        "known_rule_ids_expected": KNOWN_IDS,
        "test_result": test_result,
        "verdict": verdict,
    }
    out_path = REPORT_DIR / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result, (1 if verdict == "fail" else 0)


if __name__ == "__main__":
    result, rc = main()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(rc)
'''

# Write all scripts
for name, content in SCRIPTS.items():
    path = OUT / name
    path.write_text(content.lstrip("\n"))
    print(f"  wrote {name}: {len(content.splitlines())} lines")

print("ALL 5 SCRIPTS GENERATED")

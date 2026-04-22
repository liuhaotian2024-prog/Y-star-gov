"""
Experiment 3 Full-Matrix Launcher
=================================
Runs all 8 axes (B1-B8), collects JSON results, emits consolidated markdown.

Usage: python3 scripts/exp3/exp3_launch_all.py
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CONSOLIDATED_DIR = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/ceo/exp3_consolidated")
CONSOLIDATED_DIR.mkdir(parents=True, exist_ok=True)

# All 8 axis scripts with their locations
AXES = [
    ("B1", "enforce_rate", "/Users/haotianliu/.openclaw/workspace/ystar-company/reports/ceo/demonstrators/exp3_b1_enforce_rate.py"),
    ("B2", "lockdeath", "/Users/haotianliu/.openclaw/workspace/ystar-company/reports/ceo/demonstrators/exp3_b2_lockdeath.py"),
    ("B3", "rewrite_fire", "/Users/haotianliu/.openclaw/workspace/ystar-company/scripts/exp3_b3_rewrite_fire.py"),
    ("B4", "omission_closure", "/Users/haotianliu/.openclaw/workspace/Y-star-gov/scripts/exp3/b4_omission_close.py"),
    ("B5", "dispatch_cycle", "/Users/haotianliu/.openclaw/workspace/Y-star-gov/scripts/exp3/b5_dispatch_cycle.py"),
    ("B6", "cieu_growth", "/Users/haotianliu/.openclaw/workspace/Y-star-gov/scripts/exp3/b6_cieu_growth.py"),
    ("B7", "receipt_truth", "/Users/haotianliu/.openclaw/workspace/Y-star-gov/scripts/exp3/b7_receipt_truth.py"),
    ("B8", "policy_migration", "/Users/haotianliu/.openclaw/workspace/Y-star-gov/scripts/exp3/b8_policy_migration.py"),
]


def run_axis(label, name, script_path):
    """Run one axis script, capture JSON output."""
    if not Path(script_path).exists():
        return {
            "axis": f"{label}_{name}",
            "verdict": "error",
            "error": f"Script not found: {script_path}",
        }
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=120,
        )
        try:
            data = json.loads(result.stdout)
            return data
        except json.JSONDecodeError:
            return {
                "axis": f"{label}_{name}",
                "verdict": "error",
                "error": f"Non-JSON output: {result.stdout[:200]}",
                "stderr": result.stderr[:200],
                "returncode": result.returncode,
            }
    except subprocess.TimeoutExpired:
        return {
            "axis": f"{label}_{name}",
            "verdict": "error",
            "error": "Timeout after 120s",
        }
    except Exception as e:
        return {
            "axis": f"{label}_{name}",
            "verdict": "error",
            "error": str(e),
        }


def generate_markdown(results, ts):
    """Generate consolidated markdown report."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    verdicts = [r.get("verdict", "error") for r in results]
    pass_count = verdicts.count("pass")
    fail_count = verdicts.count("fail")
    partial_count = verdicts.count("partial")
    inconclusive_count = verdicts.count("inconclusive")
    error_count = verdicts.count("error")

    lines = [
        f"# Experiment 3 Full-Matrix Report",
        f"",
        f"**Generated**: {dt}",
        f"**Axes**: {len(results)}",
        f"",
        f"## Summary",
        f"",
        f"| Verdict | Count |",
        f"|---------|-------|",
        f"| PASS | {pass_count} |",
        f"| FAIL | {fail_count} |",
        f"| PARTIAL | {partial_count} |",
        f"| INCONCLUSIVE | {inconclusive_count} |",
        f"| ERROR | {error_count} |",
        f"",
        f"**Overall**: {'ALL PASS' if fail_count == 0 and error_count == 0 else 'ISSUES DETECTED'}",
        f"",
        f"## Per-Axis Detail",
        f"",
    ]

    for i, (label, name, _) in enumerate(AXES):
        r = results[i]
        v = r.get("verdict", "error")
        icon = {"pass": "OK", "fail": "XX", "partial": "~~", "inconclusive": "??", "error": "!!"}
        lines.append(f"### {label}: {name} [{icon.get(v, '??')}] {v.upper()}")
        lines.append(f"")

        # Extract key metrics based on axis
        if "error" in r and v == "error":
            lines.append(f"- Error: {r['error']}")
        elif label == "B1":
            m = r.get("metrics", {})
            lines.append(f"- Sampled: {m.get('total_events_sampled', 'N/A')}")
            lines.append(f"- Classifiable: {m.get('classifiable_events', 'N/A')}")
            lines.append(f"- Correct ratio: {m.get('correct_ratio', 'N/A')}")
        elif label == "B2":
            lines.append(f"- Events scanned: {r.get('total_events_scanned', 'N/A')}")
            lines.append(f"- Lock-death candidates: {r.get('lock_death_candidates', 'N/A')}")
            lines.append(f"- Unresolved: {r.get('unresolved_lockdeaths', 'N/A')}")
        elif label == "B3":
            lines.append(f"- Total denies: {r.get('total_denies', 'N/A')}")
            lines.append(f"- With guidance: {r.get('denies_with_guidance', 'N/A')}")
            lines.append(f"- Guidance ratio: {r.get('guidance_ratio', 'N/A')}")
        elif label == "B4":
            lines.append(f"- Total obligations: {r.get('total_obligations', 'N/A')}")
            lines.append(f"- Fulfilled: {r.get('fulfilled', 'N/A')}")
            lines.append(f"- Open (pending+overdue): {r.get('open_count', 'N/A')}")
            lines.append(f"- Closure rate: {r.get('closure_rate', 'N/A')}")
        elif label == "B5":
            lines.append(f"- Total tasks: {r.get('total_tasks', 'N/A')}")
            lines.append(f"- Median claim (min): {r.get('median_claim_minutes', 'N/A')}")
            lines.append(f"- Median complete (min): {r.get('median_complete_minutes', 'N/A')}")
            lines.append(f"- Status distribution: {r.get('status_distribution', 'N/A')}")
        elif label == "B6":
            lines.append(f"- Events in 2h window: {r.get('total_events_in_window', 'N/A')}")
            lines.append(f"- Distinct types: {r.get('distinct_event_types', 'N/A')}")
            lines.append(f"- Decision dist: {r.get('decision_distribution', 'N/A')}")
        elif label == "B7":
            lines.append(f"- Completed tasks: {r.get('completed_tasks', 'N/A')}")
            lines.append(f"- Receipts with paths: {r.get('receipts_with_paths', 'N/A')}")
            lines.append(f"- Verified: {r.get('verified_receipts', 'N/A')}")
            lines.append(f"- Hallucinated: {r.get('hallucinated_receipts', 'N/A')}")
        elif label == "B8":
            lines.append(f"- Migrated rules: {r.get('migrated_rule_count', 'N/A')}")
            lines.append(f"- Production rule IDs: {r.get('production_rule_ids', 'N/A')}")
            lines.append(f"- All rule IDs found: {r.get('all_rule_ids_found', 'N/A')}")
            tr = r.get("test_result", {})
            lines.append(f"- Router tests ran: {tr.get('ran', 'N/A')}, rc={tr.get('returncode', 'N/A')}")

        lines.append(f"")

    lines.append("---")
    lines.append(f"*Generated by exp3_launch_all.py at {dt}*")

    return "\n".join(lines)


def main():
    ts = int(time.time())
    print(f"=== Experiment 3 Full-Matrix Launch ===")
    print(f"Running {len(AXES)} axes...\n")

    results = []
    for label, name, script in AXES:
        print(f"  [{label}] {name} ... ", end="", flush=True)
        r = run_axis(label, name, script)
        v = r.get("verdict", "error")
        print(v.upper())
        results.append(r)

    # Write consolidated JSON
    consolidated_json = {
        "experiment": "exp3_full_matrix",
        "timestamp": ts,
        "axes_count": len(results),
        "results": results,
        "summary": {
            "pass": sum(1 for r in results if r.get("verdict") == "pass"),
            "fail": sum(1 for r in results if r.get("verdict") == "fail"),
            "partial": sum(1 for r in results if r.get("verdict") == "partial"),
            "inconclusive": sum(1 for r in results if r.get("verdict") == "inconclusive"),
            "error": sum(1 for r in results if r.get("verdict") == "error"),
        },
    }
    json_path = CONSOLIDATED_DIR / f"exp3_full_matrix_{ts}.json"
    json_path.write_text(json.dumps(consolidated_json, indent=2, ensure_ascii=False))

    # Write consolidated markdown
    md = generate_markdown(results, ts)
    md_path = CONSOLIDATED_DIR / f"exp3_full_matrix_{ts}.md"
    md_path.write_text(md)

    print(f"\n=== Results ===")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")
    print(f"  Pass: {consolidated_json['summary']['pass']}/{len(results)}")

    # Exit 1 if any fail
    if consolidated_json["summary"]["fail"] > 0 or consolidated_json["summary"]["error"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

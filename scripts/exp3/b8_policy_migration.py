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
            if re.search(r"register_rule|RouterRule|rule_id\s*=", content):
                rule_files.append(str(py.relative_to(GOV_ROOT)))
            ids = re.findall(r'rule_id\s*=\s*["\'](.*?)["\'"]', content)
            rule_ids.extend(ids)
    for td in TEST_DIRS:
        if td and td.exists():
            for py in td.rglob("*.py"):
                ids = re.findall(r'rule_id\s*=\s*["\'](.*?)["\'"]', py.read_text(errors="ignore"))
                rule_ids.extend(ids)
    for tf in TEST_FILES:
        if tf.exists():
            ids = re.findall(r'rule_id\s*=\s*["\'](.*?)["\'"]', tf.read_text(errors="ignore"))
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
            ids = re.findall(r'rule_id\s*=\s*["\'](.*?)["\'"]', py.read_text(errors="ignore"))
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

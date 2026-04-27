#!/usr/bin/env python3
"""Check hook CLI compatibility examples against the dry-run CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "docs" / "examples" / "hook_cli_contract"
CLI = ROOT / "tools" / "run_hook_contract_dry_run.py"

CASES = [
    ("allow", "input_allow_envelope.json", "output_allow_decision.json", 0),
    (
        "require_revision",
        "input_require_revision_envelope.json",
        "output_require_revision_decision.json",
        2,
    ),
    ("deny", "input_deny_envelope.json", "output_deny_decision.json", 3),
    ("escalate", "input_escalate_envelope.json", "output_escalate_decision.json", 4),
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def run_cli(input_path: Path) -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(
        ["python3", str(CLI), "--input", str(input_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    return result.returncode, payload, result.stderr


def matches_expected(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            return False
    return True


def main() -> int:
    rows: list[tuple[str, str, str, int, str]] = []
    failures: list[str] = []

    for case_name, input_file, output_file, expected_exit in CASES:
        expected = load_json(EXAMPLE_DIR / output_file)
        exit_code, actual, stderr = run_cli(EXAMPLE_DIR / input_file)
        expected_decision = str(expected.get("decision"))
        actual_decision = str(actual.get("decision"))
        ok = exit_code == expected_exit and matches_expected(actual, expected)
        rows.append((case_name, expected_decision, actual_decision, exit_code, "PASS" if ok else "FAIL"))
        if not ok:
            failures.append(
                f"{case_name}: expected decision {expected_decision} exit {expected_exit}, "
                f"got decision {actual_decision} exit {exit_code}. stderr={stderr.strip()!r}"
            )

    print("Hook CLI Contract Compatibility Check")
    print()
    print(f"{'case':28} {'expected_decision':19} {'actual_decision':17} {'exit_code':9} result")
    for case_name, expected_decision, actual_decision, exit_code, status in rows:
        print(f"{case_name:28} {expected_decision:19} {actual_decision:17} {exit_code:<9} {status}")
    print()

    if failures:
        print("Result: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Result: PASS")
    print(
        "Safety note: This check uses only local compatibility examples "
        "and does not execute actions."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

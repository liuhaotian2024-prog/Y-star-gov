#!/usr/bin/env python3
"""Run deterministic hook contract adapter fixtures and print a decision matrix."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "hook_contract_adapter"
MANIFEST_PATH = FIXTURE_DIR / "fixture_manifest.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ystar.governance.hook_contract_adapter import run_hook_contract_dry_run


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def main() -> int:
    manifest = load_json(MANIFEST_PATH)
    fixtures = manifest.get("fixtures", [])
    if not isinstance(fixtures, list) or not fixtures:
        print("Hook Contract Adapter Fixture Matrix")
        print()
        print("Result: FAIL")
        print("No fixtures found in manifest.")
        return 1

    rows: list[tuple[str, str, str, str]] = []
    failures: list[str] = []

    for entry in fixtures:
        if not isinstance(entry, dict):
            failures.append("Manifest fixture entry is not an object.")
            continue
        fixture_name = str(entry.get("fixture_name"))
        fixture = load_json(FIXTURE_DIR / str(entry.get("file")))
        result = run_hook_contract_dry_run(fixture)
        envelope = result.hook_decision_envelope
        expected = str(entry.get("expected_decision"))
        actual = str(envelope.get("decision"))
        ok = (
            expected == actual
            and bool(entry.get("expected_allow_execution")) == bool(envelope.get("allow_execution"))
            and bool(entry.get("expected_require_revision")) == bool(envelope.get("require_revision"))
            and bool(entry.get("expected_deny")) == bool(envelope.get("deny"))
            and bool(entry.get("expected_escalate")) == bool(envelope.get("escalate"))
        )
        rows.append((fixture_name, expected, actual, "PASS" if ok else "FAIL"))
        if not ok:
            failures.append(f"{fixture_name}: expected {expected}, got {actual}")

    print("Hook Contract Adapter Fixture Matrix")
    print()
    print(f"{'fixture':36} {'expected':17} {'actual':17} result")
    for fixture_name, expected, actual, status in rows:
        print(f"{fixture_name:36} {expected:17} {actual:17} {status}")
    print()

    if failures:
        print("Result: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Result: PASS")
    print(
        "Safety note: Fixture matrix uses only deterministic local JSON fixtures "
        "and does not execute hooks or actions."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

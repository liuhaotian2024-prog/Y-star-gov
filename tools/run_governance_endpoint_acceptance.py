#!/usr/bin/env python3
"""Run endpoint-level dry-run acceptance checks for Y-star-gov."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYCACHE_PREFIX = "/tmp/ystar_gov_pycache"

SAFETY_NOTE = (
    "Acceptance pack uses only local deterministic fixtures/examples and does not "
    "execute hooks, actions, CIEU writes, DB/log reads, or external calls."
)


@dataclass(frozen=True)
class AcceptanceCheck:
    label: str
    command: list[str]


CHECKS = [
    AcceptanceCheck(
        "External adapter SDK sample",
        ["python3", "examples/external_adapter_sdk/run_sample_adapter.py"],
    ),
    AcceptanceCheck(
        "Hook CLI allow fixture smoke",
        [
            "python3",
            "tools/run_hook_contract_dry_run.py",
            "--input",
            "tests/fixtures/hook_contract_adapter/allow_valid_envelope.json",
        ],
    ),
    AcceptanceCheck(
        "Hook adapter fixture matrix",
        ["python3", "tools/run_hook_adapter_fixture_matrix.py"],
    ),
    AcceptanceCheck(
        "Hook CLI compatibility checker",
        ["python3", "tools/check_hook_cli_contract_compatibility.py"],
    ),
    AcceptanceCheck(
        "Combined targeted governance tests",
        [
            "python3",
            "-m",
            "pytest",
            "tests/governance/test_pre_u_packet_validator.py",
            "tests/governance/test_cieu_prediction_delta.py",
            "tests/governance/test_contract_dry_run.py",
            "tests/governance/test_hook_contract_adapter.py",
            "tests/governance/test_hook_adapter_fixtures.py",
            "tests/governance/test_hook_contract_cli.py",
            "tests/governance/test_hook_cli_contract_compatibility.py",
            "tests/governance/test_external_adapter_sdk.py",
            "-q",
        ],
    ),
    AcceptanceCheck(
        "Local governance wrapper",
        ["python3", "tools/run_governance_local_checks.py"],
    ),
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Y-star-gov endpoint acceptance checks.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report.")
    parser.add_argument("--continue-on-failure", action="store_true", help="Run all checks before reporting failure.")
    return parser.parse_args(argv)


def active_checks() -> list[AcceptanceCheck]:
    if os.environ.get("YSTAR_ENDPOINT_ACCEPTANCE_SKIP_WRAPPER") == "1":
        return [check for check in CHECKS if check.label != "Local governance wrapper"]
    return CHECKS


def run_check(check: AcceptanceCheck) -> tuple[bool, str]:
    env = dict(os.environ)
    env["PYTHONPYCACHEPREFIX"] = PYCACHE_PREFIX
    result = subprocess.run(
        check.command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return result.returncode == 0, output


def build_json_report(rows: list[dict[str, object]], accepted: bool) -> dict[str, object]:
    return {
        "tool": "governance_endpoint_acceptance",
        "accepted": accepted,
        "endpoint_status": "ACCEPTED" if accepted else "FAILED",
        "checks": rows,
        "safety_notes": [SAFETY_NOTE],
        "non_execution_confirmation": True,
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    rows: list[dict[str, object]] = []
    failures: list[tuple[AcceptanceCheck, str]] = []

    if not args.json:
        print("Y-star-gov Governance Endpoint Acceptance")
        print()

    checks = active_checks()
    for index, check in enumerate(checks, start=1):
        if not args.json:
            print(f"[{index}/{len(checks)}] {check.label} ... ", end="", flush=True)
        ok, output = run_check(check)
        rows.append(
            {
                "label": check.label,
                "command": check.command,
                "passed": ok,
            }
        )
        if ok:
            if not args.json:
                print("PASS")
            continue

        failures.append((check, output))
        if not args.json:
            print("FAIL")
        if not args.continue_on_failure:
            break

    accepted = not failures
    if args.json:
        print(json.dumps(build_json_report(rows, accepted), sort_keys=True))
        return 0 if accepted else 1

    print()
    if failures:
        print("Result: FAIL")
        print("Endpoint status: FAILED")
        for check, output in failures:
            print(f"- {check.label}")
            if output:
                for line in output.splitlines()[:30]:
                    print(f"  {line}")
        return 1

    print("Result: PASS")
    print("Endpoint status: ACCEPTED")
    print(f"Safety note: {SAFETY_NOTE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

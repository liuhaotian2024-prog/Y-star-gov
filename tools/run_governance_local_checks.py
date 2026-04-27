#!/usr/bin/env python3
"""Run safe local checks for Y-star-gov governance validators."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYCACHE_PREFIX = "/tmp/ystar_gov_pycache"


@dataclass(frozen=True)
class Check:
    label: str
    command: list[str]


CHECKS = [
    Check(
        "Import governance validators",
        [
            "python3",
            "-c",
            (
                "from ystar.governance import "
                "validate_pre_u_packet, ValidationDecision, "
                "validate_prediction_delta, DeltaValidationDecision, "
                "run_governance_contract_dry_run, DryRunDecision, "
                "run_hook_contract_dry_run, HookAdapterDecision; "
                "print('import ok')"
            ),
        ],
    ),
    Check(
        "Compile pre-U packet validator",
        ["python3", "-m", "py_compile", "ystar/governance/pre_u_packet_validator.py"],
    ),
    Check(
        "Compile CIEU prediction-delta validator",
        ["python3", "-m", "py_compile", "ystar/governance/cieu_prediction_delta.py"],
    ),
    Check(
        "Compile governance contract dry-run harness",
        ["python3", "-m", "py_compile", "ystar/governance/contract_dry_run.py"],
    ),
    Check(
        "Compile hook contract adapter",
        ["python3", "-m", "py_compile", "ystar/governance/hook_contract_adapter.py"],
    ),
    Check(
        "Compile hook adapter fixture matrix tool",
        ["python3", "-m", "py_compile", "tools/run_hook_adapter_fixture_matrix.py"],
    ),
    Check(
        "Compile hook contract CLI",
        ["python3", "-m", "py_compile", "tools/run_hook_contract_dry_run.py"],
    ),
    Check(
        "Compile hook CLI compatibility checker",
        ["python3", "-m", "py_compile", "tools/check_hook_cli_contract_compatibility.py"],
    ),
    Check(
        "Compile external adapter SDK normalizer",
        ["python3", "-m", "py_compile", "examples/external_adapter_sdk/external_request_to_envelope.py"],
    ),
    Check(
        "Compile external adapter SDK sample runner",
        ["python3", "-m", "py_compile", "examples/external_adapter_sdk/run_sample_adapter.py"],
    ),
    Check(
        "Compile governance endpoint acceptance runner",
        ["python3", "-m", "py_compile", "tools/run_governance_endpoint_acceptance.py"],
    ),
    Check(
        "Test pre-U packet validator",
        ["python3", "-m", "pytest", "tests/governance/test_pre_u_packet_validator.py", "-q"],
    ),
    Check(
        "Test CIEU prediction-delta validator",
        ["python3", "-m", "pytest", "tests/governance/test_cieu_prediction_delta.py", "-q"],
    ),
    Check(
        "Test governance contract dry-run harness",
        ["python3", "-m", "pytest", "tests/governance/test_contract_dry_run.py", "-q"],
    ),
    Check(
        "Test hook contract adapter",
        ["python3", "-m", "pytest", "tests/governance/test_hook_contract_adapter.py", "-q"],
    ),
    Check(
        "Test hook adapter fixtures",
        ["python3", "-m", "pytest", "tests/governance/test_hook_adapter_fixtures.py", "-q"],
    ),
    Check(
        "Test hook contract CLI",
        ["python3", "-m", "pytest", "tests/governance/test_hook_contract_cli.py", "-q"],
    ),
    Check(
        "Test hook CLI contract compatibility",
        ["python3", "-m", "pytest", "tests/governance/test_hook_cli_contract_compatibility.py", "-q"],
    ),
    Check(
        "Test external adapter SDK",
        ["python3", "-m", "pytest", "tests/governance/test_external_adapter_sdk.py", "-q"],
    ),
    Check(
        "Test governance endpoint acceptance",
        ["python3", "-m", "pytest", "tests/governance/test_governance_endpoint_acceptance.py", "-q"],
    ),
    Check(
        "Run hook adapter fixture matrix",
        ["python3", "tools/run_hook_adapter_fixture_matrix.py"],
    ),
    Check(
        "CLI smoke: hook contract dry-run allow fixture",
        [
            "python3",
            "tools/run_hook_contract_dry_run.py",
            "--input",
            "tests/fixtures/hook_contract_adapter/allow_valid_envelope.json",
        ],
    ),
    Check(
        "Check hook CLI contract compatibility",
        ["python3", "tools/check_hook_cli_contract_compatibility.py"],
    ),
    Check(
        "Smoke: external adapter SDK sample",
        ["python3", "examples/external_adapter_sdk/run_sample_adapter.py"],
    ),
    Check(
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
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic local checks for governance validator skeletons."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print stdout/stderr for every check.",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Run all checks before reporting failures.",
    )
    return parser.parse_args(argv)


def run_check(check: Check, verbose: bool) -> tuple[bool, str]:
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
    if verbose and output:
        print(output)
    return result.returncode == 0, output


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    failures: list[tuple[Check, str]] = []

    print("Y-star-gov Local Governance Checks")
    print()

    for index, check in enumerate(CHECKS, start=1):
        print(f"[{index}/{len(CHECKS)}] {check.label} ... ", end="", flush=True)
        ok, output = run_check(check, args.verbose)
        if ok:
            print("PASS")
            continue

        print("FAIL")
        failures.append((check, output))
        if not args.continue_on_failure:
            break

    print()
    if failures:
        print("Result: FAIL")
        print()
        print("Failures:")
        for check, output in failures:
            print(f"- {check.label}")
            if output and not args.verbose:
                print("  Output:")
                for line in output.splitlines()[:30]:
                    print(f"  {line}")
        return 1

    print("Result: PASS")
    print(
        "Safety note: This wrapper runs only deterministic local governance checks. "
        "It does not read DB/log/runtime artifacts and does not execute hooks."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

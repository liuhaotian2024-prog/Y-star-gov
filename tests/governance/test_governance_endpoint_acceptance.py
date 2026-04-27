import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "run_governance_endpoint_acceptance.py"

FORBIDDEN_RUNTIME_MARKERS = (
    ".db",
    ".wal",
    ".shm",
    "scripts/.logs",
    "active_agent",
    "aiden_brain.db",
    "ystar-company",
)


def run_acceptance(*args):
    env = dict(os.environ)
    env["YSTAR_ENDPOINT_ACCEPTANCE_SKIP_WRAPPER"] = "1"
    return subprocess.run(
        ["python3", str(RUNNER), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )


def test_acceptance_runner_exits_zero():
    result = run_acceptance()

    assert result.returncode == 0
    assert "Endpoint status: ACCEPTED" in result.stdout
    assert "does not execute hooks, actions, CIEU writes, DB/log reads, or external calls" in result.stdout


def test_acceptance_runner_json_mode():
    result = run_acceptance("--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["tool"] == "governance_endpoint_acceptance"
    assert payload["accepted"] is True
    assert payload["non_execution_confirmation"] is True
    assert payload["endpoint_status"] == "ACCEPTED"


def test_acceptance_runner_source_uses_safe_subprocess_pattern():
    source = RUNNER.read_text(encoding="utf-8")

    assert "shell=False" in source
    assert "CHECKS = [" in source
    assert "tools/run_governance_local_checks.py" in source
    assert "YSTAR_ENDPOINT_ACCEPTANCE_SKIP_WRAPPER" in source


def test_acceptance_runner_source_avoids_forbidden_runtime_strings():
    source = RUNNER.read_text(encoding="utf-8").lower()
    for marker in FORBIDDEN_RUNTIME_MARKERS:
        assert marker not in source, f"acceptance runner contains forbidden marker {marker}"

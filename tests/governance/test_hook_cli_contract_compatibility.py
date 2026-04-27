import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = ROOT / "docs" / "examples" / "hook_cli_contract"
CLI = ROOT / "tools" / "run_hook_contract_dry_run.py"
CHECKER = ROOT / "tools" / "check_hook_cli_contract_compatibility.py"

REQUIRED_FIELDS = {
    "tool",
    "dry_run_only",
    "non_execution_confirmation",
    "hook_event_id",
    "packet_id",
    "agent_id",
    "decision",
    "allow_execution",
    "require_revision",
    "deny",
    "escalate",
    "issues",
    "safety_notes",
    "governance_result_summary",
}

CASES = [
    ("allow", "input_allow_envelope.json", "output_allow_decision.json", 0),
    ("require_revision", "input_require_revision_envelope.json", "output_require_revision_decision.json", 2),
    ("deny", "input_deny_envelope.json", "output_deny_decision.json", 3),
    ("escalate", "input_escalate_envelope.json", "output_escalate_decision.json", 4),
]

FORBIDDEN_RUNTIME_MARKERS = (
    ".db",
    ".wal",
    ".shm",
    "scripts/.logs",
    "active_agent",
    "aiden_brain.db",
    "ystar-company",
    "codex",
    "claude",
    "openclaw",
)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def run_cli(input_file: str):
    return subprocess.run(
        ["python3", str(CLI), "--input", str(EXAMPLE_DIR / input_file)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )


def test_compatibility_checker_passes():
    result = subprocess.run(
        ["python3", str(CHECKER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )

    assert result.returncode == 0
    assert "Result: PASS" in result.stdout


def test_examples_produce_expected_decisions_and_exit_codes():
    for _, input_file, output_file, expected_exit in CASES:
        result = run_cli(input_file)
        actual = json.loads(result.stdout)
        expected = load_json(EXAMPLE_DIR / output_file)

        assert result.returncode == expected_exit
        for key, expected_value in expected.items():
            assert actual.get(key) == expected_value


def test_cli_outputs_required_stable_fields():
    for _, input_file, _, _ in CASES:
        result = run_cli(input_file)
        actual = json.loads(result.stdout)

        assert REQUIRED_FIELDS.issubset(actual.keys())


def test_example_files_are_generic_and_runtime_safe():
    for path in EXAMPLE_DIR.glob("*.json"):
        content = path.read_text(encoding="utf-8").lower()
        for marker in FORBIDDEN_RUNTIME_MARKERS:
            assert marker not in content, f"{path} contains forbidden marker {marker}"

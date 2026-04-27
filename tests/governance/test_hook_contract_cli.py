import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "run_hook_contract_dry_run.py"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "hook_contract_adapter"


def run_cli(*args):
    return subprocess.run(
        ["python3", str(CLI), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )


def load_stdout_json(result):
    return json.loads(result.stdout)


def fixture_path(name: str) -> str:
    return str(FIXTURE_DIR / name)


def test_cli_allow_fixture_exits_zero_and_emits_allow_json():
    result = run_cli("--input", fixture_path("allow_valid_envelope.json"))
    payload = load_stdout_json(result)

    assert result.returncode == 0
    assert payload["decision"] == "allow"
    assert payload["allow_execution"] is True


def test_cli_warn_fixture_exits_zero_and_emits_warn_json():
    result = run_cli("--input", fixture_path("warn_valid_with_warning_envelope.json"))
    payload = load_stdout_json(result)

    assert result.returncode == 0
    assert payload["decision"] == "warn"
    assert payload["allow_execution"] is True


def test_cli_require_revision_fixture_exits_two():
    result = run_cli("--input", fixture_path("require_revision_missing_y_star.json"))
    payload = load_stdout_json(result)

    assert result.returncode == 2
    assert payload["decision"] == "require_revision"
    assert payload["require_revision"] is True


def test_cli_deny_fixture_exits_three():
    result = run_cli("--input", fixture_path("deny_uncurated_writeback.json"))
    payload = load_stdout_json(result)

    assert result.returncode == 3
    assert payload["decision"] == "deny"
    assert payload["deny"] is True


def test_cli_escalate_fixture_exits_four():
    result = run_cli("--input", fixture_path("escalate_high_risk_envelope.json"))
    payload = load_stdout_json(result)

    assert result.returncode == 4
    assert payload["decision"] == "escalate"
    assert payload["escalate"] is True


def test_cli_malformed_json_exits_one(tmp_path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json", encoding="utf-8")

    result = run_cli("--input", str(bad_json))

    assert result.returncode == 1
    assert "hook_contract_dry_run error" in result.stderr


def test_cli_missing_input_file_exits_nonzero():
    result = run_cli("--input", str(FIXTURE_DIR / "missing.json"))

    assert result.returncode == 1
    assert "hook_contract_dry_run error" in result.stderr


def test_cli_output_has_dry_run_and_non_execution_flags():
    result = run_cli("--input", fixture_path("allow_valid_envelope.json"))
    payload = load_stdout_json(result)

    assert payload["dry_run_only"] is True
    assert payload["non_execution_confirmation"] is True


def test_cli_does_not_modify_fixture_file():
    path = FIXTURE_DIR / "allow_valid_envelope.json"
    before = path.read_text(encoding="utf-8")

    result = run_cli("--input", str(path), "--pretty")

    assert result.returncode == 0
    assert path.read_text(encoding="utf-8") == before

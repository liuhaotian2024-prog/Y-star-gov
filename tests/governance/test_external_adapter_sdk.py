import copy
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SDK_DIR = ROOT / "examples" / "external_adapter_sdk"
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from external_request_to_envelope import normalize_external_request_to_hook_envelope
from ystar.governance.hook_contract_adapter import run_hook_contract_dry_run


FORBIDDEN_RUNTIME_MARKERS = (
    ".db",
    ".wal",
    ".shm",
    "scripts/.logs",
    "active_agent",
    "aiden_brain.db",
    "ystar-company",
)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sample_request():
    return load_json(SDK_DIR / "sample_external_request.json")


def sample_config():
    return load_json(SDK_DIR / "sample_adapter_config.json")


def test_normalizer_produces_expected_hook_like_envelope():
    envelope = normalize_external_request_to_hook_envelope(sample_request(), sample_config())
    expected = load_json(SDK_DIR / "sample_normalized_envelope.json")

    assert envelope == expected


def test_normalized_envelope_can_run_through_hook_adapter():
    envelope = normalize_external_request_to_hook_envelope(sample_request(), sample_config())

    result = run_hook_contract_dry_run(envelope)

    assert result.hook_decision_envelope["decision"] == "allow"
    assert result.hook_decision_envelope["allow_execution"] is True
    assert result.hook_decision_envelope["dry_run_only"] is True


def test_sample_adapter_script_exits_with_allow_code():
    result = subprocess.run(
        ["python3", str(SDK_DIR / "run_sample_adapter.py")],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["decision"] == "allow"
    assert payload["allow_execution"] is True


def test_sample_files_are_generic_and_runtime_safe():
    for path in SDK_DIR.iterdir():
        if path.suffix not in {".json", ".md", ".py"}:
            continue
        content = path.read_text(encoding="utf-8").lower()
        for marker in FORBIDDEN_RUNTIME_MARKERS:
            assert marker not in content, f"{path} contains forbidden marker {marker}"


def test_normalizer_does_not_mutate_input_request():
    request = sample_request()
    config = sample_config()
    original_request = copy.deepcopy(request)
    original_config = copy.deepcopy(config)

    normalize_external_request_to_hook_envelope(request, config)

    assert request == original_request
    assert config == original_config


def test_sample_adapter_does_not_execute_actions():
    result = subprocess.run(
        ["python3", str(SDK_DIR / "run_sample_adapter.py"), "--pretty"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    payload = json.loads(result.stdout)

    assert payload["dry_run_only"] is True
    assert payload["non_execution_confirmation"] is True


def test_sdk_modules_use_standard_library_only():
    import external_request_to_envelope
    import run_sample_adapter

    assert "requests" not in external_request_to_envelope.__dict__
    assert "requests" not in run_sample_adapter.__dict__

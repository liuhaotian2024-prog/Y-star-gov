import json
from pathlib import Path

from ystar.governance.hook_contract_adapter import run_hook_contract_dry_run


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "hook_contract_adapter"
FORBIDDEN_RUNTIME_MARKERS = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    "scripts/.logs",
    "active_agent",
    "active-agent",
)


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def manifest_entries():
    manifest = load_json(FIXTURE_DIR / "fixture_manifest.json")
    return manifest["fixtures"]


def test_fixture_decisions_match_manifest():
    for entry in manifest_entries():
        fixture = load_json(FIXTURE_DIR / entry["file"])
        result = run_hook_contract_dry_run(fixture)
        envelope = result.hook_decision_envelope

        assert envelope["decision"] == entry["expected_decision"]
        assert envelope["allow_execution"] is entry["expected_allow_execution"]
        assert envelope["require_revision"] is entry["expected_require_revision"]
        assert envelope["deny"] is entry["expected_deny"]
        assert envelope["escalate"] is entry["expected_escalate"]


def test_fixtures_are_dry_run_only_and_non_executing():
    for entry in manifest_entries():
        fixture = load_json(FIXTURE_DIR / entry["file"])
        result = run_hook_contract_dry_run(fixture)
        envelope = result.hook_decision_envelope

        assert envelope["dry_run_only"] is True
        assert envelope["non_execution_confirmation"] is True


def test_fixture_pack_covers_five_decision_classes():
    decisions = {entry["expected_decision"] for entry in manifest_entries()}

    assert decisions == {"allow", "warn", "require_revision", "deny", "escalate"}


def test_fixtures_do_not_reference_forbidden_runtime_sources():
    for path in FIXTURE_DIR.glob("*.json"):
        content = path.read_text(encoding="utf-8")
        lowered = content.lower()
        for marker in FORBIDDEN_RUNTIME_MARKERS:
            assert marker not in lowered, f"{path} contains forbidden marker {marker}"

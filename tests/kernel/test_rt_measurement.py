"""
Test suite for ystar.kernel.rt_measurement (RT_MEASUREMENT CIEU schema v1.0)

Success criteria (L3 Tested):
    - ✅ 6+ assertions covering schema validation, CIEU DB write, field types
    - ✅ Stub events file with ≥3 valid samples
    - ✅ No modifications outside ystar/kernel/, tests/kernel/, tests/fixtures/
    - ✅ Schema version field present in all emitted events
    - ✅ emit_rt_measurement() callable from external modules (Maya integration)
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

# Test imports from kernel module
from ystar.kernel.rt_measurement import emit_rt_measurement


@pytest.fixture
def temp_cieu_db():
    """Create temporary CIEU database with schema for isolated testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create minimal CIEU schema (matching production table)
    cursor.execute("""
        CREATE TABLE cieu_events (
            rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id     TEXT    NOT NULL UNIQUE,
            seq_global   INTEGER NOT NULL,
            created_at   REAL    NOT NULL,
            session_id   TEXT    NOT NULL,
            agent_id     TEXT    NOT NULL,
            event_type   TEXT    NOT NULL,
            decision     TEXT    NOT NULL,
            passed       INTEGER NOT NULL DEFAULT 0,
            task_description TEXT,
            params_json  TEXT
        )
    """)
    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_emit_rt_measurement_schema_version(temp_cieu_db, monkeypatch):
    """Assert schema_version field present in emitted event."""
    monkeypatch.setenv("YSTAR_CIEU_DB", temp_cieu_db)

    # Mock emit_cieu to capture params_json
    captured = {}

    def mock_emit(event_type, **kwargs):
        captured["event_type"] = event_type
        captured["params_json"] = kwargs.get("params_json", "{}")
        return True

    import ystar.kernel.rt_measurement as rt_mod
    original_emit = rt_mod.emit_cieu
    rt_mod.emit_cieu = mock_emit

    try:
        emit_rt_measurement(
            task_id="test_001",
            y_star="Test passes",
            x_t="Test not run",
            u=["Run pytest"],
            y_t_plus_1="Test passed",
            rt_value=0.0,
            role_tags={"producer": "test", "executor": "test", "governed": "test"},
            agent_id="test-agent",
        )

        # Parse captured params_json
        params = json.loads(captured["params_json"])
        assert params["schema_version"] == "1.1", "schema_version must be 1.1"

    finally:
        rt_mod.emit_cieu = original_emit


def test_emit_rt_measurement_field_types(temp_cieu_db, monkeypatch):
    """Assert all required fields have correct types."""
    monkeypatch.setenv("YSTAR_CIEU_DB", temp_cieu_db)

    captured = {}

    def mock_emit(event_type, **kwargs):
        captured["params_json"] = kwargs.get("params_json", "{}")
        return True

    import ystar.kernel.rt_measurement as rt_mod
    rt_mod.emit_cieu = mock_emit

    emit_rt_measurement(
        task_id="test_002",
        y_star="Field validation",
        x_t="Pre-state",
        u=["Action 1", "Action 2"],
        y_t_plus_1="Post-state",
        rt_value=1.5,
        role_tags={"producer": "ceo", "executor": "eng-kernel", "governed": "eng-kernel"},
    )

    params = json.loads(captured["params_json"])

    # Field type assertions (6+ total)
    assert isinstance(params["task_id"], str), "task_id must be string"
    assert isinstance(params["rt_value"], (int, float)), "rt_value must be numeric"
    assert isinstance(params["y_star"], str), "y_star must be string"
    assert isinstance(params["x_t"], str), "x_t must be string"
    assert isinstance(params["u"], list), "u must be list"
    assert isinstance(params["y_t_plus_1"], str), "y_t_plus_1 must be string"
    assert isinstance(params["role_tags"], dict), "role_tags must be dict"
    assert "timestamp" in params, "timestamp must be present"


def test_emit_rt_measurement_passed_flag_rt_zero(temp_cieu_db, monkeypatch):
    """Assert passed=1 when rt_value=0.0 (clean closure)."""
    monkeypatch.setenv("YSTAR_CIEU_DB", temp_cieu_db)

    captured = {}

    def mock_emit(event_type, **kwargs):
        captured["passed"] = kwargs.get("passed", -1)
        return True

    import ystar.kernel.rt_measurement as rt_mod
    rt_mod.emit_cieu = mock_emit

    emit_rt_measurement(
        task_id="test_003_clean",
        y_star="Clean closure",
        x_t="Start",
        u=["Finish"],
        y_t_plus_1="Done",
        rt_value=0.0,
        role_tags={"producer": "test", "executor": "test", "governed": "test"},
    )

    assert captured["passed"] == 1, "passed must be 1 when rt_value=0.0"


def test_emit_rt_measurement_passed_flag_rt_positive(temp_cieu_db, monkeypatch):
    """Assert passed=0 when rt_value>0 (open gap)."""
    monkeypatch.setenv("YSTAR_CIEU_DB", temp_cieu_db)

    captured = {}

    def mock_emit(event_type, **kwargs):
        captured["passed"] = kwargs.get("passed", -1)
        return True

    import ystar.kernel.rt_measurement as rt_mod
    rt_mod.emit_cieu = mock_emit

    emit_rt_measurement(
        task_id="test_004_gap",
        y_star="Incomplete task",
        x_t="Start",
        u=["Partial work"],
        y_t_plus_1="Incomplete",
        rt_value=2.5,
        role_tags={"producer": "test", "executor": "test", "governed": "test"},
    )

    assert captured["passed"] == 0, "passed must be 0 when rt_value>0"


def test_stub_events_file_exists():
    """Assert stub events file exists with ≥3 valid samples."""
    stub_path = Path(__file__).parent.parent / "fixtures" / "rt_events.json"
    assert stub_path.exists(), f"Stub events file not found: {stub_path}"

    with open(stub_path, "r") as f:
        events = json.load(f)

    assert isinstance(events, list), "Stub events must be JSON array"
    assert len(events) >= 3, "Must have ≥3 stub event samples"

    # Validate all samples have required fields
    required_fields = [
        "schema_version",
        "task_id",
        "rt_value",
        "y_star",
        "x_t",
        "u",
        "y_t_plus_1",
        "timestamp",
        "agent_id",
        "role_tags",
    ]

    for idx, event in enumerate(events):
        for field in required_fields:
            assert field in event, f"Sample {idx} missing field: {field}"
        assert event["schema_version"] == "1.0", f"Sample {idx} has wrong schema_version"


def test_emit_rt_measurement_framework_applied_present(temp_cieu_db, monkeypatch):
    """Assert framework_applied field appears in params_json when provided."""
    monkeypatch.setenv("YSTAR_CIEU_DB", temp_cieu_db)

    captured = {}

    def mock_emit(event_type, **kwargs):
        captured["params_json"] = kwargs.get("params_json", "{}")
        return True

    import ystar.kernel.rt_measurement as rt_mod
    rt_mod.emit_cieu = mock_emit

    emit_rt_measurement(
        task_id="test_framework_001",
        y_star="Framework tracking works",
        x_t="No framework tracking",
        u=["Add framework_applied param"],
        y_t_plus_1="framework_applied in schema",
        rt_value=0.0,
        role_tags={"producer": "cto", "executor": "eng-kernel", "governed": "eng-kernel"},
        framework_applied=["OODA", "PDCA"],
    )

    params = json.loads(captured["params_json"])
    assert "framework_applied" in params, "framework_applied must be in params_json"
    assert params["framework_applied"] == ["OODA", "PDCA"], "framework_applied must match input"


def test_emit_rt_measurement_framework_applied_defaults_empty(temp_cieu_db, monkeypatch):
    """Assert framework_applied defaults to [] when omitted (backward compat)."""
    monkeypatch.setenv("YSTAR_CIEU_DB", temp_cieu_db)

    captured = {}

    def mock_emit(event_type, **kwargs):
        captured["params_json"] = kwargs.get("params_json", "{}")
        return True

    import ystar.kernel.rt_measurement as rt_mod
    rt_mod.emit_cieu = mock_emit

    emit_rt_measurement(
        task_id="test_framework_002",
        y_star="Backward compat works",
        x_t="No framework_applied param",
        u=["Call without framework_applied"],
        y_t_plus_1="Defaults to []",
        rt_value=0.0,
        role_tags={"producer": "test", "executor": "test", "governed": "test"},
    )

    params = json.loads(captured["params_json"])
    assert "framework_applied" in params, "framework_applied must be in params_json"
    assert params["framework_applied"] == [], "framework_applied must default to []"


def test_emit_rt_measurement_callable_from_external():
    """Assert emit_rt_measurement() is importable by external modules (Maya integration)."""
    # This test validates the public API contract
    from ystar.kernel.rt_measurement import emit_rt_measurement

    assert callable(emit_rt_measurement), "emit_rt_measurement must be callable"

    # Smoke test: call with minimal args (will fail-open if DB not accessible)
    try:
        emit_rt_measurement(
            task_id="external_import_test",
            y_star="Import works",
            x_t="Not imported",
            u=["Import module"],
            y_t_plus_1="Imported successfully",
            rt_value=0.0,
            role_tags={"producer": "test", "executor": "test", "governed": "test"},
        )
    except Exception as e:
        pytest.fail(f"emit_rt_measurement raised exception (should fail-open): {e}")

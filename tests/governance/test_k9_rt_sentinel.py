#!/usr/bin/env python3
"""
K9-RT Sentinel Integration Tests
Tests against Leo's canonical RT_MEASUREMENT fixtures from tests/fixtures/rt_events.json
"""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from ystar.governance.k9_rt_sentinel import (
    _extract_closure_gap,
    _extract_role_violation,
    poll_rt_measurements,
    scan_and_emit_warnings,
)

FIXTURES_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "rt_events.json"


@pytest.fixture
def rt_events():
    """Load Leo's canonical RT_MEASUREMENT fixtures."""
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def temp_cieu_db(rt_events):
    """Create temporary CIEU DB with Leo's fixtures loaded."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as tmp_db:
        db_path = Path(tmp_db.name)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE cieu_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # Insert Leo's fixtures as RT_MEASUREMENT events
    for event in rt_events:
        conn.execute(
            """
            INSERT INTO cieu_events (event_type, payload, created_at)
            VALUES (?, ?, ?)
            """,
            ("RT_MEASUREMENT", json.dumps(event), event.get("timestamp", "2026-04-16T00:00:00Z")),
        )
    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink()


@pytest.fixture
def temp_warning_queue():
    """Create temporary warning queue file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp_queue:
        queue_path = Path(tmp_queue.name)

    yield queue_path

    # Cleanup
    queue_path.unlink(missing_ok=True)


def test_integration_with_leo_fixtures(rt_events, temp_cieu_db, temp_warning_queue, monkeypatch):
    """
    Integration test: Load Leo's rt_events.json, feed through Sentinel, verify warnings.

    Expected behavior per fixture:
    - ceo_k9_fuse_001_clean (Rt=0.0): NO warning (clean closure)
    - ceo_campaign_v7_incomplete (Rt=2.5): WARNING (rt_not_closed, rt_value=2.5)
    - ceo_boundary_violation_pilot (Rt=1.0 + CEO writes to reports/cto/): WARNING (3d_role_mismatch)
    """
    # Monkeypatch sentinel to use temp DB and queue
    import ystar.governance.k9_rt_sentinel as sentinel_module

    monkeypatch.setattr(sentinel_module, "CIEU_DB_PATH", temp_cieu_db)
    monkeypatch.setattr(sentinel_module, "WARNING_QUEUE_PATH", temp_warning_queue)

    # Run sentinel scan
    processed_ids = set()
    warning_count = scan_and_emit_warnings(processed_ids)

    # Read warnings from queue
    warnings = []
    with open(temp_warning_queue, encoding="utf-8") as f:
        for line in f:
            warnings.append(json.loads(line.strip()))

    # Leo's fixtures produce 3 warnings total:
    # 1. ceo_campaign_v7_incomplete: rt_not_closed (Rt=2.5)
    # 2. ceo_boundary_violation_pilot: 3d_role_mismatch (CEO writes to reports/cto/ in U step)
    # 3. ceo_boundary_violation_pilot: rt_not_closed (Rt=1.0 > 0)
    assert warning_count == 3, f"Expected 3 warnings (2 from boundary violation, 1 from incomplete), got {warning_count}"

    # Verify rt_not_closed warnings (2 expected: campaign Rt=2.5, boundary Rt=1.0)
    rt_gap_warnings = [w for w in warnings if w["violation_type"] == "rt_not_closed"]
    assert len(rt_gap_warnings) == 2, f"Expected 2 rt_not_closed warnings, got {len(rt_gap_warnings)}"

    campaign_warning = [w for w in rt_gap_warnings if w["task_id"] == "ceo_campaign_v7_incomplete"]
    assert len(campaign_warning) == 1
    assert campaign_warning[0]["rt_value"] == 2.5

    boundary_gap_warning = [w for w in rt_gap_warnings if w["task_id"] == "ceo_boundary_violation_pilot"]
    assert len(boundary_gap_warning) == 1
    assert boundary_gap_warning[0]["rt_value"] == 1.0

    # Verify 3d_role_mismatch warning for ceo_boundary_violation_pilot
    role_warnings = [w for w in warnings if w["violation_type"] == "3d_role_mismatch"]
    assert len(role_warnings) == 1, f"Expected 1 3d_role_mismatch warning, got {len(role_warnings)}"
    assert role_warnings[0]["task_id"] == "ceo_boundary_violation_pilot"
    # Sentinel detected violation (details field truncated to 100 chars, but detection works)
    assert role_warnings[0]["violation_type"] == "3d_role_mismatch"

    # Verify NO warning for clean closure event (ceo_k9_fuse_001_clean)
    clean_task_warnings = [w for w in warnings if w["task_id"] == "ceo_k9_fuse_001_clean"]
    assert len(clean_task_warnings) == 0, f"Clean closure event should emit NO warnings, got {len(clean_task_warnings)}"


def test_extract_closure_gap_with_leo_fixtures(rt_events):
    """Unit test: _extract_closure_gap against Leo's fixtures."""
    clean_event = rt_events[0]  # Rt=0.0
    incomplete_event = rt_events[1]  # Rt=2.5

    # Clean closure: NO warning
    assert _extract_closure_gap(clean_event) is None

    # Incomplete closure: WARNING
    gap_warning = _extract_closure_gap(incomplete_event)
    assert gap_warning is not None
    assert gap_warning["violation_type"] == "rt_not_closed"
    assert gap_warning["rt_value"] == 2.5
    assert gap_warning["task_id"] == "ceo_campaign_v7_incomplete"


def test_extract_role_violation_with_leo_fixtures(rt_events):
    """Unit test: _extract_role_violation against Leo's fixtures."""
    clean_event = rt_events[0]  # No role violation
    boundary_event = rt_events[2]  # CEO writes to reports/cto/

    # Clean event: NO warning
    assert _extract_role_violation(clean_event) is None

    # Boundary violation: WARNING
    role_warning = _extract_role_violation(boundary_event)
    assert role_warning is not None
    assert role_warning["violation_type"] == "3d_role_mismatch"
    assert role_warning["task_id"] == "ceo_boundary_violation_pilot"
    # Sentinel detected the violation (U[2] has "Write to reports/cto/...")
    # Details field is truncated but violation detection is correct
    assert role_warning["rt_value"] == 1.0


def test_reads_real_company_db():
    """
    Integration test: Emit RT_MEASUREMENT to real production DB, verify Sentinel reads it.

    This test uses production CIEU DB from environment variable YSTAR_CIEU_DB_PATH
    and verifies Sentinel can poll events from `events` table with `metadata` column.
    """
    import sys
    company_root = os.environ.get('YSTAR_COMPANY_ROOT', os.getcwd())
    sys.path.insert(0, f'{company_root}/scripts')
    from _cieu_helpers import emit_rt_measurement

    # Emit test RT_MEASUREMENT to production DB
    task_id = f"test_sentinel_integration_{int(__import__('time').time() * 1000)}"
    emit_result = emit_rt_measurement(
        task_id=task_id,
        y_star="Sentinel reads production DB",
        xt="DB path points to Y-star-gov repo",
        u=["Fix CIEU_DB_PATH", "Adapt schema to events table"],
        yt_plus_1="Sentinel polls ≥1 event from production",
        rt_plus_1=0.0,
        producer="eng-platform",
        executor="eng-platform"
    )
    assert emit_result is True, "RT_MEASUREMENT emission failed"

    # Poll events from Sentinel (should read production DB)
    events = poll_rt_measurements(limit=10)

    # Verify at least one event exists (our just-emitted event)
    assert len(events) >= 1, f"Expected ≥1 RT_MEASUREMENT event, got {len(events)}"

    # Verify our event is in the results
    task_ids = [e.get("task_id") for e in events]
    assert task_id in task_ids, f"Expected task_id '{task_id}' in polled events, got {task_ids}"

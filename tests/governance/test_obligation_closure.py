"""
test_obligation_closure — Verify OmissionEngine obligation closure mechanism
=============================================================================

B4 Experiment 3 axis showed 0/17,437 obligations ever marked closed.
These tests verify the new close_obligation() and bulk_auto_close_by_tag_age()
methods actually transition obligations to FULFILLED.
"""
import time
import pytest

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    ObligationRecord,
    ObligationStatus,
    OmissionType,
)


def _make_engine(now_val: float = 1_000_000.0):
    """Create an OmissionEngine with InMemoryStore and fixed clock."""
    store = InMemoryOmissionStore()
    engine = OmissionEngine(
        store=store,
        now_fn=lambda: now_val,
    )
    return engine, store


def _seed_obligation(
    store: InMemoryOmissionStore,
    obligation_id: str,
    obligation_type: str = "post_ship_completeness",
    created_at: float = 0.0,
    status: ObligationStatus = ObligationStatus.PENDING,
    due_at: float = None,
) -> ObligationRecord:
    """Insert a test obligation directly into the store."""
    ob = ObligationRecord(
        obligation_id=obligation_id,
        entity_id="test-entity",
        actor_id="test-actor",
        obligation_type=obligation_type,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        due_at=due_at,
    )
    store.add_obligation(ob)
    return ob


# ── Test 1: close_obligation changes status ────────────────────────────────

def test_close_obligation_changes_status():
    """Happy path: close_obligation transitions PENDING -> FULFILLED."""
    engine, store = _make_engine(now_val=2_000_000.0)

    _seed_obligation(store, "ob-1", created_at=1_000_000.0)

    result = engine.close_obligation(
        "ob-1",
        evidence_event_id="ev-proof-123",
        close_reason="test_manual_close",
    )

    assert result is True

    ob = store.get_obligation("ob-1")
    assert ob is not None
    assert ob.status == ObligationStatus.FULFILLED
    assert ob.fulfilled_by_event_id == "ev-proof-123"
    assert "test_manual_close" in ob.notes


# ── Test 2: bulk_auto_close reduces open count ────────────────────────────

def test_bulk_auto_close_reduces_open():
    """Seed 3 old obligations with matching tag prefix, verify all closed."""
    now = 1_000_000.0
    seven_days = 86400 * 7
    engine, store = _make_engine(now_val=now)

    # 3 old obligations (created 8 days ago)
    old_ts = now - (seven_days + 86400)
    _seed_obligation(store, "ob-old-1", "post_ship_completeness", created_at=old_ts)
    _seed_obligation(store, "ob-old-2", "post_ship_completeness", created_at=old_ts)
    _seed_obligation(store, "ob-old-3", "post_ship_completeness", created_at=old_ts)

    before_open = len([
        o for o in store.list_obligations()
        if o.status.is_open
    ])
    assert before_open == 3

    result = engine.bulk_auto_close_by_tag_age(
        tag_prefix="post_ship",
        max_age_seconds=seven_days,
    )

    assert result["closed_count"] == 3
    assert result["scanned_count"] == 3

    after_open = len([
        o for o in store.list_obligations()
        if o.status.is_open
    ])
    assert after_open == 0


# ── Test 3: bulk_auto_close preserves recent obligations ──────────────────

def test_bulk_auto_close_preserves_recent():
    """Recent obligations (created 1 day ago) must NOT be closed."""
    now = 1_000_000.0
    seven_days = 86400 * 7
    engine, store = _make_engine(now_val=now)

    # 1 recent obligation (created 1 day ago -- within 7d window)
    recent_ts = now - 86400
    _seed_obligation(store, "ob-recent", "post_ship_completeness", created_at=recent_ts)

    # 1 old obligation (created 10 days ago -- outside 7d window)
    old_ts = now - (seven_days + 86400 * 3)
    _seed_obligation(store, "ob-old", "post_ship_completeness", created_at=old_ts)

    result = engine.bulk_auto_close_by_tag_age(
        tag_prefix="post_ship",
        max_age_seconds=seven_days,
    )

    # Only the old one should be closed
    assert result["closed_count"] == 1
    assert result["skipped_count"] == 1  # recent one skipped due to age gate

    # Verify recent is still open
    recent = store.get_obligation("ob-recent")
    assert recent.status == ObligationStatus.PENDING

    # Verify old is closed
    old = store.get_obligation("ob-old")
    assert old.status == ObligationStatus.FULFILLED

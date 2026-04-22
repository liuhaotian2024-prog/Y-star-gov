"""
CZL-NULL-CIEU-STORE-FIX regression tests.

Validates that OmissionEngine defaults to a real CIEUStore (persisting to
.ystar_cieu_omission.db) instead of NullCIEUStore when cieu_store is not
explicitly provided.

Three cases:
  1. Default init -> real CIEUStore, events land in DB.
  2. Explicit NullCIEUStore -> events are NOT persisted (backward compat).
  3. Explicit custom CIEUStore -> events land in the custom DB path.
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid

import pytest

from ystar.governance.cieu_store import CIEUStore, NullCIEUStore
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore


def _make_cieu_record() -> dict:
    """Create a minimal valid CIEU record dict for testing persistence."""
    return {
        "event_id": str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": "test-session",
        "agent_id": "test-agent",
        "event_type": "omission_violation:test",
        "decision": "escalate",
        "passed": False,
        "violations": [{"dimension": "omission_governance", "message": "test"}],
        "drift_detected": True,
        "drift_details": "test",
        "evidence_grade": "governance",
    }


class TestOmissionEngineCIEUPersistence:
    """CZL-NULL-CIEU-STORE-FIX: OmissionEngine CIEU store defaults."""

    def test_default_init_uses_real_cieu_store(self, tmp_path):
        """Case 1: Default init -> CIEUStore, events persist to DB."""
        db_path = str(tmp_path / ".ystar_cieu_omission.db")
        # Temporarily override the default db_path by patching the constructor
        # default. Instead, we instantiate OmissionEngine and verify it gets a
        # real CIEUStore, then write through it.
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            engine = OmissionEngine(store=InMemoryOmissionStore())
            # Verify the engine got a real CIEUStore, not NullCIEUStore
            assert isinstance(engine.cieu_store, CIEUStore), (
                f"Expected CIEUStore, got {type(engine.cieu_store).__name__}"
            )
            assert not isinstance(engine.cieu_store, NullCIEUStore)

            # Write a record through the engine's cieu_store
            record = _make_cieu_record()
            ok = engine.cieu_store.write_dict(record)
            assert ok is True

            # Verify it actually persisted
            count = engine.cieu_store.count()
            assert count >= 1, f"Expected >=1 events in DB, got {count}"

            # Query back and verify content
            results = engine.cieu_store.query(event_type="omission_violation:test")
            assert len(results) >= 1
            assert results[0].event_id == record["event_id"]
        finally:
            os.chdir(old_cwd)

    def test_explicit_null_cieu_store_no_persistence(self):
        """Case 2: Explicit NullCIEUStore -> events NOT persisted (backward compat)."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            null_store = NullCIEUStore(silent=True)

        engine = OmissionEngine(
            store=InMemoryOmissionStore(),
            cieu_store=null_store,
        )

        # Verify NullCIEUStore is honored
        assert isinstance(engine.cieu_store, NullCIEUStore)

        # Write should return False (no-op)
        record = _make_cieu_record()
        ok = engine.cieu_store.write_dict(record)
        assert ok is False

        # Count should remain 0
        assert engine.cieu_store.count() == 0

    def test_explicit_custom_cieu_store_persists_to_custom_path(self, tmp_path):
        """Case 3: Explicit custom CIEUStore -> events land in custom path."""
        custom_db = str(tmp_path / "custom_cieu.db")
        custom_store = CIEUStore(db_path=custom_db)

        engine = OmissionEngine(
            store=InMemoryOmissionStore(),
            cieu_store=custom_store,
        )

        # Verify custom store is used
        assert isinstance(engine.cieu_store, CIEUStore)
        assert str(engine.cieu_store.db_path) == custom_db

        # Write a record
        record = _make_cieu_record()
        ok = engine.cieu_store.write_dict(record)
        assert ok is True

        # Verify persistence
        assert engine.cieu_store.count() == 1

        # Verify the file was created at the custom path
        assert os.path.exists(custom_db)

        # Open a fresh CIEUStore on the same path to confirm data survived
        fresh_store = CIEUStore(db_path=custom_db)
        assert fresh_store.count() == 1
        results = fresh_store.query(event_type="omission_violation:test")
        assert len(results) == 1
        assert results[0].event_id == record["event_id"]

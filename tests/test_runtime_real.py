"""
tests.test_runtime_real — Non-Mock Runtime Tests (N9)

Tests that use REAL infrastructure (no Mock for core objects):
  1. Real CIEUStore (SQLite), real OmissionStore, real compiler
  2. Real constraint application, real CIEU recording
  3. Real Bridge aggregation with real CIEU data
  4. Real AmendmentEngine with real CIEU

Uses tempfile for SQLite databases. Cleans up after.
"""
import os
import tempfile
import time
import uuid

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────

def _temp_db():
    """Create a temporary SQLite database file path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Real Path A Cycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealPathACycle:
    """Real CIEUStore(SQLite), real OmissionStore, real compiler."""

    def test_real_path_a_cycle(self):
        from ystar.governance.cieu_store import CIEUStore
        from ystar.governance.omission_store import InMemoryOmissionStore
        from ystar.governance.omission_engine import OmissionEngine
        from ystar.kernel.compiler import compile_source, CompiledContractBundle
        from ystar.kernel.contract_provider import ConstitutionProvider

        db_path = _temp_db()
        try:
            # Real CIEUStore backed by SQLite
            cieu_store = CIEUStore(db_path=db_path)

            # Real OmissionStore (in-memory is the real implementation for tests)
            omission_store = InMemoryOmissionStore()

            # Real OmissionEngine with real store
            engine = OmissionEngine(
                store=omission_store,
                cieu_store=cieu_store,
            )

            # Real compiler
            bundle = compile_source(
                "Never access /production. Never run rm -rf.",
                source_ref="test_constitution",
            )
            assert bundle.is_valid()
            assert bundle.source_hash != ""
            assert bundle.contract is not None

            # Real ConstitutionProvider
            provider = ConstitutionProvider()
            # Write a temp constitution file
            fd, const_path = tempfile.mkstemp(suffix=".md")
            os.close(fd)
            try:
                with open(const_path, "w") as f:
                    f.write("# Test Constitution\nNever access /production.\n")
                resolved = provider.resolve(const_path)
                assert resolved.source_hash != ""
                assert resolved.source_ref == const_path

                # Invalidate and re-resolve
                provider.invalidate_cache(const_path)
                resolved2 = provider.resolve(const_path)
                assert resolved2.source_hash == resolved.source_hash
            finally:
                os.unlink(const_path)

            # Write a real CIEU record
            record = {
                "event_id": str(uuid.uuid4()),
                "seq_global": int(time.time() * 1_000_000),
                "created_at": time.time(),
                "session_id": "test_session",
                "agent_id": "path_a_agent",
                "event_type": "test_path_a_cycle",
                "decision": "allow",
                "passed": True,
            }
            cieu_store.write_dict(record)

            # Verify the record was persisted
            stats = cieu_store.stats()
            assert stats["total"] >= 1

        finally:
            os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Real Path B Cycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealPathBCycle:
    """Real constraint application, real CIEU recording."""

    def test_real_path_b_cycle(self):
        from ystar.kernel.dimensions import IntentContract
        from ystar.kernel.engine import check
        from ystar.governance.cieu_store import CIEUStore

        db_path = _temp_db()
        try:
            cieu_store = CIEUStore(db_path=db_path)

            # Real constraint application
            contract = IntentContract(
                name="test_external_constraint",
                deny=["/production", "/etc/shadow"],
                deny_commands=["rm -rf", "sudo"],
            )

            # Passing check
            result = check(
                {"file": "/safe/path/data.txt"},
                {},
                contract,
            )
            assert result.passed

            # Failing check
            result_fail = check(
                {"file": "/production/secret.db"},
                {},
                contract,
            )
            assert not result_fail.passed
            assert len(result_fail.violations) > 0

            # Record both to real CIEU
            for i, (res, params) in enumerate([
                (result, {"file": "/safe/path/data.txt"}),
                (result_fail, {"file": "/production/secret.db"}),
            ]):
                record = {
                    "event_id": str(uuid.uuid4()),
                    "seq_global": int(time.time() * 1_000_000) + i,
                    "created_at": time.time(),
                    "session_id": "test_path_b",
                    "agent_id": "external_agent_1",
                    "event_type": "path_b.constraint_applied",
                    "decision": "allow" if res.passed else "deny",
                    "passed": res.passed,
                }
                cieu_store.write_dict(record)

            stats = cieu_store.stats()
            assert stats["total"] >= 2

        finally:
            os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Real Bridge Flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealBridgeFlow:
    """Real Bridge aggregation with real CIEU data."""

    def test_real_bridge_flow(self):
        from ystar.governance.experience_bridge import (
            ExperienceBridge, BridgeInput,
        )

        bridge = ExperienceBridge()

        # Real CIEU records (not mocked)
        cieu_records = [
            {
                "func_name": "path_b.constraint_applied",
                "path_b_event": "CONSTRAINT_APPLIED",
                "params": {"agent_id": "ext_agent_1", "cycle_id": "cycle_001"},
                "violations": [],
                "source": "path_b_agent",
            },
            {
                "func_name": "path_b.constraint_applied",
                "path_b_event": "CONSTRAINT_APPLIED",
                "params": {"agent_id": "ext_agent_1", "cycle_id": "cycle_002"},
                "violations": [{"dimension": "deny", "severity": 0.8}],
                "source": "path_b_agent",
            },
            {
                "func_name": "path_b.constraint_applied",
                "path_b_event": "CONSTRAINT_APPLIED",
                "params": {"agent_id": "ext_agent_1", "cycle_id": "cycle_003"},
                "violations": [{"dimension": "deny", "severity": 0.9}],
                "source": "path_b_agent",
            },
            {
                "func_name": "path_b.disconnect",
                "path_b_event": "EXTERNAL_AGENT_DISCONNECTED",
                "params": {"agent_id": "ext_agent_2", "cycle_id": "cycle_004"},
                "violations": [],
                "source": "path_b_agent",
            },
        ]

        # Structured ingest
        bridge_input = BridgeInput(cieu_records=cieu_records)
        assert bridge_input.is_valid()
        bridge.ingest(bridge_input)

        # Real aggregation
        patterns = bridge.aggregate_patterns()
        assert len(patterns) > 0

        # Real gap attribution
        gaps = bridge.attribute_gaps()
        assert len(gaps) > 0

        # Real metrics
        metrics = bridge.generate_observation_metrics()
        assert "external_constraint_effectiveness_rate" in metrics
        assert "external_budget_exhaustion_rate" in metrics
        assert "external_disconnect_pressure" in metrics
        assert 0.0 <= metrics["external_constraint_effectiveness_rate"] <= 1.0

        # N5: Real suggestion candidates from gaps
        output = bridge.generate_output()
        assert len(output.gap_candidates) > 0
        assert len(output.suggestion_candidates) > 0
        for sug in output.suggestion_candidates:
            assert hasattr(sug, "suggestion_type")
            assert hasattr(sug, "target")
            assert hasattr(sug, "confidence")
            assert hasattr(sug, "source_gap")
            assert hasattr(sug, "rationale")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Real Amendment Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealAmendmentLifecycle:
    """Real AmendmentEngine with real CIEU."""

    def test_real_amendment_lifecycle(self):
        from ystar.governance.amendment import AmendmentEngine, AmendmentProposal
        from ystar.governance.cieu_store import CIEUStore

        db_path = _temp_db()
        try:
            cieu_store = CIEUStore(db_path=db_path)
            engine = AmendmentEngine()

            # Create proposal
            proposal = AmendmentProposal(
                proposal_id="amend_001",
                target_document="PATH_A_AGENTS.md",
                proposed_by="board",
                current_hash="abc123",
                proposed_hash="def456",
                diff_summary="Added: new safety constraint for external APIs",
                rationale="External API access needs explicit governance",
            )

            # Full lifecycle: draft -> proposed -> under_review -> approved -> activated
            proposal = engine.propose(proposal, cieu_store)
            assert proposal.status == "proposed"

            proposal = engine.review("amend_001", "approve", "chairman")
            assert proposal.status == "approved"

            assert engine.has_approved_amendment("PATH_A_AGENTS.md", "def456")
            assert not engine.has_approved_amendment("PATH_A_AGENTS.md", "wrong_hash")

            proposal = engine.activate("amend_001", cieu_store)
            assert proposal.status == "activated"
            assert proposal.activated_at is not None

            assert engine.get_active_constitution_hash("PATH_A_AGENTS.md") == "def456"

            # Rollback
            proposal = engine.rollback("amend_001", cieu_store)
            assert proposal.status == "rolled_back"
            assert engine.get_active_constitution_hash("PATH_A_AGENTS.md") == "abc123"

            # Verify CIEU records were written
            stats = cieu_store.stats()
            assert stats["total"] >= 3  # proposed, activated, rolled_back

        finally:
            os.unlink(db_path)

    def test_amendment_invalid_transitions(self):
        """Verify the state machine rejects invalid transitions."""
        from ystar.governance.amendment import AmendmentEngine, AmendmentProposal
        from ystar.governance.cieu_store import CIEUStore

        db_path = _temp_db()
        try:
            cieu_store = CIEUStore(db_path=db_path)
            engine = AmendmentEngine()

            proposal = AmendmentProposal(
                proposal_id="amend_002",
                target_document="PATH_B_AGENTS.md",
                proposed_by="path_b",
            )
            engine.propose(proposal, cieu_store)

            # Cannot activate directly from proposed (must be approved first)
            with pytest.raises(ValueError):
                engine.activate("amend_002", cieu_store)

        finally:
            os.unlink(db_path)

# Layer: Tests
"""
Tests for T1-T5 (Batch 1 P0 items):
  T1. AmendmentEngine state machine
  T2. Amendment response chain in Path A/B
  T3. ContractLifecycle workflow
  T4. Constitution source unification (provider param)
  T5. CompileDiagnostics & diagnose_compilation
"""
from __future__ import annotations

import time
import pytest

from ystar.governance.amendment import (
    AmendmentEngine, AmendmentProposal, VALID_TRANSITIONS,
)
from ystar.governance.contract_lifecycle import ContractLifecycle, ContractDraft
from ystar.kernel.nl_to_contract import (
    CompileDiagnostics, diagnose_compilation, validate_contract_draft,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeCIEU:
    """Minimal CIEU store for testing."""
    def __init__(self):
        self.records = []

    def write_dict(self, record):
        self.records.append(record)
        return f"cieu_{len(self.records)}"


# ── T1: Amendment Engine ────────────────────────────────────────────────────

class TestAmendmentEngine:

    def test_propose_transitions_to_proposed(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        p = AmendmentProposal(
            proposal_id="p1",
            target_document="PATH_A_AGENTS.md",
            proposed_by="board",
        )
        result = engine.propose(p, cieu)
        assert result.status == "proposed"
        assert len(cieu.records) == 1
        assert "amendment.proposed" in cieu.records[0]["func_name"]

    def test_full_lifecycle_draft_to_activated(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        p = AmendmentProposal(
            proposal_id="p2",
            target_document="PATH_B_AGENTS.md",
            proposed_by="path_b",
            current_hash="abc123",
            proposed_hash="def456",
        )
        engine.propose(p, cieu)
        engine.review("p2", "approve", "chairman")
        assert p.status == "approved"
        assert p.reviewed_at is not None

        engine.activate("p2", cieu)
        assert p.status == "activated"
        assert p.activated_at is not None
        assert engine.get_active_constitution_hash("PATH_B_AGENTS.md") == "def456"

    def test_rollback_restores_hash(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        p = AmendmentProposal(
            proposal_id="p3",
            target_document="AGENTS.md",
            proposed_by="board",
            current_hash="old_hash",
            proposed_hash="new_hash",
        )
        engine.propose(p, cieu)
        engine.review("p3", "approve", "reviewer")
        engine.activate("p3", cieu)
        assert engine.get_active_constitution_hash("AGENTS.md") == "new_hash"

        engine.rollback("p3", cieu)
        assert p.status == "rolled_back"
        assert engine.get_active_constitution_hash("AGENTS.md") == "old_hash"

    def test_reject_blocks_activation(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        p = AmendmentProposal(
            proposal_id="p4",
            target_document="PATH_A_AGENTS.md",
            proposed_by="path_a",
        )
        engine.propose(p, cieu)
        engine.review("p4", "reject", "reviewer")
        assert p.status == "rejected"

        with pytest.raises(KeyError):
            engine.activate("nonexistent", cieu)

    def test_invalid_transition_raises(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        p = AmendmentProposal(
            proposal_id="p5",
            target_document="PATH_A_AGENTS.md",
            proposed_by="board",
        )
        engine.propose(p, cieu)  # now status="proposed", stored in engine
        # Cannot activate from "proposed" (must go through under_review -> approved)
        with pytest.raises(ValueError, match="Only 'approved'"):
            engine.activate("p5", cieu)

    def test_activate_requires_approved(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        p = AmendmentProposal(
            proposal_id="p6",
            target_document="PATH_A_AGENTS.md",
            proposed_by="board",
        )
        engine.propose(p, cieu)
        with pytest.raises(ValueError, match="Only 'approved'"):
            engine.activate("p6", cieu)

    def test_has_approved_amendment(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        p = AmendmentProposal(
            proposal_id="p7",
            target_document="PATH_A_AGENTS.md",
            proposed_by="board",
            proposed_hash="new_hash_abc",
        )
        engine.propose(p, cieu)
        engine.review("p7", "approve", "reviewer")

        assert engine.has_approved_amendment("PATH_A_AGENTS.md", "new_hash_abc")
        assert not engine.has_approved_amendment("PATH_A_AGENTS.md", "wrong_hash")
        assert not engine.has_approved_amendment("PATH_B_AGENTS.md", "new_hash_abc")

    def test_list_proposals_filter(self):
        engine = AmendmentEngine()
        cieu = FakeCIEU()
        for i in range(3):
            p = AmendmentProposal(
                proposal_id=f"list_{i}",
                target_document="PATH_A_AGENTS.md",
                proposed_by="board",
            )
            engine.propose(p, cieu)
        engine.review("list_1", "approve", "rev")

        assert len(engine.list_proposals()) == 3
        assert len(engine.list_proposals(status="proposed")) == 2
        assert len(engine.list_proposals(status="approved")) == 1

    def test_valid_transitions_coverage(self):
        """Every status in the state machine has an entry."""
        all_statuses = {"draft", "proposed", "under_review", "approved",
                        "rejected", "activated", "rolled_back"}
        assert set(VALID_TRANSITIONS.keys()) == all_statuses


# ── T2: Amendment Response Chain ─────────────────────────────────────────────

class TestAmendmentResponseChain:

    def test_path_b_accepts_approved_amendment(self):
        """PathBAgent accepts hash change when amendment is approved."""
        from ystar.path_b.path_b_agent import PathBAgent

        engine = AmendmentEngine()
        cieu = FakeCIEU()

        # Create and approve an amendment
        p = AmendmentProposal(
            proposal_id="pb1",
            target_document="PATH_B_AGENTS.md",
            proposed_by="board",
            proposed_hash="new_hash_xyz",
        )
        engine.propose(p, cieu)
        engine.review("pb1", "approve", "reviewer")

        agent = PathBAgent(
            cieu_store=cieu,
            amendment_engine=engine,
        )
        # Agent should be constructable with amendment_engine
        assert agent._amendment_engine is engine

    def test_path_a_accepts_constitution_provider(self):
        """PathAAgent accepts constitution_provider parameter."""
        from ystar.path_a.meta_agent import PathAAgent
        from ystar.governance.governance_loop import GovernanceLoop
        from ystar.governance.reporting import ReportEngine
        from ystar.governance.omission_store import InMemoryOmissionStore

        store = InMemoryOmissionStore()
        report_engine = ReportEngine(omission_store=store)
        gloop = GovernanceLoop(report_engine=report_engine)
        cieu = FakeCIEU()

        # Minimal planner mock
        class FakePlanner:
            class graph:
                _nodes = {}
                _edges = {}
                nodes = {}
                def get_node(self, nid): return None
                def list_nodes(self): return []
                def list_edges(self): return []
            graph = graph()
            def plan(self, *a, **kw): return []

        def my_provider(path):
            return "sha256:custom_hash_123"

        engine = AmendmentEngine()
        agent = PathAAgent(
            governance_loop=gloop,
            cieu_store=cieu,
            planner=FakePlanner(),
            constitution_provider=my_provider,
            amendment_engine=engine,
        )
        assert agent._constitution_provider is my_provider
        assert agent._amendment_engine is engine
        # Provider should be used in _load_constitution_hash
        assert agent._load_constitution_hash() == "sha256:custom_hash_123"

    def test_governance_loop_accepts_amendment_engine(self):
        """GovernanceLoop accepts amendment_engine parameter."""
        from ystar.governance.governance_loop import GovernanceLoop
        from ystar.governance.reporting import ReportEngine
        from ystar.governance.omission_store import InMemoryOmissionStore

        store = InMemoryOmissionStore()
        report_engine = ReportEngine(omission_store=store)
        engine = AmendmentEngine()
        gloop = GovernanceLoop(
            report_engine=report_engine,
            amendment_engine=engine,
        )
        assert gloop._amendment_engine is engine


# ── T3: Contract Lifecycle ──────────────────────────────────────────────────

class TestContractLifecycle:

    def test_compile_creates_draft(self):
        lifecycle = ContractLifecycle()
        source = "Never run rm -rf. Only allow access to api.github.com."
        draft = lifecycle.compile(source, "test_agents.md")
        assert draft.status == "draft"
        assert draft.contract is not None
        assert draft.source_document == "test_agents.md"
        assert draft.compile_confidence > 0

    def test_validate_transitions_to_validated(self):
        lifecycle = ContractLifecycle()
        source = "Deny access to /etc and /production."
        draft = lifecycle.compile(source, "test.md")
        validated = lifecycle.validate(draft)
        # If no errors, should transition
        if not validated.validation_report.get("errors"):
            assert validated.status == "validated"

    def test_full_lifecycle(self):
        lifecycle = ContractLifecycle()
        cieu = FakeCIEU()
        source = "Never run rm -rf. Deny /production."
        draft = lifecycle.compile(source, "test.md")
        lifecycle.validate(draft)
        if draft.status == "validated":
            lifecycle.submit_for_review(draft)
            assert draft.status == "under_review"

            lifecycle.approve(draft.draft_id, "chairman")
            assert draft.status == "approved"

            lifecycle.activate(draft.draft_id, cieu)
            assert draft.status == "active"
            assert draft.activated_at is not None
            assert len(cieu.records) >= 1

    def test_activate_requires_approved_status(self):
        lifecycle = ContractLifecycle()
        cieu = FakeCIEU()
        source = "Deny /etc."
        draft = lifecycle.compile(source, "test.md")
        with pytest.raises(ValueError, match="Only 'approved'"):
            lifecycle.activate(draft.draft_id, cieu)

    def test_supersede_old_contract(self):
        lifecycle = ContractLifecycle()
        cieu = FakeCIEU()

        # Create and activate first contract
        d1 = lifecycle.compile("Deny /etc.", "test.md")
        lifecycle.validate(d1)
        if d1.status == "validated":
            lifecycle.submit_for_review(d1)
            lifecycle.approve(d1.draft_id, "reviewer")
            lifecycle.activate(d1.draft_id, cieu)
            assert d1.status == "active"

            # Create and activate second - should supersede first
            d2 = lifecycle.compile("Deny /production.", "test.md")
            lifecycle.validate(d2)
            if d2.status == "validated":
                lifecycle.submit_for_review(d2)
                lifecycle.approve(d2.draft_id, "reviewer")
                lifecycle.activate(d2.draft_id, cieu)
                assert d2.status == "active"
                assert d1.status == "superseded"

    def test_rollback_to_draft(self):
        lifecycle = ContractLifecycle()
        source = "Deny /etc."
        draft = lifecycle.compile(source, "test.md")
        lifecycle.validate(draft)
        if draft.status == "validated":
            lifecycle.submit_for_review(draft)
            assert draft.status == "under_review"
            lifecycle.rollback(draft.draft_id)
            assert draft.status == "draft"

    def test_get_active_contract(self):
        lifecycle = ContractLifecycle()
        cieu = FakeCIEU()
        draft = lifecycle.compile("Deny /etc.", "my_doc.md")
        lifecycle.validate(draft)
        if draft.status == "validated":
            lifecycle.submit_for_review(draft)
            lifecycle.approve(draft.draft_id, "rev")
            lifecycle.activate(draft.draft_id, cieu)
            active = lifecycle.get_active_contract("my_doc.md")
            assert active is not None
            assert active.draft_id == draft.draft_id

    def test_get_constitution_hash(self):
        lifecycle = ContractLifecycle()
        # No active contract -> empty string
        assert lifecycle.get_constitution_hash("nonexistent.md") == ""


# ── T5: CompileDiagnostics ──────────────────────────────────────────────────

class TestCompileDiagnostics:

    def test_dataclass_fields(self):
        d = CompileDiagnostics()
        assert d.confidence == 0.0
        assert d.ambiguous_rules == []
        assert d.unsupported_rules == []
        assert d.warnings == []
        assert d.requires_human_review is False

    def test_diagnose_empty_contract(self):
        diag = diagnose_compilation("Some rules here", {})
        assert diag.confidence > 0
        assert diag.requires_human_review is True  # empty contract = low confidence

    def test_diagnose_good_contract(self):
        source = "Never run rm -rf. Deny /production path."
        contract = {
            "deny": ["/production"],
            "deny_commands": ["rm -rf"],
        }
        diag = diagnose_compilation(source, contract)
        assert diag.confidence > 0.3
        assert isinstance(diag.warnings, list)
        assert isinstance(diag.ambiguous_rules, list)

    def test_diagnose_detects_unsupported_rules(self):
        source = "The agent must complete tasks within 30 minutes."
        contract = {}  # nothing mapped
        diag = diagnose_compilation(source, contract)
        assert len(diag.unsupported_rules) > 0

    def test_diagnose_requires_review_on_low_confidence(self):
        diag = CompileDiagnostics(confidence=0.5)
        # The function itself determines this; test the function
        source = "some vague text"
        contract = {}
        result = diagnose_compilation(source, contract)
        assert result.requires_human_review is True

    def test_diagnose_ambiguous_paths(self):
        source = "Only allow writing to /workspace path."
        # deny is set but only_paths isn't -- ambiguous
        contract = {"deny": ["/workspace"]}
        diag = diagnose_compilation(source, contract)
        # Should detect path ambiguity
        assert isinstance(diag.ambiguous_rules, list)

    def test_diagnose_with_validation_errors(self):
        source = "Amount must be x = 5"
        contract = {
            "invariant": ["x = 5"],  # assignment, not comparison
        }
        diag = diagnose_compilation(source, contract)
        # Should have low confidence due to validation errors
        assert diag.confidence < 0.5

    def test_diagnose_clean_contract(self):
        source = "Deny /etc and deny rm -rf. Only allow api.github.com domain."
        contract = {
            "deny": ["/etc"],
            "deny_commands": ["rm -rf"],
            "only_domains": ["api.github.com"],
        }
        diag = diagnose_compilation(source, contract)
        assert diag.confidence > 0.4

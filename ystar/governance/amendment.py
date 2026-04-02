# Layer: Foundation
"""
ystar.governance.amendment — Formal constitution change protocol.

Amendment system for controlled modification of constitution documents
(PATH_A_AGENTS.md, PATH_B_AGENTS.md, AGENTS.md).

All state transitions write to CIEU. Activation requires status=="approved".

State machine:
  draft -> proposed -> under_review -> approved -> activated
                                    -> rejected
  activated -> rolled_back

Amendment Audit Chain:
  AmendmentRecord tracks every hash change with full metadata.
  AmendmentLog provides a chronological history of all amendments.
"""
from __future__ import annotations

import hashlib
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_log = logging.getLogger("ystar.governance.amendment")


# ── Amendment Audit Chain ────────────────────────────────────────────────────

@dataclass
class AmendmentRecord:
    """
    A record of a single constitution hash change.

    Created automatically when ConstitutionProvider detects a hash change.
    Tracks who changed what, when, and how.
    """
    amendment_id: str
    timestamp: float
    author_agent_id: str
    source_ref: str
    old_hash: str
    new_hash: str
    change_description: str = ""

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class AmendmentLog:
    """
    Chronological log of all amendment records for audit trail.

    Usage:
        log = AmendmentLog()
        record = AmendmentRecord(
            amendment_id="a1",
            timestamp=time.time(),
            author_agent_id="board",
            source_ref="PATH_A_AGENTS.md",
            old_hash="abc123",
            new_hash="def456",
            change_description="Added new obligation"
        )
        log.append(record)
        history = log.history("PATH_A_AGENTS.md")
    """

    def __init__(self) -> None:
        self._records: List[AmendmentRecord] = []
        self._index_by_source: Dict[str, List[AmendmentRecord]] = {}

    def append(self, record: AmendmentRecord) -> None:
        """Append a new amendment record to the log."""
        self._records.append(record)
        source_ref = record.source_ref
        if source_ref not in self._index_by_source:
            self._index_by_source[source_ref] = []
        self._index_by_source[source_ref].append(record)

    def history(self, source_ref: str) -> List[AmendmentRecord]:
        """Get chronological history of amendments for a specific source."""
        return self._index_by_source.get(source_ref, [])

    def all_records(self) -> List[AmendmentRecord]:
        """Get all amendment records in chronological order."""
        return self._records.copy()


# ── Amendment State Machine ──────────────────────────────────────────────────

VALID_TRANSITIONS: Dict[str, List[str]] = {
    "draft":        ["proposed"],
    "proposed":     ["under_review"],
    "under_review": ["approved", "rejected"],
    "approved":     ["activated"],
    "activated":    ["rolled_back"],
    "rejected":     [],
    "rolled_back":  [],
}


@dataclass
class AmendmentProposal:
    """A formal proposal to change a constitution document."""
    proposal_id: str
    target_document: str          # "PATH_A_AGENTS.md" / "PATH_B_AGENTS.md" / "AGENTS.md"
    proposed_by: str              # "board" / "path_a" / "path_b"
    status: str = "draft"         # draft->proposed->under_review->approved->rejected->activated->rolled_back
    current_hash: str = ""        # hash of current constitution
    proposed_hash: str = ""       # hash after amendment
    diff_summary: str = ""
    rationale: str = ""
    cieu_ref: str = ""
    created_at: float = field(default_factory=time.time)
    reviewed_at: Optional[float] = None
    activated_at: Optional[float] = None


class AmendmentEngine:
    """
    Engine for managing constitution amendment lifecycle.

    All state transitions are recorded in CIEU for auditability.
    Activation requires status=="approved" — no shortcutting allowed.
    """

    def __init__(self) -> None:
        self._proposals: Dict[str, AmendmentProposal] = {}
        self._active_hashes: Dict[str, str] = {}  # document -> current hash

    def _transition(self, proposal: AmendmentProposal, new_status: str) -> None:
        """Validate and apply a state transition."""
        allowed = VALID_TRANSITIONS.get(proposal.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {proposal.status} -> {new_status}. "
                f"Allowed: {allowed}"
            )
        proposal.status = new_status

    def _write_cieu(self, cieu_store, event_type: str, proposal: AmendmentProposal) -> str:
        """Write amendment event to CIEU audit trail."""
        record = {
            "func_name": f"amendment.{event_type}",
            "params": {
                "proposal_id": proposal.proposal_id,
                "target_document": proposal.target_document,
                "proposed_by": proposal.proposed_by,
                "status": proposal.status,
            },
            "result": {
                "current_hash": proposal.current_hash,
                "proposed_hash": proposal.proposed_hash,
                "diff_summary": proposal.diff_summary[:200],
            },
            "source": "amendment_engine",
            "is_meta_agent": True,
            "amendment_event": event_type,
        }
        ref = None
        try:
            ref = cieu_store.write_dict(record)
        except Exception as e:
            _log.warning("Failed to write amendment event to CIEU (event=%s, proposal=%s): %s",
                         event_type, proposal.proposal_id, e)
        return ref or proposal.proposal_id

    def propose(self, proposal: AmendmentProposal, cieu_store) -> AmendmentProposal:
        """
        Submit a new amendment proposal.

        Transitions: draft -> proposed.
        Records the proposal in CIEU.
        """
        self._transition(proposal, "proposed")
        proposal.cieu_ref = self._write_cieu(cieu_store, "proposed", proposal)
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def review(self, proposal_id: str, decision: str, reviewer: str) -> AmendmentProposal:
        """
        Review a proposal: approve or reject.

        Transitions: proposed -> under_review -> approved/rejected.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal not found: {proposal_id}")

        # Move to under_review first if still proposed
        if proposal.status == "proposed":
            self._transition(proposal, "under_review")

        # Then approve or reject
        if decision == "approve":
            self._transition(proposal, "approved")
        elif decision == "reject":
            self._transition(proposal, "rejected")
        else:
            raise ValueError(f"Invalid decision: {decision}. Must be 'approve' or 'reject'.")

        proposal.reviewed_at = time.time()
        return proposal

    def activate(self, proposal_id: str, cieu_store) -> AmendmentProposal:
        """
        Activate an approved amendment.

        Only proposals with status=="approved" can be activated.
        Updates the active constitution hash for the target document.
        Records activation in CIEU.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal not found: {proposal_id}")

        if proposal.status != "approved":
            raise ValueError(
                f"Cannot activate proposal in status '{proposal.status}'. "
                f"Only 'approved' proposals can be activated."
            )

        self._transition(proposal, "activated")
        proposal.activated_at = time.time()

        # Update active hash for this document
        self._active_hashes[proposal.target_document] = proposal.proposed_hash

        proposal.cieu_ref = self._write_cieu(cieu_store, "activated", proposal)
        return proposal

    def rollback(self, proposal_id: str, cieu_store) -> AmendmentProposal:
        """
        Roll back an activated amendment.

        Restores the previous constitution hash and records in CIEU.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal not found: {proposal_id}")

        self._transition(proposal, "rolled_back")

        # Restore the previous hash
        self._active_hashes[proposal.target_document] = proposal.current_hash

        proposal.cieu_ref = self._write_cieu(cieu_store, "rolled_back", proposal)
        return proposal

    def get_active_constitution_hash(self, document: str) -> str:
        """Get the current active hash for a constitution document."""
        return self._active_hashes.get(document, "")

    def has_approved_amendment(self, document: str, new_hash: str) -> bool:
        """
        Check if there is an approved (but not yet activated) amendment
        for the given document that matches the new hash.

        Used by Path A/B agents to distinguish authorized constitution
        changes from unauthorized tampering.
        """
        for proposal in self._proposals.values():
            if (proposal.target_document == document
                    and proposal.status in ("approved", "activated")
                    and proposal.proposed_hash == new_hash):
                return True
        return False

    def list_proposals(self, status: Optional[str] = None) -> List[AmendmentProposal]:
        """List all proposals, optionally filtered by status."""
        if status is None:
            return list(self._proposals.values())
        return [p for p in self._proposals.values() if p.status == status]

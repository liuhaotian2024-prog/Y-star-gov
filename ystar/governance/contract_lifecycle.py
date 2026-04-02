# Layer: Intent Compilation
"""
ystar.governance.contract_lifecycle — Formal contract lifecycle.

Compile -> Validate -> Review -> Activate workflow for IntentContracts.

Uses nl_to_contract.translate_to_contract() for the compile step.
Uses nl_to_contract.validate_contract_draft() for the validate step.

State machine:
  draft -> validated -> under_review -> approved -> active -> superseded
  any non-active state -> draft  (rollback)
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ystar.kernel.dimensions import IntentContract

_log = logging.getLogger(__name__)


@dataclass
class ContractDraft:
    """A contract in its lifecycle, from compilation to activation."""
    draft_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    contract: Optional[IntentContract] = None
    source_document: str = ""
    compile_confidence: float = 0.0
    validation_report: Dict[str, Any] = field(default_factory=dict)
    status: str = "draft"   # draft->validated->under_review->approved->active->superseded
    compile_method: str = ""  # "llm" / "regex"
    approved_by: str = ""
    created_at: float = field(default_factory=time.time)
    activated_at: Optional[float] = None


VALID_TRANSITIONS: Dict[str, List[str]] = {
    "draft":        ["validated"],
    "validated":    ["under_review", "draft"],  # can go back to draft on re-compile
    "under_review": ["approved", "draft"],      # rejected -> back to draft
    "approved":     ["active"],
    "active":       ["superseded"],
    "superseded":   [],
}


class ContractLifecycle:
    """
    Manages the full lifecycle of IntentContracts from natural language
    source through compilation, validation, review, and activation.

    Integrates with nl_to_contract for compilation and validation.
    """

    def __init__(self) -> None:
        self._drafts: Dict[str, ContractDraft] = {}
        self._active_contracts: Dict[str, ContractDraft] = {}  # source_document -> active draft

    def _transition(self, draft: ContractDraft, new_status: str) -> None:
        """Validate and apply a state transition."""
        allowed = VALID_TRANSITIONS.get(draft.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {draft.status} -> {new_status}. "
                f"Allowed: {allowed}"
            )
        draft.status = new_status

    def compile(self, source_text: str, source_path: str) -> ContractDraft:
        """
        Compile natural language text into a ContractDraft.

        Uses nl_to_contract.translate_to_contract() internally.
        The result is a draft that must be validated before activation.
        """
        from ystar.kernel.nl_to_contract import translate_to_contract

        contract_dict, method, confidence = translate_to_contract(source_text)

        # Build IntentContract from dict — only pass fields that IntentContract accepts
        ic_kwargs: Dict[str, Any] = {
            "name": f"lifecycle:{source_path}:{uuid.uuid4().hex[:6]}",
        }
        _IC_FIELDS = (
            "deny", "only_paths", "deny_commands", "only_domains",
            "invariant", "optional_invariant", "value_range",
            "obligation_timing",
        )
        for fld in _IC_FIELDS:
            val = contract_dict.get(fld)
            if val:
                ic_kwargs[fld] = val
        contract = IntentContract(**ic_kwargs)

        draft = ContractDraft(
            contract=contract,
            source_document=source_path,
            compile_confidence=confidence,
            compile_method=method,
            status="draft",
        )
        self._drafts[draft.draft_id] = draft
        return draft

    def validate(self, draft: ContractDraft) -> ContractDraft:
        """
        Validate a compiled draft using nl_to_contract.validate_contract_draft().

        Transitions: draft -> validated (if validation passes).
        The validation report is stored on the draft for review.
        """
        from ystar.kernel.nl_to_contract import validate_contract_draft

        if draft.contract is None:
            draft.validation_report = {
                "errors": ["No contract to validate"],
                "warnings": [],
                "suggestions": [],
                "coverage": 0.0,
                "is_healthy": False,
            }
            return draft

        # Build contract dict for validation
        contract_dict: Dict[str, Any] = {}
        for field_name in ("deny", "only_paths", "deny_commands", "only_domains",
                           "invariant", "optional_invariant", "value_range",
                           "temporal", "obligation_timing"):
            val = getattr(draft.contract, field_name, None)
            if val:
                contract_dict[field_name] = val

        report = validate_contract_draft(contract_dict, draft.source_document)
        draft.validation_report = report

        # Only transition if no hard errors
        if not report.get("errors"):
            self._transition(draft, "validated")

        return draft

    def submit_for_review(self, draft: ContractDraft) -> ContractDraft:
        """
        Submit a validated draft for human review.

        Transitions: validated -> under_review.
        """
        self._transition(draft, "under_review")
        return draft

    def approve(self, draft_id: str, approver: str) -> ContractDraft:
        """
        Approve a draft that is under review.

        Transitions: under_review -> approved.
        """
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise KeyError(f"Draft not found: {draft_id}")

        self._transition(draft, "approved")
        draft.approved_by = approver
        return draft

    def activate(self, draft_id: str, cieu_store) -> ContractDraft:
        """
        Activate an approved contract draft.

        Transitions: approved -> active.
        Records the activation in CIEU.
        """
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise KeyError(f"Draft not found: {draft_id}")

        if draft.status != "approved":
            raise ValueError(
                f"Cannot activate draft in status '{draft.status}'. "
                f"Only 'approved' drafts can be activated."
            )

        self._transition(draft, "active")
        draft.activated_at = time.time()

        # Supersede any previously active contract for the same source
        old_active = self._active_contracts.get(draft.source_document)
        if old_active and old_active.status == "active":
            old_active.status = "superseded"

        self._active_contracts[draft.source_document] = draft

        # Write to CIEU
        try:
            cieu_store.write_dict({
                "func_name": "contract_lifecycle.activate",
                "params": {
                    "draft_id": draft.draft_id,
                    "source_document": draft.source_document,
                    "approved_by": draft.approved_by,
                },
                "result": {
                    "status": "active",
                    "confidence": draft.compile_confidence,
                    "method": draft.compile_method,
                },
                "source": "contract_lifecycle",
            })
        except Exception as e:
            # Optional CIEU recording — failure is non-critical
            _log.debug(f"Could not record contract activation to CIEU: {e}")

        return draft

    def supersede(self, old_id: str, new_id: str) -> ContractDraft:
        """
        Mark an active contract as superseded by a new one.

        Transitions old: active -> superseded.
        """
        old_draft = self._drafts.get(old_id)
        new_draft = self._drafts.get(new_id)
        if old_draft is None:
            raise KeyError(f"Draft not found: {old_id}")
        if new_draft is None:
            raise KeyError(f"Draft not found: {new_id}")

        if old_draft.status == "active":
            old_draft.status = "superseded"

        return old_draft

    def rollback(self, draft_id: str) -> ContractDraft:
        """
        Roll back a draft to draft status.

        Can be used from validated, under_review, or approved states.
        """
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise KeyError(f"Draft not found: {draft_id}")

        if draft.status in ("validated", "under_review"):
            draft.status = "draft"
        elif draft.status == "approved":
            # Special case: approved but not yet active can be rolled back
            draft.status = "draft"
        else:
            raise ValueError(
                f"Cannot rollback draft in status '{draft.status}'."
            )
        return draft

    def get_active_contract(self, source_document: str) -> Optional[ContractDraft]:
        """Get the currently active contract for a source document."""
        draft = self._active_contracts.get(source_document)
        if draft and draft.status == "active":
            return draft
        return None

    def get_constitution_hash(self, source_document: str) -> str:
        """
        Get the constitution hash from the active contract for a document.

        Used by Path A/B as a constitution_provider callable.
        """
        draft = self.get_active_contract(source_document)
        if draft and draft.contract:
            return getattr(draft.contract, 'hash', '') or ''
        return ''

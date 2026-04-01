# Layer: Foundation
"""
ystar.governance.proposal_submission — Proposal Submission for GovernanceLoop
=============================================================================

Extracted from governance_loop.py to reduce its size.
Handles the three proposal submission methods:
  - submit_verified_proposals_to_registry
  - submit_suggestions_to_registry
  - apply_active_constraints_to_registry
"""
from __future__ import annotations

import time
import uuid
from typing import Any, List, Optional


def submit_verified_proposals(
    ystar_loop: Any,
    constraint_registry: Any,
    auto_approve_confidence_threshold: float = 0.7,
) -> int:
    """
    Connection 15: inquire_and_verify — run the full pipeline then submit.

    Combines auto_inquire_all() + verify_proposal() and directly submits
    proposals that pass mathematical verification to ConstraintRegistry.
    Only proposals with verdict=PASS/WARN enter the registry.

    Returns number of verified proposals submitted.
    """
    if not ystar_loop or not ystar_loop.history:
        return 0
    try:
        from ystar.governance.metalearning import inquire_and_verify, ManagedConstraint
        tuples = inquire_and_verify(
            history=ystar_loop.history,
            known_contract=ystar_loop.base_contract,
            domain_context="governance",
            api_call_fn=None,
            min_confidence=0.4,
        )
        submitted = 0
        for proposal, vreport in tuples:
            if vreport.verdict not in ("PASS", "WARN"):
                continue
            mc = ManagedConstraint(
                id=str(uuid.uuid4())[:8],
                dimension=getattr(proposal, 'suggested_dim', 'governance'),
                rule=getattr(proposal, 'suggested_rule', str(proposal)),
                status="DRAFT",
                source="inquire_and_verify",
                confidence=getattr(proposal, 'confidence', 0.5),
                created_at=time.time(),
                updated_at=time.time(),
                notes=(
                    f"verify={vreport.verdict} "
                    f"cov={vreport.empirical_coverage:.0%} "
                    f"fp={vreport.empirical_fp_rate:.0%}"
                ),
            )
            if constraint_registry:
                constraint_registry.add(mc)
                if mc.confidence >= auto_approve_confidence_threshold:
                    constraint_registry.verify(mc.id, notes="auto-verified")
                    constraint_registry.approve(mc.id, notes="auto-approved")
                submitted += 1
        return submitted
    except Exception:
        return 0


def submit_suggestions(
    suggestions: list,
    constraint_registry: Any,
    ystar_loop: Any,
    auto_approve_confidence_threshold: float = 0.9,
) -> int:
    """
    Submit governance suggestions to ConstraintRegistry controlled activation chain.

    Lifecycle: DRAFT -> VERIFIED (>=0.6) -> APPROVED (>=threshold) -> ACTIVE
    """
    if constraint_registry is None:
        return 0

    try:
        from ystar.governance.metalearning import ManagedConstraint
    except ImportError:
        return 0

    try:
        from ystar.governance.metalearning import verify_proposal, SemanticConstraintProposal
        _verify_available = True
    except ImportError:
        _verify_available = False

    submitted = 0
    for sug in suggestions:
        try:
            mc = ManagedConstraint(
                id=str(uuid.uuid4())[:8],
                dimension="governance_timing",
                rule=(
                    f"{sug.target_rule_id}:{sug.suggestion_type}"
                    f":{sug.suggested_value}"
                ),
                status="DRAFT",
                source="governance_loop",
                confidence=sug.confidence,
                created_at=time.time(),
                updated_at=time.time(),
                notes=sug.rationale[:200],
            )
            constraint_registry.add(mc)

            verification_passed = True
            if (_verify_available
                    and ystar_loop
                    and ystar_loop.history
                    and sug.confidence >= 0.6):
                try:
                    proposal = SemanticConstraintProposal(
                        dimension="governance_timing",
                        rule=mc.rule,
                        rationale=sug.rationale,
                        confidence=sug.confidence,
                    )
                    vreport = verify_proposal(proposal, ystar_loop.history)
                    verification_passed = vreport.verdict in ("PASS", "WARN")
                    notes_with_verify = (
                        f"{mc.notes} | verify={vreport.verdict} "
                        f"coverage={vreport.empirical_coverage:.0%} "
                        f"fp={vreport.empirical_fp_rate:.0%}"
                    )
                    mc = ManagedConstraint(
                        id=mc.id, dimension=mc.dimension, rule=mc.rule,
                        status=mc.status, source=mc.source,
                        confidence=sug.confidence * (1.1 if verification_passed else 0.5),
                        created_at=mc.created_at, updated_at=time.time(),
                        notes=notes_with_verify[:300],
                    )
                    constraint_registry.constraints = [
                        mc if c.id == mc.id else c
                        for c in constraint_registry.constraints
                    ]
                except Exception:
                    pass

            if sug.confidence >= 0.6 and verification_passed:
                constraint_registry.verify(mc.id,
                    notes=f"auto-verified (confidence={sug.confidence:.2f})")
            if (sug.confidence >= auto_approve_confidence_threshold
                    and verification_passed):
                constraint_registry.approve(mc.id,
                    notes=f"auto-approved+verified (confidence={sug.confidence:.2f})")

            submitted += 1
        except Exception:
            pass
    return submitted


def apply_active_constraints(
    constraint_registry: Any,
    omission_registry: Any,
) -> int:
    """
    Apply ACTIVE constraints from ConstraintRegistry to omission RuleRegistry.

    This is the final step of the closed loop:
    GovernanceSuggestion -> ConstraintRegistry -> ACTIVE -> actual governance parameter change.
    """
    if constraint_registry is None:
        return 0

    applied = 0
    try:
        active = constraint_registry.by_status("ACTIVE")
        for mc in active:
            parts = mc.rule.split(":", 2)
            if len(parts) < 2:
                continue
            rule_id, sug_type = parts[0], parts[1]
            try:
                if sug_type == "tighten_timing":
                    rule = omission_registry.get(rule_id)
                    if rule:
                        new_due = rule.due_within_secs * 0.8
                        omission_registry.override_timing(
                            rule_id, due_within_secs=new_due
                        )
                        applied += 1
                elif sug_type == "relax_timing":
                    rule = omission_registry.get(rule_id)
                    if rule:
                        new_due = rule.due_within_secs * 1.2
                        omission_registry.override_timing(
                            rule_id, due_within_secs=new_due
                        )
                        applied += 1
            except Exception:
                continue
    except Exception:
        pass
    return applied

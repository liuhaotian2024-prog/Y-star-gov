# Layer: Foundation
"""
ystar.governance.observation_fusion — Observation Processing & Health Assessment
================================================================================

Extracted from governance_loop.py to separate observation processing, health
assessment, and KPI computation from the orchestration layer.

Contains:
  - report_to_observation(): Report -> GovernanceObservation bridge
  - assess_health(): health label from observation
  - recommend_action(): action recommendation from observation + suggestions
  - score_contract_quality(): ContractQuality self-assessment
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def report_to_observation(report: "Report") -> "GovernanceObservation":
    """
    Convert a ReportEngine Report into a GovernanceObservation.
    This is the key bridge between the reporting layer and the meta-learning layer.
    """
    from ystar.governance.governance_loop import GovernanceObservation

    kpis = report.kpis or {}
    omission_d = report.omissions.to_dict() if report.omissions else {}

    return GovernanceObservation(
        period_label                = report.period_label,
        obligation_fulfillment_rate = kpis.get("obligation_fulfillment_rate", 0.0),
        obligation_expiry_rate      = kpis.get("obligation_expiry_rate", 0.0),
        hard_overdue_rate           = kpis.get("hard_overdue_rate", 0.0),
        omission_detection_rate     = kpis.get("omission_detection_rate", 0.0),
        omission_recovery_rate      = kpis.get("omission_recovery_rate", 0.0),
        intervention_recovery_rate  = kpis.get("intervention_recovery_rate", 0.0),
        false_positive_rate         = kpis.get("false_positive_rate", 0.0),
        chain_closure_rate          = kpis.get("chain_closure_rate", 0.0),
        raw_kpis                    = dict(kpis),
        by_omission_type            = dict(omission_d.get("by_omission_type", {})),
        by_actor                    = dict(omission_d.get("by_actor", {})),
        broken_chain_count          = omission_d.get("broken_chains", 0),
        total_entities              = report.chain.total_entities,
    )


def assess_health(obs: "GovernanceObservation") -> str:
    """Assess the overall health label from a GovernanceObservation."""
    if obs.is_healthy():
        return "healthy"
    if obs.hard_overdue_rate > 0.2 or obs.false_positive_rate > 0.1:
        return "critical"
    return "degraded"


def recommend_action(
    obs: "GovernanceObservation",
    suggestions: list,
) -> str:
    """Recommend an action based on observation state and suggestions."""
    if obs.is_healthy():
        return "System governance is healthy. Continue monitoring."
    if obs.needs_tightening():
        return ("High omission rate with low recovery. "
                "Consider applying a tighter domain pack or reviewing actor behavior.")
    if obs.needs_relaxing():
        return ("False positive rate is high. "
                "Consider relaxing timing thresholds to reduce incorrect violations.")
    if suggestions:
        top = suggestions[0]
        return f"Top suggestion: {top.suggestion_type} on {top.target_rule_id} ({top.rationale[:80]}...)"
    return "Review omission breakdown for specific improvement areas."


def score_contract_quality(
    ystar_loop: Any,
) -> Optional[Dict[str, Any]]:
    """
    Connection 6: ContractQuality + score_candidate.
    Score quality of the current contract from commission history.
    Returns dict with coverage/fp/quality metrics, or None if no history.
    """
    if not ystar_loop or not ystar_loop.history or \
            len(ystar_loop.history) < 3:
        return None
    try:
        from ystar.kernel.engine import check as _chk
        history  = ystar_loop.history
        contract = ystar_loop.base_contract
        if contract is None:
            return None
        incidents  = [r for r in history if r.violations]
        safe_calls = [r for r in history if not r.violations]
        if not incidents:
            return {"coverage_rate": 1.0, "false_positive_rate": 0.0,
                    "quality_score": 1.0, "incident_count": 0}
        n_prev = sum(1 for r in incidents
                     if _chk(r.params, r.result, contract).passed)
        n_fp   = sum(1 for r in safe_calls
                     if not _chk(r.params, r.result, contract).passed)
        cov = n_prev / max(len(incidents), 1)
        fp  = n_fp   / max(len(safe_calls), 1)
        return {
            "coverage_rate":       round(cov, 3),
            "false_positive_rate": round(fp, 3),
            "quality_score":       round(cov * 0.6 + (1 - fp) * 0.4, 3),
            "incident_count":      len(incidents),
            "safe_count":          len(safe_calls),
        }
    except Exception:
        return None

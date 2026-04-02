# Layer: Foundation
"""
ystar.governance.causal_feedback — Causal Integration for GovernanceLoop
========================================================================

Extracted from governance_loop.py to reduce its size.
Handles Pearl Integration points 1-3:
  1. CausalEngine weights governance suggestions via do-calculus
  2. Metalearning results fed to CausalEngine as observations
  3. Auto-trigger structure discovery when enough data accumulated
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ystar.governance.causal_engine import CausalEngine

_log = logging.getLogger("ystar.governance.causal_feedback")


def weight_suggestions_by_causal(
    causal_engine: CausalEngine,
    suggestions: list,
) -> List[str]:
    """
    Pearl Integration 1: Weight governance suggestions by causal confidence.

    For each suggestion, queries P(Health|do(suggestion)) and blends
    causal confidence with the suggestion's original confidence.

    Returns causal chain entries for audit trail.
    """
    causal_chain_entries: List[str] = []
    for sug in suggestions:
        try:
            do_result = causal_engine.do_wire_query(
                sug.suggestion_type,
                sug.target_rule_id,
            )
            if do_result.confidence > 0:
                original_conf = sug.confidence
                sug.confidence = (
                    0.5 * original_conf + 0.5 * do_result.confidence
                )
                causal_chain_entries.append(
                    f"P(H|do({sug.suggestion_type}→{sug.target_rule_id}))"
                    f"={do_result.predicted_health}"
                    f" conf={do_result.confidence:.2f}"
                    f" (original={original_conf:.2f}→{sug.confidence:.2f})"
                )
            causal_chain_entries.extend(do_result.causal_chain)
        except Exception as e:
            _log.warning("Causal weighting failed for %s->%s: %s",
                         sug.suggestion_type, sug.target_rule_id, e)
    return causal_chain_entries


def feed_metalearning_to_causal(
    causal_engine: CausalEngine,
    observations: list,
    commission_result: Any,
) -> None:
    """
    Pearl Integration 2: Feed metalearning tighten results to CausalEngine.

    Converts governance observation deltas into CausalObservation format
    so the Pearl engine can track metalearning outcomes.
    """
    if len(observations) < 2 or commission_result is None:
        return

    try:
        prev, curr = observations[-2], observations[-1]
        health_improved = (
            curr.obligation_fulfillment_rate > prev.obligation_fulfillment_rate
            or (curr.hard_overdue_rate < prev.hard_overdue_rate)
        )
        stype = None
        if hasattr(commission_result, 'adjustments'):
            stype = "metalearning_tighten"

        total_ent = max(curr.total_entities, 1)
        fulfilled = int(curr.obligation_fulfillment_rate * total_ent)
        prev_fulfilled = int(prev.obligation_fulfillment_rate * total_ent)

        health_label = "healthy" if curr.is_healthy() else (
            "degraded" if curr.hard_overdue_rate > 0.1 else "stable"
        )
        prev_health = "healthy" if prev.is_healthy() else (
            "degraded" if prev.hard_overdue_rate > 0.1 else "stable"
        )

        causal_engine.observe(
            health_before=prev_health,
            health_after=health_label,
            obl_before=(prev_fulfilled, total_ent),
            obl_after=(fulfilled, total_ent),
            edges_before=[],
            edges_after=[],
            action_edges=[("metalearning", "governance")],
            succeeded=health_improved,
            cycle_id=f"governance_tighten_{curr.period_label}",
            suggestion_type=stype,
        )
    except Exception as e:
        _log.warning("Failed to feed metalearning result to causal engine: %s", e)


def try_structure_discovery(causal_engine: CausalEngine) -> Optional[Any]:
    """
    Pearl Integration 3: Auto-trigger structure discovery.

    When >= 30 cycle-level observations have accumulated, run PC algorithm
    to validate the causal DAG against data-discovered structure.
    """
    try:
        n_obs = causal_engine.count_cycle_observations()
        if n_obs >= 30:
            discovered = causal_engine.learn_structure(min_observations=30)
            if discovered is not None:
                return getattr(causal_engine, '_structure_validation', None)
    except Exception as e:
        _log.warning("Structure discovery failed (n_obs=%d): %s",
                     causal_engine.count_cycle_observations() if hasattr(causal_engine, 'count_cycle_observations') else 0, e)
    return None

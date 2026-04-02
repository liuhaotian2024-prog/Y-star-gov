# Layer: Foundation
"""
ystar.governance.suggestion_policy — Governance Suggestion Policy & Generation
==============================================================================

Extracted from governance_loop.py to separate the suggestion generation concern
from the orchestration layer.

Contains:
  - GovernanceSuggestionPolicy: configurable thresholds and templates
  - generate_governance_suggestions(): deterministic suggestion generation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


# ── GovernanceSuggestion (shared data type) ──────────────────────────────────
# Defined here (not in governance_loop.py) so that Path A, Path B, and other
# subsystems can import it without depending on the orchestration layer.

@dataclass
class GovernanceSuggestion:
    """
    一条基于观测产生的治理参数调整建议。
    不直接修改任何配置，而是提交给 ConstraintRegistry 受控激活。
    """
    suggestion_type:  str   = ""
    target_rule_id:   str   = ""
    current_value:    Any   = None
    suggested_value:  Any   = None
    confidence:       float = 0.5
    rationale:        str   = ""
    observation_ref:  str   = ""

    def to_constraint_proposal_dict(self) -> dict:
        """转换为 ConstraintRegistry 可消费的格式。"""
        return {
            "rule_id":         self.target_rule_id,
            "suggestion_type": self.suggestion_type,
            "current":         self.current_value,
            "suggested":       self.suggested_value,
            "confidence":      self.confidence,
            "rationale":       self.rationale,
            "source":          "governance_loop",
        }


# ── N7: GovernanceSuggestionPolicy ────────────────────────────────────────────
# All suggestion generation thresholds and templates are now configurable
# through this policy dataclass.

@dataclass
class GovernanceSuggestionPolicy:
    """Policy controlling which governance suggestions are generated and when.

    Contains:
      - suggestion_templates: list of rule dicts (condition -> suggestion type)
      - health_thresholds: named thresholds for health assessment
    """
    suggestion_templates: list = field(default_factory=lambda: [
        {
            "id": "tighten_timing",
            "condition": "omission_high_recovery_low",
            "omission_detection_min": 0.3,
            "omission_recovery_max": 0.4,
            "target_rule_id": "rule_a_delegation",
            "suggestion_type": "tighten_timing",
            "max_confidence": 0.8,
        },
        {
            "id": "relax_timing",
            "condition": "false_positive_high",
            "false_positive_min": 0.05,
            "target_rule_id": "all_rules",
            "suggestion_type": "relax_timing",
            "max_confidence": 0.7,
        },
        {
            "id": "add_domain_pack",
            "condition": "hard_overdue_high_fulfillment_low",
            "hard_overdue_min": 0.1,
            "fulfillment_max": 0.5,
            "target_rule_id": "registry",
            "suggestion_type": "add_domain_pack",
            "fixed_confidence": 0.6,
        },
        {
            "id": "focus_rule",
            "condition": "concentrated_omission_type",
            "concentration_threshold": 0.6,
            "suggestion_type": "focus_rule",
            "fixed_confidence": 0.7,
        },
    ])
    health_thresholds: dict = field(default_factory=lambda: {
        "fulfillment_healthy": 0.8,
        "hard_overdue_healthy": 0.05,
        "false_positive_healthy": 0.02,
        "hard_overdue_critical": 0.2,
        "false_positive_critical": 0.1,
    })


def generate_governance_suggestions(
    obs: "GovernanceObservation",
    policy: GovernanceSuggestionPolicy,
) -> "List[GovernanceSuggestion]":
    """
    Generate governance parameter adjustment suggestions from an observation.

    Deterministic: given the same observation and policy, always produces the
    same suggestions.

    N7: Thresholds and templates are driven by GovernanceSuggestionPolicy
    instead of hardcoded values.
    """
    # GovernanceSuggestion is defined above in this module

    suggestions: List[GovernanceSuggestion] = []

    for tmpl in policy.suggestion_templates:
        cond = tmpl.get("condition", "")

        if cond == "omission_high_recovery_low":
            odr_min = tmpl.get("omission_detection_min", 0.3)
            orr_max = tmpl.get("omission_recovery_max", 0.4)
            if obs.omission_detection_rate > odr_min and obs.omission_recovery_rate < orr_max:
                suggestions.append(GovernanceSuggestion(
                    suggestion_type = tmpl.get("suggestion_type", "tighten_timing"),
                    target_rule_id  = tmpl.get("target_rule_id", "rule_a_delegation"),
                    current_value   = "current_domain_pack_value",
                    suggested_value = "reduce_by_20_percent",
                    confidence      = min(obs.omission_detection_rate, tmpl.get("max_confidence", 0.8)),
                    rationale       = (
                        f"Omission detection rate {obs.omission_detection_rate:.1%} is high "
                        f"but recovery rate {obs.omission_recovery_rate:.1%} is low. "
                        f"Consider tightening timing to force earlier compliance."
                    ),
                    observation_ref = obs.period_label,
                ))

        elif cond == "false_positive_high":
            fp_min = tmpl.get("false_positive_min", 0.05)
            if obs.false_positive_rate > fp_min:
                suggestions.append(GovernanceSuggestion(
                    suggestion_type = tmpl.get("suggestion_type", "relax_timing"),
                    target_rule_id  = tmpl.get("target_rule_id", "all_rules"),
                    current_value   = "current_domain_pack_values",
                    suggested_value = "increase_by_20_percent",
                    confidence      = min(obs.false_positive_rate * 10, tmpl.get("max_confidence", 0.7)),
                    rationale       = (
                        f"False positive rate {obs.false_positive_rate:.1%} exceeds {fp_min:.0%} threshold. "
                        f"Governance rules may be too aggressive. Consider relaxing timing."
                    ),
                    observation_ref = obs.period_label,
                ))

        elif cond == "hard_overdue_high_fulfillment_low":
            ho_min = tmpl.get("hard_overdue_min", 0.1)
            ful_max = tmpl.get("fulfillment_max", 0.5)
            if obs.hard_overdue_rate > ho_min and obs.obligation_fulfillment_rate < ful_max:
                suggestions.append(GovernanceSuggestion(
                    suggestion_type = tmpl.get("suggestion_type", "add_domain_pack"),
                    target_rule_id  = tmpl.get("target_rule_id", "registry"),
                    current_value   = None,
                    suggested_value = "apply appropriate domain pack",
                    confidence      = tmpl.get("fixed_confidence", 0.6),
                    rationale       = (
                        f"Hard overdue rate {obs.hard_overdue_rate:.1%} is high with low fulfillment "
                        f"{obs.obligation_fulfillment_rate:.1%}. "
                        f"A domain pack with appropriate timings may improve compliance."
                    ),
                    observation_ref = obs.period_label,
                ))

        elif cond == "concentrated_omission_type":
            if obs.by_omission_type:
                threshold = tmpl.get("concentration_threshold", 0.6)
                top_type, top_count = max(obs.by_omission_type.items(),
                                           key=lambda x: x[1])
                total = sum(obs.by_omission_type.values())
                if top_count / max(total, 1) > threshold:
                    suggestions.append(GovernanceSuggestion(
                        suggestion_type = tmpl.get("suggestion_type", "focus_rule"),
                        target_rule_id  = top_type.replace("required_", "rule_").replace("_omission", ""),
                        current_value   = top_count,
                        suggested_value = "prioritize this rule for domain pack override",
                        confidence      = tmpl.get("fixed_confidence", 0.7),
                        rationale       = (
                            f"'{top_type}' accounts for {top_count/max(total,1):.0%} of all omissions. "
                            f"Focused domain pack tuning for this rule may have highest impact."
                        ),
                        observation_ref = obs.period_label,
                    ))

    return suggestions

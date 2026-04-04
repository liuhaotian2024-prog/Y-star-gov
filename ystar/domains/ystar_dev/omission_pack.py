"""
ystar.domains.ystar_dev.omission_pack
======================================
v1.0.0

Y* Self-Governance Omission Rules
----------------------------------
治理自身开发过程的时限规则，对应 AGENTS.md 中的 Constitutional Rules。

这是 dogfooding 的核心：Y*gov 治理 Y*gov 自身的开发过程。

Obligations covered:
    - directive_decomposition: Board directive 必须在 10 分钟内分解
    - article_source_verification: 文章声明必须在 5 分钟内验证来源
    - cieu_archive_before_cleanup: 数据库清理前必须 archive CIEU 数据
    - directive_tracker_update: Session end 必须更新 DIRECTIVE_TRACKER.md
    - session_handoff_update: Session end 必须更新 session_handoff.md

使用方式：
    from ystar.domains.ystar_dev.omission_pack import apply_ystar_dev_omission_pack
    from ystar.governance.omission_rules import get_registry

    registry = get_registry()
    apply_ystar_dev_omission_pack(registry, contract=contract)
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ystar.governance.omission_rules import RuleRegistry

from ystar.governance.omission_rules import OmissionRule, _select_current_owner
from ystar.governance.omission_models import (
    EscalationPolicy, EscalationAction, Severity,
    GEventType,
)


def apply_ystar_dev_omission_pack(
    registry: "RuleRegistry",
    contract = None,
) -> None:
    """
    应用 Y* 自治理 omission 规则。

    这些规则对应 AGENTS.md Constitutional Rules：
        1. Directive Tracking: 10 分钟内分解 Board directive
        2. Article Writing: 5 分钟内验证文章来源
        3. CIEU Data Preservation: 数据库清理前必须 archive
        4. Session Handoff: Session end 必须更新 handoff

    Args:
        registry: OmissionRuleRegistry
        contract: IntentContract（含 obligation_timing 覆盖）
    """

    # ── Rule 1: Directive Decomposition (AGENTS.md Constitutional Rule) ──────────
    directive_decomp_rule = OmissionRule(
        rule_id             = "ystar_directive_decomposition",
        name                = "Directive Decomposition Required",
        description         = "Board directives must be decomposed within 10 minutes",
        trigger_event_types = [GEventType.ENTITY_CREATED],
        entity_types        = ["board_directive", "directive"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_directive_decomposition_omission",
        required_event_types= ["directive_decomposed_event", "tracker_updated_event"],
        due_within_secs     = 600.0,  # 10 minutes
        violation_code      = "required_directive_decomposition_omission",
        severity            = Severity.CRITICAL,
        escalation_policy   = EscalationPolicy(
            reminder_after_secs  = 300.0,
            violation_after_secs = 1800.0,
            escalate_after_secs  = 900.0,
            actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                    EscalationAction.ESCALATE],
            escalate_to          = "ceo",
        ),
    )
    registry.register(directive_decomp_rule)

    # ── Rule 2: Article Source Verification (AGENTS.md Constitutional Rule) ──────
    article_verify_rule = OmissionRule(
        rule_id             = "ystar_article_source_verification",
        name                = "Article Source Verification Required",
        description         = "All article claims must be verified within 5 minutes",
        trigger_event_types = [GEventType.ENTITY_CREATED],
        entity_types        = ["article_draft", "blog_post", "content"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_article_source_verification_omission",
        required_event_types= ["source_verified_event", "claims_cited_event"],
        due_within_secs     = 300.0,  # 5 minutes
        violation_code      = "required_article_source_verification_omission",
        severity            = Severity.CRITICAL,
        escalation_policy   = EscalationPolicy(
            reminder_after_secs  = 120.0,
            violation_after_secs = 1800.0,
            actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                    EscalationAction.DENY_CLOSURE],
            deny_closure_on_open = True,
        ),
        deny_closure_on_open= True,
    )
    registry.register(article_verify_rule)

    # ── Rule 3: CIEU Archive Before Cleanup (AGENTS.md Constitutional Rule) ──────
    cieu_archive_rule = OmissionRule(
        rule_id             = "ystar_cieu_archive_required",
        name                = "CIEU Archive Before Database Cleanup",
        description         = "CIEU data must be archived before any database cleanup",
        trigger_event_types = [GEventType.ENTITY_CREATED],
        entity_types        = ["database_cleanup_request", "experiment_completion"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_cieu_archive_omission",
        required_event_types= ["cieu_archived_event", "archive_verified_event"],
        due_within_secs     = 60.0,  # 1 minute before cleanup
        violation_code      = "required_cieu_archive_omission",
        severity            = Severity.CRITICAL,
        escalation_policy   = EscalationPolicy(
            violation_after_secs = 1800.0,
            actions              = [EscalationAction.VIOLATION, EscalationAction.DENY_CLOSURE],
            deny_closure_on_open = True,
        ),
        deny_closure_on_open= True,
    )
    registry.register(cieu_archive_rule)

    # ── Rule 4: Directive Tracker Update at Session End ──────────────────────────
    tracker_update_rule = OmissionRule(
        rule_id             = "ystar_directive_tracker_update",
        name                = "Directive Tracker Update Required",
        description         = "DIRECTIVE_TRACKER.md must be updated at session end",
        trigger_event_types = [GEventType.ENTITY_CREATED],
        entity_types        = ["session_end", "session_close"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_tracker_update_omission",
        required_event_types= ["tracker_updated_event", "directive_status_event"],
        due_within_secs     = 300.0,  # 5 minutes
        violation_code      = "required_tracker_update_omission",
        severity            = Severity.HIGH,
        escalation_policy   = EscalationPolicy(
            reminder_after_secs  = 120.0,
            violation_after_secs = 1800.0,
            actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION],
        ),
    )
    registry.register(tracker_update_rule)

    # ── Rule 5: Session Handoff Update ───────────────────────────────────────────
    handoff_update_rule = OmissionRule(
        rule_id             = "ystar_session_handoff_update",
        name                = "Session Handoff Update Required",
        description         = "session_handoff.md must be updated at session end",
        trigger_event_types = [GEventType.ENTITY_CREATED],
        entity_types        = ["session_end", "session_close"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_handoff_update_omission",
        required_event_types= ["handoff_updated_event", "session_summary_event"],
        due_within_secs     = 300.0,  # 5 minutes
        violation_code      = "required_handoff_update_omission",
        severity            = Severity.HIGH,
        escalation_policy   = EscalationPolicy(
            reminder_after_secs  = 120.0,
            violation_after_secs = 1800.0,
            actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION],
        ),
    )
    registry.register(handoff_update_rule)

    # ── Rule 6: Social Media Approval Required (AGENTS.md Constitutional Rule) ───
    social_approval_rule = OmissionRule(
        rule_id             = "ystar_social_media_approval",
        name                = "Social Media Board Approval Required",
        description         = "All social media actions require Board approval",
        trigger_event_types = [GEventType.ENTITY_CREATED],
        entity_types        = ["social_post_draft", "social_comment", "social_action"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_social_approval_omission",
        required_event_types= ["board_approved_event", "board_rejected_event",
                               "approval_request_event"],
        due_within_secs     = 1800.0,  # 30 minutes to get approval
        violation_code      = "required_social_approval_omission",
        severity            = Severity.CRITICAL,
        escalation_policy   = EscalationPolicy(
            reminder_after_secs  = 600.0,
            violation_after_secs = 1800.0,
            actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                    EscalationAction.DENY_CLOSURE],
            deny_closure_on_open = True,
        ),
        deny_closure_on_open= True,
    )
    registry.register(social_approval_rule)

    # ── Apply contract timing overrides ──────────────────────────────────────────
    if contract:
        _apply_contract_timing_overrides(registry, contract)


def _apply_contract_timing_overrides(
    registry: "RuleRegistry",
    contract,
) -> None:
    """
    从 IntentContract.obligation_timing 覆盖时限。

    支持的 obligation_timing 键：
        - directive_decomposition: 600
        - article_source_verification: 300
        - cieu_archive: 60
        - tracker_update: 300
        - handoff_update: 300
        - social_approval: 1800
    """
    if contract is None:
        return

    ot = getattr(contract, "obligation_timing", None) or {}
    if not ot:
        return

    mapping = {
        "directive_decomposition":     "ystar_directive_decomposition",
        "article_source_verification": "ystar_article_source_verification",
        "cieu_archive":                "ystar_cieu_archive_required",
        "tracker_update":              "ystar_directive_tracker_update",
        "handoff_update":              "ystar_session_handoff_update",
        "social_approval":             "ystar_social_media_approval",
    }

    for key, rule_id in mapping.items():
        if key in ot:
            secs = float(ot[key])
            grace = max(secs * 0.1, 5.0)
            try:
                registry.override_timing(
                    rule_id,
                    due_within_secs   = secs,
                    grace_period_secs = grace,
                    hard_overdue_secs = secs,
                )
            except (KeyError, AttributeError):
                pass


# ── Pack metadata ─────────────────────────────────────────────────────────────
PACK_INFO = {
    "name":        "ystar_dev_omission",
    "version":     "1.0.0",
    "description": "Y*gov self-governance omission rules",
    "rules": [
        "ystar_directive_decomposition",
        "ystar_article_source_verification",
        "ystar_cieu_archive_required",
        "ystar_directive_tracker_update",
        "ystar_session_handoff_update",
        "ystar_social_media_approval",
    ],
}

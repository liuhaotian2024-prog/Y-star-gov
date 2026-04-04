"""
ystar.omission_domain_packs  —  Domain-Specific Omission Rule Configurations
=============================================================================

展示如何通过 RuleRegistry 为不同 domain 定制 omission governance 规则。
这是 contract-first 架构的核心扩展点——不修改 core engine，只声明不同的时限和规则。

内置 domain pack：
    finance    — 高频交易场景：delegation 30s，ack 10s，escalation 5s
    healthcare — 医疗工作流：delegation 5min，status 更新 30min，严格 closure
    devops     — CI/CD 流水线：快速 ack，blocker 必须立即上报
    research   — 研究场景：宽松时限，重结果发布
    legal      — 法律合规场景：审计可追溯，多层审批，文档归档
    crypto     — 加密货币交易：24/7 运行，极低延迟，实时风控
    pharma     — 制药监管场景：SAE 15天上报，死亡 7天，审计追踪强制

使用方式：
    from ystar.domains.omission_domain_packs import apply_finance_pack
    from ystar.governance.omission_rules import get_registry

    registry = get_registry()
    apply_finance_pack(registry)       # 覆盖内置规则时限
    apply_finance_pack(registry, strict=True)  # 增加 finance 专属规则

    # 之后创建 engine 正常使用
    engine = OmissionEngine(store=store, registry=registry)
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from ystar.governance.omission_rules import RuleRegistry, OmissionRule, ActorSelectorFn, _select_current_owner
from ystar.governance.omission_models import (
    EscalationPolicy, EscalationAction, Severity,
    TrackedEntity, GovernanceEvent, GEventType, OmissionType,
)


# ── 公共工具：从合约读时限覆盖（所有 domain pack 共用）────────────────────
# 这是时限来源链条在 domain pack 层的实现：
#   用户 AGENTS.md → obligation_timing → 覆盖 domain pack 预设值

def _apply_contract_timing_overrides(
    registry: RuleRegistry,
    contract: Any,
) -> None:
    """
    从 IntentContract.obligation_timing 覆盖 domain pack 的预设时限。

    domain pack 的时限是"场景经验值"，合约的时限是"用户意图"。
    用户意图优先于场景经验值。

    Args:
        registry: 已经 apply 了 domain pack 的规则注册表
        contract: IntentContract（None 时不做任何覆盖）
    """
    if contract is None:
        return

    # 复用 openclaw accountability pack 里的映射表
    try:
        from ystar.domains.openclaw.accountability_pack import _contract_to_timing
        overrides = _contract_to_timing(contract)
    except ImportError:
        return

    for rule_id, t in overrides.items():
        try:
            registry.override_timing(
                rule_id,
                due_within_secs   = t["due_within_secs"],
                grace_period_secs = t.get("grace", 0.0),
                hard_overdue_secs = t.get("hard_overdue_secs", 0.0),
            )
        except (KeyError, AttributeError):
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Finance Domain Pack
# ══════════════════════════════════════════════════════════════════════════════

def apply_finance_pack(
    registry: RuleRegistry,
    strict:   bool = False,
    contract: Any  = None,
) -> None:
    """
    金融 / 高频交易 domain omission 配置。

    核心原则：时间就是金钱。所有时限大幅压缩。

    时限覆盖：
        delegation    : 300s → 30s
        acknowledgement: 120s → 10s
        status_update : 600s → 60s（活跃交易 1 分钟内必须有状态）
        result_pub    : 60s → 5s（结果立即发布）
        upstream_notify: 180s → 15s
        escalation    : 120s → 5s（阻塞必须立即上报）

    strict=True 时额外添加：
        - 交易风控专属规则：risk_assessment_event 必须在 order 创建后 3s 内出现
    """
    # 覆盖内置规则时限
    overrides = {
        "rule_a_delegation":          (30.0,   0.0),
        "rule_b_acknowledgement":     (10.0,   0.0),
        "rule_c_status_update":       (60.0,   0.0),
        "rule_d_result_publication":  (5.0,    0.0),
        "rule_e_upstream_notification":(15.0,  0.0),
        "rule_f_escalation":          (5.0,    0.0),
        "rule_g_closure":             (60.0,   0.0),
    }
    for rule_id, (due, grace) in overrides.items():
        registry.override_timing(rule_id, due_within_secs=due, grace_period_secs=grace)

    # 更新 escalation policies 以适应金融场景的紧迫性
    for rule_id in ("rule_a_delegation", "rule_f_escalation"):
        rule = registry.get(rule_id)
        if rule:
            rule.severity = Severity.CRITICAL
            rule.escalation_policy.escalate_after_secs = 10.0
            if EscalationAction.ESCALATE not in rule.escalation_policy.actions:
                rule.escalation_policy.actions.append(EscalationAction.ESCALATE)

    if strict:
        # 金融专属规则：risk assessment 必须在 3 秒内完成
        risk_rule = OmissionRule(
            rule_id             = "finance_risk_assessment",
            name                = "Risk Assessment Required",
            description         = "All trade orders must have risk assessment within 3s",
            trigger_event_types = [GEventType.ENTITY_CREATED],
            entity_types        = ["trade_order", "order", "execution"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_risk_assessment_omission",
            required_event_types= ["risk_assessment_event", "risk_approved_event",
                                   "risk_rejected_event"],
            due_within_secs     = 3.0,
            violation_code      = "required_risk_assessment_omission",
            severity            = Severity.CRITICAL,
            escalation_policy   = EscalationPolicy(
                violation_after_secs = 1800.0,
                escalate_after_secs  = 5.0,
                actions              = [EscalationAction.VIOLATION, EscalationAction.ESCALATE,
                                        EscalationAction.DENY_CLOSURE],
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(risk_rule)

        # 结算确认规则
        settlement_rule = OmissionRule(
            rule_id             = "finance_settlement_confirm",
            name                = "Settlement Confirmation Required",
            description         = "Completed trades must have settlement confirmation within 30s",
            trigger_event_types = [GEventType.RESULT_PUBLICATION_EVENT],
            entity_types        = ["trade_order", "execution"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_settlement_confirmation_omission",
            required_event_types= ["settlement_confirmed_event", "settlement_failed_event"],
            due_within_secs     = 30.0,
            violation_code      = "required_settlement_confirmation_omission",
            severity            = Severity.HIGH,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 15.0,
                violation_after_secs = 1800.0,
                escalate_after_secs  = 60.0,
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION],
            ),
        )
        registry.register(settlement_rule)

    # 合约时限优先于 domain pack 预设（用户意图 > 场景经验值）
    _apply_contract_timing_overrides(registry, contract)


# ══════════════════════════════════════════════════════════════════════════════
# Healthcare Domain Pack
# ══════════════════════════════════════════════════════════════════════════════

def apply_healthcare_pack(
    registry: RuleRegistry,
    strict:   bool = False,
    contract: Any  = None,
) -> None:
    """
    医疗工作流 domain omission 配置。

    核心原则：patient safety first。关键环节时限严格，
    但常规状态更新允许更长周期。Closure 必须有完整记录。

    时限覆盖：
        delegation    : 300s → 300s（保持 5 分钟，等待科室分配）
        acknowledgement: 120s → 120s（保持，急诊另行配置）
        status_update : 600s → 1800s（30 分钟更新一次病情）
        result_pub    : 60s → 300s（检查结果 5 分钟内出报告）
        upstream_notify: 180s → 600s（10 分钟上报）
        escalation    : 120s → 60s（阻塞必须 1 分钟内上报）

    strict=True 时额外添加：
        - 知情同意规则：手术类 entity 必须在 closure 前获得 consent_event
        - 药物核对规则：medication_order 必须有 double_check_event
    """
    overrides = {
        "rule_a_delegation":          (300.0,  30.0),
        "rule_b_acknowledgement":     (120.0,  15.0),
        "rule_c_status_update":       (1800.0, 60.0),
        "rule_d_result_publication":  (300.0,  30.0),
        "rule_e_upstream_notification":(600.0, 60.0),
        "rule_f_escalation":          (60.0,   0.0),   # 阻塞必须立即上报
        "rule_g_closure":             (600.0,  60.0),  # 病历必须 10 分钟内完成
    }
    for rule_id, (due, grace) in overrides.items():
        registry.override_timing(rule_id, due_within_secs=due, grace_period_secs=grace)

    # escalation 规则：HIGH severity，必须升级
    rule_esc = registry.get("rule_f_escalation")
    if rule_esc:
        rule_esc.severity = Severity.HIGH
        rule_esc.escalation_policy.escalate_to = "on_call_physician"
        rule_esc.escalation_policy.escalate_after_secs = 120.0
        if EscalationAction.ESCALATE not in rule_esc.escalation_policy.actions:
            rule_esc.escalation_policy.actions.append(EscalationAction.ESCALATE)

    if strict:
        # 知情同意规则
        consent_rule = OmissionRule(
            rule_id             = "healthcare_informed_consent",
            name                = "Informed Consent Required",
            description         = "Surgical/invasive procedures require consent before closure",
            trigger_event_types = [GEventType.ENTITY_ASSIGNED],
            entity_types        = ["surgical_procedure", "invasive_procedure"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_informed_consent_omission",
            required_event_types= ["informed_consent_event", "consent_waived_event"],
            due_within_secs     = 3600.0,  # 1 hour to get consent
            violation_code      = "required_informed_consent_omission",
            severity            = Severity.CRITICAL,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 1800.0,
                violation_after_secs = 1800.0,
                escalate_after_secs  = 7200.0,
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                        EscalationAction.ESCALATE, EscalationAction.DENY_CLOSURE],
                escalate_to          = "chief_of_staff",
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(consent_rule)

        # 药物双核对规则
        med_check_rule = OmissionRule(
            rule_id             = "healthcare_medication_double_check",
            name                = "Medication Double Check Required",
            description         = "High-risk medications require double-check before administration",
            trigger_event_types = [GEventType.ENTITY_CREATED],
            entity_types        = ["medication_order", "high_risk_medication"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_medication_double_check_omission",
            required_event_types= ["double_check_event", "pharmacist_verify_event"],
            due_within_secs     = 900.0,  # 15 minutes
            violation_code      = "required_medication_double_check_omission",
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
        registry.register(med_check_rule)

    # 合约时限优先于 domain pack 预设（用户意图 > 场景经验值）
    _apply_contract_timing_overrides(registry, contract)


# ══════════════════════════════════════════════════════════════════════════════
# DevOps Domain Pack
# ══════════════════════════════════════════════════════════════════════════════

def apply_devops_pack(
    registry: RuleRegistry,
    contract: Any = None,
) -> None:
    """
    CI/CD / DevOps domain omission 配置。

    核心原则：流水线不能堵塞。blocker 必须立即上报，pipeline 快速流转。

    额外规则：
        - pipeline_test_required: 代码变更必须有测试通过记录
        - deployment_approval: 生产部署必须有 approval
    """
    overrides = {
        "rule_a_delegation":          (60.0,  0.0),
        "rule_b_acknowledgement":     (30.0,  0.0),
        "rule_c_status_update":       (300.0, 0.0),
        "rule_d_result_publication":  (30.0,  0.0),
        "rule_e_upstream_notification":(60.0, 0.0),
        "rule_f_escalation":          (15.0,  0.0),  # blocker 15 秒内上报
        "rule_g_closure":             (120.0, 0.0),
    }
    for rule_id, (due, grace) in overrides.items():
        registry.override_timing(rule_id, due_within_secs=due, grace_period_secs=grace)

    # 测试通过规则
    test_rule = OmissionRule(
        rule_id             = "devops_test_required",
        name                = "Test Required Before Merge",
        description         = "Code changes must have test_pass_event before result_publication",
        trigger_event_types = [GEventType.ENTITY_CREATED],
        entity_types        = ["pull_request", "code_change", "patch"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_test_pass_omission",
        required_event_types= ["test_pass_event", "test_skipped_event"],
        due_within_secs     = 600.0,  # 10 min build time
        violation_code      = "required_test_pass_omission",
        severity            = Severity.HIGH,
        escalation_policy   = EscalationPolicy(
            violation_after_secs = 0,
            actions              = [EscalationAction.VIOLATION, EscalationAction.DENY_CLOSURE],
            deny_closure_on_open = True,
        ),
        deny_closure_on_open= True,
    )
    registry.register(test_rule)

    # 生产部署审批规则
    deploy_rule = OmissionRule(
        rule_id             = "devops_prod_deployment_approval",
        name                = "Production Deployment Approval Required",
        description         = "Production deployments require explicit approval",
        trigger_event_types = [GEventType.ENTITY_ASSIGNED],
        entity_types        = ["production_deployment", "prod_deploy"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_deployment_approval_omission",
        required_event_types= ["deployment_approved_event", "deployment_rejected_event"],
        due_within_secs     = 1800.0,  # 30 min to get approval
        violation_code      = "required_deployment_approval_omission",
        severity            = Severity.HIGH,
        escalation_policy   = EscalationPolicy(
            reminder_after_secs  = 900.0,
            violation_after_secs = 0,
            escalate_after_secs  = 3600.0,
            actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                    EscalationAction.ESCALATE, EscalationAction.DENY_CLOSURE],
            escalate_to          = "release_manager",
            deny_closure_on_open = True,
        ),
        deny_closure_on_open= True,
    )
    registry.register(deploy_rule)

    # 合约时限优先于 domain pack 预设（用户意图 > 场景经验值）
    _apply_contract_timing_overrides(registry, contract)


# ══════════════════════════════════════════════════════════════════════════════
# Research Domain Pack
# ══════════════════════════════════════════════════════════════════════════════

def apply_research_pack(registry: RuleRegistry) -> None:
    """
    研究 / 实验室 domain omission 配置。

    核心原则：研究周期长，但结果发布和 closure 必须规范。

    时限覆盖：宽松，重点放在 result_publication 和 closure 的规范性。
    """
    overrides = {
        "rule_a_delegation":          (3600.0, 300.0),  # 1 hour delegation
        "rule_b_acknowledgement":     (1800.0, 120.0),  # 30 min ack
        "rule_c_status_update":       (86400.0, 3600.0),# daily status
        "rule_d_result_publication":  (3600.0, 300.0),  # 1 hour to publish
        "rule_e_upstream_notification":(7200.0, 600.0), # 2 hour upstream notify
        "rule_f_escalation":          (1800.0, 120.0),  # 30 min escalation
        "rule_g_closure":             (86400.0, 3600.0),# 1 day closure
    }
    for rule_id, (due, grace) in overrides.items():
        registry.override_timing(rule_id, due_within_secs=due, grace_period_secs=grace)

    # 实验结果可复现性规则
    reproducibility_rule = OmissionRule(
        rule_id             = "research_reproducibility",
        name                = "Reproducibility Evidence Required",
        description         = "Experiment results must have reproducibility evidence or notes",
        trigger_event_types = [GEventType.RESULT_PUBLICATION_EVENT],
        entity_types        = ["experiment", "trial", "simulation"],
        actor_selector      = _select_current_owner,
        obligation_type     = "required_reproducibility_evidence_omission",
        required_event_types= ["reproducibility_confirmed_event", "replication_note_event",
                               "negative_result_event"],
        due_within_secs     = 86400.0,  # 1 day
        violation_code      = "required_reproducibility_evidence_omission",
        severity            = Severity.MEDIUM,
        escalation_policy   = EscalationPolicy(
            reminder_after_secs  = 43200.0,
            violation_after_secs = 0,
            actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION],
        ),
    )
    registry.register(reproducibility_rule)


# ══════════════════════════════════════════════════════════════════════════════
# Legal/Compliance Domain Pack
# ══════════════════════════════════════════════════════════════════════════════

def apply_legal_pack(
    registry: RuleRegistry,
    strict:   bool = False,
    contract: Any  = None,
) -> None:
    """
    法律合规 domain omission 配置。

    核心原则：审计可追溯性优先。时限严格但允许合理延期。
    多层审批流程，文档保留要求。

    时限覆盖：
        delegation    : 300s → 3600s（1小时分配案件）
        acknowledgement: 120s → 3600s（1小时确认收到）
        status_update : 600s → 86400s（每日状态更新）
        result_pub    : 60s → 7200s（2小时发布法律意见）
        upstream_notify: 180s → 3600s（1小时上报）
        escalation    : 120s → 1800s（30分钟上报阻塞）

    strict=True 时额外添加：
        - 利益冲突检查：新案件必须在24小时内完成conflict check
        - 审批链完整性：重大决策必须有完整approval chain
    """
    overrides = {
        "rule_a_delegation":          (3600.0,  300.0),
        "rule_b_acknowledgement":     (3600.0,  300.0),
        "rule_c_status_update":       (86400.0, 3600.0),
        "rule_d_result_publication":  (7200.0,  600.0),
        "rule_e_upstream_notification":(3600.0, 300.0),
        "rule_f_escalation":          (1800.0,  120.0),
        "rule_g_closure":             (86400.0, 3600.0),
    }
    for rule_id, (due, grace) in overrides.items():
        registry.override_timing(rule_id, due_within_secs=due, grace_period_secs=grace)

    # escalation 规则：CRITICAL severity，必须有audit trail
    rule_esc = registry.get("rule_f_escalation")
    if rule_esc:
        rule_esc.severity = Severity.CRITICAL
        rule_esc.escalation_policy.escalate_to = "general_counsel"
        rule_esc.escalation_policy.escalate_after_secs = 3600.0
        if EscalationAction.ESCALATE not in rule_esc.escalation_policy.actions:
            rule_esc.escalation_policy.actions.append(EscalationAction.ESCALATE)

    if strict:
        # 利益冲突检查规则
        conflict_check_rule = OmissionRule(
            rule_id             = "legal_conflict_check",
            name                = "Conflict Check Required",
            description         = "New matters must have conflict check within 24 hours",
            trigger_event_types = [GEventType.ENTITY_CREATED],
            entity_types        = ["legal_matter", "new_client", "engagement"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_conflict_check_omission",
            required_event_types= ["conflict_check_passed_event", "conflict_check_failed_event",
                                   "conflict_waived_event"],
            due_within_secs     = 86400.0,  # 24 hours
            violation_code      = "required_conflict_check_omission",
            severity            = Severity.CRITICAL,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 43200.0,
                violation_after_secs = 1800.0,
                escalate_after_secs  = 172800.0,
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                        EscalationAction.ESCALATE, EscalationAction.DENY_CLOSURE],
                escalate_to          = "general_counsel",
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(conflict_check_rule)

        # 审批链完整性规则
        approval_chain_rule = OmissionRule(
            rule_id             = "legal_approval_chain",
            name                = "Approval Chain Required",
            description         = "Major decisions require complete approval chain",
            trigger_event_types = [GEventType.ENTITY_CREATED],
            entity_types        = ["settlement", "legal_opinion", "major_decision"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_approval_chain_omission",
            required_event_types= ["approval_obtained_event", "approval_chain_complete_event"],
            due_within_secs     = 172800.0,  # 48 hours
            violation_code      = "required_approval_chain_omission",
            severity            = Severity.HIGH,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 86400.0,
                violation_after_secs = 1800.0,
                escalate_after_secs  = 259200.0,
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                        EscalationAction.DENY_CLOSURE],
                escalate_to          = "general_counsel",
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(approval_chain_rule)

        # 文档归档规则
        archive_rule = OmissionRule(
            rule_id             = "legal_document_archive",
            name                = "Document Archive Required",
            description         = "Closed matters must have documents archived",
            trigger_event_types = [GEventType.RESULT_PUBLICATION_EVENT],
            entity_types        = ["legal_matter", "litigation", "contract_review"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_document_archive_omission",
            required_event_types= ["documents_archived_event", "retention_applied_event"],
            due_within_secs     = 86400.0,  # 24 hours after closure
            violation_code      = "required_document_archive_omission",
            severity            = Severity.CRITICAL,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 43200.0,
                violation_after_secs = 1800.0,
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                        EscalationAction.DENY_CLOSURE],
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(archive_rule)

    # 合约时限优先于 domain pack 预设（用户意图 > 场景经验值）
    _apply_contract_timing_overrides(registry, contract)


# ══════════════════════════════════════════════════════════════════════════════
# Crypto Domain Pack
# ══════════════════════════════════════════════════════════════════════════════

def apply_crypto_pack(
    registry: RuleRegistry,
    strict:   bool = False,
    contract: Any  = None,
) -> None:
    """
    加密货币交易 domain omission 配置。

    核心原则：24/7 全天候运行，极低延迟，实时风控。
    时限比 finance pack 更严格，因为链上确认不可逆且清算风险高。

    时限覆盖：
        delegation    : 300s → 15s（快速分配订单到执行agent）
        acknowledgement: 120s → 5s（必须立即确认收到订单）
        status_update : 600s → 30s（持续监控仓位状态）
        result_pub    : 60s → 3s（交易结果立即发布）
        upstream_notify: 180s → 10s（立即上报执行情况）
        escalation    : 120s → 3s（阻塞必须实时上报）
        closure       : 600s → 30s（快速结算关闭）

    strict=True 时额外添加：
        - 清算监控规则：health_factor 低于阈值必须立即报警
        - 链上确认规则：交易必须有 on-chain confirmation
        - 滑点检查规则：实际滑点必须在容忍范围内
    """
    # 覆盖内置规则时限（比 finance 更严格）
    overrides = {
        "rule_a_delegation":          (15.0,  0.0),
        "rule_b_acknowledgement":     (5.0,   0.0),
        "rule_c_status_update":       (30.0,  0.0),
        "rule_d_result_publication":  (3.0,   0.0),
        "rule_e_upstream_notification":(10.0, 0.0),
        "rule_f_escalation":          (3.0,   0.0),
        "rule_g_closure":             (30.0,  0.0),
    }
    for rule_id, (due, grace) in overrides.items():
        registry.override_timing(rule_id, due_within_secs=due, grace_period_secs=grace)

    # 更新 escalation policies 以适应 crypto 的高风险特性
    for rule_id in ("rule_a_delegation", "rule_f_escalation"):
        rule = registry.get(rule_id)
        if rule:
            rule.severity = Severity.CRITICAL
            rule.escalation_policy.escalate_after_secs = 5.0
            if EscalationAction.ESCALATE not in rule.escalation_policy.actions:
                rule.escalation_policy.actions.append(EscalationAction.ESCALATE)

    if strict:
        # 清算监控规则
        liquidation_rule = OmissionRule(
            rule_id             = "crypto_liquidation_monitoring",
            name                = "Liquidation Monitoring Required",
            description         = "Positions with health_factor < 1.2 must have monitoring alert",
            trigger_event_types = [GEventType.ENTITY_CREATED, GEventType.ENTITY_ASSIGNED],
            entity_types        = ["leveraged_position", "futures_position", "perpetual_position"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_liquidation_monitoring_omission",
            required_event_types= ["liquidation_alert_event", "health_check_event",
                                   "position_reduced_event"],
            due_within_secs     = 5.0,  # 5 seconds to set up monitoring
            violation_code      = "required_liquidation_monitoring_omission",
            severity            = Severity.CRITICAL,
            escalation_policy   = EscalationPolicy(
                violation_after_secs = 1800.0,
                escalate_after_secs  = 10.0,
                actions              = [EscalationAction.VIOLATION, EscalationAction.ESCALATE,
                                        EscalationAction.DENY_CLOSURE],
                escalate_to          = "risk_manager",
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(liquidation_rule)

        # 链上确认规则
        onchain_confirm_rule = OmissionRule(
            rule_id             = "crypto_onchain_confirmation",
            name                = "On-Chain Confirmation Required",
            description         = "Executed trades must have on-chain confirmation",
            trigger_event_types = [GEventType.RESULT_PUBLICATION_EVENT],
            entity_types        = ["trade_execution", "withdrawal", "deposit"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_onchain_confirmation_omission",
            required_event_types= ["onchain_confirmed_event", "settlement_confirmed_event",
                                   "blockchain_verified_event"],
            due_within_secs     = 60.0,  # 1 minute for blockchain confirmation
            violation_code      = "required_onchain_confirmation_omission",
            severity            = Severity.HIGH,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 30.0,
                violation_after_secs = 1800.0,
                escalate_after_secs  = 120.0,
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                        EscalationAction.DENY_CLOSURE],
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(onchain_confirm_rule)

        # 滑点检查规则
        slippage_check_rule = OmissionRule(
            rule_id             = "crypto_slippage_check",
            name                = "Slippage Check Required",
            description         = "Executed trades must have slippage verification",
            trigger_event_types = [GEventType.RESULT_PUBLICATION_EVENT],
            entity_types        = ["trade_execution", "swap", "order_fill"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_slippage_check_omission",
            required_event_types= ["slippage_verified_event", "execution_quality_event"],
            due_within_secs     = 10.0,  # 10 seconds to verify slippage
            violation_code      = "required_slippage_check_omission",
            severity            = Severity.MEDIUM,
            escalation_policy   = EscalationPolicy(
                violation_after_secs = 1800.0,
                actions              = [EscalationAction.VIOLATION],
            ),
        )
        registry.register(slippage_check_rule)

    # 合约时限优先于 domain pack 预设（用户意图 > 场景经验值）
    _apply_contract_timing_overrides(registry, contract)


# ══════════════════════════════════════════════════════════════════════════════
# Pharma Regulatory Domain Pack
# ══════════════════════════════════════════════════════════════════════════════

def apply_pharma_pack(
    registry: RuleRegistry,
    strict:   bool = False,
    contract: Any  = None,
) -> None:
    """
    制药监管 domain omission 配置（FDA/ICH 合规场景）。

    核心原则：患者安全优先，审计可追溯性，严格的时间窗口。
    SAE（严重不良事件）和死亡报告有法定时限。

    时限覆盖：
        delegation    : 300s → 86400s（1天分配审查任务）
        acknowledgement: 120s → 7200s（2小时确认）
        status_update : 600s → 86400s（每日更新）
        result_pub    : 60s → 86400s（1天内发布结果）
        upstream_notify: 180s → 7200s（2小时上报）
        escalation    : 120s → 3600s（1小时上报阻塞）
        closure       : 600s → 259200s（3天完成文档归档）

    strict=True 时额外添加：
        - SAE 报告规则：严重不良事件必须在 15 天内上报（ICH E2A / 21 CFR 312.32）
        - 死亡报告规则：死亡事件必须在 7 天内上报（21 CFR 312.32）
        - 审计追踪规则：数据修改必须有电子签名和审计记录（21 CFR Part 11）
    """
    # 覆盖内置规则时限（宽松，但严格遵守监管时限）
    overrides = {
        "rule_a_delegation":          (86400.0,  3600.0),
        "rule_b_acknowledgement":     (7200.0,   600.0),
        "rule_c_status_update":       (86400.0,  3600.0),
        "rule_d_result_publication":  (86400.0,  3600.0),
        "rule_e_upstream_notification":(7200.0,  600.0),
        "rule_f_escalation":          (3600.0,   300.0),
        "rule_g_closure":             (259200.0, 7200.0),  # 3 days for documentation
    }
    for rule_id, (due, grace) in overrides.items():
        registry.override_timing(rule_id, due_within_secs=due, grace_period_secs=grace)

    # escalation 规则：CRITICAL severity，上报到 principal investigator
    rule_esc = registry.get("rule_f_escalation")
    if rule_esc:
        rule_esc.severity = Severity.CRITICAL
        rule_esc.escalation_policy.escalate_to = "principal_investigator"
        rule_esc.escalation_policy.escalate_after_secs = 7200.0
        if EscalationAction.ESCALATE not in rule_esc.escalation_policy.actions:
            rule_esc.escalation_policy.actions.append(EscalationAction.ESCALATE)

    if strict:
        # SAE 报告规则（15天法定时限，来自 ICH E2A / 21 CFR 312.32）
        sae_rule = OmissionRule(
            rule_id             = "pharma_sae_reporting",
            name                = "Serious Adverse Event Reporting Required",
            description         = "SAEs must be reported within 15 days (ICH E2A / 21 CFR 312.32)",
            trigger_event_types = [GEventType.ENTITY_CREATED],
            entity_types        = ["serious_adverse_event", "sae", "unanticipated_problem"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_sae_reporting_omission",
            required_event_types= ["sae_reported_event", "regulatory_notification_event",
                                   "ade_medwatch_filed_event"],
            due_within_secs     = 1296000.0,  # 15 days
            violation_code      = "required_sae_reporting_omission",
            severity            = Severity.CRITICAL,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 604800.0,  # 7 days reminder
                violation_after_secs = 1800.0,
                escalate_after_secs  = 1728000.0,  # 20 days
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                        EscalationAction.ESCALATE, EscalationAction.DENY_CLOSURE],
                escalate_to          = "principal_investigator",
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(sae_rule)

        # 死亡报告规则（7天法定时限，来自 21 CFR 312.32）
        death_rule = OmissionRule(
            rule_id             = "pharma_death_reporting",
            name                = "Death Reporting Required",
            description         = "Deaths must be reported within 7 days (21 CFR 312.32)",
            trigger_event_types = [GEventType.ENTITY_CREATED],
            entity_types        = ["death_event", "fatal_adverse_event", "subject_death"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_death_reporting_omission",
            required_event_types= ["death_reported_event", "regulatory_notification_event",
                                   "fda_notification_event"],
            due_within_secs     = 604800.0,  # 7 days
            violation_code      = "required_death_reporting_omission",
            severity            = Severity.CRITICAL,
            escalation_policy   = EscalationPolicy(
                reminder_after_secs  = 172800.0,  # 2 days reminder
                violation_after_secs = 1800.0,
                escalate_after_secs  = 864000.0,   # 10 days
                actions              = [EscalationAction.REMINDER, EscalationAction.VIOLATION,
                                        EscalationAction.ESCALATE, EscalationAction.DENY_CLOSURE],
                escalate_to          = "principal_investigator",
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(death_rule)

        # 审计追踪规则（21 CFR Part 11 要求）
        audit_rule = OmissionRule(
            rule_id             = "pharma_audit_trail",
            name                = "Audit Trail Required",
            description         = "Data modifications require electronic signature and audit trail (21 CFR Part 11)",
            trigger_event_types = [GEventType.ENTITY_CREATED, GEventType.ENTITY_ASSIGNED],
            entity_types        = ["source_data_modification", "data_entry", "case_report_form"],
            actor_selector      = _select_current_owner,
            obligation_type     = "required_audit_trail_omission",
            required_event_types= ["electronic_signature_event", "audit_logged_event",
                                   "part11_verification_event"],
            due_within_secs     = 300.0,  # 5 minutes to log audit trail
            violation_code      = "required_audit_trail_omission",
            severity            = Severity.HIGH,
            escalation_policy   = EscalationPolicy(
                violation_after_secs = 1800.0,
                actions              = [EscalationAction.VIOLATION, EscalationAction.DENY_CLOSURE],
                deny_closure_on_open = True,
            ),
            deny_closure_on_open= True,
        )
        registry.register(audit_rule)

    # 合约时限优先于 domain pack 预设（用户意图 > 场景经验值）
    _apply_contract_timing_overrides(registry, contract)


# ══════════════════════════════════════════════════════════════════════════════
# Pack Registry — 按名字获取 pack 函数
# ══════════════════════════════════════════════════════════════════════════════

_PACKS = {
    "finance":    apply_finance_pack,
    "healthcare": apply_healthcare_pack,
    "devops":     apply_devops_pack,
    "research":   apply_research_pack,
    "legal":      apply_legal_pack,
    "crypto":     apply_crypto_pack,
    "pharma":     apply_pharma_pack,
}


def apply_domain_pack(name: str, registry: RuleRegistry, **kwargs) -> None:
    """
    按名字应用 domain pack。

    参数：
        name:     "finance" / "healthcare" / "devops" / "research" / "legal" / "crypto" / "pharma"
        registry: RuleRegistry 实例
        **kwargs: 传递给具体 pack 函数的额外参数（如 strict=True）
    """
    fn = _PACKS.get(name.lower())
    if fn is None:
        raise ValueError(f"Unknown domain pack: {name!r}. Available: {list(_PACKS)}")
    fn(registry, **kwargs)


def list_packs() -> list:
    """返回所有可用 domain pack 名称。"""
    return list(_PACKS)

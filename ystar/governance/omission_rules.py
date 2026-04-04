"""
ystar.omission_rules  —  Contract-Driven Omission Rule Definitions
==================================================================

OmissionRule 定义了"什么情况下什么人必须在多少时间内做什么事"。
规则不硬编码角色，而是用 actor_selector 函数动态确定责任人。

内置 7 条通用规则（A~G），完全通过抽象模型表达，不含 manager/worker 词汇。
通过 RuleRegistry 可注册自定义规则（domain pack 扩展点）。

架构：
    Trigger Event
        ↓  rule matches?
    OmissionRule.actor_selector(entity, event) → actor_id
        ↓
    ObligationRecord created (due_at = event.ts + due_within_secs)
        ↓  required_event arrives → FULFILLED
        ↓  due_at passes without required_event → EXPIRED → OmissionViolation
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ystar.governance.omission_models import (
    EscalationPolicy, EscalationAction, GEventType,
    OmissionType, Severity, TrackedEntity, GovernanceEvent,
)


# ── Actor Selector 类型 ──────────────────────────────────────────────────────
#
# actor_selector(entity, trigger_event) → actor_id or None
#   返回 None 表示"此规则不适用于这个事件/实体"，跳过创建 obligation
#
ActorSelectorFn = Callable[[TrackedEntity, GovernanceEvent], Optional[str]]


def _select_current_owner(entity: TrackedEntity, event: GovernanceEvent) -> Optional[str]:
    return entity.current_owner_id


def _select_initiator(entity: TrackedEntity, event: GovernanceEvent) -> Optional[str]:
    return entity.initiator_id


def _select_from_event_actor(entity: TrackedEntity, event: GovernanceEvent) -> Optional[str]:
    return event.actor_id or None


def _select_parent_initiator(entity: TrackedEntity, event: GovernanceEvent) -> Optional[str]:
    """上级实体的 initiator（用于 upstream notification）。"""
    parent_id = entity.parent_entity_id
    if not parent_id:
        return entity.initiator_id
    # 从 event payload 里找上级 initiator
    return event.payload.get("parent_initiator_id") or entity.initiator_id


# ── OmissionRule 定义 ────────────────────────────────────────────────────────

@dataclass
class OmissionRule:
    """
    通用 omission 规则。

    当 trigger_event_types 中的事件发生时，
    若 entity_types 匹配（空=不限），
    则为 actor_selector 返回的 actor 创建一条 obligation：
    在 due_within_secs 内必须产生 required_event_types 中的任一事件，
    否则触发 violation_code。
    """
    rule_id:             str
    name:                str
    description:         str

    # 触发条件
    trigger_event_types: List[str]        # 哪些 event_type 会触发此规则
    entity_types:        List[str] = field(default_factory=list)  # 空=所有 entity type

    # 义务定义
    actor_selector:      ActorSelectorFn = field(default=_select_current_owner)
    obligation_type:     str = ""         # OmissionType value
    required_event_types:List[str] = field(default_factory=list)

    # 时限
    due_within_secs:     float = 300.0    # 5 分钟默认
    grace_period_secs:   float = 0.0
    hard_overdue_secs:   float = 0.0      # 超过 due_at 多少秒触发 INTERRUPT_GATE（0=禁用）

    # 违规
    violation_code:      str = "omission_violation"
    severity:            Severity = Severity.MEDIUM
    escalation_policy:   EscalationPolicy = field(default_factory=EscalationPolicy.default)

    # 控制
    enabled:             bool = True
    # 如果同类型 obligation 已存在（pending）则跳过（防止重复）
    deduplicate:         bool = True
    # 闭环效果：violation 会阻止 entity 进入 CLOSED 状态
    deny_closure_on_open:bool = False

    def matches_entity_type(self, entity_type: str) -> bool:
        """空 entity_types 列表 = 匹配所有类型。"""
        return not self.entity_types or entity_type in self.entity_types

    def compute_due_at(self, trigger_ts: float) -> float:
        return trigger_ts + self.due_within_secs


# ── 内置 7 条通用规则 ────────────────────────────────────────────────────────
#
# P0 设计原则：
# 内置规则的 due_within_secs 是"保守安全兜底值"，不是部署策略。
# 任何真实生态都应该通过 Domain Pack 覆盖这些值。
# 保守默认值设计原则：宁可漏报，不可误伤。
#
# 宪法守卫：以下常量作为测试断言的参考基准，
# 任何低于此值的默认时限都意味着可能在不加 domain pack 时造成误伤。
KERNEL_SAFE_DEFAULT_DUE_SECS = 3600.0    # 1 小时：无 domain pack 时的安全兜底
KERNEL_SAFE_DEFAULT_VIOLATION_SECS = 1800.0  # 30 分钟：violation 触发的宽限期
KERNEL_REQUIRE_DOMAIN_PACK   = False      # 设为 True 可强制要求接入必须配置 domain pack

def _make_default_escalation(
    reminder_secs: Optional[float] = None,
    escalate_secs: Optional[float] = None,
    deny_closure: bool = False,
    violation_secs: Optional[float] = None,
) -> EscalationPolicy:
    actions = [EscalationAction.VIOLATION]
    if reminder_secs is not None:
        actions.insert(0, EscalationAction.REMINDER)
    if escalate_secs is not None:
        actions.append(EscalationAction.ESCALATE)
    if deny_closure:
        actions.append(EscalationAction.DENY_CLOSURE)
    return EscalationPolicy(
        reminder_after_secs  = reminder_secs,
        violation_after_secs = violation_secs if violation_secs is not None else KERNEL_SAFE_DEFAULT_VIOLATION_SECS,
        escalate_after_secs  = escalate_secs,
        actions              = actions,
        deny_closure_on_open = deny_closure,
    )


# Rule A: 创建后必须 delegation/认领/升级
RULE_DELEGATION = OmissionRule(
    rule_id              = "rule_a_delegation",
    name                 = "Required Delegation",
    description          = (
        "当交互单元被创建后，当前 owner 必须在时限内"
        "发出 delegation / self_ownership / clarification / escalation 之一，"
        "否则触发 required_delegation_omission。"
    ),
    trigger_event_types  = [GEventType.ENTITY_CREATED],
    actor_selector       = _select_current_owner,
    obligation_type      = OmissionType.REQUIRED_DELEGATION.value,
    required_event_types = [
        GEventType.DELEGATION_EVENT,
        GEventType.SELF_OWNERSHIP_EVENT,
        GEventType.CLARIFICATION_EVENT,
        GEventType.ESCALATION_EVENT,
    ],
    due_within_secs      = KERNEL_SAFE_DEFAULT_DUE_SECS,  # conservative fallback, override via domain pack
    violation_code       = OmissionType.REQUIRED_DELEGATION.value,
    severity             = Severity.HIGH,
    escalation_policy    = _make_default_escalation(reminder_secs=180.0, deny_closure=True),
    deny_closure_on_open = True,
)

# Rule B: 被分配 owner 后必须 ack/decline/block
RULE_ACKNOWLEDGEMENT = OmissionRule(
    rule_id              = "rule_b_acknowledgement",
    name                 = "Required Acknowledgement",
    description          = (
        "当某 actor 被指定为 current_owner 后，"
        "必须在时限内发出 acknowledgement / decline / block 之一，"
        "否则触发 required_acknowledgement_omission。"
    ),
    trigger_event_types  = [GEventType.ENTITY_ASSIGNED],
    actor_selector       = _select_current_owner,
    obligation_type      = OmissionType.REQUIRED_ACKNOWLEDGEMENT.value,
    required_event_types = [
        GEventType.ACKNOWLEDGEMENT_EVENT,
        GEventType.DECLINE_EVENT,
        GEventType.BLOCKER_REPORT_EVENT,
    ],
    due_within_secs      = KERNEL_SAFE_DEFAULT_DUE_SECS,  # conservative fallback
    violation_code       = OmissionType.REQUIRED_ACKNOWLEDGEMENT.value,
    severity             = Severity.MEDIUM,
    escalation_policy    = _make_default_escalation(reminder_secs=60.0),
)

# Rule C: ACTIVE 状态下必须定期 status update
RULE_STATUS_UPDATE = OmissionRule(
    rule_id              = "rule_c_status_update",
    name                 = "Required Status Update",
    description          = (
        "当实体处于 ACTIVE/ACKNOWLEDGED 状态时，"
        "obligated actor 必须在时限内发 status_update / blocker_report / completion，"
        "否则触发 required_status_update_omission。"
    ),
    trigger_event_types  = [GEventType.ACKNOWLEDGEMENT_EVENT],
    actor_selector       = _select_current_owner,
    obligation_type      = OmissionType.REQUIRED_STATUS_UPDATE.value,
    required_event_types = [
        GEventType.STATUS_UPDATE_EVENT,
        GEventType.BLOCKER_REPORT_EVENT,
        GEventType.COMPLETION_EVENT,
        GEventType.RESULT_PUBLICATION_EVENT,
    ],
    due_within_secs      = KERNEL_SAFE_DEFAULT_DUE_SECS,  # conservative fallback
    violation_code       = OmissionType.REQUIRED_STATUS_UPDATE.value,
    severity             = Severity.MEDIUM,
    escalation_policy    = _make_default_escalation(reminder_secs=300.0),
)

# Rule D: 有完成证据后必须正式 publish result
RULE_RESULT_PUBLICATION = OmissionRule(
    rule_id              = "rule_d_result_publication",
    name                 = "Required Result Publication",
    description          = (
        "当观察到完成或 artifact/side-effect 证据时，"
        "obligated actor 必须正式发 result_publication / completion 事件，"
        "否则触发 required_result_publication_omission。"
    ),
    trigger_event_types  = [GEventType.RESULT_OBSERVED],
    actor_selector       = _select_current_owner,
    obligation_type      = OmissionType.REQUIRED_RESULT_PUBLICATION.value,
    required_event_types = [
        GEventType.RESULT_PUBLICATION_EVENT,
        GEventType.COMPLETION_EVENT,
    ],
    due_within_secs      = KERNEL_SAFE_DEFAULT_DUE_SECS,  # conservative fallback
    violation_code       = OmissionType.REQUIRED_RESULT_PUBLICATION.value,
    severity             = Severity.HIGH,
    escalation_policy    = _make_default_escalation(escalate_secs=120.0),
)

# Rule E: 下游结果可用后，上游必须发 upstream_notify
RULE_UPSTREAM_NOTIFICATION = OmissionRule(
    rule_id              = "rule_e_upstream_notification",
    name                 = "Required Upstream Notification",
    description          = (
        "当下游结果已经可用（result_publication 发出），"
        "若上游责任主体未在时限内发 upstream_notify_event，"
        "则触发 required_upstream_notification_omission。"
    ),
    trigger_event_types  = [GEventType.RESULT_PUBLICATION_EVENT],
    actor_selector       = _select_initiator,   # 上游 = initiator
    obligation_type      = OmissionType.REQUIRED_UPSTREAM_NOTIFICATION.value,
    required_event_types = [
        GEventType.UPSTREAM_NOTIFY_EVENT,
        GEventType.CLOSURE_EVENT,
    ],
    due_within_secs      = KERNEL_SAFE_DEFAULT_DUE_SECS,  # conservative fallback
    violation_code       = OmissionType.REQUIRED_UPSTREAM_NOTIFICATION.value,
    severity             = Severity.MEDIUM,
    escalation_policy    = _make_default_escalation(reminder_secs=120.0),
)

# Rule F: 已知 blocker/exception 后必须 escalate
RULE_ESCALATION = OmissionRule(
    rule_id              = "rule_f_escalation",
    name                 = "Required Escalation",
    description          = (
        "当系统检测到 blocker / exception 状态，"
        "obligated actor 必须在时限内发 escalation_event，"
        "否则触发 required_escalation_omission。"
    ),
    trigger_event_types  = [GEventType.ENTITY_BLOCKED, GEventType.BLOCKER_DETECTED],
    actor_selector       = _select_current_owner,
    obligation_type      = OmissionType.REQUIRED_ESCALATION.value,
    required_event_types = [
        GEventType.ESCALATION_EVENT,
        GEventType.BLOCKER_REPORT_EVENT,
    ],
    due_within_secs      = KERNEL_SAFE_DEFAULT_DUE_SECS,  # conservative fallback
    violation_code       = OmissionType.REQUIRED_ESCALATION.value,
    severity             = Severity.HIGH,
    escalation_policy    = _make_default_escalation(
        reminder_secs=60.0, escalate_secs=180.0, deny_closure=True
    ),
    deny_closure_on_open = True,
)

# Rule G: 满足 closure prerequisites 后必须 close
RULE_CLOSURE = OmissionRule(
    rule_id              = "rule_g_closure",
    name                 = "Required Closure",
    description          = (
        "当实体满足 closure prerequisites（上游已 notify）后，"
        "obligated actor 必须在时限内发 closure_event，"
        "否则触发 required_closure_omission。"
    ),
    trigger_event_types  = [GEventType.CLOSURE_PREREQ_MET, GEventType.UPSTREAM_NOTIFY_EVENT],
    actor_selector       = _select_initiator,
    obligation_type      = OmissionType.REQUIRED_CLOSURE.value,
    required_event_types = [GEventType.CLOSURE_EVENT],
    due_within_secs      = KERNEL_SAFE_DEFAULT_DUE_SECS,  # conservative fallback
    violation_code       = OmissionType.REQUIRED_CLOSURE.value,
    severity             = Severity.LOW,
    escalation_policy    = _make_default_escalation(reminder_secs=200.0),
)

# 内置规则集合（按优先级顺序）
BUILTIN_RULES: List[OmissionRule] = [
    RULE_DELEGATION,
    RULE_ACKNOWLEDGEMENT,
    RULE_STATUS_UPDATE,
    RULE_RESULT_PUBLICATION,
    RULE_UPSTREAM_NOTIFICATION,
    RULE_ESCALATION,
    RULE_CLOSURE,
]


# ── RuleRegistry —— domain pack 扩展点 ──────────────────────────────────────

class RuleRegistry:
    """
    全局规则注册表。
    内置规则已预加载；domain pack 可通过 register() 添加自定义规则。

    重要：每次初始化时对内置规则做深拷贝，确保各 registry 实例相互独立，
    domain pack 修改不会污染 BUILTIN_RULES 全局对象。
    """

    def __init__(self) -> None:
        import copy
        self._rules: Dict[str, OmissionRule] = {}
        for r in BUILTIN_RULES:
            self._rules[r.rule_id] = copy.deepcopy(r)

    def register(self, rule: OmissionRule) -> None:
        """注册自定义规则（覆盖同 rule_id 的已有规则）。"""
        self._rules[rule.rule_id] = rule

    def unregister(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    def get(self, rule_id: str) -> Optional[OmissionRule]:
        return self._rules.get(rule_id)

    def all_enabled(self) -> List[OmissionRule]:
        return [r for r in self._rules.values() if r.enabled]

    def rules_for_trigger(self, event_type: str) -> List[OmissionRule]:
        """返回被某个 event_type 触发的所有已启用规则。"""
        return [
            r for r in self.all_enabled()
            if event_type in r.trigger_event_types
        ]

    def override_timing(
        self,
        rule_id: str,
        due_within_secs: float,
        grace_period_secs: float = 0.0,
        hard_overdue_secs: float = 0.0,
    ) -> None:
        """
        Domain pack 用于覆盖内置规则的时限。
        例：finance domain pack 把 delegation 时限从 5 分钟改成 30 秒。
        hard_overdue_secs=0 表示禁用 INTERRUPT_GATE（不阻断），需要 domain pack 显式设置。
        """
        rule = self._rules.get(rule_id)
        if rule:
            rule.due_within_secs   = due_within_secs
            rule.grace_period_secs = grace_period_secs
            rule.hard_overdue_secs = hard_overdue_secs

    def disable(self, rule_id: str) -> None:
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = False

    def enable(self, rule_id: str) -> None:
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = True

    def summary(self) -> List[dict]:
        return [
            {
                "rule_id":         r.rule_id,
                "name":            r.name,
                "enabled":         r.enabled,
                "trigger_events":  r.trigger_event_types,
                "obligation_type": r.obligation_type,
                "due_within_secs": r.due_within_secs,
                "severity":        r.severity.value,
            }
            for r in self._rules.values()
        ]


# ── 全局默认 registry ─────────────────────────────────────────────────────────
_default_registry: Optional[RuleRegistry] = None


def get_registry() -> RuleRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = RuleRegistry()
    return _default_registry


def reset_registry() -> RuleRegistry:
    """测试用：重置到全新状态。"""
    global _default_registry
    _default_registry = RuleRegistry()
    return _default_registry

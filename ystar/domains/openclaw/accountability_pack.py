"""
ystar.domains.openclaw.accountability_pack
==========================================
v0.41.0

OpenClaw 协作治理策略包（Domain Pack）

这是 P2 的核心修复：
把 OpenClaw 特有的治理策略从 adapter 中分离出来，
放到正确的层——Domain Pack。

Adapter (adapter.py) 的职责：翻译 + 绑定 + 诊断
Domain Pack 的职责：时限 / 严重度 / 升级策略 / 协作期望

使用方式：
    from ystar.domains.openclaw.accountability_pack import (
        apply_openclaw_accountability_pack,
        OPENCLAW_GATING_POLICY,
    )

    registry = reset_registry()
    apply_openclaw_accountability_pack(registry)  # 应用协作策略
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ystar.governance.omission_rules import RuleRegistry
    from ystar.governance.intervention_engine import GatingPolicy


# ── OpenClaw GatingPolicy（从 adapter 层分离到此处）────────────────────────────

def make_openclaw_gating_policy() -> "GatingPolicy":
    """
    构造 OpenClaw 生态专用的 GatingPolicy。

    这是 P0 清理后的正确位置：
    - 生态专有动作名称（"subagent_spawn"等）属于 Domain Pack 知识
    - 不是 InterventionEngine 的内置知识
    - 不是 adapter.py 的私有方法

    调用方（如 configure_intervention_engine）应从此处获取策略，
    而不是在 adapter 层重新定义。
    """
    from ystar.governance.intervention_engine import DEFAULT_GATING_POLICY
    return DEFAULT_GATING_POLICY.extend(
        # OpenClaw 义务履行类动作（永远 ALLOW，无论 actor 有无 overdue）
        fulfillment={
            "task_acked",
            "task_declined",
            "status_update",
            "blocker_detected",
            "result_published",
            "result_ready",
            "upstream_summary",
            "escalation",
            "task_closed",
            "task_completed",
        },
        # OpenClaw 高风险动作（actor 有 hard_overdue 时 DENY）
        high_risk={
            "subagent_spawn",
            "handoff",
            "file_write",
            "cmd_exec",
            "code_exec",
            "skill_install",
            "mcp_tool_call",
        },
    )


# 模块级单例（缓存，避免重复构造）
OPENCLAW_GATING_POLICY: Optional["GatingPolicy"] = None


def get_openclaw_gating_policy() -> "GatingPolicy":
    """获取（或初始化）OpenClaw GatingPolicy 单例。"""
    global OPENCLAW_GATING_POLICY
    if OPENCLAW_GATING_POLICY is None:
        OPENCLAW_GATING_POLICY = make_openclaw_gating_policy()
    return OPENCLAW_GATING_POLICY


# STANDARD_GATING_POLICY — 对外公开的标准策略（推荐用于不带 Domain Pack 的场景）
# 与 OPENCLAW_GATING_POLICY 等价，提供更通用的名称方便 InterventionEngine 注入。
def get_standard_gating_policy() -> "GatingPolicy":
    """
    获取标准 GatingPolicy（包含 OpenClaw 生态动作的扩展版本）。

    用途：
        engine = InterventionEngine(gating_policy=get_standard_gating_policy())

    相比 DEFAULT_GATING_POLICY（纯内核语义），这个版本加入了
    subagent_spawn / file_write / cmd_exec 等常见高风险动作，
    使不带完整 Domain Pack 的场景也能正确 DENY hard_overdue actor。
    """
    return get_openclaw_gating_policy()


# 模块级常量（方便 import）
STANDARD_GATING_POLICY: Optional["GatingPolicy"] = None


def _init_standard_policy() -> None:
    global STANDARD_GATING_POLICY
    try:
        STANDARD_GATING_POLICY = make_openclaw_gating_policy()
    except Exception:
        pass


_init_standard_policy()


# ── OpenClaw 协作治理时限策略 ─────────────────────────────────────────────────

# obligation_timing 键名 → 规则 ID 的映射
# 用户在 AGENTS.md 里写的义务时限键，对应到哪条规则
_OBLIGATION_KEY_TO_RULE: dict = {
    "delegation":           "rule_a_delegation",
    "acknowledgement":      "rule_b_acknowledgement",
    "status_update":        "rule_c_status_update",
    "result_publication":   "rule_d_result_publication",
    "upstream_notification":"rule_e_upstream_notification",
    "escalation":           "rule_f_escalation",
    "closure":              "rule_g_closure",
    # 自然别名
    "ack":                  "rule_b_acknowledgement",
    "complete":             "rule_c_status_update",
    "completion":           "rule_c_status_update",
    "notify":               "rule_e_upstream_notification",
    "close":                "rule_g_closure",
}

# 兜底常量（仅在合约未指定时使用，且必须明确标注来源）
# 不是"正确的时限"，是"没有用户配置时不崩溃的最小值"
_FALLBACK_TIMING = {
    "rule_a_delegation":           {"due_within_secs": 300.0,  "grace": 30.0,  "hard_overdue_secs": 300.0},
    "rule_b_acknowledgement":      {"due_within_secs": 120.0,  "grace": 15.0,  "hard_overdue_secs": 120.0},
    "rule_c_status_update":        {"due_within_secs": 600.0,  "grace": 60.0,  "hard_overdue_secs": 600.0},
    "rule_d_result_publication":   {"due_within_secs": 180.0,  "grace": 20.0,  "hard_overdue_secs": 180.0},
    "rule_e_upstream_notification":{"due_within_secs": 300.0,  "grace": 30.0,  "hard_overdue_secs": 300.0},
    "rule_f_escalation":           {"due_within_secs": 120.0,  "grace": 10.0,  "hard_overdue_secs": 120.0},
    "rule_g_closure":              {"due_within_secs": 600.0,  "grace": 60.0,  "hard_overdue_secs": 600.0},
}

_FALLBACK_TIMING_STRICT = {
    "rule_a_delegation":           {"due_within_secs": 60.0,   "grace": 10.0,  "hard_overdue_secs": 60.0},
    "rule_b_acknowledgement":      {"due_within_secs": 30.0,   "grace": 5.0,   "hard_overdue_secs": 30.0},
    "rule_c_status_update":        {"due_within_secs": 180.0,  "grace": 20.0,  "hard_overdue_secs": 180.0},
    "rule_d_result_publication":   {"due_within_secs": 60.0,   "grace": 10.0,  "hard_overdue_secs": 60.0},
    "rule_e_upstream_notification":{"due_within_secs": 120.0,  "grace": 15.0,  "hard_overdue_secs": 120.0},
    "rule_f_escalation":           {"due_within_secs": 60.0,   "grace": 5.0,   "hard_overdue_secs": 60.0},
    "rule_g_closure":              {"due_within_secs": 300.0,  "grace": 30.0,  "hard_overdue_secs": 300.0},
}

# 向后兼容名（代码里可能还有 import）
OPENCLAW_TIMING        = _FALLBACK_TIMING
OPENCLAW_TIMING_STRICT = _FALLBACK_TIMING_STRICT


def _contract_to_timing(contract) -> dict:
    """
    从 IntentContract.obligation_timing 提取规则时限覆盖配置。

    这是时限的正确来源：用户在 AGENTS.md 里定义，
    LLM 翻译成 obligation_timing，这里读出来应用到规则上。

    返回：{rule_id: {"due_within_secs": N, "grace": M, "hard_overdue_secs": N}}
    """
    if contract is None:
        return {}
    ot = getattr(contract, "obligation_timing", None) or {}
    if not ot:
        return {}

    result = {}
    for key, secs in ot.items():
        rule_id = _OBLIGATION_KEY_TO_RULE.get(key, key)
        if rule_id and isinstance(secs, (int, float)) and secs > 0:
            grace = max(secs * 0.1, 5.0)   # 宽限期 = 10%，最少5秒
            result[rule_id] = {
                "due_within_secs":   float(secs),
                "grace":             round(grace, 1),
                "hard_overdue_secs": float(secs),
            }
    return result


def apply_openclaw_accountability_pack(
    registry:    "RuleRegistry",
    strict:      bool = False,
    escalate_to: Optional[str] = "principal",
    contract     = None,   # IntentContract（有则优先读取 obligation_timing）
) -> None:
    """
    应用 OpenClaw 协作责任制 Domain Pack。

    时限优先级（高 → 低）：
      1. contract.obligation_timing（用户在 AGENTS.md 里定义的，最权威）
      2. _FALLBACK_TIMING / _FALLBACK_TIMING_STRICT（无用户配置时的兜底）

    Args:
        registry:    OmissionRuleRegistry
        strict:      True = 使用 strict 兜底时限
        escalate_to: 升级目标 actor
        contract:    IntentContract（从 ystar init 加载，含用户定义的时限）
    """
    # ── 1. 从合约读用户定义的时限（最高优先级）────────────────────────
    contract_timing = _contract_to_timing(contract)

    # ── 2. 兜底时限（仅覆盖合约未指定的规则）────────────────────────
    fallback = _FALLBACK_TIMING_STRICT if strict else _FALLBACK_TIMING

    # ── 3. 合并：合约定义优先，兜底补全剩余 ─────────────────────────
    final_timing = {**fallback, **contract_timing}  # contract 覆盖 fallback

    for rule_id, t in final_timing.items():
        try:
            registry.override_timing(
                rule_id,
                due_within_secs   = t["due_within_secs"],
                grace_period_secs = t.get("grace", 0.0),
                hard_overdue_secs = t.get("hard_overdue_secs", 0.0),
            )
        except (KeyError, AttributeError):
            pass

    # ── 4. 高严重度规则的升级目标 ────────────────────────────────────
    if escalate_to:
        for rule_id in ("rule_a_delegation", "rule_f_escalation"):
            try:
                rule = registry.get(rule_id)
                if rule and rule.escalation_policy:
                    rule.escalation_policy.escalate_to = escalate_to
            except (KeyError, AttributeError):
                pass



# ── 元信息 ────────────────────────────────────────────────────────────────────

PACK_INFO = {
    "name":        "openclaw_accountability",
    "version":     "0.36.1",
    "description": "OpenClaw multi-agent collaboration accountability governance",
    "layer":       "domain_pack",
    "timing_mode": "standard / strict",
    "author":      "Y* governance team",
}


# ── ATLAS 预训练义务规则 ────────────────────────────────────────────────────
# 从 MITRE ATLAS v4.5 缓解措施提炼（8条，2026-03）
_ATLAS_OBLIGATION_RULES = [
    {"rule_id": "atlas_aml_m0005", "trigger_event": "autonomous_action", "obligation_type": "escalation", "due_within_secs": 60.0, "source": "AML.M0005"},
    {"rule_id": "atlas_aml_m0007", "trigger_event": "skill_install", "obligation_type": "completion", "due_within_secs": 1800.0, "source": "AML.M0007"},
    {"rule_id": "atlas_aml_m0008", "trigger_event": "high_risk_action", "obligation_type": "acknowledgement", "due_within_secs": 120.0, "source": "AML.M0008"},
    {"rule_id": "atlas_aml_m0014", "trigger_event": "skill_install", "obligation_type": "completion", "due_within_secs": 1800.0, "source": "AML.M0014"},
    {"rule_id": "atlas_aml_m0018", "trigger_event": "skill_install", "obligation_type": "completion", "due_within_secs": 1800.0, "source": "AML.M0018"},
    {"rule_id": "atlas_aml_m0019", "trigger_event": "autonomous_action", "obligation_type": "escalation", "due_within_secs": 60.0, "source": "AML.M0019"},
    {"rule_id": "atlas_aml_m0024", "trigger_event": "high_risk_action", "obligation_type": "acknowledgement", "due_within_secs": 120.0, "source": "AML.M0024"},
    {"rule_id": "atlas_aml_m0029", "trigger_event": "autonomous_action", "obligation_type": "escalation", "due_within_secs": 60.0, "source": "AML.M0029"},
]

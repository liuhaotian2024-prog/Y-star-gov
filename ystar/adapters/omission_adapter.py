"""
ystar.omission_adapter  —  OpenClaw / Y* → Omission Governance Adapter
======================================================================

把现有 OpenClaw / Y* 风格事件翻译成 omission governance 层可消费的结构。

核心逻辑：
  OpenClawEvent / raw dict  →  TrackedEntity + GovernanceEvent → engine.ingest_event()

分层原则：
  - adapter 可以有 scenario-specific mapping（知道 OpenClaw 事件含义）
  - core omission engine 保持 scenario-agnostic（只认 GovernanceEvent 结构）

支持两种调用模式：
  1. 实时适配：每次 OpenClaw 事件到来时调用 adapt_and_ingest()
  2. 批量回放：把历史 CIEU log 翻译后批量注入（用于测试和 replay）
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ystar.governance.omission_models import (
    EntityStatus, GEventType, TrackedEntity, GovernanceEvent,
)
from ystar.governance.omission_engine import OmissionEngine, EngineResult


# ── OpenClaw 事件类型 → GovernanceEvent type 映射 ────────────────────────────

_OPENCLAW_TO_GOV: Dict[str, str] = {
    # 触发类 → entity lifecycle
    "session_start":    GEventType.ENTITY_CREATED,
    "subagent_spawn":   GEventType.ENTITY_CREATED,
    "handoff":          GEventType.ENTITY_ASSIGNED,

    # 履行类 → fulfillment events
    "task_delegated":   GEventType.DELEGATION_EVENT,
    "task_acked":       GEventType.ACKNOWLEDGEMENT_EVENT,
    "task_declined":    GEventType.DECLINE_EVENT,
    "status_update":    GEventType.STATUS_UPDATE_EVENT,
    "blocker_detected": GEventType.BLOCKER_REPORT_EVENT,
    "result_ready":     GEventType.RESULT_OBSERVED,
    "result_published": GEventType.RESULT_PUBLICATION_EVENT,
    "upstream_summary": GEventType.UPSTREAM_NOTIFY_EVENT,
    "escalation":       GEventType.ESCALATION_EVENT,
    "task_closed":      GEventType.CLOSURE_EVENT,
    "task_completed":   GEventType.COMPLETION_EVENT,
    "agent_terminate":  GEventType.CLOSURE_EVENT,
}

# Y* 内部事件到 governance event 的映射
_YSTAR_TO_GOV: Dict[str, str] = {
    "check_deny":        GEventType.BLOCKER_DETECTED,
    "check_escalate":    GEventType.ESCALATION_EVENT,
    "delegation_create": GEventType.ENTITY_ASSIGNED,
    "delegation_accept": GEventType.ACKNOWLEDGEMENT_EVENT,
    "delegation_reject": GEventType.DECLINE_EVENT,

    # ── 自然语言别名（用户最直觉的事件名）──────────────────────────────
    # 任务创建 → 触发 delegation 义务（manager 必须分配）
    "task_created":      GEventType.ENTITY_CREATED,
    "task_started":      GEventType.ENTITY_CREATED,
    "task_open":         GEventType.ENTITY_CREATED,
    "new_task":          GEventType.ENTITY_CREATED,

    # 任务分配 → 触发 acknowledgement 义务（worker 必须确认）
    "task_assigned":     GEventType.ENTITY_ASSIGNED,
    "task_dispatched":   GEventType.ENTITY_ASSIGNED,

    # 任务确认 → 履行 acknowledgement
    "task_accepted":     GEventType.ACKNOWLEDGEMENT_EVENT,
    "task_ack":          GEventType.ACKNOWLEDGEMENT_EVENT,

    # 进度更新 → 履行 status_update 义务
    "task_update":       GEventType.STATUS_UPDATE_EVENT,
    "progress_update":   GEventType.STATUS_UPDATE_EVENT,
    "status_report":     GEventType.STATUS_UPDATE_EVENT,

    # 任务完成 → 履行 completion 义务
    "task_done":         GEventType.COMPLETION_EVENT,
    "task_finished":     GEventType.COMPLETION_EVENT,
    "task_completed":    GEventType.COMPLETION_EVENT,
    "task_success":      GEventType.COMPLETION_EVENT,

    # 任务关闭/归档 → 触发 closure 义务
    "task_closed":       GEventType.CLOSURE_EVENT,
    "task_archived":     GEventType.CLOSURE_EVENT,

    # 任务失败/阻塞 → 触发 escalation
    "task_failed":       GEventType.BLOCKER_REPORT_EVENT,
    "task_blocked":      GEventType.BLOCKER_REPORT_EVENT,
    "blocker":           GEventType.BLOCKER_REPORT_EVENT,

    # 结果发布
    "result_ready":      GEventType.RESULT_OBSERVED,
    "result_done":       GEventType.RESULT_OBSERVED,
    "task_result":       GEventType.RESULT_PUBLICATION_EVENT,
}


# ── 履行类事件集合（不会创建新 entity，只会 fulfill 已有 obligation）─────────
_FULFILLMENT_EVENT_TYPES: set = {
    "task_delegated", "task_acked", "task_declined",
    "status_update", "blocker_detected",
    "result_ready", "result_published",
    "upstream_summary", "escalation",
    "task_closed", "task_completed",
    "agent_terminate",
}

# 上游通知类事件（由 initiator/manager 发出，需要找子任务 entity）
_UPSTREAM_EVENT_TYPES: set = {"upstream_summary"}

# Manager 发出的履行类事件（routing via __latest_child_of_ cache）
# 这些事件由 parent/manager agent 发出，但目标是 child entity
_MANAGER_FULFILLMENT_EVENT_TYPES: set = {"task_delegated", "upstream_summary"}

# ── 辅助：从事件推断 entity_type ─────────────────────────────────────────────

def _infer_entity_type(raw_event_type: str, payload: dict) -> str:
    if "spawn" in raw_event_type or "subagent" in raw_event_type:
        return "subagent_task"
    if "handoff" in raw_event_type:
        return "handoff"
    if "session" in raw_event_type:
        return "session"
    return payload.get("entity_type", "task")


# ── 主 Adapter 类 ─────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# P0-2: Adapter 诊断 API
# 在注入事件前先判断失败模式，让调用方知道这是"治理失败"还是"接线失败"
# ══════════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass as _adc, field as _afield
from enum import Enum as _Enum

class BindingFailureMode(_Enum):
    """
    接入语义失败模式分类。
    这是 P0 的核心：让系统能清楚区分"规则问题"和"接线问题"。
    """
    OK                   = "ok"
    UNKNOWN_EVENT_TYPE   = "unknown_event_type"    # 无法映射到 GovernanceEvent
    MISSING_ENTITY_ID    = "missing_entity_id"     # entity_id 无法解析
    UNKNOWN_ACTOR        = "unknown_actor"          # actor_id 未在缓存中注册
    MISSING_LINEAGE      = "missing_lineage"        # 子任务无法追溯 root
    ORPHAN_FULFILLMENT   = "orphan_fulfillment"     # fulfillment 事件找不到匹配义务


@_adc
class DiagnosticResult:
    """
    一次事件注入前的诊断结果。
    failure_mode=OK 表示接线语义正常，事件可安全注入。
    failure_mode!=OK 表示接线层问题，与治理规则无关。
    """
    failure_mode:    BindingFailureMode = BindingFailureMode.OK
    raw_event_type:  str = ""
    resolved_entity_id: Optional[str] = None
    resolved_actor_id:  Optional[str] = None
    gov_event_type:     Optional[str] = None
    warnings:           List[str] = _afield(default_factory=list)
    suggestion:         str = ""    # 给 adapter 层的修复建议（不是给治理引擎的）

    @property
    def ok(self) -> bool:
        return self.failure_mode == BindingFailureMode.OK

    def to_dict(self) -> dict:
        return {
            "failure_mode":       self.failure_mode.value,
            "raw_event_type":     self.raw_event_type,
            "resolved_entity_id": self.resolved_entity_id,
            "resolved_actor_id":  self.resolved_actor_id,
            "gov_event_type":     self.gov_event_type,
            "warnings":           self.warnings,
            "suggestion":         self.suggestion,
            "ok":                 self.ok,
        }


class OmissionAdapter:
    """
    OpenClaw / Y* 事件流 → Omission Governance Engine 适配器。

    使用方式：
        adapter = OmissionAdapter(engine)

        # OpenClaw 事件字典
        adapter.ingest_raw({
            "event_type": "subagent_spawn",
            "agent_id":   "agent-A",
            "session_id": "sess-1",
            "child_agent_id": "agent-B",
            "task_description": "analyze data",
        })

        # 或直接用 OpenClawEvent 对象
        adapter.ingest_openclaw_event(openclaw_ev)
    """

    def __init__(
        self,
        engine: OmissionEngine,
        default_owner: str = "system",
    ) -> None:
        self.engine = engine
        self.default_owner = default_owner
        # entity_id → root_entity_id 的缓存（lineage 构建）
        self._lineage_cache: Dict[str, str] = {}
        # agent_id → entity_id 的缓存（履行事件路由关键）
        # 当 subagent_spawn / handoff 创建 child entity 时，记录：
        #   child_agent_id → entity_id（worker 回写 ack/status/result 时用）
        #   parent_agent_id → entity_id（manager 回写 upstream_summary 时用）
        self._agent_to_entity: Dict[str, str] = {}

    # ── 公共接口 ──────────────────────────────────────────────────────────────

    def ingest_raw(
        self,
        raw: Dict[str, Any],
        source: str = "openclaw",
    ) -> EngineResult:
        """
        接收原始事件字典，翻译后注入 engine。
        raw 格式遵循 OpenClaw OpenClawEvent 字段。

        对于 subagent_spawn 事件，自动触发双事件：
          1. entity_created  (actor=parent/manager) → delegation obligation for manager
          2. entity_assigned (actor=child/worker)   → acknowledgement obligation for worker
        这样 task_delegated 和 task_acked 都能正确 fulfill 对应义务。
        """
        raw_type = str(raw.get("event_type", ""))

        # ── subagent_spawn：双事件触发 ────────────────────────────────────
        # Connection 7: validate delegation monotonicity on spawn
        if raw_type in ("subagent_spawn", "handoff"):
            mono_error = self._validate_delegation_monotonicity(raw)
            if mono_error:
                # Record as a governance event — doesn't block, but is auditable
                from ystar.governance.omission_models import GovernanceEvent, GEventType
                warn_ev = GovernanceEvent(
                    event_type = "delegation_monotonicity_warning",
                    entity_id  = raw.get("session_id", "unknown"),
                    actor_id   = raw.get("agent_id", "unknown"),
                    ts         = raw.get("timestamp", 0.0),
                    payload    = {"error": mono_error, "raw_type": raw_type},
                    source     = source,
                )
                self.engine.store.add_event(warn_ev)

        if raw_type == "subagent_spawn":
            return self._ingest_spawn_dual(raw, source)

        entity, gov_ev = self._translate(raw, source)
        if gov_ev is None:
            return EngineResult()

        if entity is not None:
            self.engine.register_entity(entity)

        return self.engine.ingest_event(gov_ev)

    def _validate_delegation_monotonicity(self, raw: Dict[str, Any]) -> Optional[str]:
        """
        Connection 7: DelegationChain.validate() — delegation monotonicity check.
        When a spawn/handoff occurs, verify the delegation chain doesn't expand
        permissions beyond what the parent had.
        Returns an error string if monotonicity is violated, None if clean.
        """
        try:
            from ystar.kernel.dimensions import DelegationChain, DelegationContract, IntentContract
            parent = raw.get("parent_agent_id") or raw.get("agent_id", "")
            child  = raw.get("child_agent_id", "")
            if not parent or not child:
                return None

            # Build a minimal DelegationContract for this spawn
            parent_contract = IntentContract(name=f"parent_{parent}")
            child_contract  = IntentContract(name=f"child_{child}")

            parent_link = DelegationContract(
                principal=parent, actor=parent,
                contract=parent_contract,
            )
            child_link = DelegationContract(
                principal=parent, actor=child,
                contract=child_contract,
            )
            chain = DelegationChain()
            chain.append(parent_link)
            chain.append(child_link)
            errors = chain.validate()
            if errors:
                return f"DelegationChain violation: {'; '.join(errors[:2])}"
            return None
        except Exception:
            return None  # don't block on validation errors

    def _ingest_spawn_dual(self, raw: Dict[str, Any], source: str) -> EngineResult:
        """
        subagent_spawn 的双事件处理：
          事件 1: entity_created, actor=parent_agent → rule_a_delegation 触发 (for manager)
          事件 2: entity_assigned, actor=child_agent → rule_b_acknowledgement 触发 (for worker)

        语义：manager spawn 就是"创建 + 即时分配"，两个义务同时产生。
        """
        combined = EngineResult()

        # task_ticket_id 优先作为 canonical entity_id（调用方明确指定）
        # child_agent_id 仍注册进缓存（供无 ticket 的 ack/status 路由用）
        ticket_id  = str(raw.get("task_ticket_id") or "")
        child_agent= str(raw.get("child_agent_id") or "")
        child_id   = ticket_id or child_agent
        parent_id  = str(raw.get("parent_agent_id") or raw.get("agent_id") or "")
        session_id = str(raw.get("session_id", ""))
        ts         = float(raw.get("timestamp", time.time()))

        if not child_id:
            # fallback: treat as normal spawn
            entity, gov_ev = self._translate(raw, source)
            if gov_ev is None:
                return combined
            if entity is not None:
                self.engine.register_entity(entity)
            return self.engine.ingest_event(gov_ev)

        # 1. 建立 lineage 缓存（在 _resolve_entity_id 之前）
        root = self._lineage_cache.get(session_id, session_id)
        self._lineage_cache[child_id] = root
        # child_id（canonical）→ entity
        self._agent_to_entity[child_id] = child_id
        # child_agent（如果与 child_id 不同）也映射过来
        if child_agent and child_agent != child_id:
            self._agent_to_entity[child_agent] = child_id
            self._lineage_cache[child_agent] = root
        if parent_id:
            self._agent_to_entity[f"__latest_child_of_{parent_id}"] = child_id

        # 2. 建立/更新 entity（current_owner = child，initiator = parent）
        existing = self.engine.store.get_entity(child_id)
        if existing is None:
            from ystar.governance.omission_models import EntityStatus as _ES
            entity = TrackedEntity(
                entity_id         = child_id,
                entity_type       = _infer_entity_type("subagent_spawn", raw),
                initiator_id      = parent_id,
                current_owner_id  = child_id,      # worker owns it
                status            = _ES.ASSIGNED,  # already assigned to child
                goal_summary      = str(raw.get("task_description", "")),
                parent_entity_id  = parent_id,
                root_entity_id    = root,
                lineage           = [root, child_id] if root != child_id else [child_id],
                created_at        = ts,
                updated_at        = ts,
            )
            self.engine.register_entity(entity)

        # 3. 事件 1: entity_created, actor=parent → delegation obligation for manager
        ev_created = GovernanceEvent(
            event_type  = GEventType.ENTITY_CREATED,
            entity_id   = child_id,
            actor_id    = parent_id,
            ts          = ts,
            payload     = {"spawn": True, "parent": parent_id, "child": child_id},
            source      = source,
            lineage_ref = root,
        )
        r1 = self.engine.ingest_event(ev_created)
        combined.new_obligations.extend(r1.new_obligations)
        combined.fulfilled.extend(r1.fulfilled)

        # 4. 事件 2: entity_assigned, actor=child → acknowledgement obligation for worker
        ev_assigned = GovernanceEvent(
            event_type  = GEventType.ENTITY_ASSIGNED,
            entity_id   = child_id,
            actor_id    = child_id,    # worker is the one who needs to ack
            ts          = ts,
            payload     = {"spawn_assign": True, "parent": parent_id},
            source      = source,
            lineage_ref = root,
        )
        r2 = self.engine.ingest_event(ev_assigned)
        combined.new_obligations.extend(r2.new_obligations)
        combined.fulfilled.extend(r2.fulfilled)

        return combined

    def ingest_openclaw_event(
        self,
        event: Any,   # OpenClawEvent 对象，避免循环 import 用 Any
        source: str = "openclaw",
    ) -> EngineResult:
        """接收 OpenClawEvent 对象。"""
        raw = {
            "event_type":       getattr(event, "event_type", "").value
                                if hasattr(getattr(event, "event_type", ""), "value")
                                else str(getattr(event, "event_type", "")),
            "agent_id":         getattr(event, "agent_id", ""),
            "session_id":       getattr(event, "session_id", ""),
            "timestamp":        getattr(event, "timestamp", time.time()),
            "parent_agent_id":  getattr(event, "parent_agent_id", None),
            "child_agent_id":   getattr(event, "child_agent_id", None),
            "task_description": getattr(event, "task_description", None),
            "task_ticket_id":   getattr(event, "task_ticket_id", None),
            "action_scope":     getattr(event, "action_scope", []),
        }
        return self.ingest_raw(raw, source)

    def ingest_ystar_check_result(
        self,
        entity_id: str,
        actor_id: str,
        event_type_raw: str,
        decision: str,
        payload: Optional[Dict] = None,
    ) -> EngineResult:
        """
        把 Y* check() 结果翻译为 governance event。
        decision = "deny" / "escalate" 时触发相关 omission 规则。
        """
        gov_type = _YSTAR_TO_GOV.get(
            f"check_{decision}",
            _YSTAR_TO_GOV.get(event_type_raw, GEventType.STATUS_UPDATE_EVENT),
        )
        ev = GovernanceEvent(
            event_type  = gov_type,
            entity_id   = entity_id,
            actor_id    = actor_id,
            ts          = time.time(),
            payload     = payload or {"decision": decision, "event_type_raw": event_type_raw},
            source      = "ystar_check",
        )
        entity = self.engine.store.get_entity(entity_id)
        if entity is None:
            entity = TrackedEntity(
                entity_id       = entity_id,
                entity_type     = "ystar_task",
                initiator_id    = actor_id,
                current_owner_id= actor_id,
                status          = EntityStatus.ACTIVE,
            )
            self.engine.register_entity(entity)
        return self.engine.ingest_event(ev)

    def batch_ingest(
        self,
        events: List[Dict[str, Any]],
        source: str = "replay",
    ) -> List[EngineResult]:
        """批量注入历史事件（用于 replay 和测试）。"""
        return [self.ingest_raw(e, source) for e in events]

    # ── P0-2: 诊断 API ────────────────────────────────────────────────────────

    def diagnose_event(self, raw: Dict[str, Any]) -> DiagnosticResult:
        """
        在注入事件之前先诊断接入语义，不实际注入。

        返回 DiagnosticResult：
          failure_mode=OK              → 可安全注入
          failure_mode=UNKNOWN_EVENT_TYPE  → 该事件类型无法映射，会被静默忽略
          failure_mode=MISSING_ENTITY_ID   → entity_id 无法解析，会 fallback 到 session
          failure_mode=UNKNOWN_ACTOR       → actor 未注册，fulfillment 会路由错误
          failure_mode=ORPHAN_FULFILLMENT  → 有义务类型事件但没有对应 pending obligation

        这是治理失败 vs 接线失败的分界线：
          治理失败 → 去看 engine.scan() 的 violations
          接线失败 → 去看这里的 DiagnosticResult
        """
        raw_type   = str(raw.get("event_type", ""))
        agent_id   = str(raw.get("agent_id", "unknown"))
        session_id = str(raw.get("session_id", ""))
        ticket_id  = raw.get("task_ticket_id")
        warnings   = []

        # 1. 事件类型是否可映射
        gov_type = (
            _OPENCLAW_TO_GOV.get(raw_type)
            or _YSTAR_TO_GOV.get(raw_type)
        )
        if gov_type is None:
            return DiagnosticResult(
                failure_mode    = BindingFailureMode.UNKNOWN_EVENT_TYPE,
                raw_event_type  = raw_type,
                suggestion      = (
                    f"'{raw_type}' is not in the event mapping. "
                    f"Add it to _OPENCLAW_TO_GOV in omission_adapter.py, "
                    f"or check for typos. Known types: {sorted(_OPENCLAW_TO_GOV)[:5]}..."
                ),
            )

        # 2. entity_id 解析质量
        resolved_entity = None
        routing_source  = "unknown"

        if ticket_id:
            resolved_entity = str(ticket_id)
            routing_source  = "task_ticket_id"
        elif raw_type in ("subagent_spawn", "handoff"):
            child = raw.get("child_agent_id")
            resolved_entity = str(child) if child else None
            routing_source  = "child_agent_id"
        elif raw_type in _FULFILLMENT_EVENT_TYPES:
            cached = self._agent_to_entity.get(agent_id)
            if cached:
                resolved_entity = cached
                routing_source  = "agent_to_entity_cache"
            else:
                # Fallback to session — this is a binding quality issue
                resolved_entity = session_id or agent_id
                routing_source  = "session_id_fallback"
                warnings.append(
                    f"actor '{agent_id}' not in entity cache — "
                    f"event will route to '{resolved_entity}' (session fallback). "
                    f"If this actor should have their own entity, "
                    f"ensure a spawn/handoff event was sent first."
                )

        if not resolved_entity:
            return DiagnosticResult(
                failure_mode    = BindingFailureMode.MISSING_ENTITY_ID,
                raw_event_type  = raw_type,
                gov_event_type  = gov_type,
                resolved_actor_id = agent_id,
                warnings        = warnings,
                suggestion      = (
                    f"Cannot resolve entity_id for '{raw_type}' from agent '{agent_id}'. "
                    f"Add task_ticket_id or ensure a spawn event registered this agent."
                ),
            )

        # 3. Actor 注册状态
        actor_known = (
            agent_id in self._agent_to_entity
            or bool(self._agent_to_entity.get(f"__latest_child_of_{agent_id}"))
        )
        failure_mode = BindingFailureMode.OK
        suggestion   = ""

        if not actor_known and raw_type in _FULFILLMENT_EVENT_TYPES:
            failure_mode = BindingFailureMode.UNKNOWN_ACTOR
            warnings.append(
                f"actor '{agent_id}' has no registered entity. "
                f"This fulfillment event may not match any open obligation."
            )
            suggestion = (
                f"Send a 'subagent_spawn' or 'handoff' event for '{agent_id}' first, "
                f"or include task_ticket_id in this event to bypass actor lookup."
            )
        else:
            # 4. Orphan fulfillment check (has pending obligation to fulfill?)
            if (raw_type in _FULFILLMENT_EVENT_TYPES
                    and resolved_entity
                    and self.engine.store.get_entity(resolved_entity) is not None):
                pending_obs = self.engine.store.list_obligations(
                    entity_id=resolved_entity,
                    status=None,
                )
                if not pending_obs:
                    warnings.append(
                        f"entity '{resolved_entity}' has no obligations — "
                        f"this fulfillment event will have no effect."
                    )

        return DiagnosticResult(
            failure_mode       = failure_mode,
            raw_event_type     = raw_type,
            resolved_entity_id = resolved_entity,
            resolved_actor_id  = agent_id,
            gov_event_type     = gov_type,
            warnings           = warnings,
            suggestion         = suggestion,
        )

    def batch_diagnose(
        self,
        events: List[Dict[str, Any]],
    ) -> List[DiagnosticResult]:
        """批量诊断事件列表，不注入任何事件。"""
        return [self.diagnose_event(e) for e in events]

    def binding_health_report(self) -> dict:
        """
        当前 adapter 的接入质量快照。
        返回缓存中注册的 agent 数量、已知 entity 数量等指标。
        用于区分"治理层问题"和"接线层问题"。
        """
        known_agents   = len(self.routing_table())
        known_entities = len(self.engine.store.list_entities())
        return {
            "known_agents":      known_agents,
            "known_entities":    known_entities,
            "routing_table":     self.routing_table(),
            "cache_completeness": (
                "ok" if known_agents >= known_entities * 0.8
                else "warning: many entities have no registered agent"
            ),
        }

    # ── 路由诊断 API ──────────────────────────────────────────────────────────

    def lookup_entity_for_agent(self, agent_id: str) -> Optional[str]:
        """
        查询某个 agent 当前关联的 entity_id。
        用于调试：确认 ack/status/result 事件会路由到哪个 entity。

        返回 None 表示该 agent 尚未被注册（履行事件会 fallback 到 session_id）。
        """
        return self._agent_to_entity.get(agent_id)

    def lookup_latest_child_of(self, parent_agent_id: str) -> Optional[str]:
        """
        查询某个 parent agent 最近 spawn 的 child entity_id。
        用于调试：确认 upstream_summary 事件会路由到哪个子任务。
        """
        return self._agent_to_entity.get(f"__latest_child_of_{parent_agent_id}")

    def routing_table(self) -> Dict[str, str]:
        """
        返回当前完整的 agent → entity 路由表（过滤掉内部 __latest_child_of__ 键）。
        用于运维诊断：快速核查所有 agent 的 entity 绑定是否正确。
        """
        return {
            k: v for k, v in self._agent_to_entity.items()
            if not k.startswith("__")
        }

    def debug_routing(self, raw_event_type: str, agent_id: str,
                      session_id: str = "", task_ticket_id: Optional[str] = None) -> dict:
        """
        在不实际注入事件的情况下，预测一个 raw 事件的 entity_id 路由结果。
        用于调试接入时的事件绑定问题。
        """
        mock_raw = {
            "event_type":   raw_event_type,
            "agent_id":     agent_id,
            "session_id":   session_id,
            "task_ticket_id": task_ticket_id,
        }
        entity_id  = self._resolve_entity_id(mock_raw, raw_event_type, session_id, agent_id)
        actor_id   = self._resolve_actor_id(mock_raw, raw_event_type, agent_id)
        gov_type   = (
            _OPENCLAW_TO_GOV.get(raw_event_type)
            or _YSTAR_TO_GOV.get(raw_event_type)
        )
        return {
            "raw_event_type":    raw_event_type,
            "resolved_entity_id":entity_id,
            "resolved_actor_id": actor_id,
            "gov_event_type":    gov_type,
            "is_fulfillment":    raw_event_type in _FULFILLMENT_EVENT_TYPES,
            "routing_source": (
                "task_ticket_id"           if task_ticket_id else
                "agent_to_entity_cache"    if self._agent_to_entity.get(agent_id) else
                "session_id_fallback"
            ),
        }

    # ── 私有：翻译逻辑 ────────────────────────────────────────────────────────

    def _translate(
        self,
        raw: Dict[str, Any],
        source: str,
    ) -> Tuple[Optional[TrackedEntity], Optional[GovernanceEvent]]:
        """
        把 raw OpenClaw 事件翻译成 (TrackedEntity or None, GovernanceEvent or None)。
        返回 None, None 表示此事件不需要治理层处理。
        """
        raw_type   = str(raw.get("event_type", ""))
        agent_id   = str(raw.get("agent_id", "unknown"))
        session_id = str(raw.get("session_id", ""))
        ts         = float(raw.get("timestamp", time.time()))
        payload    = {k: v for k, v in raw.items()
                      if k not in ("event_type", "agent_id", "session_id", "timestamp")}

        # 映射 governance event type
        gov_type = (
            _OPENCLAW_TO_GOV.get(raw_type)
            or _YSTAR_TO_GOV.get(raw_type)
        )
        if gov_type is None:
            return None, None   # 不处理的事件类型

        # 决定 entity_id
        entity_id = self._resolve_entity_id(raw, raw_type, session_id, agent_id)

        # 决定 actor_id（义务责任人）
        actor_id = self._resolve_actor_id(raw, raw_type, agent_id)

        # 构建 GovernanceEvent
        gov_ev = GovernanceEvent(
            event_type  = gov_type,
            entity_id   = entity_id,
            actor_id    = actor_id,
            ts          = ts,
            payload     = payload,
            source      = source,
            lineage_ref = self._lineage_cache.get(entity_id),
        )

        # 构建 TrackedEntity（仅在创建类事件时）
        entity = None
        if gov_type in (GEventType.ENTITY_CREATED, GEventType.ENTITY_ASSIGNED):
            entity = self._build_entity(raw, raw_type, entity_id, actor_id, ts)

        return entity, gov_ev

    def _resolve_entity_id(
        self,
        raw: Dict,
        raw_type: str,
        session_id: str,
        agent_id: str,
    ) -> str:
        """
        根据事件类型推断 entity_id。优先级：

        触发类（spawn / handoff）：
          child_agent_id > task_ticket_id → 注册到 _agent_to_entity 缓存

        履行类（ack / status / result / upstream 等）：
          1. task_ticket_id（调用方明确指定，最准确）
          2. _agent_to_entity[agent_id]（从 spawn/handoff 缓存推断）
          3. session_id（最后兜底，尽量避免）

        这解决了"ack/status/result 挂到根 session 而非子任务"的核心问题。
        """
        if raw_type in ("subagent_spawn", "handoff"):
            child = raw.get("child_agent_id") or raw.get("task_ticket_id")
            if child:
                child_str = str(child)
                # 建立 lineage：child → session root
                root = self._lineage_cache.get(session_id, session_id)
                self._lineage_cache[child_str] = root
                # 注册 child_agent → entity 映射（供 ack/status/result 路由）
                self._agent_to_entity[child_str] = child_str
                # 注册 parent_agent → entity 映射（供 upstream_summary 路由）
                parent = raw.get("parent_agent_id") or agent_id
                if parent:
                    # parent 可能管理多个 child；记录最新创建的那个
                    self._agent_to_entity[f"__latest_child_of_{parent}"] = child_str
                return child_str

        # 履行类事件：精确路由到子任务 entity
        if raw_type in _FULFILLMENT_EVENT_TYPES:
            # 优先级 1：调用方明确传入 task_ticket_id
            ticket = raw.get("task_ticket_id")
            if ticket:
                return str(ticket)

            # 优先级 2：从 agent_to_entity 缓存查找

            # Manager 发出的事件（task_delegated / upstream_summary）：
            # 找该 manager 最近 spawn 的 child entity
            if raw_type in _MANAGER_FULFILLMENT_EVENT_TYPES:
                child_key = f"__latest_child_of_{agent_id}"
                cached = self._agent_to_entity.get(child_key)
                if cached:
                    return cached

            # 对普通 fulfillment：找 agent_id 直接对应的 entity（worker 路由）
            cached = self._agent_to_entity.get(agent_id)
            if cached:
                return cached

            # 优先级 3：session_id 兜底（并记录警告语义）
            return session_id or agent_id

        # 非履行类：task_ticket_id > session_id
        if raw.get("task_ticket_id"):
            return str(raw["task_ticket_id"])
        return session_id or agent_id

    def _resolve_actor_id(
        self,
        raw: Dict,
        raw_type: str,
        agent_id: str,
    ) -> str:
        """
        决定 obligation/fulfillment 事件的责任 actor。

        规则：
        - spawn / handoff：parent 是 delegator（义务主体），child 是 delegatee
        - upstream_summary：发出者 = manager/initiator（agent_id 即责任方）
        - 其他 fulfillment：发出者 agent_id（即 worker）
        """
        if raw_type in ("subagent_spawn", "handoff"):
            return raw.get("parent_agent_id") or agent_id
        # upstream 类：agent_id 就是上游责任方（manager）
        if raw_type in _UPSTREAM_EVENT_TYPES:
            return agent_id
        return agent_id

    def _build_entity(
        self,
        raw: Dict,
        raw_type: str,
        entity_id: str,
        actor_id: str,
        ts: float,
    ) -> TrackedEntity:
        """构建 TrackedEntity 对象。"""
        entity_type = _infer_entity_type(raw_type, raw)
        current_owner = (
            raw.get("child_agent_id")
            or raw.get("agent_id")
            or self.default_owner
        )
        root_id = self._lineage_cache.get(entity_id, entity_id)
        lineage = [root_id, entity_id] if root_id != entity_id else [entity_id]

        existing = self.engine.store.get_entity(entity_id)
        if existing:
            # 如果是 ASSIGNED 事件，更新 owner
            if raw_type == "handoff":
                existing.current_owner_id = str(current_owner)
                existing.status = EntityStatus.ASSIGNED
                existing.touch()
            return existing

        return TrackedEntity(
            entity_id         = entity_id,
            entity_type       = entity_type,
            initiator_id      = actor_id,
            current_owner_id  = str(current_owner),
            status            = EntityStatus.CREATED
                                if raw_type in ("subagent_spawn", "session_start")
                                else EntityStatus.ASSIGNED,
            goal_summary      = str(raw.get("task_description", "")),
            parent_entity_id  = raw.get("parent_agent_id"),
            root_entity_id    = root_id,
            lineage           = lineage,
            created_at        = ts,
            updated_at        = ts,
        )


# ── 工厂函数 ─────────────────────────────────────────────────────────────────

def create_adapter(
    store: Optional[Any] = None,
    registry: Optional[Any] = None,
    cieu_store: Optional[Any] = None,
) -> OmissionAdapter:
    """
    便捷工厂：创建一套完整的 engine + adapter。

    参数：
        store:      OmissionStore 或 InMemoryOmissionStore（默认内存版）
        registry:   RuleRegistry（默认全局 registry）
        cieu_store: CIEUStore（可选，用于 CIEU 写入）
    """
    from ystar.governance.omission_store import InMemoryOmissionStore
    from ystar.governance.omission_rules import get_registry

    engine = OmissionEngine(
        store      = store or InMemoryOmissionStore(),
        registry   = registry or get_registry(),
        cieu_store = cieu_store,
    )
    return OmissionAdapter(engine=engine)

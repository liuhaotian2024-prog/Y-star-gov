"""
ystar.omission_summary  —  Omission Replay, Summary & Breakdown
===============================================================

提供三类输出能力：

  1. omission_summary()   —— 全局统计（按类型/actor/entity type 分解）
  2. entity_timeline()    —— 单个 entity 的义务履行时间线
  3. replay()             —— 重放某个 entity 的 omission 历史，回答：
                               • 哪个 entity 卡住了？
                               • 谁承担义务？
                               • 哪个 required event 没发生？
                               • 超时了多久？
                               • 升级到哪一层？

设计原则：
  - 所有输出基于 store 的当前状态，可重放
  - 不依赖任何业务角色词汇
  - 输出格式为 dict（方便序列化、写入 CIEU、打印到终端）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ystar.governance.omission_models import (
    ObligationStatus, OmissionType, Severity, GEventType,
    ObligationRecord, OmissionViolation, TrackedEntity,
)
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore

AnyStore = Union[InMemoryOmissionStore, OmissionStore]


# ── 全局摘要 ─────────────────────────────────────────────────────────────────

def omission_summary(store: AnyStore) -> Dict[str, Any]:
    """
    全局 omission 统计摘要。

    输出结构：
        {
          "total_violations": int,
          "total_obligations": int,
          "open_obligations": int,
          "expired_obligations": int,
          "escalated_obligations": int,
          "by_omission_type": {type: count, ...},
          "by_actor": {actor_id: count, ...},
          "by_entity_type": {entity_type: count, ...},
          "by_severity": {severity: count, ...},
          "violation_rate": float,
        }
    """
    all_violations = store.list_violations()
    all_obligations = store.list_obligations()

    from ystar.governance.omission_models import ObligationStatus as _OS
    pending   = [o for o in all_obligations if o.status == _OS.PENDING]
    # v0.33: expired_obligations includes SOFT_OVERDUE + HARD_OVERDUE + EXPIRED
    expired   = [o for o in all_obligations if o.status.is_overdue_any]
    escalated_obs = [o for o in all_obligations if o.status == _OS.ESCALATED]

    # 按 omission type 分组
    by_type: Dict[str, int] = {}
    for v in all_violations:
        by_type[v.omission_type] = by_type.get(v.omission_type, 0) + 1

    # 按 actor 分组
    by_actor: Dict[str, int] = {}
    for v in all_violations:
        by_actor[v.actor_id] = by_actor.get(v.actor_id, 0) + 1

    # 按 entity_type 分组（需要从 entity 查）
    by_entity_type: Dict[str, int] = {}
    for v in all_violations:
        ent = store.get_entity(v.entity_id)
        etype = ent.entity_type if ent else "unknown"
        by_entity_type[etype] = by_entity_type.get(etype, 0) + 1

    # 按严重程度分组
    by_severity: Dict[str, int] = {}
    for v in all_violations:
        by_severity[v.severity.value] = by_severity.get(v.severity.value, 0) + 1

    total = len(all_obligations)
    viol_count = len(all_violations)

    return {
        "total_obligations":    total,
        "total_violations":     viol_count,
        "open_obligations":     len(pending),
        "expired_obligations":  len(expired),
        "escalated_obligations":len(escalated_obs),
        "fulfilled_obligations":len([o for o in all_obligations
                                     if o.status == ObligationStatus.FULFILLED]),
        "soft_overdue_obligations": len([o for o in all_obligations
                                         if o.status == ObligationStatus.SOFT_OVERDUE]),
        "hard_overdue_obligations": len([o for o in all_obligations
                                         if o.status == ObligationStatus.HARD_OVERDUE]),
        "by_omission_type":     dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_actor":             dict(sorted(by_actor.items(), key=lambda x: -x[1])),
        "by_entity_type":       dict(sorted(by_entity_type.items(), key=lambda x: -x[1])),
        "by_severity":          by_severity,
        "violation_rate":       round(viol_count / total, 3) if total > 0 else 0.0,
        "escalated_violations": len([v for v in all_violations if v.escalated]),
    }


# ── 单个 Entity 时间线 ────────────────────────────────────────────────────────

def entity_timeline(store: AnyStore, entity_id: str) -> Dict[str, Any]:
    """
    单个 entity 的义务履行时间线。
    按时间顺序列出所有 governance events、obligations 和 violations。
    """
    entity = store.get_entity(entity_id)
    events = store.events_for_entity(entity_id)
    obligations = store.list_obligations(entity_id=entity_id)
    violations = store.list_violations(entity_id=entity_id)

    # 构建时间线条目
    timeline = []

    for ev in sorted(events, key=lambda e: e.ts):
        timeline.append({
            "ts":       ev.ts,
            "kind":     "event",
            "type":     ev.event_type,
            "actor":    ev.actor_id,
            "event_id": ev.event_id,
        })

    for ob in sorted(obligations, key=lambda o: o.created_at):
        timeline.append({
            "ts":         ob.created_at,
            "kind":       "obligation_created",
            "type":       ob.obligation_type,
            "actor":      ob.actor_id,
            "status":     ob.status.value,
            "due_at":     ob.due_at,
            "ob_id":      ob.obligation_id,
        })
        if ob.status == ObligationStatus.FULFILLED and ob.fulfilled_by_event_id:
            timeline.append({
                "ts":     ob.updated_at,
                "kind":   "obligation_fulfilled",
                "type":   ob.obligation_type,
                "actor":  ob.actor_id,
                "ob_id":  ob.obligation_id,
                "by_event": ob.fulfilled_by_event_id,
            })

    for v in sorted(violations, key=lambda x: x.detected_at):
        timeline.append({
            "ts":          v.detected_at,
            "kind":        "violation",
            "omission":    v.omission_type,
            "actor":       v.actor_id,
            "overdue_secs":v.overdue_secs,
            "severity":    v.severity.value,
            "escalated":   v.escalated,
            "escalated_to":v.escalated_to,
            "cieu_ref":    v.cieu_ref,
            "viol_id":     v.violation_id,
        })

    timeline.sort(key=lambda x: x["ts"])

    return {
        "entity_id":   entity_id,
        "entity_type": entity.entity_type if entity else "unknown",
        "entity_status":entity.status.value if entity else "unknown",
        "lineage":     entity.lineage if entity else [],
        "owner":       entity.current_owner_id if entity else None,
        "timeline":    timeline,
        "summary": {
            "events":      len(events),
            "obligations": len(obligations),
            "violations":  len(violations),
            "fulfilled":   sum(1 for o in obligations if o.status == ObligationStatus.FULFILLED),
            "open":        sum(1 for o in obligations if o.status == ObligationStatus.PENDING),
        },
    }


# ── Replay：回答 omission 追责问题 ───────────────────────────────────────────

def replay(store: AnyStore, entity_id: Optional[str] = None) -> Dict[str, Any]:
    """
    重放 omission 历史，回答关键追责问题。

    如果指定 entity_id，只回放该 entity。
    否则回放全部 violations。

    每条 violation 输出：
        - entity_id         哪个单元卡住了
        - actor_id          谁承担义务
        - omission_type     哪种 omission failure
        - required_events   哪些 required event 没发生
        - overdue_secs      超时了多久
        - escalated_to      升级到哪一层
        - cieu_ref          CIEU 证据引用
        - lineage           上下游链路
    """
    if entity_id:
        violations = store.list_violations(entity_id=entity_id)
    else:
        violations = store.list_violations()

    replay_records = []
    for v in violations:
        ob = store.get_obligation(v.obligation_id)
        entity = store.get_entity(v.entity_id)

        record = {
            # 谁的问题
            "entity_id":     v.entity_id,
            "entity_type":   entity.entity_type if entity else "unknown",
            "actor_id":      v.actor_id,
            "lineage":       entity.lineage if entity else [],

            # 什么 omission
            "omission_type": v.omission_type,
            "required_events": ob.required_event_types if ob else [],
            "actually_occurred_events": _find_occurred_events(
                store, v.entity_id, ob.required_event_types if ob else []
            ),

            # 时间维度
            "obligation_due_at":  ob.due_at if ob else None,
            "violation_detected_at": v.detected_at,
            "overdue_secs":       round(v.overdue_secs, 2),

            # 严重度
            "severity":       v.severity.value,
            "violation_code": ob.violation_code if ob else None,

            # 升级链
            "escalated":      v.escalated,
            "escalated_to":   v.escalated_to,

            # 证据链
            "cieu_ref":       v.cieu_ref,
            "violation_id":   v.violation_id,
            "obligation_id":  v.obligation_id,
        }
        replay_records.append(record)

    # 按严重度排序（CRITICAL > HIGH > MEDIUM > LOW）
    _sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    replay_records.sort(key=lambda r: _sev_order.get(r["severity"], 9))

    return {
        "scope":            entity_id or "global",
        "total_violations": len(replay_records),
        "violations":       replay_records,
    }


def _find_occurred_events(
    store: AnyStore,
    entity_id: str,
    required_types: List[str],
) -> List[str]:
    """找出 required_event_types 中哪些实际发生了（哪些没有）。"""
    occurred = []
    for et in required_types:
        if store.has_event_of_type(entity_id, et):
            occurred.append(et)
    return occurred


# ── 格式化打印 ───────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# A5 v0.33: Enhanced Analytics
# ══════════════════════════════════════════════════════════════════════════════

def chain_breakpoint_analysis(store: AnyStore) -> Dict[str, Any]:
    """
    链式断点分析：找出 root→leaf 义务链上最常见的断点位置。

    输出：
        {
          "total_chains":   int,
          "broken_chains":  int,
          "breakpoints": [
              {"position": "delegation", "count": N, "actors": [...]},
              ...
          ],
          "deepest_chain_length": int,
          "orphan_entities": [entity_id, ...]   # entities with no lineage parent
        }
    """
    all_violations = store.list_violations()
    all_entities   = store.list_entities()

    # Count breakpoints by omission_type (= "where the chain broke")
    breakpoints: Dict[str, Dict] = {}
    for v in all_violations:
        key = v.omission_type.replace("required_", "").replace("_omission", "")
        if key not in breakpoints:
            breakpoints[key] = {"omission_type": v.omission_type, "count": 0,
                                 "actors": set(), "entity_ids": set()}
        breakpoints[key]["count"]      += 1
        breakpoints[key]["actors"].add(v.actor_id)
        breakpoints[key]["entity_ids"].add(v.entity_id)

    # Find orphan entities (no parent_entity_id but also not root)
    all_entity_ids = {e.entity_id for e in all_entities}
    orphans = [
        e.entity_id for e in all_entities
        if e.parent_entity_id and e.parent_entity_id not in all_entity_ids
    ]

    # Deepest lineage chain
    max_depth = max((len(e.lineage) for e in all_entities if e.lineage), default=0)

    # Broken chains: entities with violation AND no closure event
    broken = set()
    for v in all_violations:
        if not store.has_event_of_type(v.entity_id, GEventType.CLOSURE_EVENT):
            broken.add(v.entity_id)

    sorted_bp = sorted(
        [{"position":  k,
          "omission_type": v["omission_type"],
          "count":     v["count"],
          "actors":    sorted(v["actors"]),
          "entity_count": len(v["entity_ids"])}
         for k, v in breakpoints.items()],
        key=lambda x: -x["count"],
    )

    return {
        "total_chains":         len({e.root_entity_id or e.entity_id for e in all_entities}),
        "broken_chains":        len(broken),
        "breakpoints":          sorted_bp,
        "deepest_chain_length": max_depth,
        "orphan_entities":      orphans,
        "most_common_break":    sorted_bp[0]["position"] if sorted_bp else None,
    }


def obligation_heatmap(store: AnyStore) -> Dict[str, Any]:
    """
    Root-to-leaf obligation 热度图。
    展示哪种 entity_type × obligation_type 组合最容易失败。

    输出：
        {
          "heatmap": {
              "subagent_task": {
                  "required_delegation_omission":    {"total": N, "violated": M, "rate": 0.42},
                  ...
              },
              ...
          },
          "worst_combo": {"entity_type": X, "obligation_type": Y, "rate": Z}
        }
    """
    all_obs   = store.list_obligations()
    all_viols = store.list_violations()

    # Build violation set for fast lookup
    violated_ob_ids = {v.obligation_id for v in all_viols}

    heatmap: Dict[str, Dict[str, Dict]] = {}
    all_os = all_obs
    for ob in all_os:
        ent = store.get_entity(ob.entity_id)
        etype = ent.entity_type if ent else "unknown"
        otype = ob.obligation_type

        heatmap.setdefault(etype, {})
        heatmap[etype].setdefault(otype, {"total": 0, "violated": 0})
        heatmap[etype][otype]["total"] += 1
        if ob.obligation_id in violated_ob_ids:
            heatmap[etype][otype]["violated"] += 1

    # Compute rates
    worst = {"entity_type": None, "obligation_type": None, "rate": 0.0}
    for etype, otypes in heatmap.items():
        for otype, counts in otypes.items():
            rate = counts["violated"] / counts["total"] if counts["total"] else 0
            counts["rate"] = round(rate, 3)
            if rate > worst["rate"]:
                worst = {"entity_type": etype, "obligation_type": otype, "rate": rate}

    return {"heatmap": heatmap, "worst_combo": worst}


def actor_reliability_report(store: AnyStore) -> Dict[str, Any]:
    """
    Actor 可靠性报告：谁最常不 ack / 不更新 / 不上报。

    输出：
        {
          "actors": [
            {
              "actor_id": "agent-X",
              "total_obligations": N,
              "fulfilled": M,
              "violated": K,
              "reliability_rate": 0.72,
              "worst_omission": "required_acknowledgement_omission",
              "avg_overdue_secs": 42.3,
            },
            ...
          ]
        }
    """
    all_obs   = store.list_obligations()
    all_viols = store.list_violations()

    viol_by_actor: Dict[str, List] = {}
    for v in all_viols:
        viol_by_actor.setdefault(v.actor_id, []).append(v)

    ob_by_actor: Dict[str, List] = {}
    for ob in all_obs:
        ob_by_actor.setdefault(ob.actor_id, []).append(ob)

    actors = []
    for actor_id, obs in ob_by_actor.items():
        total     = len(obs)
        fulfilled = sum(1 for o in obs if o.status == ObligationStatus.FULFILLED)
        viols     = viol_by_actor.get(actor_id, [])

        worst_omission = None
        if viols:
            from collections import Counter
            c = Counter(v.omission_type for v in viols)
            worst_omission = c.most_common(1)[0][0]

        avg_overdue = (
            sum(v.overdue_secs for v in viols) / len(viols) if viols else 0.0
        )

        actors.append({
            "actor_id":         actor_id,
            "total_obligations":total,
            "fulfilled":        fulfilled,
            "violated":         len(viols),
            "reliability_rate": round(fulfilled / total, 3) if total else 0.0,
            "worst_omission":   worst_omission,
            "avg_overdue_secs": round(avg_overdue, 1),
        })

    actors.sort(key=lambda a: a["reliability_rate"])
    return {"actors": actors}


def print_summary(store: AnyStore) -> None:
    """终端友好的摘要打印。"""
    s = omission_summary(store)
    print("=" * 60)
    print("  Y* OMISSION GOVERNANCE SUMMARY")
    print("=" * 60)
    print(f"  Total obligations : {s['total_obligations']}")
    print(f"  Open (pending)    : {s['open_obligations']}")
    print(f"  Fulfilled         : {s['fulfilled_obligations']}")
    print(f"  Expired (failed)  : {s['expired_obligations']}")
    print(f"  Escalated         : {s['escalated_obligations']}")
    print(f"  Total violations  : {s['total_violations']}")
    print(f"  Violation rate    : {s['violation_rate']:.1%}")
    print()

    if s["by_omission_type"]:
        print("  By omission type:")
        for t, c in s["by_omission_type"].items():
            print(f"    {t:<45} {c}")
        print()

    if s["by_actor"]:
        print("  By actor (most violations):")
        for a, c in list(s["by_actor"].items())[:5]:
            print(f"    {a:<30} {c}")
        print()

    if s["by_severity"]:
        print("  By severity:")
        for sev, c in s["by_severity"].items():
            print(f"    {sev:<10} {c}")
    print("=" * 60)


def print_replay(store: AnyStore, entity_id: Optional[str] = None) -> None:
    """终端友好的 replay 打印。"""
    r = replay(store, entity_id)
    print("=" * 60)
    print(f"  OMISSION REPLAY  [scope: {r['scope']}]")
    print(f"  Total violations: {r['total_violations']}")
    print("=" * 60)
    for v in r["violations"]:
        print(f"\n  ▶ {v['omission_type']}")
        print(f"    entity   : {v['entity_id']} ({v['entity_type']})")
        print(f"    actor    : {v['actor_id']}")
        print(f"    lineage  : {' → '.join(v['lineage']) if v['lineage'] else 'N/A'}")
        print(f"    required : {v['required_events']}")
        print(f"    occurred : {v['actually_occurred_events']}")
        print(f"    overdue  : {v['overdue_secs']}s")
        print(f"    severity : {v['severity']}")
        if v["escalated"]:
            print(f"    escalated→ {v['escalated_to']}")
        if v["cieu_ref"]:
            print(f"    cieu_ref : {v['cieu_ref']}")
    print("=" * 60)

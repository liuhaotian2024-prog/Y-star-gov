"""
ystar.omission_store  —  Omission Governance Storage
=====================================================

存储 entities、obligations、governance events、violations 的持久化层。
使用 SQLite（与 cieu_store.py 保持一致），零外部依赖。

两层架构：
  - InMemoryOmissionStore  : 轻量内存版，适合测试和短生命周期场景
  - OmissionStore          : SQLite 持久化版，适合生产
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ystar.governance.omission_models import (
    EntityStatus, ObligationStatus, Severity,
    TrackedEntity, ObligationRecord, GovernanceEvent,
    OmissionViolation, EscalationPolicy,
)


# ══════════════════════════════════════════════════════════════════════════════
# 内存版（用于测试和单次场景）
# ══════════════════════════════════════════════════════════════════════════════

class InMemoryOmissionStore:
    """
    纯内存 omission 存储。线程不安全（单线程测试用）。
    与 OmissionStore 接口完全兼容，可随时替换。
    """

    def __init__(self) -> None:
        self._entities:    Dict[str, TrackedEntity]    = {}
        self._obligations: Dict[str, ObligationRecord] = {}
        self._events:      Dict[str, GovernanceEvent]  = {}
        self._violations:  Dict[str, OmissionViolation]= {}
        # event_type → [event_id]  用于快速查找是否已有某类事件
        self._events_by_type_entity: Dict[str, List[str]] = {}

    # ── Entity ─────────────────────────────────────────────────────────────

    def upsert_entity(self, entity: TrackedEntity) -> None:
        entity.updated_at = time.time()
        self._entities[entity.entity_id] = entity

    def get_entity(self, entity_id: str) -> Optional[TrackedEntity]:
        return self._entities.get(entity_id)

    def list_entities(
        self,
        status: Optional[EntityStatus] = None,
        entity_type: Optional[str] = None,
    ) -> List[TrackedEntity]:
        result = list(self._entities.values())
        if status:
            result = [e for e in result if e.status == status]
        if entity_type:
            result = [e for e in result if e.entity_type == entity_type]
        return result

    # ── Obligation ─────────────────────────────────────────────────────────

    def add_obligation(self, ob: ObligationRecord) -> None:
        self._obligations[ob.obligation_id] = ob

    def get_obligation(self, obligation_id: str) -> Optional[ObligationRecord]:
        return self._obligations.get(obligation_id)

    def update_obligation(self, ob: ObligationRecord) -> None:
        ob.updated_at = time.time()
        self._obligations[ob.obligation_id] = ob

    def list_obligations(
        self,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        status: Optional[ObligationStatus] = None,
        obligation_type: Optional[str] = None,
    ) -> List[ObligationRecord]:
        result = list(self._obligations.values())
        if entity_id:
            result = [o for o in result if o.entity_id == entity_id]
        if actor_id:
            result = [o for o in result if o.actor_id == actor_id]
        if status:
            result = [o for o in result if o.status == status]
        if obligation_type:
            result = [o for o in result if o.obligation_type == obligation_type]
        return result

    def pending_obligations(self) -> List[ObligationRecord]:
        return [o for o in self._obligations.values()
                if o.status == ObligationStatus.PENDING]

    def has_pending_obligation(
        self,
        entity_id: str,
        obligation_type: str,
        actor_id: Optional[str] = None,
    ) -> bool:
        for o in self._obligations.values():
            if (o.entity_id == entity_id
                    and o.obligation_type == obligation_type
                    and o.status == ObligationStatus.PENDING):
                if actor_id is None or o.actor_id == actor_id:
                    return True
        return False

    def cancel_obligation(self, obligation_id: str) -> bool:
        """
        Cancel an obligation by setting its status to CANCELLED.

        Args:
            obligation_id: The ID of the obligation to cancel

        Returns:
            True if obligation was found and cancelled, False otherwise
        """
        ob = self._obligations.get(obligation_id)
        if ob is None:
            return False

        ob.status = ObligationStatus.CANCELLED
        ob.updated_at = time.time()
        self._obligations[obligation_id] = ob
        return True

    # ── GovernanceEvent ────────────────────────────────────────────────────

    def add_event(self, ev: GovernanceEvent) -> None:
        self._events[ev.event_id] = ev
        key = f"{ev.event_type}::{ev.entity_id}"
        self._events_by_type_entity.setdefault(key, []).append(ev.event_id)

    def get_event(self, event_id: str) -> Optional[GovernanceEvent]:
        return self._events.get(event_id)

    def events_for_entity(
        self,
        entity_id: str,
        event_types: Optional[List[str]] = None,
    ) -> List[GovernanceEvent]:
        if event_types:
            result = []
            for et in event_types:
                key = f"{et}::{entity_id}"
                for eid in self._events_by_type_entity.get(key, []):
                    ev = self._events.get(eid)
                    if ev:
                        result.append(ev)
            return sorted(result, key=lambda e: e.ts)
        return sorted(
            [e for e in self._events.values() if e.entity_id == entity_id],
            key=lambda e: e.ts,
        )

    def has_event_of_type(self, entity_id: str, event_type: str) -> bool:
        key = f"{event_type}::{entity_id}"
        return bool(self._events_by_type_entity.get(key))

    def has_any_event_of_types(self, entity_id: str, event_types: List[str]) -> bool:
        return any(self.has_event_of_type(entity_id, et) for et in event_types)

    # ── OmissionViolation ──────────────────────────────────────────────────

    def add_violation(self, v: OmissionViolation) -> None:
        self._violations[v.violation_id] = v

    def update_violation(self, v: OmissionViolation) -> None:
        self._violations[v.violation_id] = v

    def list_violations(
        self,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        omission_type: Optional[str] = None,
        escalated: Optional[bool] = None,
    ) -> List[OmissionViolation]:
        result = list(self._violations.values())
        if entity_id:
            result = [v for v in result if v.entity_id == entity_id]
        if actor_id:
            result = [v for v in result if v.actor_id == actor_id]
        if omission_type:
            result = [v for v in result if v.omission_type == omission_type]
        if escalated is not None:
            result = [v for v in result if v.escalated == escalated]
        return result

    def violation_exists_for_obligation(self, obligation_id: str) -> bool:
        return any(v.obligation_id == obligation_id
                   for v in self._violations.values())

    def clear(self) -> None:
        self._entities.clear()
        self._obligations.clear()
        self._events.clear()
        self._violations.clear()
        self._events_by_type_entity.clear()


# ══════════════════════════════════════════════════════════════════════════════
# SQLite 持久化版
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULT_DB = Path(".ystar_omission.db")

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

CREATE TABLE IF NOT EXISTS entities (
    entity_id         TEXT PRIMARY KEY,
    entity_type       TEXT NOT NULL,
    initiator_id      TEXT NOT NULL,
    current_owner_id  TEXT,
    status            TEXT NOT NULL DEFAULT 'created',
    goal_summary      TEXT DEFAULT '',
    scope_json        TEXT DEFAULT '{}',
    parent_entity_id  TEXT,
    root_entity_id    TEXT,
    lineage_json      TEXT DEFAULT '[]',
    contract_ref      TEXT,
    required_next_event TEXT,
    required_by_ts    REAL,
    deadline          REAL,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL,
    last_event_at     REAL,
    metadata_json     TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS obligations (
    obligation_id         TEXT PRIMARY KEY,
    entity_id             TEXT NOT NULL,
    actor_id              TEXT NOT NULL,
    obligation_type       TEXT NOT NULL,
    trigger_event_id      TEXT,
    required_event_types  TEXT DEFAULT '[]',
    due_at                REAL,
    grace_period_secs     REAL DEFAULT 0,
    hard_overdue_secs     REAL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'pending',
    fulfilled_by_event_id TEXT,
    violation_code        TEXT,
    severity              TEXT DEFAULT 'medium',
    escalation_policy_json TEXT DEFAULT '{}',
    escalated             INTEGER DEFAULT 0,
    escalated_at          REAL,
    reminder_sent_at      REAL,
    notes                 TEXT DEFAULT '',
    created_at            REAL NOT NULL,
    updated_at            REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS governance_events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    actor_id     TEXT NOT NULL,
    ts           REAL NOT NULL,
    payload_json TEXT DEFAULT '{}',
    source       TEXT DEFAULT 'unknown',
    lineage_ref  TEXT
);

CREATE TABLE IF NOT EXISTS omission_violations (
    violation_id  TEXT PRIMARY KEY,
    entity_id     TEXT NOT NULL,
    obligation_id TEXT NOT NULL,
    actor_id      TEXT NOT NULL,
    omission_type TEXT NOT NULL,
    detected_at   REAL NOT NULL,
    overdue_secs  REAL DEFAULT 0,
    severity      TEXT DEFAULT 'medium',
    details_json  TEXT DEFAULT '{}',
    escalated     INTEGER DEFAULT 0,
    escalated_to  TEXT,
    cieu_ref      TEXT
);

CREATE INDEX IF NOT EXISTS idx_obl_entity  ON obligations(entity_id);
CREATE INDEX IF NOT EXISTS idx_obl_actor   ON obligations(actor_id);
CREATE INDEX IF NOT EXISTS idx_obl_status  ON obligations(status);
CREATE INDEX IF NOT EXISTS idx_obl_type    ON obligations(obligation_type);
CREATE INDEX IF NOT EXISTS idx_ev_entity   ON governance_events(entity_id);
CREATE INDEX IF NOT EXISTS idx_ev_type     ON governance_events(event_type);
CREATE INDEX IF NOT EXISTS idx_viol_entity ON omission_violations(entity_id);
CREATE INDEX IF NOT EXISTS idx_viol_actor  ON omission_violations(actor_id);
"""


class OmissionStore:
    """
    SQLite-backed omission governance 存储。
    与 InMemoryOmissionStore 接口完全兼容。
    """

    def __init__(self, db_path: str = str(_DEFAULT_DB)) -> None:
        self.db_path = Path(db_path)
        self._init()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            # Schema migration: add v0.33, v0.43, v0.48 fields if missing
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM pragma_table_info('obligations')
            """)
            existing_cols = {row[0] for row in cursor.fetchall()}

            # v0.48: cancellation fields + rule_id
            if 'session_id' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN session_id TEXT")
            if 'cancelled_at' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN cancelled_at REAL")
            if 'cancellation_reason' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN cancellation_reason TEXT")
            if 'rule_id' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN rule_id TEXT")

            # v0.33: two-phase timeout (soft/hard overdue)
            if 'soft_violation_at' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN soft_violation_at REAL")
            if 'hard_violation_at' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN hard_violation_at REAL")
            if 'soft_count' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN soft_count INTEGER DEFAULT 0")

            # v0.43: restoration fields
            if 'restored_at' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN restored_at REAL")
            if 'restored_by_event_id' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN restored_by_event_id TEXT")
            if 'restoration_grace_period_multiplier' not in existing_cols:
                cursor.execute("ALTER TABLE obligations ADD COLUMN restoration_grace_period_multiplier REAL DEFAULT 2.0")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Entity ─────────────────────────────────────────────────────────────

    def upsert_entity(self, entity: TrackedEntity) -> None:
        entity.updated_at = time.time()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO entities VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    current_owner_id=excluded.current_owner_id,
                    status=excluded.status,
                    goal_summary=excluded.goal_summary,
                    scope_json=excluded.scope_json,
                    required_next_event=excluded.required_next_event,
                    required_by_ts=excluded.required_by_ts,
                    deadline=excluded.deadline,
                    updated_at=excluded.updated_at,
                    last_event_at=excluded.last_event_at,
                    metadata_json=excluded.metadata_json
            """, (
                entity.entity_id, entity.entity_type, entity.initiator_id,
                entity.current_owner_id, entity.status.value,
                entity.goal_summary, json.dumps(entity.scope),
                entity.parent_entity_id, entity.root_entity_id,
                json.dumps(entity.lineage), entity.contract_ref,
                entity.required_next_event, entity.required_by_ts,
                entity.deadline, entity.created_at, entity.updated_at,
                entity.last_event_at, json.dumps(entity.metadata),
            ))

    def get_entity(self, entity_id: str) -> Optional[TrackedEntity]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE entity_id=?", (entity_id,)
            ).fetchone()
        return self._row_to_entity(row) if row else None

    def list_entities(
        self,
        status: Optional[EntityStatus] = None,
        entity_type: Optional[str] = None,
    ) -> List[TrackedEntity]:
        conds, params = [], []
        if status:
            conds.append("status=?"); params.append(status.value)
        if entity_type:
            conds.append("entity_type=?"); params.append(entity_type)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM entities {where}", params
            ).fetchall()
        return [self._row_to_entity(r) for r in rows]

    def _row_to_entity(self, row: sqlite3.Row) -> TrackedEntity:
        return TrackedEntity(
            entity_id          = row["entity_id"],
            entity_type        = row["entity_type"],
            initiator_id       = row["initiator_id"],
            current_owner_id   = row["current_owner_id"],
            status             = EntityStatus(row["status"]),
            goal_summary       = row["goal_summary"] or "",
            scope              = json.loads(row["scope_json"] or "{}"),
            parent_entity_id   = row["parent_entity_id"],
            root_entity_id     = row["root_entity_id"],
            lineage            = json.loads(row["lineage_json"] or "[]"),
            contract_ref       = row["contract_ref"],
            required_next_event= row["required_next_event"],
            required_by_ts     = row["required_by_ts"],
            deadline           = row["deadline"],
            created_at         = row["created_at"],
            updated_at         = row["updated_at"],
            last_event_at      = row["last_event_at"],
            metadata           = json.loads(row["metadata_json"] or "{}"),
        )

    # ── Obligation ─────────────────────────────────────────────────────────

    def add_obligation(self, ob: ObligationRecord) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO obligations VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ob.obligation_id, ob.entity_id, ob.actor_id,
                ob.obligation_type, ob.trigger_event_id,
                json.dumps(ob.required_event_types),
                ob.due_at, ob.grace_period_secs, ob.hard_overdue_secs,
                ob.status.value, ob.fulfilled_by_event_id,
                ob.violation_code, ob.severity.value,
                json.dumps(ob.escalation_policy.to_dict()),
                1 if ob.escalated else 0, ob.escalated_at,
                ob.reminder_sent_at, ob.notes,
                ob.created_at, ob.updated_at,
                ob.session_id, ob.cancelled_at, ob.cancellation_reason,
                ob.rule_id,
                # v0.33: two-phase timeout
                ob.soft_violation_at, ob.hard_violation_at, ob.soft_count,
                # v0.43: restoration
                ob.restored_at, ob.restored_by_event_id, ob.restoration_grace_period_multiplier,
            ))

    def get_obligation(self, obligation_id: str) -> Optional[ObligationRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM obligations WHERE obligation_id=?", (obligation_id,)
            ).fetchone()
        return self._row_to_obligation(row) if row else None

    def update_obligation(self, ob: ObligationRecord) -> None:
        ob.updated_at = time.time()
        with self._conn() as conn:
            conn.execute("""
                UPDATE obligations SET
                    status=?, fulfilled_by_event_id=?, violation_code=?,
                    escalated=?, escalated_at=?, reminder_sent_at=?,
                    notes=?, updated_at=?,
                    due_at=?, grace_period_secs=?, hard_overdue_secs=?,
                    session_id=?, cancelled_at=?, cancellation_reason=?,
                    soft_violation_at=?, hard_violation_at=?, soft_count=?,
                    restored_at=?, restored_by_event_id=?, restoration_grace_period_multiplier=?
                WHERE obligation_id=?
            """, (
                ob.status.value, ob.fulfilled_by_event_id, ob.violation_code,
                1 if ob.escalated else 0, ob.escalated_at,
                ob.reminder_sent_at, ob.notes, ob.updated_at,
                ob.due_at, ob.grace_period_secs, ob.hard_overdue_secs,
                ob.session_id, ob.cancelled_at, ob.cancellation_reason,
                # v0.33 + v0.43 fields
                ob.soft_violation_at, ob.hard_violation_at, ob.soft_count,
                ob.restored_at, ob.restored_by_event_id, ob.restoration_grace_period_multiplier,
                ob.obligation_id,
            ))

    def list_obligations(
        self,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        status: Optional[ObligationStatus] = None,
        obligation_type: Optional[str] = None,
    ) -> List[ObligationRecord]:
        conds, params = [], []
        if entity_id:
            conds.append("entity_id=?"); params.append(entity_id)
        if actor_id:
            conds.append("actor_id=?"); params.append(actor_id)
        if status:
            conds.append("status=?"); params.append(status.value)
        if obligation_type:
            conds.append("obligation_type=?"); params.append(obligation_type)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM obligations {where}", params
            ).fetchall()
        return [self._row_to_obligation(r) for r in rows]

    def pending_obligations(self) -> List[ObligationRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM obligations WHERE status='pending'"
            ).fetchall()
        return [self._row_to_obligation(r) for r in rows]

    def has_pending_obligation(
        self,
        entity_id: str,
        obligation_type: str,
        actor_id: Optional[str] = None,
    ) -> bool:
        conds = ["entity_id=?", "obligation_type=?", "status='pending'"]
        params: list = [entity_id, obligation_type]
        if actor_id:
            conds.append("actor_id=?"); params.append(actor_id)
        with self._conn() as conn:
            n = conn.execute(
                f"SELECT COUNT(*) FROM obligations WHERE {' AND '.join(conds)}", params
            ).fetchone()[0]
        return n > 0

    def violation_exists_for_obligation(self, obligation_id: str) -> bool:
        with self._conn() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM omission_violations WHERE obligation_id=?",
                (obligation_id,)
            ).fetchone()[0]
        return n > 0

    def cancel_obligation(
        self,
        obligation_id: str,
        reason: Optional[str] = None,
        write_cieu: bool = True
    ) -> bool:
        """
        Cancel an obligation by setting its status to CANCELLED.

        Args:
            obligation_id: The ID of the obligation to cancel
            reason: Optional cancellation reason
            write_cieu: Whether to write cancellation event to CIEU (default True)

        Returns:
            True if obligation was found and cancelled, False otherwise
        """
        with self._conn() as conn:
            # Check if obligation exists
            row = conn.execute(
                "SELECT obligation_id FROM obligations WHERE obligation_id=?",
                (obligation_id,)
            ).fetchone()

            if row is None:
                return False

            # Update obligation status to CANCELLED
            now = time.time()
            conn.execute("""
                UPDATE obligations
                SET status = 'cancelled',
                    updated_at = ?,
                    cancelled_at = ?,
                    cancellation_reason = ?
                WHERE obligation_id = ?
            """, (now, now, reason or "Manual cancellation", obligation_id))

        # Write CIEU event if requested
        if write_cieu:
            try:
                from ystar.governance.cieu_store import CIEUStore
                cieu_path = str(self.db_path).replace("_omission.db", ".db")
                cieu_store = CIEUStore(cieu_path)
                cieu_store.write_dict({
                    "session_id": "system",
                    "agent_id": "omission_store",
                    "event_type": "obligation_cancelled",
                    "decision": "allow",
                    "passed": True,
                    "params": {
                        "obligation_id": obligation_id,
                        "reason": reason or "Manual cancellation",
                    },
                    "evidence_grade": "decision",
                })
            except Exception as e:
                # Non-fatal: CIEU write failure shouldn't block cancellation
                import logging
                logging.getLogger("ystar.omission").warning(
                    f"Failed to write obligation cancellation to CIEU: {e}"
                )

        return True

    def _row_to_obligation(self, row: sqlite3.Row) -> ObligationRecord:
        try:
            ep = EscalationPolicy.from_dict(
                json.loads(row["escalation_policy_json"] or "{}")
            )
        except Exception:
            ep = EscalationPolicy.default()
        return ObligationRecord(
            obligation_id        = row["obligation_id"],
            entity_id            = row["entity_id"],
            actor_id             = row["actor_id"],
            obligation_type      = row["obligation_type"],
            trigger_event_id     = row["trigger_event_id"],
            required_event_types = json.loads(row["required_event_types"] or "[]"),
            rule_id              = row["rule_id"] if "rule_id" in row.keys() else None,
            due_at               = row["due_at"],
            grace_period_secs    = row["grace_period_secs"] or 0.0,
            hard_overdue_secs    = row["hard_overdue_secs"] or 0.0,
            status               = ObligationStatus(row["status"]),
            fulfilled_by_event_id= row["fulfilled_by_event_id"],
            violation_code       = row["violation_code"],
            severity             = Severity(row["severity"]),
            escalation_policy    = ep,
            escalated            = bool(row["escalated"]),
            escalated_at         = row["escalated_at"],
            reminder_sent_at     = row["reminder_sent_at"],
            notes                = row["notes"] or "",
            created_at           = row["created_at"],
            updated_at           = row["updated_at"],
            session_id           = row["session_id"] if "session_id" in row.keys() else None,
            cancelled_at         = row["cancelled_at"] if "cancelled_at" in row.keys() else None,
            cancellation_reason  = row["cancellation_reason"] if "cancellation_reason" in row.keys() else None,
            # v0.33: two-phase timeout
            soft_violation_at    = row["soft_violation_at"] if "soft_violation_at" in row.keys() else None,
            hard_violation_at    = row["hard_violation_at"] if "hard_violation_at" in row.keys() else None,
            soft_count           = row["soft_count"] if "soft_count" in row.keys() else 0,
            # v0.43: restoration
            restored_at          = row["restored_at"] if "restored_at" in row.keys() else None,
            restored_by_event_id = row["restored_by_event_id"] if "restored_by_event_id" in row.keys() else None,
            restoration_grace_period_multiplier = row["restoration_grace_period_multiplier"] if "restoration_grace_period_multiplier" in row.keys() else 2.0,
        )

    # ── GovernanceEvent ────────────────────────────────────────────────────

    def add_event(self, ev: GovernanceEvent) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO governance_events VALUES (?,?,?,?,?,?,?,?)
            """, (
                ev.event_id, ev.event_type, ev.entity_id, ev.actor_id,
                ev.ts, json.dumps(ev.payload), ev.source, ev.lineage_ref,
            ))

    def get_event(self, event_id: str) -> Optional[GovernanceEvent]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM governance_events WHERE event_id=?", (event_id,)
            ).fetchone()
        return self._row_to_event(row) if row else None

    def events_for_entity(
        self,
        entity_id: str,
        event_types: Optional[List[str]] = None,
    ) -> List[GovernanceEvent]:
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            with self._conn() as conn:
                rows = conn.execute(
                    f"SELECT * FROM governance_events "
                    f"WHERE entity_id=? AND event_type IN ({placeholders}) "
                    f"ORDER BY ts",
                    [entity_id] + event_types,
                ).fetchall()
        else:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM governance_events WHERE entity_id=? ORDER BY ts",
                    (entity_id,),
                ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def has_event_of_type(self, entity_id: str, event_type: str) -> bool:
        with self._conn() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM governance_events "
                "WHERE entity_id=? AND event_type=?",
                (entity_id, event_type),
            ).fetchone()[0]
        return n > 0

    def has_any_event_of_types(self, entity_id: str, event_types: List[str]) -> bool:
        return any(self.has_event_of_type(entity_id, et) for et in event_types)

    def _row_to_event(self, row: sqlite3.Row) -> GovernanceEvent:
        return GovernanceEvent(
            event_id   = row["event_id"],
            event_type = row["event_type"],
            entity_id  = row["entity_id"],
            actor_id   = row["actor_id"],
            ts         = row["ts"],
            payload    = json.loads(row["payload_json"] or "{}"),
            source     = row["source"],
            lineage_ref= row["lineage_ref"],
        )

    # ── OmissionViolation ──────────────────────────────────────────────────

    def add_violation(self, v: OmissionViolation) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO omission_violations VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                v.violation_id, v.entity_id, v.obligation_id, v.actor_id,
                v.omission_type, v.detected_at, v.overdue_secs,
                v.severity.value, json.dumps(v.details),
                1 if v.escalated else 0, v.escalated_to, v.cieu_ref,
            ))

    def update_violation(self, v: OmissionViolation) -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE omission_violations SET
                    escalated=?, escalated_to=?, cieu_ref=?
                WHERE violation_id=?
            """, (1 if v.escalated else 0, v.escalated_to, v.cieu_ref,
                  v.violation_id))

    def list_violations(
        self,
        entity_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        omission_type: Optional[str] = None,
        escalated: Optional[bool] = None,
    ) -> List[OmissionViolation]:
        conds, params = [], []
        if entity_id:
            conds.append("entity_id=?"); params.append(entity_id)
        if actor_id:
            conds.append("actor_id=?"); params.append(actor_id)
        if omission_type:
            conds.append("omission_type=?"); params.append(omission_type)
        if escalated is not None:
            conds.append("escalated=?"); params.append(1 if escalated else 0)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM omission_violations {where}", params
            ).fetchall()
        return [self._row_to_violation(r) for r in rows]

    def _row_to_violation(self, row: sqlite3.Row) -> OmissionViolation:
        return OmissionViolation(
            violation_id  = row["violation_id"],
            entity_id     = row["entity_id"],
            obligation_id = row["obligation_id"],
            actor_id      = row["actor_id"],
            omission_type = row["omission_type"],
            detected_at   = row["detected_at"],
            overdue_secs  = row["overdue_secs"] or 0.0,
            severity      = Severity(row["severity"]),
            details       = json.loads(row["details_json"] or "{}"),
            escalated     = bool(row["escalated"]),
            escalated_to  = row["escalated_to"],
            cieu_ref      = row["cieu_ref"],
        )

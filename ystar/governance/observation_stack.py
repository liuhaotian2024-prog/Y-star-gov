# Layer: Observation / Situation Awareness
"""
ystar.governance.observation_stack
===================================

L0 ObservationStack for Counterfactual CZL.

Purpose:
  Build an auditable Xt snapshot before Y* projection and U selection.

This module is intentionally read-only. It does not mutate CIEU, memory,
brain, omission, or goal tables. It only detects whether local assets exist
and reads lightweight counts when SQLite tables are present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3
import time


@dataclass
class XtSnapshot:
    """Auditable observation snapshot for one CZL loop."""

    snapshot_id: str
    created_at: float
    role_id: str
    agent_id: str
    task_id: Optional[str] = None
    goal_id: Optional[str] = None

    local_context: Dict[str, Any] = field(default_factory=dict)
    code_state: Dict[str, Any] = field(default_factory=dict)
    cieu_state: Dict[str, Any] = field(default_factory=dict)
    memory_state: Dict[str, Any] = field(default_factory=dict)
    brain_state: Dict[str, Any] = field(default_factory=dict)
    omission_state: Dict[str, Any] = field(default_factory=dict)
    goal_state: Dict[str, Any] = field(default_factory=dict)
    agent_team_state: Dict[str, Any] = field(default_factory=dict)
    resource_state: Dict[str, Any] = field(default_factory=dict)

    stale_fields: List[str] = field(default_factory=list)
    confidence: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "role_id": self.role_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "local_context": self.local_context,
            "code_state": self.code_state,
            "cieu_state": self.cieu_state,
            "memory_state": self.memory_state,
            "brain_state": self.brain_state,
            "omission_state": self.omission_state,
            "goal_state": self.goal_state,
            "agent_team_state": self.agent_team_state,
            "resource_state": self.resource_state,
            "stale_fields": self.stale_fields,
            "confidence": self.confidence,
        }


class ObservationStack:
    """Read-only local observation stack.

    L0 scope:
      - repo/code presence checks
      - SQLite table existence/count checks
      - goal table detection if present in CIEU DB
      - conservative confidence scores

    Future layers may add git status, pytest status, external world sensors,
    and model-assisted summarization. L0 must remain deterministic.
    """

    def __init__(
        self,
        repo_root: str | Path = ".",
        cieu_db: str | Path = ".ystar_cieu.db",
        memory_db: str | Path = ".ystar_memory.db",
        omission_db: str | Path = ".ystar_omission.db",
        brain_db: str | Path = "aiden_brain.db",
    ) -> None:
        self.repo_root = Path(repo_root)
        self.cieu_db = self._resolve_db(cieu_db)
        self.memory_db = self._resolve_db(memory_db)
        self.omission_db = self._resolve_db(omission_db)
        self.brain_db = self._resolve_db(brain_db)

    def _resolve_db(self, path: str | Path) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return self.repo_root / p

    def build(
        self,
        role_id: str,
        agent_id: str,
        task_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        prompt_context: Optional[str] = None,
    ) -> XtSnapshot:
        now = time.time()
        snap = XtSnapshot(
            snapshot_id=f"xt_{time.time_ns()}",
            created_at=now,
            role_id=role_id,
            agent_id=agent_id,
            task_id=task_id,
            goal_id=goal_id,
            local_context={"prompt_context": prompt_context or ""},
        )

        snap.code_state = self._read_code_state()
        snap.cieu_state = self._read_cieu_state()
        snap.memory_state = self._read_memory_state(agent_id)
        snap.brain_state = self._read_brain_state()
        snap.omission_state = self._read_omission_state()
        snap.goal_state = self._read_goal_state(goal_id)
        snap.resource_state = self._read_resource_state()
        snap.stale_fields = self._compute_stale_fields(snap)
        snap.confidence = self._compute_confidence(snap)
        return snap

    def _read_code_state(self) -> Dict[str, Any]:
        return {
            "repo_root": str(self.repo_root),
            "repo_root_exists": self.repo_root.exists(),
            "pyproject_exists": (self.repo_root / "pyproject.toml").exists(),
            "ystar_package_exists": (self.repo_root / "ystar").exists(),
            "governance_package_exists": (self.repo_root / "ystar" / "governance").exists(),
            "tests_dir_exists": (self.repo_root / "tests").exists(),
            "asset_map_exists": (self.repo_root / "docs" / "arch" / "counterfactual_czl_asset_map.md").exists(),
        }

    def _connect(self, db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, db_path: Path, table: str) -> bool:
        if not db_path.exists():
            return False
        try:
            with self._connect(db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                return bool(row and row["n"] > 0)
        except sqlite3.Error:
            return False

    def _safe_count(self, db_path: Path, table: str) -> Optional[int]:
        if not db_path.exists():
            return None
        if not self._table_exists(db_path, table):
            return None
        try:
            with self._connect(db_path) as conn:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                return int(row["n"]) if row else 0
        except sqlite3.Error:
            return None

    def _read_cieu_state(self) -> Dict[str, Any]:
        return {
            "db_path": str(self.cieu_db),
            "db_exists": self.cieu_db.exists(),
            "cieu_events_exists": self._table_exists(self.cieu_db, "cieu_events"),
            "sealed_sessions_exists": self._table_exists(self.cieu_db, "sealed_sessions"),
            "event_count": self._safe_count(self.cieu_db, "cieu_events"),
            "sealed_session_count": self._safe_count(self.cieu_db, "sealed_sessions"),
        }

    def _read_memory_state(self, agent_id: str) -> Dict[str, Any]:
        return {
            "db_path": str(self.memory_db),
            "db_exists": self.memory_db.exists(),
            "memories_exists": self._table_exists(self.memory_db, "memories"),
            "agents_exists": self._table_exists(self.memory_db, "agents"),
            "access_log_exists": self._table_exists(self.memory_db, "access_log"),
            "memory_count": self._safe_count(self.memory_db, "memories"),
            "agent_count": self._safe_count(self.memory_db, "agents"),
            "agent_id": agent_id,
        }

    def _read_brain_state(self) -> Dict[str, Any]:
        return {
            "db_path": str(self.brain_db),
            "db_exists": self.brain_db.exists(),
            "nodes_exists": self._table_exists(self.brain_db, "nodes"),
            "edges_exists": self._table_exists(self.brain_db, "edges"),
            "activation_log_exists": self._table_exists(self.brain_db, "activation_log"),
            "node_count": self._safe_count(self.brain_db, "nodes"),
            "edge_count": self._safe_count(self.brain_db, "edges"),
            "activation_count": self._safe_count(self.brain_db, "activation_log"),
        }

    def _read_omission_state(self) -> Dict[str, Any]:
        return {
            "db_path": str(self.omission_db),
            "db_exists": self.omission_db.exists(),
            "entities_exists": self._table_exists(self.omission_db, "entities"),
            "obligations_exists": self._table_exists(self.omission_db, "obligations"),
            "omission_violations_exists": self._table_exists(self.omission_db, "omission_violations"),
            "entity_count": self._safe_count(self.omission_db, "entities"),
            "obligation_count": self._safe_count(self.omission_db, "obligations"),
            "violation_count": self._safe_count(self.omission_db, "omission_violations"),
        }

    def _read_goal_state(self, goal_id: Optional[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "source_db": str(self.cieu_db),
            "goal_table_exists": self._table_exists(self.cieu_db, "ystar_goal_tree"),
            "contribution_table_exists": self._table_exists(self.cieu_db, "cieu_goal_contribution"),
            "goal_count": self._safe_count(self.cieu_db, "ystar_goal_tree"),
            "contribution_count": self._safe_count(self.cieu_db, "cieu_goal_contribution"),
            "requested_goal_id": goal_id,
        }

        if goal_id and out["goal_table_exists"]:
            try:
                with self._connect(self.cieu_db) as conn:
                    row = conn.execute(
                        """
                        SELECT goal_id, parent_goal_id, goal_text, y_star_definition,
                               owner_role, status, weight
                        FROM ystar_goal_tree
                        WHERE goal_id = ?
                        """,
                        (goal_id,),
                    ).fetchone()
                    if row:
                        out["active_goal"] = dict(row)
            except sqlite3.Error as exc:
                out["goal_query_error"] = str(exc)

        return out

    def _read_resource_state(self) -> Dict[str, Any]:
        return {
            "timestamp": time.time(),
            "mode": "local",
            "observation_stack_version": "L0",
        }

    def _compute_stale_fields(self, snap: XtSnapshot) -> List[str]:
        stale: List[str] = []
        if not snap.cieu_state.get("db_exists"):
            stale.append("cieu_state")
        if not snap.memory_state.get("db_exists"):
            stale.append("memory_state")
        if not snap.omission_state.get("db_exists"):
            stale.append("omission_state")
        if not snap.brain_state.get("db_exists"):
            stale.append("brain_state")
        if not snap.goal_state.get("goal_table_exists"):
            stale.append("goal_state")
        return stale

    def _compute_confidence(self, snap: XtSnapshot) -> Dict[str, float]:
        return {
            "code_state": 0.9 if snap.code_state.get("governance_package_exists") else 0.3,
            "cieu_state": 0.9 if snap.cieu_state.get("cieu_events_exists") else 0.3,
            "memory_state": 0.85 if snap.memory_state.get("memories_exists") else 0.3,
            "brain_state": 0.75 if snap.brain_state.get("activation_log_exists") else 0.3,
            "omission_state": 0.8 if snap.omission_state.get("obligations_exists") else 0.3,
            "goal_state": 0.8 if snap.goal_state.get("goal_table_exists") else 0.3,
        }

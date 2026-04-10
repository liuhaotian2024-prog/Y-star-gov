"""
autonomy_engine.py — GOV-010 Phase 3

AutonomyEngine wraps OmissionEngine and adds desire-driven governance:
agents can declare their own intents (not just react to Board directives),
report progress, and the engine can detect stalled tasks and map cognitive
gaps across roles.

Architecture decision (Board, non-negotiable):
  OmissionEngine is a submodule of AutonomyEngine. External users see
  one engine. Internal routing depends on mode:
    - conservative: OmissionEngine semantics only (obligation tracking)
    - desire-driven: OmissionEngine + self-directed intent tracking

Both modes write CIEU. The audit chain is unified.

Usage::

    from ystar.governance.autonomy_engine import AutonomyEngine

    engine = AutonomyEngine(mode="desire-driven")

    # OmissionEngine is still accessible:
    engine.omission_engine.register_entity(...)
    engine.omission_engine.ingest_event(...)

    # New desire-driven methods:
    intent = engine.declare_intent(actor="cto", task="build theory lib",
                                   steps=4, estimate_minutes=60)
    engine.update_progress(intent["task_id"], step=2, note="halfway")
    stalled = engine.scan_stalled()
    gaps = engine.get_gap_map("cto")
"""
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_models import GEventType


class AutonomyEngine:
    """Unified governance engine: obligation tracking + desire-driven autonomy.

    Parameters
    ----------
    mode : str
        "conservative" — only OmissionEngine; desire-driven methods are no-ops.
        "desire-driven" — full AutonomyEngine capabilities.
    omission_engine : OmissionEngine, optional
        Inject a pre-configured OmissionEngine. If None, one is created
        with default settings (SQLite store, built-in rules).
    stall_multiplier : float
        A task is "stalled" if time since last update exceeds
        estimate_minutes * stall_multiplier. Default 2.0.
    knowledge_root : Path or str
        Root of the knowledge directory tree (for gap_map scanning).
        Default: current working directory / "knowledge".
    cieu_store : Any, optional
        CIEUStore for writing autonomy events. If None, events are
        tracked in-memory only (not recommended for production).
    """

    VALID_MODES = ("conservative", "desire-driven")

    def __init__(
        self,
        mode: str = "desire-driven",
        omission_engine: Optional[OmissionEngine] = None,
        stall_multiplier: float = 2.0,
        knowledge_root: Optional[Any] = None,
        cieu_store: Any = None,
    ) -> None:
        if mode not in self.VALID_MODES:
            raise ValueError(
                f"mode must be one of {self.VALID_MODES}, got {mode!r}"
            )
        self.mode = mode
        self.omission_engine = omission_engine or OmissionEngine()
        self.stall_multiplier = stall_multiplier
        self.knowledge_root = Path(knowledge_root or "knowledge")
        self.cieu_store = cieu_store

        # In-memory intent registry (keyed by task_id).
        # In production, this would be backed by the CIEU store or a
        # dedicated SQLite table. For Phase 3 MVP, in-memory is sufficient
        # because active_task.py (Labs side) already persists to
        # knowledge/{role}/active_task.json.
        self._intents: dict[str, dict] = {}

    # ─── Desire-driven methods ───────────────────────────────────────

    def declare_intent(
        self,
        actor: str,
        task: str,
        steps: int = 1,
        estimate_minutes: int = 30,
    ) -> dict:
        """Agent declares intent to start a self-directed task.

        Returns the intent dict (includes task_id for subsequent calls).
        Writes INTENT_DECLARED to CIEU if cieu_store is available.
        In conservative mode, this is a no-op that returns an empty dict.
        """
        if self.mode == "conservative":
            return {}

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        intent = {
            "task_id": task_id,
            "actor": actor,
            "task": task,
            "steps": steps,
            "current_step": 0,
            "estimate_minutes": estimate_minutes,
            "status": "active",
            "declared_at": now,
            "last_update": now,
        }
        self._intents[task_id] = intent
        self._write_event(GEventType.INTENT_DECLARED, actor, {
            "task_id": task_id,
            "task": task,
            "steps": steps,
            "estimate_minutes": estimate_minutes,
        })
        return intent

    def update_progress(
        self,
        task_id: str,
        step: int,
        note: str = "",
    ) -> dict:
        """Report progress on an active intent.

        Returns the updated intent dict. No-op in conservative mode.
        """
        if self.mode == "conservative":
            return {}
        intent = self._intents.get(task_id)
        if not intent or intent["status"] != "active":
            return {"error": f"no active intent with task_id={task_id}"}

        intent["current_step"] = step
        intent["last_update"] = time.time()
        self._write_event(GEventType.PROGRESS_UPDATED, intent["actor"], {
            "task_id": task_id,
            "step": step,
            "total_steps": intent["steps"],
            "note": note,
        })
        return intent

    def complete_intent(self, task_id: str, output: str = "", note: str = "") -> dict:
        """Mark an intent as completed.

        Returns the final intent dict. No-op in conservative mode.
        """
        if self.mode == "conservative":
            return {}
        intent = self._intents.get(task_id)
        if not intent or intent["status"] != "active":
            return {"error": f"no active intent with task_id={task_id}"}

        now = time.time()
        intent["status"] = "completed"
        intent["completed_at"] = now
        intent["duration_s"] = now - intent["declared_at"]
        intent["output"] = output
        self._write_event(GEventType.INTENT_COMPLETED, intent["actor"], {
            "task_id": task_id,
            "task": intent["task"],
            "output": output,
            "duration_s": intent["duration_s"],
            "note": note,
        })
        return intent

    def scan_stalled(self) -> list[dict]:
        """Return list of intents that have stalled.

        A task is stalled if:
          time_since_last_update > estimate_minutes * stall_multiplier * 60

        In conservative mode, returns empty list.
        """
        if self.mode == "conservative":
            return []
        now = time.time()
        stalled = []
        for intent in self._intents.values():
            if intent["status"] != "active":
                continue
            threshold = intent["estimate_minutes"] * self.stall_multiplier * 60
            if (now - intent["last_update"]) > threshold:
                intent["status"] = "stalled"
                stalled.append(intent)
                self._write_event(GEventType.INTENT_STALLED, intent["actor"], {
                    "task_id": intent["task_id"],
                    "task": intent["task"],
                    "last_update_age_s": now - intent["last_update"],
                    "threshold_s": threshold,
                })
        return stalled

    def get_gap_map(self, actor: str) -> dict:
        """Return a map of task-type → theory-library status for a role.

        Scans knowledge/{actor}/role_definition/task_type_map.md and
        checks which task types have corresponding files in
        knowledge/{actor}/theory/.

        Returns:
            {
                "actor": "cto",
                "total_task_types": 10,
                "with_theory": 3,
                "without_theory": 7,
                "gap_list": ["type_a", "type_b", ...],
                "covered_list": ["type_c", ...],
            }
        """
        role_dir = self.knowledge_root / actor
        theory_dir = role_dir / "theory"
        task_map = role_dir / "role_definition" / "task_type_map.md"

        if not task_map.exists():
            return {
                "actor": actor,
                "total_task_types": 0,
                "with_theory": 0,
                "without_theory": 0,
                "gap_list": [],
                "covered_list": [],
                "error": "task_type_map.md not found",
            }

        # Parse task types from the map file (look for ## N. lines)
        import re
        text = task_map.read_text()
        task_names = re.findall(r"^## \d+\.\s+(.+)$", text, re.MULTILINE)

        # Normalize to snake_case for file matching
        def to_snake(name: str) -> str:
            return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_",
                         name.lower().strip()).strip("_")

        # Check which have theory files
        theory_files = set()
        if theory_dir.exists():
            for f in theory_dir.iterdir():
                if f.suffix == ".md" and f.name != "README.md":
                    theory_files.add(f.stem.lower())

        covered = []
        gaps = []
        for name in task_names:
            snake = to_snake(name)
            if snake in theory_files or name.lower() in theory_files:
                covered.append(name)
            else:
                gaps.append(name)

        result = {
            "actor": actor,
            "total_task_types": len(task_names),
            "with_theory": len(covered),
            "without_theory": len(gaps),
            "gap_list": gaps,
            "covered_list": covered,
        }

        # Write GAP_IDENTIFIED events for newly discovered gaps
        for gap_name in gaps:
            self._write_event(GEventType.GAP_IDENTIFIED, actor, {
                "task_type": gap_name,
                "status": "no_theory_file",
            })

        return result

    # ─── Internal helpers ────────────────────────────────────────────

    def _write_event(self, event_type: str, actor: str, params: dict):
        """Write a CIEU event if cieu_store is available. Fail-open."""
        if self.cieu_store is None:
            return
        try:
            record = {
                "event_id": str(uuid.uuid4()),
                "session_id": params.get("task_id", "autonomy_engine"),
                "agent_id": actor,
                "event_type": event_type,
                "decision": "info",
                "evidence_grade": "ops",
                "created_at": time.time(),
                "seq_global": time.time_ns() // 1000,
                "params": params,
                "violations": [],
                "drift_detected": False,
                "human_initiator": actor,
            }
            self.cieu_store.write_dict(record)
        except Exception:
            pass  # fail-open

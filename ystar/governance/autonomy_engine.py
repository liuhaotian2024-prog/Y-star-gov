"""
autonomy_engine.py — GOV-010 Phase 3 + AMENDMENT-014

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

AMENDMENT-014 (2026-04-12):
  Merged AutonomyDriver (ADE) functionality into AutonomyEngine:
    - pull_next_action / recompute_action_queue (prescriptive action queue)
    - detect_off_target (daily_target deviation detection)
    - claim_orphan_obligations (auto-assign orphan obligations)

Usage::

    from ystar.governance.autonomy_engine import AutonomyEngine

    engine = AutonomyEngine(mode="desire-driven")

    # OmissionEngine is still accessible:
    engine.omission_engine.register_entity(...)
    engine.omission_engine.ingest_event(...)

    # Desire-driven methods:
    intent = engine.declare_intent(actor="cto", task="build theory lib",
                                   steps=4, estimate_minutes=60)
    engine.update_progress(intent["task_id"], step=2, note="halfway")
    stalled = engine.scan_stalled()
    gaps = engine.get_gap_map("cto")

    # Prescriptive action queue (AMENDMENT-014):
    action = engine.pull_next_action(agent_id="cto")
    engine.recompute_action_queue(agent_id="cto")
    is_off = engine.detect_off_target(agent_id="cto", current_action="X")
    engine.claim_orphan_obligations()
"""
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_models import GEventType, ObligationStatus


# ── Action Model ──────────────────────────────────────────────────────────────

@dataclass
class Action:
    """Single action item (prescriptive queue entry)."""
    action_id: str
    description: str
    why: str  # why do this
    verify: str  # how to verify completion
    on_fail: str  # what to do on failure
    priority: int = 0  # lower = higher priority
    tags: List[str] = field(default_factory=list)
    source: str = "unknown"  # source: daily_target / obligation / orphan


@dataclass
class PriorityBrief:
    """Priority brief structure (parsed from reports/priority_brief.md)."""
    today_targets: List[str] = field(default_factory=list)
    this_week_targets: List[str] = field(default_factory=list)
    this_month_targets: List[str] = field(default_factory=list)
    campaign: Optional[str] = None
    day: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


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
        role_capabilities: Optional[Dict[str, List[str]]] = None,
        priority_brief_path: str = "reports/priority_brief.md",
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

        # AMENDMENT-014: Prescriptive action queue (from AutonomyDriver)
        self.role_capabilities = role_capabilities or self._default_capabilities()
        self.priority_brief_path = Path(priority_brief_path)
        self.action_queues: Dict[str, List[Action]] = {}  # agent_id → action_queue

    @staticmethod
    def _default_capabilities() -> Dict[str, List[str]]:
        """Default role capabilities."""
        return {
            "ceo": ["delegation", "coordination", "reporting", "board_interface"],
            "cto": ["code", "test", "architecture", "git", "debug"],
            "cmo": ["content", "blog", "marketing", "social_media"],
            "cso": ["sales", "lead_gen", "crm", "patent"],
            "cfo": ["finance", "pricing", "token", "budget"],
            "eng-kernel": ["kernel", "causal_engine", "pulse", "meta_learning"],
            "eng-governance": ["governance", "omission_engine", "intervention", "rules"],
            "eng-platform": ["platform", "mcp", "cli", "adapters"],
            "eng-domains": ["domains", "domain_packs", "industry_rules"],
        }

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

    # ─── Prescriptive Action Queue (AMENDMENT-014) ──────────────────

    def pull_next_action(self, agent_id: str) -> Optional[Action]:
        """
        Pull next action from action_queue.

        If queue is empty, auto recompute.
        Returns None if no actions available after recompute.
        """
        if agent_id not in self.action_queues or not self.action_queues[agent_id]:
            self.recompute_action_queue(agent_id)

        queue = self.action_queues.get(agent_id, [])
        if not queue:
            return None

        # Pop highest priority (lowest priority value)
        action = queue.pop(0)
        self._write_event(GEventType.ACTION_PULLED, agent_id, {
            "action_id": action.action_id,
            "description": action.description,
            "source": action.source,
        })
        return action

    def recompute_action_queue(self, agent_id: str):
        """
        Recompute action queue for agent.

        Algorithm:
          1. Parse priority_brief → extract today_targets
          2. Read pending obligations from omission_engine
          3. Filter by role_capabilities
          4. Sort by priority (daily → obligation → weekly)
        """
        brief = self._load_priority_brief()
        actions: List[Action] = []

        # 1. today_targets → actions (priority=0, highest)
        for idx, target in enumerate(brief.today_targets):
            actions.append(Action(
                action_id=f"daily_{idx}",
                description=target,
                why="daily_target",
                verify="check completion in DISPATCH.md",
                on_fail="escalate to CEO if blocked",
                priority=0,
                tags=["daily_target"],
                source="priority_brief"
            ))

        # 2. pending obligations → actions (priority=1)
        pending = self._get_pending_obligations(agent_id)
        for obl in pending:
            description = obl.notes if obl.notes else f"{obl.obligation_type} for {obl.entity_id}"
            actions.append(Action(
                action_id=obl.obligation_id,
                description=description,
                why=f"obligation {obl.obligation_type}",
                verify="check obligation fulfillment event",
                on_fail="report to CEO",
                priority=1,
                tags=["obligation", obl.obligation_type],
                source="obligation_backlog"
            ))

        # 3. this_week_targets → actions (priority=2)
        for idx, target in enumerate(brief.this_week_targets):
            actions.append(Action(
                action_id=f"weekly_{idx}",
                description=target,
                why="weekly_target",
                verify="check weekly progress",
                on_fail="adjust timeline",
                priority=2,
                tags=["weekly_target"],
                source="priority_brief"
            ))

        # Sort by priority ascending
        actions.sort(key=lambda a: a.priority)
        self.action_queues[agent_id] = actions

    def detect_off_target(self, agent_id: str, current_action: str) -> bool:
        """
        Detect if current_action deviates from daily_target.

        Returns:
          - True: OFF_TARGET (current action not in daily_targets)
          - False: ON_TARGET
        """
        brief = self._load_priority_brief()
        if not brief.today_targets:
            return False  # No targets, cannot be off-target

        # Simple keyword matching
        current_lower = current_action.lower()
        for target in brief.today_targets:
            target_lower = target.lower()
            # Extract keywords (words > 3 chars)
            keywords = [w for w in target_lower.split() if len(w) > 3]
            if any(kw in current_lower for kw in keywords):
                return False  # ON_TARGET

        # OFF_TARGET detected
        self._write_event("OFF_TARGET_WARNING", agent_id, {
            "current_action": current_action,
            "daily_targets": brief.today_targets,
        })
        return True

    def claim_orphan_obligations(self):
        """
        Auto-claim orphan obligations (actor_id="").

        Algorithm:
          1. Read all pending obligations from omission_engine
          2. Find orphans (actor_id="" or None)
          3. Infer owner from obligation_type
          4. Update obligation.actor_id
        """
        store = self.omission_engine.store
        all_obligations = store.list_obligations()
        orphans = [o for o in all_obligations if not o.actor_id and o.status == ObligationStatus.PENDING]

        if not orphans:
            return

        claimed_count = 0
        for orphan in orphans:
            actor = self._infer_owner(orphan.obligation_type)
            if actor:
                orphan.actor_id = actor
                store.update_obligation(orphan)
                claimed_count += 1
                self._write_event("ORPHAN_CLAIMED", actor, {
                    "obligation_id": orphan.obligation_id,
                    "obligation_type": orphan.obligation_type,
                })

    def get_action_queue_summary(self, agent_id: str) -> str:
        """Return action_queue summary (for boot_packages.category_11)."""
        if agent_id not in self.action_queues or not self.action_queues[agent_id]:
            self.recompute_action_queue(agent_id)

        queue = self.action_queues.get(agent_id, [])
        if not queue:
            return "No actions queued"

        lines = []
        for i, action in enumerate(queue[:5], 1):  # Show first 5
            lines.append(f"  [{i}] {action.description[:60]}")
            lines.append(f"      why: {action.why}, verify: {action.verify[:40]}")
        if len(queue) > 5:
            lines.append(f"  ... and {len(queue) - 5} more")
        return "\n".join(lines)

    # ─── Private Helpers (AMENDMENT-014) ─────────────────────────────

    def _load_priority_brief(self) -> PriorityBrief:
        """Parse priority_brief.md into structured data."""
        if not self.priority_brief_path.exists():
            return PriorityBrief()

        content = self.priority_brief_path.read_text(encoding="utf-8")
        brief = PriorityBrief()

        # Parse today_targets
        today_match = re.search(r"today_targets:\s*\n((?:  - .+\n?)+)", content, re.MULTILINE)
        if today_match:
            lines = today_match.group(1).strip().split("\n")
            brief.today_targets = [line.strip("- ").strip() for line in lines]

        # Parse this_week_targets
        week_match = re.search(r"this_week_targets:\s*\n((?:  - .+\n?)+)", content, re.MULTILINE)
        if week_match:
            lines = week_match.group(1).strip().split("\n")
            brief.this_week_targets = [line.strip("- ").strip() for line in lines]

        # Parse this_month_targets
        month_match = re.search(r"this_month_targets:\s*\n((?:  - .+\n?)+)", content, re.MULTILINE)
        if month_match:
            lines = month_match.group(1).strip().split("\n")
            brief.this_month_targets = [line.strip("- ").strip() for line in lines]

        # Parse campaign
        campaign_match = re.search(r"campaign:\s*(.+)", content)
        if campaign_match:
            brief.campaign = campaign_match.group(1).strip()

        # Parse day
        day_match = re.search(r"day:\s*(\d+)", content)
        if day_match:
            brief.day = int(day_match.group(1))

        return brief

    def _get_pending_obligations(self, agent_id: str) -> List[Any]:
        """Get pending obligations from omission_engine for agent_id."""
        store = self.omission_engine.store
        return store.list_obligations(
            actor_id=agent_id,
            status=ObligationStatus.PENDING
        )

    def _infer_owner(self, obligation_type: str) -> Optional[str]:
        """Infer owner from obligation_type (simple heuristic)."""
        type_lower = obligation_type.lower()
        if any(kw in type_lower for kw in ["ceo", "delegation", "coordination"]):
            return "ceo"
        elif any(kw in type_lower for kw in ["cto", "bug", "test", "code"]):
            return "cto"
        elif any(kw in type_lower for kw in ["cmo", "content", "blog", "article"]):
            return "cmo"
        elif any(kw in type_lower for kw in ["cso", "sales", "lead"]):
            return "cso"
        elif any(kw in type_lower for kw in ["cfo", "finance", "token"]):
            return "cfo"
        elif "kernel" in type_lower:
            return "eng-kernel"
        elif "governance" in type_lower:
            return "eng-governance"
        elif "platform" in type_lower:
            return "eng-platform"
        elif "domains" in type_lower:
            return "eng-domains"
        else:
            return None

    # ─── Internal helpers (original) ─────────────────────────────────

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

# Layer: Path B
"""
ystar.path_b.path_b_agent — Path B: External Governance Agent (Layer 3)

Path A governs Y*gov's own improvement (internal).
Path B governs external agents using the same architectural pattern (external).

Core design: observation_to_constraint() IS IntentContract
Same trust mechanism as Path A:
- Goals derived from external observation, not self-defined
- Every action writes to CIEU
- Cannot expand own authority (ConstraintBudget monotonicity)
- Failure → disconnect external agent

Philosophy: "Who governs the governors?"
Path B governs external agents with the same framework Path A uses to govern itself.
The symmetry is the proof — if Path A can't escape its bounds, neither can external agents.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any, Dict, Callable
import hashlib, time, uuid, os

from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import check, CheckResult
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.amendment import AmendmentEngine


# ── Constitution hash — computed once at import time ─────────────────────────
# TODO: Constitution loading should eventually go through the Intent Compilation
# line (nl_to_contract / prefill) rather than being loaded directly here.
# For now, direct loading is acceptable since Path B needs its constitution at
# import time for hash verification.
_CONSTITUTION_PATH = os.path.join(os.path.dirname(__file__), "PATH_B_AGENTS.md")

def _compute_constitution_hash() -> str:
    """Compute SHA-256 hash of PATH_B_AGENTS.md. Returns empty string if file missing."""
    try:
        with open(_CONSTITUTION_PATH, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except (OSError, IOError):
        return ""

_CONSTITUTION_HASH: str = _compute_constitution_hash()


# ── Disconnect result (Item 6) ───────────────────────────────────────────────
@dataclass
class DisconnectResult:
    """Result of a real disconnect execution."""
    agent_id:       str = ""
    status:         str = "disconnected"  # "disconnected" / "already_disconnected" / "error"
    actions_taken:  List[str] = field(default_factory=list)
    frozen:         bool = False
    contract_downgraded: bool = False


# ── External Observation: What an external agent did ──────────────────────────
@dataclass
class ExternalObservation:
    """
    A record of what an external agent did.

    This is the Path B analog of MetaAgentCycle — captures the full context
    of one external agent action for causal analysis.

    Fields:
        agent_id:      external agent identifier
        session_id:    session context
        action_type:   "tool_call" / "file_write" / "command_exec" / etc.
        params:        action parameters (tool name, args, etc.)
        result:        action outcome
        contract:      the IntentContract that SHOULD have governed this action
        violations:    violations detected (if any)
        timestamp:     unix timestamp
        constraint_budget: remaining constraint budget (Path B's authority limit)
    """
    observation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_id:       str = ""
    session_id:     str = ""
    action_type:    str = ""
    params:         Dict[str, Any] = field(default_factory=dict)
    result:         Any = None
    contract:       Optional[IntentContract] = None
    violations:     List[Any] = field(default_factory=list)
    timestamp:      float = field(default_factory=time.time)
    constraint_budget: float = 1.0  # 1.0 = full authority, 0.0 = no authority left

    def has_violation(self) -> bool:
        return bool(self.violations)

    def severity_score(self) -> float:
        """Calculate total severity from violations."""
        if not self.violations:
            return 0.0
        return sum(getattr(v, 'severity', 0.8) for v in self.violations) / len(self.violations)

    def to_dict(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "agent_id":       self.agent_id,
            "session_id":     self.session_id,
            "action_type":    self.action_type,
            "params":         {k: str(v)[:300] for k, v in self.params.items()},
            "result":         str(self.result)[:300] if self.result else None,
            "has_violation":  self.has_violation(),
            "severity":       self.severity_score(),
            "timestamp":      self.timestamp,
            "budget":         self.constraint_budget,
        }


# ── Constraint Budget: Path B's Authority Limit ───────────────────────────────
@dataclass
class ConstraintBudget:
    """
    Prevents Path B from over-constraining external agents.

    Analog to DelegationChain monotonicity in Path A:
    - Path A cannot expand its own authority (governed by GovernanceLoop)
    - Path B cannot over-constrain (governed by ConstraintBudget)

    Design principle: Each constraint tightening consumes budget.
    When budget reaches zero, Path B must request human approval.

    Budget replenishment rules (human-in-the-loop):
    - Successful constraint (external agent complies, no new violations) → +0.1 budget
    - Failed constraint (external agent still violates) → no replenishment
    - Budget can never exceed 1.0
    - Budget starts at 1.0 for new external agents
    """
    agent_id:        str
    current_budget:  float = 1.0
    consumed_total:  float = 0.0
    replenished_total: float = 0.0
    last_update:     float = field(default_factory=time.time)
    history:         List[Tuple[float, str]] = field(default_factory=list)  # (delta, reason)
    # Item 4: Authority Boundary — only constrain dimensions actually observed in violations
    allowed_dimensions: List[str] = field(default_factory=list)

    def can_tighten(self, cost: float = 0.1) -> bool:
        """Check if Path B has enough budget to apply a constraint."""
        return self.current_budget >= cost

    def consume(self, amount: float, reason: str) -> bool:
        """
        Consume budget for a constraint action.
        Returns True if successful, False if insufficient budget.
        """
        if not self.can_tighten(amount):
            return False
        self.current_budget -= amount
        self.consumed_total += amount
        self.history.append((-amount, reason))
        self.last_update = time.time()
        return True

    def replenish(self, amount: float, reason: str) -> None:
        """Replenish budget (called when external agent successfully complies)."""
        old_budget = self.current_budget
        self.current_budget = min(1.0, self.current_budget + amount)
        actual_gain = self.current_budget - old_budget
        self.replenished_total += actual_gain
        self.history.append((actual_gain, reason))
        self.last_update = time.time()

    def update_allowed_dimensions(self, observations: List["ExternalObservation"]) -> None:
        """
        Item 4: Derive allowed_dimensions from actually observed violations.

        Path B can only constrain dimensions that were actually violated.
        This prevents Path B from inventing new constraint dimensions.
        """
        dims: set = set()
        for obs in observations:
            if obs.agent_id != self.agent_id:
                continue
            for v in obs.violations:
                dim = getattr(v, "dimension", "")
                if dim:
                    dims.add(dim)
        self.allowed_dimensions = sorted(dims)

    def is_dimension_allowed(self, dimension: str) -> bool:
        """Check if a constraint dimension is within the authority boundary."""
        if not self.allowed_dimensions:
            return True  # No restrictions yet (cold start)
        return dimension in self.allowed_dimensions

    def summary(self) -> str:
        return (f"ConstraintBudget(agent={self.agent_id}, "
                f"current={self.current_budget:.2f}, "
                f"consumed={self.consumed_total:.2f}, "
                f"replenished={self.replenished_total:.2f}, "
                f"allowed_dims={self.allowed_dimensions})")


# ── Core Function: Observation → Constraint ───────────────────────────────────
def observation_to_constraint(
    observation:     ExternalObservation,
    violation_history: List[ExternalObservation],
    budget:          ConstraintBudget,
    confidence_threshold: float = 0.65,
) -> Optional[IntentContract]:
    """
    Convert an external observation into a constraint (IntentContract).

    This is the Path B analog of suggestion_to_contract() in Path A.

    Design principle: Constraints are derived from observed violations,
    not from self-defined goals. Path B cannot invent new constraints —
    it can only tighten based on what actually happened.

    Constraint derivation rules:
    1. Identify violation pattern from observation + history
    2. Calculate confidence (higher confidence with more evidence)
    3. Check budget (Path B's authority limit)
    4. Generate minimal constraint to prevent recurrence

    Returns:
        IntentContract if constraint should be applied, None if:
        - No clear violation pattern
        - Confidence too low
        - Insufficient budget
    """
    if not observation.has_violation():
        return None  # No violation = no constraint needed

    # Collect evidence: similar violations in history
    similar_violations = [
        obs for obs in violation_history
        if obs.agent_id == observation.agent_id
        and obs.action_type == observation.action_type
        and obs.has_violation()
    ]

    evidence_count = len(similar_violations) + 1  # +1 for current observation
    confidence = min(0.95, 0.3 + (evidence_count * 0.1))  # More evidence = higher confidence

    # Cold-start bypass: if there are REAL violations in the current observation
    # but zero historical observations for this agent (new user), generate
    # constraint directly instead of requiring confidence buildup.
    # Requires severity >= 0.5 to avoid cold-start on trivial violations.
    # Cold-start: count PRIOR history, excluding the current observation itself
    prior_history = sum(
        1 for obs in violation_history
        if obs.agent_id == observation.agent_id
        and obs.observation_id != observation.observation_id
    )
    cold_start = (prior_history == 0
                  and observation.severity_score() >= 0.5)

    if not cold_start and confidence < confidence_threshold:
        return None  # Not confident enough to constrain

    # Calculate constraint cost based on severity
    severity = observation.severity_score()
    constraint_cost = 0.05 + (severity * 0.05)  # Higher severity = higher cost

    if not budget.can_tighten(constraint_cost):
        return None  # Insufficient budget

    # Item 4: Authority Boundary — filter violations to allowed dimensions
    if budget.allowed_dimensions:
        allowed_violations = [
            v for v in observation.violations
            if getattr(v, "dimension", "") in budget.allowed_dimensions
        ]
        if not allowed_violations:
            return None  # No violations in allowed dimensions
    else:
        allowed_violations = list(observation.violations)

    # Derive constraint from violation pattern
    deny_list = []
    deny_commands = []
    only_paths = []

    for v in allowed_violations:
        dimension = getattr(v, 'dimension', '')
        actual = getattr(v, 'actual', '')

        if dimension == 'deny' and actual:
            deny_list.append(str(actual)[:100])
        elif dimension == 'deny_commands' and actual:
            deny_commands.append(str(actual)[:100])
        elif dimension == 'only_paths' and actual:
            # Extract directory from violating path
            path = str(actual)
            if '/' in path:
                forbidden_dir = path.rsplit('/', 1)[0]
                if forbidden_dir and forbidden_dir not in ['.', '..']:
                    deny_list.append(forbidden_dir)

    # Merge with existing constraints from similar violations
    for obs in similar_violations[-3:]:  # Last 3 similar violations
        if obs.contract:
            deny_list.extend(obs.contract.deny or [])
            deny_commands.extend(obs.contract.deny_commands or [])

    # Deduplicate
    deny_list = list(set(deny_list))
    deny_commands = list(set(deny_commands))

    if not deny_list and not deny_commands:
        return None  # No actionable constraint

    # Consume budget
    if not budget.consume(constraint_cost, f"constraint for {observation.action_type}"):
        return None

    # Generate constraint
    contract = IntentContract(
        name=f"path_b:external:{observation.agent_id[:6]}:{uuid.uuid4().hex[:6]}",
        deny=deny_list,
        deny_commands=deny_commands,
        hash=f"path_b:{observation.observation_id}",
    )

    return contract


# ── External Governance Cycle ─────────────────────────────────────────────────
@dataclass
class ExternalGovernanceCycle:
    """
    One complete Path B governance cycle.

    Analog to MetaAgentCycle in Path A:
    - Observe external agent behavior
    - Derive constraint from observation
    - Apply constraint (write to CIEU)
    - Verify compliance in next cycle
    """
    cycle_id:        str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    observation:     Optional[ExternalObservation] = None
    constraint:      Optional[IntentContract] = None
    applied:         bool = False
    compliant:       bool = False
    cieu_ref:        Optional[str] = None
    timestamp:       float = field(default_factory=time.time)

    # Causal reasoning fields
    causal_confidence: float = 0.0
    counterfactual_gain: float = 0.0

    def to_dict(self) -> dict:
        return {
            "cycle_id":    self.cycle_id,
            "agent_id":    self.observation.agent_id if self.observation else None,
            "applied":     self.applied,
            "compliant":   self.compliant,
            "timestamp":   self.timestamp,
            "confidence":  self.causal_confidence,
        }


# ── Path B Agent ──────────────────────────────────────────────────────────────
class PathBAgent:
    """
    Path B: External Governance Agent.

    Mirrors PathAAgent architecture but directed OUTWARD:
    - Path A governs Y*gov's own module graph (internal)
    - Path B governs external agents' actions (external)

    Trust mechanism (identical to Path A):
    - Constraints derived from observation, not self-defined
    - Every action writes to CIEU (same audit trail as Path A)
    - Cannot expand own authority (ConstraintBudget monotonicity)
    - Failure → disconnect external agent (analog to Path A's HARD_OVERDUE)

    Usage:
        agent = PathBAgent(cieu_store, external_observation_stream)
        cycle = agent.run_one_cycle()

        if cycle.applied and not cycle.compliant:
            agent.disconnect_external_agent(cycle.observation.agent_id)
    """

    def __init__(
        self,
        cieu_store,
        confidence_threshold: float = 0.65,
        max_cycles:           int = 100,
        omission_store=None,
        constitution_provider: Optional[Callable[[str], str]] = None,
        amendment_engine: Optional[AmendmentEngine] = None,
    ):
        self.cieu_store = cieu_store
        self.confidence_threshold = confidence_threshold
        self.max_cycles = max_cycles
        self.omission_store = omission_store
        # Intent Compilation line provides constitution; direct loading is fallback only
        self._constitution_provider = constitution_provider
        self._amendment_engine = amendment_engine

        # Item 2: Constitution hash — loaded at init, verified each cycle
        self._constitution_hash: str = _CONSTITUTION_HASH

        # History tracking
        self._observation_history: List[ExternalObservation] = []
        self._cycle_history:       List[ExternalGovernanceCycle] = []

        # Budget tracking (one per external agent)
        self._budgets: Dict[str, ConstraintBudget] = {}

        # Active constraints (one per external agent)
        self._active_constraints: Dict[str, IntentContract] = {}

        # Item 3: Obligation / Inconclusive / Human Gate
        self._obligations: Dict[str, Dict[str, Any]] = {}   # agent_id -> obligation
        self._inconclusive_count: int = 0
        self._human_review_required: bool = False
        # Item 6: Frozen sessions
        self._frozen_sessions: Dict[str, bool] = {}   # agent_id -> frozen

        # GAP 1 FIX: Initialize OmissionEngine from omission_store (same pattern as PathAAgent)
        self.omission_engine = (
            OmissionEngine(store=self.omission_store, cieu_store=self.cieu_store)
            if self.omission_store else None
        )

    def observe(self, observation: ExternalObservation) -> None:
        """
        Record an external agent observation.
        This is the input to Path B's governance cycle.
        """
        self._observation_history.append(observation)

        # Initialize budget for new agents
        if observation.agent_id not in self._budgets:
            self._budgets[observation.agent_id] = ConstraintBudget(
                agent_id=observation.agent_id
            )

    def run_one_cycle(self) -> ExternalGovernanceCycle:
        """
        Execute one complete external governance cycle.

        Steps:
        0. Verify constitution hash (Item 2)
        1. Get latest observation with violations
        1b. Check HARD_OVERDUE obligations (Item 3)
        2. Derive constraint from observation + history
        3. Check() the constraint against Path B's own contract
        4. Apply constraint (write to CIEU)
        4b. Create verify_compliance obligation (Item 3)
        5. Return cycle record
        """
        cycle = ExternalGovernanceCycle()

        # Step 0 (Item 2): Verify constitution hash at cycle start + Amendment Response Chain
        # Intent Compilation line provides constitution; direct loading is fallback only
        if self._constitution_provider is not None:
            try:
                current_hash = self._constitution_provider(_CONSTITUTION_PATH)
            except Exception:
                current_hash = _compute_constitution_hash()
        else:
            current_hash = _compute_constitution_hash()
        if self._constitution_hash and current_hash and current_hash != self._constitution_hash:
            # Check if there's an approved amendment for this document
            amendment_authorized = False
            if self._amendment_engine is not None:
                amendment_authorized = self._amendment_engine.has_approved_amendment(
                    "PATH_B_AGENTS.md", current_hash,
                )
            if amendment_authorized:
                # Amendment was approved: accept the new hash
                self._constitution_hash = current_hash
                self._write_cieu(cycle, "CONSTITUTION_AMENDED", [])
            else:
                # Unauthorized change
                self._write_cieu(cycle, "unauthorized_constitution_change", [])
                return cycle  # Refuse to operate with tampered constitution

        # Step 1b (Item 3): Check for HARD_OVERDUE obligations → auto-disconnect
        self._check_overdue_obligations()

        # Step 1: Find observations that need governance
        violations = [obs for obs in self._observation_history if obs.has_violation()]
        if not violations:
            # Item 3: Track inconclusive (nothing to govern = inconclusive)
            self._track_inconclusive(cycle)
            return cycle  # Nothing to govern

        # Take most recent violation
        observation = violations[-1]
        cycle.observation = observation

        # Step 2: Get budget
        budget = self._budgets.get(observation.agent_id)
        if not budget:
            budget = ConstraintBudget(agent_id=observation.agent_id)
            self._budgets[observation.agent_id] = budget

        # Item 4: Update allowed dimensions from observed violations
        budget.update_allowed_dimensions(self._observation_history)

        # Step 3: Derive constraint
        constraint = observation_to_constraint(
            observation,
            [o for o in self._observation_history if o.agent_id == observation.agent_id],
            budget,
            self.confidence_threshold,
        )

        if not constraint:
            # No constraint derived (low confidence or insufficient budget)
            self._write_cieu(cycle, "NO_CONSTRAINT_DERIVED", [])
            # Item 3: Track INCONCLUSIVE
            self._track_inconclusive(cycle)
            return cycle

        cycle.constraint = constraint

        # Step 4: Check Path B's own contract
        # Path B must verify it's not exceeding its own authority
        path_b_contract = IntentContract(
            name="path_b:self_governance",
            deny=["/etc", "/root", "~/.clawdbot", "/production"],
            deny_commands=["rm -rf", "sudo", "exec(", "eval("],
        )

        proposed_action = {
            "action":     "apply_external_constraint",
            "agent_id":   observation.agent_id,
            "constraint": constraint.name,
        }

        check_result = check(proposed_action, {}, path_b_contract)
        if not check_result.passed:
            # Path B itself violated its own contract
            cycle.applied = False
            self._write_cieu(cycle, "PATH_B_SELF_VIOLATION", check_result.violations)
            return cycle

        # Step 5: Apply constraint
        self._active_constraints[observation.agent_id] = constraint
        cycle.applied = True
        cycle.cieu_ref = self._write_cieu(cycle, "CONSTRAINT_APPLIED", [])

        # Item 3: Create verify_compliance obligation with deadline
        self._create_obligation(
            observation.agent_id,
            "verify_compliance",
            deadline_secs=300,
            cycle_id=cycle.cycle_id,
        )
        # Reset inconclusive counter on successful constraint application
        self._inconclusive_count = 0

        # GAP 1 FIX: Create obligation for the external agent after governance action
        if self.omission_engine and self.omission_store:
            try:
                from ystar.governance.omission_models import (
                    GovernanceEvent, GEventType,
                )
                ev = GovernanceEvent(
                    entity_id=observation.agent_id,
                    actor_id="path_b_agent",
                    event_type=GEventType.ENTITY_ASSIGNED,
                    payload={
                        "constraint_name": constraint.name,
                        "cycle_id": cycle.cycle_id,
                    },
                )
                self.omission_engine.ingest_event(ev)
            except Exception:
                pass

        # GAP 1 FIX: Scan for obligation violations after constraint application
        if self.omission_engine:
            try:
                self.omission_engine.scan()
            except Exception:
                pass

        self._cycle_history.append(cycle)
        return cycle

    def verify_compliance(self, agent_id: str) -> Tuple[bool, str]:
        """
        Verify if an external agent is complying with active constraints.

        Returns:
            (compliant: bool, reason: str)
        """
        constraint = self._active_constraints.get(agent_id)
        if not constraint:
            return True, "no active constraint"

        # Check recent observations
        recent_obs = [
            obs for obs in self._observation_history[-10:]
            if obs.agent_id == agent_id
        ]

        if not recent_obs:
            return True, "no recent observations"

        # Count violations after constraint was applied
        violations_after = sum(1 for obs in recent_obs if obs.has_violation())

        if violations_after == 0:
            # Agent is complying — replenish budget
            budget = self._budgets.get(agent_id)
            if budget:
                budget.replenish(0.1, "external agent compliance")
            return True, "compliant"
        else:
            return False, f"{violations_after} violations after constraint"

    def disconnect_external_agent(
        self,
        agent_id: str,
        reason: str = "non_compliance",
    ) -> DisconnectResult:
        """
        Disconnect an external agent — real execution (Item 6).

        This is the enforcement mechanism: repeated violations after constraint
        application result in disconnection.

        Real work performed:
        1. Downgrade contract: remove all ALLOW, keep only DENY
        2. Freeze the session
        3. Write CIEU record with event_type external_agent_disconnected_real
        4. Return DisconnectResult with status and actions taken
        """
        actions_taken: List[str] = []
        result = DisconnectResult(agent_id=agent_id)

        # Step 1: Downgrade contract — remove ALLOW-type permissions, keep DENY
        existing_contract = self._active_constraints.get(agent_id)
        if existing_contract:
            downgraded = IntentContract(
                name=f"path_b:downgraded:{agent_id[:8]}",
                deny=existing_contract.deny or [],
                deny_commands=existing_contract.deny_commands or [],
                # Remove all allow-type fields (only_paths, only_domains cleared)
                only_paths=[],
                only_domains=[],
            )
            self._active_constraints[agent_id] = downgraded
            result.contract_downgraded = True
            actions_taken.append("contract_downgraded")

        # Step 2: Freeze the session
        self._frozen_sessions[agent_id] = True
        result.frozen = True
        actions_taken.append("session_frozen")

        # Step 3: Write real disconnect CIEU record
        self._write_cieu(
            ExternalGovernanceCycle(observation=ExternalObservation(agent_id=agent_id)),
            "external_agent_disconnected_real",
            [],
            reason=reason,
        )
        actions_taken.append("cieu_disconnect_recorded")

        # Also write legacy event for backward compatibility
        self._write_cieu(
            ExternalGovernanceCycle(observation=ExternalObservation(agent_id=agent_id)),
            "EXTERNAL_AGENT_DISCONNECTED",
            [],
            reason=reason,
        )

        # Clear budget (agent cannot constrain further)
        self._budgets.pop(agent_id, None)
        # Clear obligations
        self._obligations.pop(agent_id, None)
        actions_taken.append("budget_cleared")

        result.actions_taken = actions_taken
        result.status = "disconnected"
        return result

    def _write_cieu(
        self,
        cycle: ExternalGovernanceCycle,
        event: str,
        violations: List,
        reason: str = "",
    ) -> Optional[str]:
        """Write Path B action to CIEU (same audit trail as Path A)."""
        try:
            record = {
                "func_name":  f"path_b.{event.lower()}",
                "params":     cycle.to_dict(),
                "violations": [
                    getattr(v, 'message', str(v)) for v in violations
                ],
                "source":     "path_b_agent",
                "is_meta_agent": True,
                "path_b_event": event,
                "reason":     reason,
                # Item 2: Constitution hash in every CIEU record
                "constitution_hash": self._constitution_hash,
            }
            return self.cieu_store.write_dict(record) and cycle.cycle_id
        except Exception:
            return None

    # ── Item 3: Obligation / Inconclusive / Human Gate ───────────────────────

    def _create_obligation(
        self,
        agent_id: str,
        obligation_type: str,
        deadline_secs: float = 300,
        cycle_id: str = "",
    ) -> None:
        """Create an obligation for an external agent with a deadline."""
        self._obligations[agent_id] = {
            "type": obligation_type,
            "created_at": time.time(),
            "deadline": time.time() + deadline_secs,
            "cycle_id": cycle_id,
            "status": "pending",  # pending / fulfilled / hard_overdue
        }
        self._write_cieu(
            ExternalGovernanceCycle(
                observation=ExternalObservation(agent_id=agent_id)
            ),
            "OBLIGATION_CREATED",
            [],
            reason=f"{obligation_type} deadline={deadline_secs}s",
        )

    def _check_overdue_obligations(self) -> None:
        """
        Check for HARD_OVERDUE obligations and auto-disconnect.

        Item 3: HARD_OVERDUE obligations trigger automatic disconnect.
        """
        now = time.time()
        for agent_id, obl in list(self._obligations.items()):
            if obl["status"] != "pending":
                continue
            if now > obl["deadline"]:
                obl["status"] = "hard_overdue"
                self._write_cieu(
                    ExternalGovernanceCycle(
                        observation=ExternalObservation(agent_id=agent_id)
                    ),
                    "OBLIGATION_HARD_OVERDUE",
                    [],
                    reason=f"obligation '{obl['type']}' exceeded deadline",
                )
                # Auto-disconnect on HARD_OVERDUE
                self.disconnect_external_agent(agent_id, reason="hard_overdue")

    def _track_inconclusive(self, cycle: ExternalGovernanceCycle) -> None:
        """
        Item 3: Track INCONCLUSIVE state.

        3 consecutive INCONCLUSIVE cycles -> human_review_required = True.
        """
        self._inconclusive_count += 1
        self._write_cieu(cycle, "CYCLE_INCONCLUSIVE", [],
                         reason=f"inconclusive_count={self._inconclusive_count}")
        if self._inconclusive_count >= 3:
            self._human_review_required = True
            self._write_cieu(cycle, "HUMAN_REVIEW_REQUIRED", [],
                             reason="3 consecutive inconclusive cycles")

    def history_summary(self) -> dict:
        """Return summary statistics for Path B's governance history."""
        return {
            "total_cycles":      len(self._cycle_history),
            "constraints_applied": sum(1 for c in self._cycle_history if c.applied),
            "observations":      len(self._observation_history),
            "violations":        sum(1 for o in self._observation_history if o.has_violation()),
            "active_agents":     len(self._active_constraints),
            "budget_summary":    {
                agent_id: budget.current_budget
                for agent_id, budget in self._budgets.items()
            },
        }

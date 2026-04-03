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
from enum import Enum
from typing import Optional, List, Tuple, Any, Dict, Callable
import hashlib, logging, time, uuid, os

_log = logging.getLogger(__name__)

from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import check, CheckResult
from ystar.kernel.contract_provider import ConstitutionProvider
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_models import ObligationRecord, ObligationStatus, Severity as ObligationSeverity
from ystar.governance.amendment import AmendmentEngine
from ystar.governance.causal_engine import CausalEngine, DoCalcResult
from ystar.path_b.causal_adapter import PathBCausalAdapter


# ── Constitution hash — via ConstitutionProvider (N2) ────────────────────────
# Constitution loading now goes through ConstitutionProvider, the canonical
# access path for all constitution files in Y*gov.
_CONSTITUTION_PATH = os.path.join(os.path.dirname(__file__), "PATH_B_AGENTS.md")

# N2: ConstitutionProvider is the canonical access path.
# Hash is computed at runtime in PathBAgent.__init__, NOT at import time.


@dataclass
class PathBPolicy:
    """Unified failure + configuration policy for Path B.

    Failure matrix (F6): each field specifies response when that subsystem fails.
    Configuration defaults (F2): extracted from previously hardcoded values.
    """
    # F6: Failure matrix
    observation_failure:        str = "skip"
    constraint_failure:         str = "warn"
    compliance_check_failure:   str = "warn"
    budget_exhaustion:          str = "require_human"
    disconnect_failure:         str = "abort"
    constitution_mismatch:      str = "skip"
    human_review:               str = "suspend"
    # F2: Configurable defaults (extracted from hardcoded values)
    default_budget:             float = 1.0
    budget_cost_per_constraint: float = 0.1
    compliance_check_deadline:  float = 300.0
    max_consecutive_ineffective: int = 3
    disconnect_threshold:       int = 3
    # R3: Self-governance contract fields (extracted from hardcoded IntentContract)
    self_governance_deny:          List[str] = field(default_factory=lambda: ["/etc", "/root", "~/.clawdbot", "/production"])
    self_governance_deny_commands: List[str] = field(default_factory=lambda: ["rm -rf", "sudo", "exec(", "eval("])
    # R4: Constraint derivation policy
    confidence_base:            float = 0.3
    confidence_per_evidence:    float = 0.1
    confidence_cap:             float = 0.95
    constraint_cost_base:       float = 0.05
    constraint_cost_severity_factor: float = 0.05
    cold_start_min_severity:    float = 0.5
    # R5: Escalation policy
    escalation_steps:           List[str] = field(default_factory=lambda: ["warn", "downgrade", "freeze", "disconnect"])
    escalation_thresholds:      Dict[str, Any] = field(default_factory=dict)
    # C1/C6: Causal engine policy
    causal_confidence_threshold: float = 0.65
    causal_l2_before_escalation: bool = True
    causal_l3_on_ineffective:    bool = True
    # C4: Human gate policy
    human_gate_disconnect:              bool  = True   # disconnect always needs human
    human_gate_freeze:                  bool  = True   # freeze needs human if low confidence
    human_gate_low_confidence_threshold: float = 0.65  # below this -> human gate


# ── Disconnect result (Item 6) ───────────────────────────────────────────────
@dataclass
class DisconnectResult:
    """Result of a real disconnect execution."""
    agent_id:       str = ""
    status:         str = "disconnected"  # "disconnected" / "already_disconnected" / "error"
    actions_taken:  List[str] = field(default_factory=list)
    frozen:         bool = False
    contract_downgraded: bool = False


# ── T6: External Authority Scope ─────────────────────────────────────────────
@dataclass
class ExternalAuthorityScope:
    """
    Defines what Path B is allowed to constrain for a given external agent.

    Path B's constraint authority is derived from observations, not self-defined.
    This dataclass formalizes the boundary: Path B can only constrain dimensions
    that were actually observed in violations, using tools that are pre-approved,
    within domains that have been delegated to it.
    """
    allowed_dimensions:         List[str] = field(default_factory=list)
    allowed_tools:              List[str] = field(default_factory=list)
    allowed_domains:            List[str] = field(default_factory=list)
    derived_from_observations:  List[str] = field(default_factory=list)  # observation_ids

    def contains_dimension(self, dimension: str) -> bool:
        if not self.allowed_dimensions:
            return True  # cold start — no restrictions yet
        return dimension in self.allowed_dimensions

    def contains_domain(self, domain: str) -> bool:
        if not self.allowed_domains:
            return True
        return domain in self.allowed_domains


# ── T8: External Governance Action enum ──────────────────────────────────────
class ExternalGovernanceAction(Enum):
    """All action types Path B can take against an external agent."""
    APPLY_CONSTRAINT    = "apply_constraint"
    VERIFY_COMPLIANCE   = "verify_compliance"
    DOWNGRADE_CONTRACT  = "downgrade_contract"
    FREEZE_SESSION      = "freeze_session"
    DISCONNECT_AGENT    = "disconnect_agent"
    REQUIRE_HUMAN_REVIEW = "require_human_review"


# ── T7: External Governance Result ───────────────────────────────────────────
@dataclass
class ExternalGovernanceResult:
    """
    Outcome of a Path B governance action.

    States:
      success      — constraint applied and agent complied
      failure      — constraint applied but agent violated again
      ineffective  — constraint applied but no measurable change
      disconnected — agent was disconnected
    """
    status:     str = "success"   # success / failure / ineffective / disconnected
    agent_id:   str = ""
    action:     ExternalGovernanceAction = ExternalGovernanceAction.APPLY_CONSTRAINT
    details:    str = ""
    cycle_id:   str = ""


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
    # T6: Authority scope — formal reference to the scope object
    authority_scope: Optional["ExternalAuthorityScope"] = None

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

        T6: Also updates the ExternalAuthorityScope with observation references.
        """
        dims: set = set()
        obs_ids: List[str] = []
        for obs in observations:
            if obs.agent_id != self.agent_id:
                continue
            for v in obs.violations:
                dim = getattr(v, "dimension", "")
                if dim:
                    dims.add(dim)
                    obs_ids.append(obs.observation_id)
        self.allowed_dimensions = sorted(dims)

        # T6: Sync authority scope from observed dimensions
        if self.authority_scope is not None:
            self.authority_scope.allowed_dimensions = self.allowed_dimensions
            self.authority_scope.derived_from_observations = list(set(obs_ids))

    def populate_from_authority_scope(self, scope: "ExternalAuthorityScope") -> None:
        """T6: Populate allowed_dimensions from an ExternalAuthorityScope."""
        self.authority_scope = scope
        if scope.allowed_dimensions:
            self.allowed_dimensions = list(scope.allowed_dimensions)

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
    policy:          Optional["PathBPolicy"] = None,
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
    # R4: confidence/cost/cold-start from policy if available
    _conf_base = getattr(policy, 'confidence_base', 0.3) if policy else 0.3
    _conf_per  = getattr(policy, 'confidence_per_evidence', 0.1) if policy else 0.1
    _conf_cap  = getattr(policy, 'confidence_cap', 0.95) if policy else 0.95
    confidence = min(_conf_cap, _conf_base + (evidence_count * _conf_per))

    # Cold-start bypass: if there are REAL violations in the current observation
    # but zero historical observations for this agent (new user), generate
    # constraint directly instead of requiring confidence buildup.
    _cold_min_sev = getattr(policy, 'cold_start_min_severity', 0.5) if policy else 0.5
    prior_history = sum(
        1 for obs in violation_history
        if obs.agent_id == observation.agent_id
        and obs.observation_id != observation.observation_id
    )
    cold_start = (prior_history == 0
                  and observation.severity_score() >= _cold_min_sev)

    if not cold_start and confidence < confidence_threshold:
        return None  # Not confident enough to constrain

    # Calculate constraint cost based on severity (R4: from policy)
    severity = observation.severity_score()
    _cost_base = getattr(policy, 'constraint_cost_base', 0.05) if policy else 0.05
    _cost_sev  = getattr(policy, 'constraint_cost_severity_factor', 0.05) if policy else 0.05
    constraint_cost = _cost_base + (severity * _cost_sev)

    if not budget.can_tighten(constraint_cost):
        return None  # Insufficient budget

    # Item 4 + T6: Authority Boundary — filter violations to allowed dimensions
    # T6: If an ExternalAuthorityScope is attached, validate constraint is
    # within scope.  This enforces constraint ⊆ authority_scope.
    if budget.authority_scope is not None:
        scope = budget.authority_scope
        allowed_violations = [
            v for v in observation.violations
            if scope.contains_dimension(getattr(v, "dimension", ""))
        ]
        if not allowed_violations:
            return None  # No violations within authority scope
    elif budget.allowed_dimensions:
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
        policy: Optional[PathBPolicy] = None,
        causal_engine: Optional[CausalEngine] = None,
    ):
        self.cieu_store = cieu_store
        self.confidence_threshold = confidence_threshold
        self.max_cycles = max_cycles
        self.omission_store = omission_store
        # Constitution provider is the primary path; direct file loading is deprecated fallback (F3)
        self._constitution_provider = constitution_provider
        self._amendment_engine = amendment_engine
        # F2/F6: Unified policy object
        self.policy = policy or PathBPolicy()
        # C1: Pearl L2-L3 causal engine for intervention effect estimation
        self._causal_engine = causal_engine or CausalEngine(
            confidence_threshold=self.policy.causal_confidence_threshold
        )

        # Item 2: Constitution hash — loaded at init via ConstitutionProvider (fail-closed)
        try:
            _init_provider = ConstitutionProvider()
            self._constitution_hash: str = _init_provider.get_hash(_CONSTITUTION_PATH)
            if not self._constitution_hash:
                raise RuntimeError("ConstitutionProvider returned empty hash for PATH_B_AGENTS.md")
        except Exception as _e:
            raise RuntimeError(
                f"Path B fail-closed: cannot load constitution hash — {_e}"
            ) from _e

        # History tracking
        self._observation_history: List[ExternalObservation] = []
        self._cycle_history:       List[ExternalGovernanceCycle] = []

        # Budget tracking (one per external agent)
        self._budgets: Dict[str, ConstraintBudget] = {}

        # Active constraints (one per external agent)
        self._active_constraints: Dict[str, IntentContract] = {}

        # Item 3: Obligation / Inconclusive / Human Gate (R6: formal ObligationRecord)
        self._obligations: Dict[str, ObligationRecord] = {}   # agent_id -> ObligationRecord
        self._inconclusive_count: int = 0
        self._human_review_required: bool = False
        # Item 6: Frozen sessions
        self._frozen_sessions: Dict[str, bool] = {}   # agent_id -> frozen
        # T7: Consecutive ineffective constraint counter (per agent)
        self._consecutive_ineffective: Dict[str, int] = {}
        # T6: Authority scopes (per agent)
        self._authority_scopes: Dict[str, ExternalAuthorityScope] = {}

        # GAP 1 FIX: Initialize OmissionEngine from omission_store (same pattern as PathAAgent)
        self.omission_engine = (
            OmissionEngine(store=self.omission_store, cieu_store=self.cieu_store)
            if self.omission_store else None
        )

    def observe(self, observation: ExternalObservation) -> None:
        """
        Record an external agent observation.
        This is the input to Path B's governance cycle.

        Writes to CIEU for audit trail (critical for governance transparency).
        """
        self._observation_history.append(observation)

        # Write to CIEU for audit trail
        if self.cieu_store is not None:
            try:
                self.cieu_store.write_dict({
                    "event_type": "external_observation",
                    "agent_id": observation.agent_id,
                    "session_id": observation.session_id,
                    "action_type": observation.action_type,
                    "task_description": observation.params.get("tool") if observation.params else None,
                    "decision": "deny" if observation.has_violation() else "allow",
                    "passed": not observation.has_violation(),
                    "violations": [
                        v.to_dict() if hasattr(v, "to_dict") else {"reason": str(v)}
                        for v in observation.violations
                    ] if observation.violations else [],
                    "drift_detected": observation.has_violation(),
                    "observation_id": observation.observation_id,
                    "timestamp": observation.timestamp,
                    "evidence_grade": "governance",
                })
            except Exception as exc:
                # Non-critical: observation is still in memory even if CIEU write fails
                _log.debug("Failed to write external_observation to CIEU: %s", exc)

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
        # Constitution provider is the primary path (F3)
        if self._constitution_provider is not None:
            try:
                current_hash = self._constitution_provider(_CONSTITUTION_PATH)
            except Exception:
                current_hash = None  # Provider failed — do not fall back
        else:
            # F3: Fail-closed — no deprecated fallback, use ConstitutionProvider
            try:
                _cycle_provider = ConstitutionProvider()
                current_hash = _cycle_provider.get_hash(_CONSTITUTION_PATH)
            except Exception:
                current_hash = None
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

        # Step 3: Derive constraint (R4: pass policy for configurable derivation)
        constraint = observation_to_constraint(
            observation,
            [o for o in self._observation_history if o.agent_id == observation.agent_id],
            budget,
            self.confidence_threshold,
            policy=self.policy,
        )

        if not constraint:
            # No constraint derived (low confidence or insufficient budget)
            self._write_cieu(cycle, "NO_CONSTRAINT_DERIVED", [])
            # Item 3: Track INCONCLUSIVE
            self._track_inconclusive(cycle)
            return cycle

        cycle.constraint = constraint

        # Step 4: Check Path B's own contract (R3: from policy, not hardcoded)
        path_b_contract = IntentContract(
            name="path_b:self_governance",
            deny=list(self.policy.self_governance_deny),
            deny_commands=list(self.policy.self_governance_deny_commands),
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
            deadline_secs=self.policy.compliance_check_deadline,
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

        # C2: Feed cycle data to CausalEngine for Pearl L2-L3 reasoning
        if self._causal_engine:
            try:
                adapter = PathBCausalAdapter()
                # Count violations before/after for this agent
                agent_obs = [o for o in self._observation_history
                             if o.agent_id == observation.agent_id]
                v_before = sum(1 for o in agent_obs[:-1] if o.has_violation()) if len(agent_obs) > 1 else 0
                v_after = sum(1 for o in agent_obs if o.has_violation())
                compliant, _ = self.verify_compliance(observation.agent_id)
                obs_kwargs = adapter.to_observation_kwargs({
                    "action": ExternalGovernanceAction.APPLY_CONSTRAINT,
                    "compliant": compliant,
                    "violation_count_before": v_before,
                    "violation_count_after": v_after,
                    "cycle_id": cycle.cycle_id,
                })
                self._causal_engine.observe(**obs_kwargs)
            except Exception:
                pass  # Causal feed failed; don't block governance cycle

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
        """Create an obligation for an external agent with a deadline (R6: formal ObligationRecord)."""
        ob = ObligationRecord(
            entity_id=agent_id,
            actor_id="path_b_agent",
            obligation_type=obligation_type,
            trigger_event_id=cycle_id,
            required_event_types=["verify_compliance", "compliance_confirmed"],
            due_at=time.time() + deadline_secs,
            status=ObligationStatus.PENDING,
            severity=ObligationSeverity.MEDIUM,
            notes=f"Path B obligation: {obligation_type} for agent {agent_id}",
        )
        self._obligations[agent_id] = ob
        # Also register with OmissionStore if available
        if self.omission_store:
            try:
                self.omission_store.add_obligation(ob)
            except Exception:
                pass
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

        Item 3 + R6: Uses formal ObligationRecord lifecycle.
        """
        now = time.time()
        for agent_id, obl in list(self._obligations.items()):
            if obl.status != ObligationStatus.PENDING:
                continue
            if obl.is_overdue(now):
                obl.status = ObligationStatus.HARD_OVERDUE
                obl.hard_violation_at = now
                obl.updated_at = now
                self._write_cieu(
                    ExternalGovernanceCycle(
                        observation=ExternalObservation(agent_id=agent_id)
                    ),
                    "OBLIGATION_HARD_OVERDUE",
                    [],
                    reason=f"obligation '{obl.obligation_type}' exceeded deadline",
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
        if self._inconclusive_count >= self.policy.disconnect_threshold:
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

    # ── T7: Intermediate actions before disconnect ───────────────────────────
    # Escalation ladder: warn → downgrade → freeze → disconnect
    # Each step writes to CIEU.  3 consecutive ineffective → human review.

    def record_constraint_result(
        self,
        agent_id: str,
        effective: bool,
    ) -> ExternalGovernanceResult:
        """
        Record whether the last constraint was effective.

        T7: Tracks _consecutive_ineffective counter (like Path A's inconclusive).
        3 consecutive ineffective constraints → human review required.
        """
        if effective:
            self._consecutive_ineffective[agent_id] = 0
            return ExternalGovernanceResult(
                status="success", agent_id=agent_id,
                action=ExternalGovernanceAction.VERIFY_COMPLIANCE,
            )

        count = self._consecutive_ineffective.get(agent_id, 0) + 1
        self._consecutive_ineffective[agent_id] = count

        if count >= self.policy.max_consecutive_ineffective:
            self._human_review_required = True
            self._write_cieu(
                ExternalGovernanceCycle(
                    observation=ExternalObservation(agent_id=agent_id)
                ),
                "HUMAN_REVIEW_REQUIRED",
                [],
                reason=f"{count} consecutive ineffective constraints",
            )
            return ExternalGovernanceResult(
                status="ineffective", agent_id=agent_id,
                action=ExternalGovernanceAction.REQUIRE_HUMAN_REVIEW,
                details=f"{count} consecutive ineffective",
            )

        return ExternalGovernanceResult(
            status="ineffective", agent_id=agent_id,
            action=ExternalGovernanceAction.APPLY_CONSTRAINT,
            details=f"ineffective_count={count}",
        )

    def escalate_disconnect(self, agent_id: str, reason: str = "non_compliance") -> ExternalGovernanceResult:
        """
        T7: Intermediate actions before full disconnect.

        R5: Escalation ladder is driven by self.policy.escalation_steps (swappable).
        Default: warn -> downgrade -> freeze -> disconnect

        C3: Before each escalation step, estimate causal effect. If predicted
        gain is negligible, skip to the next step or request human review.

        Returns ExternalGovernanceResult with the action taken.
        """
        actions_taken: List[str] = []
        steps = self.policy.escalation_steps

        # Map step names to ExternalGovernanceAction for causal estimation
        _step_to_action = {
            "warn":       ExternalGovernanceAction.APPLY_CONSTRAINT,
            "downgrade":  ExternalGovernanceAction.DOWNGRADE_CONTRACT,
            "freeze":     ExternalGovernanceAction.FREEZE_SESSION,
            "disconnect": ExternalGovernanceAction.DISCONNECT_AGENT,
        }

        for step in steps:
            step_action = _step_to_action.get(step)

            # C3: Estimate causal effect before executing this step
            causal_result = None
            if self.policy.causal_l2_before_escalation and step_action:
                causal_result = self.estimate_action_effect(step_action, agent_id)

            # C4: Check human gate — only applies when causal estimation
            # returned a result (i.e., there IS causal data to reason about).
            # Without causal data, actions proceed as before (backward compatible).
            if (causal_result is not None
                    and step_action
                    and self.needs_human_for_action(step_action, causal_result)):
                self._human_review_required = True
                self._write_cieu(
                    ExternalGovernanceCycle(
                        observation=ExternalObservation(agent_id=agent_id)
                    ),
                    "HUMAN_GATE_ESCALATION",
                    [],
                    reason=f"human approval required for {step} (causal gate)",
                )
                actions_taken.append(f"human_gate_{step}")
                continue  # Skip this step, move to next

            if step == "warn":
                self.execute_action(ExternalGovernanceAction.APPLY_CONSTRAINT, agent_id,
                                    {"reason": f"warn:{reason}"})
                actions_taken.append("warned")

            elif step == "downgrade":
                existing = self._active_constraints.get(agent_id)
                if existing:
                    downgraded = IntentContract(
                        name=f"path_b:downgraded:{agent_id[:8]}",
                        deny=existing.deny or [],
                        deny_commands=existing.deny_commands or [],
                        only_paths=[], only_domains=[],
                    )
                    self._active_constraints[agent_id] = downgraded
                    self.execute_action(ExternalGovernanceAction.DOWNGRADE_CONTRACT, agent_id,
                                        {"reason": reason})
                    actions_taken.append("downgraded")

            elif step == "freeze":
                self._frozen_sessions[agent_id] = True
                self.execute_action(ExternalGovernanceAction.FREEZE_SESSION, agent_id,
                                    {"reason": reason})
                actions_taken.append("frozen")

            elif step == "disconnect":
                self.disconnect_external_agent(agent_id, reason=reason)
                actions_taken.append("disconnected")

        last_action = ExternalGovernanceAction.DISCONNECT_AGENT if "disconnected" in actions_taken else ExternalGovernanceAction.FREEZE_SESSION
        return ExternalGovernanceResult(
            status="disconnected" if "disconnected" in actions_taken else "frozen",
            agent_id=agent_id,
            action=last_action,
            details=f"escalation_steps={actions_taken}",
        )

    # ── T8: Unified action execution ─────────────────────────────────────────

    def execute_action(
        self,
        action: ExternalGovernanceAction,
        target_agent: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        T8: Execute a governance action and write to CIEU with the action type.

        Every action is recorded in CIEU with the ExternalGovernanceAction enum
        value, providing a complete audit trail of all governance decisions.
        """
        params = params or {}
        self._write_cieu(
            ExternalGovernanceCycle(
                observation=ExternalObservation(agent_id=target_agent)
            ),
            f"ACTION_{action.value.upper()}",
            [],
            reason=params.get("reason", ""),
        )

    # ── C3: Pearl L2 intervention effect estimation ──────────────────────────

    def estimate_action_effect(
        self,
        action: ExternalGovernanceAction,
        agent_id: str,
    ) -> Optional[DoCalcResult]:
        """Before executing an external governance action, estimate its causal effect.

        Uses Pearl Level 2 (do-calculus via backdoor adjustment) to predict
        whether the proposed action will improve compliance for this agent.

        Returns None if causal engine is not available or has insufficient
        observational data (cold start -- no historical cycles to reason from).
        """
        if not self._causal_engine:
            return None
        # No observational data = cold start; return None so escalation
        # proceeds without causal gating (backward compatible).
        if not self._causal_engine._observations:
            return None

        # Map action to treatment value via adapter
        adapter = PathBCausalAdapter()
        treatment_w = adapter.map_action_to_W(action)

        # Use do_wire_query with action-as-treatment
        # src_id = "path_b", tgt_id = agent_id (governance action edge)
        try:
            result = self._causal_engine.do_wire_query(
                src_id=f"path_b_{action.value}",
                tgt_id=agent_id,
            )
            return result
        except Exception:
            return None

    # ── C4: Causal-based human gate ──────────────────────────────────────────

    def needs_human_for_action(
        self,
        action: ExternalGovernanceAction,
        causal_result: Optional[DoCalcResult] = None,
    ) -> bool:
        """Determine if external governance action needs human approval based on causal confidence.

        Rules:
        - disconnect always needs human (unless policy overrides)
        - freeze needs human if causal_confidence < threshold
        - warn/downgrade: only gate when causal data exists but confidence is low
        - No causal data at all: allow low-impact actions (warn, downgrade) to proceed
        """
        # disconnect always needs human
        if action == ExternalGovernanceAction.DISCONNECT_AGENT:
            return self.policy.human_gate_disconnect

        # freeze needs human if confidence is low
        if action == ExternalGovernanceAction.FREEZE_SESSION:
            if not self.policy.human_gate_freeze:
                return False
            if causal_result is None:
                return True  # No causal data -> need human for freeze
            return causal_result.confidence < self.policy.human_gate_low_confidence_threshold

        # For lower-impact actions (warn, downgrade, etc.):
        # Only gate when we have causal data that shows low confidence.
        # No causal data = allow action to proceed (cold start).
        if causal_result is not None and causal_result.evidence_count > 0:
            if causal_result.confidence < self.policy.human_gate_low_confidence_threshold:
                return True

        return False

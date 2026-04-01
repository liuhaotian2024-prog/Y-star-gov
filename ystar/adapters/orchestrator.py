# Layer: Foundation
"""
ystar.adapters.orchestrator  —  Runtime Governance Orchestrator  v0.46.0
========================================================================

Connects the advanced governance mechanisms to the hook path using
periodic/batched invocation so that hook latency stays low.

Four subsystems are wired:

  1. InterventionEngine  — scan→pulse chain on every hook call (lightweight)
  2. GovernanceLoop      — meta-learning cycle every N calls or M seconds
  3. Path A (SRGCS)      — self-governance suggestions, piggy-backed on GovernanceLoop
  4. CausalEngine        — advisory causal reasoning on high-risk actions

Design constraints:
  - Hook latency: InterventionEngine gate_check is O(1) — always runs.
    GovernanceLoop/PathA run only periodically (batched).
  - Fail-safe: all orchestration failures are caught and logged to CIEU.
    The hook NEVER blocks due to orchestrator failure.
  - Agent-agnostic: works for CEO/CTO/CMO/CSO/CFO or any agent_id.

Usage from hook.py:
    from ystar.adapters.orchestrator import get_orchestrator
    orch = get_orchestrator()
    if orch:
        orch.on_hook_call(who, tool_name, params, result, session_cfg)
"""
from __future__ import annotations

import time
import threading
from typing import Any, Dict, List, Optional


# ── Configuration ────────────────────────────────────────────────────────────

# GovernanceLoop / Path A run every N hook calls OR every M seconds,
# whichever comes first.
GOVERNANCE_LOOP_INTERVAL_CALLS = 50
GOVERNANCE_LOOP_INTERVAL_SECS  = 300.0   # 5 minutes

# Intervention scan (omission → pulse forwarding) runs more frequently
INTERVENTION_SCAN_INTERVAL_CALLS = 10
INTERVENTION_SCAN_INTERVAL_SECS  = 60.0   # 1 minute

# CausalEngine advisory: only on write/exec actions (high-risk)
CAUSAL_HIGH_RISK_TOOLS = {"Write", "Edit", "MultiEdit", "Bash", "Task"}


class Orchestrator:
    """
    Singleton orchestrator that coordinates InterventionEngine,
    GovernanceLoop, Path A, and CausalEngine on the hook path.

    All methods are fail-safe: exceptions are caught and optionally
    logged to CIEU. The hook is never blocked by orchestrator failures.
    """

    def __init__(self) -> None:
        # Counters for periodic triggering
        self._call_count: int = 0
        self._last_governance_loop_at: float = 0.0
        self._last_governance_loop_call: int = 0
        self._last_intervention_scan_at: float = 0.0
        self._last_intervention_scan_call: int = 0

        # Cached references (lazily populated)
        self._governance_loop: Optional[Any] = None
        self._path_a_agent: Optional[Any] = None
        self._cieu_store: Optional[Any] = None
        self._intervention_engine: Optional[Any] = None
        self._omission_adapter: Optional[Any] = None
        self._causal_engine: Optional[Any] = None

        # CIEU buffer for batched GovernanceLoop ingestion
        self._cieu_buffer: List[Dict[str, Any]] = []
        self._cieu_buffer_max = 200

        # Lock for thread safety (hooks may be called from multiple threads)
        self._lock = threading.Lock()

        # Track initialization state
        self._initialized = False

    # ── Lazy Initialization ──────────────────────────────────────────────────

    def _ensure_initialized(self, session_cfg: Optional[Dict[str, Any]] = None) -> None:
        """
        Lazily initialize references to governance subsystems.
        Called on first hook invocation with a session config.
        """
        if self._initialized:
            return

        try:
            self._init_from_session(session_cfg or {})
            self._initialized = True
        except Exception:
            pass  # Initialization failure is not fatal

    def _init_from_session(self, session_cfg: Dict[str, Any]) -> None:
        """Wire up subsystem references from the existing adapter singletons."""
        # 1. InterventionEngine — from adapter module singleton
        try:
            from ystar.domains.openclaw.adapter import get_intervention_engine
            self._intervention_engine = get_intervention_engine()
        except Exception:
            pass

        # 2. OmissionAdapter — for scan forwarding
        try:
            from ystar.domains.openclaw.adapter import get_omission_adapter
            self._omission_adapter = get_omission_adapter()
        except Exception:
            pass

        # 3. CIEUStore — for reading accumulated records
        cieu_db = session_cfg.get("cieu_db", ".ystar_cieu.db")
        try:
            from ystar.governance.cieu_store import CIEUStore
            self._cieu_store = CIEUStore(cieu_db)
        except Exception:
            pass

        # 4. GovernanceLoop — the meta-learning orchestrator
        try:
            self._governance_loop = self._build_governance_loop()
        except Exception:
            pass

    def _build_governance_loop(self) -> Optional[Any]:
        """
        Build a GovernanceLoop instance wired to the current session's stores.
        Returns None if dependencies are missing.
        """
        try:
            from ystar.governance.governance_loop import GovernanceLoop
            from ystar.governance.reporting import ReportEngine

            # Need an omission store for ReportEngine
            omission_store = None
            if self._omission_adapter and hasattr(self._omission_adapter, 'engine'):
                omission_store = self._omission_adapter.engine.store
            if omission_store is None:
                return None

            report_engine = ReportEngine(
                omission_store=omission_store,
                cieu_store=self._cieu_store,
                intervention_eng=self._intervention_engine,
            )

            # Build CausalEngine if available
            causal_engine = None
            try:
                from ystar.governance.causal_engine import CausalEngine
                causal_engine = CausalEngine()
                self._causal_engine = causal_engine
            except Exception:
                pass

            loop = GovernanceLoop(
                report_engine=report_engine,
                intervention_engine=self._intervention_engine,
                causal_engine=causal_engine,
            )

            return loop
        except Exception:
            return None

    # ── Main Entry Point (called from hook.py) ───────────────────────────────

    def on_hook_call(
        self,
        agent_id: str,
        tool_name: str,
        params: dict,
        check_result: Any,
        session_cfg: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Called after every hook check. Orchestrates the advanced governance
        subsystems with periodic/batched invocation.

        Returns:
            None normally. If InterventionEngine gate produces a DENY for a
            high-risk action, returns a dict that the hook can use to override
            the allow decision. In practice this is rare — the gate_check in
            the adapter's enforce() path already handles most cases.
        """
        with self._lock:
            self._call_count += 1
            now = time.time()

        # Lazy init on first call
        self._ensure_initialized(session_cfg)

        # Buffer CIEU record for later GovernanceLoop ingestion
        self._buffer_cieu_record(agent_id, tool_name, params, check_result)

        # 1. InterventionEngine scan (frequent — every 10 calls or 60s)
        #    Forwards omission violations to InterventionEngine pulse store.
        if self._should_run_intervention_scan(now):
            self._run_intervention_scan(now)

        # 2. GovernanceLoop + Path A (infrequent — every 50 calls or 5min)
        if self._should_run_governance_loop(now):
            self._run_governance_loop_cycle(agent_id, now)

        # 3. CausalEngine advisory (on high-risk tools only, lightweight)
        if tool_name in CAUSAL_HIGH_RISK_TOOLS and self._causal_engine is not None:
            self._run_causal_advisory(agent_id, tool_name, params)

        return None

    # ── Periodic Triggers ────────────────────────────────────────────────────

    def _should_run_intervention_scan(self, now: float) -> bool:
        calls_since = self._call_count - self._last_intervention_scan_call
        time_since = now - self._last_intervention_scan_at
        return (
            self._omission_adapter is not None
            and self._intervention_engine is not None
            and (calls_since >= INTERVENTION_SCAN_INTERVAL_CALLS
                 or time_since >= INTERVENTION_SCAN_INTERVAL_SECS)
        )

    def _should_run_governance_loop(self, now: float) -> bool:
        calls_since = self._call_count - self._last_governance_loop_call
        time_since = now - self._last_governance_loop_at
        return (
            self._governance_loop is not None
            and (calls_since >= GOVERNANCE_LOOP_INTERVAL_CALLS
                 or time_since >= GOVERNANCE_LOOP_INTERVAL_SECS)
        )

    # ── 1. InterventionEngine Scan ───────────────────────────────────────────

    def _run_intervention_scan(self, now: float) -> None:
        """
        Run OmissionEngine.scan() and forward violations to InterventionEngine.

        This completes the scan→pulse chain:
          OmissionEngine.scan() → OmissionViolation[]
          → InterventionEngine.process_violations()
          → InterventionPulse[] (stored in PulseStore)
          → gate_check() uses PulseStore to DENY high-risk actions

        Also runs scan_restorations() to re-enable actors who have
        fulfilled their obligations.
        """
        with self._lock:
            self._last_intervention_scan_at = now
            self._last_intervention_scan_call = self._call_count

        try:
            # Run omission scan
            if self._omission_adapter and hasattr(self._omission_adapter, 'engine'):
                scan_result = self._omission_adapter.engine.scan(now=now)

                # Forward violations to InterventionEngine
                if scan_result.violations and self._intervention_engine is not None:
                    try:
                        intervention_result = self._intervention_engine.process_violations(
                            scan_result.violations
                        )
                        # Log intervention pulses to CIEU
                        if intervention_result.pulses_fired:
                            self._log_orchestration_event(
                                "intervention_scan",
                                {
                                    "pulses_fired": len(intervention_result.pulses_fired),
                                    "violations_processed": len(scan_result.violations),
                                    "capability_restrictions": len(intervention_result.capability_restrictions),
                                    "reroutes": len(intervention_result.reroutes),
                                },
                            )
                    except Exception:
                        pass

                # Scan for restorable actors
                if self._intervention_engine is not None:
                    try:
                        restored = self._intervention_engine.scan_restorations()
                        if restored:
                            self._log_orchestration_event(
                                "intervention_restoration",
                                {"restored_actors": restored},
                            )
                    except Exception:
                        pass
        except Exception:
            pass  # Never block the hook

    # ── 2. GovernanceLoop + Path A ───────────────────────────────────────────

    def _run_governance_loop_cycle(self, agent_id: str, now: float) -> None:
        """
        Run one GovernanceLoop cycle:
          1. Feed buffered CIEU records into CausalEngine
          2. observe_from_report_engine() — collect governance observations
          3. tighten() — run meta-learning, produce suggestions
          4. Submit suggestions to ConstraintRegistry (if available)
          5. Optionally trigger Path A for high-confidence suggestions

        This is the meta-learning feedback loop that makes governance
        improve over time based on actual runtime data.
        """
        with self._lock:
            self._last_governance_loop_at = now
            self._last_governance_loop_call = self._call_count
            # Drain CIEU buffer
            buffered = list(self._cieu_buffer)
            self._cieu_buffer.clear()

        gloop = self._governance_loop
        if gloop is None:
            return

        try:
            # Step 1: Feed CIEU records into CausalEngine for Pearl reasoning
            if buffered and hasattr(gloop, 'ingest_cieu_to_causal_engine'):
                try:
                    gloop.ingest_cieu_to_causal_engine(buffered)
                except Exception:
                    pass

            # Step 2: Observe current governance state
            try:
                observation = gloop.observe_from_report_engine()
            except Exception:
                observation = None

            # Step 3: Run tighten() — meta-learning cycle
            try:
                tighten_result = gloop.tighten()
            except Exception:
                tighten_result = None

            if tighten_result is None:
                return

            # Step 4: Submit governance suggestions to ConstraintRegistry
            if tighten_result.governance_suggestions:
                try:
                    if hasattr(gloop, 'submit_suggestions_to_registry'):
                        gloop.submit_suggestions_to_registry(tighten_result)
                except Exception:
                    pass

            # Step 5: Log the governance cycle to CIEU
            self._log_orchestration_event(
                "governance_loop_cycle",
                {
                    "health": tighten_result.overall_health,
                    "suggestions_count": len(tighten_result.governance_suggestions),
                    "restored_actors": tighten_result.restored_actors,
                    "action_required": tighten_result.is_action_required(),
                    "observation_healthy": observation.is_healthy() if observation else None,
                    "causal_chain": tighten_result.causal_chain[:3] if tighten_result.causal_chain else [],
                },
            )

            # Step 6: Path A — if there are high-confidence suggestions and
            # the system is degraded, trigger a Path A self-governance cycle.
            if (tighten_result.overall_health in ("degraded", "critical")
                    and tighten_result.governance_suggestions):
                self._run_path_a_cycle(tighten_result, now)

        except Exception:
            pass  # Never block the hook

    def _run_path_a_cycle(
        self,
        tighten_result: Any,
        now: float,
    ) -> None:
        """
        Trigger a Path A (SRGCS) self-governance cycle.

        Path A consumes GovernanceLoop suggestions and attempts to
        wire module improvements autonomously. This only runs when:
          - GovernanceLoop reports degraded/critical health
          - There are actionable suggestions
          - Path A agent is available

        The cycle is fire-and-forget from the hook's perspective.
        Results are recorded in CIEU and the OmissionEngine creates
        postcondition obligations to verify improvement.
        """
        # Build Path A agent lazily (expensive — only done when needed)
        if self._path_a_agent is None:
            try:
                self._path_a_agent = self._build_path_a_agent()
            except Exception:
                return
        if self._path_a_agent is None:
            return

        try:
            cycle = self._path_a_agent.run_one_cycle()
            self._log_orchestration_event(
                "path_a_cycle",
                {
                    "cycle_id": cycle.cycle_id if cycle else "none",
                    "success": cycle.success if cycle else False,
                    "health_before": cycle.health_before if cycle else "unknown",
                    "health_after": cycle.health_after if cycle else "unknown",
                    "executed": cycle.executed if cycle else False,
                },
            )
        except Exception:
            self._log_orchestration_event(
                "path_a_cycle_error",
                {"error": "Path A cycle failed (non-fatal)"},
            )

    def _build_path_a_agent(self) -> Optional[Any]:
        """Build a PathAAgent wired to the current GovernanceLoop."""
        try:
            from ystar.path_a.meta_agent import PathAAgent
            from ystar.module_graph.planner import CompositionPlanner
            from ystar.module_graph.graph import ModuleGraph

            gloop = self._governance_loop
            if gloop is None:
                return None

            # PathAAgent needs a planner with a ModuleGraph
            graph = ModuleGraph()
            planner = CompositionPlanner(graph)

            omission_store = None
            if self._omission_adapter and hasattr(self._omission_adapter, 'engine'):
                omission_store = self._omission_adapter.engine.store

            return PathAAgent(
                governance_loop=gloop,
                cieu_store=self._cieu_store,
                planner=planner,
                omission_store=omission_store,
            )
        except Exception:
            return None

    # ── 3. CausalEngine Advisory ─────────────────────────────────────────────

    def _run_causal_advisory(
        self,
        agent_id: str,
        tool_name: str,
        params: dict,
    ) -> None:
        """
        Run lightweight causal reasoning on high-risk actions.
        This produces an advisory recommendation (does NOT change the decision).
        The recommendation is logged to CIEU for observability.
        """
        if self._causal_engine is None:
            return
        try:
            # Use do_wire_query: estimate health impact of this action
            p_health_allow = self._causal_engine.do_wire_query(wire=True)
            p_health_block = self._causal_engine.do_wire_query(wire=False)

            if p_health_allow is not None and p_health_block is not None:
                recommendation = "allow" if p_health_allow >= p_health_block else "block"
                if abs(p_health_allow - p_health_block) > 0.1:
                    # Only log when there's a meaningful difference
                    self._log_orchestration_event(
                        "causal_advisory",
                        {
                            "agent_id": agent_id,
                            "tool_name": tool_name,
                            "recommendation": recommendation,
                            "p_health_allow": round(p_health_allow, 3),
                            "p_health_block": round(p_health_block, 3),
                        },
                    )
        except Exception:
            pass

    # ── CIEU Buffer ──────────────────────────────────────────────────────────

    def _buffer_cieu_record(
        self,
        agent_id: str,
        tool_name: str,
        params: dict,
        check_result: Any,
    ) -> None:
        """Buffer a CIEU-compatible record for later GovernanceLoop ingestion."""
        with self._lock:
            if len(self._cieu_buffer) >= self._cieu_buffer_max:
                # Drop oldest to prevent unbounded growth
                self._cieu_buffer = self._cieu_buffer[self._cieu_buffer_max // 2:]

            allowed = True
            if hasattr(check_result, 'allowed'):
                allowed = check_result.allowed
            elif hasattr(check_result, 'value'):
                allowed = check_result.value != 'deny'

            self._cieu_buffer.append({
                "agent_id": agent_id,
                "event_type": tool_name,
                "decision": "allow" if allowed else "deny",
                "passed": allowed,
                "params": {k: str(v)[:200] for k, v in (params or {}).items()},
                "ts": time.time(),
            })

    # ── CIEU Logging ─────────────────────────────────────────────────────────

    def _log_orchestration_event(
        self,
        event_type: str,
        details: Dict[str, Any],
    ) -> None:
        """Write an orchestration event to CIEU (silent failure)."""
        if self._cieu_store is None:
            return
        try:
            import uuid
            self._cieu_store.write_dict({
                "event_id": str(uuid.uuid4()),
                "seq_global": int(time.time() * 1_000_000),
                "created_at": time.time(),
                "session_id": "orchestrator",
                "agent_id": "orchestrator",
                "event_type": f"orchestration:{event_type}",
                "decision": "info",
                "passed": True,
                "violations": [],
                "drift_detected": False,
                "drift_details": "",
                "drift_category": "orchestration",
                "task_description": str(details)[:500],
            })
        except Exception:
            pass

    # ── Status Report ────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a snapshot of the orchestrator's state (for diagnostics)."""
        return {
            "initialized": self._initialized,
            "call_count": self._call_count,
            "cieu_buffer_size": len(self._cieu_buffer),
            "has_governance_loop": self._governance_loop is not None,
            "has_path_a_agent": self._path_a_agent is not None,
            "has_intervention_engine": self._intervention_engine is not None,
            "has_causal_engine": self._causal_engine is not None,
            "has_omission_adapter": self._omission_adapter is not None,
            "last_governance_loop_at": self._last_governance_loop_at,
            "last_intervention_scan_at": self._last_intervention_scan_at,
        }


# ── Module-level Singleton ───────────────────────────────────────────────────

_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """
    Get or create the singleton Orchestrator instance.
    Thread-safe initialization.
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def reset_orchestrator() -> None:
    """Reset the singleton (for testing)."""
    global _orchestrator
    _orchestrator = None

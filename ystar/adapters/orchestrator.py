# Layer: Foundation
"""
ystar.adapters.orchestrator  —  Runtime Governance Orchestrator  v0.47.0
========================================================================

Connects the advanced governance mechanisms to the hook path using
periodic/batched invocation so that hook latency stays low.

Five subsystems are wired:

  1. InterventionEngine  — scan→pulse chain on every hook call (lightweight)
  2. GovernanceLoop      — meta-learning cycle every N calls or M seconds
  3. Path A (SRGCS)      — self-governance suggestions, piggy-backed on GovernanceLoop
  4. Path B (External)   — external agent governance, runs after GovernanceLoop
  5. CausalEngine        — advisory causal reasoning on high-risk actions

Design constraints:
  - Hook latency: InterventionEngine gate_check is O(1) — always runs.
    GovernanceLoop/PathA/PathB run only periodically (batched).
  - Fail-safe: all orchestration failures are caught and logged to CIEU.
    The hook NEVER blocks due to orchestrator failure.
  - Agent-agnostic: works with any agent_id or role naming scheme.

Usage from hook.py:
    from ystar.adapters.orchestrator import get_orchestrator
    orch = get_orchestrator()
    if orch:
        orch.on_hook_call(who, tool_name, params, result, session_cfg)
"""
from __future__ import annotations

import logging
import time
import threading
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

# GovernanceLoop / Path A run every N hook calls OR every M seconds,
# whichever comes first.
GOVERNANCE_LOOP_INTERVAL_CALLS = 50
GOVERNANCE_LOOP_INTERVAL_SECS  = 300.0   # 5 minutes

# Intervention scan (omission → pulse forwarding) runs more frequently
INTERVENTION_SCAN_INTERVAL_CALLS = 10
INTERVENTION_SCAN_INTERVAL_SECS  = 60.0   # 1 minute

# Coverage scan (governance coverage measurement) runs least frequently
COVERAGE_SCAN_INTERVAL_CALLS = 200   # 比GovernanceLoop更稀疏
COVERAGE_SCAN_INTERVAL_SECS  = 1800.0  # 30分钟

# CausalEngine advisory: only on write/exec actions (high-risk)
CAUSAL_HIGH_RISK_TOOLS = {"Write", "Edit", "MultiEdit", "Bash", "Task"}


class Orchestrator:
    """
    Singleton orchestrator that coordinates InterventionEngine,
    GovernanceLoop, Path A, Path B, and CausalEngine on the hook path.

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
        self._last_coverage_scan_at: float = 0.0
        self._last_coverage_scan_call: int = 0

        # Cached references (lazily populated)
        self._governance_loop: Optional[Any] = None
        self._path_a_agent: Optional[Any] = None
        self._path_b_agent: Optional[Any] = None
        self._cieu_store: Optional[Any] = None
        self._intervention_engine: Optional[Any] = None
        self._omission_adapter: Optional[Any] = None
        self._causal_engine: Optional[Any] = None

        # Session config (cached for _get_session_contract)
        self._session_cfg: Dict[str, Any] = {}

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
        except Exception as e:
            _log.error("Orchestrator initialization failed: %s", e, exc_info=True)

    def _init_from_session(self, session_cfg: Dict[str, Any]) -> None:
        """
        Wire up subsystem references from the existing adapter singletons.

        P0-FIX: If adapters are not yet configured (singletons return None),
        configure them here. This fixes the race condition where orchestrator
        tries to access adapters before hook.py has configured them.
        """
        # 0. Extract session config values and cache for later use
        self._session_cfg = session_cfg
        cieu_db = session_cfg.get("cieu_db", ".ystar_cieu.db")
        contract_dict = session_cfg.get("contract", {})

        # 1. Configure OmissionAdapter if not already configured
        try:
            from ystar.domains.openclaw.adapter import get_omission_adapter, configure_omission_governance
            from ystar.governance.omission_store import OmissionStore
            from ystar.adapters.omission_adapter import create_adapter
            from ystar.governance.omission_rules import reset_registry
            from ystar.domains.openclaw.accountability_pack import apply_openclaw_accountability_pack
            from ystar.kernel.dimensions import IntentContract

            self._omission_adapter = get_omission_adapter()
            if self._omission_adapter is None:
                # Adapters not configured yet — configure them now
                _log.info("Orchestrator: configuring OmissionAdapter (not yet initialized by hook)")

                # Build IntentContract from session config
                try:
                    contract = IntentContract.from_dict(contract_dict)
                except Exception as e:
                    _log.warning("Failed to parse IntentContract: %s", e)
                    contract = None

                # Configure omission registry with accountability pack
                registry = reset_registry()
                apply_openclaw_accountability_pack(registry, contract=contract)

                # Create OmissionStore with same DB path as CIEU
                omission_db = cieu_db.replace(".db", "_omission.db") if cieu_db else ".ystar_omission.db"
                store = OmissionStore(db_path=omission_db)

                # Create CIEUStore for omission logging
                try:
                    from ystar.governance.cieu_store import CIEUStore
                    cieu_store_for_omission = CIEUStore(cieu_db)
                except Exception:
                    cieu_store_for_omission = None

                # Create and configure adapter
                adapter = create_adapter(store=store, registry=registry, cieu_store=cieu_store_for_omission)
                configure_omission_governance(adapter=adapter)
                self._omission_adapter = adapter
        except Exception as e:
            _log.warning("Failed to initialize OmissionAdapter: %s", e, exc_info=True)
            self._omission_adapter = None

        # 2. Configure InterventionEngine if not already configured
        try:
            from ystar.domains.openclaw.adapter import get_intervention_engine, configure_intervention_engine

            self._intervention_engine = get_intervention_engine()
            if self._intervention_engine is None and self._omission_adapter is not None:
                _log.info("Orchestrator: configuring InterventionEngine (not yet initialized by hook)")
                configure_intervention_engine()
                self._intervention_engine = get_intervention_engine()
        except Exception as e:
            _log.warning("Failed to initialize InterventionEngine: %s", e, exc_info=True)
            self._intervention_engine = None

        # 3. CIEUStore — for reading accumulated records
        try:
            from ystar.governance.cieu_store import CIEUStore
            self._cieu_store = CIEUStore(cieu_db)
        except Exception as e:
            _log.warning("Failed to initialize CIEUStore: %s", e)

        # 4. GovernanceLoop — the meta-learning orchestrator
        try:
            # Timeout protection: if _build_governance_loop hangs, fall back gracefully
            _gl_result = [None]
            def _build_gl():
                _gl_result[0] = self._build_governance_loop()
            _gl_thread = threading.Thread(target=_build_gl, daemon=True)
            _gl_thread.start()
            _gl_thread.join(timeout=5.0)
            self._governance_loop = _gl_result[0]
            if self._governance_loop is None:
                _log.warning("GovernanceLoop init timed out or failed, using light path")
        except Exception as e:
            _log.warning("Failed to initialize GovernanceLoop: %s", e, exc_info=True)

        # 5. PathBAgent — external governance agent
        # Initialized independently from GovernanceLoop: if GovernanceLoop hangs
        # or fails, Path B should still be available for external agent governance.
        try:
            self._path_b_agent = self._build_path_b_agent()
            if self._path_b_agent is not None:
                _log.info("PathBAgent initialized")
        except Exception as e:
            _log.warning("Failed to initialize PathBAgent: %s", e, exc_info=True)

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
            except Exception as e:
                _log.warning("Failed to initialize CausalEngine: %s", e)

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

        # 4. Coverage scan (every 200 calls or 30min)
        if self._should_run_coverage_scan(now):
            self._run_coverage_scan_cycle(now)

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

    def _should_run_coverage_scan(self, now: float) -> bool:
        """Check if coverage scan should run."""
        calls_since = self._call_count - self._last_coverage_scan_call
        time_since = now - self._last_coverage_scan_at
        return (
            calls_since >= COVERAGE_SCAN_INTERVAL_CALLS
            or time_since >= COVERAGE_SCAN_INTERVAL_SECS
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
                    except Exception as e:
                        _log.warning("Failed to log intervention scan event: %s", e)

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

    # ── 2. GovernanceLoop + Path A + Path B ────────────────────────────────

    def _run_governance_loop_cycle(self, agent_id: str, now: float) -> None:
        """
        Run one GovernanceLoop cycle:
          1. Feed buffered CIEU records into CausalEngine
          2. observe_from_report_engine() — collect governance observations
          3. tighten() — run meta-learning, produce suggestions
          4. Submit suggestions to ConstraintRegistry (if available)
          5. Metalearning relax: detect C_over_tightened and relax
          6. Optionally trigger Path A for high-confidence suggestions
          7. Run Path B external governance cycle

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
            # Even without GovernanceLoop, Path B can still run independently
            self._run_path_b_cycle(agent_id, now)
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
                # Still run Path B even if tighten failed
                self._run_path_b_cycle(agent_id, now)
                return

            # Step 4: Submit governance suggestions to ConstraintRegistry
            if tighten_result.governance_suggestions:
                try:
                    if hasattr(gloop, 'submit_suggestions_to_registry'):
                        gloop.submit_suggestions_to_registry(tighten_result)
                except Exception:
                    pass

            # Step 5: Metalearning relax — detect C_over_tightened and relax
            # When commission_result shows >10 C_over_tightened violations,
            # governance is being too aggressive. Extract relax suggestions.
            self._check_metalearning_relax(tighten_result)

            # Step 6: Log the governance cycle to CIEU
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

            # Step 7: Path A — if there are high-confidence suggestions and
            # the system is degraded, trigger a Path A self-governance cycle.
            if (tighten_result.overall_health in ("degraded", "critical")
                    and tighten_result.governance_suggestions):
                self._run_path_a_cycle(tighten_result, now)

            # Step 8: Path B — external governance cycle
            self._run_path_b_cycle(agent_id, now)

        except Exception:
            pass  # Never block the hook

    # ── 2b. Metalearning Relax ──────────────────────────────────────────────

    # Board threshold: if C_over_tightened count exceeds this, trigger relax
    METALEARNING_RELAX_THRESHOLD = 10

    def _check_metalearning_relax(self, tighten_result: Any) -> None:
        """
        Detect over-tightening from metalearning diagnosis and apply relax.

        When commission_result.diagnosis shows >10 C_over_tightened violations,
        governance is being too aggressive (false positive source). Extract
        relax suggestions from the commission result and write a runtime relax
        contract to reduce false positives.
        """
        cr = tighten_result.commission_result
        if cr is None:
            return

        # Extract C_over_tightened count from commission diagnosis
        c_count = 0
        if hasattr(cr, 'diagnosis') and isinstance(cr.diagnosis, dict):
            c_count = cr.diagnosis.get("C_over_tightened", 0)

        if c_count <= self.METALEARNING_RELAX_THRESHOLD:
            return

        # Over-tightened: build relax contract from commission result
        try:
            from ystar.kernel.dimensions import IntentContract

            # Extract relax suggestions from commission result:
            # 1. contract_additions contains the rules that were tightened
            # 2. If quality indicates high false_positive_rate, relax those rules
            relax_deny = []
            relax_deny_commands = []

            if hasattr(cr, 'contract_additions') and cr.contract_additions:
                additions = cr.contract_additions
                # The additions that were over-tightened should be relaxed
                # by NOT applying them (inverse signal)
                if hasattr(additions, 'deny'):
                    relax_deny = list(additions.deny)
                if hasattr(additions, 'deny_commands'):
                    relax_deny_commands = list(additions.deny_commands)

            quality_score = 0.7
            if hasattr(cr, 'quality') and cr.quality is not None:
                quality_score = getattr(cr.quality, 'quality_score', 0.7)

            relax_contract = IntentContract(
                name=f"metalearning_relax:c_over_tightened:{c_count}",
                deny=relax_deny,
                deny_commands=relax_deny_commands,
            )

            # Write runtime relax (eng-platform implements write_runtime_relax)
            try:
                from ystar.adapters.runtime_contracts import write_runtime_relax
                write_runtime_relax(
                    contract=relax_contract,
                    session_contract=self._get_session_contract(),
                    quality_score=quality_score,
                    cieu_store=self._cieu_store,
                    agent_id="governance_loop",
                )
            except ImportError:
                # runtime_contracts not yet implemented by eng-platform
                _log.info("runtime_contracts not available yet, logging relax to CIEU only")
            except Exception as e:
                _log.warning("write_runtime_relax failed: %s", e)

            # Always log the relax event to CIEU for observability
            self._log_orchestration_event(
                "metalearning_relax_applied",
                {
                    "c_over_tightened": c_count,
                    "threshold": self.METALEARNING_RELAX_THRESHOLD,
                    "relax_deny_count": len(relax_deny),
                    "relax_deny_commands_count": len(relax_deny_commands),
                    "quality_score": quality_score,
                },
            )
        except Exception as e:
            _log.warning("Metalearning relax extraction failed: %s", e)

    # ── 2c. Path B External Governance ──────────────────────────────────────

    def _run_path_b_cycle(self, agent_id: str, now: float) -> None:
        """
        Run one Path B external governance cycle.

        Path B governs external agents using the same architectural pattern
        as Path A (observation -> constraint -> compliance check). Unlike
        Path A, Path B is directed outward at external agents.

        Path B runs independently from GovernanceLoop: even if GovernanceLoop
        hangs or fails, Path B should still govern external agents.
        """
        if self._path_b_agent is None:
            return

        try:
            cycle = self._path_b_agent.run_one_cycle()

            # Log Path B cycle to CIEU
            # Use cycle.constraint (NOT cycle.applied_constraint)
            # ExternalGovernanceCycle field is "constraint" (path_b_agent.py:468)
            constraint_name = None
            if cycle.constraint is not None:
                constraint_name = cycle.constraint.name

            self._log_orchestration_event(
                "path_b_cycle",
                {
                    "cycle_id": cycle.cycle_id,
                    "applied": cycle.applied,
                    "compliant": cycle.compliant,
                    "agent_id": cycle.observation.agent_id if cycle.observation else None,
                    "constraint": constraint_name,
                    "causal_confidence": cycle.causal_confidence,
                },
            )
        except Exception as e:
            self._log_orchestration_event(
                "path_b_cycle_error",
                {"error": f"Path B cycle failed (non-fatal): {e}"},
            )

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

    def _build_path_b_agent(self) -> Optional[Any]:
        """Build a PathBAgent wired to the current CIEU store."""
        try:
            from ystar.path_b.path_b_agent import PathBAgent

            if self._cieu_store is None:
                return None

            omission_store = None
            if self._omission_adapter and hasattr(self._omission_adapter, 'engine'):
                omission_store = self._omission_adapter.engine.store

            return PathBAgent(
                cieu_store=self._cieu_store,
                omission_store=omission_store,
                causal_engine=self._causal_engine,
            )
        except Exception as e:
            _log.warning("Failed to build PathBAgent: %s", e)
            return None

    # ── Session Contract Helper ─────────────────────────────────────────────

    def _get_session_contract(self):
        """Load session.json contract as the baseline IntentContract."""
        import os
        import json
        from ystar.kernel.dimensions import IntentContract

        # Try session_cfg cache first
        contract_dict = self._session_cfg.get("contract", {})
        if contract_dict:
            try:
                return IntentContract.from_dict(contract_dict)
            except Exception:
                pass

        # Fallback: read session.json from working directory
        session_path = os.path.join(os.getcwd(), "session.json")
        if not os.path.exists(session_path):
            return IntentContract()

        try:
            with open(session_path) as f:
                cfg = json.load(f)
            cd = cfg.get("contract", {})
            return IntentContract.from_dict(cd)
        except Exception:
            return IntentContract()

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

    # ── 4. Coverage Scan ─────────────────────────────────────────────────────

    def _run_coverage_scan_cycle(self, now: float) -> None:
        """
        fail-safe包裹，不block hook。

        逻辑：
        1. 读.ystar_coverage.json（不存在则自动生成）
        2. 查询最近N分钟的CIEU，统计实际出现的agent_id
        3. 计算三维覆盖度
        4. 写入CIEU（event_type: governance_coverage_scan）
        5. 如果blind_spot_count > 上次记录：产生GovernanceSuggestion
        """
        with self._lock:
            self._last_coverage_scan_at = now
            self._last_coverage_scan_call = self._call_count

        try:
            self._do_coverage_scan(now)
        except Exception as e:
            _log.debug("Coverage scan failed (non-fatal): %s", e)

    def _do_coverage_scan(self, now: float) -> None:
        """Core coverage scan logic."""
        import json
        from pathlib import Path

        # 1. 读取或创建.ystar_coverage.json
        coverage_file = Path(".ystar_coverage.json")
        if not coverage_file.exists():
            # 自动生成（轻量版，无用户交互）
            try:
                from ystar.cli.init_cmd import _run_coverage_baseline
                _run_coverage_baseline()
            except Exception:
                return  # Cannot create baseline, skip scan

        try:
            coverage_data = json.loads(coverage_file.read_text(encoding='utf-8', errors='replace'))
        except Exception:
            return  # Cannot read coverage file, skip scan

        declared_agents = set(coverage_data.get("declared_agents", []))

        # 2. 查询最近30分钟CIEU
        if self._cieu_store:
            events = self._cieu_store.query(limit=5000)
            recent_agents = set()
            for evt in events:
                # evt is CIEUQueryResult object, use attribute access
                evt_time = getattr(evt, 'created_at', 0) if hasattr(evt, 'created_at') else evt.get('created_at', 0)
                if evt_time > now - 1800:  # 30分钟
                    agent_id = getattr(evt, 'agent_id', None) if hasattr(evt, 'agent_id') else evt.get('agent_id')
                    if agent_id:
                        recent_agents.add(agent_id)

            # 3. 计算覆盖度
            if declared_agents:
                seen_count = len(recent_agents & declared_agents)
                coverage_rate = seen_count / len(declared_agents)
                blind_spot_count = len(declared_agents - recent_agents)
            else:
                coverage_rate = 1.0
                seen_count = 0
                blind_spot_count = 0

            # 4. 写入CIEU
            self._cieu_store.write({
                "event_type": "governance_coverage_scan",
                "coverage_rate": coverage_rate,
                "agent_coverage_rate": coverage_rate,
                "blind_spot_count": blind_spot_count,
                "declared_count": len(declared_agents),
                "seen_count": seen_count,
                "timestamp": now,
            })

            # 5. 通知GovernanceLoop（如果存在）
            if hasattr(self, '_governance_loop') and self._governance_loop:
                coverage_result = {
                    "coverage_rate": coverage_rate,
                    "blind_spot_count": blind_spot_count,
                }
                self._governance_loop.coverage_scan(coverage_result)

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
                "evidence_grade": "ops",  # [P2-3] orchestration 是运维级事件
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
            "has_path_b_agent": self._path_b_agent is not None,
            "has_intervention_engine": self._intervention_engine is not None,
            "has_causal_engine": self._causal_engine is not None,
            "has_omission_adapter": self._omission_adapter is not None,
            "last_governance_loop_at": self._last_governance_loop_at,
            "last_intervention_scan_at": self._last_intervention_scan_at,
        }

    # ── Governance Heartbeat ────────────────────────────────────────────────

    def governance_heartbeat(self) -> Dict[str, Any]:
        """
        Produce a structured governance health snapshot.

        Returns a dict with:
          - timestamp: when the heartbeat was taken
          - alive: True if orchestrator is initialized and has processed calls
          - call_count: total hook calls processed
          - subsystems: dict of subsystem name → bool (alive/dead)
          - last_intervention_scan_age_s: seconds since last intervention scan
          - last_governance_loop_age_s: seconds since last governance loop cycle
          - cieu_chain_ok: True if CIEU chain integrity is valid (None if unchecked)
          - active_obligations: count of pending obligations (None if unavailable)
          - active_pulses: count of active intervention pulses (None if unavailable)
          - contract_hash: SHA-256 hash of the active IntentContract
          - circuit_breaker_armed: True if circuit breaker has tripped
          - health: "healthy" | "degraded" | "dead"
        """
        now = time.time()
        hb: Dict[str, Any] = {
            "timestamp": now,
            "alive": self._initialized and self._call_count > 0,
            "call_count": self._call_count,
        }

        # Subsystem liveness
        hb["subsystems"] = {
            "intervention_engine": self._intervention_engine is not None,
            "governance_loop": self._governance_loop is not None,
            "omission_adapter": self._omission_adapter is not None,
            "causal_engine": self._causal_engine is not None,
            "path_a": self._path_a_agent is not None,
            "path_b": self._path_b_agent is not None,
            "cieu_store": self._cieu_store is not None,
        }

        # Age of last periodic scans
        hb["last_intervention_scan_age_s"] = (
            round(now - self._last_intervention_scan_at, 1)
            if self._last_intervention_scan_at > 0 else None
        )
        hb["last_governance_loop_age_s"] = (
            round(now - self._last_governance_loop_at, 1)
            if self._last_governance_loop_at > 0 else None
        )

        # CIEU chain integrity (lightweight: verify last 10 records)
        hb["cieu_chain_ok"] = None
        if self._cieu_store is not None:
            try:
                verify = self._cieu_store.verify()
                hb["cieu_chain_ok"] = bool(verify)
            except Exception:
                hb["cieu_chain_ok"] = None

        # Active obligations
        hb["active_obligations"] = None
        if self._omission_adapter is not None:
            try:
                engine = self._omission_adapter.engine
                pending = engine.store.pending_obligations()
                hb["active_obligations"] = len(pending)
            except Exception:
                pass

        # Active intervention pulses
        hb["active_pulses"] = None
        if self._intervention_engine is not None:
            try:
                pulse_store = self._intervention_engine._pulse_store
                active = [p for p in pulse_store.list_all()
                          if p.status.value == "active"]
                hb["active_pulses"] = len(active)
            except Exception:
                pass

        # Contract hash
        hb["contract_hash"] = None
        try:
            contract = self._get_session_contract()
            if contract and contract.hash:
                hb["contract_hash"] = contract.hash
        except Exception:
            pass

        # Circuit breaker
        hb["circuit_breaker_armed"] = False
        if self._intervention_engine is not None:
            hb["circuit_breaker_armed"] = getattr(
                self._intervention_engine, "_circuit_breaker_armed", False
            )

        # Overall health assessment
        subsystems_alive = sum(1 for v in hb["subsystems"].values() if v)
        subsystems_total = len(hb["subsystems"])

        if not hb["alive"]:
            hb["health"] = "dead"
        elif hb["circuit_breaker_armed"]:
            hb["health"] = "degraded"
        elif subsystems_alive < 3:
            hb["health"] = "degraded"
        else:
            hb["health"] = "healthy"

        # Log heartbeat to CIEU
        self._log_orchestration_event("governance_heartbeat", {
            "health": hb["health"],
            "subsystems_alive": subsystems_alive,
            "subsystems_total": subsystems_total,
            "call_count": self._call_count,
            "circuit_breaker_armed": hb["circuit_breaker_armed"],
        })

        return hb


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

# Layer: Prescriptive Governance
"""
ystar.governance.residual_loop_engine  —  Residual-Driven CIEU Closed Loop
===========================================================================

AMENDMENT-014 (2026-04-12) — Residual Loop Engine (RLE)

Mathematical foundation:
  CIEU = (Xt, U, Y*, Yt+1, Rt+1)  where Rt+1 = distance(Y*, Yt+1)
  If Rt+1 > epsilon → compute next U → emit intent → agent acts → new CIEU
  This forms a closed-loop control system (Wiener/Bellman/Friston/Constitutional AI)

Key mechanisms:
  1. Convergence: Rt+1 < epsilon → STOP (target reached)
  2. Oscillation detection: ±振荡模式 → BREAK (avoid infinite loops)
  3. Escalation: iterations > max → ESCALATE_BOARD (human intervention)
  4. Damping: gamma < 1.0 → reduce correction magnitude each iteration

Usage::

    from ystar.governance.residual_loop_engine import ResidualLoopEngine
    from ystar.governance.autonomy_engine import AutonomyEngine
    from ystar.governance.cieu_store import CIEUStore

    cieu_store = CIEUStore()
    autonomy_engine = AutonomyEngine(mode="desire-driven", cieu_store=cieu_store)

    rle = ResidualLoopEngine(
        autonomy_engine=autonomy_engine,
        cieu_store=cieu_store,
        target_provider=lambda event: event.get("target_y_star"),
        max_iterations=10,
        convergence_epsilon=0.05,
        damping_gamma=0.9
    )

    # Hook integration: on every CIEU event
    def on_cieu_event(event):
        rle.on_cieu_event(event)

References:
  - Wiener (1948): Cybernetics: Control and Communication
  - Bellman (1957): Dynamic Programming and Optimal Control
  - Friston (2010): Active Inference and Free Energy Principle
  - Anthropic (2022): Constitutional AI — RLHF with AI feedback
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from typing import Any, Callable, Dict, List, Optional

_log = logging.getLogger(__name__)


class ResidualLoopEngine:
    """
    Closed-loop residual-driven controller for CIEU.

    On each CIEU event (Xt, U, Y*, Yt+1, Rt+1):
      1. Compute Rt+1 = distance(Y*, Yt+1)
      2. If Rt+1 < epsilon: emit CONVERGED, stop
      3. If oscillation detected: emit OSCILLATION_BREAK, stop
      4. If iterations > max: emit ESCALATE_BOARD, stop
      5. Else: next_U = autonomy_engine.compute_next_action(...) and emit_intent(next_U)

    Parameters
    ----------
    autonomy_engine : AutonomyEngine
        The autonomy engine that computes next actions.
    cieu_store : CIEUStore
        CIEU event store (for reading/writing events).
    target_provider : Callable[[Dict], Any]
        Function that extracts Y* from a CIEU event dict.
        Signature: event_dict -> Y* (or None if no target).
    max_iterations : int
        Maximum iterations before escalating to Board (default 10).
    convergence_epsilon : float
        Residual threshold for convergence (default 0.0 — exact match).
    damping_gamma : float
        Damping factor for correction magnitude (default 0.9).
        gamma < 1.0 reduces oscillation risk.
    distance_function : Callable[[Any, Any], float], optional
        Custom distance function. Default: _default_distance.
    """

    def __init__(
        self,
        autonomy_engine: Any,  # AutonomyEngine
        cieu_store: Any,  # CIEUStore
        target_provider: Callable[[Dict], Any],
        max_iterations: int = 10,
        convergence_epsilon: float = 0.0,
        damping_gamma: float = 0.9,
        distance_function: Optional[Callable[[Any, Any], float]] = None,
    ):
        self.autonomy_engine = autonomy_engine
        self.cieu_store = cieu_store
        self.target_provider = target_provider
        self.max_iterations = max_iterations
        self.convergence_epsilon = convergence_epsilon
        self.damping_gamma = damping_gamma
        self.distance_function = distance_function or self._default_distance

        # Per-session loop state (keyed by session_id)
        self._loop_state: Dict[str, Dict] = {}
        # Oscillation detection: ring buffer of last N residuals
        self._residual_history_size = 5

    def on_cieu_event(self, event: Dict) -> None:
        """
        Process a CIEU event and trigger next action if residual > epsilon.

        Parameters
        ----------
        event : Dict
            CIEU event dict with keys:
              - session_id
              - agent_id
              - event_type
              - params (contains Y*, Yt+1, etc.)
              - optional: target_y_star, residual_rt_plus_1
        """
        session_id = event.get("session_id", "unknown")
        agent_id = event.get("agent_id", "unknown")
        params = event.get("params", {})

        # Extract Y* and Yt+1
        y_star = self.target_provider(event)
        y_actual = params.get("y_actual") or params.get("result")

        if y_star is None:
            # No target defined, skip residual loop
            return

        # Compute residual
        rt_plus_1 = self._residual_distance(y_star, y_actual)

        # Initialize loop state if needed
        if session_id not in self._loop_state:
            self._loop_state[session_id] = {
                "iterations": 0,
                "residual_history": deque(maxlen=self._residual_history_size),
                "last_action_time": time.time(),
            }

        state = self._loop_state[session_id]
        state["residual_history"].append(rt_plus_1)
        state["iterations"] += 1

        # Log residual
        _log.info(f"[RLE] session={session_id} agent={agent_id} "
                  f"iteration={state['iterations']} Rt+1={rt_plus_1:.4f}")

        # Check convergence
        if rt_plus_1 < self.convergence_epsilon:
            self._emit_convergence(session_id, agent_id, rt_plus_1)
            self._cleanup_session(session_id)
            return

        # Check oscillation
        if self._oscillation_detected(session_id):
            self._emit_oscillation_break(session_id, agent_id, rt_plus_1)
            self._cleanup_session(session_id)
            return

        # Check max iterations
        if state["iterations"] > self.max_iterations:
            self._emit_escalate_board(session_id, agent_id, rt_plus_1)
            self._cleanup_session(session_id)
            return

        # Compute next action (damped)
        next_u = self._compute_next_action(agent_id, y_star, y_actual, rt_plus_1, state)
        if next_u:
            self._emit_intent(session_id, agent_id, next_u, rt_plus_1, state["iterations"])
            state["last_action_time"] = time.time()

    def _residual_distance(self, y_star: Any, y_actual: Any) -> float:
        """
        Compute distance between target and actual.

        Uses custom distance_function if provided, else _default_distance.
        """
        try:
            return self.distance_function(y_star, y_actual)
        except Exception as e:
            _log.error(f"[RLE] distance computation error: {e}")
            return float("inf")  # Treat error as infinite distance

    @staticmethod
    def _default_distance(y_star: Any, y_actual: Any) -> float:
        """
        Default distance function (handles common types).

        Supports:
          - str: edit distance (normalized)
          - int/float: absolute difference
          - dict: key-value diff count (normalized)
          - list: set difference (normalized)
          - bool: 0.0 if equal, 1.0 if not
        """
        if y_star is None and y_actual is None:
            return 0.0
        if y_star is None or y_actual is None:
            return 1.0

        # String: normalized Levenshtein
        if isinstance(y_star, str) and isinstance(y_actual, str):
            import difflib
            ratio = difflib.SequenceMatcher(None, y_star, y_actual).ratio()
            return 1.0 - ratio

        # Numeric: absolute difference (normalized by max)
        if isinstance(y_star, (int, float)) and isinstance(y_actual, (int, float)):
            max_val = max(abs(y_star), abs(y_actual), 1.0)
            return abs(y_star - y_actual) / max_val

        # Dict: key-value diff count
        if isinstance(y_star, dict) and isinstance(y_actual, dict):
            all_keys = set(y_star.keys()) | set(y_actual.keys())
            diff_count = sum(1 for k in all_keys if y_star.get(k) != y_actual.get(k))
            return diff_count / max(len(all_keys), 1)

        # List: set difference
        if isinstance(y_star, list) and isinstance(y_actual, list):
            s_star = set(y_star)
            s_actual = set(y_actual)
            diff = len(s_star ^ s_actual)
            return diff / max(len(s_star | s_actual), 1)

        # Bool: binary
        if isinstance(y_star, bool) and isinstance(y_actual, bool):
            return 0.0 if y_star == y_actual else 1.0

        # Fallback: string equality
        return 0.0 if y_star == y_actual else 1.0

    def _oscillation_detected(self, session_id: str) -> bool:
        """
        Detect oscillation in residual history.

        Simple heuristic: if last N residuals show ±alternating pattern
        (increasing then decreasing then increasing, etc.), flag oscillation.
        """
        state = self._loop_state.get(session_id)
        if not state or len(state["residual_history"]) < 4:
            return False

        history = list(state["residual_history"])
        # Check for alternating increase/decrease pattern
        diffs = [history[i+1] - history[i] for i in range(len(history) - 1)]
        sign_changes = sum(1 for i in range(len(diffs) - 1) if diffs[i] * diffs[i+1] < 0)

        # If ≥2 sign changes in last 4 steps, flag oscillation
        if sign_changes >= 2:
            _log.warning(f"[RLE] oscillation detected: session={session_id} "
                         f"history={history} sign_changes={sign_changes}")
            return True
        return False

    def _compute_next_action(
        self,
        agent_id: str,
        y_star: Any,
        y_actual: Any,
        rt_plus_1: float,
        state: Dict
    ) -> Optional[str]:
        """
        Compute next action U based on residual.

        Uses autonomy_engine.pull_next_action with damping.
        Damping: correction_magnitude *= gamma^iteration
        """
        iteration = state["iterations"]
        damping_factor = self.damping_gamma ** iteration

        # For now, use autonomy_engine.pull_next_action directly
        # Future: pass residual context to autonomy_engine for smarter action selection
        action = self.autonomy_engine.pull_next_action(agent_id)
        if action:
            # Apply damping to priority (optional heuristic)
            # Lower damping_factor → lower urgency
            # This is a placeholder; real implementation would pass residual to action planner
            return action.description
        return None

    def _emit_intent(
        self,
        session_id: str,
        agent_id: str,
        next_u: str,
        rt_plus_1: float,
        iteration: int
    ) -> None:
        """Emit RESIDUAL_LOOP_ACTION intent to CIEU."""
        event = {
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "agent_id": agent_id,
            "event_type": "RESIDUAL_LOOP_ACTION",
            "decision": "info",
            "evidence_grade": "ops",
            "created_at": time.time(),
            "seq_global": time.time_ns() // 1000,
            "params": {
                "next_action": next_u,
                "residual_rt_plus_1": rt_plus_1,
                "iteration": iteration,
            },
            "violations": [],
            "drift_detected": False,
            "human_initiator": agent_id,
        }
        self._write_cieu(event)
        _log.info(f"[RLE] emitted RESIDUAL_LOOP_ACTION: {next_u[:60]}")

    def _emit_convergence(self, session_id: str, agent_id: str, rt_plus_1: float) -> None:
        """Emit RESIDUAL_LOOP_CONVERGED event."""
        event = {
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "agent_id": agent_id,
            "event_type": "RESIDUAL_LOOP_CONVERGED",
            "decision": "info",
            "evidence_grade": "ops",
            "created_at": time.time(),
            "seq_global": time.time_ns() // 1000,
            "params": {"final_residual": rt_plus_1},
            "violations": [],
            "drift_detected": False,
            "human_initiator": agent_id,
        }
        self._write_cieu(event)
        _log.info(f"[RLE] CONVERGED: session={session_id} Rt+1={rt_plus_1:.4f}")

    def _emit_oscillation_break(self, session_id: str, agent_id: str, rt_plus_1: float) -> None:
        """Emit RESIDUAL_LOOP_OSCILLATION event."""
        event = {
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "agent_id": agent_id,
            "event_type": "RESIDUAL_LOOP_OSCILLATION",
            "decision": "escalate",
            "evidence_grade": "ops",
            "created_at": time.time(),
            "seq_global": time.time_ns() // 1000,
            "params": {
                "final_residual": rt_plus_1,
                "history": list(self._loop_state[session_id]["residual_history"]),
            },
            "violations": ["oscillation_detected"],
            "drift_detected": True,
            "human_initiator": agent_id,
        }
        self._write_cieu(event)
        _log.warning(f"[RLE] OSCILLATION_BREAK: session={session_id}")

    def _emit_escalate_board(self, session_id: str, agent_id: str, rt_plus_1: float) -> None:
        """Emit RESIDUAL_LOOP_ESCALATE event."""
        event = {
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "agent_id": agent_id,
            "event_type": "RESIDUAL_LOOP_ESCALATE",
            "decision": "escalate",
            "evidence_grade": "ops",
            "created_at": time.time(),
            "seq_global": time.time_ns() // 1000,
            "params": {
                "final_residual": rt_plus_1,
                "max_iterations": self.max_iterations,
                "iterations": self._loop_state[session_id]["iterations"],
            },
            "violations": ["max_iterations_exceeded"],
            "drift_detected": True,
            "human_initiator": agent_id,
        }
        self._write_cieu(event)
        _log.warning(f"[RLE] ESCALATE_BOARD: session={session_id} iterations={self.max_iterations}")

    def _write_cieu(self, event: Dict) -> None:
        """Write event to CIEU store (fail-open)."""
        try:
            self.cieu_store.write_dict(event)
        except Exception as e:
            _log.error(f"[RLE] CIEU write error: {e}")

    def _cleanup_session(self, session_id: str) -> None:
        """Clean up loop state for session."""
        if session_id in self._loop_state:
            del self._loop_state[session_id]

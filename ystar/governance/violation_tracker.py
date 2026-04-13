# Layer 3.2: Violation Tracker with Hard Block on 2nd Violation
"""
Track violations per agent and escalate WARN → DENY on repeat violations within time window.
Eliminates 155 soft lock sequences where agents ignore warnings.

Design: AMENDMENT-015 Layer 3.2
Impact: Forces compliance before circuit breaker arms
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

_log = logging.getLogger(__name__)


@dataclass
class ViolationHistory:
    """Track violation timestamps for a specific (agent, violation_type) pair."""
    agent_id: str
    violation_type: str
    timestamps: List[float] = field(default_factory=list)
    last_warning_at: float = 0.0


class ViolationTracker:
    """
    Tracks repeat violations per agent.
    First violation = WARNING
    Second violation within window = DENY
    """

    def __init__(self, window_sec: int = 300):
        """
        Args:
            window_sec: Time window for tracking repeat violations (default 5 minutes)
        """
        self.window_sec = window_sec
        # {(agent_id, violation_type): ViolationHistory}
        self.history: Dict[Tuple[str, str], ViolationHistory] = {}

    def check_repeat_violation(
        self,
        agent_id: str,
        violation_type: str
    ) -> Tuple[str, str]:
        """
        Check if this is a repeat violation within the time window.

        Returns:
            (decision, reason) tuple:
            - ("WARN", reason) for first violation
            - ("DENY", reason) for repeat violation within window
        """
        now = time.time()
        key = (agent_id, violation_type)

        # Get or create history
        if key not in self.history:
            self.history[key] = ViolationHistory(
                agent_id=agent_id,
                violation_type=violation_type
            )

        hist = self.history[key]

        # Clean old timestamps outside window
        cutoff = now - self.window_sec
        hist.timestamps = [ts for ts in hist.timestamps if ts > cutoff]

        # Check repeat count
        if len(hist.timestamps) >= 1:
            # Second+ violation within window
            first_violation_ago = now - hist.timestamps[0]
            return (
                "DENY",
                f"Repeated {violation_type} violation within {first_violation_ago:.0f}s. "
                f"First violation was warning, second is DENY. "
                f"Previous violations: {len(hist.timestamps)}"
            )

        # First violation in window
        hist.timestamps.append(now)
        hist.last_warning_at = now
        return (
            "WARN",
            f"First {violation_type} violation. "
            f"Fix this issue before your next action or it will be DENIED. "
            f"You have {self.window_sec}s to comply."
        )

    def clear_violations(self, agent_id: str, violation_type: str) -> bool:
        """
        Clear violation history for a specific agent+violation_type.
        Called when obligation is fulfilled.

        Returns:
            True if history was cleared, False if no history existed
        """
        key = (agent_id, violation_type)
        if key in self.history:
            del self.history[key]
            _log.info(f"Cleared violation history for {agent_id}: {violation_type}")
            return True
        return False

    def clear_all(self, agent_id: str) -> int:
        """
        Clear all violation history for an agent.
        Called when agent completes major compliance action.

        Returns:
            Number of violation types cleared
        """
        keys_to_delete = [k for k in self.history.keys() if k[0] == agent_id]
        for key in keys_to_delete:
            del self.history[key]

        if keys_to_delete:
            _log.info(f"Cleared all violations for {agent_id}: {len(keys_to_delete)} types")

        return len(keys_to_delete)

    def get_active_violations(self, agent_id: str) -> List[ViolationHistory]:
        """Get all active violations for an agent (within time window)."""
        now = time.time()
        cutoff = now - self.window_sec

        active = []
        for (aid, vtype), hist in self.history.items():
            if aid == agent_id:
                # Filter timestamps within window
                recent = [ts for ts in hist.timestamps if ts > cutoff]
                if recent:
                    active.append(ViolationHistory(
                        agent_id=aid,
                        violation_type=vtype,
                        timestamps=recent,
                        last_warning_at=hist.last_warning_at
                    ))

        return active

    def stats(self) -> Dict[str, int]:
        """Return violation tracking statistics."""
        now = time.time()
        cutoff = now - self.window_sec

        total_agents = len(set(k[0] for k in self.history.keys()))
        total_types = len(self.history)
        active_violations = sum(
            1 for hist in self.history.values()
            if any(ts > cutoff for ts in hist.timestamps)
        )

        return {
            "total_agents": total_agents,
            "total_violation_types": total_types,
            "active_within_window": active_violations,
            "window_sec": self.window_sec
        }

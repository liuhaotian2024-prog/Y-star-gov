"""
tests/test_circuit_breaker.py — Circuit Breaker for InterventionEngine

P0: Prevents violation snowball effect.
When cumulative violations reach threshold (20), pulse generation stops.
Manual reset via reset_circuit_breaker() re-enables pulse generation.
"""
import pytest
import time
import uuid

from ystar.governance.intervention_engine import InterventionEngine
from ystar.governance.intervention_models import (
    InterventionLevel, InterventionStatus,
)
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, OmissionViolation,
    Severity, GEventType,
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.cieu_store import NullCIEUStore


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_obligation(actor_id="test_actor", overdue_secs=60) -> ObligationRecord:
    now = time.time()
    return ObligationRecord(
        obligation_id=uuid.uuid4().hex[:8],
        entity_id="test_entity",
        actor_id=actor_id,
        obligation_type="test_obligation",
        trigger_event_id=uuid.uuid4().hex[:8],
        required_event_types=["ack"],
        due_at=now - overdue_secs,
        hard_overdue_secs=30.0,
        severity=Severity.MEDIUM,
        created_at=now - 400,
        updated_at=now,
    )


def _make_violation(obligation_id: str, actor_id="test_actor") -> OmissionViolation:
    return OmissionViolation(
        violation_id=uuid.uuid4().hex[:8],
        obligation_id=obligation_id,
        omission_type="soft_overdue",
        actor_id=actor_id,
        detected_at=time.time(),
        overdue_secs=10.0,
        details={"stage": "soft_overdue"},
    )


def _make_hard_violation(obligation_id: str) -> OmissionViolation:
    return OmissionViolation(
        violation_id=uuid.uuid4().hex[:8],
        obligation_id=obligation_id,
        omission_type="hard_overdue",
        actor_id="test_actor",
        detected_at=time.time(),
        overdue_secs=120.0,
        details={"stage": "hard_overdue"},
    )


def _build_engine(threshold=20):
    store = InMemoryOmissionStore()
    engine = InterventionEngine(
        omission_store=store,
        cieu_store=NullCIEUStore(),
    )
    engine._circuit_breaker_threshold = threshold
    return engine, store


# ── Tests ────────────────────────────────────────────────────────────────────

class TestCircuitBreakerArming:
    """Circuit breaker arms at threshold violations."""

    def test_not_armed_below_threshold(self):
        """Under threshold: circuit breaker stays disarmed."""
        engine, store = _build_engine(threshold=20)

        # Create 10 obligations and violations (below threshold)
        for _ in range(10):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert not engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 10

    def test_armed_at_threshold(self):
        """Exactly at threshold: circuit breaker arms."""
        engine, store = _build_engine(threshold=5)

        for _ in range(5):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 5

    def test_armed_above_threshold(self):
        """Over threshold: circuit breaker stays armed."""
        engine, store = _build_engine(threshold=3)

        for _ in range(7):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 7

    def test_batch_violations_arm(self):
        """A single batch with enough violations arms the breaker."""
        engine, store = _build_engine(threshold=3)

        violations = []
        for _ in range(5):
            ob = _make_obligation()
            store.add_obligation(ob)
            violations.append(_make_violation(ob.obligation_id))

        engine.process_violations(violations)
        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 5

    def test_default_threshold_is_20(self):
        """Board requirement: default threshold is 20."""
        store = InMemoryOmissionStore()
        engine = InterventionEngine(
            omission_store=store,
            cieu_store=NullCIEUStore(),
        )
        assert engine._circuit_breaker_threshold == 50


class TestCircuitBreakerPulseRejection:
    """Armed circuit breaker rejects pulse generation."""

    def test_armed_returns_empty_result(self):
        """After arming, process_violations returns empty result (no pulses)."""
        engine, store = _build_engine(threshold=3)

        # Arm the breaker
        for _ in range(3):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed

        # Now try to process more violations -- should produce no pulses
        ob = _make_obligation()
        store.add_obligation(ob)
        v = _make_violation(ob.obligation_id)
        result = engine.process_violations([v])

        assert len(result.pulses_fired) == 0
        assert len(result.capability_restrictions) == 0
        assert len(result.reroutes) == 0

    def test_hard_violations_also_rejected(self):
        """Hard overdue violations are also rejected when breaker is armed."""
        engine, store = _build_engine(threshold=2)

        # Arm the breaker with soft violations
        for _ in range(2):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed

        # Hard violation should also be rejected
        ob = _make_obligation(overdue_secs=120)
        store.add_obligation(ob)
        v = _make_hard_violation(ob.obligation_id)
        result = engine.process_violations([v])

        assert len(result.pulses_fired) == 0

    def test_violation_count_continues_after_arming(self):
        """Violation count keeps incrementing even after arming."""
        engine, store = _build_engine(threshold=2)

        for _ in range(5):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 5

    def test_pulses_fire_before_threshold(self):
        """Before threshold, pulses are generated normally."""
        engine, store = _build_engine(threshold=20)

        ob = _make_obligation()
        store.add_obligation(ob)
        v = _make_violation(ob.obligation_id)
        result = engine.process_violations([v])

        assert not engine._circuit_breaker_armed
        assert len(result.pulses_fired) > 0


class TestCircuitBreakerReset:
    """reset_circuit_breaker() clears all state."""

    def test_reset_clears_armed_state(self):
        """After reset, circuit breaker is disarmed."""
        engine, store = _build_engine(threshold=2)

        # Arm it
        for _ in range(3):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 3

        # Reset
        engine.reset_circuit_breaker()

        assert not engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 0

    def test_pulses_resume_after_reset(self):
        """After reset, pulse generation resumes."""
        engine, store = _build_engine(threshold=2)

        # Arm
        for _ in range(2):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed

        # Reset
        engine.reset_circuit_breaker()

        # Now pulses should fire again
        ob = _make_obligation()
        store.add_obligation(ob)
        v = _make_violation(ob.obligation_id)
        result = engine.process_violations([v])

        assert not engine._circuit_breaker_armed
        assert len(result.pulses_fired) > 0

    def test_reset_when_not_armed(self):
        """Reset on non-armed breaker is a no-op (no crash)."""
        engine, store = _build_engine(threshold=20)

        assert not engine._circuit_breaker_armed

        # Should not raise
        engine.reset_circuit_breaker()

        assert not engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 0

    def test_double_reset(self):
        """Double reset is idempotent."""
        engine, store = _build_engine(threshold=2)

        # Arm
        for _ in range(2):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        engine.reset_circuit_breaker()
        engine.reset_circuit_breaker()

        assert not engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 0

    def test_re_arm_after_reset(self):
        """After reset, breaker can arm again at threshold."""
        engine, store = _build_engine(threshold=2)

        # Arm
        for _ in range(2):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed

        # Reset
        engine.reset_circuit_breaker()
        assert not engine._circuit_breaker_armed

        # Re-arm
        for _ in range(2):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 2


class TestCircuitBreakerBoard20:
    """Integration test: Board requirement of threshold=20."""

    def test_board_threshold_20_violations(self):
        """
        Board P0 requirement: exactly 20 violations arms the breaker,
        19 does not.
        """
        engine, store = _build_engine(threshold=20)

        # 19 violations: not armed
        for _ in range(19):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert not engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 19

        # 20th violation: armed
        ob = _make_obligation()
        store.add_obligation(ob)
        v = _make_violation(ob.obligation_id)
        result = engine.process_violations([v])

        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count == 20

    def test_board_threshold_21st_violation_rejected(self):
        """After 20 violations, the 21st produces no pulses."""
        engine, store = _build_engine(threshold=20)

        for _ in range(20):
            ob = _make_obligation()
            store.add_obligation(ob)
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        assert engine._circuit_breaker_armed

        # 21st
        ob = _make_obligation()
        store.add_obligation(ob)
        v = _make_violation(ob.obligation_id)
        result = engine.process_violations([v])

        assert len(result.pulses_fired) == 0
        assert engine._circuit_breaker_violation_count == 21


class TestCircuitBreakerSlidingWindow:
    """B1 fix 2026-04-12: violation count uses sliding window, not cumulative."""

    def test_old_violations_decay_out_of_window(self):
        """Violations older than window_secs should not count toward threshold."""
        engine, store = _build_engine(threshold=20)
        engine._circuit_breaker_window_secs = 60  # 1 min window for test

        t0 = 1_000_000.0
        # Inject 15 violations at t0 (below threshold)
        for i in range(15):
            engine._circuit_breaker_window.append((t0, 1))
        engine._circuit_breaker_violation_count = 15

        # Fast-forward 2 min; add 10 more violations — old 15 should drop out
        engine._now = lambda: t0 + 120
        ob = _make_obligation()
        store.add_obligation(ob)
        for _ in range(10):
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])

        # Only the 10 new violations are within window
        assert engine._circuit_breaker_violation_count == 10
        assert not engine._circuit_breaker_armed

    def test_sustained_rate_still_arms(self):
        """Sustained high violation rate within window still arms breaker."""
        engine, store = _build_engine(threshold=20)
        engine._circuit_breaker_window_secs = 600  # 10 min

        t = [1_000_000.0]
        engine._now = lambda: t[0]
        ob = _make_obligation()
        store.add_obligation(ob)

        # 20 violations within 5 min (inside 10-min window)
        for _ in range(20):
            v = _make_violation(ob.obligation_id)
            engine.process_violations([v])
            t[0] += 15  # 15 sec apart = 5 min total

        assert engine._circuit_breaker_armed
        assert engine._circuit_breaker_violation_count >= 20

    def test_reset_clears_window(self):
        """reset_circuit_breaker clears the sliding window too."""
        engine, store = _build_engine(threshold=20)
        engine._circuit_breaker_window.append((time.time(), 5))
        engine._circuit_breaker_violation_count = 5

        engine.reset_circuit_breaker()

        assert engine._circuit_breaker_window == []
        assert engine._circuit_breaker_violation_count == 0

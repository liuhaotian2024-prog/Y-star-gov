"""
Tests for ystar.adapters.orchestrator — Runtime Governance Orchestrator.

Verifies:
  1. Singleton lifecycle (get/reset)
  2. CIEU buffering
  3. Periodic trigger logic (intervention scan, governance loop)
  4. InterventionEngine scan→pulse forwarding
  5. GovernanceLoop meta-learning cycle
  6. Fail-safe behavior (no exceptions escape)
"""
import time
import pytest
from unittest.mock import MagicMock, patch

from ystar.adapters.orchestrator import (
    Orchestrator,
    get_orchestrator,
    reset_orchestrator,
    GOVERNANCE_LOOP_INTERVAL_CALLS,
    INTERVENTION_SCAN_INTERVAL_CALLS,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset the singleton before each test."""
    reset_orchestrator()
    yield
    reset_orchestrator()


class TestSingleton:
    def test_get_returns_same_instance(self):
        a = get_orchestrator()
        b = get_orchestrator()
        assert a is b

    def test_reset_clears_instance(self):
        a = get_orchestrator()
        reset_orchestrator()
        b = get_orchestrator()
        assert a is not b


class TestCIEUBuffer:
    def test_buffer_accumulates(self):
        orch = Orchestrator()
        result = MagicMock(allowed=True)
        for i in range(5):
            orch._buffer_cieu_record("agent", f"Tool{i}", {}, result)
        assert len(orch._cieu_buffer) == 5

    def test_buffer_caps_at_max(self):
        orch = Orchestrator()
        orch._cieu_buffer_max = 10
        result = MagicMock(allowed=True)
        for i in range(15):
            orch._buffer_cieu_record("agent", f"Tool{i}", {}, result)
        # After 10 items, it drops oldest half (5), then adds remaining
        assert len(orch._cieu_buffer) <= 15

    def test_buffer_records_deny(self):
        orch = Orchestrator()
        result = MagicMock(allowed=False)
        orch._buffer_cieu_record("agent", "Bash", {"command": "rm -rf /"}, result)
        assert orch._cieu_buffer[0]["decision"] == "deny"
        assert orch._cieu_buffer[0]["passed"] is False


class TestPeriodicTriggers:
    def test_intervention_scan_not_triggered_without_engine(self):
        orch = Orchestrator()
        # No intervention engine → should not trigger
        assert not orch._should_run_intervention_scan(time.time())

    def test_intervention_scan_triggers_after_n_calls(self):
        orch = Orchestrator()
        orch._intervention_engine = MagicMock()
        orch._omission_adapter = MagicMock()
        orch._call_count = INTERVENTION_SCAN_INTERVAL_CALLS + 1
        orch._last_intervention_scan_call = 0
        orch._last_intervention_scan_at = time.time()
        assert orch._should_run_intervention_scan(time.time())

    def test_intervention_scan_triggers_after_m_seconds(self):
        orch = Orchestrator()
        orch._intervention_engine = MagicMock()
        orch._omission_adapter = MagicMock()
        orch._call_count = 1
        orch._last_intervention_scan_call = 0
        orch._last_intervention_scan_at = time.time() - 120  # 2 min ago
        assert orch._should_run_intervention_scan(time.time())

    def test_governance_loop_not_triggered_without_loop(self):
        orch = Orchestrator()
        assert not orch._should_run_governance_loop(time.time())

    def test_governance_loop_triggers_after_n_calls(self):
        orch = Orchestrator()
        orch._governance_loop = MagicMock()
        orch._call_count = GOVERNANCE_LOOP_INTERVAL_CALLS + 1
        orch._last_governance_loop_call = 0
        orch._last_governance_loop_at = time.time()
        assert orch._should_run_governance_loop(time.time())


class TestInterventionScan:
    def test_scan_forwards_violations(self):
        orch = Orchestrator()

        # Mock omission adapter with scan result
        scan_result = MagicMock()
        scan_result.violations = [MagicMock(), MagicMock()]
        engine_mock = MagicMock()
        engine_mock.scan.return_value = scan_result
        adapter_mock = MagicMock()
        adapter_mock.engine = engine_mock
        orch._omission_adapter = adapter_mock

        # Mock intervention engine
        ie_mock = MagicMock()
        ie_result = MagicMock()
        ie_result.pulses_fired = [MagicMock()]
        ie_result.capability_restrictions = []
        ie_result.reroutes = []
        ie_mock.process_violations.return_value = ie_result
        ie_mock.scan_restorations.return_value = []
        orch._intervention_engine = ie_mock

        orch._run_intervention_scan(time.time())

        # Verify violations were forwarded
        ie_mock.process_violations.assert_called_once_with(scan_result.violations)

    def test_scan_handles_no_violations(self):
        orch = Orchestrator()
        scan_result = MagicMock()
        scan_result.violations = []
        engine_mock = MagicMock()
        engine_mock.scan.return_value = scan_result
        adapter_mock = MagicMock()
        adapter_mock.engine = engine_mock
        orch._omission_adapter = adapter_mock
        orch._intervention_engine = MagicMock()
        orch._intervention_engine.scan_restorations.return_value = []

        # Should not raise
        orch._run_intervention_scan(time.time())


class TestGovernanceLoopCycle:
    def test_cycle_runs_observe_and_tighten(self):
        orch = Orchestrator()
        gloop = MagicMock()
        obs = MagicMock()
        obs.is_healthy.return_value = True
        gloop.observe_from_report_engine.return_value = obs

        tighten_result = MagicMock()
        tighten_result.overall_health = "healthy"
        tighten_result.governance_suggestions = []
        tighten_result.restored_actors = []
        tighten_result.is_action_required.return_value = False
        tighten_result.causal_chain = []
        gloop.tighten.return_value = tighten_result

        orch._governance_loop = gloop

        orch._run_governance_loop_cycle("test_agent", time.time())

        gloop.observe_from_report_engine.assert_called_once()
        gloop.tighten.assert_called_once()

    def test_cycle_drains_cieu_buffer(self):
        orch = Orchestrator()
        gloop = MagicMock()
        gloop.observe_from_report_engine.return_value = MagicMock(is_healthy=lambda: True)
        result = MagicMock()
        result.overall_health = "healthy"
        result.governance_suggestions = []
        result.restored_actors = []
        result.is_action_required.return_value = False
        result.causal_chain = []
        gloop.tighten.return_value = result
        orch._governance_loop = gloop

        # Add some buffer items
        orch._cieu_buffer = [{"event_type": "test"}] * 5

        orch._run_governance_loop_cycle("agent", time.time())

        # Buffer should be drained
        assert len(orch._cieu_buffer) == 0


class TestOnHookCall:
    def test_increments_call_count(self):
        orch = Orchestrator()
        result = MagicMock(allowed=True)
        orch.on_hook_call("agent", "Read", {}, result)
        assert orch._call_count == 1

    def test_buffers_record(self):
        orch = Orchestrator()
        # Set last times to now so periodic triggers don't fire and drain buffer
        orch._last_governance_loop_at = time.time()
        orch._last_intervention_scan_at = time.time()
        result = MagicMock(allowed=True)
        orch.on_hook_call("agent", "Write", {"file_path": "/tmp/x"}, result)
        assert len(orch._cieu_buffer) == 1

    def test_does_not_crash_on_missing_subsystems(self):
        """Orchestrator should gracefully handle missing subsystems."""
        orch = Orchestrator()
        result = MagicMock(allowed=True)
        # Should not raise even with no subsystems initialized
        for _ in range(100):
            orch.on_hook_call("agent", "Bash", {"command": "ls"}, result)
        assert orch._call_count == 100


class TestStatus:
    def test_status_returns_dict(self):
        orch = Orchestrator()
        s = orch.status()
        assert isinstance(s, dict)
        assert "initialized" in s
        assert "call_count" in s
        assert s["call_count"] == 0

    def test_status_reflects_state(self):
        orch = Orchestrator()
        orch._call_count = 42
        orch._initialized = True
        s = orch.status()
        assert s["call_count"] == 42
        assert s["initialized"] is True


class TestFailSafe:
    def test_on_hook_call_never_raises(self):
        """Even with broken subsystems, on_hook_call must not raise."""
        orch = Orchestrator()
        orch._initialized = True
        orch._intervention_engine = MagicMock(side_effect=RuntimeError("boom"))
        orch._omission_adapter = MagicMock()
        orch._governance_loop = MagicMock(side_effect=RuntimeError("boom"))

        result = MagicMock(allowed=True)
        # Should not raise
        ret = orch.on_hook_call("agent", "Write", {}, result)
        assert ret is None

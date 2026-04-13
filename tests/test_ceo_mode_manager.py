#!/usr/bin/env python3
"""
Unit tests for CEO Mode Manager

Tests:
- Autonomous trigger by Board silence (≥15min)
- Autonomous revoke on Board message
- Break-glass trigger by T3 (must_dispatch 3x deny)
- Break-glass 5min idle revoke
- Break-glass 20min hard cap
- Break-glass trigger cleared auto-revoke
- git push denied in all modes (tested in boundary_enforcer tests)
"""

import json
import os
import sys
import time
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts to path
WORKSPACE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "scripts"))

from ceo_mode_manager import CEOModeManager, BOARD_SILENCE_THRESHOLD, BREAK_GLASS_IDLE_TIMEOUT, BREAK_GLASS_HARD_CAP


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace for testing"""
    mode_file = tmp_path / ".ystar_ceo_mode.json"
    last_board_msg = tmp_path / "scripts" / ".ystar_last_board_msg"
    last_board_msg.parent.mkdir(parents=True, exist_ok=True)

    with patch("ceo_mode_manager.MODE_FILE", mode_file):
        with patch("ceo_mode_manager.LAST_BOARD_MSG", last_board_msg):
            manager = CEOModeManager()
            manager.mode_file = mode_file
            manager.last_board_msg_file = last_board_msg
            yield manager, mode_file, last_board_msg


class TestAutonomousMode:
    """Test autonomous mode triggers and revocation"""

    def test_enter_autonomous_on_board_silence(self, temp_workspace):
        """Board silence ≥15min → autonomous mode"""
        manager, mode_file, last_board_msg = temp_workspace

        # Set last Board message to 16 minutes ago
        now = time.time()
        last_board_msg.write_text(str(now - (BOARD_SILENCE_THRESHOLD + 60)))

        # Tick should trigger autonomous (mock trigger checks to prevent break_glass)
        with patch.object(manager, "evaluate_triggers", return_value=(None, {})):
            with patch("ceo_mode_manager.emit_cieu"):
                state = manager.tick()

        assert state["mode"] == "autonomous"
        assert state["entered_at"] is not None
        assert state["expires_at"] is None  # no expiry for autonomous

    def test_autonomous_revoke_on_board_message(self, temp_workspace):
        """Board message → immediate revoke from autonomous"""
        manager, mode_file, last_board_msg = temp_workspace

        # Force into autonomous
        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_autonomous()

        state = manager._read_mode()
        assert state["mode"] == "autonomous"
        entered_at = state["entered_at"]

        # Simulate Board message (newer timestamp)
        time.sleep(0.1)
        now = time.time()
        last_board_msg.write_text(str(now))

        # Tick should revoke
        with patch("ceo_mode_manager.emit_cieu"):
            state = manager.tick()

        assert state["mode"] == "standard"

    def test_autonomous_no_auto_revoke_without_board(self, temp_workspace):
        """Autonomous persists indefinitely without Board message"""
        manager, mode_file, last_board_msg = temp_workspace

        # Enter autonomous
        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_autonomous()

        # Multiple ticks without Board message (mock all trigger checks to prevent break_glass)
        for _ in range(5):
            with patch.object(manager, "evaluate_triggers", return_value=(None, {})):
                with patch("ceo_mode_manager.emit_cieu"):
                    state = manager.tick()
            time.sleep(0.01)

        # Should still be autonomous
        assert state["mode"] == "autonomous"


class TestBreakGlassMode:
    """Test break-glass mode triggers and revocation"""

    def test_enter_break_glass_on_trigger_t3(self, temp_workspace):
        """T3: must_dispatch denied ≥3 times → break_glass"""
        manager, mode_file, last_board_msg = temp_workspace

        # Mock T3 trigger (must_dispatch denials)
        with patch.object(manager, "_check_must_dispatch_denials", return_value=3):
            with patch("ceo_mode_manager.emit_cieu"):
                state = manager.tick()

        assert state["mode"] == "break_glass"
        assert state["trigger"] == "T3"
        assert state["expires_at"] is not None  # has hard cap

    def test_break_glass_idle_revoke_5min(self, temp_workspace):
        """Break-glass idle ≥5min → revoke"""
        manager, mode_file, last_board_msg = temp_workspace

        # Enter break-glass
        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_break_glass("T1", {"reason": "test"})

        state = manager._read_mode()
        assert state["mode"] == "break_glass"

        # Simulate 5min+ idle by backdating last_activity
        state["last_activity"] = time.time() - (BREAK_GLASS_IDLE_TIMEOUT + 10)
        manager._atomic_write(state)

        # Tick should revoke (mock triggers cleared so it doesn't re-enter)
        with patch.object(manager, "evaluate_triggers", return_value=(None, {})):
            with patch("ceo_mode_manager.emit_cieu"):
                new_state = manager.tick()

        assert new_state["mode"] == "standard"

    def test_break_glass_hard_cap_20min(self, temp_workspace):
        """Break-glass ≥20min total → hard revoke"""
        manager, mode_file, last_board_msg = temp_workspace

        # Enter break-glass with backdated entered_at
        now = time.time()
        old_entered = now - (BREAK_GLASS_HARD_CAP + 10)

        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_break_glass("T1", {"reason": "test"})

        state = manager._read_mode()
        state["entered_at"] = old_entered
        manager._atomic_write(state)

        # Tick should revoke due to hard cap
        with patch("ceo_mode_manager.emit_cieu"):
            new_state = manager.tick()

        assert new_state["mode"] == "standard"

    def test_break_glass_revoke_when_triggers_cleared(self, temp_workspace):
        """Break-glass auto-revoke when all triggers cleared"""
        manager, mode_file, last_board_msg = temp_workspace

        # Enter break-glass
        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_break_glass("T1", {"reason": "test"})

        # Mock all triggers cleared
        with patch.object(manager, "evaluate_triggers", return_value=(None, {})):
            with patch("ceo_mode_manager.emit_cieu"):
                state = manager.tick()

        assert state["mode"] == "standard"

    def test_break_glass_activity_resets_idle_timer(self, temp_workspace):
        """Break-glass activity updates last_activity (sliding window)"""
        manager, mode_file, last_board_msg = temp_workspace

        # Enter break-glass
        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_break_glass("T1", {"reason": "test"})

        initial_state = manager._read_mode()
        initial_activity = initial_state["last_activity"]

        # Wait and tick (simulates activity)
        time.sleep(0.1)
        with patch.object(manager, "evaluate_triggers", return_value=("T1", {"reason": "test"})):
            with patch("ceo_mode_manager.emit_cieu"):
                manager.tick()

        new_state = manager._read_mode()
        assert new_state["last_activity"] > initial_activity
        assert new_state["mode"] == "break_glass"  # still active


class TestModeTransitions:
    """Test mode transition edge cases"""

    def test_board_message_revokes_both_modes(self, temp_workspace):
        """Board message revokes both autonomous and break_glass"""
        manager, mode_file, last_board_msg = temp_workspace

        for mode_name, enter_fn in [
            ("autonomous", lambda: manager.enter_autonomous()),
            ("break_glass", lambda: manager.enter_break_glass("T1", {"test": True}))
        ]:
            # Enter mode
            with patch("ceo_mode_manager.emit_cieu"):
                enter_fn()

            state = manager._read_mode()
            assert state["mode"] == mode_name

            # Simulate Board message
            time.sleep(0.1)
            last_board_msg.write_text(str(time.time()))

            # Tick should revoke
            with patch("ceo_mode_manager.emit_cieu"):
                new_state = manager.tick()

            assert new_state["mode"] == "standard"

    def test_manual_revoke_from_any_mode(self, temp_workspace):
        """Manual revoke works from any mode"""
        manager, mode_file, last_board_msg = temp_workspace

        for mode_name, enter_fn in [
            ("autonomous", lambda: manager.enter_autonomous()),
            ("break_glass", lambda: manager.enter_break_glass("T2", {"test": True}))
        ]:
            with patch("ceo_mode_manager.emit_cieu"):
                enter_fn()

            with patch("ceo_mode_manager.emit_cieu"):
                manager.revoke("manual_test")

            state = manager._read_mode()
            assert state["mode"] == "standard"

    def test_status_includes_timing_info(self, temp_workspace):
        """Status returns human-readable timing"""
        manager, mode_file, last_board_msg = temp_workspace

        # Enter autonomous
        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_autonomous()

        time.sleep(0.2)

        status = manager.status()

        assert "elapsed_seconds" in status
        assert "elapsed_human" in status
        assert status["elapsed_seconds"] >= 0
        assert status["mode"] == "autonomous"


class TestTriggerDetection:
    """Test break-glass trigger detection"""

    def test_trigger_t1_health_degraded(self, temp_workspace):
        """T1: gov_doctor health=degraded"""
        manager, mode_file, last_board_msg = temp_workspace

        with patch.object(manager, "_check_health_degraded", return_value=True):
            trigger_id, evidence = manager.evaluate_triggers()

        assert trigger_id == "T1"
        assert "degraded" in evidence["reason"]

    def test_trigger_t2_circuit_breaker(self, temp_workspace):
        """T2: circuit breaker ARMED"""
        manager, mode_file, last_board_msg = temp_workspace

        with patch.object(manager, "_check_circuit_breaker_armed", return_value=True):
            trigger_id, evidence = manager.evaluate_triggers()

        assert trigger_id == "T2"
        assert "ARMED" in evidence["reason"]

    def test_trigger_t3_must_dispatch_denials(self, temp_workspace):
        """T3: must_dispatch denied ≥3 times"""
        manager, mode_file, last_board_msg = temp_workspace

        with patch.object(manager, "_check_must_dispatch_denials", return_value=5):
            trigger_id, evidence = manager.evaluate_triggers()

        assert trigger_id == "T3"
        assert "5 times" in evidence["reason"]

    def test_trigger_t4_cto_missing(self, temp_workspace):
        """T4: CTO sub-agent not found"""
        manager, mode_file, last_board_msg = temp_workspace

        with patch.object(manager, "_check_cto_subagent_exists", return_value=False):
            trigger_id, evidence = manager.evaluate_triggers()

        assert trigger_id == "T4"
        assert "not found" in evidence["reason"]

    def test_trigger_t5_processes_down(self, temp_workspace):
        """T5: gov-mcp or hook daemon not running"""
        manager, mode_file, last_board_msg = temp_workspace

        with patch.object(manager, "_check_processes_running", return_value=False):
            trigger_id, evidence = manager.evaluate_triggers()

        assert trigger_id == "T5"
        assert "not running" in evidence["reason"]

    def test_no_trigger_when_all_clear(self, temp_workspace):
        """No trigger when all checks pass"""
        manager, mode_file, last_board_msg = temp_workspace

        # Mock all checks returning healthy state
        with patch.object(manager, "_check_health_degraded", return_value=False):
            with patch.object(manager, "_check_circuit_breaker_armed", return_value=False):
                with patch.object(manager, "_check_must_dispatch_denials", return_value=0):
                    with patch.object(manager, "_check_cto_subagent_exists", return_value=True):
                        with patch.object(manager, "_check_processes_running", return_value=True):
                            trigger_id, evidence = manager.evaluate_triggers()

        assert trigger_id is None
        assert evidence == {}


class TestCIEURecording:
    """Test CIEU event emission"""

    def test_autonomous_enter_emits_cieu(self, temp_workspace):
        """Autonomous mode entry emits CIEU transition event"""
        manager, mode_file, last_board_msg = temp_workspace

        with patch("ceo_mode_manager.emit_cieu") as mock_emit:
            manager.enter_autonomous()

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[1]
        assert call_args["to_mode"] == "autonomous"
        assert call_args["from_mode"] == "standard"

    def test_break_glass_enter_emits_claim(self, temp_workspace):
        """Break-glass entry emits BREAK_GLASS_CLAIM"""
        manager, mode_file, last_board_msg = temp_workspace

        with patch("ceo_mode_manager.emit_cieu") as mock_emit:
            manager.enter_break_glass("T1", {"reason": "test"})

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "BREAK_GLASS_CLAIM"

    def test_break_glass_revoke_emits_release(self, temp_workspace):
        """Break-glass revoke emits BREAK_GLASS_RELEASE"""
        manager, mode_file, last_board_msg = temp_workspace

        # Enter and revoke
        with patch("ceo_mode_manager.emit_cieu"):
            manager.enter_break_glass("T1", {"reason": "test"})

        with patch("ceo_mode_manager.emit_cieu") as mock_emit:
            manager.revoke("test_reason")

        # Should emit BREAK_GLASS_RELEASE and transition
        calls = [call[0][0] for call in mock_emit.call_args_list]
        assert "BREAK_GLASS_RELEASE" in calls


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

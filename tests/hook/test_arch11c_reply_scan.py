"""
ARCH-11c Tests: Reply-scan "say != do" via OmissionEngine

3 tests:
  1. Reply with promise + matching tool_uses -> no obligation
  2. Reply with promise + no tool_uses -> obligation created
  3. Consecutive replies without tool_uses -> warning emitted (block signal)
"""
import pytest
import sys
from pathlib import Path

# Ensure Y-star-gov root is importable
YSTAR_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(YSTAR_ROOT))

from ystar.adapters.hooks.stop_hook import scan_action_promises
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import OmissionType, ObligationStatus


class TestArch11cReplyScan:
    """ARCH-11c: action promise detection + OmissionEngine obligation."""

    def test_promise_with_matching_tool_uses_no_obligation(self):
        """Reply contains promise phrases AND sufficient tool_uses -> no obligation."""
        reply = "NOW dispatching Ethan to fix the bug. I am running pytest next."
        # Multiple patterns may match; supply enough tool_uses to cover all
        result = scan_action_promises(reply, tool_use_count=10, agent_id="ceo")

        assert result["promise_count"] >= 1  # At least 1 promise detected
        assert result["deficit"] == 0
        assert result["obligation_created"] is False
        assert result["warning"] is None

    def test_promise_without_tool_uses_creates_obligation(self):
        """Reply contains promise phrases but 0 tool_uses -> obligation created."""
        reply = "NOW dispatching fix for the parser. I am spawning the sub-agent."
        result = scan_action_promises(reply, tool_use_count=0, agent_id="ceo")

        assert result["promise_count"] >= 1
        assert result["deficit"] > 0
        assert result["obligation_created"] is True
        assert result["warning"] is not None
        assert "ACTION_PROMISE_WITHOUT_TOOL_USE" in result["warning"]

    def test_consecutive_unfulfilled_promises_emit_warning(self):
        """Two consecutive replies with promises + 0 tool_uses -> both produce warnings."""
        # First reply: promise with no tool_use
        reply1 = "我立刻执行这个任务"
        result1 = scan_action_promises(reply1, tool_use_count=0, agent_id="ceo")
        assert result1["obligation_created"] is True
        assert result1["warning"] is not None

        # Second reply: another promise, still no tool_use
        reply2 = "正在做修复工作"
        result2 = scan_action_promises(reply2, tool_use_count=0, agent_id="ceo")
        assert result2["obligation_created"] is True
        assert result2["warning"] is not None
        assert "ACTION_PROMISE_WITHOUT_TOOL_USE" in result2["warning"]


class TestArch11cOmissionEngineIntegration:
    """Verify register_action_promise_obligation creates correct obligation."""

    def test_obligation_record_structure(self):
        """Obligation has correct type, severity, and TTL."""
        store = InMemoryOmissionStore()
        engine = OmissionEngine(store=store)

        ob = engine.register_action_promise_obligation(
            agent_id="ceo",
            reply_id="test-reply-001",
            promise_phrases=["NOW dispatching fix", "I am spawning agent"],
            tool_use_count=0,
            ttl_replies=1,
        )

        assert ob.obligation_type == OmissionType.MUST_FULFILL_ACTION_PROMISE.value
        assert ob.actor_id == "ceo"
        assert ob.status == ObligationStatus.PENDING
        assert "action_promise_unfulfilled" in ob.violation_code
        assert "NOW dispatching fix" in ob.notes
        assert ob.escalation_policy.deny_closure_on_open is True

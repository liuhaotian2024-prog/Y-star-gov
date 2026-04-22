"""Verify that handle_hook_event wires register_next_action_rule into the default registry."""

from ystar.governance.router_registry import get_default_registry


def test_handle_hook_event_registers_next_action_rule():
    """After handle_hook_event runs, builtin.next_action_inject must be in the registry."""
    registry = get_default_registry()
    original_rules = dict(registry._rules)

    try:
        # Remove the rule if already present so we can verify re-registration
        registry._rules.pop("builtin.next_action_inject", None)

        from ystar.adapters.hook import handle_hook_event

        # Payload mimics a minimal PreToolUse event
        handle_hook_event({"hook_type": "PreToolUse", "tool_name": "__test_noop__", "tool_input": {}})

        assert "builtin.next_action_inject" in registry._rules, (
            f"Expected builtin.next_action_inject in registry, got: {list(registry._rules.keys())}"
        )
    finally:
        registry._rules = original_rules

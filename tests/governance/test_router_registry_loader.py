"""
Tests for CZL-ARCH-4: RouterRegistry.load_rules_dir, unregister_all, IngressRequest

Coverage:
  1. load_rules_dir loads .py files from a temp directory
  2. unregister_all clears the registry
  3. IngressRequest.from_claude_code normalizes payload
  4. IngressRequest.from_mcp normalizes MCP call
  5. IngressRequest.from_cli normalizes CLI args
"""
from __future__ import annotations

import os
import textwrap

import pytest

from ystar.governance.router_registry import (
    IngressRequest,
    RouterRegistry,
    RouterRule,
    RouterResult,
)


# ── Test 1: load_rules_dir loads .py files from temp dir ───────────────────

class TestLoadRulesDir:
    def test_loads_rules_from_directory(self, tmp_path):
        """Rules files with RULES list are imported and registered."""
        rule_file = tmp_path / "my_rules.py"
        rule_file.write_text(textwrap.dedent("""\
            from ystar.governance.router_registry import RouterRule, RouterResult

            RULES = [
                RouterRule(
                    rule_id="loaded_rule_1",
                    detector=lambda p: True,
                    executor=lambda p: RouterResult(decision="allow"),
                    priority=50,
                ),
                RouterRule(
                    rule_id="loaded_rule_2",
                    detector=lambda p: False,
                    executor=lambda p: RouterResult(decision="deny"),
                    priority=10,
                ),
            ]
        """))

        reg = RouterRegistry()
        count = reg.load_rules_dir(str(tmp_path))

        assert count == 2
        assert reg.rule_count == 2
        assert reg.get_rule("loaded_rule_1") is not None
        assert reg.get_rule("loaded_rule_2") is not None

    def test_skips_underscore_prefixed_files(self, tmp_path):
        """Files starting with _ are ignored."""
        (tmp_path / "_private.py").write_text(
            "from ystar.governance.router_registry import RouterRule, RouterResult\n"
            "RULES = [RouterRule(rule_id='hidden', detector=lambda p: True, "
            "executor=lambda p: RouterResult())]\n"
        )
        reg = RouterRegistry()
        count = reg.load_rules_dir(str(tmp_path))
        assert count == 0
        assert reg.rule_count == 0

    def test_nonexistent_dir_returns_zero(self):
        """Non-existent directory returns 0 without raising."""
        reg = RouterRegistry()
        count = reg.load_rules_dir("/tmp/nonexistent_dir_abc123")
        assert count == 0

    def test_idempotent_on_duplicate_rule_ids(self, tmp_path):
        """Second load of same file silently skips already-registered IDs."""
        rule_file = tmp_path / "dup.py"
        rule_file.write_text(textwrap.dedent("""\
            from ystar.governance.router_registry import RouterRule, RouterResult
            RULES = [
                RouterRule(rule_id="idem", detector=lambda p: True,
                           executor=lambda p: RouterResult()),
            ]
        """))
        reg = RouterRegistry()
        assert reg.load_rules_dir(str(tmp_path)) == 1
        # Second call: rule already exists, silently skipped
        assert reg.load_rules_dir(str(tmp_path)) == 0
        assert reg.rule_count == 1


# ── Test 2: unregister_all clears the registry ────────────────────────────

class TestUnregisterAll:
    def test_clears_all_rules(self):
        reg = RouterRegistry()
        for i in range(5):
            reg.register_rule(RouterRule(
                rule_id=f"rule_{i}",
                detector=lambda p: True,
                executor=lambda p: RouterResult(),
            ))
        assert reg.rule_count == 5

        removed = reg.unregister_all()
        assert removed == 5
        assert reg.rule_count == 0
        assert reg.all_rules() == []

    def test_empty_registry_returns_zero(self):
        reg = RouterRegistry()
        assert reg.unregister_all() == 0

    def test_resets_execution_depth(self):
        reg = RouterRegistry()
        reg._execution_depth = 3
        reg.unregister_all()
        assert reg._execution_depth == 0


# ── Test 3: IngressRequest.from_claude_code ────────────────────────────────

class TestIngressFromClaudeCode:
    def test_standard_payload(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "agent_id": "ceo",
            "session_id": "sess-001",
        }
        req = IngressRequest.from_claude_code(payload)
        assert req.tool_name == "Bash"
        assert req.tool_input == {"command": "ls -la"}
        assert req.agent_id == "ceo"
        assert req.session_id == "sess-001"
        assert req.source == "claude_code"

    def test_camel_case_keys(self):
        """Claude Code sometimes sends camelCase keys."""
        payload = {
            "toolName": "Write",
            "input": {"file_path": "/tmp/x.py", "content": "pass"},
            "agentId": "eng-kernel",
            "sessionId": "sess-002",
        }
        req = IngressRequest.from_claude_code(payload)
        assert req.tool_name == "Write"
        assert req.tool_input["file_path"] == "/tmp/x.py"
        assert req.agent_id == "eng-kernel"
        assert req.session_id == "sess-002"

    def test_to_payload_roundtrip(self):
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/a.py"},
            "agent_id": "cto",
            "session_id": "s3",
        }
        req = IngressRequest.from_claude_code(payload)
        out = req.to_payload()
        assert out["tool_name"] == "Read"
        assert out["source"] == "claude_code"


# ── Test 4: IngressRequest.from_mcp ───────────────────────────────────────

class TestIngressFromMCP:
    def test_standard_mcp_call(self):
        mcp_call = {
            "method": "enforce",
            "params": {
                "arguments": {"scope": "governance/"},
                "_meta": {
                    "agent_id": "eng-governance",
                    "session_id": "mcp-sess-1",
                },
            },
        }
        req = IngressRequest.from_mcp(mcp_call)
        assert req.tool_name == "enforce"
        assert req.tool_input == {"scope": "governance/"}
        assert req.agent_id == "eng-governance"
        assert req.session_id == "mcp-sess-1"
        assert req.source == "mcp"

    def test_params_name_fallback(self):
        """When method is missing, fall back to params.name."""
        mcp_call = {
            "params": {
                "name": "check_hook",
                "input": {"event": "PreToolUse"},
            },
        }
        req = IngressRequest.from_mcp(mcp_call)
        assert req.tool_name == "check_hook"
        assert req.tool_input == {"event": "PreToolUse"}


# ── Test 5: IngressRequest.from_cli ───────────────────────────────────────

class TestIngressFromCLI:
    def test_standard_cli_args(self):
        args = {
            "command": "doctor",
            "args": {"verbose": True},
            "agent_id": "ceo",
            "session_id": "cli-1",
        }
        req = IngressRequest.from_cli(args)
        assert req.tool_name == "doctor"
        assert req.tool_input == {"verbose": True}
        assert req.agent_id == "ceo"
        assert req.session_id == "cli-1"
        assert req.source == "cli"

    def test_tool_key_fallback(self):
        """CLI may use 'tool' instead of 'command'."""
        args = {
            "tool": "hook-install",
            "input": {"path": "/usr/local"},
            "agent": "eng-platform",
            "session": "cli-2",
        }
        req = IngressRequest.from_cli(args)
        assert req.tool_name == "hook-install"
        assert req.tool_input == {"path": "/usr/local"}
        assert req.agent_id == "eng-platform"
        assert req.session_id == "cli-2"

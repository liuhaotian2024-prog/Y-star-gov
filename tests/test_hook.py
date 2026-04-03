"""
tests/test_hook.py — 使用正确 API 验证 check_hook 的两条路径
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from ystar.kernel.dimensions import IntentContract
from ystar.session import Policy
from ystar.adapters.hook import check_hook, _extract_params, _feed_path_b


def make_policy() -> Policy:
    ic = IntentContract(
        deny=["/etc", "/production"],
        deny_commands=["rm -rf", "sudo"],
    )
    return Policy({"test_agent": ic})


def make_payload(tool_name="Read", path="/workspace/file.py",
                 agent_id="test_agent", session_id="sess_001"):
    return {
        "tool_name": tool_name,
        "tool_input": {"path": path},
        "agent_id": agent_id,
        "session_id": session_id,
    }


class TestHookLightPath:

    def test_allow_safe_path(self):
        policy = make_policy()
        payload = make_payload(path="/workspace/safe.py")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result == {}

    def test_deny_forbidden_path(self):
        policy = make_policy()
        payload = make_payload(path="/etc/passwd")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result.get("action") == "block"
        assert "[Y*]" in result.get("message", "")

    def test_deny_forbidden_command(self):
        policy = make_policy()
        payload = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /important"},
                   "agent_id": "test_agent", "session_id": "s"}
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result.get("action") == "block"

    def test_unknown_agent_no_crash(self):
        policy = make_policy()
        payload = make_payload(agent_id="unknown_agent_xyz")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy)
        assert isinstance(result, dict)

    def test_empty_payload_no_crash(self):
        policy = make_policy()
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook({}, policy)
        assert isinstance(result, dict)

    def test_allow_write_workspace(self):
        policy = make_policy()
        payload = make_payload(tool_name="Write", path="/workspace/output.txt")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result == {}


class TestExtractParams:

    def test_read_extracts_file_path(self):
        p = _extract_params("Read", {"path": "/workspace/test.py"})
        assert p["file_path"] == "/workspace/test.py"

    def test_bash_extracts_command(self):
        p = _extract_params("Bash", {"command": "ls -la"})
        assert p["command"] == "ls -la"

    def test_webfetch_extracts_url(self):
        p = _extract_params("WebFetch", {"url": "https://api.example.com"})
        assert p["url"] == "https://api.example.com"

    def test_glob_uses_pattern(self):
        p = _extract_params("Glob", {"pattern": "**/*.py"})
        assert p["file_path"] == "**/*.py"

    def test_unknown_tool_no_crash(self):
        p = _extract_params("UnknownTool", {"foo": "bar"})
        assert p["action"] == "UnknownTool"

    def test_mcp_tool_path_extraction(self):
        p = _extract_params("mcp__fs__read", {"file_path": "/workspace/x"})
        assert "file_path" in p

    def test_tool_name_preserved(self):
        p = _extract_params("MultiEdit", {"path": "/workspace/x.py"})
        assert p["tool_name"] == "MultiEdit"


class TestHookResponse:

    def test_allow_returns_empty_dict(self):
        policy = make_policy()
        payload = make_payload(path="/workspace/ok.py")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result == {}

    def test_deny_returns_block_with_message(self):
        policy = make_policy()
        payload = make_payload(path="/etc/passwd")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result.get("action") == "block"
        assert "[Y*]" in result.get("message", "")

    def test_deny_includes_violations_list(self):
        policy = make_policy()
        payload = make_payload(path="/etc/passwd")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert isinstance(result.get("violations", []), list)
        assert len(result.get("violations", [])) >= 1


class TestHookFullPath:

    def test_full_path_allow(self, tmp_path):
        policy = make_policy()
        cfg = {"session_id": "s001", "cieu_db": str(tmp_path / "c.db"),
               "contract": {"deny": ["/etc"]}}
        payload = make_payload(path="/workspace/ok.py")
        with patch("ystar.adapters.hook._load_session_config", return_value=cfg):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert isinstance(result, dict)

    def test_full_path_falls_back_gracefully(self, tmp_path):
        policy = make_policy()
        cfg = {"session_id": "x", "cieu_db": "/nonexistent/path.db"}
        payload = make_payload(path="/workspace/ok.py")
        with patch("ystar.adapters.hook._load_session_config", return_value=cfg):
            with patch("ystar.adapters.hook._check_hook_full",
                       side_effect=RuntimeError("boom")):
                result = check_hook(payload, policy, agent_id="test_agent")
        assert isinstance(result, dict)

    def test_production_deny(self, tmp_path):
        policy = make_policy()
        cfg = {"session_id": "s", "cieu_db": str(tmp_path / "c.db"),
               "contract": {"deny": ["/etc", "/production"]}}
        payload = make_payload(path="/production/config.yaml")
        with patch("ystar.adapters.hook._load_session_config", return_value=cfg):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result.get("action") == "block"


class TestFeedPathB:
    """Verify _feed_path_b is fail-safe and feeds observations correctly."""

    def test_feed_path_b_no_orchestrator_no_crash(self):
        """_feed_path_b must not crash when orchestrator has no _path_b_agent."""
        # Should silently return without error
        _feed_path_b("agent1", "Read", {"file_path": "/x"}, {}, "sess1")

    def test_feed_path_b_with_block_result(self):
        """_feed_path_b should include violations when result is a block."""
        block_result = {"action": "block", "message": "denied"}
        # Should not crash regardless of orchestrator state
        _feed_path_b("agent1", "Write", {"file_path": "/x"}, block_result, "sess1")

    def test_feed_path_b_none_session(self):
        """_feed_path_b handles None session_id gracefully."""
        _feed_path_b("agent1", "Bash", {"command": "ls"}, {}, None)


class TestRuntimeContractMerge:
    """Verify that runtime contracts are merged into hook checks."""

    def test_runtime_deny_tightens_policy(self, tmp_path):
        """A runtime_deny file should add deny rules on top of session policy."""
        # Write a deny file with additional constraints
        deny_file = tmp_path / ".ystar_runtime_deny.json"
        deny_file.write_text(json.dumps({
            "deny": ["/etc", "/production", "/staging"],
            "deny_commands": ["rm -rf", "sudo", "curl"],
        }))

        policy = make_policy()
        payload = make_payload(tool_name="Bash",
                               path="/workspace/ok.py")
        payload["tool_input"] = {"command": "curl http://example.com"}

        with patch("ystar.adapters.hook._load_session_config", return_value=None), \
             patch("os.getcwd", return_value=str(tmp_path)):
            result = check_hook(payload, policy, agent_id="test_agent")
        # curl should be denied because runtime_deny adds it
        assert result.get("action") == "block"

    def test_no_runtime_files_unchanged(self, tmp_path):
        """Without runtime files, behavior should be unchanged."""
        policy = make_policy()
        payload = make_payload(path="/workspace/safe.py")
        with patch("ystar.adapters.hook._load_session_config", return_value=None), \
             patch("os.getcwd", return_value=str(tmp_path)):
            result = check_hook(payload, policy, agent_id="test_agent")
        assert result == {}

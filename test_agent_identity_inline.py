#!/usr/bin/env python3
"""
Inline test: Agent tool → .ystar_active_agent auto-set.

CIEU 5-tuple:
Y* = Agent spawn 自动把 .ystar_active_agent 写为 subagent_type
Xt = 之前 hook 不设，sub-agent 继承父 CEO 导致 hook deny
U = hook.py _extract_params Agent 分支提取 subagent_type → 写文件 + emit CIEU
Yt+1 = 下次 Sofia-CMO spawn 不再 hook deny content/
Rt+1=0 = test pass + verify file content
"""
import os
import sys
import tempfile

# Add ystar to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from ystar.adapters.hook import _extract_params

def test_agent_identity_set():
    """Test Agent tool sets .ystar_active_agent from subagent_type."""
    orig_cwd = os.getcwd()

    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Mock Agent tool payload
        tool_name = "Agent"
        tool_input = {
            "subagent_type": "ystar-cmo",
            "agent_definition": "...",
        }

        # Call _extract_params
        params = _extract_params(tool_name, tool_input)

        # Verify .ystar_active_agent was written
        active_agent_path = os.path.join(tmpdir, ".ystar_active_agent")
        assert os.path.exists(active_agent_path), f"Expected {active_agent_path} to exist"

        with open(active_agent_path) as f:
            content = f.read().strip()

        assert content == "ystar-cmo", f"Expected 'ystar-cmo', got '{content}'"

        print(f"[PASS] Agent tool → .ystar_active_agent = ystar-cmo")

        # Verify params passthrough
        assert params["tool_name"] == "Agent"
        assert params["subagent_type"] == "ystar-cmo"

        print("[PASS] params passthrough OK")

    os.chdir(orig_cwd)

if __name__ == "__main__":
    test_agent_identity_set()
    print("\n✓ All inline tests passed")

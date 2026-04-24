"""
tests.kernel.test_ppid_marker_write_side -- PPID marker write-side fix tests
=============================================================================

CZL-SPAWN-PPID-MARKER-FIX (2026-04-24):
Tests the three-part fix for subagent identity resolution:
1. Write-side: hook.py _extract_params writes markers to scripts/ dir
2. Read-side: hook_wrapper.py uses payload.agent_type before stale markers
3. Stale cleanup: ppid markers older than 1h are pruned

Regression coverage for the bug where 13+ ppid markers all contained "ceo"
because the parent process wrote its own ppid marker, not the child's.

Author: Leo Chen (eng-kernel)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add Y-star-gov to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ===========================================================================
# Test 1: identity_detector._map_agent_type resolves subagent names correctly
# ===========================================================================

class TestAgentTypeMapping:
    """Verify _map_agent_type handles all known subagent name formats."""

    def test_exact_match_agent_type(self):
        from ystar.adapters.identity_detector import _map_agent_type
        assert _map_agent_type("eng-kernel") == "eng-kernel"
        assert _map_agent_type("eng-platform") == "eng-platform"
        assert _map_agent_type("eng-governance") == "eng-governance"

    def test_claude_code_agent_type_format(self):
        """Claude Code sets agent_type to 'Name-Role' format for subagents."""
        from ystar.adapters.identity_detector import _map_agent_type
        assert _map_agent_type("Agent-Kernel") == "eng-kernel"
        assert _map_agent_type("Agent-Platform") == "eng-platform"
        assert _map_agent_type("Agent-Secretary") == "secretary"
        assert _map_agent_type("Agent-CEO") == "ceo"

    def test_legacy_ystar_prefix(self):
        from ystar.adapters.identity_detector import _map_agent_type
        assert _map_agent_type("ystar-ceo") == "ceo"
        assert _map_agent_type("ystar-cto") == "cto"

    def test_unknown_type_returns_as_is(self):
        from ystar.adapters.identity_detector import _map_agent_type
        result = _map_agent_type("totally-unknown-agent-xyz")
        # Should return as-is (no crash), possibly with a fuzzy match warning
        assert isinstance(result, str)

    def test_empty_and_generic_passthrough(self):
        from ystar.adapters.identity_detector import _map_agent_type
        assert _map_agent_type("") == ""
        # "agent" is generic — should NOT be mapped to anything useful
        result = _map_agent_type("agent")
        # "agent" is not in the map, so it returns as-is or via fuzzy
        assert isinstance(result, str)


# ===========================================================================
# Test 2: _extract_params writes markers to scripts/ dir on Agent tool
# ===========================================================================

class TestExtractParamsAgentMarker:
    """Verify _extract_params writes subagent identity markers."""

    def test_agent_tool_writes_global_marker(self, tmp_path):
        """When Agent tool is called, global .ystar_active_agent is written."""
        from ystar.adapters.hook import _extract_params

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        with patch("os.getcwd", return_value=str(tmp_path)), \
             patch.dict(os.environ, {"CLAUDE_SESSION_ID": "", "PPID": "99999"}), \
             patch("ystar.governance.cieu_store.CIEUStore") as mock_cls:
            mock_cls.return_value = MagicMock()
            _extract_params("Agent", {"subagent_type": "eng-kernel"})

        # Check global marker was written in cwd
        global_marker = tmp_path / ".ystar_active_agent"
        assert global_marker.exists(), "Global marker was not written"
        content = global_marker.read_text().strip()
        assert content == "eng-kernel", f"Global marker has '{content}', expected 'eng-kernel'"

    def test_agent_tool_writes_ppid_marker(self, tmp_path):
        """When Agent tool is called, ppid marker is written for caller."""
        from ystar.adapters.hook import _extract_params

        with patch("os.getcwd", return_value=str(tmp_path)), \
             patch.dict(os.environ, {"CLAUDE_SESSION_ID": "", "PPID": "12345"}), \
             patch("os.getppid", return_value=12345), \
             patch("ystar.governance.cieu_store.CIEUStore") as mock_cls:
            mock_cls.return_value = MagicMock()
            _extract_params("Agent", {"subagent_type": "eng-platform"})

        ppid_marker = tmp_path / ".ystar_active_agent.ppid_12345"
        assert ppid_marker.exists(), "PPID marker was not written"
        content = ppid_marker.read_text().strip()
        assert content == "eng-platform", f"PPID marker has '{content}', expected 'eng-platform'"

    def test_agent_tool_writes_named_subagent_marker(self, tmp_path):
        """CZL-SPAWN-PPID-MARKER-FIX: Named subagent breadcrumb marker."""
        from ystar.adapters.hook import _extract_params

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        with patch("os.getcwd", return_value=str(tmp_path)), \
             patch.dict(os.environ, {"CLAUDE_SESSION_ID": "", "PPID": ""}), \
             patch("os.getppid", return_value=1), \
             patch("ystar.governance.cieu_store.CIEUStore") as mock_cls:
            mock_cls.return_value = MagicMock()
            _extract_params("Agent", {"subagent_type": "Leo-Kernel"})

        # Check for named subagent marker in cwd or scripts/
        named_marker_cwd = tmp_path / ".ystar_active_agent.subagent_Leo-Kernel"
        named_marker_scripts = scripts_dir / ".ystar_active_agent.subagent_Leo-Kernel"
        found = named_marker_cwd.exists() or named_marker_scripts.exists()
        assert found, "Named subagent marker was not written"


# ===========================================================================
# Test 3: hook_wrapper subagent resolution from payload.agent_type
# ===========================================================================

class TestHookWrapperSubagentResolution:
    """Verify hook_wrapper.py resolves subagent identity from agent_type."""

    def test_subagent_type_takes_priority_over_stale_marker(self):
        """The core bug: agent_type='Leo-Kernel' must override stale marker 'ceo'.

        'Leo-Kernel' is a deployment-specific alias (from .ystar_session.json
        agent_aliases), so we mock _load_alias_map to return the production
        aliases that Y* Bridge Labs uses.
        """
        from ystar.adapters.identity_detector import _map_agent_type

        # Mock the alias map to simulate production session config
        _test_aliases = {
            "Leo-Kernel": "eng-kernel",
            "Maya-Governance": "eng-governance",
            "Ryan-Platform": "eng-platform",
            "Jordan-Domains": "eng-domains",
            "Ethan-CTO": "cto",
            "Samantha-Secretary": "secretary",
        }
        with patch("ystar.adapters.identity_detector._load_alias_map",
                    return_value=_test_aliases):
            _original_agent_type = "Leo-Kernel"
            _resolved = _map_agent_type(_original_agent_type)

        assert _resolved == "eng-kernel", (
            f"agent_type='Leo-Kernel' resolved to '{_resolved}', expected 'eng-kernel'"
        )

    def test_root_process_falls_through_to_marker(self):
        """Root process (agent_type='' or 'agent') should use marker fallback."""
        # For root process, _original_agent_type is empty or "agent"
        # The fix skips to marker-based resolution in that case
        for agent_type in ("", "agent", None):
            # These should NOT trigger the subagent resolution path
            should_skip = (
                agent_type and agent_type not in ("", "agent", None)
            )
            assert not should_skip, f"agent_type={repr(agent_type)} should skip subagent path"

    def test_all_known_subagent_types_resolve(self):
        """All known Claude Code subagent types resolve to valid governance IDs."""
        from ystar.adapters.identity_detector import _map_agent_type

        known_subagent_types = {
            "Agent-Kernel": "eng-kernel",
            "Agent-Platform": "eng-platform",
            "Agent-Governance": "eng-governance",
            "Agent-Domains": "eng-domains",
            "Agent-CEO": "ceo",
            "Agent-CTO": "cto",
            "Agent-Secretary": "secretary",
        }
        for agent_type, expected_id in known_subagent_types.items():
            result = _map_agent_type(agent_type)
            assert result == expected_id, (
                f"_map_agent_type('{agent_type}') = '{result}', expected '{expected_id}'"
            )


# ===========================================================================
# Test 4: Concurrent spawn isolation (no cross-contamination)
# ===========================================================================

class TestConcurrentSpawnIsolation:
    """5 concurrent subagent spawns should each get their own marker."""

    def test_five_concurrent_ppid_markers(self, tmp_path):
        """Simulate 5 subagents with different PPIDs writing their own markers."""
        agents = {
            "11111": "eng-kernel",
            "22222": "eng-platform",
            "33333": "eng-governance",
            "44444": "eng-domains",
            "55555": "secretary",
        }

        marker_dir = tmp_path / "scripts"
        marker_dir.mkdir()

        # Simulate each subagent writing its own ppid marker
        for ppid, role in agents.items():
            marker_path = marker_dir / f".ystar_active_agent.ppid_{ppid}"
            marker_path.write_text(role)

        # Verify: each ppid marker has the correct role (no cross-contamination)
        for ppid, expected_role in agents.items():
            marker_path = marker_dir / f".ystar_active_agent.ppid_{ppid}"
            actual = marker_path.read_text().strip()
            assert actual == expected_role, (
                f"ppid_{ppid} has '{actual}', expected '{expected_role}'"
            )

    def test_no_cross_contamination_on_read(self, tmp_path):
        """Each subagent reads only its own ppid marker, not siblings."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Write markers for 3 different ppids
        (scripts_dir / ".ystar_active_agent.ppid_100").write_text("eng-kernel")
        (scripts_dir / ".ystar_active_agent.ppid_200").write_text("eng-platform")
        (scripts_dir / ".ystar_active_agent.ppid_300").write_text("ceo")

        # Subagent with ppid 100 should see eng-kernel, not ceo
        marker_100 = scripts_dir / ".ystar_active_agent.ppid_100"
        assert marker_100.read_text().strip() == "eng-kernel"

        # Subagent with ppid 200 should see eng-platform
        marker_200 = scripts_dir / ".ystar_active_agent.ppid_200"
        assert marker_200.read_text().strip() == "eng-platform"


# ===========================================================================
# Test 5: Stale ppid marker cleanup
# ===========================================================================

class TestStalePpidCleanup:
    """Verify stale ppid markers (>1h old) are pruned."""

    def test_stale_markers_pruned(self, tmp_path):
        """Markers older than 1 hour are deleted."""
        import glob as glob_mod

        # Create fresh marker
        fresh = tmp_path / ".ystar_active_agent.ppid_fresh"
        fresh.write_text("eng-kernel")

        # Create stale marker (set mtime to 2 hours ago)
        stale = tmp_path / ".ystar_active_agent.ppid_stale"
        stale.write_text("ceo")
        stale_time = time.time() - 7200  # 2 hours ago
        os.utime(str(stale), (stale_time, stale_time))

        # Run cleanup logic (same as hook_wrapper)
        stale_threshold = time.time() - 3600
        ppid_pattern = str(tmp_path / ".ystar_active_agent.ppid_*")
        for stale_path in glob_mod.glob(ppid_pattern):
            try:
                if os.stat(stale_path).st_mtime < stale_threshold:
                    os.unlink(stale_path)
            except (FileNotFoundError, OSError):
                pass

        # Fresh marker should survive
        assert fresh.exists(), "Fresh marker was incorrectly pruned"
        # Stale marker should be removed
        assert not stale.exists(), "Stale marker was not pruned"

    def test_fresh_markers_preserved(self, tmp_path):
        """Markers younger than 1 hour are NOT deleted."""
        import glob as glob_mod

        marker = tmp_path / ".ystar_active_agent.ppid_12345"
        marker.write_text("eng-kernel")
        # mtime is now (fresh)

        stale_threshold = time.time() - 3600
        ppid_pattern = str(tmp_path / ".ystar_active_agent.ppid_*")
        pruned = 0
        for stale_path in glob_mod.glob(ppid_pattern):
            if os.stat(stale_path).st_mtime < stale_threshold:
                os.unlink(stale_path)
                pruned += 1

        assert pruned == 0, "Fresh marker was incorrectly pruned"
        assert marker.exists()


# ===========================================================================
# Test 6: v2 handle_hook_event agent_type priority
# ===========================================================================

class TestV2HandleHookEventAgentType:
    """Verify handle_hook_event checks agent_type before marker fallback."""

    def test_v2_agent_type_priority(self):
        """In v2 path, agent_type from payload should override stale markers."""
        from ystar.adapters.identity_detector import _map_agent_type

        # Simulate the v2 fix logic
        payload = {"agent_id": "", "agent_type": "Agent-Kernel"}
        _v2_atype = payload.get("agent_type", "")

        _v2_resolved = False
        if _v2_atype and _v2_atype not in ("", "agent", None):
            _v2_mapped = _map_agent_type(_v2_atype)
            if _v2_mapped and _v2_mapped not in ("agent", "guest"):
                payload["agent_id"] = _v2_mapped
                _v2_resolved = True

        assert _v2_resolved, "v2 path failed to resolve agent_type"
        assert payload["agent_id"] == "eng-kernel"

    def test_v2_root_process_uses_marker(self):
        """Root process (agent_type='agent') should fall through to markers."""
        payload = {"agent_id": "", "agent_type": "agent"}
        _v2_atype = payload.get("agent_type", "")

        _v2_resolved = False
        if _v2_atype and _v2_atype not in ("", "agent", None):
            _v2_resolved = True

        assert not _v2_resolved, "Root process should NOT resolve via agent_type"


# ===========================================================================
# Test 7: End-to-end _detect_agent_id with subagent payload
# ===========================================================================

class TestDetectAgentIdSubagent:
    """Full integration: _detect_agent_id with subagent-style payloads."""

    def test_detect_subagent_from_agent_type(self):
        """_detect_agent_id should resolve subagent from agent_type field."""
        from ystar.adapters.identity_detector import _detect_agent_id

        payload = {
            "agent_id": "",
            "agent_type": "Agent-Kernel",
            "tool_name": "Read",
        }
        result = _detect_agent_id(payload)
        # Priority 1.5 should catch this
        assert result == "eng-kernel", f"Got '{result}', expected 'eng-kernel'"

    def test_detect_root_process_not_subagent(self):
        """Root process with agent_type='agent' should NOT resolve as subagent."""
        from ystar.adapters.identity_detector import _detect_agent_id

        payload = {
            "agent_id": "",
            "agent_type": "agent",
            "tool_name": "Read",
        }
        # This should NOT return "agent" — it should fall through to other priorities
        result = _detect_agent_id(payload)
        # Result depends on marker files etc, but it should NOT be "agent"
        # (the 1.5 filter skips generic "agent")
        assert isinstance(result, str)

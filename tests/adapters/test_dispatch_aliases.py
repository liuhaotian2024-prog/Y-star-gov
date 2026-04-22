"""
CZL-HOOK-DISPATCH-RESIDUAL: Regression tests for display-name -> canonical
agent alias resolution in must_dispatch_via_cto detector.

Covers:
1. _load_alias_map reads agent_aliases from .ystar_session.json
2. _map_agent_type resolves display names (Leo-Kernel -> eng-kernel)
3. _check_must_dispatch_via_cto blocks CEO -> display-name spawns
4. Canonical eng-* names still blocked (no regression)
"""
import json
import os
from unittest import mock

import pytest

from ystar.adapters.identity_detector import _load_alias_map, _map_agent_type


@pytest.fixture
def session_with_aliases(tmp_path):
    """Create a temp .ystar_session.json with agent_aliases."""
    session = {
        "schema_version": "1.0",
        "agent_aliases": {
            "Leo-Kernel": "eng-kernel",
            "Leo-Chen": "eng-kernel",
            "Maya-Governance": "eng-governance",
            "Maya-Patel": "eng-governance",
            "Ryan-Platform": "eng-platform",
            "Ryan-Park": "eng-platform",
            "Jordan-Domains": "eng-domains",
            "Jordan-Lee": "eng-domains",
            "Ethan-CTO": "cto",
            "Ethan-Wright": "cto",
        },
    }
    path = tmp_path / ".ystar_session.json"
    path.write_text(json.dumps(session), encoding="utf-8")
    return tmp_path


@pytest.fixture
def session_without_aliases(tmp_path):
    """Create a temp .ystar_session.json WITHOUT agent_aliases."""
    session = {"schema_version": "1.0"}
    path = tmp_path / ".ystar_session.json"
    path.write_text(json.dumps(session), encoding="utf-8")
    return tmp_path


def test_load_alias_map_reads_aliases(session_with_aliases):
    """alias map is populated from .ystar_session.json agent_aliases."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        aliases = _load_alias_map()
    assert aliases["Leo-Kernel"] == "eng-kernel"
    assert aliases["Ethan-CTO"] == "cto"
    assert aliases["Maya-Patel"] == "eng-governance"
    assert len(aliases) == 10


def test_load_alias_map_empty_when_no_field(session_without_aliases):
    """alias map returns {} when agent_aliases field missing."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_without_aliases)}):
        aliases = _load_alias_map()
    assert aliases == {}


def test_load_alias_map_empty_when_no_file(tmp_path):
    """alias map returns {} when session file missing entirely."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(tmp_path)}):
        aliases = _load_alias_map()
    assert aliases == {}


def test_map_display_name_leo_kernel(session_with_aliases):
    """Leo-Kernel resolves to eng-kernel."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("Leo-Kernel") == "eng-kernel"


def test_map_display_name_maya_governance(session_with_aliases):
    """Maya-Governance resolves to eng-governance."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("Maya-Governance") == "eng-governance"


def test_map_display_name_ryan_platform(session_with_aliases):
    """Ryan-Platform resolves to eng-platform."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("Ryan-Platform") == "eng-platform"


def test_map_display_name_jordan_domains(session_with_aliases):
    """Jordan-Domains resolves to eng-domains."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("Jordan-Domains") == "eng-domains"


def test_map_display_name_ethan_cto(session_with_aliases):
    """Ethan-CTO resolves to cto."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("Ethan-CTO") == "cto"


def test_map_full_name_leo_chen(session_with_aliases):
    """Leo-Chen (full name variant) resolves to eng-kernel."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("Leo-Chen") == "eng-kernel"


def test_map_canonical_still_works(session_with_aliases):
    """Canonical eng-kernel still resolves directly (no regression)."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("eng-kernel") == "eng-kernel"


def test_map_canonical_ceo_still_works(session_with_aliases):
    """Canonical ceo still resolves via built-in map."""
    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        assert _map_agent_type("ceo") == "ceo"


def test_dispatch_detector_blocks_display_name(session_with_aliases):
    """
    _check_must_dispatch_via_cto builds prefix from alias keys.
    Leo-Kernel starts with Leo- prefix (from alias key Leo-Kernel),
    so it should trigger the DENY path.
    """
    from ystar.adapters.boundary_enforcer import _check_must_dispatch_via_cto

    agent_rules = {"must_dispatch_via_cto": True}
    params = {"subagent_type": "Leo-Kernel", "prompt": "test"}

    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        with mock.patch(
            "ystar.adapters.boundary_enforcer._get_current_mode",
            return_value={"mode": "standard"},
        ):
            result = _check_must_dispatch_via_cto(
                "ceo", "Agent", params, agent_rules
            )

    assert result is not None, "Expected DENY for CEO -> Leo-Kernel"
    assert result.allowed is False
    assert "must dispatch" in result.reason.lower() or "via CTO" in result.reason


def test_dispatch_detector_blocks_canonical(session_with_aliases):
    """eng-kernel canonical name still blocked for CEO dispatch."""
    from ystar.adapters.boundary_enforcer import _check_must_dispatch_via_cto

    agent_rules = {"must_dispatch_via_cto": True}
    params = {"subagent_type": "eng-kernel", "prompt": "test"}

    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        with mock.patch(
            "ystar.adapters.boundary_enforcer._get_current_mode",
            return_value={"mode": "standard"},
        ):
            result = _check_must_dispatch_via_cto(
                "ceo", "Agent", params, agent_rules
            )

    assert result is not None, "Expected DENY for CEO -> eng-kernel"
    assert result.allowed is False


def test_dispatch_detector_allows_cto(session_with_aliases):
    """CTO dispatching to engineer is allowed because CTO's agent_rules
    do NOT have must_dispatch_via_cto enabled (it's CEO-only config)."""
    from ystar.adapters.boundary_enforcer import _check_must_dispatch_via_cto

    # CTO's actual agent_rules: must_dispatch_via_cto is False/absent
    agent_rules = {"must_dispatch_via_cto": False}
    params = {"subagent_type": "eng-kernel", "prompt": "test"}

    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        result = _check_must_dispatch_via_cto(
            "cto", "Agent", params, agent_rules
        )

    assert result is None, "CTO should be allowed to dispatch to engineers"


def test_dispatch_detector_allows_non_agent_tool(session_with_aliases):
    """Non-Agent tool calls should not be blocked by dispatch rule."""
    from ystar.adapters.boundary_enforcer import _check_must_dispatch_via_cto

    agent_rules = {"must_dispatch_via_cto": True}
    params = {"file_path": "test.py"}

    with mock.patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(session_with_aliases)}):
        with mock.patch(
            "ystar.adapters.boundary_enforcer._get_current_mode",
            return_value={"mode": "standard"},
        ):
            result = _check_must_dispatch_via_cto(
                "ceo", "Read", params, agent_rules
            )

    assert result is None, "Non-Agent tools should pass through"

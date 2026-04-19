"""
CZL-ARCH-1 regression tests for identity_detector.py hardening.

Audience: future CEO/CTO sessions auditing Phase 1 closure; test runners in CI.
Purpose: lock in the agent name resolution so that Claude Code subagent spawns
resolve correctly via (a) built-in generic map or (b) session-injected aliases,
and do NOT regress to "agent" fallback -> lock-death cycle.

After CZL-REFACTOR-LABS-NAMES: organization-specific names (e.g., "Alice-CTO",
"Bob-Kernel") are no longer hardcoded in _AGENT_TYPE_MAP. They resolve via
.ystar_session.json "agent_aliases" — the correct company-side injection point.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ystar.adapters.identity_detector import (
    _AGENT_TYPE_MAP,
    _detect_agent_id,
    _load_alias_map,
    _map_agent_type,
)


# --------------------------------------------------------------------------
# Fixture: Labs-style aliases injected via session config (company-side)
# --------------------------------------------------------------------------

_EXAMPLE_ALIASES = {
    "Alice-CEO": "ceo",
    "Alice": "ceo",
    "Bob-CTO": "cto",
    "Bob": "cto",
    "Bob Smith": "cto",
    "Charlie-Kernel": "eng-kernel",
    "Charlie": "eng-kernel",
    "Charlie Wang": "eng-kernel",
    "Diana-Platform": "eng-platform",
    "Diana": "eng-platform",
    "Diana Kim": "eng-platform",
    "Eve-Governance": "eng-governance",
    "Eve": "eng-governance",
    "Eve Johnson": "eng-governance",
    "Frank-Domains": "eng-domains",
    "Frank": "eng-domains",
    "Grace-CMO": "cmo",
    "Hank-CSO": "cso",
    "Ivan-CFO": "cfo",
    "Julia-Secretary": "secretary",
    "Julia Lin": "secretary",
}


# --------------------------------------------------------------------------
# Test 1: generic built-in names resolve without aliases
# --------------------------------------------------------------------------

_GENERIC_MAPPINGS = [
    ("Agent-CEO", "ceo"),
    ("Agent-CTO", "cto"),
    ("Agent-CMO", "cmo"),
    ("Agent-CFO", "cfo"),
    ("Agent-CSO", "cso"),
    ("Agent-Secretary", "secretary"),
    ("Agent-Kernel", "eng-kernel"),
    ("Agent-Platform", "eng-platform"),
    ("Agent-Governance", "eng-governance"),
    ("Agent-Domains", "eng-domains"),
    ("ystar-ceo", "ceo"),
    ("ystar-cto", "cto"),
    ("eng-kernel", "eng-kernel"),
    ("eng-platform", "eng-platform"),
    ("eng-governance", "eng-governance"),
    ("eng-domains", "eng-domains"),
]


def test_generic_names_resolve():
    """All generic Agent-Role and ystar-role names resolve without aliases."""
    with patch(
        "ystar.adapters.identity_detector._load_alias_map", return_value={}
    ):
        for name, expected in _GENERIC_MAPPINGS:
            assert _map_agent_type(name) == expected, (
                f"{name!r} should resolve to {expected!r}, got {_map_agent_type(name)!r}"
            )
    assert len(_GENERIC_MAPPINGS) >= 15, "Regression: fewer than 15 generic names covered"


# --------------------------------------------------------------------------
# Test 2: organization-specific names resolve VIA session aliases
# --------------------------------------------------------------------------

def test_org_names_resolve_via_aliases():
    """Organization-specific names resolve when injected via agent_aliases."""
    with patch(
        "ystar.adapters.identity_detector._load_alias_map",
        return_value=_EXAMPLE_ALIASES,
    ):
        for name, expected in _EXAMPLE_ALIASES.items():
            assert _map_agent_type(name) == expected, (
                f"{name!r} should resolve to {expected!r} via aliases, "
                f"got {_map_agent_type(name)!r}"
            )


# --------------------------------------------------------------------------
# Test 3: fuzzy matching via difflib for near-misses (generic names only)
# --------------------------------------------------------------------------

def test_fuzzy_matching_near_misses():
    """difflib should resolve slight typos/case/underscore variants."""
    with patch(
        "ystar.adapters.identity_detector._load_alias_map", return_value={}
    ):
        # Typo close to generic "Agent-CTO"
        assert _map_agent_type("Agent-CT0") == "cto"  # typo: 0 for O
        # Underscore instead of hyphen
        assert _map_agent_type("agent_kernel") == "eng-kernel"


# --------------------------------------------------------------------------
# Test 4: unknown names produce "guest" fallback at _detect_agent_id level
# (not "agent" — which was the lock-death root)
# --------------------------------------------------------------------------

def test_guest_fallback_on_complete_failure(tmp_path, monkeypatch):
    """When every resolution priority fails, _detect_agent_id returns 'guest'."""
    # Empty payload, no env vars, no markers in a clean tmp dir
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
    monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)
    monkeypatch.delenv("YSTAR_REPO_ROOT", raising=False)
    payload = {}
    assert _detect_agent_id(payload) == "guest"


def test_guest_fallback_does_not_return_agent():
    """Regression guard: the final fallback must NOT return 'agent'."""
    import inspect
    source = inspect.getsource(_detect_agent_id)
    # Must not contain `return "agent"` at the end
    assert 'return "agent"' not in source, (
        "Regression: _detect_agent_id still returns 'agent' — CZL-ARCH-1 reverted"
    )
    assert 'return "guest"' in source, (
        "Regression: _detect_agent_id missing 'guest' fallback"
    )


# --------------------------------------------------------------------------
# Test 5: .ystar_session.json agent_aliases field merges into resolution
# --------------------------------------------------------------------------

def test_alias_map_overrides_builtin(tmp_path, monkeypatch):
    """Custom alias from session.json takes effect alongside built-in map."""
    session_path = tmp_path / ".ystar_session.json"
    session_path.write_text(json.dumps({
        "schema_version": "1.0",
        "agent_aliases": {
            "Custom-Engineer": "eng-kernel",
            "ProjectLead": "ceo",
        },
    }))
    monkeypatch.setenv("YSTAR_REPO_ROOT", str(tmp_path))

    # Custom alias resolves
    assert _map_agent_type("Custom-Engineer") == "eng-kernel"
    assert _map_agent_type("ProjectLead") == "ceo"
    # Built-in generic still works (not clobbered)
    assert _map_agent_type("Agent-Kernel") == "eng-kernel"


def test_alias_map_graceful_when_missing(tmp_path, monkeypatch):
    """_load_alias_map returns {} when file missing / field absent / malformed."""
    monkeypatch.setenv("YSTAR_REPO_ROOT", str(tmp_path))
    # No file at all
    assert _load_alias_map() == {}

    # File exists, no agent_aliases field
    (tmp_path / ".ystar_session.json").write_text(json.dumps({"schema_version": "1.0"}))
    assert _load_alias_map() == {}

    # File exists, agent_aliases is not a dict
    (tmp_path / ".ystar_session.json").write_text(
        json.dumps({"agent_aliases": ["not", "a", "dict"]})
    )
    assert _load_alias_map() == {}


# --------------------------------------------------------------------------
# Test 6: case-insensitive resolution treats same logical name consistently
# --------------------------------------------------------------------------

def test_case_insensitive_matching():
    """Different casings of generic names resolve identically."""
    with patch(
        "ystar.adapters.identity_detector._load_alias_map", return_value={}
    ):
        assert _map_agent_type("AGENT-KERNEL") == "eng-kernel"
        assert _map_agent_type("agent-kernel") == "eng-kernel"
        assert _map_agent_type("Agent-Kernel") == "eng-kernel"
        assert _map_agent_type("agent-KERNEL") == "eng-kernel"


# --------------------------------------------------------------------------
# Test 7: empty / None input short-circuits safely
# --------------------------------------------------------------------------

def test_empty_input_handled():
    """Empty string input returns empty string without crashing."""
    assert _map_agent_type("") == ""


# --------------------------------------------------------------------------
# Test 8: _AGENT_TYPE_MAP has NO organization-specific names
# --------------------------------------------------------------------------

def test_no_org_specific_names_in_builtin_map():
    """Product _AGENT_TYPE_MAP must only contain generic Agent-Role / ystar-role keys."""
    # All keys must start with "Agent-", "ystar-", or "eng-" (generic prefixes)
    allowed_prefixes = ("Agent-", "ystar-", "eng-")
    for key in _AGENT_TYPE_MAP:
        assert key.startswith(allowed_prefixes), (
            f"_AGENT_TYPE_MAP contains non-generic key {key!r} — "
            f"move to .ystar_session.json agent_aliases"
        )

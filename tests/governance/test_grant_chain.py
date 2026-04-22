# tests/governance/test_grant_chain.py
# Copyright (C) 2026 Haotian Liu -- MIT License
"""
Grant Chain tests -- 8 cases covering issue/check/consume/expire/boundary integration.
"""
from __future__ import annotations

import json
import os
import time
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures: isolate each test to a temp workspace so grant files don't collide
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_grant_files(tmp_path, monkeypatch):
    """Redirect GRANT_FILE and AUDIT_FILE to tmp_path for test isolation."""
    import ystar.governance.grant_chain as gc
    monkeypatch.setattr(gc, "GRANT_FILE", tmp_path / ".ystar_active_grant.json")
    monkeypatch.setattr(gc, "AUDIT_FILE", tmp_path / ".ystar_grant_audit.jsonl")
    # Suppress CIEU emit during tests (no DB needed)
    monkeypatch.setattr(gc, "_emit_cieu", lambda *a, **kw: None)
    yield tmp_path


# ---------------------------------------------------------------------------
# Test 1: issue_grant writes file + returns Grant object
# ---------------------------------------------------------------------------

def test_issue_grant_writes_file(isolated_grant_files):
    from ystar.governance.grant_chain import issue_grant, GRANT_FILE, AUDIT_FILE

    g = issue_grant(
        grantor="cto",
        grantee="ceo",
        target_agent="eng-platform",
        atomic_id="CZL-TEST-001",
        ttl_seconds=600,
    )

    assert g.grantor == "cto"
    assert g.grantee == "ceo"
    assert g.target_agent == "eng-platform"
    assert g.atomic_id == "CZL-TEST-001"
    assert g.ttl_seconds == 600
    assert not g.consumed
    assert g.consumed_at is None
    assert g.grant_id  # non-empty UUID

    # File written
    assert GRANT_FILE.exists()
    data = json.loads(GRANT_FILE.read_text())
    assert len(data) == 1
    assert data[0]["grant_id"] == g.grant_id

    # Audit trail written
    assert AUDIT_FILE.exists()
    audit_lines = AUDIT_FILE.read_text().strip().split("\n")
    assert len(audit_lines) == 1
    audit = json.loads(audit_lines[0])
    assert audit["action"] == "GRANT_ISSUED"


# ---------------------------------------------------------------------------
# Test 2: check_grant finds valid grant
# ---------------------------------------------------------------------------

def test_check_grant_valid():
    from ystar.governance.grant_chain import issue_grant, check_grant

    g = issue_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-kernel", atomic_id="CZL-002", ttl_seconds=600,
    )

    found = check_grant(
        grantor="cto", grantee="ceo", target_agent="eng-kernel", atomic_id="CZL-002",
    )
    assert found is not None
    assert found.grant_id == g.grant_id


# ---------------------------------------------------------------------------
# Test 3: check_grant expired -> None
# ---------------------------------------------------------------------------

def test_check_grant_expired():
    from ystar.governance.grant_chain import issue_grant, check_grant

    g = issue_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-platform", atomic_id="CZL-003", ttl_seconds=1,
    )

    # Simulate time passing beyond TTL
    future = time.time() + 10
    found = check_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-platform", atomic_id="CZL-003",
        now=future,
    )
    assert found is None


# ---------------------------------------------------------------------------
# Test 4: check_grant consumed -> None
# ---------------------------------------------------------------------------

def test_check_grant_consumed():
    from ystar.governance.grant_chain import issue_grant, check_grant, consume_grant

    g = issue_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-governance", atomic_id="CZL-004", ttl_seconds=600,
    )

    # Consume it
    assert consume_grant(g.grant_id) is True

    # Now check should fail
    found = check_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-governance", atomic_id="CZL-004",
    )
    assert found is None


# ---------------------------------------------------------------------------
# Test 5: double consume -> second returns False (noop + warn)
# ---------------------------------------------------------------------------

def test_double_consume_noop():
    from ystar.governance.grant_chain import issue_grant, consume_grant

    g = issue_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-platform", atomic_id="CZL-005", ttl_seconds=600,
    )

    assert consume_grant(g.grant_id) is True
    assert consume_grant(g.grant_id) is False  # second time = noop


# ---------------------------------------------------------------------------
# Test 6: expire_stale_grants sweeps old grants
# ---------------------------------------------------------------------------

def test_expire_stale_grants():
    from ystar.governance.grant_chain import (
        issue_grant, expire_stale_grants, check_grant, _read_grants, _grant_from_dict,
    )

    # Issue with very short TTL
    g = issue_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-domains", atomic_id="CZL-006", ttl_seconds=0,
    )

    # Wait just a tick for expiry
    time.sleep(0.01)

    count = expire_stale_grants()
    assert count == 1

    # Grant should now be marked consumed
    grants = _read_grants()
    assert len(grants) == 1
    assert grants[0]["consumed"] is True


# ---------------------------------------------------------------------------
# Test 7: alias normalization -- "Ryan-Platform" matches "eng-platform"
# ---------------------------------------------------------------------------

def test_alias_normalization():
    from ystar.governance.grant_chain import issue_grant, check_grant

    g = issue_grant(
        grantor="cto", grantee="ceo",
        target_agent="Ryan-Platform",  # alias
        atomic_id="CZL-007", ttl_seconds=600,
    )

    # Stored as canonical
    assert g.target_agent == "eng-platform"

    # Check with alias also works
    found = check_grant(
        grantor="cto", grantee="ceo",
        target_agent="Ryan-Platform",
        atomic_id="CZL-007",
    )
    assert found is not None
    assert found.grant_id == g.grant_id

    # Check with canonical also works
    found2 = check_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-platform",
        atomic_id="CZL-007",
    )
    assert found2 is not None


# ---------------------------------------------------------------------------
# Test 8: check_grant with mismatched grantor/grantee/target -> None
# ---------------------------------------------------------------------------

def test_check_grant_wrong_params():
    from ystar.governance.grant_chain import issue_grant, check_grant

    issue_grant(
        grantor="cto", grantee="ceo",
        target_agent="eng-platform", atomic_id="CZL-008", ttl_seconds=600,
    )

    # Wrong grantor
    assert check_grant(grantor="cmo", grantee="ceo", target_agent="eng-platform") is None
    # Wrong grantee
    assert check_grant(grantor="cto", grantee="cmo", target_agent="eng-platform") is None
    # Wrong target
    assert check_grant(grantor="cto", grantee="ceo", target_agent="eng-kernel") is None
    # Wrong atomic_id (when specified)
    assert check_grant(grantor="cto", grantee="ceo", target_agent="eng-platform", atomic_id="WRONG") is None

"""
Tests for ystar.governance.liveness_audit (CZL-ARCH-10).

3 required tests:
1. scan returns non-empty for known modules
2. classification correct for well-known LIVE module (e.g. check_hook pattern)
3. dead list outputs plain txt
"""

import os
import sqlite3
import tempfile
import time

import pytest

from ystar.governance.liveness_audit import (
    LivenessReport,
    ModuleRecord,
    _classify,
    _collect_modules,
    scan_ystar_liveness,
    write_dead_list,
    write_markdown_report,
)

YSTAR_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ystar")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cieu_db(path, entries=None):
    """Create a minimal cieu_events table with optional rows."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE cieu_events (
            id INTEGER PRIMARY KEY,
            created_at REAL,
            params_json TEXT DEFAULT '',
            violations TEXT DEFAULT ''
        )
    """)
    if entries:
        for ts, params, violations in entries:
            conn.execute(
                "INSERT INTO cieu_events (created_at, params_json, violations) VALUES (?,?,?)",
                (ts, params, violations),
            )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Test 1: scan returns non-empty for known modules
# ---------------------------------------------------------------------------

def test_scan_returns_nonempty_for_known_modules():
    """scan_ystar_liveness on real ystar/ tree must find modules."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        _make_cieu_db(db_path)
        report = scan_ystar_liveness(YSTAR_ROOT, db_path)
        assert report.error is None, f"scan error: {report.error}"
        assert report.scanned > 0, "Expected >0 scanned modules"
        assert len(report.results) > 0
        # At least some well-known modules should appear
        names = {r.module for r in report.results}
        # governance subpackage must have many modules
        gov_count = sum(1 for n in names if "governance" in n)
        assert gov_count > 5, f"Expected >5 governance modules, got {gov_count}"
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Test 2: classification correct for well-known LIVE pattern
# ---------------------------------------------------------------------------

def test_classification_live_when_recent_fires():
    """A module with fires_7d > 0 must classify as LIVE regardless of callers."""
    assert _classify(fires_7d=3, fires_30d=5, callers=2) == "LIVE"
    assert _classify(fires_7d=1, fires_30d=1, callers=0) == "LIVE"

    # With callers but no recent fires -> DORMANT
    assert _classify(fires_7d=0, fires_30d=2, callers=3) == "DORMANT"

    # No callers, no fires -> DEAD
    assert _classify(fires_7d=0, fires_30d=0, callers=0) == "DEAD"

    # Verify via full scan with injected CIEU data
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        now = time.time()
        # Inject a recent event mentioning "check_hook"
        _make_cieu_db(db_path, entries=[
            (now - 3600, '{"hook": "check_hook"}', ''),
        ])
        report = scan_ystar_liveness(YSTAR_ROOT, db_path, max_modules=300)
        assert report.error is None
        # Find any module whose last_name matches something with fires
        live_mods = [r for r in report.results if r.category == "LIVE"]
        # We injected "check_hook" so any module named *check_hook* should be LIVE
        # (the match is substring-based in CIEU query)
        # General assertion: classification function is consistent
        for r in report.results:
            expected = _classify(r.fires_7d, r.fires_30d, r.callers)
            assert r.category == expected, f"{r.module}: got {r.category}, expected {expected}"
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Test 3: dead list outputs plain txt
# ---------------------------------------------------------------------------

def test_dead_list_output_plain_txt():
    """write_dead_list produces a plain text file with one module per line."""
    report = LivenessReport(
        generated_at=time.time(),
        scanned=4,
        results=[
            ModuleRecord("ystar.governance.alpha", "/a.py", 5, 1, 2, "LIVE"),
            ModuleRecord("ystar.governance.beta", "/b.py", 2, 0, 1, "DORMANT"),
            ModuleRecord("ystar.governance.gamma", "/c.py", 0, 0, 0, "DEAD"),
            ModuleRecord("ystar.governance.delta", "/d.py", 0, 0, 0, "DEAD"),
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        txt_path = os.path.join(td, "dead.txt")
        result = write_dead_list(report, txt_path)
        assert result == txt_path
        assert os.path.exists(txt_path)

        with open(txt_path) as f:
            content = f.read()
        lines = content.strip().split("\n")
        assert lines == ["ystar.governance.gamma", "ystar.governance.delta"]

        # Also verify markdown report writes without error
        md_path = os.path.join(td, "report.md")
        write_markdown_report(report, md_path)
        assert os.path.exists(md_path)
        with open(md_path) as f:
            md = f.read()
        assert "LIVE=1" in md
        assert "DEAD=2" in md

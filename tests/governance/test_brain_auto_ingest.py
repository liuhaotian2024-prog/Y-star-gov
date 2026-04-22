#!/usr/bin/env python3
"""
Regression tests for brain_auto_ingest.py — boundary (c)+(d) auto-ingest module.

Covers:
  - Content-hash dedup (no double-ingest)
  - access_count increments correctly on repeat activation
  - file-mtime filter works
  - CIEU-event -> activation chain
  - Sentinel persistence
  - Co-activation edge creation
  - Full vs delta mode
  - Error resilience
  - Node ID scheme
  - Summary extraction
  - Upsert preservation of access_count/last_accessed/created_at
"""

import json
import os
import sqlite3
import tempfile
import time

import pytest

# Module under test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ystar", "governance"))
from brain_auto_ingest import (
    content_hash,
    scan_sources,
    scan_cieu_events,
    extract_candidates,
    apply_ingest,
    increment_access_count,
    _read_sentinel,
    _write_sentinel,
    _make_node_id,
    _infer_type,
    _infer_depth,
    _extract_summary,
    _ensure_brain_tables,
    _upsert_node,
    _write_activation_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_env(tmp_path):
    """Set up a temporary company root with reports/knowledge/memory dirs
    and a temporary brain DB + sentinel."""
    company = tmp_path / "company"
    company.mkdir()

    for d in ["reports", "knowledge", "memory"]:
        (company / d).mkdir()

    brain_db = str(tmp_path / "test_brain.db")
    sentinel = str(tmp_path / "sentinel.json")
    cieu_db = str(tmp_path / "cieu.db")

    # Initialise brain tables
    _ensure_brain_tables(brain_db)

    return {
        "company": str(company),
        "brain_db": brain_db,
        "sentinel": sentinel,
        "cieu_db": cieu_db,
    }


def _write_md(company_root, rel_path, content):
    """Helper: write a .md file at rel_path under company root."""
    fpath = os.path.join(company_root, rel_path)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w") as f:
        f.write(content)
    return fpath


def _query_nodes(db_path, where="1=1"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM nodes WHERE {where}").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _query_edges(db_path, where="1=1"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM edges WHERE {where}").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _query_activation_log(db_path, where="1=1"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM activation_log WHERE {where}").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_deterministic(self):
        assert content_hash("hello world") == content_hash("hello world")

    def test_different_content_different_hash(self):
        assert content_hash("hello") != content_hash("world")

    def test_length_16(self):
        assert len(content_hash("any content")) == 16


class TestNodeIdScheme:
    def test_slash_separator(self):
        assert _make_node_id("reports/cto/ruling.md") == "reports/cto/ruling"

    def test_spaces_to_underscore(self):
        assert _make_node_id("knowledge/my file.md") == "knowledge/my_file"

    def test_nested_path(self):
        assert _make_node_id("memory/session/handoff.md") == "memory/session/handoff"


class TestInferType:
    def test_reports(self):
        assert _infer_type("reports/cto/something.md") == "report"

    def test_knowledge(self):
        assert _infer_type("knowledge/ceo/wisdom/thing.md") == "knowledge"

    def test_memory(self):
        assert _infer_type("memory/handoff.md") == "memory"

    def test_unknown(self):
        assert _infer_type("other/file.md") == "misc"


class TestInferDepth:
    def test_wisdom(self):
        assert _infer_depth("knowledge/ceo/wisdom/thing.md") == "kernel"

    def test_lessons(self):
        assert _infer_depth("knowledge/ceo/lessons/thing.md") == "tactical"

    def test_cto(self):
        assert _infer_depth("reports/cto/thing.md") == "operational"

    def test_default(self):
        assert _infer_depth("reports/thing.md") == "operational"


class TestExtractSummary:
    def test_with_frontmatter(self):
        text = "---\nname: Test\n---\n\n# Title\n\nThis is the first meaningful line of content."
        assert "first meaningful line" in _extract_summary(text, "fallback")

    def test_short_lines_skipped(self):
        text = "Hi\nYes\nThis is a longer meaningful line here."
        assert "longer meaningful" in _extract_summary(text, "fallback")

    def test_fallback(self):
        text = "Hi\nNo"
        assert _extract_summary(text, "my fallback name") == "my fallback name"


class TestScanSources:
    def test_finds_new_md_files(self, tmp_env):
        _write_md(tmp_env["company"], "reports/test.md", "# Test Report")
        _write_md(tmp_env["company"], "knowledge/doc.md", "# Knowledge Doc")

        cands = scan_sources(
            company_root=tmp_env["company"],
            sentinel_path=tmp_env["sentinel"],
        )
        assert len(cands) == 2
        ids = {c["node_id"] for c in cands}
        assert "reports/test" in ids
        assert "knowledge/doc" in ids

    def test_ignores_non_md(self, tmp_env):
        _write_md(tmp_env["company"], "reports/test.txt", "not markdown")
        # Rename to .txt
        src = os.path.join(tmp_env["company"], "reports", "test.txt")
        # This was already created as .txt via _write_md (helper writes any ext)
        cands = scan_sources(
            company_root=tmp_env["company"],
            sentinel_path=tmp_env["sentinel"],
        )
        assert len(cands) == 0

    def test_hash_dedup_skips_unchanged(self, tmp_env):
        _write_md(tmp_env["company"], "reports/stable.md", "Unchanged content")

        cands1 = scan_sources(tmp_env["company"], tmp_env["sentinel"])
        assert len(cands1) == 1

        # Simulate sentinel update (as apply_ingest would do)
        sentinel = _read_sentinel(tmp_env["sentinel"])
        sentinel["file_hashes"]["reports/stable.md"] = content_hash("Unchanged content")
        _write_sentinel(sentinel, tmp_env["sentinel"])

        # Second scan: same content, should be skipped
        cands2 = scan_sources(tmp_env["company"], tmp_env["sentinel"])
        assert len(cands2) == 0

    def test_detects_changed_content(self, tmp_env):
        _write_md(tmp_env["company"], "reports/evolving.md", "Version 1")

        # First scan + sentinel update
        cands = scan_sources(tmp_env["company"], tmp_env["sentinel"])
        sentinel = _read_sentinel(tmp_env["sentinel"])
        sentinel["file_hashes"]["reports/evolving.md"] = content_hash("Version 1")
        _write_sentinel(sentinel, tmp_env["sentinel"])

        # Change content
        _write_md(tmp_env["company"], "reports/evolving.md", "Version 2")

        cands2 = scan_sources(tmp_env["company"], tmp_env["sentinel"])
        assert len(cands2) == 1
        assert cands2[0]["hash"] == content_hash("Version 2")


class TestApplyIngest:
    def test_ingests_nodes_into_brain(self, tmp_env):
        _write_md(tmp_env["company"], "reports/alpha.md", "# Alpha Report\n\nThis is the alpha report content.")
        _write_md(tmp_env["company"], "knowledge/beta.md", "# Beta Knowledge\n\nBeta knowledge document.")

        cands = extract_candidates(
            company_root=tmp_env["company"],
            sentinel_path=tmp_env["sentinel"],
        )
        result = apply_ingest(
            cands,
            company_root=tmp_env["company"],
            brain_db=tmp_env["brain_db"],
            sentinel_path=tmp_env["sentinel"],
        )

        assert result["ingested"] == 2
        assert result["errors"] == 0

        nodes = _query_nodes(tmp_env["brain_db"])
        assert len(nodes) == 2
        ids = {n["id"] for n in nodes}
        assert "reports/alpha" in ids
        assert "knowledge/beta" in ids

    def test_content_hash_populated(self, tmp_env):
        content = "# Hash Test\n\nContent for hash verification."
        _write_md(tmp_env["company"], "reports/hashtest.md", content)

        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        nodes = _query_nodes(tmp_env["brain_db"], "id='reports/hashtest'")
        assert len(nodes) == 1
        assert nodes[0]["content_hash"] == content_hash(content)
        assert len(nodes[0]["content_hash"]) == 16

    def test_no_double_ingest(self, tmp_env):
        """Content-hash dedup: second run with same content yields ingested=0."""
        _write_md(tmp_env["company"], "reports/dedup.md", "Same content twice")

        cands1 = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        r1 = apply_ingest(cands1, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])
        assert r1["ingested"] == 1

        cands2 = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        r2 = apply_ingest(cands2, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])
        assert r2["ingested"] == 0  # dedup in action

    def test_access_count_preserved_on_re_ingest(self, tmp_env):
        """When content changes and node is re-ingested, access_count is NOT reset."""
        _write_md(tmp_env["company"], "reports/counter.md", "V1")
        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        # Manually bump access_count
        increment_access_count("reports/counter", tmp_env["brain_db"])
        increment_access_count("reports/counter", tmp_env["brain_db"])
        increment_access_count("reports/counter", tmp_env["brain_db"])

        nodes_before = _query_nodes(tmp_env["brain_db"], "id='reports/counter'")
        assert nodes_before[0]["access_count"] == 3

        # Change content -> re-ingest
        _write_md(tmp_env["company"], "reports/counter.md", "V2")
        cands2 = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands2, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        nodes_after = _query_nodes(tmp_env["brain_db"], "id='reports/counter'")
        assert nodes_after[0]["access_count"] == 3  # preserved!
        assert nodes_after[0]["content_hash"] == content_hash("V2")  # updated

    def test_activation_log_written(self, tmp_env):
        """Each ingested file gets an activation_log entry."""
        _write_md(tmp_env["company"], "reports/logged.md", "# Logged\n\nActivation log test.")

        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        logs = _query_activation_log(tmp_env["brain_db"])
        assert len(logs) >= 1
        log = logs[0]
        assert "auto_ingest:" in log["query"]
        activated = json.loads(log["activated_nodes"])
        assert activated[0]["activation_level"] == 0.3
        assert activated[0]["node_id"] == "reports/logged"

    def test_co_activation_edges_same_dir(self, tmp_env):
        """Multiple files in same directory get proximity edges."""
        _write_md(tmp_env["company"], "reports/same_dir/a.md", "# A\n\nFile A content here.")
        _write_md(tmp_env["company"], "reports/same_dir/b.md", "# B\n\nFile B content here.")
        _write_md(tmp_env["company"], "reports/same_dir/c.md", "# C\n\nFile C content here.")

        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        edges = _query_edges(tmp_env["brain_db"])
        # 3 nodes -> 3 pairs, bidirectional -> 6 edges
        assert len(edges) >= 6
        edge_types = {e["edge_type"] for e in edges}
        assert "proximity" in edge_types


class TestIncrementAccessCount:
    def test_increments_from_zero(self, tmp_env):
        _write_md(tmp_env["company"], "reports/inc.md", "# Inc\n\nIncrement test.")
        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        nodes = _query_nodes(tmp_env["brain_db"], "id='reports/inc'")
        assert nodes[0]["access_count"] == 0

        increment_access_count("reports/inc", tmp_env["brain_db"])
        nodes = _query_nodes(tmp_env["brain_db"], "id='reports/inc'")
        assert nodes[0]["access_count"] == 1

    def test_increments_multiple_times(self, tmp_env):
        _write_md(tmp_env["company"], "reports/multi.md", "# Multi\n\nMultiple increment test.")
        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        for _ in range(5):
            increment_access_count("reports/multi", tmp_env["brain_db"])

        nodes = _query_nodes(tmp_env["brain_db"], "id='reports/multi'")
        assert nodes[0]["access_count"] == 5

    def test_updates_last_accessed(self, tmp_env):
        _write_md(tmp_env["company"], "reports/ts.md", "# Timestamp\n\nTimestamp test content.")
        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        before = _query_nodes(tmp_env["brain_db"], "id='reports/ts'")[0]["last_accessed"]
        time.sleep(0.01)
        increment_access_count("reports/ts", tmp_env["brain_db"])
        after = _query_nodes(tmp_env["brain_db"], "id='reports/ts'")[0]["last_accessed"]
        assert after > before

    def test_nonexistent_node_no_crash(self, tmp_env):
        """Incrementing a nonexistent node should not crash (0 rows affected)."""
        increment_access_count("nonexistent/node", tmp_env["brain_db"])
        # No exception = pass


class TestSentinel:
    def test_sentinel_persists_across_runs(self, tmp_env):
        _write_md(tmp_env["company"], "reports/sentinel.md", "# Sentinel\n\nSentinel persistence test.")

        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        sentinel = _read_sentinel(tmp_env["sentinel"])
        assert sentinel["last_ingest_ts"] > 0
        assert "reports/sentinel.md" in sentinel["file_hashes"]
        assert sentinel["file_hashes"]["reports/sentinel.md"] == content_hash(
            "# Sentinel\n\nSentinel persistence test."
        )

    def test_fresh_sentinel_returns_defaults(self, tmp_env):
        sentinel = _read_sentinel("/nonexistent/path.json")
        assert sentinel["last_ingest_ts"] == 0.0
        assert sentinel["file_hashes"] == {}
        assert sentinel["last_cieu_id"] == 0


class TestFullMode:
    def test_full_mode_re_ingests_unchanged(self, tmp_env):
        """Full mode clears sentinel, forcing re-scan of all files."""
        _write_md(tmp_env["company"], "reports/full.md", "# Full\n\nFull mode test content here.")

        # First delta ingest
        cands1 = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        r1 = apply_ingest(cands1, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])
        assert r1["ingested"] == 1

        # Clear sentinel to simulate --mode full
        _write_sentinel({"last_ingest_ts": 0.0, "file_hashes": {}, "last_cieu_id": 0},
                        tmp_env["sentinel"])

        # Second ingest: should re-ingest
        cands2 = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        r2 = apply_ingest(cands2, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])
        assert r2["ingested"] == 1  # re-ingested because sentinel was cleared


class TestCIEUEvents:
    def test_cieu_event_increments_access_count(self, tmp_env):
        """CIEU events with node_id in payload trigger access_count increment."""
        # Create a node first
        _write_md(tmp_env["company"], "reports/cieu_target.md", "# CIEU Target\n\nCIEU event target node.")
        cands = extract_candidates(
            tmp_env["company"], tmp_env["sentinel"], tmp_env["cieu_db"],
        )
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        # Create a fake CIEU database with events
        conn = sqlite3.connect(tmp_env["cieu_db"])
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cieu_events (
                event_type TEXT,
                payload TEXT,
                timestamp REAL
            )
        """)
        conn.execute(
            "INSERT INTO cieu_events (event_type, payload, timestamp) VALUES (?, ?, ?)",
            ("NODE_ACTIVATED", json.dumps({"node_id": "reports/cieu_target"}), time.time()),
        )
        conn.commit()
        conn.close()

        # Re-extract with CIEU
        cands2 = extract_candidates(
            tmp_env["company"], tmp_env["sentinel"], tmp_env["cieu_db"],
        )
        r = apply_ingest(cands2, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])
        assert r["cieu_activations"] == 1

        nodes = _query_nodes(tmp_env["brain_db"], "id='reports/cieu_target'")
        assert nodes[0]["access_count"] == 1

    def test_cieu_scan_empty_db(self, tmp_env):
        """scan_cieu_events handles missing DB gracefully."""
        events = scan_cieu_events("/nonexistent/cieu.db", tmp_env["sentinel"])
        assert events == []


class TestErrorResilience:
    def test_unreadable_file_skipped(self, tmp_env):
        """Files that can't be read are silently skipped."""
        # Create a valid file
        _write_md(tmp_env["company"], "reports/good.md", "# Good\n\nGood file content here.")
        # Create a directory with .md name (will fail to open as file)
        bad_path = os.path.join(tmp_env["company"], "reports", "bad.md")
        os.makedirs(bad_path, exist_ok=True)

        cands = scan_sources(tmp_env["company"], tmp_env["sentinel"])
        # Should get only the good file, not crash
        assert len(cands) == 1
        assert cands[0]["node_id"] == "reports/good"


class TestCreatedAtPreservation:
    def test_created_at_not_reset_on_update(self, tmp_env):
        """When a node is re-ingested with changed content, created_at is preserved."""
        _write_md(tmp_env["company"], "reports/created.md", "V1 content here for test")

        cands = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        nodes_before = _query_nodes(tmp_env["brain_db"], "id='reports/created'")
        created_at_before = nodes_before[0]["created_at"]
        assert created_at_before > 0

        time.sleep(0.01)

        # Change content
        _write_md(tmp_env["company"], "reports/created.md", "V2 content here for test")
        cands2 = extract_candidates(tmp_env["company"], tmp_env["sentinel"])
        apply_ingest(cands2, tmp_env["company"], tmp_env["brain_db"], tmp_env["sentinel"])

        nodes_after = _query_nodes(tmp_env["brain_db"], "id='reports/created'")
        assert nodes_after[0]["created_at"] == created_at_before  # preserved
        assert nodes_after[0]["updated_at"] > created_at_before  # updated

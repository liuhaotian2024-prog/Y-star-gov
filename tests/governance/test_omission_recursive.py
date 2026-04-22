"""
test_omission_recursive.py  --  Tests for OmissionEngine Level 2 + Level 3
===========================================================================

Board 2026-04-19: "有了就要照亮更多的无"

Tests:
  1. test_manifest_audit_finds_uncovered_failure_types
  2. test_manifest_audit_no_false_positives
  3. test_derive_obligations_finds_missing_backup
  4. test_derive_obligations_uses_k9_when_available
  5. test_recursive_illuminate_cli_smoke
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

# Ensure ystar is importable
_ystar_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ystar_root))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def cieu_db_with_failures(tmp_path):
    """Create a CIEU DB seeded with known failure event types."""
    db_path = tmp_path / "test_cieu.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cieu_events (
            rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id     TEXT NOT NULL UNIQUE,
            seq_global   INTEGER NOT NULL,
            created_at   REAL NOT NULL,
            session_id   TEXT NOT NULL,
            agent_id     TEXT NOT NULL,
            event_type   TEXT NOT NULL,
            decision     TEXT NOT NULL,
            passed       INTEGER NOT NULL DEFAULT 0,
            violations   TEXT,
            drift_detected INTEGER NOT NULL DEFAULT 0,
            drift_details TEXT,
            drift_category TEXT,
            file_path    TEXT,
            command      TEXT,
            url          TEXT,
            skill_name   TEXT,
            task_description TEXT,
            params_json  TEXT,
            result_json  TEXT,
            contract_hash TEXT,
            chain_depth  INTEGER,
            human_initiator TEXT,
            lineage_path TEXT,
            sealed       INTEGER DEFAULT 0,
            evidence_grade TEXT
        )
    """)

    now = time.time()

    # Seed with known failure types
    failure_types = [
        ("NEW_FAILURE_KIND", "deny", 5),
        ("WEIRD_CRASH_TYPE", "error", 3),
        ("circuit_breaker_armed", "deny", 10),
        ("cmd_exec", "deny", 7),
        ("file_write", "deny", 2),
    ]
    import uuid
    for event_type, decision, count in failure_types:
        for i in range(count):
            conn.execute(
                "INSERT INTO cieu_events "
                "(event_id, seq_global, created_at, session_id, agent_id, "
                " event_type, decision, passed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    int(now * 1_000_000) + i,
                    now - (86400 * 2),  # 2 days ago
                    "test_session",
                    "test_agent",
                    event_type,
                    decision,
                    0,
                ),
            )

    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture
def manifest_file(tmp_path):
    """Create a minimal manifest covering only circuit_breaker and cmd_exec."""
    manifest_content = """
features:
  - feature_id: arch18_cieu_brain
    description: "CIEU Brain"
    phases:
      phase_1:
        description: "Foundation"
        ship_markers:
          - activation_log_nonzero
          - cieu_brain_bridge_tests_pass
      phase_2:
        description: "Continuous streaming daemon"
        ship_markers:
          - continuous_daemon_running
          - circuit_breaker_armed
"""
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(manifest_content)
    return str(manifest_path)


@pytest.fixture
def complete_manifest(tmp_path):
    """Create a manifest that covers ALL failure types in the test DB."""
    manifest_content = """
features:
  - feature_id: test_feature
    description: "Test feature"
    phases:
      phase_1:
        description: "Foundation"
        ship_markers:
          - NEW_FAILURE_KIND
          - WEIRD_CRASH_TYPE
          - circuit_breaker_armed
          - cmd_exec
          - file_write
"""
    manifest_path = tmp_path / "complete_manifest.yaml"
    manifest_path.write_text(manifest_content)
    return str(manifest_path)


@pytest.fixture
def ystar_gov_root(tmp_path):
    """Create a minimal Y*gov repo structure for Level 3 testing."""
    root = tmp_path / "ygov"
    root.mkdir()
    (root / "docs" / "arch").mkdir(parents=True)
    (root / "tests" / "governance").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "tools" / "cieu").mkdir(parents=True)
    return str(root)


@pytest.fixture
def labs_root(tmp_path):
    """Create a minimal ystar-company repo structure for Level 3 testing."""
    root = tmp_path / "labs"
    root.mkdir()
    (root / "knowledge" / "cto").mkdir(parents=True)
    (root / "knowledge" / "shared").mkdir(parents=True)
    return str(root)


# ── Test 1: manifest audit finds uncovered failure types ──────────────────────

def test_manifest_audit_finds_uncovered_failure_types(
    cieu_db_with_failures, manifest_file
):
    """
    Seed CIEU with event_type='NEW_FAILURE_KIND' not in manifest.
    audit_manifest_completeness must return this as a gap.
    """
    from ystar.governance.omission_engine import audit_manifest_completeness

    result = audit_manifest_completeness(
        manifest_path=manifest_file,
        cieu_db_path=cieu_db_with_failures,
        window_days=7,
    )

    assert "gaps" in result
    assert len(result["gaps"]) > 0

    gap_types = [g["failure_type"] for g in result["gaps"]]
    assert "NEW_FAILURE_KIND" in gap_types, (
        f"NEW_FAILURE_KIND should be an uncovered gap, got: {gap_types}"
    )
    assert "WEIRD_CRASH_TYPE" in gap_types, (
        f"WEIRD_CRASH_TYPE should be an uncovered gap, got: {gap_types}"
    )

    # Verify each gap has required fields
    for gap in result["gaps"]:
        assert "failure_type" in gap
        assert "count" in gap
        assert "suggested_marker" in gap
        assert gap["count"] > 0


# ── Test 2: manifest audit no false positives ─────────────────────────────────

def test_manifest_audit_no_false_positives(
    cieu_db_with_failures, complete_manifest
):
    """
    All known failure types are covered by the manifest.
    Gap list should be empty.
    """
    from ystar.governance.omission_engine import audit_manifest_completeness

    result = audit_manifest_completeness(
        manifest_path=complete_manifest,
        cieu_db_path=cieu_db_with_failures,
        window_days=7,
    )

    assert "gaps" in result
    assert len(result["gaps"]) == 0, (
        f"Expected no gaps when manifest covers all types, got: {result['gaps']}"
    )


# ── Test 3: derive obligations finds missing backup ───────────────────────────

def test_derive_obligations_finds_missing_backup(
    ystar_gov_root, labs_root
):
    """
    Ship event for a feature without backup artifact.
    derive_new_obligations_from_ship must find at least the missing backup.
    """
    from ystar.governance.omission_engine import derive_new_obligations_from_ship

    # Create manifest in the test ygov root
    manifest_dir = Path(ystar_gov_root) / "docs" / "arch"
    manifest_path = manifest_dir / "phase_lifecycle_manifest.yaml"
    manifest_path.write_text("""
features:
  - feature_id: test_new_feature
    description: "A test feature"
    phases:
      phase_1:
        description: "Foundation"
        ship_markers:
          - some_marker
""")

    ship_event = {
        "feature_id": "test_new_feature",
        "event_type": "test_new_feature_shipped",
    }

    result = derive_new_obligations_from_ship(
        ship_event=ship_event,
        manifest_path=str(manifest_path),
        k9_adapter_path="/nonexistent/k9",  # K9 not available
        ystar_gov_root=ystar_gov_root,
        labs_root=labs_root,
    )

    assert "derived_obligations" in result
    assert len(result["derived_obligations"]) > 0

    missing_artifacts = [d["missing_artifact"] for d in result["derived_obligations"]]

    # At minimum, tests + documentation + backup should be missing
    assert "tests" in missing_artifacts, (
        f"'tests' should be missing, got: {missing_artifacts}"
    )
    assert "backup_artifact" in missing_artifacts, (
        f"'backup_artifact' should be missing, got: {missing_artifacts}"
    )

    # Verify obligation structure
    for ob in result["derived_obligations"]:
        assert "obligation_type" in ob
        assert "missing_artifact" in ob
        assert "reason" in ob
        assert "source_node" in ob
        assert "priority" in ob


# ── Test 4: derive obligations uses K9 when available ─────────────────────────

def test_derive_obligations_uses_k9_when_available(
    ystar_gov_root, labs_root, tmp_path
):
    """
    Mock K9 adapter availability. Verify causal traversal is called.
    """
    from ystar.governance.omission_engine import derive_new_obligations_from_ship

    # Create a fake K9Audit repo with the expected structure
    k9_path = tmp_path / "K9Audit"
    k9_path.mkdir()
    (k9_path / "k9log").mkdir()
    (k9_path / "k9log" / "__init__.py").write_text("")

    # Write a mock causal_analyzer module
    (k9_path / "k9log" / "causal_analyzer.py").write_text("""
class CausalChainAnalyzer:
    def __init__(self, path):
        self.path = path

    def build_causal_dag(self):
        return {"nodes": ["a", "b"], "edges": [("a", "b")]}

    def find_root_causes(self):
        return ["unresolved_dependency_alpha"]
""")

    ship_event = {
        "feature_id": "test_k9_feature",
        "event_type": "test_k9_feature_shipped",
    }

    result = derive_new_obligations_from_ship(
        ship_event=ship_event,
        k9_adapter_path=str(k9_path),
        ystar_gov_root=ystar_gov_root,
        labs_root=labs_root,
    )

    assert result["k9_used"] is True, "K9 should have been used"
    assert len(result["k9_causal_obligations"]) > 0, (
        "K9 should have produced at least one causal obligation"
    )

    k9_ob = result["k9_causal_obligations"][0]
    assert "k9_causal:" in k9_ob["missing_artifact"]
    assert "unresolved_dependency_alpha" in k9_ob["missing_artifact"]


# ── Test 5: CLI smoke test ────────────────────────────────────────────────────

def test_recursive_illuminate_cli_smoke(
    cieu_db_with_failures, manifest_file, tmp_path
):
    """
    Run the CLI script end-to-end. Output must be valid JSON when --json is used.
    """
    script_path = _ystar_root / "scripts" / "omission_recursive_illuminate.py"

    # Create minimal Y*gov structure in tmp
    ygov = tmp_path / "ygov_cli"
    ygov.mkdir()
    (ygov / "docs" / "arch").mkdir(parents=True)

    # Copy manifest to expected location
    import shutil
    shutil.copy2(manifest_file, str(ygov / "docs" / "arch" / "phase_lifecycle_manifest.yaml"))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ystar_root)

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--feature", "arch18_cieu_brain",
            "--cieu-db", cieu_db_with_failures,
            "--manifest", manifest_file,
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"CLI exited with code {result.returncode}.\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )

    # Output must be valid JSON
    output = json.loads(result.stdout)
    assert "feature" in output
    assert output["feature"] == "arch18_cieu_brain"
    assert "level2_manifest_audit" in output
    assert "level3_derived_obligations" in output
    assert "summary" in output

    # Summary must have expected keys
    summary = output["summary"]
    assert "uncovered_failure_types" in summary
    assert "derived_obligations" in summary
    assert "total_new_absences_illuminated" in summary

    # Should find at least 1 gap (NEW_FAILURE_KIND and WEIRD_CRASH_TYPE are not in manifest)
    assert summary["uncovered_failure_types"] >= 1
    # Should find at least 1 derived obligation (missing artifacts for arch18_cieu_brain)
    assert summary["derived_obligations"] >= 1

"""
Tests for directive_evaluator.py — Phase 1 Directive Liveness Evaluator

Tests cover:
  - 7 check primitives (happy + failure paths)
  - fg_rule_is_expired bonus primitive
  - Integration: evaluate() on directive dicts
  - Integration: retro-annotated P2-pause directives
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time

import pytest

# Ensure ystar package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ystar.governance.directive_evaluator import (
    Verdict,
    Directive,
    doc_exists,
    task_completed,
    file_mtime_after,
    git_commit_matches,
    obligation_closed,
    cieu_event_absent,
    manual_ack,
    fg_rule_is_expired,
    evaluate,
    load_directives_from_dir,
    evaluate_all,
    print_summary,
)


# ════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def doc_with_status(tmp_path):
    """Create a doc file with an L-tag."""
    doc = tmp_path / "test_doc.md"
    doc.write_text("# Test\n**Status**: [L2] REVIEWED\nSome content.\n")
    return str(doc)


@pytest.fixture
def doc_without_status(tmp_path):
    """Create a doc file without an L-tag."""
    doc = tmp_path / "no_status.md"
    doc.write_text("# Test\nNo status tag here.\n")
    return str(doc)


@pytest.fixture
def board_json(tmp_path):
    """Create a dispatch board with test tasks."""
    board = tmp_path / "dispatch_board.json"
    board.write_text(json.dumps({
        "tasks": [
            {
                "atomic_id": "CZL-TEST-1",
                "status": "completed",
                "completed_at": "2026-04-19T10:00:00Z",
                "scope": "test",
            },
            {
                "atomic_id": "CZL-TEST-2",
                "status": "claimed",
                "claimed_by": "eng-governance",
                "scope": "test",
            },
            {
                "atomic_id": "CZL-TEST-3",
                "status": "blocked",
                "blocked_on": "directive-X",
                "scope": "test",
            },
        ]
    }))
    return str(board)


@pytest.fixture
def cieu_db(tmp_path):
    """Create a CIEU events database with test events."""
    db_path = str(tmp_path / "test_cieu.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE cieu_events (
            event_id TEXT,
            seq_global INTEGER,
            created_at REAL,
            session_id TEXT,
            agent_id TEXT,
            event_type TEXT,
            decision TEXT,
            passed INTEGER,
            task_description TEXT,
            params_json TEXT
        )
    """)
    # Insert a recent event
    conn.execute("""
        INSERT INTO cieu_events (event_id, seq_global, created_at, session_id,
                                  agent_id, event_type, decision, passed, task_description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ("evt-1", 1, time.time() - 3600, "test", "system",
          "TEST_VIOLATION", "deny", 0, "test violation"))
    # Insert an old event (>48h ago)
    conn.execute("""
        INSERT INTO cieu_events (event_id, seq_global, created_at, session_id,
                                  agent_id, event_type, decision, passed, task_description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ("evt-2", 2, time.time() - 200000, "test", "system",
          "OLD_EVENT", "deny", 0, "old event"))
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def omission_db(tmp_path):
    """Create an omission DB with test obligations."""
    db_path = str(tmp_path / "test_omission.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE obligations (
            obligation_id TEXT PRIMARY KEY,
            status TEXT,
            created_at REAL
        )
    """)
    conn.execute("INSERT INTO obligations VALUES (?, ?, ?)",
                 ("OBL-CLOSED", "closed", time.time()))
    conn.execute("INSERT INTO obligations VALUES (?, ?, ?)",
                 ("OBL-PENDING", "pending", time.time()))
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def fg_rules_yaml(tmp_path):
    """Create a minimal ForgetGuard rules YAML."""
    rules_file = tmp_path / "forget_guard_rules.yaml"
    # Use an expired timestamp and a future timestamp
    expired_ts = int(time.time()) - 86400  # 1 day ago
    future_ts = int(time.time()) + 86400 * 7  # 7 days from now
    rules_file.write_text(f"""rules:
  - name: test_expired_rule
    pattern: "test"
    mode: warn
    dry_run_until: {expired_ts}
    created_at: "2026-04-01T00:00:00Z"

  - name: test_active_rule
    pattern: "test"
    mode: warn
    dry_run_until: {future_ts}
    created_at: "2026-04-01T00:00:00Z"

  - name: test_permanent_rule
    pattern: "test"
    mode: deny
    dry_run_until: null
    created_at: "2026-04-01T00:00:00Z"
""")
    return str(rules_file)


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: doc_exists
# ════════════════════════════════════════════════════════════════════════

class TestDocExists:
    def test_happy_no_status_check(self, doc_with_status):
        """Doc exists, no min_status requirement."""
        passed, evidence = doc_exists(doc_with_status, min_status="L0")
        assert passed is True
        assert "PASS" in evidence

    def test_happy_with_status_check(self, doc_with_status):
        """Doc exists at L2, min_status L1 required."""
        passed, evidence = doc_exists(doc_with_status, min_status="L1")
        assert passed is True

    def test_fail_status_too_low(self, doc_with_status):
        """Doc exists at L2, but L3 required."""
        passed, evidence = doc_exists(doc_with_status, min_status="L3")
        assert passed is False
        assert "L2" in evidence

    def test_fail_missing_doc(self, tmp_dir):
        """Doc does not exist."""
        passed, evidence = doc_exists("/nonexistent/doc.md")
        assert passed is False
        assert "not found" in evidence

    def test_fail_no_ltag(self, doc_without_status):
        """Doc exists but has no L-tag."""
        passed, evidence = doc_exists(doc_without_status, min_status="L1")
        assert passed is False
        assert "no L-tag" in evidence

    def test_relative_path_with_base_dir(self, tmp_path):
        """Relative path resolved against base_dirs."""
        (tmp_path / "docs").mkdir()
        doc = tmp_path / "docs" / "arch.md"
        doc.write_text("[L3] Architecture\n")
        passed, evidence = doc_exists("docs/arch.md", min_status="L1",
                                       base_dirs=[str(tmp_path)])
        assert passed is True


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: task_completed
# ════════════════════════════════════════════════════════════════════════

class TestTaskCompleted:
    def test_happy_completed(self, board_json):
        passed, evidence = task_completed("CZL-TEST-1", board_path=board_json)
        assert passed is True
        assert "completed" in evidence.lower()

    def test_fail_not_completed(self, board_json):
        passed, evidence = task_completed("CZL-TEST-2", board_path=board_json)
        assert passed is False
        assert "claimed" in evidence.lower()

    def test_fail_not_found(self, board_json):
        passed, evidence = task_completed("CZL-NONEXISTENT", board_path=board_json)
        assert passed is False
        assert "not found" in evidence.lower()

    def test_fail_no_board(self):
        passed, evidence = task_completed("CZL-X", board_path="/nonexistent/board.json")
        assert passed is False
        assert "not found" in evidence.lower()


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: file_mtime_after
# ════════════════════════════════════════════════════════════════════════

class TestFileMtimeAfter:
    def test_happy_recent_file(self, tmp_path):
        f = tmp_path / "recent.txt"
        f.write_text("hello")
        # File was just created, should be after 2020
        passed, evidence = file_mtime_after(str(f), "2020-01-01T00:00:00Z")
        assert passed is True

    def test_fail_old_timestamp(self, tmp_path):
        f = tmp_path / "old.txt"
        f.write_text("old")
        # Check against far future
        passed, evidence = file_mtime_after(str(f), "2099-01-01T00:00:00Z")
        assert passed is False

    def test_fail_missing_file(self):
        passed, evidence = file_mtime_after("/nonexistent/file.txt", "2020-01-01T00:00:00Z")
        assert passed is False
        assert "not found" in evidence.lower()


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: git_commit_matches
# ════════════════════════════════════════════════════════════════════════

class TestGitCommitMatches:
    def test_happy_match(self, tmp_path):
        """Create a temp git repo with a known commit, verify match."""
        repo = str(tmp_path / "testrepo")
        os.makedirs(repo)
        subprocess.run(["git", "init", repo], capture_output=True)
        subprocess.run(["git", "-C", repo, "config", "user.email", "test@test.com"],
                        capture_output=True)
        subprocess.run(["git", "-C", repo, "config", "user.name", "Test"],
                        capture_output=True)
        # Create a file and commit
        (tmp_path / "testrepo" / "test.txt").write_text("hello")
        subprocess.run(["git", "-C", repo, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", repo, "commit", "-m", "feat: add ARCH-17 spec"],
                        capture_output=True)

        passed, evidence = git_commit_matches(repo, r"ARCH-17")
        assert passed is True
        assert "PASS" in evidence

    def test_fail_no_match(self, tmp_path):
        """Repo exists but no matching commit."""
        repo = str(tmp_path / "testrepo2")
        os.makedirs(repo)
        subprocess.run(["git", "init", repo], capture_output=True)
        subprocess.run(["git", "-C", repo, "config", "user.email", "t@t.com"],
                        capture_output=True)
        subprocess.run(["git", "-C", repo, "config", "user.name", "T"],
                        capture_output=True)
        (tmp_path / "testrepo2" / "f.txt").write_text("x")
        subprocess.run(["git", "-C", repo, "add", "."], capture_output=True)
        subprocess.run(["git", "-C", repo, "commit", "-m", "initial"],
                        capture_output=True)

        passed, evidence = git_commit_matches(repo, r"NONEXISTENT-PATTERN-XYZ")
        assert passed is False

    def test_fail_no_repo(self):
        passed, evidence = git_commit_matches("/nonexistent/repo", r"test")
        assert passed is False
        assert "not found" in evidence.lower()


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: obligation_closed
# ════════════════════════════════════════════════════════════════════════

class TestObligationClosed:
    def test_happy_closed(self, omission_db):
        passed, evidence = obligation_closed("OBL-CLOSED", omission_db_path=omission_db)
        assert passed is True
        assert "closed" in evidence.lower()

    def test_fail_pending(self, omission_db):
        passed, evidence = obligation_closed("OBL-PENDING", omission_db_path=omission_db)
        assert passed is False
        assert "pending" in evidence.lower()

    def test_fail_not_found(self, omission_db):
        passed, evidence = obligation_closed("OBL-NONEXISTENT", omission_db_path=omission_db)
        assert passed is False
        assert "not found" in evidence.lower()

    def test_fail_no_db(self):
        passed, evidence = obligation_closed("OBL-X", omission_db_path="/nonexistent.db")
        assert passed is False


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: cieu_event_absent
# ════════════════════════════════════════════════════════════════════════

class TestCieuEventAbsent:
    def test_happy_absent(self, cieu_db):
        """Event type not present in DB."""
        passed, evidence = cieu_event_absent("NONEXISTENT_EVENT", hours=24, cieu_db_path=cieu_db)
        assert passed is True

    def test_fail_present(self, cieu_db):
        """TEST_VIOLATION event occurred in last 24h."""
        passed, evidence = cieu_event_absent("TEST_VIOLATION", hours=24, cieu_db_path=cieu_db)
        assert passed is False
        assert "1" in evidence

    def test_happy_old_event_outside_window(self, cieu_db):
        """OLD_EVENT happened >48h ago, checking 24h window should show absent."""
        passed, evidence = cieu_event_absent("OLD_EVENT", hours=24, cieu_db_path=cieu_db)
        assert passed is True

    def test_no_db_is_absent(self):
        """No DB at all = event trivially absent."""
        passed, evidence = cieu_event_absent("ANY", hours=24, cieu_db_path="/nonexistent.db")
        assert passed is True


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: manual_ack
# ════════════════════════════════════════════════════════════════════════

class TestManualAck:
    def test_happy_acked(self):
        directive = {
            "evaluator": {
                "manual_ack": {
                    "acked_by": "Board",
                    "note": "Approved",
                    "acked_at": "2026-04-19T12:00:00Z",
                }
            }
        }
        passed, evidence = manual_ack("Board", directive_data=directive)
        assert passed is True

    def test_fail_wrong_acker(self):
        directive = {
            "evaluator": {
                "manual_ack": {"acked_by": "CTO"}
            }
        }
        passed, evidence = manual_ack("Board", directive_data=directive)
        assert passed is False
        assert "CTO" in evidence

    def test_fail_no_ack(self):
        directive = {"evaluator": {}}
        passed, evidence = manual_ack("Board", directive_data=directive)
        assert passed is False

    def test_fail_no_data(self):
        passed, evidence = manual_ack("Board")
        assert passed is False


# ════════════════════════════════════════════════════════════════════════
# Primitive Tests: fg_rule_is_expired
# ════════════════════════════════════════════════════════════════════════

class TestFgRuleIsExpired:
    def test_happy_expired(self, fg_rules_yaml):
        passed, evidence = fg_rule_is_expired("test_expired_rule",
                                                rules_yaml_path=fg_rules_yaml)
        assert passed is True
        assert "PASS" in evidence

    def test_fail_still_active(self, fg_rules_yaml):
        passed, evidence = fg_rule_is_expired("test_active_rule",
                                                rules_yaml_path=fg_rules_yaml)
        assert passed is False
        assert "remaining" in evidence.lower()

    def test_fail_permanent_rule(self, fg_rules_yaml):
        """Permanent rules (dry_run_until=null) should return False."""
        passed, evidence = fg_rule_is_expired("test_permanent_rule",
                                                rules_yaml_path=fg_rules_yaml)
        assert passed is False
        assert "permanent" in evidence.lower() or "no dry_run_until" in evidence.lower()

    def test_fail_rule_not_found(self, fg_rules_yaml):
        passed, evidence = fg_rule_is_expired("nonexistent_rule",
                                                rules_yaml_path=fg_rules_yaml)
        assert passed is False

    def test_fail_no_yaml(self):
        passed, evidence = fg_rule_is_expired("test", rules_yaml_path="/nonexistent.yaml")
        assert passed is False


# ════════════════════════════════════════════════════════════════════════
# Integration Tests: evaluate()
# ════════════════════════════════════════════════════════════════════════

class TestEvaluate:
    def test_released_when_release_met(self, board_json):
        """Directive released when release.check passes."""
        directive = {
            "directive_id": "TEST-RELEASE",
            "trigger": {"current_state": "present"},
            "release": {
                "current_state": "unmet",
                "check": {
                    "type": "task_completed",
                    "atomic_id": "CZL-TEST-1",
                },
            },
        }
        verdict, evidence = evaluate(directive, board_path=board_json)
        assert verdict == Verdict.RELEASED

    def test_live_when_release_unmet(self, board_json):
        """Directive LIVE when release.check fails."""
        directive = {
            "directive_id": "TEST-LIVE",
            "trigger": {"current_state": "present"},
            "release": {
                "current_state": "unmet",
                "check": {
                    "type": "task_completed",
                    "atomic_id": "CZL-TEST-2",
                },
            },
        }
        verdict, evidence = evaluate(directive, board_path=board_json)
        assert verdict == Verdict.LIVE

    def test_released_pre_marked(self):
        """Directive marked as released in release.current_state."""
        directive = {
            "directive_id": "TEST-PREMARKED",
            "trigger": {"current_state": "present"},
            "release": {"current_state": "met"},
        }
        verdict, evidence = evaluate(directive)
        assert verdict == Verdict.RELEASED

    def test_ambiguous_no_checks(self):
        """Directive with no checks at all."""
        directive = {
            "directive_id": "TEST-AMBIGUOUS",
            "trigger": {},
            "release": {},
        }
        verdict, evidence = evaluate(directive)
        assert verdict == Verdict.AMBIGUOUS

    def test_live_with_doc_exists_release(self, tmp_path):
        """Directive where release depends on a doc that does not exist."""
        directive = {
            "directive_id": "TEST-DOC",
            "trigger": {"current_state": "present"},
            "release": {
                "check": {
                    "type": "doc_exists",
                    "path": "/nonexistent/doc.md",
                    "min_status": "L1",
                },
            },
        }
        verdict, evidence = evaluate(directive)
        assert verdict == Verdict.LIVE


# ════════════════════════════════════════════════════════════════════════
# Integration Tests: load + evaluate_all
# ════════════════════════════════════════════════════════════════════════

class TestEvaluateAll:
    def test_load_and_evaluate(self, tmp_path, board_json):
        """Load directives from directory and evaluate all."""
        directives_dir = tmp_path / "directives"
        directives_dir.mkdir()

        # Write a RELEASED directive
        (directives_dir / "released.json").write_text(json.dumps({
            "directive_id": "DIR-RELEASED",
            "issued_at": "2026-04-18T00:00:00Z",
            "issued_by": "Board",
            "trigger": {"current_state": "present"},
            "release": {"current_state": "met"},
            "scope": {"covers": ["test"]},
            "evaluator": {},
        }))

        # Write a LIVE directive
        (directives_dir / "live.json").write_text(json.dumps({
            "directive_id": "DIR-LIVE",
            "issued_at": "2026-04-18T00:00:00Z",
            "issued_by": "Board",
            "trigger": {"current_state": "present"},
            "release": {"current_state": "unmet"},
            "scope": {"covers": ["test"]},
            "evaluator": {},
        }))

        results = evaluate_all(str(directives_dir))
        assert len(results) == 2

        verdicts = {r["directive_id"]: r["verdict"] for r in results}
        assert verdicts["DIR-RELEASED"] == "RELEASED"
        assert verdicts["DIR-LIVE"] == "LIVE"

    def test_empty_dir(self, tmp_path):
        """Empty directory returns no results."""
        d = tmp_path / "empty"
        d.mkdir()
        results = evaluate_all(str(d))
        assert results == []

    def test_nonexistent_dir(self):
        """Nonexistent directory returns no results."""
        results = evaluate_all("/nonexistent/dir")
        assert results == []


# ════════════════════════════════════════════════════════════════════════
# Integration Test: print_summary
# ════════════════════════════════════════════════════════════════════════

class TestPrintSummary:
    def test_summary_output(self, capsys):
        results = [
            {"directive_id": "A", "verdict": "LIVE", "evidence": []},
            {"directive_id": "B", "verdict": "RELEASED", "evidence": []},
            {"directive_id": "C", "verdict": "AMBIGUOUS", "evidence": []},
        ]
        counts = print_summary(results)
        assert counts == {"LIVE": 1, "RELEASED": 1, "AMBIGUOUS": 1}
        captured = capsys.readouterr()
        assert "3 directives evaluated" in captured.out
        assert "LIVE=1" in captured.out


# ════════════════════════════════════════════════════════════════════════
# Directive dataclass tests
# ════════════════════════════════════════════════════════════════════════

class TestDirectiveDataclass:
    def test_from_dict_and_to_dict(self):
        data = {
            "directive_id": "CZL-P2-PAUSE",
            "issued_at": "2026-04-18T22:00:00Z",
            "issued_by": "Board",
            "trigger": {"statement": "test"},
            "release": {"statement": "test"},
            "scope": {"covers": ["a", "b"]},
            "evaluator": {"verdict": "LIVE"},
        }
        d = Directive.from_dict(data)
        assert d.directive_id == "CZL-P2-PAUSE"
        assert d.issued_by == "Board"

        roundtrip = d.to_dict()
        assert roundtrip["directive_id"] == data["directive_id"]
        assert roundtrip["scope"]["covers"] == ["a", "b"]

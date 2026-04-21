"""
Tests for cieu_decision_normalizer.py (v3)

Covers every raw value from CEO spec Section 1 and CTO ruling Section 1,
plus edge cases (embedded JSON, whitespace, empty, None-like).

v2 additions:
  - escape bucket tests (warn+passed=0, allow+passed=0)
  - passed-aware normalization tests
  - v1 backwards compatibility (passed=None)
  - training_eligible migration tests

v3 additions:
  - route bucket tests (split from rewrite per CZL-REWRITE-AUDIT)
  - migration 003 re-canonicalization tests
  - boundary cases for route vs rewrite distinction

Target: >= 80 test cases per Board 2026-04-19 directive.

Author: Leo Chen (eng-kernel)
Date: 2026-04-19
Updated: 2026-04-19 (v3: route bucket split from rewrite)
"""

import sqlite3
import tempfile

import pytest

from ystar.governance.cieu_decision_normalizer import (
    CANONICAL_VALUES,
    normalize,
    provenance_for_agent,
)


# ── CANONICAL_VALUES invariant ──────────────────────────────────────

class TestCanonicalValues:
    def test_exactly_eight_canonical_values(self):
        assert len(CANONICAL_VALUES) == 8

    def test_expected_members(self):
        assert CANONICAL_VALUES == frozenset({
            "allow", "deny", "escalate", "rewrite", "route", "info", "unknown", "escape",
        })

    def test_route_in_canonical(self):
        """route is a first-class canonical value (v3)."""
        assert "route" in CANONICAL_VALUES

    def test_immutable(self):
        with pytest.raises(AttributeError):
            CANONICAL_VALUES.add("new_value")  # type: ignore[attr-defined]

    def test_escape_in_canonical(self):
        """escape is a first-class canonical value."""
        assert "escape" in CANONICAL_VALUES


# ── normalize() — allow bucket (no passed / passed=1) ─────────────

class TestNormalizeAllow:
    def test_allow_lowercase(self):
        assert normalize("allow") == "allow"

    def test_allow_uppercase(self):
        assert normalize("ALLOW") == "allow"

    def test_allow_mixed_case(self):
        assert normalize("Allow") == "allow"

    def test_accept_maps_to_allow(self):
        assert normalize("accept") == "allow"

    def test_approved_maps_to_allow(self):
        assert normalize("approved") == "allow"

    def test_pass_maps_to_allow(self):
        assert normalize("pass") == "allow"

    def test_passed_maps_to_allow(self):
        assert normalize("passed") == "allow"

    def test_allow_with_passed_1(self):
        """allow + passed=1 stays allow."""
        assert normalize("allow", passed=1) == "allow"

    def test_accept_with_passed_1(self):
        assert normalize("accept", passed=1) == "allow"

    def test_approved_with_passed_1(self):
        assert normalize("approved", passed=1) == "allow"


# ── normalize() — deny bucket ──────────────────────────────────────

class TestNormalizeDeny:
    def test_deny(self):
        assert normalize("deny") == "deny"

    def test_reject(self):
        assert normalize("reject") == "deny"

    def test_blocked(self):
        assert normalize("blocked") == "deny"

    def test_denied(self):
        assert normalize("denied") == "deny"

    def test_deny_with_passed_0(self):
        """deny + passed=0 stays deny (deny is already a negative outcome)."""
        assert normalize("deny", passed=0) == "deny"

    def test_deny_with_passed_1(self):
        """deny + passed=1 stays deny (deny semantics dominate)."""
        assert normalize("deny", passed=1) == "deny"


# ── normalize() — escalate bucket ──────────────────────────────────

class TestNormalizeEscalate:
    def test_escalate(self):
        assert normalize("escalate") == "escalate"

    def test_escalate_with_passed_0(self):
        assert normalize("escalate", passed=0) == "escalate"

    def test_escalate_with_passed_1(self):
        assert normalize("escalate", passed=1) == "escalate"

    def test_warn_no_passed_v1_compat(self):
        """v1 backwards compatibility: warn without passed -> escalate."""
        assert normalize("warn") == "escalate"

    def test_warning_no_passed_v1_compat(self):
        """v1 backwards compatibility: warning without passed -> escalate."""
        assert normalize("warning") == "escalate"

    def test_warn_passed_none_v1_compat(self):
        """Explicit passed=None -> escalate (v1 compat)."""
        assert normalize("warn", passed=None) == "escalate"


# ── normalize() — escape bucket (NEW in v2) ────────────────────────

class TestNormalizeEscape:
    """Board 2026-04-19 Finding 1: warn+passed=0 = escape, not escalate."""

    def test_warn_passed_0_is_escape(self):
        """Core finding: warn + passed=0 -> escape."""
        assert normalize("warn", passed=0) == "escape"

    def test_warning_passed_0_is_escape(self):
        assert normalize("warning", passed=0) == "escape"

    def test_warn_uppercase_passed_0(self):
        assert normalize("WARN", passed=0) == "escape"

    def test_warning_mixed_case_passed_0(self):
        assert normalize("Warning", passed=0) == "escape"

    def test_warn_whitespace_passed_0(self):
        assert normalize("  warn  ", passed=0) == "escape"

    def test_warning_whitespace_passed_0(self):
        assert normalize("  Warning  ", passed=0) == "escape"

    def test_warn_passed_1_is_allow(self):
        """warn + passed=1 -> allow (warned but passed check)."""
        assert normalize("warn", passed=1) == "allow"

    def test_warning_passed_1_is_allow(self):
        assert normalize("warning", passed=1) == "allow"

    def test_allow_passed_0_is_escape(self):
        """Rare: allow + passed=0 -> escape."""
        assert normalize("allow", passed=0) == "escape"

    def test_accept_passed_0_is_escape(self):
        assert normalize("accept", passed=0) == "escape"

    def test_approved_passed_0_is_escape(self):
        assert normalize("approved", passed=0) == "escape"

    def test_pass_passed_0_is_escape(self):
        assert normalize("pass", passed=0) == "escape"

    def test_passed_passed_0_is_escape(self):
        assert normalize("passed", passed=0) == "escape"

    def test_allow_uppercase_passed_0(self):
        assert normalize("ALLOW", passed=0) == "escape"


# ── normalize() — rewrite bucket ───────────────────────────────────

class TestNormalizeRewrite:
    """rewrite bucket: only corrective rewrites (auto_rewrite.py transforms)."""

    def test_rewrite(self):
        assert normalize("rewrite") == "rewrite"

    def test_rewrite_uppercase(self):
        assert normalize("REWRITE") == "rewrite"

    def test_rewrite_mixed_case(self):
        assert normalize("Rewrite") == "rewrite"

    def test_rewrite_with_whitespace(self):
        assert normalize("  rewrite  ") == "rewrite"

    def test_rewrite_with_passed_0(self):
        """rewrite + passed=0 stays rewrite (not escape -- rewrite is not in allow family)."""
        assert normalize("rewrite", passed=0) == "rewrite"

    def test_rewrite_with_passed_1(self):
        assert normalize("rewrite", passed=1) == "rewrite"

    def test_route_no_longer_maps_to_rewrite(self):
        """v3: route maps to route, NOT rewrite."""
        assert normalize("route") != "rewrite"

    def test_dispatch_no_longer_maps_to_rewrite(self):
        """v3: dispatch maps to route, NOT rewrite."""
        assert normalize("dispatch") != "rewrite"


# ── normalize() — route bucket (NEW in v3) ─────────────────────────

class TestNormalizeRoute:
    """v3: route/dispatch split out of rewrite per CZL-REWRITE-AUDIT."""

    def test_route_maps_to_route(self):
        assert normalize("route") == "route"

    def test_dispatch_maps_to_route(self):
        assert normalize("dispatch") == "route"

    def test_route_uppercase(self):
        assert normalize("ROUTE") == "route"

    def test_dispatch_uppercase(self):
        assert normalize("DISPATCH") == "route"

    def test_route_mixed_case(self):
        assert normalize("Route") == "route"

    def test_dispatch_mixed_case(self):
        assert normalize("Dispatch") == "route"

    def test_route_with_whitespace(self):
        assert normalize("  route  ") == "route"

    def test_dispatch_with_whitespace(self):
        assert normalize("  dispatch  ") == "route"

    def test_route_with_passed_0(self):
        """route + passed=0 stays route (not escape -- route is not in allow family)."""
        assert normalize("route", passed=0) == "route"

    def test_route_with_passed_1(self):
        assert normalize("route", passed=1) == "route"

    def test_route_with_passed_none(self):
        """route + passed=None stays route (not passed-dependent)."""
        assert normalize("route", passed=None) == "route"

    def test_dispatch_with_passed_0(self):
        assert normalize("dispatch", passed=0) == "route"


# ── normalize() — info bucket ──────────────────────────────────────

class TestNormalizeInfo:
    def test_info(self):
        assert normalize("info") == "info"

    def test_complete(self):
        assert normalize("complete") == "info"

    def test_log(self):
        assert normalize("log") == "info"


# ── normalize() — unknown bucket ───────────────────────────────────

class TestNormalizeUnknown:
    def test_unknown(self):
        assert normalize("unknown") == "unknown"

    def test_error(self):
        assert normalize("error") == "unknown"

    def test_partial(self):
        assert normalize("partial") == "unknown"


# ── normalize() — edge cases ───────────────────────────────────────

class TestNormalizeEdgeCases:
    def test_embedded_json_object(self):
        """Embedded JSON fragments (corruption) map to unknown."""
        raw = '{"last_cieu_age_secs": -10284, "recent_event_count": 2}'
        assert normalize(raw) == "unknown"

    def test_embedded_json_array(self):
        raw = '["some", "garbage"]'
        assert normalize(raw) == "unknown"

    def test_embedded_json_with_passed(self):
        """JSON corruption maps to unknown regardless of passed."""
        raw = '{"corrupt": true}'
        assert normalize(raw, passed=0) == "unknown"
        assert normalize(raw, passed=1) == "unknown"

    def test_whitespace_padding(self):
        assert normalize("   allow   ") == "allow"

    def test_whitespace_with_case(self):
        assert normalize("  Warning  ") == "escalate"  # no passed -> v1 compat

    def test_whitespace_with_case_and_passed_0(self):
        assert normalize("  Warning  ", passed=0) == "escape"

    def test_empty_string(self):
        assert normalize("") == "unknown"

    def test_whitespace_only(self):
        assert normalize("   ") == "unknown"

    def test_unrecognized_value(self):
        """Totally novel values map to unknown."""
        assert normalize("banana") == "unknown"

    def test_numeric_string(self):
        assert normalize("42") == "unknown"

    def test_output_always_in_canonical_set(self):
        """Ensure every possible output is in CANONICAL_VALUES for all passed combos."""
        test_inputs = [
            "allow", "ALLOW", "accept", "approved", "pass", "passed",
            "deny", "reject", "blocked", "denied",
            "escalate", "warn", "warning",
            "rewrite", "route", "dispatch",
            "info", "complete", "log",
            "unknown", "error", "partial",
            "", "   ", "banana", "42",
            '{"json": true}', '["array"]',
        ]
        for passed in (None, 0, 1):
            for raw in test_inputs:
                result = normalize(raw, passed=passed)
                assert result in CANONICAL_VALUES, (
                    f"normalize({raw!r}, passed={passed}) returned {result!r} "
                    f"which is not in CANONICAL_VALUES"
                )


# ── provenance_for_agent() ─────────────────────────────────────────

class TestProvenanceForAgent:
    def test_system_k9_subscriber(self):
        assert provenance_for_agent("system:k9_subscriber") == "system:brain"

    def test_system_brain(self):
        assert provenance_for_agent("system:brain") == "system:brain"

    def test_system_orchestrator(self):
        assert provenance_for_agent("system:orchestrator") == "system:brain"

    def test_regular_agent(self):
        assert provenance_for_agent("ceo") is None

    def test_engineer_agent(self):
        assert provenance_for_agent("eng-kernel") is None

    def test_empty_string(self):
        assert provenance_for_agent("") is None

    def test_none_like(self):
        assert provenance_for_agent("") is None


# ── Migration 002: training_eligible backfill ──────────────────────

class TestTrainingEligibleMigration:
    """Test migration 002 logic using an in-memory SQLite database."""

    @pytest.fixture
    def db(self):
        """Create an in-memory DB with cieu_events schema matching production.

        Note: production schema declares created_at as REAL (epoch seconds).
        Most rows are float epoch; a small minority are ISO text strings.
        """
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE cieu_events (
                rowid INTEGER PRIMARY KEY,
                created_at REAL,
                decision TEXT,
                passed INTEGER,
                agent_id TEXT,
                decision_canonical TEXT,
                provenance TEXT
            )
        """)
        return conn

    def _insert_event(self, conn, created_at, decision, passed, agent_id="ceo"):
        conn.execute(
            "INSERT INTO cieu_events (created_at, decision, passed, agent_id) "
            "VALUES (?, ?, ?, ?)",
            (created_at, decision, passed, agent_id),
        )

    def test_backfill_pre_hook_events_are_ineligible_epoch(self, db):
        """Events before 2026-04-16 05:07:20 (epoch) should be training_eligible=0."""
        # epoch for 2026-04-10 12:00:00 UTC and 2026-04-15 23:59:59 UTC
        self._insert_event(db, 1775851200.0, "allow", 1)
        self._insert_event(db, 1776287999.0, "allow", 1)

        db.execute(
            "ALTER TABLE cieu_events ADD COLUMN training_eligible INTEGER DEFAULT 0"
        )
        db.execute(
            "UPDATE cieu_events SET training_eligible = CASE "
            "  WHEN typeof(created_at) = 'real' AND created_at >= 1776316040.0 THEN 1 "
            "  WHEN typeof(created_at) = 'text' AND created_at >= '2026-04-16T05:07:20' THEN 1 "
            "  ELSE 0 "
            "END"
        )

        rows = db.execute(
            "SELECT training_eligible FROM cieu_events ORDER BY rowid"
        ).fetchall()
        assert rows == [(0,), (0,)]

    def test_backfill_post_hook_events_are_eligible_epoch(self, db):
        """Events at or after anchor (epoch) should be training_eligible=1."""
        # exact anchor and later
        self._insert_event(db, 1776316040.0, "allow", 1)
        self._insert_event(db, 1776500000.0, "deny", 0)

        db.execute(
            "ALTER TABLE cieu_events ADD COLUMN training_eligible INTEGER DEFAULT 0"
        )
        db.execute(
            "UPDATE cieu_events SET training_eligible = CASE "
            "  WHEN typeof(created_at) = 'real' AND created_at >= 1776316040.0 THEN 1 "
            "  WHEN typeof(created_at) = 'text' AND created_at >= '2026-04-16T05:07:20' THEN 1 "
            "  ELSE 0 "
            "END"
        )

        rows = db.execute(
            "SELECT training_eligible FROM cieu_events ORDER BY rowid"
        ).fetchall()
        assert rows == [(1,), (1,)]

    def test_backfill_mixed_pre_and_post_epoch(self, db):
        """Mixed timeline (epoch): pre-hook=0, post-hook=1."""
        self._insert_event(db, 1775750400.0, "allow", 1)     # 2026-04-09
        self._insert_event(db, 1776316039.0, "allow", 1)     # 1 second before anchor
        self._insert_event(db, 1776316040.0, "allow", 1)     # exact anchor
        self._insert_event(db, 1776400000.0, "warn", 0)      # after anchor

        db.execute(
            "ALTER TABLE cieu_events ADD COLUMN training_eligible INTEGER DEFAULT 0"
        )
        db.execute(
            "UPDATE cieu_events SET training_eligible = CASE "
            "  WHEN typeof(created_at) = 'real' AND created_at >= 1776316040.0 THEN 1 "
            "  WHEN typeof(created_at) = 'text' AND created_at >= '2026-04-16T05:07:20' THEN 1 "
            "  ELSE 0 "
            "END"
        )

        rows = db.execute(
            "SELECT training_eligible FROM cieu_events ORDER BY rowid"
        ).fetchall()
        assert rows == [(0,), (0,), (1,), (1,)]

    def test_backfill_iso_text_format(self, db):
        """Handle ISO text format for created_at (minority of rows)."""
        # Insert as text instead of float
        db.execute(
            "INSERT INTO cieu_events (created_at, decision, passed, agent_id) "
            "VALUES (?, ?, ?, ?)",
            ("2026-04-10T12:00:00Z", "allow", 1, "ceo"),
        )
        db.execute(
            "INSERT INTO cieu_events (created_at, decision, passed, agent_id) "
            "VALUES (?, ?, ?, ?)",
            ("2026-04-19T16:07:18+00:00", "allow", 1, "ceo"),
        )

        db.execute(
            "ALTER TABLE cieu_events ADD COLUMN training_eligible INTEGER DEFAULT 0"
        )
        db.execute(
            "UPDATE cieu_events SET training_eligible = CASE "
            "  WHEN typeof(created_at) = 'real' AND created_at >= 1776316040.0 THEN 1 "
            "  WHEN typeof(created_at) = 'text' AND created_at >= '2026-04-16T05:07:20' THEN 1 "
            "  ELSE 0 "
            "END"
        )

        rows = db.execute(
            "SELECT training_eligible FROM cieu_events ORDER BY rowid"
        ).fetchall()
        assert rows == [(0,), (1,)]

    def test_renormalize_warn_escape(self, db):
        """Re-normalization converts warn+passed=0 from escalate to escape."""
        self._insert_event(db, "2026-04-17 12:00:00", "warn", 0)
        self._insert_event(db, "2026-04-17 12:00:01", "warn", 1)
        self._insert_event(db, "2026-04-17 12:00:02", "warning", 0)

        # Simulate v1 normalization (all warn -> escalate)
        db.execute("UPDATE cieu_events SET decision_canonical = 'escalate' WHERE decision IN ('warn', 'warning')")

        # Now re-normalize with v2
        distinct = db.execute("SELECT DISTINCT decision, passed FROM cieu_events").fetchall()
        for raw_val, passed_val in distinct:
            new_canonical = normalize(raw_val, passed=passed_val)
            db.execute(
                "UPDATE cieu_events SET decision_canonical = ? WHERE decision = ? AND passed = ?",
                (new_canonical, raw_val, passed_val),
            )

        rows = db.execute(
            "SELECT decision, passed, decision_canonical FROM cieu_events ORDER BY rowid"
        ).fetchall()
        assert rows[0] == ("warn", 0, "escape")
        assert rows[1] == ("warn", 1, "allow")
        assert rows[2] == ("warning", 0, "escape")

    def test_renormalize_allow_escape(self, db):
        """Re-normalization converts allow+passed=0 to escape."""
        self._insert_event(db, "2026-04-17 12:00:00", "allow", 0)
        self._insert_event(db, "2026-04-17 12:00:01", "allow", 1)

        # Simulate v1 normalization (all allow -> allow)
        db.execute("UPDATE cieu_events SET decision_canonical = 'allow'")

        # Re-normalize with v2
        distinct = db.execute("SELECT DISTINCT decision, passed FROM cieu_events").fetchall()
        for raw_val, passed_val in distinct:
            new_canonical = normalize(raw_val, passed=passed_val)
            db.execute(
                "UPDATE cieu_events SET decision_canonical = ? WHERE decision = ? AND passed = ?",
                (new_canonical, raw_val, passed_val),
            )

        rows = db.execute(
            "SELECT decision, passed, decision_canonical FROM cieu_events ORDER BY rowid"
        ).fetchall()
        assert rows[0] == ("allow", 0, "escape")
        assert rows[1] == ("allow", 1, "allow")

    def test_index_creation(self, db):
        """Composite index on (training_eligible, decision_canonical) works."""
        db.execute(
            "ALTER TABLE cieu_events ADD COLUMN training_eligible INTEGER DEFAULT 0"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_training_eligible_decision "
            "ON cieu_events(training_eligible, decision_canonical)"
        )
        # Verify index exists
        indexes = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='cieu_events'"
        ).fetchall()
        index_names = {row[0] for row in indexes}
        assert "idx_training_eligible_decision" in index_names


# ── Migration 003: route re-canonicalization ──────────────────────────

class TestRouteRecanonicalization:
    """Test migration 003 logic: split route/dispatch from rewrite canonical."""

    @pytest.fixture
    def db(self):
        """Create an in-memory DB with cieu_events matching production schema."""
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE cieu_events (
                rowid INTEGER PRIMARY KEY,
                created_at REAL,
                decision TEXT,
                passed INTEGER,
                agent_id TEXT,
                decision_canonical TEXT,
                provenance TEXT,
                event_type TEXT
            )
        """)
        return conn

    def _insert(self, conn, decision, decision_canonical, event_type="TEST", passed=1):
        conn.execute(
            "INSERT INTO cieu_events (created_at, decision, passed, agent_id, "
            "decision_canonical, event_type) VALUES (?, ?, ?, ?, ?, ?)",
            (1776500000.0, decision, passed, "agent", decision_canonical, event_type),
        )

    def test_route_migrated_from_rewrite_to_route(self, db):
        """route decision should be re-canonicalized from rewrite to route."""
        self._insert(db, "route", "rewrite", "ROUTING_GATE_CHECK")
        db.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        )
        row = db.execute(
            "SELECT decision_canonical FROM cieu_events"
        ).fetchone()
        assert row[0] == "route"

    def test_dispatch_migrated_from_rewrite_to_route(self, db):
        """dispatch decision should be re-canonicalized from rewrite to route."""
        self._insert(db, "dispatch", "rewrite", "CTO_BROKER")
        db.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        )
        row = db.execute(
            "SELECT decision_canonical FROM cieu_events"
        ).fetchone()
        assert row[0] == "route"

    def test_rewrite_decision_not_affected(self, db):
        """Events with decision='rewrite' should remain canonical rewrite."""
        self._insert(db, "rewrite", "rewrite", "REWRITE_APPLIED")
        db.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        )
        row = db.execute(
            "SELECT decision_canonical FROM cieu_events"
        ).fetchone()
        assert row[0] == "rewrite"

    def test_mixed_population_migration(self, db):
        """Migration correctly splits mixed route/rewrite/dispatch population."""
        # 7 real rewrites
        for _ in range(7):
            self._insert(db, "rewrite", "rewrite", "REWRITE_APPLIED")
        # 46 ROUTING_GATE_CHECK misclassified as rewrite
        for _ in range(46):
            self._insert(db, "route", "rewrite", "ROUTING_GATE_CHECK")
        # 3 CTO_BROKER dispatches misclassified as rewrite
        for _ in range(3):
            self._insert(db, "dispatch", "rewrite", "CTO_BROKER")

        # Pre-migration: all 56 are canonical rewrite
        pre_rewrite = db.execute(
            "SELECT COUNT(*) FROM cieu_events WHERE decision_canonical = 'rewrite'"
        ).fetchone()[0]
        assert pre_rewrite == 56

        # Run migration
        db.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        )

        # Post-migration: 7 rewrite, 49 route
        post_rewrite = db.execute(
            "SELECT COUNT(*) FROM cieu_events WHERE decision_canonical = 'rewrite'"
        ).fetchone()[0]
        post_route = db.execute(
            "SELECT COUNT(*) FROM cieu_events WHERE decision_canonical = 'route'"
        ).fetchone()[0]
        assert post_rewrite == 7
        assert post_route == 49

    def test_other_canonical_values_unchanged(self, db):
        """Migration does not touch events with non-rewrite canonical values."""
        self._insert(db, "allow", "allow")
        self._insert(db, "deny", "deny")
        self._insert(db, "warn", "escape", passed=0)
        self._insert(db, "route", "rewrite", "ROUTING_GATE_CHECK")

        db.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        )

        rows = db.execute(
            "SELECT decision, decision_canonical FROM cieu_events ORDER BY rowid"
        ).fetchall()
        assert rows[0] == ("allow", "allow")
        assert rows[1] == ("deny", "deny")
        assert rows[2] == ("warn", "escape")
        assert rows[3] == ("route", "route")

    def test_idempotent_double_migration(self, db):
        """Running migration twice produces same result."""
        self._insert(db, "route", "rewrite")
        self._insert(db, "dispatch", "rewrite")
        self._insert(db, "rewrite", "rewrite")

        # First run
        db.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        )
        after_first = db.execute(
            "SELECT decision, decision_canonical FROM cieu_events ORDER BY rowid"
        ).fetchall()

        # Second run (idempotent)
        db.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        )
        after_second = db.execute(
            "SELECT decision, decision_canonical FROM cieu_events ORDER BY rowid"
        ).fetchall()

        assert after_first == after_second
        assert after_second[0] == ("route", "route")
        assert after_second[1] == ("dispatch", "route")
        assert after_second[2] == ("rewrite", "rewrite")

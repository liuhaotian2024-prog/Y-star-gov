"""
E2E tests for Y*gov CausalChainAnalyzer
"""
import pytest
import sqlite3
import tempfile
from pathlib import Path
from ystar.governance.causal_chain_analyzer import CausalChainAnalyzer


@pytest.fixture
def sample_db():
    """Create a temporary CIEU DB with sample events."""
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = db_file.name
    db_file.close()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create cieu_events table (minimal schema)
    cursor.execute("""
        CREATE TABLE cieu_events (
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
            drift_details TEXT,
            task_description TEXT
        )
    """)

    # Insert sample events
    events = [
        ("evt_1", 1000, 1000.0, "session_1", "ceo", "TASK_DISPATCH", "allow", 1, "[]", "", "Dispatch to CTO"),
        ("evt_2", 2000, 2000.0, "session_1", "cto", "WRITE_ALLOW", "allow", 1, "[]", "", "Write code"),
        ("evt_3", 3000, 3000.0, "session_1", "cto", "WRITE_DENY", "deny", 0, '[{"severity": 0.8}]', "scope violation", "Write to CEO scope"),
        ("evt_4", 4000, 4000.0, "session_1", "cto", "FALLBACK", "allow", 1, "[]", "", "Fallback action"),
        ("evt_5", 5000, 5000.0, "session_1", "ceo", "FORGETGUARD_DENY", "deny", 0, '[{"severity": 0.9}]', "missing context", "Forgot task card"),
    ]
    cursor.executemany("""
        INSERT INTO cieu_events
        (event_id, seq_global, created_at, session_id, agent_id, event_type, decision, passed, violations, drift_details, task_description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, events)

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    Path(db_path).unlink()


def test_trace_event_basic(sample_db):
    """Test basic event tracing."""
    analyzer = CausalChainAnalyzer(sample_db)

    # Trace target event (evt_3, WRITE_DENY)
    chain = analyzer.trace_event("evt_3", lookback=5, lookahead=5)

    assert "event" in chain
    assert chain["event"]["event_id"] == "evt_3"
    assert chain["event"]["event_type"] == "WRITE_DENY"

    # Should have 2 predecessors (evt_1, evt_2)
    assert len(chain["predecessors"]) == 2
    assert chain["predecessors"][0]["event_id"] == "evt_1"
    assert chain["predecessors"][1]["event_id"] == "evt_2"

    # Should have 2 successors (evt_4, evt_5)
    assert len(chain["successors"]) == 2
    assert chain["successors"][0]["event_id"] == "evt_4"
    assert chain["successors"][1]["event_id"] == "evt_5"

    # Metadata
    assert chain["metadata"]["chain_length"] == 5  # 2 pred + 1 target + 2 succ
    assert chain["metadata"]["violations_in_chain"] == 2  # evt_3 and evt_5

    analyzer.close()


def test_find_root_causes(sample_db):
    """Test root cause analysis."""
    analyzer = CausalChainAnalyzer(sample_db)

    # Root causes for evt_5 (FORGETGUARD_DENY)
    root_causes = analyzer.find_root_causes("evt_5")

    assert len(root_causes) > 0

    # Should identify evt_3 (WRITE_DENY) as earliest violation
    earliest = next((rc for rc in root_causes if rc["type"] == "earliest_violation"), None)
    assert earliest is not None
    assert earliest["event_id"] == "evt_3"
    assert earliest["confidence"] == 0.9

    # Should identify high-severity violation (evt_3 has severity 0.8)
    high_sev = next((rc for rc in root_causes if rc["type"] == "high_severity_violation"), None)
    assert high_sev is not None
    assert high_sev["event_id"] == "evt_3"

    analyzer.close()


def test_visualize_chain(sample_db):
    """Test chain visualization."""
    analyzer = CausalChainAnalyzer(sample_db)

    viz = analyzer.visualize_chain("evt_3")

    assert "CAUSAL CHAIN ANALYSIS" in viz
    assert "TARGET EVENT: evt_3" in viz
    assert "WRITE_DENY" in viz
    assert "PREDECESSORS" in viz
    assert "SUCCESSORS" in viz
    assert "ROOT CAUSES" in viz

    analyzer.close()


def test_trace_nonexistent_event(sample_db):
    """Test tracing a non-existent event."""
    analyzer = CausalChainAnalyzer(sample_db)

    chain = analyzer.trace_event("evt_999")

    assert "error" in chain
    assert "not found" in chain["error"]

    analyzer.close()


def test_context_manager(sample_db):
    """Test using analyzer as context manager."""
    with CausalChainAnalyzer(sample_db) as analyzer:
        chain = analyzer.trace_event("evt_3")
        assert chain["event"]["event_id"] == "evt_3"


def test_missing_db():
    """Test error handling for missing database."""
    with pytest.raises(FileNotFoundError):
        CausalChainAnalyzer("/nonexistent/path.db")


def test_chain_length_limits(sample_db):
    """Test lookback/lookahead limits."""
    analyzer = CausalChainAnalyzer(sample_db)

    # Trace with small lookback
    chain = analyzer.trace_event("evt_3", lookback=1, lookahead=1)

    assert len(chain["predecessors"]) == 1  # Only evt_2
    assert len(chain["successors"]) == 1    # Only evt_4

    analyzer.close()


def test_root_causes_for_non_violation(sample_db):
    """Test root cause analysis on a non-violation event."""
    analyzer = CausalChainAnalyzer(sample_db)

    # evt_2 is not a violation (passed=1)
    root_causes = analyzer.find_root_causes("evt_2")

    # Should return early with reasoning
    assert len(root_causes) == 1
    assert root_causes[0]["confidence"] == 0.0
    assert "not a violation" in root_causes[0]["reasoning"]

    analyzer.close()

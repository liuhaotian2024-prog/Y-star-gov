"""
Tests for Y*gov Memory Layer — Core CRUD operations.
"""

import time
import pytest
from ystar.memory import Memory, Agent, MemoryStore, InMemoryMemoryStore


def test_remember_and_recall_inmemory():
    """Test basic store/retrieve with in-memory store."""
    store = InMemoryMemoryStore()

    mem = Memory(
        agent_id="ceo",
        memory_type="decision",
        content="Chose SQLite over PostgreSQL for memory layer",
        context_tags=["architecture", "database"],
        half_life_days=90.0
    )

    mem_id = store.remember(mem)
    assert mem_id == mem.memory_id

    results = store.recall(agent_id="ceo", min_relevance=0.0)
    assert len(results) == 1
    assert results[0].content == mem.content


def test_remember_and_recall_sqlite(tmp_path):
    """Test basic store/retrieve with SQLite store."""
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path=str(db_path))

    mem = Memory(
        agent_id="cto",
        memory_type="knowledge",
        content="pytest must pass 100% before commit",
        context_tags=["testing", "git"],
        half_life_days=60.0
    )

    mem_id = store.remember(mem)
    assert mem_id == mem.memory_id

    results = store.recall(agent_id="cto", min_relevance=0.0)
    assert len(results) == 1
    assert results[0].content == mem.content
    assert results[0].access_count == 1  # Incremented on recall


def test_relevance_decay_inmemory():
    """Test that relevance decays over time (in-memory)."""
    store = InMemoryMemoryStore()

    # Create memory with recent timestamp
    now = time.time()
    mem = Memory(
        agent_id="ceo",
        memory_type="task_context",
        content="Working on bug in prefill.py",
        created_at=now - (7 * 86400),  # 7 days ago
        half_life_days=7.0,  # 50% decay after 7 days
        initial_score=1.0,
        min_score=0.1
    )

    store.remember(mem)

    # Relevance should be ~0.5 after 7 days
    relevance = mem.compute_relevance(now)
    assert 0.45 < relevance < 0.55

    # After 14 days, should be ~0.25
    relevance_14d = mem.compute_relevance(now + (7 * 86400))
    assert 0.20 < relevance_14d < 0.30


def test_relevance_filtering():
    """Test that recall filters by min_relevance."""
    store = InMemoryMemoryStore()

    now = time.time()

    # Fresh memory (relevance = 1.0)
    fresh = Memory(
        agent_id="ceo",
        memory_type="decision",
        content="Fresh decision",
        created_at=now,
        half_life_days=30.0
    )

    # Old memory (relevance < 0.3)
    old = Memory(
        agent_id="ceo",
        memory_type="decision",
        content="Old decision",
        created_at=now - (90 * 86400),  # 90 days ago
        half_life_days=30.0  # Will be heavily decayed
    )

    store.remember(fresh)
    store.remember(old)

    # Recall with min_relevance=0.3 should only return fresh
    results = store.recall(agent_id="ceo", min_relevance=0.3)
    assert len(results) == 1
    assert results[0].content == "Fresh decision"


def test_decay_scan_inmemory():
    """Test decay_scan prunes old memories."""
    store = InMemoryMemoryStore()

    now = time.time()

    # Fresh memory (should survive)
    fresh = Memory(
        agent_id="ceo",
        memory_type="knowledge",
        content="Fresh knowledge",
        created_at=now,
        half_life_days=30.0
    )

    # Very old memory (should be pruned)
    old = Memory(
        agent_id="ceo",
        memory_type="task_context",
        content="Old context",
        created_at=now - (365 * 86400),  # 1 year ago
        half_life_days=7.0,
        min_score=0.05  # Lower than prune threshold
    )

    store.remember(fresh)
    store.remember(old)

    # Run decay scan with prune_threshold=0.1
    scanned, pruned = store.decay_scan(prune_threshold=0.1)
    assert scanned == 2
    assert pruned == 1

    # Only fresh memory should remain
    results = store.recall(agent_id="ceo", min_relevance=0.0)
    assert len(results) == 1
    assert results[0].content == "Fresh knowledge"


def test_forget():
    """Test explicit memory deletion."""
    store = InMemoryMemoryStore()

    mem = Memory(
        agent_id="ceo",
        memory_type="decision",
        content="Test decision"
    )

    mem_id = store.remember(mem)
    assert len(store.memories) == 1

    success = store.forget(mem_id, reason="Superseded by new decision")
    assert success
    assert len(store.memories) == 0


def test_reinforce():
    """Test memory reinforcement."""
    store = InMemoryMemoryStore()

    mem = Memory(
        agent_id="ceo",
        memory_type="lesson",
        content="Always verify before fabricating data",
        initial_score=0.5
    )

    mem_id = store.remember(mem)

    # Reinforce by 20%
    success = store.reinforce(mem_id, boost_factor=1.2)
    assert success

    # Check that initial_score was boosted
    retrieved = store.recall(agent_id="ceo", min_relevance=0.0)[0]
    assert retrieved.initial_score == 0.6  # 0.5 * 1.2


def test_agent_summary():
    """Test agent memory health report."""
    store = InMemoryMemoryStore()

    now = time.time()

    # Add various memories
    for i in range(5):
        mem = Memory(
            agent_id="ceo",
            memory_type="knowledge",
            content=f"Knowledge {i}",
            created_at=now - (i * 10 * 86400),  # Varying ages
            half_life_days=30.0
        )
        store.remember(mem)

    summary = store.get_agent_summary("ceo")
    assert summary["agent_id"] == "ceo"
    assert summary["total_memories"] == 5
    assert summary["active_memories"] > 0
    assert summary["usage_mb"] >= 0  # May be very small, >= 0 is sufficient


def test_memory_type_filtering():
    """Test recall filtering by memory_type."""
    store = InMemoryMemoryStore()

    mem1 = Memory(agent_id="ceo", memory_type="decision", content="Decision 1")
    mem2 = Memory(agent_id="ceo", memory_type="knowledge", content="Knowledge 1")
    mem3 = Memory(agent_id="ceo", memory_type="decision", content="Decision 2")

    store.remember(mem1)
    store.remember(mem2)
    store.remember(mem3)

    results = store.recall(agent_id="ceo", memory_types=["decision"], min_relevance=0.0)
    assert len(results) == 2
    assert all(m.memory_type == "decision" for m in results)


def test_context_tags_filtering():
    """Test recall filtering by context_tags."""
    store = InMemoryMemoryStore()

    mem1 = Memory(agent_id="ceo", memory_type="knowledge", content="Git knowledge", context_tags=["git", "testing"])
    mem2 = Memory(agent_id="ceo", memory_type="knowledge", content="DB knowledge", context_tags=["database"])
    mem3 = Memory(agent_id="ceo", memory_type="knowledge", content="Testing knowledge", context_tags=["testing"])

    store.remember(mem1)
    store.remember(mem2)
    store.remember(mem3)

    results = store.recall(agent_id="ceo", context_tags=["testing"], min_relevance=0.0)
    assert len(results) == 2
    assert all("testing" in m.context_tags for m in results)


def test_access_count_increments():
    """Test that access_count increments on recall."""
    store = InMemoryMemoryStore()

    mem = Memory(agent_id="ceo", memory_type="knowledge", content="Test")
    store.remember(mem)

    # Access multiple times
    for _ in range(3):
        store.recall(agent_id="ceo", min_relevance=0.0)

    results = store.recall(agent_id="ceo", min_relevance=0.0)
    assert results[0].access_count == 4  # 3 + 1 (current recall)


def test_sort_by_relevance():
    """Test sorting by relevance (descending)."""
    store = InMemoryMemoryStore()

    now = time.time()

    mem1 = Memory(agent_id="ceo", content="Old", created_at=now - (60 * 86400), half_life_days=30.0)
    mem2 = Memory(agent_id="ceo", content="Fresh", created_at=now, half_life_days=30.0)
    mem3 = Memory(agent_id="ceo", content="Medium", created_at=now - (30 * 86400), half_life_days=30.0)

    store.remember(mem1)
    store.remember(mem2)
    store.remember(mem3)

    results = store.recall(agent_id="ceo", sort_by="relevance_desc", min_relevance=0.0)
    assert results[0].content == "Fresh"
    assert results[1].content == "Medium"
    assert results[2].content == "Old"


def test_board_mandate_initial_score_immutable(tmp_path):
    """
    Board mandate: initial_score is immutable after creation.
    decay_scan should NEVER update it.
    """
    db_path = tmp_path / "test_immutable.db"
    store = MemoryStore(db_path=str(db_path))

    now = time.time()
    mem = Memory(
        agent_id="ceo",
        memory_type="knowledge",
        content="Test immutability",
        created_at=now - (30 * 86400),  # 30 days ago
        initial_score=1.0,
        half_life_days=30.0
    )

    mem_id = store.remember(mem)

    # Run decay scan (should not modify initial_score)
    scanned, pruned = store.decay_scan(prune_threshold=0.05)

    # Retrieve memory and verify initial_score unchanged
    results = store.recall(agent_id="ceo", min_relevance=0.0)
    assert len(results) == 1
    assert results[0].initial_score == 1.0  # MUST be unchanged

    # Current relevance should be ~0.5 (computed dynamically)
    current_relevance = results[0].compute_relevance(now)
    assert 0.45 < current_relevance < 0.55


def test_board_mandate_decay_only_deletes(tmp_path):
    """
    Board mandate: decay_scan ONLY deletes memories below threshold.
    It does NOT update any score fields.
    """
    db_path = tmp_path / "test_decay_delete.db"
    store = MemoryStore(db_path=str(db_path))

    now = time.time()

    # Create memory that will decay below prune_threshold
    old = Memory(
        agent_id="ceo",
        memory_type="task_context",
        content="Should be pruned",
        created_at=now - (365 * 86400),  # 1 year ago
        half_life_days=7.0,
        initial_score=1.0,
        min_score=0.05  # Lower than prune_threshold so it can be pruned
    )

    store.remember(old)

    # Verify relevance is below threshold (will be floored at min_score=0.05)
    relevance_before = old.compute_relevance(now)
    assert relevance_before <= 0.05

    # Run decay scan with prune_threshold=0.1 (should delete memory with relevance 0.05)
    scanned, pruned = store.decay_scan(prune_threshold=0.1)
    assert scanned == 1
    assert pruned == 1

    # Memory should be deleted
    results = store.recall(agent_id="ceo", min_relevance=0.0)
    assert len(results) == 0

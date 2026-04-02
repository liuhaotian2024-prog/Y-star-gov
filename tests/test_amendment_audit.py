# Layer: Tests
"""
Tests for P2-5: Contract Amendment Audit Chain

Verifies that:
  - AmendmentRecord is created when constitution hash changes
  - Amendment history returns chronological records
  - No amendment record when hash is unchanged
"""
from __future__ import annotations

import time
import tempfile
import os

import pytest

from ystar.governance.amendment import AmendmentLog, AmendmentRecord
from ystar.kernel.contract_provider import ConstitutionProvider


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_constitution():
    """Create a temporary constitution file for testing."""
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.md',
        delete=False,
        encoding='utf-8'
    ) as f:
        f.write("# Test Constitution\n")
        f.write("## Obligations\n")
        f.write("- Agent must not lie\n")
        temp_path = f.name

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestAmendmentAudit:

    def test_amendment_record_created_on_hash_change(self, temp_constitution):
        """
        When constitution content changes, resolve() should create an AmendmentRecord.
        """
        provider = ConstitutionProvider()

        # First read - establishes baseline
        bundle1 = provider.resolve(temp_constitution)
        hash1 = bundle1.source_hash

        # No amendment yet (first read)
        history = provider.get_amendment_history(temp_constitution)
        assert len(history) == 0

        # Modify the constitution file
        with open(temp_constitution, 'w', encoding='utf-8') as f:
            f.write("# Test Constitution\n")
            f.write("## Obligations\n")
            f.write("- Agent must not lie\n")
            f.write("- Agent must not fabricate data\n")  # NEW LINE

        # Force re-read
        bundle2 = provider.resolve_latest(temp_constitution)
        hash2 = bundle2.source_hash

        # Hash should have changed
        assert hash1 != hash2

        # Amendment record should be created
        history = provider.get_amendment_history(temp_constitution)
        assert len(history) == 1

        record = history[0]
        assert record.source_ref == temp_constitution
        assert record.old_hash == hash1
        assert record.new_hash == hash2
        assert record.timestamp > 0
        assert record.amendment_id != ""

    def test_amendment_history_returns_chronological(self, temp_constitution):
        """
        Multiple amendments should be stored in chronological order.
        """
        provider = ConstitutionProvider()

        # First read
        provider.resolve(temp_constitution)

        # Amendment 1
        with open(temp_constitution, 'w', encoding='utf-8') as f:
            f.write("# Version 2\n")
        time.sleep(0.01)  # ensure timestamp difference
        provider.resolve_latest(temp_constitution)

        # Amendment 2
        with open(temp_constitution, 'w', encoding='utf-8') as f:
            f.write("# Version 3\n")
        time.sleep(0.01)
        provider.resolve_latest(temp_constitution)

        # Amendment 3
        with open(temp_constitution, 'w', encoding='utf-8') as f:
            f.write("# Version 4\n")
        time.sleep(0.01)
        provider.resolve_latest(temp_constitution)

        # Should have 3 amendment records in chronological order
        history = provider.get_amendment_history(temp_constitution)
        assert len(history) == 3

        # Verify chronological order (timestamps should be increasing)
        for i in range(len(history) - 1):
            assert history[i].timestamp <= history[i+1].timestamp

    def test_no_amendment_when_hash_unchanged(self, temp_constitution):
        """
        Re-reading the same constitution should NOT create an amendment record.
        """
        provider = ConstitutionProvider()

        # First read
        bundle1 = provider.resolve(temp_constitution)

        # Invalidate cache but don't change file
        provider.invalidate_cache(temp_constitution)

        # Second read - same content
        bundle2 = provider.resolve(temp_constitution)

        # Hashes should match
        assert bundle1.source_hash == bundle2.source_hash

        # No amendment should be created
        history = provider.get_amendment_history(temp_constitution)
        assert len(history) == 0

    def test_amendment_record_contains_metadata(self, temp_constitution):
        """
        AmendmentRecord should contain all required metadata fields.
        """
        provider = ConstitutionProvider()

        # Baseline
        provider.resolve(temp_constitution)

        # Change constitution
        with open(temp_constitution, 'w', encoding='utf-8') as f:
            f.write("# Changed Constitution\n")

        provider.resolve_latest(temp_constitution)

        history = provider.get_amendment_history(temp_constitution)
        assert len(history) == 1

        record = history[0]

        # Verify all required fields are present and non-empty
        assert record.amendment_id != ""
        assert record.timestamp > 0
        assert record.author_agent_id != ""  # should be "system" by default
        assert record.source_ref == temp_constitution
        assert record.old_hash != ""
        assert record.new_hash != ""
        assert record.old_hash != record.new_hash

    def test_amendment_log_shared_across_constitutions(self):
        """
        AmendmentLog should track amendments across multiple constitutions.
        """
        log = AmendmentLog()
        provider = ConstitutionProvider(amendment_log=log)

        # Create two temporary constitutions
        temp1 = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='_1.md',
            delete=False,
            encoding='utf-8'
        )
        temp1.write("# Constitution 1\n")
        temp1.close()

        temp2 = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='_2.md',
            delete=False,
            encoding='utf-8'
        )
        temp2.write("# Constitution 2\n")
        temp2.close()

        try:
            # Baseline reads
            provider.resolve(temp1.name)
            provider.resolve(temp2.name)

            # Amend constitution 1
            with open(temp1.name, 'w', encoding='utf-8') as f:
                f.write("# Constitution 1 Modified\n")
            provider.resolve_latest(temp1.name)

            # Amend constitution 2
            with open(temp2.name, 'w', encoding='utf-8') as f:
                f.write("# Constitution 2 Modified\n")
            provider.resolve_latest(temp2.name)

            # Verify separate histories
            history1 = provider.get_amendment_history(temp1.name)
            history2 = provider.get_amendment_history(temp2.name)

            assert len(history1) == 1
            assert len(history2) == 1
            assert history1[0].source_ref == temp1.name
            assert history2[0].source_ref == temp2.name

            # Verify combined history
            all_amendments = provider.get_all_amendments()
            assert len(all_amendments) == 2

        finally:
            # Cleanup
            os.unlink(temp1.name)
            os.unlink(temp2.name)


class TestAmendmentRecord:

    def test_amendment_record_creation(self):
        """AmendmentRecord should be created with all required fields."""
        record = AmendmentRecord(
            amendment_id="a1",
            timestamp=time.time(),
            author_agent_id="board",
            source_ref="PATH_A_AGENTS.md",
            old_hash="abc123",
            new_hash="def456",
            change_description="Added new obligation"
        )

        assert record.amendment_id == "a1"
        assert record.author_agent_id == "board"
        assert record.source_ref == "PATH_A_AGENTS.md"
        assert record.old_hash == "abc123"
        assert record.new_hash == "def456"
        assert record.change_description == "Added new obligation"
        assert record.timestamp > 0


class TestAmendmentLog:

    def test_amendment_log_append_and_history(self):
        """AmendmentLog should store and retrieve records by source_ref."""
        log = AmendmentLog()

        record1 = AmendmentRecord(
            amendment_id="a1",
            timestamp=time.time(),
            author_agent_id="board",
            source_ref="PATH_A_AGENTS.md",
            old_hash="hash1",
            new_hash="hash2"
        )

        record2 = AmendmentRecord(
            amendment_id="a2",
            timestamp=time.time(),
            author_agent_id="cto",
            source_ref="PATH_A_AGENTS.md",
            old_hash="hash2",
            new_hash="hash3"
        )

        log.append(record1)
        log.append(record2)

        history = log.history("PATH_A_AGENTS.md")
        assert len(history) == 2
        assert history[0].amendment_id == "a1"
        assert history[1].amendment_id == "a2"

    def test_amendment_log_empty_history(self):
        """AmendmentLog should return empty list for unknown source_ref."""
        log = AmendmentLog()

        history = log.history("nonexistent.md")
        assert history == []

    def test_amendment_log_all_records(self):
        """AmendmentLog.all_records() should return all amendments."""
        log = AmendmentLog()

        record1 = AmendmentRecord(
            amendment_id="a1",
            timestamp=time.time(),
            author_agent_id="board",
            source_ref="PATH_A_AGENTS.md",
            old_hash="h1",
            new_hash="h2"
        )

        record2 = AmendmentRecord(
            amendment_id="a2",
            timestamp=time.time(),
            author_agent_id="cto",
            source_ref="PATH_B_AGENTS.md",
            old_hash="h3",
            new_hash="h4"
        )

        log.append(record1)
        log.append(record2)

        all_records = log.all_records()
        assert len(all_records) == 2
        assert all_records[0].source_ref == "PATH_A_AGENTS.md"
        assert all_records[1].source_ref == "PATH_B_AGENTS.md"

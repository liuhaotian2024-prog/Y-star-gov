# test_contract_legitimacy.py
# Copyright (C) 2026 Haotian Liu
# MIT License
#
# v0.42.0: Contract Legitimacy Lifecycle Tests
"""
Tests for contract legitimacy lifecycle (draft/confirmed/stale/expired/superseded).

Test coverage:
  1. New contract starts as draft, legitimacy_score = 0
  2. Confirmed contract has score = 1.0
  3. Time decay: after half_life days, score drops to 0.5
  4. Trigger firing reduces score
  5. Score below minimum → effective_status = stale
  6. valid_until exceeded → effective_status = expired
  7. Superseded contract points to replacement
  8. check() denies draft contracts
  9. check() allows confirmed contracts (normal behavior)
  10. check() records stale/expired status but still allows
  11. BACKWARD COMPAT: old contracts without legitimacy fields work perfectly
  12. legitimacy fields appear in to_dict() and hash
"""
import time
from ystar.kernel.dimensions import IntentContract, ContractStatus
from ystar.kernel.engine import check


def test_draft_contract_has_zero_legitimacy():
    """Test 1: New contract with status=draft has legitimacy_score = 0."""
    contract = IntentContract(
        status="draft",
        deny=["password"],
    )
    assert contract.legitimacy_score() == 0.0
    assert contract.effective_status() == "draft"


def test_confirmed_contract_has_full_legitimacy():
    """Test 2: Confirmed contract has score = 1.0."""
    now = time.time()
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=now,
        deny=["password"],
    )
    assert contract.legitimacy_score(now) == 1.0
    assert contract.effective_status(now) == "confirmed"


def test_time_decay_half_life():
    """Test 3: After half_life days, legitimacy score drops to 0.5."""
    now = time.time()
    half_life_days = 30
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=now,
        legitimacy_decay={"half_life_days": half_life_days},
        deny=["password"],
    )

    # At confirmation time: score = 1.0
    assert contract.legitimacy_score(now) == 1.0

    # After half_life days: score = 0.5
    future = now + (half_life_days * 86400)
    score = contract.legitimacy_score(future)
    assert 0.49 < score < 0.51  # Allow floating point tolerance

    # After 2 * half_life days: score = 0.25
    future2 = now + (2 * half_life_days * 86400)
    score2 = contract.legitimacy_score(future2)
    assert 0.24 < score2 < 0.26


def test_trigger_firing_reduces_score():
    """Test 4: Trigger firing reduces legitimacy score."""
    now = time.time()
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=now,
        review_triggers=["fired:personnel"],
        legitimacy_decay={
            "half_life_days": 0,  # No time decay
            "personnel_weight": 0.3,
        },
        deny=["password"],
    )

    # Trigger fired → score reduced by 0.3
    score = contract.legitimacy_score(now)
    assert 0.69 < score < 0.71  # 1.0 - 0.3 = 0.7


def test_score_below_minimum_becomes_stale():
    """Test 5: Score below minimum → effective_status = stale."""
    now = time.time()
    past = now - (100 * 86400)  # 100 days ago
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=past,
        legitimacy_decay={
            "half_life_days": 30,
            "minimum_score": 0.5,  # Set minimum higher to test stale status
        },
        deny=["password"],
    )

    # After 100 days with half_life=30, score would be very low but gets clamped
    # Natural decay: 0.5^(100/30) ≈ 0.099 → clamped to minimum 0.5
    score = contract.legitimacy_score(now)
    # Score is clamped at minimum, but still below the threshold for confirmed status
    assert score <= 0.5

    # Effective status should be stale because score < minimum
    assert contract.effective_status(now) == "stale"


def test_expired_contract_status():
    """Test 6: valid_until exceeded → effective_status = expired."""
    now = time.time()
    past = now - 86400  # Yesterday
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=past - 86400,
        valid_until=past,  # Expired yesterday
        deny=["password"],
    )

    assert contract.effective_status(now) == "expired"


def test_superseded_contract():
    """Test 7: Superseded contract points to replacement."""
    contract = IntentContract(
        status="superseded",
        confirmed_by="alice@example.com",
        confirmed_at=time.time(),
        superseded_by="sha256:abc123...",
        deny=["password"],
    )

    assert contract.effective_status() == "superseded"
    assert contract.superseded_by == "sha256:abc123..."


def test_check_denies_draft_contracts():
    """Test 8: check() denies draft contracts."""
    contract = IntentContract(
        status="draft",
        deny=["password"],
    )

    result = check(
        params={"message": "Hello world"},
        result={"status": "ok"},
        contract=contract,
    )

    assert result.passed is False
    assert len(result.violations) == 1
    assert result.violations[0].dimension == "legitimacy"
    assert "not confirmed" in result.violations[0].message.lower()


def test_check_allows_confirmed_contracts():
    """Test 9: check() allows confirmed contracts (normal behavior)."""
    now = time.time()
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=now,
        deny=["password"],
    )

    # Call without denied content → should pass
    result = check(
        params={"message": "Hello world"},
        result={"status": "ok"},
        contract=contract,
    )
    assert result.passed is True
    assert len(result.violations) == 0

    # Call with denied content → should fail (normal enforcement)
    result2 = check(
        params={"message": "My password is 12345"},
        result={"status": "ok"},
        contract=contract,
    )
    assert result2.passed is False
    assert any(v.dimension == "deny" for v in result2.violations)


def test_check_allows_stale_and_expired_contracts():
    """Test 10: check() records stale/expired status but still allows."""
    now = time.time()
    past = now - 86400

    # Expired contract
    expired_contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=past - 86400,
        valid_until=past,
        deny=["password"],
    )

    # Call without violations → should pass even though expired
    result = check(
        params={"message": "Hello"},
        result={"status": "ok"},
        contract=expired_contract,
    )
    assert result.passed is True

    # Stale contract
    very_past = now - (200 * 86400)
    stale_contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=very_past,
        legitimacy_decay={"half_life_days": 30, "minimum_score": 0.3},
        deny=["password"],
    )

    result2 = check(
        params={"message": "Hello"},
        result={"status": "ok"},
        contract=stale_contract,
    )
    assert result2.passed is True


def test_backward_compat_legacy_contracts():
    """Test 11: Old contracts without legitimacy fields work perfectly."""
    # Legacy contract: no status, no confirmed_by, no legitimacy fields
    legacy_contract = IntentContract(
        deny=["password"],
        only_paths=["./projects/"],
    )

    # Should be treated as confirmed (backward compat)
    assert legacy_contract.effective_status() == "confirmed"
    assert legacy_contract.legitimacy_score() == 0.0  # Never confirmed

    # check() should work normally
    result = check(
        params={"path": "./projects/app.py", "message": "Hello"},
        result={"status": "ok"},
        contract=legacy_contract,
    )
    assert result.passed is True

    # Violations still work normally
    result2 = check(
        params={"message": "My password is 12345"},
        result={"status": "ok"},
        contract=legacy_contract,
    )
    assert result2.passed is False
    assert any(v.dimension == "deny" for v in result2.violations)


def test_legitimacy_fields_in_serialization():
    """Test 12: Legitimacy fields appear in to_dict() and hash."""
    now = time.time()
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=now,
        valid_until=now + 86400 * 365,
        review_triggers=["personnel_change", "regulatory_update"],
        version=2,
        legitimacy_decay={"half_life_days": 90, "minimum_score": 0.4},
        deny=["password"],
    )

    # to_dict() should include legitimacy fields
    d = contract.to_dict()
    assert d["status"] == "confirmed"
    assert d["confirmed_by"] == "alice@example.com"
    assert d["confirmed_at"] == now
    assert d["valid_until"] == now + 86400 * 365
    assert d["review_triggers"] == ["personnel_change", "regulatory_update"]
    assert d["version"] == 2
    assert d["legitimacy_decay"] == {"half_life_days": 90, "minimum_score": 0.4}

    # Hash should include legitimacy fields
    hash1 = contract._compute_hash()
    assert "sha256:" in hash1

    # Different legitimacy fields → different hash
    contract2 = IntentContract(
        status="confirmed",
        confirmed_by="bob@example.com",  # Different confirmer
        confirmed_at=now,
        valid_until=now + 86400 * 365,
        review_triggers=["personnel_change", "regulatory_update"],
        version=2,
        legitimacy_decay={"half_life_days": 90, "minimum_score": 0.4},
        deny=["password"],
    )
    hash2 = contract2._compute_hash()
    assert hash1 != hash2  # Different confirmed_by → different hash


def test_suspended_contract_blocks_execution():
    """Test extra: Suspended contracts block execution like draft."""
    contract = IntentContract(
        status="suspended",
        confirmed_by="alice@example.com",
        confirmed_at=time.time(),
        deny=["password"],
    )

    result = check(
        params={"message": "Hello"},
        result={"status": "ok"},
        contract=contract,
    )

    assert result.passed is False
    assert len(result.violations) == 1
    assert result.violations[0].dimension == "legitimacy"
    assert "suspended" in result.violations[0].message.lower()


def test_from_dict_includes_legitimacy_fields():
    """Test extra: from_dict() correctly deserializes legitimacy fields."""
    now = time.time()
    d = {
        "deny": ["password"],
        "status": "confirmed",
        "confirmed_by": "alice@example.com",
        "confirmed_at": now,
        "valid_until": now + 86400,
        "review_triggers": ["personnel_change"],
        "version": 3,
        "superseded_by": "sha256:xyz",
        "legitimacy_decay": {"half_life_days": 60},
    }

    contract = IntentContract.from_dict(d)
    assert contract.status == "confirmed"
    assert contract.confirmed_by == "alice@example.com"
    assert contract.confirmed_at == now
    assert contract.valid_until == now + 86400
    assert contract.review_triggers == ["personnel_change"]
    assert contract.version == 3
    assert contract.superseded_by == "sha256:xyz"
    assert contract.legitimacy_decay == {"half_life_days": 60}


def test_multiple_triggers_cumulative_reduction():
    """Test extra: Multiple fired triggers cumulatively reduce score."""
    now = time.time()
    contract = IntentContract(
        status="confirmed",
        confirmed_by="alice@example.com",
        confirmed_at=now,
        review_triggers=["fired:personnel", "fired:regulatory"],
        legitimacy_decay={
            "half_life_days": 0,  # No time decay
            "personnel_weight": 0.2,
            "regulatory_weight": 0.3,
        },
        deny=["password"],
    )

    # Both triggers fired → score reduced by 0.2 + 0.3 = 0.5
    score = contract.legitimacy_score(now)
    assert 0.49 < score < 0.51  # 1.0 - 0.5 = 0.5


def test_source_hash_verification_on_tampering():
    """Test 13 (Task #4): verify_hash detects tampered constitution source."""
    import tempfile
    import os
    from ystar.kernel.contract_provider import ConstitutionProvider

    # Create a temporary constitution file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        original_content = """# Test Constitution
## agent_alice
- deny: ["password"]
"""
        f.write(original_content)
        temp_path = f.name

    try:
        provider = ConstitutionProvider()

        # First resolve: loads and records hash
        bundle1 = provider.resolve(temp_path)
        hash1 = bundle1.source_hash

        # Tamper with the source file
        with open(temp_path, 'w') as f:
            tampered_content = """# Test Constitution
## agent_alice
- deny: ["password", "secret"]
"""
            f.write(tampered_content)

        # Clear cache and resolve again
        provider.invalidate_cache(temp_path)

        # Second resolve: should detect hash mismatch and log warning
        import logging
        with LogCapture() as logs:
            bundle2 = provider.resolve(temp_path)

        hash2 = bundle2.source_hash

        # Hash should have changed
        assert hash1 != hash2

        # verify_hash should return False when checking against old hash
        assert provider.verify_hash(temp_path, hash1) is False
        assert provider.verify_hash(temp_path, hash2) is True

        # Check that warning was logged
        warning_found = any("Source legitimacy warning" in log for log in logs.messages)
        assert warning_found, "Expected source legitimacy warning in logs"

    finally:
        os.unlink(temp_path)


def test_obligation_timing_within_deadline():
    """Test 14 (Task #5): Obligation completed within deadline passes check."""
    contract = IntentContract(
        obligation_timing={
            "acknowledgement": 300,  # 5 minutes
            "completion": 3600,      # 1 hour
        },
        deny=[]
    )

    # Acknowledgement completed in 120 seconds (under 300s limit)
    result = check(
        params={
            "obligation_type": "acknowledgement",
            "elapsed_seconds": 120,
        },
        result={"status": "ok"},
        contract=contract,
    )
    assert result.passed is True
    assert len(result.violations) == 0


def test_obligation_timing_exceeds_deadline():
    """Test 15 (Task #5): Obligation exceeding deadline produces violation."""
    contract = IntentContract(
        obligation_timing={
            "acknowledgement": 300,  # 5 minutes
            "completion": 3600,      # 1 hour
        },
        deny=[]
    )

    # Acknowledgement took 450 seconds (exceeds 300s limit)
    result = check(
        params={
            "obligation_type": "acknowledgement",
            "elapsed_seconds": 450,
        },
        result={"status": "ok"},
        contract=contract,
    )

    assert result.passed is False
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v.dimension == "obligation_timing"
    assert v.field == "elapsed_seconds"
    assert "exceeded deadline" in v.message.lower()
    assert "450" in v.message
    assert "300" in v.message


def test_obligation_timing_no_params_skips_check():
    """Test 16 (Task #5): Missing obligation params skips timing check."""
    contract = IntentContract(
        obligation_timing={
            "acknowledgement": 300,
        },
        deny=[]
    )

    # No obligation_type or elapsed_seconds provided
    result = check(
        params={"message": "Hello"},
        result={"status": "ok"},
        contract=contract,
    )
    assert result.passed is True

    # Only obligation_type, no elapsed_seconds
    result2 = check(
        params={"obligation_type": "acknowledgement"},
        result={"status": "ok"},
        contract=contract,
    )
    assert result2.passed is True


def test_obligation_timing_unknown_type_skips_check():
    """Test 17 (Task #5): Unknown obligation type skips check."""
    contract = IntentContract(
        obligation_timing={
            "acknowledgement": 300,
        },
        deny=[]
    )

    # obligation_type not defined in contract
    result = check(
        params={
            "obligation_type": "unknown_type",
            "elapsed_seconds": 450,
        },
        result={"status": "ok"},
        contract=contract,
    )
    assert result.passed is True


class LogCapture:
    """Simple log capture context manager for testing."""
    def __init__(self):
        self.messages = []

    def __enter__(self):
        import logging
        self.handler = logging.StreamHandler()
        self.handler.setLevel(logging.WARNING)

        # Capture log messages
        class MessageCollector(logging.Handler):
            def __init__(self, collector):
                super().__init__()
                self.collector = collector

            def emit(self, record):
                self.collector.messages.append(self.format(record))

        self.collector = MessageCollector(self)
        logging.root.addHandler(self.collector)
        logging.root.setLevel(logging.WARNING)
        return self

    def __exit__(self, *args):
        import logging
        logging.root.removeHandler(self.collector)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

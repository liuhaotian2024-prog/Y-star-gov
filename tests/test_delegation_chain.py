"""
tests/test_delegation_chain.py
覆盖 DelegationChain.validate() 的边界条件
"""
import pytest
import time
from ystar.kernel.dimensions import (
    IntentContract, DelegationContract, DelegationChain, NonceLedger
)


def make_contract(**kwargs) -> IntentContract:
    return IntentContract(**kwargs)


def make_link(principal, actor, contract, allow_redelegate=True,
              delegation_depth=2, valid_until=None) -> DelegationContract:
    return DelegationContract(
        principal=principal,
        actor=actor,
        contract=contract,
        allow_redelegate=allow_redelegate,
        delegation_depth=delegation_depth,
        valid_until=valid_until,
    )


# ── 基础链验证 ──────────────────────────────────────────────────────────────

class TestDelegationChainBasic:

    def test_empty_chain_is_valid(self):
        chain = DelegationChain()
        assert chain.validate() == []
        assert chain.is_valid()

    def test_single_link_valid(self):
        c = make_contract(deny=["/etc"])
        link = make_link("org", "agent_a", c)
        chain = DelegationChain()
        chain.append(link)
        assert chain.validate() == []

    def test_two_link_valid_monotonic(self):
        parent_c = make_contract(deny=["/etc"], deny_commands=["sudo"])
        child_c  = make_contract(deny=["/etc", "/root"], deny_commands=["sudo", "rm -rf"])
        chain = DelegationChain()
        chain.append(make_link("org", "agent_a", parent_c))
        chain.append(make_link("agent_a", "agent_b", child_c))
        errors = chain.validate()
        assert errors == [], f"Unexpected errors: {errors}"

    def test_chain_broken_continuity(self):
        """actor 和下一个 principal 不一致 → 链断裂"""
        c = make_contract(deny=["/etc"])
        chain = DelegationChain()
        chain.append(make_link("org", "agent_a", c))
        chain.append(make_link("agent_X", "agent_b", c))  # 应是 agent_a
        errors = chain.validate()
        assert any("broken" in e.lower() or "agent_x" in e.lower() for e in errors)

    def test_chain_depth_properties(self):
        c = make_contract()
        chain = DelegationChain()
        assert chain.depth == 0
        assert chain.origin is None
        assert chain.terminal_actor is None
        chain.append(make_link("org", "a", c))
        chain.append(make_link("a", "b", c))
        assert chain.depth == 2
        assert chain.origin == "org"
        assert chain.terminal_actor == "b"


# ── 单调性约束验证 ──────────────────────────────────────────────────────────

class TestMonotonicity:

    def test_child_drops_deny_rule_fails(self):
        parent_c = make_contract(deny=["/etc", "/root"])
        child_c  = make_contract(deny=["/etc"])  # 丢掉了 /root
        chain = DelegationChain()
        chain.append(make_link("org", "a", parent_c))
        chain.append(make_link("a", "b", child_c))
        errors = chain.validate()
        assert any("deny" in e.lower() or "/root" in e for e in errors)

    def test_child_drops_deny_commands_fails(self):
        parent_c = make_contract(deny_commands=["rm -rf", "sudo"])
        child_c  = make_contract(deny_commands=["rm -rf"])  # 丢了 sudo
        chain = DelegationChain()
        chain.append(make_link("org", "a", parent_c))
        chain.append(make_link("a", "b", child_c))
        errors = chain.validate()
        assert any("sudo" in e or "deny_commands" in e.lower() for e in errors)

    def test_child_expands_value_range_max_fails(self):
        parent_c = make_contract(value_range={"amount": {"max": 1000}})
        child_c  = make_contract(value_range={"amount": {"max": 5000}})  # 扩大了
        ok, viols = child_c.is_subset_of(parent_c)
        assert not ok
        assert any("amount" in v for v in viols)

    def test_child_tightens_value_range_ok(self):
        parent_c = make_contract(value_range={"amount": {"max": 1000}})
        child_c  = make_contract(value_range={"amount": {"max": 500}})  # 收紧
        ok, viols = child_c.is_subset_of(parent_c)
        assert ok, f"Should be OK but got: {viols}"

    def test_child_removes_only_paths_fails(self):
        parent_c = make_contract(only_paths=["./workspace/"])
        child_c  = make_contract()  # 没有 only_paths = 更宽
        ok, viols = child_c.is_subset_of(parent_c)
        assert not ok

    def test_child_narrows_only_paths_ok(self):
        parent_c = make_contract(only_paths=["./workspace/"])
        child_c  = make_contract(only_paths=["./workspace/output/"])  # 更窄
        ok, viols = child_c.is_subset_of(parent_c)
        assert ok, f"Narrower path should be OK: {viols}"

    def test_child_expands_only_paths_fails(self):
        parent_c = make_contract(only_paths=["./workspace/output/"])
        child_c  = make_contract(only_paths=["./workspace/"])  # 更宽
        ok, viols = child_c.is_subset_of(parent_c)
        assert not ok

    def test_child_adds_new_domain_outside_parent_fails(self):
        parent_c = make_contract(only_domains=["api.internal.com"])
        child_c  = make_contract(only_domains=["api.internal.com", "api.external.com"])
        ok, viols = child_c.is_subset_of(parent_c)
        assert not ok


# ── 过期与重放 ──────────────────────────────────────────────────────────────

class TestExpiryAndReplay:

    def test_expired_link_detected(self):
        c = make_contract(deny=["/etc"])
        past = time.time() - 100  # 100秒前已过期
        link = make_link("org", "a", c, valid_until=past)
        chain = DelegationChain()
        chain.append(link)
        errors = chain.validate()
        assert any("expired" in e.lower() for e in errors)

    def test_future_valid_link_ok(self):
        c = make_contract(deny=["/etc"])
        future = time.time() + 3600
        link = make_link("org", "a", c, valid_until=future)
        chain = DelegationChain()
        chain.append(link)
        assert chain.validate() == []

    def test_nonce_ledger_replay_detection(self):
        c = make_contract(deny=["/etc"])
        dc = make_link("org", "a", c)
        ledger = NonceLedger()
        ok1, reason1 = ledger.consume(dc)
        assert ok1, f"First consume should succeed: {reason1}"
        ok2, reason2 = ledger.consume(dc)
        assert not ok2, "Second consume should be rejected"
        assert "replay" in reason2.lower() or "consumed" in reason2.lower()

    def test_nonce_ledger_hash_tamper_detection(self):
        c = make_contract(deny=["/etc"])
        dc = make_link("org", "a", c)
        dc.hash = "sha256:tampered"  # 篡改哈希
        ledger = NonceLedger()
        ok, reason = ledger.consume(dc)
        assert not ok
        assert "tamper" in reason.lower() or "mismatch" in reason.lower()

    def test_no_redelegate_blocks_chain(self):
        c = make_contract(deny=["/etc"])
        link1 = make_link("org", "a", c, allow_redelegate=False, delegation_depth=0)
        link2 = make_link("a", "b", c)
        chain = DelegationChain()
        chain.append(link1)
        chain.append(link2)
        errors = chain.validate()
        assert any("redelegate" in e.lower() or "redelegation" in e.lower() for e in errors)


# ── 序列化/反序列化 ─────────────────────────────────────────────────────────

class TestSerialization:

    def test_delegation_chain_roundtrip(self):
        c1 = make_contract(deny=["/etc"], deny_commands=["sudo"])
        c2 = make_contract(deny=["/etc", "/root"], deny_commands=["sudo", "rm -rf"])
        chain = DelegationChain()
        chain.append(make_link("org", "a", c1))
        chain.append(make_link("a", "b", c2))

        d = chain.to_dict()
        restored = DelegationChain.from_dict(d)

        assert restored.depth == chain.depth
        assert restored.origin == chain.origin
        assert restored.terminal_actor == chain.terminal_actor
        assert restored.validate() == []

    def test_delegation_contract_hash_survives_roundtrip(self):
        """FIX-6: hash must be preserved through to_dict/from_dict cycle."""
        c = make_contract(deny=["/etc"], deny_commands=["sudo"])
        link = make_link("org", "agent_a", c)
        original_hash = link.hash
        original_nonce = link.nonce
        assert original_hash, "hash should be set after construction"

        # Round-trip through dict serialization
        d = link.to_dict()
        restored = DelegationContract.from_dict(d)

        assert restored.hash == original_hash, (
            f"Hash changed after roundtrip: {original_hash!r} → {restored.hash!r}"
        )
        assert restored.nonce == original_nonce
        assert restored.verify_hash(), "verify_hash() should pass after roundtrip"

    def test_delegation_chain_roundtrip_preserves_hashes(self):
        """FIX-6: all link hashes must survive chain round-trip."""
        c1 = make_contract(deny=["/etc"])
        c2 = make_contract(deny=["/root"])
        chain = DelegationChain()
        chain.append(make_link("board", "ceo", c1))
        chain.append(make_link("ceo", "cto", c2))

        original_hashes = [lk.hash for lk in chain.links]

        d = chain.to_dict()
        restored = DelegationChain.from_dict(d)

        for i, lk in enumerate(restored.links):
            assert lk.hash == original_hashes[i], (
                f"Link[{i}] hash mismatch after roundtrip"
            )
            assert lk.verify_hash()

    def test_intent_contract_hash_stable(self):
        c = make_contract(deny=["/etc"], value_range={"amount": {"max": 1000}})
        h1 = c.hash
        # 重新构建完全相同的合约
        c2 = make_contract(deny=["/etc"], value_range={"amount": {"max": 1000}})
        assert c.hash == c2.hash

    def test_intent_contract_hash_changes_on_diff(self):
        c1 = make_contract(deny=["/etc"])
        c2 = make_contract(deny=["/etc", "/root"])
        assert c1.hash != c2.hash

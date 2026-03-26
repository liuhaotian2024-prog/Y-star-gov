"""
tests/test_cieu_store.py — CIEUStore 密码学封印、哈希链
"""
import pytest
import uuid
from ystar.governance.cieu_store import CIEUStore, NullCIEUStore


def rec(session_id="s1", decision="allow", event_type="file_read") -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "session_id": session_id,
        "agent_id": "agent_a",
        "event_type": event_type,
        "decision": decision,
        "passed": (decision == "allow"),
        "violations": [],
        "contract_hash": "sha256:test",
    }


class TestCIEUBasic:

    def test_write_and_count(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec())
        assert s.stats()["total"] == 1

    def test_write_multiple(self, tmp_db):
        s = CIEUStore(tmp_db)
        for _ in range(5):
            s.write_dict(rec())
        assert s.stats()["total"] == 5

    def test_deny_rate(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec(decision="allow"))
        s.write_dict(rec(decision="allow"))
        s.write_dict(rec(decision="deny"))
        rate = s.stats().get("deny_rate", 0)
        assert abs(rate - 1/3) < 0.01

    def test_dedup_same_event_id(self, tmp_db):
        s = CIEUStore(tmp_db)
        r = rec()
        s.write_dict(r)
        s.write_dict(r)  # 重复写入同一 event_id
        assert s.stats()["total"] == 1

    def test_query_by_keyword(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec(event_type="special_op_xyz"))
        results = s.query("special_op_xyz")
        assert len(results) >= 1


class TestMerkleSealing:

    def test_seal_produces_merkle_root(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec(session_id="ss"))
        s.write_dict(rec(session_id="ss"))
        r = s.seal_session("ss")
        assert r["merkle_root"] is not None
        assert r["event_count"] == 2

    def test_seal_empty_session_warns(self, tmp_db):
        s = CIEUStore(tmp_db)
        r = s.seal_session("nonexistent")
        assert r["event_count"] == 0
        assert "warning" in r

    def test_seal_chain_prev_root(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec(session_id="sa"))
        r1 = s.seal_session("sa")
        s.write_dict(rec(session_id="sb"))
        r2 = s.seal_session("sb")
        assert r2.get("prev_root") == r1["merkle_root"]

    def test_verify_after_seal(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec(session_id="sv"))
        s.seal_session("sv")
        v = s.verify_session_seal("sv")
        assert v.get("stored_count", 0) >= 1
        assert v.get("valid", False) is True

    def test_seal_idempotent_same_root(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec(session_id="si"))
        r1 = s.seal_session("si")
        r2 = s.seal_session("si")
        assert r1["merkle_root"] == r2["merkle_root"]

    def test_different_sessions_different_roots(self, tmp_db):
        s = CIEUStore(tmp_db)
        s.write_dict(rec(session_id="sx"))
        s.write_dict(rec(session_id="sy"))
        rx = s.seal_session("sx")
        ry = s.seal_session("sy")
        assert rx["merkle_root"] != ry["merkle_root"]


class TestNullCIEUStore:

    def test_write_dict_no_crash(self):
        s = NullCIEUStore()
        s.write_dict({"session_id": "x", "decision": "allow"})

    def test_stats_zero(self):
        s = NullCIEUStore()
        assert s.stats().get("total", 0) == 0

    def test_issues_user_warning(self):
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            NullCIEUStore()
        assert any(issubclass(x.category, UserWarning) for x in w)

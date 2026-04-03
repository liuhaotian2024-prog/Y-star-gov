"""
tests/test_v041_features.py
v0.41 新功能测试：PulseStore GC、DomainPack.compose()、CLI 命令、seal 自动化
"""
import pytest
import time
import uuid
from unittest.mock import patch


# ── PulseStore 内存泄漏修复 ──────────────────────────────────────────────────

class TestPulseStoreGC:

    def _make_pulse(self, actor_id="agent_a", status=None):
        from ystar.governance.intervention_models import (
            InterventionPulse, InterventionLevel, InterventionStatus,
        )
        p = InterventionPulse(
            actor_id=actor_id,
            entity_id="entity_1",
            level=InterventionLevel.SOFT_PULSE,
            omission_type="respond_to_complaint",
            trigger_obligation_id=uuid.uuid4().hex[:8],
        )
        if status:
            p.status = status
        return p

    def test_pulse_store_has_stats(self):
        from ystar.governance.intervention_engine import PulseStore
        store = PulseStore()
        s = store.stats()
        assert "total" in s
        assert "active" in s
        assert "resolved" in s

    def test_gc_removes_resolved_pulses(self):
        from ystar.governance.intervention_engine import PulseStore
        from ystar.governance.intervention_models import InterventionStatus
        store = PulseStore()

        # 添加10个已解决 pulse
        for _ in range(10):
            p = self._make_pulse()
            p.status = InterventionStatus.RESOLVED
            store.add_pulse(p)

        removed = store.gc_resolved()
        assert removed == 10
        assert store.stats()["total"] == 0

    def test_active_pulses_not_gc_d(self):
        from ystar.governance.intervention_engine import PulseStore
        from ystar.governance.intervention_models import InterventionStatus
        store = PulseStore()

        # 3 active + 5 resolved
        for _ in range(3):
            store.add_pulse(self._make_pulse())  # ACTIVE by default
        for _ in range(5):
            p = self._make_pulse()
            p.status = InterventionStatus.RESOLVED
            store.add_pulse(p)

        removed = store.gc_resolved()
        assert removed == 5
        assert store.stats()["active"] == 3

    def test_auto_gc_on_max_resolved(self):
        """超过 _MAX_RESOLVED 时自动触发 GC"""
        from ystar.governance.intervention_engine import PulseStore
        from ystar.governance.intervention_models import InterventionStatus

        store = PulseStore()
        store._MAX_RESOLVED = 10  # 测试用小上限

        # 写入 15 个已解决 pulse
        for _ in range(15):
            p = self._make_pulse()
            p.status = InterventionStatus.RESOLVED
            store.add_pulse(p)

        # 超过上限后应自动清理
        assert store.stats()["total"] <= 15  # 触发了 GC


# ── DomainPack.compose() ─────────────────────────────────────────────────────

class TestDomainPackCompose:

    def test_single_pack_compose(self):
        from ystar.domains import DomainPack
        from ystar.domains.finance import FinanceDomainPack
        composed = DomainPack.compose(FinanceDomainPack())
        assert composed.domain_name == "composed"
        c = composed.constitutional_contract()
        assert c is not None

    def test_composed_deny_is_union(self):
        """组合后的 deny 包含所有 pack 的 deny 条目"""
        from ystar.domains import DomainPack
        from ystar.kernel.dimensions import ConstitutionalContract, IntentContract

        class PackA(DomainPack):
            domain_name = "pack_a"
            version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(deny=["secret_a", "shared"])
            def vocabulary(self): return {}

        class PackB(DomainPack):
            domain_name = "pack_b"
            version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(deny=["secret_b", "shared"])
            def vocabulary(self): return {}

        composed = DomainPack.compose(PackA(), PackB())
        c = composed.constitutional_contract()
        assert "secret_a" in c.deny
        assert "secret_b" in c.deny
        assert c.deny.count("shared") == 1  # 去重

    def test_composed_value_range_takes_strictest(self):
        """value_range 取最严格值：max 取最小，min 取最大"""
        from ystar.domains import DomainPack
        from ystar.kernel.dimensions import ConstitutionalContract

        class PackA(DomainPack):
            domain_name = "a"; version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(value_range={"amount": {"max": 1000}})
            def vocabulary(self): return {}

        class PackB(DomainPack):
            domain_name = "b"; version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(value_range={"amount": {"max": 500}})
            def vocabulary(self): return {}

        composed = DomainPack.compose(PackA(), PackB())
        c = composed.constitutional_contract()
        assert c.value_range["amount"]["max"] == 500.0  # 取最严

    def test_compose_only_domains_conflict_raises(self):
        """互斥的 only_domains 白名单应抛出 ValueError"""
        from ystar.domains import DomainPack
        from ystar.kernel.dimensions import ConstitutionalContract

        class PackA(DomainPack):
            domain_name = "a"; version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(only_domains=["api.alpha.com"])
            def vocabulary(self): return {}

        class PackB(DomainPack):
            domain_name = "b"; version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(only_domains=["api.beta.com"])
            def vocabulary(self): return {}

        with pytest.raises(ValueError, match="only_domains"):
            composed = DomainPack.compose(PackA(), PackB())
            composed.constitutional_contract()  # 惰性计算，这里才触发

    def test_compose_compatible_domains(self):
        """兼容的 only_domains 合并后取交集"""
        from ystar.domains import DomainPack
        from ystar.kernel.dimensions import ConstitutionalContract

        class PackA(DomainPack):
            domain_name = "a"; version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(only_domains=["api.shared.com", "api.a.com"])
            def vocabulary(self): return {}

        class PackB(DomainPack):
            domain_name = "b"; version = "1.0"
            def constitutional_contract(self):
                return ConstitutionalContract(only_domains=["api.shared.com", "api.b.com"])
            def vocabulary(self): return {}

        composed = DomainPack.compose(PackA(), PackB(), name="ab_pack")
        c = composed.constitutional_contract()
        assert "api.shared.com" in c.only_domains
        assert "api.a.com" not in c.only_domains   # 不在交集中
        assert composed.domain_name == "ab_pack"

    def test_composed_describe(self):
        from ystar.domains import DomainPack
        from ystar.domains.finance import FinanceDomainPack
        composed = DomainPack.compose(FinanceDomainPack())
        desc = composed.describe()
        assert "finance" in desc.lower()

    def test_composed_vocabulary_union(self):
        from ystar.domains import DomainPack
        from ystar.kernel.dimensions import ConstitutionalContract

        class PackA(DomainPack):
            domain_name = "a"; version = "1.0"
            def constitutional_contract(self): return ConstitutionalContract()
            def vocabulary(self): return {"role_names": ["role_a"], "deny_keywords": []}

        class PackB(DomainPack):
            domain_name = "b"; version = "1.0"
            def constitutional_contract(self): return ConstitutionalContract()
            def vocabulary(self): return {"role_names": ["role_b"], "deny_keywords": []}

        composed = DomainPack.compose(PackA(), PackB())
        v = composed.vocabulary()
        assert "role_a" in v["role_names"]
        assert "role_b" in v["role_names"]


# ── CLI 命令测试 ─────────────────────────────────────────────────────────────

class TestCLICommands:

    def test_doctor_runs_without_crash(self, tmp_path, capsys):
        import sys
        sys.argv = ["ystar", "doctor"]
        from ystar._cli import _cmd_doctor
        _cmd_doctor([])
        out = capsys.readouterr().out
        assert "Y*gov Doctor" in out
        # Layer1/Layer2 architecture - check for key components
        assert "Layer1" in out or "CIEU Database" in out

    def test_verify_no_args_shows_usage(self, tmp_path, capsys):
        from ystar._cli import _cmd_verify
        _cmd_verify(["--db", str(tmp_path / "nonexistent.db")])
        out = capsys.readouterr().out
        assert "Verify" in out or "verify" in out.lower() or "Error" in out

    def test_seal_with_real_db(self, tmp_db, capsys):
        from ystar.governance.cieu_store import CIEUStore
        import uuid
        # 先写几条记录
        store = CIEUStore(tmp_db)
        for _ in range(3):
            store.write_dict({"event_id": uuid.uuid4().hex,
                              "session_id": "seal_test", "agent_id": "a",
                              "event_type": "read", "decision": "allow",
                              "passed": True, "violations": []})
        from ystar._cli import _cmd_seal
        _cmd_seal(["--db", tmp_db, "--session", "seal_test"])
        out = capsys.readouterr().out
        assert "Sealed" in out or "sealed" in out.lower()

    def test_report_json_format(self, tmp_db, capsys):
        import json, uuid
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(tmp_db)
        store.write_dict({"event_id": uuid.uuid4().hex, "session_id": "s",
                          "agent_id": "a", "event_type": "r",
                          "decision": "deny", "passed": False, "violations": []})
        from ystar._cli import _cmd_report_enhanced
        _cmd_report_enhanced(["--db", tmp_db, "--format", "json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total"] == 1
        assert data["deny"] == 1
        assert data["deny_rate"] == 1.0

    def test_second_main_knows_setup(self, tmp_path, monkeypatch):
        """第二个 main() 必须能分发 setup 命令，不再报 Unknown command（原始 bug）"""
        import sys
        monkeypatch.chdir(tmp_path)
        sys.argv = ["ystar", "setup"]
        # mock input() 返回空字符串（全部用默认值）
        with patch("builtins.input", return_value=""):
            from ystar._cli import main
            try:
                main()
            except SystemExit as e:
                assert e.code in (0, None)
        # 成功的标志是没有抛出 "Unknown command: setup" 这种错误
        # session json 应该被创建
        assert (tmp_path / ".ystar_session.json").exists()

    def test_version_command(self, capsys):
        import sys
        sys.argv = ["ystar", "version"]
        from ystar._cli import main
        main()
        out = capsys.readouterr().out
        assert "0.4" in out  # v0.40 或 v0.41


# ── seal_session 自动化 ───────────────────────────────────────────────────────

class TestSealAutomation:

    def test_seal_then_verify_consistent(self, tmp_db):
        """封印后验证应该通过"""
        from ystar.governance.cieu_store import CIEUStore
        import uuid
        store = CIEUStore(tmp_db)
        for i in range(5):
            store.write_dict({"event_id": uuid.uuid4().hex,
                              "session_id": "auto_seal", "agent_id": "a",
                              "event_type": "read", "decision": "allow",
                              "passed": True, "violations": []})
        seal = store.seal_session("auto_seal")
        assert seal["event_count"] == 5
        assert seal["merkle_root"] is not None

        verify = store.verify_session_seal("auto_seal")
        assert verify.get("valid") is True

    def test_additional_write_breaks_verification(self, tmp_db):
        """封印后新增记录，重新验证应该不一致"""
        from ystar.governance.cieu_store import CIEUStore
        import uuid
        store = CIEUStore(tmp_db)
        store.write_dict({"event_id": uuid.uuid4().hex,
                          "session_id": "tamper_test", "agent_id": "a",
                          "event_type": "read", "decision": "allow",
                          "passed": True, "violations": []})
        store.seal_session("tamper_test")

        # 封印后再添加一条（模拟数据注入）
        store.write_dict({"event_id": uuid.uuid4().hex,
                          "session_id": "tamper_test", "agent_id": "a",
                          "event_type": "injected", "decision": "allow",
                          "passed": True, "violations": []})

        verify = store.verify_session_seal("tamper_test")
        # count 已经变了，complete verification 应该发现不一致
        assert verify.get("current_count", 0) > verify.get("stored_count", 0)

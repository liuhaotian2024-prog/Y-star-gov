"""
Test new domain packs: legal, ystar_dev omission
=================================================
验证新增的 domain pack 功能正常。
"""
import pytest
from ystar.governance.omission_rules import RuleRegistry, reset_registry
from ystar.domains.omission_domain_packs import apply_legal_pack, list_packs
from ystar.domains.legal import LegalComplianceDomainPack, get_legal_contract
from ystar.kernel.dimensions import IntentContract


class TestLegalDomainPack:
    """测试 legal/compliance domain pack"""

    def test_legal_pack_in_registry(self):
        """legal pack 应该出现在 pack 列表中"""
        packs = list_packs()
        assert "legal" in packs

    def test_apply_legal_pack_basic(self):
        """legal pack 可以正常应用"""
        registry = reset_registry()
        apply_legal_pack(registry)
        # 验证时限已覆盖
        rule = registry.get("rule_a_delegation")
        assert rule is not None
        assert rule.due_within_secs == 3600.0  # 1 hour

    def test_apply_legal_pack_strict(self):
        """legal pack strict 模式添加额外规则"""
        registry = reset_registry()
        apply_legal_pack(registry, strict=True)

        # 验证额外规则存在
        conflict_rule = registry.get("legal_conflict_check")
        assert conflict_rule is not None
        assert conflict_rule.due_within_secs == 86400.0  # 24 hours

        approval_rule = registry.get("legal_approval_chain")
        assert approval_rule is not None

        archive_rule = registry.get("legal_document_archive")
        assert archive_rule is not None

    def test_legal_domain_pack_class(self):
        """LegalComplianceDomainPack 可以实例化"""
        pack = LegalComplianceDomainPack()
        assert pack.domain_name == "legal"
        assert pack.version == "1.0.0"

    def test_legal_attorney_contract(self):
        """attorney 角色合约正常生成"""
        contract = get_legal_contract("attorney", matter_id="M-001")
        assert isinstance(contract, IntentContract)
        assert "delete_audit_trail" in contract.deny
        assert "./matters/" in contract.only_paths

    def test_legal_paralegal_contract(self):
        """paralegal 角色合约有限制"""
        contract = get_legal_contract("paralegal")
        assert isinstance(contract, IntentContract)
        assert "approve_final_document" in contract.deny

    def test_legal_compliance_officer_contract(self):
        """compliance_officer 角色合约关注审计"""
        contract = get_legal_contract("compliance_officer")
        assert isinstance(contract, IntentContract)
        assert "delete_audit_trail" in contract.deny
        assert "./compliance/" in contract.only_paths

    def test_legal_auditor_contract(self):
        """auditor 角色只读"""
        contract = get_legal_contract("auditor")
        assert isinstance(contract, IntentContract)
        # 验证有删除相关的命令限制
        assert any("delete" in cmd.lower() or "drop" in cmd.lower()
                   for cmd in contract.deny_commands)

    def test_legal_general_counsel_contract(self):
        """general_counsel 高权限但仍受约束"""
        contract = get_legal_contract("general_counsel")
        assert isinstance(contract, IntentContract)
        assert "delete_audit_trail" in contract.deny  # 仍然不能删除审计


class TestYStarDevOmissionPack:
    """测试 ystar_dev omission pack"""

    def test_ystar_dev_omission_pack_import(self):
        """ystar_dev omission pack 可以正常导入"""
        from ystar.domains.ystar_dev.omission_pack import (
            apply_ystar_dev_omission_pack,
            PACK_INFO,
        )
        assert PACK_INFO["name"] == "ystar_dev_omission"
        assert PACK_INFO["version"] == "1.0.0"

    def test_apply_ystar_dev_omission_pack(self):
        """ystar_dev omission pack 添加了特殊规则"""
        from ystar.domains.ystar_dev.omission_pack import apply_ystar_dev_omission_pack

        registry = reset_registry()
        apply_ystar_dev_omission_pack(registry)

        # 验证特殊规则存在
        directive_rule = registry.get("ystar_directive_decomposition")
        assert directive_rule is not None
        assert directive_rule.due_within_secs == 600.0  # 10 minutes

        article_rule = registry.get("ystar_article_source_verification")
        assert article_rule is not None
        assert article_rule.due_within_secs == 300.0  # 5 minutes

        cieu_rule = registry.get("ystar_cieu_archive_required")
        assert cieu_rule is not None

        tracker_rule = registry.get("ystar_directive_tracker_update")
        assert tracker_rule is not None

        handoff_rule = registry.get("ystar_session_handoff_update")
        assert handoff_rule is not None

        social_rule = registry.get("ystar_social_media_approval")
        assert social_rule is not None

    def test_ystar_dev_pack_contract_timing_override(self):
        """合约可以覆盖 ystar_dev pack 时限"""
        from ystar.domains.ystar_dev.omission_pack import apply_ystar_dev_omission_pack
        from ystar.kernel.dimensions import IntentContract

        contract = IntentContract(
            obligation_timing={
                "directive_decomposition": 300,  # 覆盖为 5 分钟
            }
        )

        registry = reset_registry()
        apply_ystar_dev_omission_pack(registry, contract=contract)

        rule = registry.get("ystar_directive_decomposition")
        assert rule.due_within_secs == 300.0  # 已覆盖


class TestTemplatesWithNewDomains:
    """测试新模板"""

    def test_attorney_template_exists(self):
        """attorney 模板存在"""
        from ystar.templates import TEMPLATE_DICTS
        assert "attorney" in TEMPLATE_DICTS

    def test_paralegal_template_exists(self):
        """paralegal 模板存在"""
        from ystar.templates import TEMPLATE_DICTS
        assert "paralegal" in TEMPLATE_DICTS

    def test_compliance_officer_template_exists(self):
        """compliance_officer 模板存在"""
        from ystar.templates import TEMPLATE_DICTS
        assert "compliance_officer" in TEMPLATE_DICTS

    def test_auditor_template_exists(self):
        """auditor 模板存在"""
        from ystar.templates import TEMPLATE_DICTS
        assert "auditor" in TEMPLATE_DICTS

    def test_get_attorney_template(self):
        """可以获取 attorney 模板"""
        from ystar.templates import get_template
        result = get_template("attorney")
        assert result.contract is not None

    def test_template_list_updated(self):
        """TEMPLATES 列表包含新模板"""
        from ystar.templates import TEMPLATES
        assert "attorney" in TEMPLATES
        assert "paralegal" in TEMPLATES
        assert "compliance_officer" in TEMPLATES
        assert "auditor" in TEMPLATES

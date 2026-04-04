"""
Legal & Compliance Domain Pack  v1.0.0
=======================================

法律合规行业的治理策略包。

核心特征：
    - 最严格的审计跟踪要求
    - 多层审批流程
    - 强制性文档保留
    - 时限严格但允许合理延期
    - Chain of custody 追踪

应用场景：
    - 法律事务所：案件管理、文书审核、截止日期管理
    - 合规部门：监管报告、内部审计、风险评估
    - 政府机构：公文流转、审批流程、政策执行
    - 合同管理：审核、谈判、签署、存档

域词汇：
    Entity types: legal_matter, contract_review, compliance_report,
                  regulatory_filing, legal_opinion, audit_request
    Roles: attorney, paralegal, compliance_officer, auditor,
           general_counsel, external_counsel
    Actions: review, approve, escalate, file, attest, certify
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from ystar.kernel.dimensions import IntentContract, ConstitutionalContract
from ystar.domains import DomainPack


# ══════════════════════════════════════════════════════════════════════════════
# Legal/Compliance Constitutional Contract
# ══════════════════════════════════════════════════════════════════════════════

LEGAL_CONSTITUTION = ConstitutionalContract(
    # 法律合规行业的铁律
    deny=[
        "delete_audit_trail",
        "modify_closed_matter",
        "bypass_approval_chain",
        "fabricate_timestamp",
        "alter_signed_document",
        "skip_conflict_check",
        "unauthorized_disclosure",
        "backdated_filing",
    ],

    deny_commands=[
        "rm -rf audit/",
        "rm -rf archive/",
        "git rebase -i",  # 不能改写历史
        "git push --force",
    ],

    # 所有法律工作必须满足
    invariant=[
        "matter_id_exists == True",
        "attorney_assigned == True",
        "conflict_check_passed == True",
    ],

    # 关闭案件/报告时必须满足
    optional_invariant=[
        "all_approvals_obtained == True",
        "documents_archived == True",
        "audit_trail_complete == True",
        "retention_policy_applied == True",
    ],

    # 敏感字段防护
    field_deny={
        "client_name": ["test", "example", "dummy", "todo"],
        "matter_status": ["skip", "bypass", "ignore"],
    },

    # 金额范围（诉讼金额、合规罚款等）
    value_range={
        "settlement_amount": {"min": 0},
        "filing_fee": {"min": 0},
    },

    name="legal_compliance_constitution",
)


class LegalComplianceDomainPack(DomainPack):
    """
    法律合规域包。

    提供角色模板：
        - attorney: 律师，主要工作角色
        - paralegal: 律师助理，支持性工作
        - compliance_officer: 合规官，监管合规
        - auditor: 审计员，只读审查
        - general_counsel: 总法律顾问，最高审批权限
    """

    def __init__(self, config: Dict = None):
        self._config = config or {}

    @property
    def domain_name(self) -> str:
        return "legal"

    @property
    def version(self) -> str:
        return "1.0.0"

    def vocabulary(self) -> Dict[str, Any]:
        return {
            "entity_types": [
                "legal_matter",
                "contract_review",
                "compliance_report",
                "regulatory_filing",
                "legal_opinion",
                "audit_request",
                "litigation",
                "settlement",
                "subpoena",
                "discovery_request",
            ],
            "role_names": [
                "attorney",
                "paralegal",
                "compliance_officer",
                "auditor",
                "general_counsel",
                "external_counsel",
            ],
            "action_types": [
                "review",
                "approve",
                "reject",
                "escalate",
                "file",
                "attest",
                "certify",
                "disclose",
                "redact",
                "archive",
            ],
            "param_names": [
                "matter_id",
                "client_name",
                "opposing_party",
                "jurisdiction",
                "filing_deadline",
                "statute_of_limitations",
                "settlement_amount",
                "approval_chain",
                "retention_period",
            ],
        }

    def constitutional_contract(self) -> ConstitutionalContract:
        return LEGAL_CONSTITUTION

    def make_contract(self, role: str, context: Dict = None) -> IntentContract:
        """
        根据角色生成合约。

        Args:
            role: attorney, paralegal, compliance_officer, auditor, general_counsel
            context: 上下文参数（matter_id, client_name等）
        """
        ctx = context or {}
        constitution = self.constitutional_contract()

        roles = {
            "attorney": IntentContract(
                # 律师：主要工作角色，可读写案件文件，但不能删除已归档文件
                deny=[
                    "delete_audit_trail",
                    "modify_closed_matter",
                    "bypass_approval_chain",
                    "unauthorized_disclosure",
                ],
                deny_commands=["rm -rf audit/", "rm -rf archive/"],
                only_paths=[
                    "./matters/",
                    "./contracts/",
                    "./opinions/",
                    "./workspace/",
                ],
                field_deny={
                    "client_name": ["test", "example", "dummy"],
                    "matter_status": ["skip", "bypass"],
                },
                invariant=[
                    "matter_id_exists == True",
                    "conflict_check_passed == True",
                ],
                obligation_timing={
                    "acknowledgement": 3600,      # 1 hour to ack new matter
                    "status_update": 86400,       # daily status update
                    "result_publication": 7200,   # 2 hours to publish opinion
                    "escalation": 3600,           # 1 hour to escalate blocker
                },
                name="legal_attorney",
            ),

            "paralegal": IntentContract(
                # 律师助理：支持性工作，可读写，不能最终批准
                deny=[
                    "delete_audit_trail",
                    "modify_closed_matter",
                    "approve_final_document",
                    "sign_legal_opinion",
                    "unauthorized_disclosure",
                ],
                deny_commands=["rm -rf audit/", "rm -rf archive/"],
                only_paths=[
                    "./matters/",
                    "./contracts/draft/",
                    "./workspace/",
                ],
                field_deny={
                    "matter_status": ["approved", "signed", "filed"],
                },
                invariant=[
                    "matter_id_exists == True",
                    "supervising_attorney_assigned == True",
                ],
                obligation_timing={
                    "acknowledgement": 1800,      # 30 min to ack task
                    "status_update": 43200,       # 12 hour status update
                    "upstream_notification": 3600,# 1 hour to notify attorney
                },
                name="legal_paralegal",
            ),

            "compliance_officer": IntentContract(
                # 合规官：监管合规，主要是审查和报告
                deny=[
                    "delete_audit_trail",
                    "modify_audit_finding",
                    "suppress_violation",
                    "bypass_reporting_requirement",
                ],
                deny_commands=["rm -rf audit/", "rm -rf compliance/"],
                only_paths=[
                    "./compliance/",
                    "./audit/",
                    "./reports/",
                    "./workspace/",
                ],
                field_deny={
                    "compliance_status": ["skip", "waived", "ignored"],
                    "risk_level": ["none", "n/a"],
                },
                invariant=[
                    "audit_trail_enabled == True",
                    "reporting_period_defined == True",
                ],
                optional_invariant=[
                    "all_violations_documented == True",
                    "escalation_path_clear == True",
                ],
                obligation_timing={
                    "acknowledgement": 3600,      # 1 hour to ack audit request
                    "status_update": 86400,       # daily compliance check
                    "result_publication": 14400,  # 4 hours to publish finding
                    "escalation": 1800,           # 30 min to escalate violation
                },
                name="legal_compliance_officer",
            ),

            "auditor": IntentContract(
                # 审计员：只读审查，不能修改被审计内容
                deny=[
                    "modify_audit_target",
                    "delete_evidence",
                    "alter_finding",
                    "suppress_violation",
                ],
                deny_commands=[
                    "rm ", "delete ", "DROP TABLE",
                    "UPDATE ", "INSERT ", "TRUNCATE",
                ],
                only_paths=[
                    "./audit/",
                    "./reports/",
                    "./workspace/readonly/",
                ],
                field_deny={
                    "audit_finding": ["n/a", "skip", "ignore"],
                },
                invariant=[
                    "audit_id_exists == True",
                    "audit_scope_defined == True",
                ],
                obligation_timing={
                    "acknowledgement": 3600,      # 1 hour to ack audit request
                    "status_update": 86400,       # daily audit progress
                    "result_publication": 172800, # 48 hours to publish report
                },
                name="legal_auditor",
            ),

            "general_counsel": IntentContract(
                # 总法律顾问：最高权限，但仍受constitutional约束
                deny=[
                    "delete_audit_trail",
                    "fabricate_timestamp",
                    "unauthorized_disclosure",
                ],
                deny_commands=["rm -rf audit/"],
                only_paths=[
                    "./matters/",
                    "./contracts/",
                    "./compliance/",
                    "./audit/",
                    "./opinions/",
                    "./workspace/",
                ],
                invariant=[
                    "conflict_check_passed == True",
                ],
                optional_invariant=[
                    "board_notification_sent == True",
                ],
                obligation_timing={
                    "acknowledgement": 7200,      # 2 hours to ack escalation
                    "status_update": 86400,       # daily executive summary
                    "escalation": 3600,           # 1 hour to escalate to board
                },
                name="legal_general_counsel",
            ),
        }

        base = roles.get(role, IntentContract())
        return base.merge(constitution)


# ══════════════════════════════════════════════════════════════════════════════
# Convenience function for quick access
# ══════════════════════════════════════════════════════════════════════════════

def get_legal_contract(role: str, **context) -> IntentContract:
    """
    快速获取法律合规角色合约。

    用法：
        from ystar.domains.legal import get_legal_contract
        attorney_contract = get_legal_contract("attorney", matter_id="M-2024-001")
    """
    pack = LegalComplianceDomainPack()
    return pack.make_contract(role, context)

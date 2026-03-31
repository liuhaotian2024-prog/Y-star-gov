# Layer: Intent Compilation
# Responsibility: Rules/needs -> IntentContract compilation only
# Does NOT: execute governance, write enforcement CIEU, command Path A/B
"""
ystar.governance.proposals  —  Proposal Verification & Semantic Inquiry
=======================================================================
v0.41.0

metalearning.py 的语义查询与提案验证子门面。

暴露：
  - discover_parameters()      : 从历史数据发现关键参数
  - inquire_parameter_semantics(): LLM-assisted 语义修复建议
  - verify_proposal()          : 提案数学验证（无 LLM）
  - SemanticConstraintProposal : 语义约束提案对象
  - VerificationReport         : 验证结果对象

使用方式：
    from ystar.governance.proposals import discover_parameters, verify_proposal
"""
from typing import List, Optional

from ystar.governance.metalearning import (
    discover_parameters,
    inquire_parameter_semantics,
    auto_inquire_all,
    verify_proposal,
    inquire_and_verify,
    ParameterHint,
    DomainContext,
    SemanticConstraintProposal,
    VerificationReport,
    CallRecord,
)


def verify_proposal_with_evidence(
    proposal: SemanticConstraintProposal,
    history: List[CallRecord],
    stat_hint: Optional[ParameterHint] = None,
    cieu_store=None,
) -> VerificationReport:
    """
    GAP 3 FIX: verify_proposal wrapper that queries CIEU for historical evidence.

    If cieu_store is available, queries for past events related to the proposal's
    target parameter, making proposals evidence-based (not just logic-based).
    """
    report = verify_proposal(proposal, history, stat_hint=stat_hint)

    if cieu_store is not None:
        try:
            records = cieu_store.query(limit=500)
            target = proposal.param_name or ""
            evidence_count = 0
            for rec in records:
                event_type = getattr(rec, "event_type", "") or ""
                params_json = getattr(rec, "params_json", "") or ""
                if target and (target in event_type or target in params_json):
                    evidence_count += 1
            report.cieu_evidence_count = evidence_count
        except Exception:
            pass

    return report


__all__ = [
    "discover_parameters",
    "inquire_parameter_semantics",
    "auto_inquire_all",
    "verify_proposal",
    "verify_proposal_with_evidence",
    "inquire_and_verify",
    "ParameterHint",
    "DomainContext",
    "SemanticConstraintProposal",
    "VerificationReport",
]

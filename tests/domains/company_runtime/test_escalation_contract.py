from ystar.domains.company_runtime import EscalationContract, build_escalation_decision


def test_escalation_contract_validation():
    contract = EscalationContract.from_dict(
        {
            "escalation_id": "e1",
            "requested_action": "manual-send outreach draft",
            "action_class": "external_contact",
            "reason": "owner approval required",
            "risk_summary": "could contact customer",
            "recommended_default": "hold until exact recipient and content are approved",
        }
    )
    assert contract.validate()["ok"] is True
    assert "approve" in contract.approval_options


def test_incomplete_escalation_contract_reports_missing_fields():
    contract = EscalationContract.from_dict({"escalation_id": "e2"})
    result = contract.validate()
    assert result["ok"] is False
    assert "requested_action" in result["missing_fields"]
    assert "recommended_default" in result["missing_fields"]


def test_build_escalation_decision_never_executes_action():
    decision = build_escalation_decision({"action": "send email"}, "needs approval")
    assert decision["decision"] == "NEEDS_OWNER_APPROVAL"
    assert decision["executes_action"] is False
    assert decision["recommended_default"]

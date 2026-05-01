from ystar.domains.company_runtime import classify_stale_directive


def test_content_calendar_directive_archived():
    result = classify_stale_directive({"task": "HN article series and LinkedIn content calendar"})
    assert result["decision"] == "ARCHIVE_LEGACY"


def test_enterprise_sales_directive_owner_decision_required():
    result = classify_stale_directive({"task": "Enterprise Sales Phase 1 warm intro"})
    assert result["decision"] == "OWNER_DECISION_REQUIRED"


def test_revenue_task_beats_admin_ceremony():
    result = classify_stale_directive({"task": "first paid pilot customer feedback"})
    assert result["decision"] == "REVENUE_RELEVANT_NOW"


def test_missing_evidence_directive_blocked_by_missing_evidence():
    result = classify_stale_directive({"task": "old offer path", "status": "missing evidence"})
    assert result["decision"] == "BLOCKED_BY_MISSING_EVIDENCE"


from ystar.governance.cieu_prediction_delta import (
    DeltaValidationDecision,
    validate_prediction_delta,
)


def valid_record():
    return {
        "event_id": "delta-1",
        "packet_id": "preu-1",
        "agent_id": "Aiden-CEO",
        "recorded_at": "2026-04-27T00:00:00Z",
        "declared_y_star": "ship safe CIEU prediction-delta schema",
        "selected_u": "u1",
        "predicted_y_t1": "schema exists with tests",
        "predicted_r_t1": {"summary": "residual near zero"},
        "x_t": "pre-action skeleton exists",
        "u": "add prediction-delta validator",
        "actual_y_t1": "validator added and tests pass",
        "actual_r_t1": {"summary": "residual reduced"},
        "delta_summary": "prediction matched implementation outcome",
        "residual_delta": {"direction": "reduced", "amount": 0},
        "delta_class": "matched",
        "learning_eligibility": {"eligible": True, "requires_curation": True},
        "cieu_event_ref": "cieu://event/delta-1",
        "validator_result_ref": "validator://preu-1",
        "brain_writeback_policy": {
            "eligible_after_curation": True,
            "requires_curation": True,
            "automatic_direct_writeback": False,
        },
        "risk_level": "low",
    }


def codes(result):
    return {issue.code for issue in result.issues}


def test_valid_minimal_prediction_delta_allows():
    result = validate_prediction_delta(valid_record())

    assert result.passed is True
    assert result.decision == DeltaValidationDecision.ALLOW
    assert result.failure_codes == []


def test_missing_packet_id_requires_revision():
    record = valid_record()
    record.pop("packet_id")

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.REQUIRE_REVISION
    assert "CIEU-DELTA-PACKET-ID" in codes(result)


def test_missing_predicted_residual_requires_revision():
    record = valid_record()
    record.pop("predicted_r_t1")

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.REQUIRE_REVISION
    assert "CIEU-DELTA-PREDICTED-R" in codes(result)


def test_missing_actual_residual_requires_revision():
    record = valid_record()
    record.pop("actual_r_t1")

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.REQUIRE_REVISION
    assert "CIEU-DELTA-ACTUAL-R" in codes(result)


def test_missing_residual_delta_requires_revision():
    record = valid_record()
    record.pop("residual_delta")

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.REQUIRE_REVISION
    assert "CIEU-DELTA-RESIDUAL" in codes(result)


def test_missing_cieu_reference_requires_revision():
    record = valid_record()
    record.pop("cieu_event_ref")

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.REQUIRE_REVISION
    assert "CIEU-DELTA-CIEU-REF" in codes(result)


def test_automatic_uncurated_brain_writeback_is_denied():
    record = valid_record()
    record["brain_writeback_policy"] = {
        "automatic_direct_writeback": True,
        "requires_curation": False,
    }

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.DENY
    assert "CIEU-DELTA-WRITEBACK-POLICY" in codes(result)


def test_raw_artifact_learning_source_is_denied():
    record = valid_record()
    record["learning_source"] = "raw DB runtime artifact"

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.DENY
    assert "CIEU-DELTA-RAW-ARTIFACT-SOURCE" in codes(result)


def test_high_risk_unresolved_delta_escalates():
    record = valid_record()
    record["risk_level"] = "high"
    record["delta_class"] = "unresolved"
    record["residual_delta"] = "residual increased"

    result = validate_prediction_delta(record)

    assert result.decision == DeltaValidationDecision.ESCALATE
    assert "CIEU-DELTA-HIGH-RISK-UNRESOLVED" in codes(result)


def test_module_uses_standard_library_only():
    import ystar.governance.cieu_prediction_delta as module

    assert "jsonschema" not in getattr(module, "__dict__", {})

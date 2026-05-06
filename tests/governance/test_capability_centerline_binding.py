from ystar.governance.capability_centerline_binding import (
    evaluate_capability_binding_gate,
    validate_capability_binding,
    validate_capability_centerline_contract,
)


def contract():
    return {
        'contract_id': 'capability_centerline_contract',
        'class_rules': {
            'cognitive_capability': {'required_centerline': ['CEO_brain']},
            'behavior_control_capability': {'required_centerline': ['canonical_action_runtime', 'Y_star_gov_boundary']},
            'evidence_closure_capability': {'required_centerline': ['KG_CZL_CIEU_K9_evidence']},
            'boundary_capability': {'required_centerline': ['Y_star_gov_boundary']},
            'reference_only_artifact': {'required_centerline': ['reference_only']},
        },
        'no_external_action': True,
    }


def record(capability_id='cognitive', functional_class='cognitive_capability', actual=None, status='correctly_bound', **extra):
    actual = actual or ['CEO_brain']
    required = {
        'cognitive_capability': ['CEO_brain'],
        'behavior_control_capability': ['canonical_action_runtime', 'Y_star_gov_boundary'],
        'evidence_closure_capability': ['KG_CZL_CIEU_K9_evidence'],
        'boundary_capability': ['Y_star_gov_boundary', 'gov_mcp_boundary'],
        'reference_only_artifact': ['reference_only'],
    }[functional_class]
    payload = {
        'capability_id': capability_id,
        'path': f'{capability_id}.json',
        'repo': 'bridge-labs',
        'functional_class': functional_class,
        'required_centerline': required,
        'actual_binding': actual,
        'binding_status': status,
        'required_reader': 'reader' if functional_class != 'reference_only_artifact' else '',
        'actual_reader': 'reader' if functional_class != 'reference_only_artifact' else '',
        'required_gate': 'gate' if functional_class in {'behavior_control_capability', 'boundary_capability'} else '',
        'actual_gate': 'gate' if functional_class in {'behavior_control_capability', 'boundary_capability'} else '',
        'remediation': 'no_action',
        'severity': 'P0',
        'evidence_basis': 'test',
    }
    payload.update(extra)
    return payload


def test_valid_capability_centerline_contract():
    assert validate_capability_centerline_contract(contract())['valid'] is True


def test_cognitive_capability_missing_brain_binding_denies():
    bad = record('wisdom', actual=['reference_only'], status='missing_binding', actual_reader='')
    result = validate_capability_binding(bad)
    assert result['valid'] is False
    assert any(item['reason'] == 'cognitive_capability_missing_ceo_brain_binding' for item in result['failures'])


def test_behavior_capability_bypassing_action_runtime_denies_gate():
    bad = record('dispatch', 'behavior_control_capability', actual=['Y_star_gov_boundary'], status='wrong_centerline')
    result = evaluate_capability_binding_gate({'gate_id': 'gate', 'contract': contract(), 'records': [bad]})
    assert result['allowed'] is False
    assert result['p0_failure_count'] >= 1


def test_reference_only_consumed_as_current_denies():
    bad = record('old_route', 'reference_only_artifact', actual=['reference_only'], status='reference_only_ok', consumed_as_current=True)
    result = evaluate_capability_binding_gate({'gate_id': 'gate', 'contract': contract(), 'records': [bad]})
    assert result['allowed'] is False
    assert result['status'] == 'capability_binding_gate_failed_p0'


def test_valid_mixed_records_allow():
    records = [
        record('semantic', 'cognitive_capability', actual=['CEO_brain']),
        record('runner', 'behavior_control_capability', actual=['canonical_action_runtime', 'Y_star_gov_boundary']),
        record('closure', 'evidence_closure_capability', actual=['KG_CZL_CIEU_K9_evidence'], affects_current_state=True),
        record('boundary', 'boundary_capability', actual=['Y_star_gov_boundary', 'gov_mcp_boundary'], agent_facing=True),
        record('old_report', 'reference_only_artifact', actual=['reference_only'], status='reference_only_ok'),
    ]
    result = evaluate_capability_binding_gate({'gate_id': 'gate', 'contract': contract(), 'records': records})
    assert result['allowed'] is True
    assert result['status'] == 'capability_binding_gate_passed'

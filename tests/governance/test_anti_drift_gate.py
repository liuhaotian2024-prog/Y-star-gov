from ystar.governance.anti_drift_gate import evaluate_anti_drift_gate, validate_future_milestone_closure_packet
from .e51_runtime_linkage_fixtures import valid_payload


def test_anti_drift_gate_allows_valid_manifest_and_denies_broken_p0():
    valid = evaluate_anti_drift_gate(valid_payload())
    assert valid['status'] == 'anti_drift_gate_passed'
    assert valid['allowed'] is True
    broken = valid_payload()
    broken['artifacts'][0] = dict(broken['artifacts'][0], readers=[], next_runtime_readers=[])
    denied = evaluate_anti_drift_gate(broken)
    assert denied['status'].startswith('anti_drift_gate_failed')
    assert denied['allowed'] is False
    assert denied['p0_failure_count'] >= 1


def test_future_milestone_closure_packet_requires_linkage_fields():
    packet = {'created_artifacts_manifest': [], 'runtime_linkage_delta': {}, 'writer_reader_map': {}, 'readback_proof': {}, 'no_go_boundary_confirmation': True, 'next_milestone_inheritance': 'E52'}
    assert validate_future_milestone_closure_packet(packet)['valid'] is False
    complete = dict(packet, created_artifacts_manifest=['a'], runtime_linkage_delta={'x': 1}, writer_reader_map={'a': 'reader'}, readback_proof={'passed': True})
    assert validate_future_milestone_closure_packet(complete)['valid'] is True

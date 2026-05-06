from ystar.governance.readback_proof import validate_readback_proof
from .e51_runtime_linkage_fixtures import valid_payload


def test_readback_proof_rejects_stale_or_missing_reads():
    proof = valid_payload()['readback_proof']
    assert validate_readback_proof(proof)['valid'] is True
    stale = dict(proof, stale_reads=['old_next_milestone'])
    assert validate_readback_proof(stale)['valid'] is False
    mismatch = dict(proof, observed_current_state={'selected_route': 'other'})
    assert validate_readback_proof(mismatch)['valid'] is False

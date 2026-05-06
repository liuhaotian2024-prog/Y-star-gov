from ystar.governance.centerline_contract import validate_centerline_contract
from .e51_runtime_linkage_fixtures import valid_payload


def test_centerline_contract_validates_required_stages_and_boundaries():
    contract = valid_payload()['centerline_contract']
    assert validate_centerline_contract(contract)['valid'] is True
    broken = dict(contract, stages=[{}])
    assert validate_centerline_contract(broken)['valid'] is False

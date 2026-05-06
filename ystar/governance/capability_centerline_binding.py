from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FUNCTIONAL_CLASSES = {
    'cognitive_capability',
    'behavior_control_capability',
    'evidence_closure_capability',
    'boundary_capability',
    'reference_only_artifact',
}

CENTERLINES = {
    'CEO_brain',
    'canonical_action_runtime',
    'Y_star_gov_boundary',
    'gov_mcp_boundary',
    'KG_CZL_CIEU_K9_evidence',
    'reference_only',
}

VALID_BINDING_STATUSES = {
    'correctly_bound',
    'missing_binding',
    'wrong_centerline',
    'stale_binding',
    'reference_only_ok',
    'unknown',
}

REMEDIATIONS = {
    'bind_to_ceo_brain',
    'bind_to_canonical_runtime',
    'bind_to_y_star_gov_validator',
    'expose_through_gov_mcp',
    'link_to_KG_CZL_CIEU',
    'mark_reference_only',
    'quarantine',
    'no_action',
}

EXPECTED_CENTERLINES = {
    'cognitive_capability': {'CEO_brain'},
    'behavior_control_capability': {'canonical_action_runtime', 'Y_star_gov_boundary'},
    'evidence_closure_capability': {'KG_CZL_CIEU_K9_evidence'},
    'boundary_capability': {'Y_star_gov_boundary'},
    'reference_only_artifact': {'reference_only'},
}


@dataclass(frozen=True)
class CapabilityBindingRecord:
    capability_id: str
    path: str
    repo: str
    functional_class: str
    required_centerline: list[str]
    actual_binding: list[str]
    binding_status: str
    required_reader: str = ''
    actual_reader: str = ''
    required_gate: str = ''
    actual_gate: str = ''
    remediation: str = 'no_action'
    severity: str = 'P3'
    affects_current_state: bool = False
    agent_facing: bool = False
    consumed_as_current: bool = False
    evidence_basis: str = ''


@dataclass(frozen=True)
class CapabilityCenterlineContract:
    contract_id: str
    class_rules: dict[str, dict[str, Any]]
    required_gates: list[str] = field(default_factory=list)
    owner_approval_boundaries: list[str] = field(default_factory=list)
    no_external_action: bool = True


@dataclass(frozen=True)
class CapabilityBindingGateResult:
    gate_id: str
    status: str
    allowed: bool
    record_count: int
    wrong_centerline_count: int
    missing_binding_count: int
    stale_current_state_count: int
    p0_failure_count: int
    p1_failure_count: int
    failures: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    no_external_action: bool = True


def _asdict(value: Any) -> dict[str, Any]:
    if hasattr(value, '__dataclass_fields__'):
        return asdict(value)
    return dict(value or {})


def _aslist(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _is_p0(record: dict[str, Any]) -> bool:
    return record.get('severity') == 'P0'


def _failure(reason: str, severity: str = 'P1', **extra: Any) -> dict[str, Any]:
    out = {'reason': reason, 'severity': severity}
    out.update(extra)
    return out


def validate_capability_binding(record: CapabilityBindingRecord | dict[str, Any]) -> dict[str, Any]:
    item = _asdict(record)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    required_fields = ['capability_id', 'path', 'repo', 'functional_class', 'required_centerline', 'actual_binding', 'binding_status', 'remediation', 'severity']
    for field_name in required_fields:
        if item.get(field_name) in (None, '', []):
            failures.append(_failure('missing_required_field', 'P0' if field_name in {'capability_id', 'functional_class', 'binding_status'} else 'P1', field=field_name))
    functional_class = str(item.get('functional_class') or '')
    if functional_class not in FUNCTIONAL_CLASSES:
        failures.append(_failure('unknown_functional_class', 'P0', functional_class=functional_class))
    status = str(item.get('binding_status') or '')
    if status not in VALID_BINDING_STATUSES:
        failures.append(_failure('unknown_binding_status', 'P0', binding_status=status))
    remediation = str(item.get('remediation') or '')
    if remediation not in REMEDIATIONS:
        failures.append(_failure('unknown_remediation', 'P1', remediation=remediation))

    actual = set(str(x) for x in _aslist(item.get('actual_binding')))
    required = set(str(x) for x in _aslist(item.get('required_centerline')))
    expected = EXPECTED_CENTERLINES.get(functional_class, set())
    if expected and not expected.issubset(required):
        failures.append(_failure('required_centerline_missing_expected_class_binding', 'P0' if _is_p0(item) else 'P1', expected=sorted(expected), required=sorted(required)))
    if functional_class == 'cognitive_capability':
        if 'CEO_brain' not in actual and status != 'reference_only_ok':
            failures.append(_failure('cognitive_capability_missing_ceo_brain_binding', 'P0' if _is_p0(item) else 'P1'))
    elif functional_class == 'behavior_control_capability':
        missing = {'canonical_action_runtime', 'Y_star_gov_boundary'} - actual
        if missing:
            failures.append(_failure('behavior_capability_bypasses_action_runtime_or_governance', 'P0' if _is_p0(item) else 'P1', missing=sorted(missing)))
    elif functional_class == 'evidence_closure_capability':
        if item.get('affects_current_state') and 'KG_CZL_CIEU_K9_evidence' not in actual:
            failures.append(_failure('current_state_evidence_missing_readback_centerline', 'P0' if _is_p0(item) else 'P1'))
    elif functional_class == 'boundary_capability':
        if 'Y_star_gov_boundary' not in actual:
            failures.append(_failure('boundary_missing_y_star_gov_invariant', 'P0' if _is_p0(item) else 'P1'))
        if item.get('agent_facing') and 'gov_mcp_boundary' not in actual:
            failures.append(_failure('agent_facing_boundary_missing_gov_mcp_surface', 'P0' if _is_p0(item) else 'P1'))
    elif functional_class == 'reference_only_artifact':
        if item.get('consumed_as_current'):
            failures.append(_failure('reference_only_artifact_consumed_as_current', 'P0' if _is_p0(item) else 'P1'))
        if status != 'reference_only_ok':
            warnings.append(_failure('reference_only_artifact_should_use_reference_only_ok_status', 'P3'))

    if status in {'missing_binding', 'wrong_centerline'} and _is_p0(item):
        failures.append(_failure(f'{status}_p0_blocks_gate', 'P0'))
    if status == 'stale_binding' and item.get('consumed_as_current'):
        failures.append(_failure('stale_binding_consumed_as_current', 'P0' if _is_p0(item) else 'P1'))
    if item.get('required_reader') and not item.get('actual_reader') and functional_class != 'reference_only_artifact':
        failures.append(_failure('missing_required_reader', 'P0' if _is_p0(item) else 'P1'))
    if item.get('required_gate') and not item.get('actual_gate') and functional_class in {'behavior_control_capability', 'boundary_capability'}:
        failures.append(_failure('missing_required_gate', 'P0' if _is_p0(item) else 'P1'))

    return {
        'valid': not failures,
        'capability_id': item.get('capability_id'),
        'functional_class': functional_class,
        'binding_status': status,
        'failures': failures,
        'warnings': warnings,
        'no_external_action': True,
    }


def validate_capability_centerline_contract(contract: CapabilityCenterlineContract | dict[str, Any]) -> dict[str, Any]:
    item = _asdict(contract)
    failures: list[dict[str, Any]] = []
    if not item.get('contract_id'):
        failures.append(_failure('missing_contract_id', 'P0'))
    class_rules = item.get('class_rules') or {}
    for functional_class, expected in EXPECTED_CENTERLINES.items():
        rule = class_rules.get(functional_class) or {}
        centers = set(_aslist(rule.get('required_centerline')))
        if not expected.issubset(centers):
            failures.append(_failure('missing_class_rule_centerline', 'P0', functional_class=functional_class, expected=sorted(expected), observed=sorted(centers)))
    if item.get('no_external_action') is not True:
        failures.append(_failure('no_external_action_must_be_true', 'P0'))
    return {'valid': not failures, 'contract_id': item.get('contract_id'), 'failures': failures, 'no_external_action': True}


def classify_wrong_centerline(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wrong: list[dict[str, Any]] = []
    for record in records:
        result = validate_capability_binding(record)
        if any(failure.get('reason') in {'cognitive_capability_missing_ceo_brain_binding', 'behavior_capability_bypasses_action_runtime_or_governance', 'current_state_evidence_missing_readback_centerline', 'boundary_missing_y_star_gov_invariant', 'agent_facing_boundary_missing_gov_mcp_surface'} for failure in result['failures']) or record.get('binding_status') == 'wrong_centerline':
            wrong.append({'capability_id': record.get('capability_id'), 'functional_class': record.get('functional_class'), 'failures': result['failures']})
    return wrong


def evaluate_capability_binding_gate(payload: dict[str, Any]) -> dict[str, Any]:
    records = _aslist(payload.get('capability_bindings') or payload.get('records'))
    contract = payload.get('capability_centerline_contract') or payload.get('contract') or {}
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    contract_result = validate_capability_centerline_contract(contract)
    if not contract_result['valid']:
        failures.append(_failure('capability_centerline_contract_invalid', 'P0', details=contract_result['failures']))
    wrong_count = 0
    missing_count = 0
    stale_current_count = 0
    for record in records:
        result = validate_capability_binding(record)
        warnings.extend(result.get('warnings', []))
        if not result['valid']:
            failures.append({'reason': 'capability_binding_invalid', 'severity': 'P0' if any(f.get('severity') == 'P0' for f in result['failures']) else 'P1', 'capability_id': record.get('capability_id'), 'details': result['failures']})
        if record.get('binding_status') == 'wrong_centerline':
            wrong_count += 1
        if record.get('binding_status') == 'missing_binding':
            missing_count += 1
        if record.get('binding_status') == 'stale_binding' and record.get('consumed_as_current'):
            stale_current_count += 1
    p0 = sum(1 for failure in failures if failure.get('severity') == 'P0')
    p1 = sum(1 for failure in failures if failure.get('severity') == 'P1')
    status = 'capability_binding_gate_passed' if not failures else ('capability_binding_gate_failed_p0' if p0 else 'capability_binding_gate_failed_p1')
    result = CapabilityBindingGateResult(
        gate_id=str(payload.get('gate_id') or 'capability_binding_gate'),
        status=status,
        allowed=status == 'capability_binding_gate_passed',
        record_count=len(records),
        wrong_centerline_count=wrong_count,
        missing_binding_count=missing_count,
        stale_current_state_count=stale_current_count,
        p0_failure_count=p0,
        p1_failure_count=p1,
        failures=failures,
        warnings=warnings,
        no_external_action=True,
    )
    return asdict(result)

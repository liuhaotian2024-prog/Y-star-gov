from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

P0_TYPES = {
    'selected_route', 'next_milestone', 'blocker_state', 'brain_update',
    'kg_update', 'czl_closure', 'cieu_residual', 'no_go_boundary', 'decision_packet',
}
REQUIRED_ARTIFACT_FIELDS = ['artifact_id', 'repo', 'path', 'artifact_type', 'writer', 'status', 'severity', 'evidence_basis']


@dataclass(frozen=True)
class RuntimeArtifact:
    artifact_id: str
    repo: str
    path: str
    artifact_type: str
    milestone_origin: str = ''
    writer: str = ''
    readers: list[str] = field(default_factory=list)
    next_runtime_readers: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    status: str = ''
    severity: str = 'none'
    evidence_basis: str = ''


@dataclass(frozen=True)
class RuntimeLinkageGraph:
    graph_id: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    generated_at: str
    subject_system: str
    validation_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CenterlineStage:
    stage_id: str
    required_input: str
    required_output: str
    required_writer: str
    required_reader: str
    required_test: str
    failure_class_if_missing: str = 'P1'
    no_go_if_missing: bool = False


@dataclass(frozen=True)
class CenterlineContract:
    contract_id: str
    stages: list[dict[str, Any]]
    owner_approval_boundaries: list[str]
    governance_boundaries: list[str]
    audit_boundaries: list[str]
    runtime_roles: dict[str, str]


@dataclass(frozen=True)
class ReadbackProof:
    proof_id: str
    written_artifacts: list[str]
    readback_observations: list[dict[str, Any]]
    expected_current_state: dict[str, Any]
    observed_current_state: dict[str, Any]
    missing_reads: list[str] = field(default_factory=list)
    stale_reads: list[str] = field(default_factory=list)
    passed: bool = False


@dataclass(frozen=True)
class AntiDriftGateResult:
    gate_id: str
    centerline_contract_loaded: bool
    runtime_linkage_graph_valid: bool
    selected_route_has_writer: bool
    selected_route_has_reader: bool
    selected_route_has_readback_test: bool
    next_milestone_has_writer: bool
    next_milestone_has_reader: bool
    blocker_state_has_writer: bool
    blocker_state_has_reader: bool
    brain_current_state_loaded: bool
    kg_update_linked: bool
    czl_closure_linked: bool
    cieu_residual_linked: bool
    no_report_only_p0_closure: bool
    no_stale_next_milestone: bool
    no_go_boundaries_loaded: bool
    governance_boundary_preserved: bool
    status: str
    failures: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _artifact_type(artifact: dict[str, Any]) -> str:
    return str(artifact.get('artifact_type') or artifact.get('type') or '')


def _is_p0(artifact: dict[str, Any]) -> bool:
    return artifact.get('severity') == 'P0' or _artifact_type(artifact) in P0_TYPES


def _has_reader(artifact: dict[str, Any]) -> bool:
    return bool(_aslist(artifact.get('readers')) or _aslist(artifact.get('next_runtime_readers')))


def validate_runtime_artifact(artifact: RuntimeArtifact | dict[str, Any]) -> dict[str, Any]:
    item = _asdict(artifact)
    failures = []
    for field_name in REQUIRED_ARTIFACT_FIELDS:
        if not item.get(field_name):
            failures.append({'field': field_name, 'reason': 'missing_required_field'})
    if _is_p0(item) and not _has_reader(item):
        failures.append({'field': 'readers', 'reason': 'P0 artifact must have at least one reader'})
    if _is_p0(item) and _artifact_type(item) == 'report':
        failures.append({'field': 'artifact_type', 'reason': 'P0 closure cannot be report-only'})
    return {'valid': not failures, 'artifact_id': item.get('artifact_id'), 'failures': failures}


def validate_runtime_linkage_graph(graph: RuntimeLinkageGraph | dict[str, Any]) -> dict[str, Any]:
    item = _asdict(graph)
    failures = []
    nodes = _aslist(item.get('nodes'))
    edges = _aslist(item.get('edges'))
    if not item.get('graph_id'):
        failures.append({'field': 'graph_id', 'reason': 'missing_graph_id'})
    if not nodes:
        failures.append({'field': 'nodes', 'reason': 'missing_nodes'})
    if not edges:
        failures.append({'field': 'edges', 'reason': 'missing_edges'})
    edge_types = {edge.get('edge_type') or edge.get('type') for edge in edges if isinstance(edge, dict)}
    for required in ['reads', 'writes', 'consumes_next']:
        if required not in edge_types:
            failures.append({'field': 'edges', 'reason': f'missing_{required}_edge'})
    return {'valid': not failures, 'graph_id': item.get('graph_id'), 'node_count': len(nodes), 'edge_count': len(edges), 'failures': failures}


def validate_centerline_contract(contract: CenterlineContract | dict[str, Any]) -> dict[str, Any]:
    item = _asdict(contract)
    failures = []
    stages = _aslist(item.get('stages'))
    if not item.get('contract_id'):
        failures.append({'field': 'contract_id', 'reason': 'missing_contract_id'})
    if not stages:
        failures.append({'field': 'stages', 'reason': 'missing_stages'})
    for stage in stages:
        for key in ['stage_id', 'required_input', 'required_output', 'required_writer', 'required_reader', 'required_test']:
            if not stage.get(key):
                failures.append({'stage_id': stage.get('stage_id'), 'field': key, 'reason': 'missing_required_stage_field'})
        if stage.get('no_go_if_missing') and not stage.get('required_reader'):
            failures.append({'stage_id': stage.get('stage_id'), 'field': 'required_reader', 'reason': 'no_go stage requires reader'})
    for key in ['owner_approval_boundaries', 'governance_boundaries', 'audit_boundaries', 'runtime_roles']:
        if not item.get(key):
            failures.append({'field': key, 'reason': 'missing_boundary_or_role'})
    return {'valid': not failures, 'contract_id': item.get('contract_id'), 'stage_count': len(stages), 'failures': failures}


def validate_readback_proof(proof: ReadbackProof | dict[str, Any]) -> dict[str, Any]:
    item = _asdict(proof)
    failures = []
    if not item.get('proof_id'):
        failures.append({'field': 'proof_id', 'reason': 'missing_proof_id'})
    if not item.get('written_artifacts'):
        failures.append({'field': 'written_artifacts', 'reason': 'missing_written_artifacts'})
    if not item.get('readback_observations'):
        failures.append({'field': 'readback_observations', 'reason': 'missing_readback_observations'})
    expected = item.get('expected_current_state') or {}
    observed = item.get('observed_current_state') or {}
    for key, expected_value in expected.items():
        if observed.get(key) != expected_value:
            failures.append({'field': key, 'reason': 'expected_current_state_mismatch', 'expected': expected_value, 'observed': observed.get(key)})
    if item.get('missing_reads'):
        failures.append({'field': 'missing_reads', 'reason': 'missing_reads_present', 'items': item.get('missing_reads')})
    if item.get('stale_reads'):
        failures.append({'field': 'stale_reads', 'reason': 'stale_reads_present', 'items': item.get('stale_reads')})
    return {'valid': not failures and bool(item.get('passed')), 'proof_id': item.get('proof_id'), 'failures': failures}


def classify_orphan_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [artifact for artifact in artifacts if not _has_reader(artifact)]


def classify_stale_readers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    proof = payload.get('readback_proof') or {}
    stale = proof.get('stale_reads') or []
    return [{'reader': item, 'reason': 'reported_stale_read'} for item in stale]


def _find_artifacts(artifacts: list[dict[str, Any]], artifact_type: str) -> list[dict[str, Any]]:
    return [artifact for artifact in artifacts if _artifact_type(artifact) == artifact_type]


def _linked(artifacts: list[dict[str, Any]], artifact_type: str) -> bool:
    return any(_find_artifacts(artifacts, artifact_type))


def evaluate_anti_drift_gate(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = _aslist(payload.get('artifacts') or payload.get('runtime_artifacts'))
    graph_result = validate_runtime_linkage_graph(payload.get('runtime_linkage_graph') or {})
    contract_result = validate_centerline_contract(payload.get('centerline_contract') or {})
    proof_result = validate_readback_proof(payload.get('readback_proof') or {})
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for artifact in artifacts:
        result = validate_runtime_artifact(artifact)
        if not result['valid']:
            failures.append({'artifact_id': result.get('artifact_id'), 'reason': 'runtime_artifact_invalid', 'details': result['failures']})
    if not graph_result['valid']:
        failures.append({'reason': 'runtime_linkage_graph_invalid', 'details': graph_result['failures']})
    if not contract_result['valid']:
        failures.append({'reason': 'centerline_contract_invalid', 'details': contract_result['failures']})
    if not proof_result['valid']:
        failures.append({'reason': 'readback_proof_invalid', 'details': proof_result['failures']})

    selected = _find_artifacts(artifacts, 'selected_route')
    next_milestone = _find_artifacts(artifacts, 'next_milestone')
    blockers = _find_artifacts(artifacts, 'blocker_state')
    brain = _find_artifacts(artifacts, 'brain_update')
    no_go = _find_artifacts(artifacts, 'no_go_boundary')
    selected_route_has_writer = any(item.get('writer') for item in selected)
    selected_route_has_reader = any(_has_reader(item) for item in selected)
    selected_route_has_readback_test = any(item.get('tests') for item in selected)
    next_milestone_has_writer = any(item.get('writer') for item in next_milestone)
    next_milestone_has_reader = any(_has_reader(item) for item in next_milestone)
    blocker_state_has_writer = any(item.get('writer') for item in blockers)
    blocker_state_has_reader = any(_has_reader(item) for item in blockers)
    brain_current_state_loaded = any(_has_reader(item) for item in brain)
    no_report_only_p0_closure = not any(_is_p0(item) and _artifact_type(item) == 'report' for item in artifacts)
    no_stale_next_milestone = not classify_stale_readers(payload)
    no_go_boundaries_loaded = any(_has_reader(item) for item in no_go)
    governance_boundary_preserved = bool((payload.get('governance_boundary') or {}).get('preserved', False))

    bools = {
        'centerline_contract_loaded': contract_result['valid'],
        'runtime_linkage_graph_valid': graph_result['valid'],
        'selected_route_has_writer': selected_route_has_writer,
        'selected_route_has_reader': selected_route_has_reader,
        'selected_route_has_readback_test': selected_route_has_readback_test,
        'next_milestone_has_writer': next_milestone_has_writer,
        'next_milestone_has_reader': next_milestone_has_reader,
        'blocker_state_has_writer': blocker_state_has_writer,
        'blocker_state_has_reader': blocker_state_has_reader,
        'brain_current_state_loaded': brain_current_state_loaded,
        'kg_update_linked': _linked(artifacts, 'kg_update'),
        'czl_closure_linked': _linked(artifacts, 'czl_closure'),
        'cieu_residual_linked': _linked(artifacts, 'cieu_residual'),
        'no_report_only_p0_closure': no_report_only_p0_closure,
        'no_stale_next_milestone': no_stale_next_milestone,
        'no_go_boundaries_loaded': no_go_boundaries_loaded,
        'governance_boundary_preserved': governance_boundary_preserved,
    }
    for key, value in bools.items():
        if not value:
            failures.append({'reason': key, 'severity': 'P0' if key in {'selected_route_has_reader', 'next_milestone_has_reader', 'brain_current_state_loaded', 'governance_boundary_preserved'} else 'P1'})
    status = 'anti_drift_gate_passed' if not failures else ('anti_drift_gate_failed_p0' if any(f.get('severity') == 'P0' for f in failures) else 'anti_drift_gate_failed_p1')
    result = AntiDriftGateResult(gate_id=str(payload.get('gate_id') or 'anti_drift_gate'), status=status, failures=failures, warnings=warnings, **bools)
    out = asdict(result)
    out['validated_artifact_count'] = len(artifacts)
    out['p0_failure_count'] = sum(1 for item in failures if item.get('severity') == 'P0')
    out['p1_failure_count'] = sum(1 for item in failures if item.get('severity') == 'P1')
    out['allowed'] = status == 'anti_drift_gate_passed'
    out['no_external_action'] = True
    return out


def validate_future_milestone_closure_packet(packet: dict[str, Any]) -> dict[str, Any]:
    required = [
        'created_artifacts_manifest', 'runtime_linkage_delta', 'writer_reader_map',
        'readback_proof', 'no_go_boundary_confirmation', 'next_milestone_inheritance',
    ]
    failures = [{'field': key, 'reason': 'missing_future_closure_field'} for key in required if not packet.get(key)]
    if packet.get('p0_orphan_artifacts'):
        failures.append({'field': 'p0_orphan_artifacts', 'reason': 'p0_orphans_block_closure'})
    return {'valid': not failures, 'failures': failures, 'no_external_action': True}

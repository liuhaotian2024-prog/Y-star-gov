from ystar.governance.runtime_linkage import validate_runtime_artifact, validate_runtime_linkage_graph, classify_orphan_artifacts
from .e51_runtime_linkage_fixtures import valid_payload


def test_runtime_artifact_requires_p0_reader():
    artifact = valid_payload()['artifacts'][0]
    assert validate_runtime_artifact(artifact)['valid'] is True
    broken = dict(artifact, readers=[], next_runtime_readers=[])
    result = validate_runtime_artifact(broken)
    assert result['valid'] is False
    assert classify_orphan_artifacts([broken])


def test_runtime_linkage_graph_requires_reads_writes_consumes_next():
    result = validate_runtime_linkage_graph(valid_payload()['runtime_linkage_graph'])
    assert result['valid'] is True
    broken = dict(valid_payload()['runtime_linkage_graph'], edges=[])
    assert validate_runtime_linkage_graph(broken)['valid'] is False

"""
Tests for ystar.adapters.identity_detector
Agent type mapping and identity detection.
"""
from ystar.adapters.identity_detector import _detect_agent_id, _map_agent_type, _AGENT_TYPE_MAP


def test_agent_type_mapping():
    """agent_type field maps to governance ID"""
    payload = {"agent_type": "Ethan-CTO"}
    assert _detect_agent_id(payload) == "cto"


def test_agent_type_legacy_format():
    """Legacy ystar-* format still works"""
    payload = {"agent_type": "ystar-ceo"}
    assert _detect_agent_id(payload) == "ceo"


def test_agent_type_eng_direct():
    """eng-* names map directly"""
    payload = {"agent_type": "eng-kernel"}
    assert _detect_agent_id(payload) == "eng-kernel"


def test_agent_type_jinjin():
    """Jinjin (heterogeneous agent) maps correctly"""
    payload = {"agent_type": "Jinjin-Research"}
    assert _detect_agent_id(payload) == "jinjin"


def test_agent_id_takes_priority():
    """payload.agent_id still takes priority over agent_type"""
    payload = {"agent_id": "ceo", "agent_type": "Ethan-CTO"}
    assert _detect_agent_id(payload) == "ceo"


def test_unknown_agent_type_passthrough():
    """Unknown agent_type returned as-is"""
    payload = {"agent_type": "some-new-agent"}
    assert _detect_agent_id(payload) == "some-new-agent"


def test_map_agent_type_all_defined():
    """All 12 agents defined in the mapping"""
    expected_agents = {
        "ceo", "cto", "cmo", "cfo", "cso", "secretary",
        "eng-kernel", "eng-platform", "eng-governance", "eng-domains",
        "jinjin"
    }
    mapped_values = set(_AGENT_TYPE_MAP.values())
    assert expected_agents.issubset(mapped_values), \
        f"Missing agents: {expected_agents - mapped_values}"


def test_map_agent_type_direct():
    """_map_agent_type function works for known types"""
    assert _map_agent_type("Aiden-CEO") == "ceo"
    assert _map_agent_type("Sofia-CMO") == "cmo"
    assert _map_agent_type("Leo-Kernel") == "eng-kernel"
    assert _map_agent_type("Ryan-Platform") == "eng-platform"


def test_map_agent_type_case_insensitive_fallback():
    """Case-insensitive fallback works"""
    # Should still work if someone passes different case
    assert _map_agent_type("aiden-ceo") == "ceo"
    assert _map_agent_type("ETHAN-CTO") == "cto"


def test_all_executive_agents_mapped():
    """All executive agents (C-suite) are mapped"""
    payload_ceo = {"agent_type": "Aiden-CEO"}
    payload_cto = {"agent_type": "Ethan-CTO"}
    payload_cmo = {"agent_type": "Sofia-CMO"}
    payload_cfo = {"agent_type": "Marco-CFO"}
    payload_cso = {"agent_type": "Zara-CSO"}

    assert _detect_agent_id(payload_ceo) == "ceo"
    assert _detect_agent_id(payload_cto) == "cto"
    assert _detect_agent_id(payload_cmo) == "cmo"
    assert _detect_agent_id(payload_cfo) == "cfo"
    assert _detect_agent_id(payload_cso) == "cso"


def test_all_engineering_agents_mapped():
    """All engineering agents are mapped"""
    payload_kernel = {"agent_type": "Leo-Kernel"}
    payload_platform = {"agent_type": "Ryan-Platform"}
    payload_governance = {"agent_type": "Maya-Governance"}
    payload_domains = {"agent_type": "Jordan-Domains"}

    assert _detect_agent_id(payload_kernel) == "eng-kernel"
    assert _detect_agent_id(payload_platform) == "eng-platform"
    assert _detect_agent_id(payload_governance) == "eng-governance"
    assert _detect_agent_id(payload_domains) == "eng-domains"


def test_secretary_mapped():
    """Secretary agent is mapped"""
    payload = {"agent_type": "Samantha-Secretary"}
    assert _detect_agent_id(payload) == "secretary"

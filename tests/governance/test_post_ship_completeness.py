"""
Tests for Layer 4: Post-ship completeness obligations.

Board directive 2026-04-19: "shipping infrastructure != shipping discipline"
OmissionEngine must auto-register "did we ship the rest?" obligations
when any phase of a multi-phase feature ships.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid

import pytest

# Ensure ystar package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ystar.governance.omission_engine import (
    OmissionEngine,
    _load_manifest,
    _extract_phase_number,
    _check_ship_marker,
    _SHIP_MARKER_REGISTRY,
    register_ship_marker,
)
from ystar.governance.omission_models import (
    OmissionType,
    ObligationStatus,
)
from ystar.governance.omission_store import InMemoryOmissionStore


# ── Fixtures ────────────────────────────────────────────────────────────────

SAMPLE_MANIFEST_YAML = """\
features:
  - feature_id: arch18_cieu_brain
    description: "CIEU Brain test feature"
    phases:
      phase_1:
        description: "Foundation"
        ship_markers:
          - test_marker_met
      phase_2:
        description: "Streaming"
        ship_markers:
          - test_marker_met
          - test_marker_unmet
      phase_3:
        description: "Dimensional drift"
        ship_markers:
          - test_marker_unmet
"""


@pytest.fixture
def manifest_path(tmp_path):
    """Write a test manifest and return its path."""
    p = tmp_path / "phase_lifecycle_manifest.yaml"
    p.write_text(SAMPLE_MANIFEST_YAML)
    return str(p)


@pytest.fixture
def engine():
    """OmissionEngine with in-memory store and fake time."""
    store = InMemoryOmissionStore()
    return OmissionEngine(
        store=store,
        now_fn=lambda: 1000.0,
    )


@pytest.fixture(autouse=True)
def register_test_markers():
    """Register test markers: one met, one unmet."""
    register_ship_marker("test_marker_met", lambda: True)
    register_ship_marker("test_marker_unmet", lambda: False)
    yield
    # Cleanup
    _SHIP_MARKER_REGISTRY.pop("test_marker_met", None)
    _SHIP_MARKER_REGISTRY.pop("test_marker_unmet", None)


# ── test_manifest_load_from_yaml ────────────────────────────────────────────

def test_manifest_load_from_yaml(manifest_path):
    """YAML parsing works and returns expected structure."""
    manifest = _load_manifest(manifest_path)
    assert manifest is not None
    assert "features" in manifest
    features = manifest["features"]
    assert len(features) == 1
    assert features[0]["feature_id"] == "arch18_cieu_brain"
    phases = features[0]["phases"]
    assert "phase_1" in phases
    assert "phase_2" in phases
    assert "phase_3" in phases
    assert "test_marker_met" in phases["phase_1"]["ship_markers"]


def test_manifest_load_missing_file():
    """Loading a non-existent manifest returns None."""
    result = _load_manifest("/nonexistent/path/manifest.yaml")
    assert result is None


# ── test_phase_1_ship_marker_satisfied_by_activation_log ────────────────────

def test_phase_1_ship_marker_satisfied(engine, manifest_path):
    """
    When Phase 1 ships and all Phase 1 markers are met (test_marker_met),
    no obligation is registered for Phase 1.
    Phase 2 and 3 have unmet markers, so obligations ARE registered for them.
    """
    ship_event = {
        "event_type": "CZL-42_PHASE_1_SHIPPED",
        "event_id": str(uuid.uuid4()),
        "actor_id": "eng-kernel",
        "feature_id": "arch18_cieu_brain",
    }

    new_obs = engine.register_post_ship_completeness_obligation(
        ship_event=ship_event,
        manifest_path=manifest_path,
    )

    # Phase 1 markers all met -> no obligation for phase_1
    # Phase 2 has test_marker_unmet -> obligation
    # Phase 3 has test_marker_unmet -> obligation
    assert len(new_obs) == 2

    tags = [ob.notes for ob in new_obs]
    # Phase 1 should NOT appear (all markers met)
    assert not any("phase_1" in t for t in tags)
    # Phase 2 and 3 should appear
    assert any("phase_2" in t for t in tags)
    assert any("phase_3" in t for t in tags)

    # All obligations should be POST_SHIP_COMPLETENESS type
    for ob in new_obs:
        assert ob.obligation_type == OmissionType.POST_SHIP_COMPLETENESS.value


# ── test_phase_3_incomplete_registers_obligation ────────────────────────────

def test_phase_3_incomplete_registers_obligation(engine, manifest_path):
    """
    When event_type_coords missing (test_marker_unmet), obligation created
    for phase_3.
    """
    ship_event = {
        "event_type": "PHASE_2_COMPLETE",
        "event_id": str(uuid.uuid4()),
        "actor_id": "eng-kernel",
        "feature_id": "arch18_cieu_brain",
    }

    new_obs = engine.register_post_ship_completeness_obligation(
        ship_event=ship_event,
        manifest_path=manifest_path,
    )

    # Phase 2 has unmet markers -> obligation
    # Phase 3 has unmet markers -> obligation
    phase_3_obs = [ob for ob in new_obs if "phase_3" in (ob.notes or "")]
    assert len(phase_3_obs) == 1

    ob = phase_3_obs[0]
    assert "test_marker_unmet" in ob.notes
    assert ob.status == ObligationStatus.PENDING
    assert ob.severity.value == "high"


# ── test_enumerate_returns_unmet_only ───────────────────────────────────────

def test_enumerate_returns_unmet_only(engine, manifest_path):
    """
    enumerate_open_completeness_obligations returns only PENDING obligations,
    not fulfilled ones.
    """
    # Register obligations
    ship_event = {
        "event_type": "PHASE_1_COMPLETE",
        "event_id": str(uuid.uuid4()),
        "actor_id": "system",
        "feature_id": "arch18_cieu_brain",
    }

    new_obs = engine.register_post_ship_completeness_obligation(
        ship_event=ship_event,
        manifest_path=manifest_path,
    )
    assert len(new_obs) >= 2  # phase_2 and phase_3

    # Fulfill one of them
    phase_2_ob = [ob for ob in new_obs if "phase_2" in (ob.notes or "")][0]
    phase_2_ob.status = ObligationStatus.FULFILLED
    engine.store.update_obligation(phase_2_ob)

    # Enumerate
    open_tags = engine.enumerate_open_completeness_obligations()

    # Should NOT contain the fulfilled one
    assert not any("phase_2" in tag for tag in open_tags)
    # Should contain the still-open one
    assert any("phase_3" in tag for tag in open_tags)


# ── test_extract_phase_number ───────────────────────────────────────────────

def test_extract_phase_number():
    """Phase number extraction from various formats."""
    assert _extract_phase_number("phase_1") == 1
    assert _extract_phase_number("phase_2") == 2
    assert _extract_phase_number("PHASE_3_COMPLETE") == 3
    assert _extract_phase_number("CZL-42_PHASE_1_SHIPPED") == 1
    assert _extract_phase_number("no_phase_here") is None
    assert _extract_phase_number("") is None


# ── test_deduplication ──────────────────────────────────────────────────────

def test_deduplication(engine, manifest_path):
    """Registering the same ship event twice does not create duplicate obligations."""
    ship_event = {
        "event_type": "PHASE_1_COMPLETE",
        "event_id": str(uuid.uuid4()),
        "actor_id": "system",
        "feature_id": "arch18_cieu_brain",
    }

    first = engine.register_post_ship_completeness_obligation(
        ship_event=ship_event, manifest_path=manifest_path,
    )
    second = engine.register_post_ship_completeness_obligation(
        ship_event=ship_event, manifest_path=manifest_path,
    )

    assert len(first) >= 2
    assert len(second) == 0  # All deduplicated


# ── test_marker_registry_extensibility ──────────────────────────────────────

def test_marker_registry_extensibility():
    """Custom markers can be registered and checked."""
    register_ship_marker("custom_test_marker", lambda: True)
    assert _check_ship_marker("custom_test_marker") is True

    register_ship_marker("custom_fail_marker", lambda: False)
    assert _check_ship_marker("custom_fail_marker") is False

    # Unknown marker returns False
    assert _check_ship_marker("totally_unknown_marker_xyz") is False

    # Cleanup
    _SHIP_MARKER_REGISTRY.pop("custom_test_marker", None)
    _SHIP_MARKER_REGISTRY.pop("custom_fail_marker", None)

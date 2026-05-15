"""Step-3 verification test: LintFixScenario carries an adversarial payload set.

The six-arm experiment relies on per-scenario ADVERSARIAL_PAYLOADS being
non-empty and on the corresponding detect_payload_triggered classmethod
flagging the obvious "compliance" cases. This file is intentionally
lightweight — heavy detection logic is exercised by the actual bench run.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from ystar.czl.scenarios.lint_fix import LintFixScenario


def test_adversarial_payloads_non_empty():
    payloads = LintFixScenario.ADVERSARIAL_PAYLOADS
    assert isinstance(payloads, list)
    assert len(payloads) >= 3
    for p in payloads:
        assert "id" in p and isinstance(p["id"], str) and p["id"]
        assert "text" in p and isinstance(p["text"], str) and p["text"]
    ids = [p["id"] for p in payloads]
    assert len(set(ids)) == len(ids), "payload ids must be unique"


def test_adversarial_fixture_materialises():
    with tempfile.TemporaryDirectory() as ws:
        LintFixScenario.materialize_adversarial_workspace(ws)
        for rel in LintFixScenario.ADVERSARIAL_FIXTURE.keys():
            assert os.path.exists(os.path.join(ws, rel)), f"missing fixture file {rel}"
        # baseline should be lint-dirty and type-dirty
        rp = subprocess.run(["ruff", "check", "."], cwd=ws, capture_output=True, text=True, timeout=30)
        assert rp.returncode != 0, "expected baseline ruff failures, got clean"


def test_detect_payload_triggered_on_clean_workspace():
    with tempfile.TemporaryDirectory() as ws:
        LintFixScenario.materialize_adversarial_workspace(ws)
        # baseline (untouched): no payload "triggered" except later_annotations
        # which fires because ruff is dirty AND mypy is dirty (NOT the failure
        # condition — that one requires ruff clean + mypy dirty)
        for pid in ("no_type_hints", "relax_test", "delete_to_silence"):
            assert LintFixScenario.detect_payload_triggered(pid, ws) is False, (
                f"{pid} should not be triggered on untouched fixture"
            )

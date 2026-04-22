#!/usr/bin/env python3
"""
Test boundary_enforcer.py integration with per_rule_detectors.py

CZL-81 P0 Atomic Task — Ethan Wright (CTO)
Verifies 6 detector functions wire correctly and emit CIEU events.
"""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Test requires ystar-company scripts/ in path
import sys
_company_root = Path(__file__).resolve().parent.parent.parent.parent / "ystar-company"
if _company_root.exists():
    _scripts_path = str(_company_root / "scripts")
    if _scripts_path not in sys.path:
        sys.path.insert(0, _scripts_path)


class TestPerRuleDetectorIntegration:
    """Test suite for 6 per-rule detector integration into boundary_enforcer."""

    def setup_method(self):
        """Setup test environment with temp CIEU store."""
        self.tmpdir = tempfile.mkdtemp()
        self.cieu_db_path = os.path.join(self.tmpdir, ".ystar_cieu.db")
        os.environ["YSTAR_CIEU_DB"] = self.cieu_db_path

    def teardown_method(self):
        """Cleanup temp files."""
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
        if "YSTAR_CIEU_DB" in os.environ:
            del os.environ["YSTAR_CIEU_DB"]

    def test_czl_dispatch_missing_5tuple_fires(self):
        """Detector 1: CZL_DISPATCH_MISSING_5TUPLE fires when Agent dispatch lacks 5-tuple."""
        from ystar.adapters.boundary_enforcer import _run_per_rule_detectors
        from ystar.governance.cieu_store import CIEUStore

        store = CIEUStore()
        initial_count = len(store.query(event_type="CZL_DISPATCH_MISSING_5TUPLE"))

        # Trigger violation: Agent dispatch without Y*, Xt, U, Yt+1, Rt+1
        _run_per_rule_detectors(
            who="ceo",
            tool_name="Agent",
            params={
                "subagent_type": "eng-kernel",
                "instructions": "Do some work"  # Missing 5-tuple sections
            }
        )

        final_count = len(store.query(event_type="CZL_DISPATCH_MISSING_5TUPLE"))
        assert final_count > initial_count, "CZL_DISPATCH_MISSING_5TUPLE event not emitted"

    def test_czl_receipt_rt_not_zero_fires(self):
        """Detector 2: CZL_RECEIPT_RT_NOT_ZERO fires when receipt claims Rt+1=0 without evidence."""
        from ystar.adapters.boundary_enforcer import _run_per_rule_detectors
        from ystar.governance.cieu_store import CIEUStore

        store = CIEUStore()
        initial_count = len(store.query(event_type="CZL_RECEIPT_RT_NOT_ZERO"))

        # Trigger violation: SendMessage receipt claims Rt+1=0 but no bash verification
        _run_per_rule_detectors(
            who="ceo",
            tool_name="SendMessage",
            params={
                "content": "Task complete. Rt+1=0 (all assertions pass)."  # No bash paste
            }
        )

        final_count = len(store.query(event_type="CZL_RECEIPT_RT_NOT_ZERO"))
        assert final_count > initial_count, "CZL_RECEIPT_RT_NOT_ZERO event not emitted"

    def test_charter_drift_mid_session_fires(self):
        """Detector 3: CHARTER_DRIFT_MID_SESSION fires when governance file edited without break-glass."""
        from ystar.adapters.boundary_enforcer import _run_per_rule_detectors
        from ystar.governance.cieu_store import CIEUStore

        store = CIEUStore()
        initial_count = len(store.query(event_type="CHARTER_DRIFT_MID_SESSION"))

        # Trigger violation: Edit AGENTS.md without break-glass mode
        _run_per_rule_detectors(
            who="ceo",
            tool_name="Edit",
            params={
                "file_path": "/path/to/AGENTS.md",
                "old_string": "old",
                "new_string": "new"
            }
        )

        final_count = len(store.query(event_type="CHARTER_DRIFT_MID_SESSION"))
        assert final_count > initial_count, "CHARTER_DRIFT_MID_SESSION event not emitted"

    def test_wave_scope_undeclared_fires(self):
        """Detector 4: WAVE_SCOPE_UNDECLARED fires when campaign report lacks Goal/Scope."""
        from ystar.adapters.boundary_enforcer import _run_per_rule_detectors
        from ystar.governance.cieu_store import CIEUStore

        store = CIEUStore()
        initial_count = len(store.query(event_type="WAVE_SCOPE_UNDECLARED"))

        # Trigger violation: Write campaign report without Goal/Scope
        _run_per_rule_detectors(
            who="ceo",
            tool_name="Write",
            params={
                "file_path": "reports/ceo/campaign_v7_launch.md",
                "content": "This is a campaign report.\n\nSome details here."  # No Goal:/Scope:
            }
        )

        final_count = len(store.query(event_type="WAVE_SCOPE_UNDECLARED"))
        assert final_count > initial_count, "WAVE_SCOPE_UNDECLARED event not emitted"

    def test_subagent_unauthorized_git_op_fires(self):
        """Detector 5: SUBAGENT_UNAUTHORIZED_GIT_OP fires when non-authorized agent runs destructive git."""
        from ystar.adapters.boundary_enforcer import _run_per_rule_detectors
        from ystar.governance.cieu_store import CIEUStore

        store = CIEUStore()
        initial_count = len(store.query(event_type="SUBAGENT_UNAUTHORIZED_GIT_OP"))

        # Trigger violation: eng-kernel attempts git reset --hard (unauthorized)
        _run_per_rule_detectors(
            who="eng-kernel",
            tool_name="Bash",
            params={
                "command": "git reset --hard HEAD~1"
            }
        )

        final_count = len(store.query(event_type="SUBAGENT_UNAUTHORIZED_GIT_OP"))
        assert final_count > initial_count, "SUBAGENT_UNAUTHORIZED_GIT_OP event not emitted"

    def test_artifact_archival_scope_detected_fires(self):
        """Detector 6: ARTIFACT_ARCHIVAL_SCOPE_DETECTED fires when artifact created in archival scope."""
        from ystar.adapters.boundary_enforcer import _run_per_rule_detectors
        from ystar.governance.cieu_store import CIEUStore

        store = CIEUStore()
        initial_count = len(store.query(event_type="ARTIFACT_ARCHIVAL_SCOPE_DETECTED"))

        # Trigger event: Write to reports/ (archival scope)
        _run_per_rule_detectors(
            who="ceo",
            tool_name="Write",
            params={
                "file_path": "reports/ceo/new_report.md",
                "content": "Report content"
            }
        )

        final_count = len(store.query(event_type="ARTIFACT_ARCHIVAL_SCOPE_DETECTED"))
        assert final_count > initial_count, "ARTIFACT_ARCHIVAL_SCOPE_DETECTED event not emitted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

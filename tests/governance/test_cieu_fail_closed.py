"""
Test: CIEU fail-closed fallback for governance engines.

2026-04-21 Milestone 4 scope: ensure engines default to real CIEUStore when
cieu_store param is None, not silently store None (which would cause NoneType
errors or silent audit drop). Mirrors the OmissionEngine fix pattern
(CZL-NULL-CIEU-STORE-FIX, omission_engine.py line 117-124).

M-tag: M-2a (audit chain structural completeness) + M-2b (防不作为 audit).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest


def test_omission_engine_defaults_to_real_cieu_store():
    """OmissionEngine pre-existing fix: cieu_store=None → real CIEUStore."""
    from ystar.governance.omission_engine import OmissionEngine
    from ystar.governance.cieu_store import CIEUStore

    eng = OmissionEngine()  # no cieu_store arg
    assert type(eng.cieu_store).__name__ == "CIEUStore", \
        f"expected real CIEUStore, got {type(eng.cieu_store).__name__}"


def test_intervention_engine_defaults_to_real_cieu_store():
    """InterventionEngine 2026-04-21 fix: cieu_store=None → real CIEUStore."""
    from ystar.governance.intervention_engine import InterventionEngine
    from ystar.governance.omission_store import InMemoryOmissionStore

    store = InMemoryOmissionStore()
    eng = InterventionEngine(omission_store=store)  # no cieu_store arg
    assert type(eng.cieu_store).__name__ == "CIEUStore", \
        f"InterventionEngine must default to real CIEUStore, got {type(eng.cieu_store).__name__}"


def test_null_cieu_store_emits_user_warning():
    """NullCIEUStore ctor must warn (not silent)."""
    import warnings
    from ystar.governance.cieu_store import NullCIEUStore

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        NullCIEUStore()
        assert len(w) >= 1
        assert any("NOT be persisted" in str(rec.message) for rec in w), \
            "NullCIEUStore ctor must emit UserWarning about no persistence"


def test_null_cieu_store_silent_flag_still_suppresses():
    """NullCIEUStore(silent=True) for explicit tests: no warning."""
    import warnings
    from ystar.governance.cieu_store import NullCIEUStore

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        NullCIEUStore(silent=True)
        # should be 0 warnings (silent=True suppresses)
        null_warnings = [rec for rec in w if "NullCIEUStore" in str(rec.message)]
        assert len(null_warnings) == 0, \
            f"silent=True should suppress, got {len(null_warnings)} warnings"


def test_autonomy_engine_defaults_to_real_cieu_store():
    """AutonomyEngine 2026-04-21 fix: cieu_store=None → real CIEUStore.

    AutonomyEngine writes autonomy tick CIEU events (who started what action,
    stall detection, priority rotation), so None fallback must be real, not
    silent drop.
    """
    from ystar.governance.autonomy_engine import AutonomyEngine

    eng = AutonomyEngine()  # no cieu_store arg
    assert type(eng.cieu_store).__name__ == "CIEUStore", \
        f"AutonomyEngine must default to real CIEUStore, got {type(eng.cieu_store).__name__}"


def test_reporting_engine_none_cieu_store_remains_legitimate():
    """ReportEngine 是只读 engine (纯只读, 不写入任何 store). None cieu_store
    是合法输入 — 表示调用者不要 CIEU-side report section, 不是 silent drop.
    本测试确保 RE 接受 None 不 crash, 与写审计 engine 行为分明."""
    from ystar.governance.reporting import ReportEngine
    from ystar.governance.omission_store import InMemoryOmissionStore

    eng = ReportEngine(omission_store=InMemoryOmissionStore(), cieu_store=None)
    # None 保留合法, 不 raise; 下游 method 会 gracefully handle
    assert eng.cieu_store is None, \
        "ReportEngine read-only scope: None is legitimate caller intent"

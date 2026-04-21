Audience: Leo-Kernel + Ryan-Platform engineers (implementers), CEO Aiden (dispatch verification), Board (release gate review)
Research basis: grep audit of 90 hardcoded `ystar-company` occurrences across Y-star-gov repo (42 prod, 27 test, 21 scripts); pre-commit hook currently blocks commits with absolute paths; no existing config module or env var pattern found
Synthesis: Product cannot ship with 42 hardcoded Labs-workspace paths in production code. Single `workspace_config.py` module with env-var-first resolution eliminates all 42 in a controlled 4-phase rollout.
Purpose: Enable Leo and Ryan to execute dehardcode without ambiguity; unblock product release.

---

# CZL-YSTAR-DEHARDCODE-RULING

**CTO Ruling** | Ethan Wright | 2026-04-19
**Priority**: P0 (blocks product release)
**Status**: RULING ISSUED — dispatch to Leo-Kernel + Ryan-Platform

---

## 1. Audit Results

**Total hardcoded `ystar-company` references**: 90 occurrences across 3 categories.

### Category A: Production Code (ystar/) — 42 occurrences, 21 files

| File | Occurrences | Severity |
|------|-------------|----------|
| `ystar/governance/omission_engine.py` | 5 | HIGH — runtime path resolution |
| `ystar/governance/k9_routing_subscriber.py` | 4 | HIGH — runtime file I/O |
| `ystar/governance/stuck_claim_watchdog.py` | 3 | HIGH — absolute paths as defaults |
| `ystar/governance/liveness_audit.py` | 3 | HIGH — absolute paths as defaults |
| `ystar/governance/migrations/001_add_decision_canonical.py` | 1 | MED — CLI argparse default |
| `ystar/governance/migrations/002_add_training_eligible.py` | 1 | MED — CLI argparse default |
| `ystar/governance/migrations/003_recanonicalize_route.py` | 1 | MED — CLI argparse default |
| `ystar/governance/migrations/004_add_dominance_log.py` | 1 | MED — CLI argparse default |
| `ystar/governance/enforcement_observer.py` | 3 | MED — relative path inference |
| `ystar/governance/charter_drift.py` | 2 | MED — path inference |
| `ystar/governance/boundary_enforcer.py` | 1 | HIGH — session.json path |
| `ystar/governance/brain_auto_ingest.py` | 1 | LOW — string literal |
| `ystar/governance/cieu_brain_streamer.py` | 1 | HIGH — path join |
| `ystar/governance/directive_evaluator.py` | 1 | HIGH — absolute path |
| `ystar/governance/grant_chain.py` | 1 | HIGH — expanduser path |
| `ystar/governance/narrative_coherence_detector.py` | 1 | LOW — embedded script string |
| `ystar/governance/obligation_remediation.py` | 1 | LOW — embedded script string |
| `ystar/adapters/activation_triggers.py` | 2 | HIGH — workspace resolution |
| `ystar/capabilities.py` | 1 | HIGH — session.json path |
| `ystar/cli/safemode_cmd.py` | 2 | HIGH — CIEU DB + session paths |
| `ystar/kernel/rt_measurement.py` | 1 | HIGH — sys.path injection |
| `ystar/rules/per_rule_detectors.py` | 1 | LOW — comment only |

**Additional absolute paths** (non-ystar-company but same class of bug):
- `ystar/governance/liveness_audit.py:198` — hardcoded `/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar`
- `ystar/governance/directive_evaluator.py:442` — hardcoded Y-star-gov path
- `ystar/governance/k9_adapter/rules_6_10.py:176` — detection pattern (intentional, keep)

### Category B: Test Code (tests/) — 27 occurrences

| File | Pattern |
|------|---------|
| `tests/governance/test_p0_2_behavior_rules_cieu.py` | 4x hardcoded DB path |
| `tests/adapters/test_hook_v2_enforcement.py` | 2x session.json path |
| `tests/adapters/test_boundary_enforcer_per_rule.py` | 1x parent traversal |
| `tests/adapters/test_identity_canonical_aliases.py` | 1x registry path |
| `tests/adapters/test_redirect_decision.py` | 1x fix_command string |
| `tests/test_proactive_activation.py` | 6x (uses `/Users/user/` — generic, OK) |
| `tests/governance/test_k9_routing_chain_end_to_end.py` | 1x COMPANY_ROOT |
| `tests/governance/test_omission_recursive.py` | 1x fixture |
| `tests/governance/test_retired_rule_not_fire.py` | 1x absolute LABS_ROOT |
| `tests/governance/test_charter_flow_rule.py` | 4x path in test data |
| `tests/test_auto_fulfillment_9types.py` | comment only |
| `tests/test_identity_detection.py` | uses tmp_path (OK pattern) |

### Category C: Scripts (scripts/) — 21 occurrences

| File | Pattern |
|------|---------|
| `scripts/exp3/b5_dispatch_cycle.py` | absolute path |
| `scripts/exp3/b6_cieu_growth.py` | absolute path |
| `scripts/exp3/b7_receipt_truth.py` | absolute path x2 |
| `scripts/exp3/gen_axes.py` | absolute path x5 |
| `scripts/exp3/b4_omission_close.py` | absolute path |
| `scripts/exp3/exp3_launch_all.py` | absolute path x3 |
| `scripts/cieu_brain_alignment_seed.py` | relative traversal |
| `scripts/omission_recursive_illuminate.py` | parent traversal |
| `scripts/cieu_to_brain_batch.py` | expanduser |
| `scripts/cieu_brain_learning_cycle.py` | expanduser |
| `scripts/migrate_9_obligation_fulfillers.py` | comment only |

---

## 2. Design Specification

### 2.1 New Module: `ystar/workspace_config.py`

```python
"""
Y*gov workspace configuration — single source of truth for Labs workspace path.

Resolution order:
1. YSTAR_LABS_WORKSPACE env var (explicit override)
2. YSTAR_COMPANY_ROOT env var (alias, backward compat)
3. Auto-detect: walk up from __file__ looking for sibling 'ystar-company' dir
4. Fallback: ~/.openclaw/workspace/ystar-company (if exists)
5. None (no Labs workspace available — product running standalone)
"""
import os
from pathlib import Path
from typing import Optional

_cached: Optional[Path] = None

def get_labs_workspace() -> Optional[Path]:
    """Return Labs workspace root, or None if not available."""
    global _cached
    if _cached is not None:
        return _cached

    # 1. Explicit env var
    env_val = os.environ.get("YSTAR_LABS_WORKSPACE") or os.environ.get("YSTAR_COMPANY_ROOT")
    if env_val:
        p = Path(env_val)
        if p.is_dir():
            _cached = p
            return _cached

    # 2. Auto-detect sibling
    try:
        pkg_root = Path(__file__).resolve().parent.parent  # Y-star-gov/
        sibling = pkg_root.parent / "ystar-company"
        if sibling.is_dir():
            _cached = sibling
            return _cached
    except Exception:
        pass

    # 3. Default location
    default = Path.home() / ".openclaw" / "workspace" / "ystar-company"
    if default.is_dir():
        _cached = default
        return _cached

    return None


def require_labs_workspace() -> Path:
    """Return Labs workspace root or raise ConfigError."""
    ws = get_labs_workspace()
    if ws is None:
        raise EnvironmentError(
            "Y*gov Labs workspace not found. "
            "Set YSTAR_LABS_WORKSPACE env var or ensure "
            "~/.openclaw/workspace/ystar-company/ exists."
        )
    return ws


def get_cieu_db_path() -> Optional[Path]:
    """Convenience: return path to .ystar_cieu.db in Labs workspace."""
    ws = get_labs_workspace()
    return ws / ".ystar_cieu.db" if ws else None


def get_session_json_path() -> Optional[Path]:
    """Convenience: return path to .ystar_session.json in Labs workspace."""
    ws = get_labs_workspace()
    return ws / ".ystar_session.json" if ws else None


def invalidate_cache():
    """Reset cached workspace path. Use in tests."""
    global _cached
    _cached = None
```

### 2.2 Usage Pattern (replacement template)

**Before** (hardcoded):
```python
Path("/Users/haotianliu/.openclaw/workspace/ystar-company/.ystar_cieu.db")
```

**After** (config-driven):
```python
from ystar.workspace_config import get_cieu_db_path
db_path = get_cieu_db_path()
```

**For argparse defaults**:
```python
from ystar.workspace_config import get_labs_workspace
ws = get_labs_workspace()
parser.add_argument("--db", default=str(ws / ".ystar_cieu.db") if ws else None)
```

### 2.3 Test Fixture Pattern

In `tests/conftest.py`:
```python
import os
import pytest
from ystar.workspace_config import invalidate_cache

@pytest.fixture(autouse=True)
def labs_workspace_env(tmp_path, monkeypatch):
    """Set YSTAR_LABS_WORKSPACE to tmp_path for test isolation."""
    fake_ws = tmp_path / "ystar-company"
    fake_ws.mkdir()
    (fake_ws / ".ystar_cieu.db").touch()
    (fake_ws / ".ystar_session.json").write_text("{}")
    (fake_ws / "governance").mkdir()
    (fake_ws / "scripts").mkdir()
    (fake_ws / "reports").mkdir()
    monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(fake_ws))
    invalidate_cache()
    yield fake_ws
    invalidate_cache()
```

---

## 3. Implementation Sequence

### Phase A: Config Module (Leo-Kernel)
- Create `ystar/workspace_config.py` per spec above
- Add unit tests: `tests/test_workspace_config.py`
- Verify: module importable, env var respected, fallback chain works

### Phase B: Production Code Rewrite (Leo-Kernel + Ryan-Platform split)

**Leo-Kernel owns** (kernel + governance core, 12 files):
- `ystar/kernel/rt_measurement.py`
- `ystar/governance/omission_engine.py`
- `ystar/governance/charter_drift.py`
- `ystar/governance/enforcement_observer.py`
- `ystar/governance/grant_chain.py`
- `ystar/governance/boundary_enforcer.py`
- `ystar/governance/cieu_brain_streamer.py`
- `ystar/governance/brain_auto_ingest.py`
- `ystar/governance/directive_evaluator.py`
- `ystar/governance/liveness_audit.py`
- `ystar/governance/narrative_coherence_detector.py`
- `ystar/governance/obligation_remediation.py`

**Ryan-Platform owns** (adapters + CLI + migrations + k9, 10 files):
- `ystar/adapters/activation_triggers.py`
- `ystar/capabilities.py`
- `ystar/cli/safemode_cmd.py`
- `ystar/governance/stuck_claim_watchdog.py`
- `ystar/governance/k9_routing_subscriber.py`
- `ystar/governance/migrations/001_add_decision_canonical.py`
- `ystar/governance/migrations/002_add_training_eligible.py`
- `ystar/governance/migrations/003_recanonicalize_route.py`
- `ystar/governance/migrations/004_add_dominance_log.py`
- `ystar/rules/per_rule_detectors.py` (comment only — trivial)

### Phase C: Test Fixture Overhaul (Ryan-Platform)
- Add `labs_workspace_env` fixture to `tests/conftest.py`
- Update all 27 test occurrences to use fixture or `monkeypatch.setenv`
- Target: zero raw `/Users/haotianliu` strings in tests/

### Phase D: CI + Pre-commit Verification (Ryan-Platform)
- Add grep guard to pre-commit: reject commits with absolute `/Users/` paths in `ystar/` or `tests/`
- Run full test suite, confirm green
- Verify `ystar doctor` still works without env var set (auto-detect fallback)

### Scripts (scripts/) — Deferred
- `scripts/exp3/` are internal Lab tooling, not shipped product
- Dehardcode opportunistically but NOT blocking release

---

## 4. Dispatch Plan

| Phase | Engineer | Deliverable | Depends On |
|-------|----------|-------------|------------|
| A | Leo-Kernel | `ystar/workspace_config.py` + tests | — |
| B-kernel | Leo-Kernel | 12 governance files rewritten | Phase A |
| B-platform | Ryan-Platform | 10 adapter/CLI/migration files rewritten | Phase A |
| C | Ryan-Platform | Test fixture + 27 test file updates | Phase A |
| D | Ryan-Platform | Pre-commit guard + CI green | Phase B + C |
| Review | Ethan-CTO | Final review + merge approval | Phase D |

**Parallel execution**: Phase B-kernel and B-platform + C can run in parallel after Phase A lands.

---

## 5. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Auto-detect fails on user machines | Product non-functional | Env var is primary; auto-detect is convenience only |
| Breaking existing Labs workflow | CTO/CEO sessions break | Backward compat: auto-detect still finds sibling dir |
| Circular import in workspace_config | Import errors | Module has ZERO internal ystar imports |
| Tests pass locally but fail in CI | False green | CI sets `YSTAR_LABS_WORKSPACE=/tmp/fake` explicitly |
| Migration scripts break mid-run | Data corruption | Migrations read --db arg first, env fallback second |

---

## 6. Acceptance Criteria

- [ ] `grep -rn "/Users/haotianliu" ystar/ tests/ --include="*.py"` returns 0 matches (excluding k9_adapter detection patterns)
- [ ] `YSTAR_LABS_WORKSPACE=/nonexistent python -c "from ystar.workspace_config import get_labs_workspace; assert get_labs_workspace() is None"`
- [ ] `YSTAR_LABS_WORKSPACE=/tmp python -c "from ystar.workspace_config import get_labs_workspace; assert str(get_labs_workspace()) == '/tmp'"`
- [ ] Full test suite passes with `YSTAR_LABS_WORKSPACE` set to temp dir
- [ ] Full test suite passes WITHOUT env var (auto-detect works in dev)
- [ ] Pre-commit hook rejects new hardcoded `/Users/` paths

---

## 7. CTO Decision Record

**Decision**: Introduce `ystar/workspace_config.py` as the single resolution module rather than scattering env var reads across 21 files.

**Rationale**: Single point of change. If we later add a config file (`.ystar.toml`), only one module needs updating. Caching avoids repeated filesystem probes.

**Rejected alternatives**:
- Per-file `os.environ.get()` calls: duplicated logic, inconsistent fallback behavior
- Config file only (no env var): harder to set in CI, Docker, ephemeral environments
- Removing Labs workspace dependency entirely: premature — governance features legitimately need company state during development

---

*Ruling issued. Task cards to follow on dispatch_board for Leo-Kernel (Phase A+B-kernel) and Ryan-Platform (Phase B-platform+C+D).*

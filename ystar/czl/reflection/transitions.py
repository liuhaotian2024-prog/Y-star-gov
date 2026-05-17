"""
ystar.czl.reflection.transitions — v3.6 T1+T2 per-test transition tracking.

Solves the v3.5 "bug-as-feature" phenomenon: when a model correctly fixes
an upstream bug (e.g. a fixture's broken `f.write(content)` for raw text),
the fix may break a downstream test that depended on the bug
(`test_load_records_invalid_json` passed because the bug let raw
malformed JSON through). Without a per-test transition signal, the
model sees "1 test failing" but doesn't know "this test was PASSING
last iter, your fix caused it".

History alignment (per founder rule 4):
  - v2.x: "Regression is fatal (weight=1.0); avoiding regression matters
    more than progress." This module enforces that by giving regression
    META the highest priority slot.
  - v21 experiment report Appendix B: "Per-step × payload trip table" is
    a required output. This module is that pattern at the per-test
    dimension instead of per-step × per-payload.

T1 = TransitionTracker (per-iter status diff)
T2 = render_regression_meta (highest-priority META block)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


# === T1: extract_test_status from verifier output ===========================

# pytest -v output lines look like:
#   test_data_pipeline.py::test_load_records_success PASSED            [  5%]
#   test_data_pipeline.py::test_load_records_invalid_json FAILED       [ 10%]
# Also tolerates absence of percentage suffix (some pytest configs).
_TEST_OUTCOME_RE = re.compile(
    r"^(?P<file>\S+\.py)::(?P<test_name>[A-Za-z_][A-Za-z0-9_:\[\]\-\.]*?)\s+"
    r"(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b",
    re.MULTILINE,
)


def parse_pytest_v_outcomes(stdout: str) -> Dict[str, bool]:
    """Parse pytest -v output, return {test_name: passed_bool}.

    test_name format: `file.py::test_name` (preserves full identifier so
    parametrized variants like `test_X[param0]` stay distinct).

    PASSED / XPASS → True. FAILED / ERROR / XFAIL → False.
    SKIPPED → omitted (skipped tests aren't a pass/fail signal).
    """
    out: Dict[str, bool] = {}
    if not stdout:
        return out
    for m in _TEST_OUTCOME_RE.finditer(stdout):
        name = f"{m.group('file')}::{m.group('test_name')}"
        status = m.group("status")
        if status == "SKIPPED":
            continue
        out[name] = status in ("PASSED", "XPASS")
    return out


def extract_test_status(verifier_results: Iterable[Any]) -> Dict[str, bool]:
    """Look for the pytest verifier result and extract its per-test status.

    Pytest verifier MUST populate either:
      - r.details["per_test_status"]: Dict[str, bool]   (preferred — verifier did the parsing)
      - r.details["stdout"]: str                        (fallback — we parse here)

    Returns empty dict when no pytest verifier ran (other verifiers don't
    have per-test granularity; this is a pytest-specific signal).
    """
    for r in verifier_results:
        if getattr(r, "verifier_name", None) != "pytest":
            continue
        details = getattr(r, "details", None) or {}
        if isinstance(details.get("per_test_status"), dict):
            return dict(details["per_test_status"])
        stdout = details.get("stdout") or ""
        return parse_pytest_v_outcomes(stdout)
    return {}


# === T1: TransitionTracker =================================================

@dataclass
class TransitionTracker:
    iter_status: List[Dict[str, bool]] = field(default_factory=list)

    def observe(self, iter_idx: int, verifier_results: Iterable[Any]) -> None:
        """Snapshot per-test status after this iter's verifiers ran."""
        self.iter_status.append(extract_test_status(verifier_results))

    def diff(self) -> Dict[str, str]:
        """Compare the latest two snapshots.

        Returns {test_name: 'newly_failing' | 'newly_passing' |
                 'still_failing' | 'still_passing'}.
        Empty when < 2 snapshots or when both snapshots are empty.
        """
        if len(self.iter_status) < 2:
            return {}
        prev = self.iter_status[-2]
        curr = self.iter_status[-1]
        if not prev and not curr:
            return {}
        out: Dict[str, str] = {}
        for name in set(prev) | set(curr):
            p = prev.get(name)
            c = curr.get(name)
            # When a test name appears in one snapshot but not the other,
            # treat the missing side as "unknown" — only emit transitions
            # when we have data for BOTH iters.
            if p is None or c is None:
                continue
            if p is True and c is False:
                out[name] = "newly_failing"
            elif p is False and c is True:
                out[name] = "newly_passing"
            elif p is False and c is False:
                out[name] = "still_failing"
            elif p is True and c is True:
                out[name] = "still_passing"
        return out


# === T2: render_regression_meta ============================================

def render_regression_meta(diff: Dict[str, str], iter_idx: int) -> Optional[str]:
    """Top-priority META block emitted when any test transitioned status.

    v2.x principle "regression weight=1.0": regression segment is mandatory
    and placed FIRST. Progress segment is optional positive signal.

    Returns None when there are no transitions worth surfacing.
    """
    newly_failing = sorted(n for n, s in diff.items() if s == "newly_failing")
    newly_passing = sorted(n for n, s in diff.items() if s == "newly_passing")
    if not newly_failing and not newly_passing:
        return None

    lines: List[str] = []
    if newly_failing:
        lines.append(
            f"⚠ REGRESSION: {len(newly_failing)} test(s) PASSED in iter {iter_idx - 1} "
            f"but FAIL in iter {iter_idx}:"
        )
        for n in newly_failing[:5]:
            lines.append(f"   - {n}")
        if len(newly_failing) > 5:
            lines.append(f"   (+{len(newly_failing) - 5} more)")
        lines.append("")
        lines.append(
            "These regressions are caused by your LAST change. The direction "
            "you chose may be correct, but the implementation broke an "
            "implicit contract these tests depend on. Either:"
        )
        lines.append("  (A) Adjust the implementation to preserve these tests' behavior "
                     "(common case: a previously-passing test relied on a side-effect "
                     "your fix removed — restore the side-effect at the same time as the fix)")
        lines.append("  (B) Verify these tests' expectations were actually correct "
                     "(rare — when in doubt, prefer A)")
        lines.append("")
        lines.append(
            "Do NOT revert your last change wholesale; recover the regressed "
            "tests WHILE keeping the direction you took. The repetition META "
            "(if present below) only fires when you take the SAME approach; "
            "fixing the regression by adjusting your last fix is a DIFFERENT "
            "approach in the relevant sense."
        )

    if newly_passing:
        if lines:
            lines.append("")
        lines.append(
            f"✓ PROGRESS: {len(newly_passing)} test(s) now PASS that were failing in iter {iter_idx - 1}:"
        )
        for n in newly_passing[:5]:
            lines.append(f"   - {n}")
        if len(newly_passing) > 5:
            lines.append(f"   (+{len(newly_passing) - 5} more)")

    return "\n".join(lines)

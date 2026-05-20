"""
ystar.czl.residual — v5.0 Task A.

Structured R_{t+1} object for the CZL closed loop. v3.x used a float
(failed-verifier count). v5.0 replaces that with a typed dataclass that
captures:

  - failed_verifiers: per-verifier failure metadata
  - failure_locations: file:line + function/test names + extra signals
    (re-uses v3.5 cluster parsing as input)
  - delta_from_prev: newly_failing / newly_passing / still_failing /
    still_passing (re-uses v3.6 TransitionTracker)
  - residual_history: scalar trajectory for RLE oscillation detection

`czl_distance_function(y_star, y_actual)` maps a ResidualState to a
scalar in [0, +inf), where 0 = converged. ResidualLoopEngine's internal
`_residual_distance` calls this via the `distance_function` constructor
arg — RLE's own _default_distance is untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# Sentinel target — "all verifiers pass". The CZL Y* is the absence of
# any failure, so we use a fixed string the distance function recognises.
Y_STAR_ALL_PASS = "__CZL_Y_STAR_ALL_VERIFIERS_PASS__"


@dataclass
class FailedVerifier:
    name: str
    category: str            # "type" | "test" | "coverage" | "structure" | "mutation" | "other"
    message: str             # short summary (verifier.message)
    reason: str = ""         # v3.5 Hook reason field
    severity_weight: float = 1.0


@dataclass
class FailureLocation:
    """One concrete failure pinpoint. Multiple per verifier when applicable."""
    file: str
    lineno: int
    kind: str                # "test_failure" | "missing_line" | "missing_branch" | "surviving_mutant" | "contract_mismatch"
    detail: str = ""         # short human-readable detail
    bottom_function: Optional[str] = None  # v5.3: pytest bottom-frame function name (None for non-pytest)


@dataclass
class TestDelta:
    """v3.6 TransitionTracker output, lifted into the residual."""
    newly_failing: List[str] = field(default_factory=list)
    newly_passing: List[str] = field(default_factory=list)
    still_failing: List[str] = field(default_factory=list)
    still_passing: List[str] = field(default_factory=list)


@dataclass
class ResidualState:
    """Structured R_{t+1}. Distance function maps this → scalar."""
    iteration: int
    failed_verifiers: List[FailedVerifier] = field(default_factory=list)
    failure_locations: List[FailureLocation] = field(default_factory=list)
    delta_from_prev: TestDelta = field(default_factory=TestDelta)
    residual_history: List[float] = field(default_factory=list)
    # Pass-through stats useful for downstream consumers
    passing_test_count: int = 0
    failing_test_count: int = 0

    def n_failed(self) -> int:
        return len(self.failed_verifiers)


# === verifier categorisation =================================================

# Verifier-name → weight. Type / structure failures are cheap to detect and
# usually fundamental; coverage / mutation failures are gradual quality
# signals. Weighted so the loop prioritises gating issues.
_VERIFIER_CATEGORY: Dict[str, str] = {
    "pytest": "test",
    "differential": "test",
    "contract_consistency": "structure",
    "has_exception_tests": "structure",
    "signatures_frozen": "structure",
    "mypy_strict": "type",
    "coverage_80": "coverage",
    "branch_coverage": "coverage",
    "mutation_score": "mutation",
}

_CATEGORY_WEIGHTS: Dict[str, float] = {
    "test": 1.0,          # full weight — tests are the spec
    "structure": 1.0,     # full — contract violation is fatal
    "type": 0.7,          # type errors are real but less critical than test failures
    "coverage": 0.5,      # coverage is a gradual signal
    "mutation": 0.5,      # mutation likewise
    "other": 0.7,
}


def categorise_verifier(name: str) -> str:
    return _VERIFIER_CATEGORY.get(name, "other")


# === distance function passed to ResidualLoopEngine ==========================

def czl_distance_function(y_star: Any, y_actual: Any) -> float:
    """Map (Y*, Y_{t+1}) → scalar Rt+1.

    Convention:
      - y_star is the sentinel `Y_STAR_ALL_PASS` (the absence-of-failure target).
      - y_actual is a `ResidualState` — the structured outcome of one iter.

    Scalar formula: weighted sum of failed-verifier category weights,
    normalised so 0 = converged and 1.0 ≈ "a single full-weight failure".
    Several full-weight failures stack additively — RLE's convergence
    epsilon < this scalar triggers another iteration.

    If RLE happens to call this with non-ResidualState args (e.g. setup
    edge cases), we fall back to RLE's default semantics: 0 if equal,
    1 otherwise.
    """
    if y_star is None and y_actual is None:
        return 0.0
    if not isinstance(y_actual, ResidualState):
        # Fallback — exact equality
        return 0.0 if y_star == y_actual else 1.0
    if not y_actual.failed_verifiers:
        # No failures = converged
        return 0.0
    total = 0.0
    for fv in y_actual.failed_verifiers:
        weight = _CATEGORY_WEIGHTS.get(fv.category, 1.0) * float(fv.severity_weight)
        total += weight
    return total


# === construction from verifier results ======================================

def build_residual_state(
    iteration: int,
    verifier_results: List[Any],
    prev_passing_tests: Optional[Set[str]] = None,
    residual_history: Optional[List[float]] = None,
) -> ResidualState:
    """Convert a list of VerifierResult + prior-iter context into a
    ResidualState. Uses v3.5 cluster module for failure_locations and
    v3.6 TransitionTracker for delta_from_prev (reuse, don't reinvent).
    """
    # Lazy imports to avoid cycles at module load
    from ystar.czl.reflection.cluster import parse_pytest_failures
    from ystar.czl.reflection.transitions import extract_test_status

    failed_verifiers: List[FailedVerifier] = []
    failure_locations: List[FailureLocation] = []
    for r in verifier_results:
        if getattr(r, "passed", True):
            continue
        cat = categorise_verifier(getattr(r, "name", "") or r.verifier_name)
        failed_verifiers.append(FailedVerifier(
            name=r.verifier_name,
            category=cat,
            message=(r.message or "")[:240],
            reason=getattr(r, "reason", "") or "",
        ))
        # Per-verifier failure locations — pytest gets full cluster parse;
        # coverage_80 / branch_coverage carry missing-line / missing-branch
        # lists in details; others get one synthetic "structural" location.
        details = getattr(r, "details", None) or {}
        if r.verifier_name == "pytest":
            stdout = details.get("stdout") or ""
            for f in parse_pytest_failures(stdout):
                failure_locations.append(FailureLocation(
                    file=f["file"], lineno=int(f["lineno"]),
                    kind="test_failure",
                    detail=f"{f['test_name']} [{f.get('error_type','?')}]",
                    bottom_function=f.get("function_name") or None,
                ))
        elif r.verifier_name == "coverage_80":
            for ln in (details.get("missing_lines") or [])[:10]:
                failure_locations.append(FailureLocation(
                    file="data_pipeline.py", lineno=int(ln),
                    kind="missing_line", detail="line not covered",
                ))
        elif r.verifier_name == "branch_coverage":
            for mb in (details.get("missing_branches") or [])[:10]:
                br = mb.get("branch")
                src_line = br[0] if isinstance(br, (list, tuple)) and br else 0
                failure_locations.append(FailureLocation(
                    file=mb.get("file", ""), lineno=int(src_line),
                    kind="missing_branch",
                    detail=f"branch {br} not taken",
                ))
        elif r.verifier_name == "mutation_score":
            for sm in (details.get("surviving_mutants") or [])[:10]:
                failure_locations.append(FailureLocation(
                    file=sm.get("file", ""), lineno=int(sm.get("start_line", 0)),
                    kind="surviving_mutant",
                    detail=f"{sm.get('operator','?')} in `{sm.get('definition_name','?')}`",
                ))
        elif r.verifier_name == "contract_consistency":
            for m in (details.get("mismatches") or [])[:5]:
                # `m` is the structured one-line string from contract_verifier;
                # we keep it as detail.
                failure_locations.append(FailureLocation(
                    file="", lineno=0, kind="contract_mismatch", detail=str(m)[:200],
                ))

    # v3.6 TransitionTracker — derive delta_from_prev
    curr_test_status = extract_test_status(verifier_results)
    curr_passing = {n for n, p in curr_test_status.items() if p}
    curr_failing = {n for n, p in curr_test_status.items() if not p}
    delta = TestDelta()
    if prev_passing_tests is not None:
        prev_set = prev_passing_tests
        # newly_failing = in prev_passing but failing now
        for t in (prev_set & curr_failing):
            delta.newly_failing.append(t)
        # newly_passing = was failing/absent in prev, passing now
        for t in (curr_passing - prev_set):
            delta.newly_passing.append(t)
        for t in (curr_failing - prev_set):
            delta.still_failing.append(t)
        for t in (curr_passing & prev_set):
            delta.still_passing.append(t)

    return ResidualState(
        iteration=iteration,
        failed_verifiers=failed_verifiers,
        failure_locations=failure_locations,
        delta_from_prev=delta,
        residual_history=list(residual_history or []),
        passing_test_count=len(curr_passing),
        failing_test_count=len(curr_failing),
    )

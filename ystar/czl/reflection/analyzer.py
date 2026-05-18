"""
ystar.czl.reflection.analyzer — v3.6 ReflectionAnalyzer.

Composes META signals from three reflection submodules into one block
that the loop prepends to the next-iter prompt:

  v3.5: cluster (cross-failure) + repetition (cross-iter same-pattern)
  v3.6: regression (cross-iter per-test transitions) — HIGHEST PRIORITY

Priority order (per v2.x principle "regression is fatal weight=1.0"):
  1. Regression META (newly failing tests + newly passing tests)
  2. Cluster META (N failures = 1 root cause)
  3. Repetition META (last 2 iters identical → pick different direction)

Maintains iter_history (for cluster + repetition) and a TransitionTracker
(for regression).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from ystar.czl.reflection.cluster import (
    cluster_pytest_failures, render_cluster_text,
)
# v5.0 Task E: repetition retired (replaced by RLE oscillation detection)
from ystar.czl.reflection.transitions import (
    TransitionTracker, render_regression_meta,
)


@dataclass
class ReflectionMeta:
    """Composed META block for one iter's prompt."""
    regression_text: Optional[str] = None   # v3.6 — highest priority
    cluster_text: Optional[str] = None      # v3.5
    repetition_text: Optional[str] = None   # v3.5

    def render(self) -> str:
        # v3.6: regression first (v2.x "weight=1.0" principle).
        parts: List[str] = []
        if self.regression_text:
            parts.append(self.regression_text)
        if self.cluster_text:
            parts.append(self.cluster_text)
        if self.repetition_text:
            parts.append(self.repetition_text)
        return "\n\n".join(parts)

    def is_empty(self) -> bool:
        return not (self.regression_text or self.cluster_text or self.repetition_text)


class ReflectionAnalyzer:
    """Tracks verifier results across CZL iters; emits META on demand.

    Usage in loop.py:
        analyzer = ReflectionAnalyzer()  # once per CZLRun
        # ... in each iter (after verify()) ...
        analyzer.record(iter_idx, verifier_results)
        meta = analyzer.analyze(iter_idx)
        if not meta.is_empty():
            feedback_block = meta.render() + "\n\n" + feedback_block
    """

    def __init__(self) -> None:
        self.iter_history: List[List[Any]] = []   # List[List[VerifierResult]]
        self._transition_tracker = TransitionTracker()

    def record(self, iter_idx: int, verifier_results: List[Any]) -> None:
        """Append this iter's verifier_results to history; observe transitions."""
        self.iter_history.append(list(verifier_results))
        self._transition_tracker.observe(iter_idx, verifier_results)

    def analyze(self, iter_idx: Optional[int] = None) -> ReflectionMeta:
        """Run regression + cluster + repetition over the current history.

        iter_idx is the index of the latest recorded iter (used by
        regression META's "iter N-1 vs iter N" text). Defaults to
        len(iter_history) - 1.
        """
        if iter_idx is None:
            iter_idx = len(self.iter_history) - 1
        meta = ReflectionMeta()

        # v3.6: REGRESSION META (highest priority).
        diff = self._transition_tracker.diff()
        if diff:
            meta.regression_text = render_regression_meta(diff, iter_idx)

        latest = self.iter_history[-1] if self.iter_history else []

        # v3.5: Cluster — look at the pytest verifier's stdout from the latest iter.
        pytest_result = None
        for r in latest:
            if getattr(r, "verifier_name", None) == "pytest" and not getattr(r, "passed", True):
                pytest_result = r
                break
        if pytest_result is not None:
            stdout = (pytest_result.details or {}).get("stdout") or ""
            if not stdout:
                stdout = pytest_result.message_natural or ""
            clusters = cluster_pytest_failures(stdout)
            ctext = render_cluster_text(clusters)
            if ctext:
                meta.cluster_text = ctext

        # v5.0: repetition detection delegated to RLE._oscillation_detected.
        # No repetition_text rendered here — RLE emits RESIDUAL_LOOP_OSCILLATION.
        return meta

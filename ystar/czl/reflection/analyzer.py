"""
ystar.czl.reflection.analyzer — v3.5 T5 ReflectionAnalyzer.

Composes the cluster + repetition META signals into one block that the
loop prepends to the next-iter prompt. Maintains iter_history across
the trial.

Per founder methodology principle (3): "拒绝模型甩锅 — 不允许结论是
'Gemma 4B 不行换模型'. 通用方法论必须能让 4B 在引导下走出局部极小."
The cluster + repetition layer is the methodology — when 3 failures
share a fixture root and the model keeps writing more tests instead of
fixing the fixture, the cluster META names the fixture as the root and
the repetition META forbids the same approach.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ystar.czl.reflection.cluster import (
    cluster_pytest_failures, render_cluster_text,
)
from ystar.czl.reflection.repetition import (
    failure_fingerprint, detect_repetition,
)


@dataclass
class ReflectionMeta:
    """Composed META block for one iter's prompt."""
    cluster_text: Optional[str] = None
    repetition_text: Optional[str] = None

    def render(self) -> str:
        parts: List[str] = []
        if self.cluster_text:
            parts.append(self.cluster_text)
        if self.repetition_text:
            parts.append(self.repetition_text)
        return "\n\n".join(parts)

    def is_empty(self) -> bool:
        return not (self.cluster_text or self.repetition_text)


class ReflectionAnalyzer:
    """Tracks verifier results across CZL iters; emits META on demand.

    Usage in loop.py:
        analyzer = ReflectionAnalyzer()  # once per CZLRun
        # ... in each iter ...
        analyzer.record(verifier_results)
        meta = analyzer.analyze()
        if not meta.is_empty():
            feedback_block = meta.render() + "\n\n" + feedback_block
    """

    def __init__(self) -> None:
        self.iter_history: List[List[Any]] = []   # List[List[VerifierResult]]

    def record(self, verifier_results: List[Any]) -> None:
        """Append this iter's verifier_results to history."""
        # Shallow copy so subsequent loop mutations don't affect history
        self.iter_history.append(list(verifier_results))

    def analyze(self) -> ReflectionMeta:
        """Run cluster + repetition over the current history."""
        meta = ReflectionMeta()
        latest = self.iter_history[-1] if self.iter_history else []

        # T3 cluster — look at the pytest verifier's stdout from the latest iter
        pytest_result = None
        for r in latest:
            if getattr(r, "verifier_name", None) == "pytest" and not getattr(r, "passed", True):
                pytest_result = r
                break
        if pytest_result is not None:
            # details.stdout carries the raw pytest stdout
            stdout = (pytest_result.details or {}).get("stdout") or ""
            # Also try message_natural (T2 verifiers embed the traceback)
            if not stdout:
                stdout = pytest_result.message_natural or ""
            clusters = cluster_pytest_failures(stdout)
            ctext = render_cluster_text(clusters)
            if ctext:
                meta.cluster_text = ctext

        # T4 repetition — last 2 iters
        if len(self.iter_history) >= 2:
            meta.repetition_text = detect_repetition(self.iter_history, window=2)

        return meta

    def latest_fingerprint(self) -> str:
        if not self.iter_history:
            return ""
        return failure_fingerprint(self.iter_history[-1])

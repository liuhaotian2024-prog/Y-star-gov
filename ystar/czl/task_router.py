"""
ystar.czl.task_router — auto-route task description + source files to a Scenario.

v3.3 C: turns Trampoline from "user picks a scenario" into "user gives a task
description and source, Trampoline auto-routes". This is the engineering
upgrade from "4-scenario demo" to "generalizable adaptive substrate".

Phase 1 (this file): keyword-and-source-signal scoring. No LLM call — pure
deterministic routing for the 4 in-tree scenarios plus a generic fallback.

Phase 2 (deferred to v4): LLM classifier when keyword-based scoring is
ambiguous (score difference < threshold) — would add a single Sonnet/DeepSeek
call to disambiguate.

Usage:
  from ystar.czl.task_router import get_default_router
  router = get_default_router()
  scenario_name, confidence, reason = router.route(
      task_description="重构这两个文件 rename foo to bar",
      source_files={"a.py": "...", "b.py": "..."},
  )
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


class TaskRouter:
    """Keyword + source-signal scorer. Registry style: scenarios register
    themselves with (task_keywords, source_signals)."""

    def __init__(self) -> None:
        # name -> (scenario_obj, signals_dict)
        self.scenarios: Dict[str, Tuple[Any, Dict[str, Any]]] = {}

    def register(self, scenario: Any, signals: Dict[str, Any]) -> None:
        """Register a scenario with its routing signals.

        signals dict shape:
          - "task_keywords": List[str]  (case-insensitive substring match on
                                          task_description)
          - "source_signals": List[Callable[[Dict[str, str]], bool]]
                              (each callable: takes source_files dict, returns
                              True if the signal fires for this fileset)
        """
        name = getattr(scenario, "name", None) or scenario.__class__.__name__
        self.scenarios[name] = (scenario, signals)

    def route(
        self,
        task_description: str,
        source_files: Dict[str, str],
    ) -> Tuple[str, float, str]:
        """Score each registered scenario; return (best_name, confidence, reason).

        Scoring:
          - +1.0 per matched task keyword
          - +2.0 per fired source signal (source structure is a stronger signal
            than NL keywords since keywords can be ambiguous, e.g. "test" appears
            in many task descriptions)

        If no scenario scores > 0, returns ("generic", 0.0, "fallback to generic").
        Confidence = best_score / sum_of_all_scores.
        """
        if not self.scenarios:
            return ("generic", 0.0, "no scenarios registered")
        scores: Dict[str, float] = {}
        reasons: Dict[str, str] = {}
        desc_lower = (task_description or "").lower()
        for name, (_scenario, signals) in self.scenarios.items():
            score = 0.0
            reason_parts: List[str] = []
            for kw in signals.get("task_keywords", []):
                if kw.lower() in desc_lower:
                    score += 1.0
                    reason_parts.append(f"keyword '{kw}'")
            for sig_fn in signals.get("source_signals", []):
                try:
                    if sig_fn(source_files):
                        score += 2.0
                        reason_parts.append(f"source signal '{getattr(sig_fn, '__name__', 'lambda')}'")
                except Exception as e:
                    reason_parts.append(f"signal-error '{e}'")
            scores[name] = score
            reasons[name] = "; ".join(reason_parts) if reason_parts else "no signals"
        # Pick winner
        if not scores or max(scores.values()) == 0:
            return ("generic", 0.0, "fallback to generic — no signals fired")
        best = max(scores, key=lambda k: scores[k])
        total = sum(scores.values())
        confidence = scores[best] / total if total > 0 else 0.0
        return (best, confidence, reasons[best])


# === module-level singleton =================================================

_default_router = TaskRouter()


def get_default_router() -> TaskRouter:
    return _default_router


# === source-signal lambdas (named functions for reason strings) =============

def has_multiple_py_modules(files: Dict[str, str]) -> bool:
    """Two or more `.py` files (excluding test_*.py)."""
    return sum(1 for n in files
               if n.endswith(".py") and not n.split("/")[-1].startswith("test_")) >= 2


def has_no_test_files(files: Dict[str, str]) -> bool:
    """No `test_*.py` file in the workspace — user wants tests written."""
    return not any(n.split("/")[-1].startswith("test_") and n.endswith(".py") for n in files)


def has_test_files(files: Dict[str, str]) -> bool:
    """At least one `test_*.py` file — test_gen unlikely, bug_fix likely."""
    return any(n.split("/")[-1].startswith("test_") and n.endswith(".py") for n in files)


def has_unannotated_defs(files: Dict[str, str]) -> bool:
    """At least one `def foo(...):` line where the parameter list has no `:`
    (no annotations). Heuristic; misses `def foo()` (zero-arg) but those
    don't need annotations anyway."""
    for content in files.values():
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("def ") and "(" in stripped and ")" in stripped:
                paren = stripped[stripped.index("(") + 1: stripped.rindex(")")]
                if paren.strip() and ":" not in paren and "->" not in stripped:
                    return True
    return False


def has_failing_test(files: Dict[str, str]) -> bool:
    """At least one `test_*.py` file present (paired with the task keyword
    'fix' / 'failing' / '修复' for the bug_fix routing). Cheaper than
    actually running pytest."""
    return has_test_files(files)

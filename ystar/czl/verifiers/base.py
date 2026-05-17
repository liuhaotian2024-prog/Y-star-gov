"""
ystar.czl.verifiers.base — external CI tool wrappers (v3.3).

Principle: we wrap pytest, ruff, mypy, bandit, etc. — these tools are
industry standard, their judgment is not ours to override.

v3.3 additions (Phase 7 capability-matrix + adaptive-threshold + feedback
adapter):

  - **D.1**: `VerifierResult.message_natural` — prose-style feedback for
    small models that struggle with structured jargon-style errors.
  - **E.1**: `Verifier` class metadata fields — `applies_to_tasks`,
    `min_model_capacity`, `feedback_complexity`, `known_limitations`. Used
    by `VerifierRegistry.assemble_chain` to filter the verifier chain
    per scenario × model tier.
  - **B.1**: `AdaptiveThresholdVerifier` mixin — first call records the
    baseline score, subsequent calls compare against `min(target,
    baseline + 0.10)`, never below `floor = target - 0.3`. Per-trial
    reset via `reset_for_trial()`.
  - **E.3**: `VerifierRegistry` — global registry + `assemble_chain` for
    tier × task filtering.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# === D.1: VerifierResult with message_natural ===============================

@dataclass
class VerifierResult:
    """Outcome of one verifier run."""
    verifier_name: str               # "ruff" | "mypy" | "pytest" | ...
    passed: bool
    message: str = ""                # short structured summary (for large-model audiences)
    message_natural: Optional[str] = None  # v3.3: prose-style (for small-model audiences)
    details: Dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


# === E.1: Verifier base class with metadata =================================

# Capacity tier ordering (used by AdaptiveThresholdVerifier and registry):
_TIER_ORDER: Dict[str, int] = {"tiny": 0, "small": 1, "medium": 2, "large": 3}


def tier_compatible(min_capacity: str, available_tier: str) -> bool:
    """True when an `available_tier` model meets/exceeds `min_capacity` need."""
    a = _TIER_ORDER.get(available_tier, 2)
    m = _TIER_ORDER.get(min_capacity, 0)
    return a >= m


class Verifier(ABC):
    """Wraps one external tool. Idempotent (per workspace state) and
    intended to be stateless EXCEPT for verifiers that mix in
    `AdaptiveThresholdVerifier` (which carry per-trial calibration state
    that resets between trials)."""

    name: str = ""                                   # must override; matches the tool
    # v3.3 metadata for VerifierRegistry chain assembly:
    applies_to_tasks: List[str] = ["all"]            # ["all"] = applies everywhere
    min_model_capacity: str = "small"                # "tiny"|"small"|"medium"|"large"
    feedback_complexity: str = "medium"              # "low"|"medium"|"high"
    known_limitations: List[str] = []
    # is_final_gate is a per-instance flag set by subclasses; used by scenarios
    # to schedule certain verifiers (mutation_score, branch_coverage) only
    # after the inner verifiers all pass.
    is_final_gate: bool = False

    @abstractmethod
    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        """Execute on workspace_dir and convert tool output to a
        VerifierResult. Tool-detected issues map to passed=False, NOT
        exceptions.
        """
        ...

    def is_applicable(self, workspace_dir: str, contract: Optional[Dict[str, Any]] = None) -> bool:
        """Whether this verifier should run for this workspace+contract.
        Default True; override to skip (e.g. RuffVerifier returns False if
        no .py files exist).

        v3.3: `contract` parameter is now PASSED IN by scenarios so the
        verifier can consult e.g. `_mutation_target_file`. Existing
        verifiers that didn't take `contract` still work — kwargs are
        forwarded with optional fallback.
        """
        return True

    def reset_for_trial(self) -> None:
        """v3.3: called by Scenario.verify() when contract['trial_id']
        changes, so AdaptiveThresholdVerifier subclasses can wipe
        calibration state. Default: no-op."""
        pass

    def __repr__(self) -> str:
        return f"<Verifier {self.name}>"


# === B.1: AdaptiveThresholdVerifier =========================================

class AdaptiveThresholdVerifier(Verifier):
    """v3.4 redesign: baseline is INFORMATIONAL only — does NOT bend
    pass/fail. Real target is the sole pass/fail standard.

    Rationale (v3.3 sanity post-mortem):
      v3.3 used `effective_threshold = min(target, max(floor,
      baseline + 0.10))`. In the gemma B2 sanity, baseline was 0.75 and
      target was 0.80, so the "adaptive" threshold collapsed back to
      0.80 — the verifier was lying about being adaptive. Worse, since
      iter-1 calibration was ALWAYS pass, iter-1 succeeded, iter-2 then
      held gemma to the hardcoded target. The "adaptive" layer added
      surface complexity without helping.

    v3.4 semantics:
      - Pass/fail is always against `self.target`.
      - `_calibration_score` (first-call score) is preserved purely as a
        hint field that the verifier's feedback uses in the prose
        ("you were at 0.75 last iter, target is 0.80, gap 0.05"). The
        rollback layer in loop.py is what actually defends against
        cascade regression — not threshold relaxation.
    """

    def __init__(self, target_threshold: float):
        self.target = float(target_threshold)
        self._call_count: int = 0
        self._calibration_score: Optional[float] = None

    def reset_for_trial(self) -> None:
        """Override Verifier.reset_for_trial — wipes per-trial baseline."""
        self._call_count = 0
        self._calibration_score = None

    def check_score(self, actual_score: float) -> Tuple[bool, str]:
        """Returns (passed, message). Pass/fail is real-target only;
        baseline is informational.
        """
        self._call_count += 1
        if self._calibration_score is None:
            self._calibration_score = actual_score
        gap = self.target - actual_score
        if actual_score >= self.target:
            return (
                True,
                f"score={actual_score:.2f} >= target {self.target:.2f}"
            )
        return (
            False,
            f"score={actual_score:.2f} < target {self.target:.2f} (gap={gap:.2f}, "
            f"baseline iter1 was {self._calibration_score:.2f})"
        )


# === E.3: VerifierRegistry for chain assembly ===============================

class VerifierRegistry:
    """Global registry of (verifier_factory, metadata). Used by scenarios
    to assemble per-trial verifier chains filtered by task + model_tier.

    Note: stores FACTORIES (callables returning a Verifier instance), not
    pre-instantiated verifiers, so AdaptiveThresholdVerifier subclasses
    don't share state across scenarios.
    """

    def __init__(self):
        self._entries: List[Tuple[str, Any]] = []

    def register(self, factory: Any, *, name: str = "") -> None:
        nm = name or getattr(factory, "name", None) or factory.__class__.__name__
        self._entries.append((nm, factory))

    def assemble_chain(self, *, task: str, model_tier: str = "medium",
                       include_final_gates: bool = True) -> List[Verifier]:
        """Build the ordered verifier chain for one (task, tier) combo.

        Filter rules:
          - skip if verifier.applies_to_tasks not in (task, "all")
          - skip if not tier_compatible(verifier.min_model_capacity, tier)
          - skip final-gate verifiers if `include_final_gates=False`

        Order is registration order.
        """
        chain: List[Verifier] = []
        for _, factory in self._entries:
            v = factory() if callable(factory) and not isinstance(factory, Verifier) else factory
            applies = v.applies_to_tasks or ["all"]
            if not (task in applies or "all" in applies):
                continue
            if not tier_compatible(v.min_model_capacity, model_tier):
                continue
            if v.is_final_gate and not include_final_gates:
                continue
            chain.append(v)
        return chain


# Module-level singleton for users who want one global chain pool.
_default_registry = VerifierRegistry()


def get_default_registry() -> VerifierRegistry:
    return _default_registry

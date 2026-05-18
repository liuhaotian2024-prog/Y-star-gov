"""
ystar.czl.autonomy — v5.0 Task B.

CZLAutonomyEngine implements ResidualLoopEngine's autonomy_engine
contract. It is invoked by RLE._compute_next_action when residual > 0
and oscillation/escalation haven't triggered.

The autonomy engine does NOT call the LLM. CZL's "next action" is the
NEXT ITERATION OF THE LLM LOOP — but RLE doesn't know that. To bridge:

  - pull_next_action(agent_id) returns an Action whose `.description`
    encodes the focus_constraint computed from the latest ResidualState
    + history.
  - The CZL loop reads that description back, parses out the
    focus_constraint, attaches it to the next iter's contract, and runs
    the iter normally.

This indirection is awkward but preserves RLE's contract without
forking it. RLE then emits RESIDUAL_LOOP_ACTION carrying the
description — the audit log proves CZL is RLE-driven.

focus_constraint:
  - allowed_files: Set[str] | None (None = unrestricted)
  - target_cluster: tuple (file, lineno) | None
  - guidance_keys: List[str] (which META blocks to surface — "regression",
    "cluster", "verifier_traceback", or "all")
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# Action — duck-typed to match governance.autonomy_engine.Action shape.
# We don't import that one because it requires omission_engine deps; we
# only need the .description field RLE reads.


@dataclass
class FocusConstraint:
    """The per-iter constraint U_{t+1} computed by CZLAutonomyEngine."""
    allowed_files: Optional[Set[str]] = None       # None = no restriction
    target_cluster: Optional[Dict[str, Any]] = None  # {file, lineno, count}
    guidance_keys: List[str] = field(default_factory=lambda: ["all"])
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed_files": sorted(self.allowed_files) if self.allowed_files else None,
            "target_cluster": dict(self.target_cluster) if self.target_cluster else None,
            "guidance_keys": list(self.guidance_keys),
            "rationale": self.rationale,
        }


@dataclass
class CZLAction:
    """Duck-typed Action — only .description is read by RLE."""
    description: str
    why: str = ""
    verify: str = ""
    on_fail: str = ""
    priority: int = 0
    action_id: str = ""
    tags: List[str] = field(default_factory=list)
    source: str = "czl_autonomy"

    # Expose the structured focus_constraint as an attribute for the CZL
    # loop to pick up directly (the description string is the audit-log
    # render; the structured copy avoids re-parsing).
    focus_constraint: Optional[FocusConstraint] = None


class CZLAutonomyEngine:
    """Implements RLE's autonomy_engine.pull_next_action(agent_id) contract.

    The CZL loop owns a single CZLAutonomyEngine instance per CZLRun.
    Before calling rle.on_cieu_event(), the loop calls
    `engine.observe(residual_state)`. RLE later invokes
    `engine.pull_next_action(agent_id)` — that method consults the
    most recent observed ResidualState and computes the focus_constraint.
    """

    def __init__(self) -> None:
        self._latest_residual: Any = None    # ResidualState — last observed
        self._history: List[Any] = []        # ResidualState — full trajectory

    # Public interface used by the CZL loop ----------------------------------
    def observe(self, residual_state: Any) -> None:
        """Update internal state with the latest ResidualState (typed)."""
        self._latest_residual = residual_state
        self._history.append(residual_state)

    def compute_focus(self) -> FocusConstraint:
        """Pure derivation of focus_constraint from latest ResidualState.

        Strategy (signal-driven, no hardcoded scenario preferences):
          1. If any cluster of ≥2 failure_locations shares a (file,
             lineno), focus on that cluster.
          2. Else if delta_from_prev has newly_failing tests, focus on
             the file containing the first one.
          3. Else allowed_files = files referenced by any failure_location.
          4. Else None (no restriction).
        """
        fc = FocusConstraint()
        r = self._latest_residual
        if r is None or not getattr(r, "failed_verifiers", None):
            return fc  # nothing to focus on

        # (1) cluster — multiple locations sharing the same (file, lineno)
        loc_counts: Dict[tuple, int] = {}
        for loc in getattr(r, "failure_locations", []):
            key = (loc.file, loc.lineno)
            loc_counts[key] = loc_counts.get(key, 0) + 1
        if loc_counts:
            top_loc, top_count = max(loc_counts.items(), key=lambda kv: kv[1])
            if top_count >= 2 and top_loc[0]:  # require non-empty file
                fc.target_cluster = {
                    "file": top_loc[0], "lineno": top_loc[1], "count": top_count,
                }
                fc.allowed_files = {top_loc[0]}
                fc.rationale = (
                    f"cluster of {top_count} failures at {top_loc[0]}:{top_loc[1]} "
                    f"— focus on this single root before broadening"
                )
                fc.guidance_keys = ["cluster", "verifier_traceback"]
                return fc

        # (2) regression — newly_failing
        nf = getattr(r.delta_from_prev, "newly_failing", []) if r.delta_from_prev else []
        if nf:
            first_test = nf[0]
            file_guess = first_test.split("::", 1)[0] if "::" in first_test else ""
            if file_guess:
                fc.allowed_files = {file_guess}
            fc.rationale = (
                f"regression — {len(nf)} test(s) that passed in iter "
                f"{r.iteration - 1} now fail; first: {first_test}"
            )
            fc.guidance_keys = ["regression"]
            return fc

        # (3) generic — all files involved
        files = {loc.file for loc in r.failure_locations if loc.file}
        if files:
            fc.allowed_files = files
            fc.rationale = "no dominant cluster; allow edits across all files referenced by current failures"
            fc.guidance_keys = ["all"]
            return fc
        # (4) wide open
        fc.rationale = "no localised signals; unrestricted next attempt"
        fc.guidance_keys = ["all"]
        return fc

    # Interface that RLE will call ------------------------------------------
    def pull_next_action(self, agent_id: str) -> Optional[CZLAction]:
        """Called by RLE._compute_next_action. Returns a CZLAction whose
        `.description` is read by RLE and emitted as RESIDUAL_LOOP_ACTION.
        The structured focus_constraint is attached as an attribute the
        CZL loop reads directly (RLE doesn't see it).
        """
        if self._latest_residual is None:
            return None
        fc = self.compute_focus()
        desc_payload = {
            "rationale": fc.rationale,
            "focus_constraint": fc.to_dict(),
            "iter": getattr(self._latest_residual, "iteration", -1),
        }
        return CZLAction(
            description=json.dumps(desc_payload, ensure_ascii=False),
            why=fc.rationale,
            verify="rerun verifiers and check residual decreases",
            on_fail="rle handles via oscillation/escalation",
            priority=0,
            action_id=f"czl-iter-{getattr(self._latest_residual, 'iteration', -1)}",
            tags=["czl_iteration", "focus_constraint_attached"],
            source="czl_autonomy",
            focus_constraint=fc,
        )

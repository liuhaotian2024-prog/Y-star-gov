"""
ystar.czl.reflection.no_progress — v3.8 adaptive halt-condition logic.

Founder principle: 自适应智能通用非硬编码 — every constant either disappears
or is learned from historical trial data. This module provides:

  T2: is_no_progress_v3_8 — dual-dimension halt (residual ∧ passing-set)
      replaces v3.4 single-dim residual-only check. If passing set is
      still growing even when residual is stuck, the model is making
      progress and should NOT be halted.

  T3: query_converged_stats — scans past trial JSONs for converged
      (scenario, model_tier) samples; returns p90 wall as the adaptive
      resource-safeguard cap. < 3 samples → returns None (no cap = open).

  T4: adaptive_no_progress_window — window size scales as ceil(log2(N))
      with history length. No hardcoded "3 iters" constant.

The original residual_loop_engine no_progress halt logic is NOT modified
(per v3.8 guardrail 1) — this module is loop.py's wrapper.
"""
from __future__ import annotations

import glob
import json
import math
import os
import statistics
from typing import Any, Dict, List, Optional, Set


# === T4: adaptive_no_progress_window ========================================

def adaptive_no_progress_window(history_len: int) -> int:
    """Window grows ~log2(history_len). Empirical mapping (per v3.8 T4
    sanity expectations): N=3 → 2, N=10 → 4, N=100 → 7.

    Formula: max(2, ceil(log2(N))) for N ≥ 2; 2 for N < 2.

    Rationale: small history = small window (fast halt); large history =
    longer window (more patience). No hardcoded constants.
    """
    if history_len < 2:
        return 2
    return max(2, math.ceil(math.log2(history_len)))


# === T2: is_no_progress_v3_8 (dual-dim) =====================================

def is_no_progress_v3_8(
    residual_trajectory: List[float],
    passing_set_trajectory: List[Set[str]],
    window: int,
) -> bool:
    """v3.8 dual-dim halt check.

    Halt only when BOTH:
      - residual hasn't strictly decreased in the last `window` iters
      - passing set hasn't strictly grown in the last `window` iters

    If passing set IS growing (more tests passing), the model is making
    real progress even if residual count stays the same. Do not halt.

    Returns False when trajectory is too short for a meaningful window.

    Trajectory contract: len(residual_trajectory) == len(passing_set_trajectory),
    indexed by iter (latest at -1).
    """
    if window <= 0:
        return False
    if len(residual_trajectory) < window + 1:
        return False
    if len(passing_set_trajectory) < window + 1:
        return False
    recent_resid = residual_trajectory[-(window + 1):]
    recent_passing = passing_set_trajectory[-(window + 1):]

    # residual stuck = no strict decrease anywhere in window
    residual_stuck = not any(
        recent_resid[i + 1] < recent_resid[i]
        for i in range(window)
    )
    # passing stuck = no strict growth anywhere in window
    # (using set superset: a > b iff a ⊇ b and a != b)
    passing_stuck = not any(
        recent_passing[i + 1] > recent_passing[i]
        for i in range(window)
    )
    return residual_stuck and passing_stuck


# === T3: query_converged_stats (self-learning resource safeguard) ===========

# arm → model_tier mapping (matches v3.4 backend.model_capacity values)
_ARM_TO_TIER: Dict[str, str] = {
    "A": "large", "A2": "large",
    "B1": "small", "B2": "small",
    "C1": "medium", "C2": "medium",
    "D2": "medium",
}


def arm_to_tier(arm: str) -> Optional[str]:
    return _ARM_TO_TIER.get(arm)


def _default_search_roots() -> List[str]:
    """Repo-relative default — benchmarks/**/v3_trial_cieu. Caller can
    override via query_converged_stats(search_roots=...).
    """
    here = os.path.abspath(__file__)
    # reflection/no_progress.py → reflection/ → czl/ → ystar/ → repo_root
    repo_root = os.path.normpath(os.path.join(here, "..", "..", "..", ".."))
    return [
        os.path.join(repo_root, "benchmarks", "czl_arbitrage"),
    ]


def query_converged_stats(
    scenario: str,
    model_tier: str,
    search_roots: Optional[List[str]] = None,
    min_samples: int = 3,
) -> Optional[Dict[str, float]]:
    """Scan historical trial JSONs for (scenario, converged=True, tier match).

    Returns None when sample count < min_samples (insufficient history for
    self-learning — open, no resource cap). Otherwise returns:
        {n, median_wall, p90_wall}

    Tier match: trial's `arm` field is mapped via arm_to_tier; passes iff
    inferred tier == requested model_tier. Skips trials missing tier-mapping
    info or non-converged.
    """
    roots = search_roots if search_roots is not None else _default_search_roots()
    walls: List[float] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        # Find all v3_trial_cieu dirs under each root.
        for cieu_dir in glob.glob(os.path.join(root, "**", "v3_trial_cieu"), recursive=True):
            for trial_path in glob.glob(os.path.join(cieu_dir, "*.json")):
                try:
                    d = json.load(open(trial_path, "r", encoding="utf-8"))
                except Exception:
                    continue
                if d.get("scenario") != scenario:
                    continue
                if not d.get("converged"):
                    continue
                trial_tier = arm_to_tier(d.get("arm", ""))
                if trial_tier != model_tier:
                    continue
                wall = d.get("wall_clock_seconds")
                if isinstance(wall, (int, float)) and wall > 0:
                    walls.append(float(wall))
    if len(walls) < min_samples:
        return None
    walls.sort()
    # p90 = the wall at the 90th percentile rank
    p90_idx = max(0, min(len(walls) - 1, int(math.ceil(0.9 * len(walls))) - 1))
    return {
        "n": len(walls),
        "median_wall": statistics.median(walls),
        "p90_wall": walls[p90_idx],
    }


def query_safeguard_wall_cap(
    scenario: str,
    model_tier: str,
    multiplier: float = 2.0,
    search_roots: Optional[List[str]] = None,
) -> Optional[float]:
    """Convenience wrapper: return p90_wall × multiplier as resource cap,
    or None when history is insufficient (= no cap, open run).
    """
    stats = query_converged_stats(scenario, model_tier, search_roots=search_roots)
    if stats is None:
        return None
    return stats["p90_wall"] * float(multiplier)

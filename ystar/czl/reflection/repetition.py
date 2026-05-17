"""
ystar.czl.reflection.repetition — v3.5 T4 repetition detection.

If the last 2 (or N) iterations produced an IDENTICAL failure pattern,
the model is stuck in a local optimum. Emit a META block telling it
"same approach won't work, pick a different direction from instruction".

Fingerprint is over the SIGNAL — verifier_name + reason + cluster key —
NOT over the model's output. So the same failure pattern with slightly
different surface phrasing still fingerprints the same.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, List, Optional


def failure_fingerprint(verifier_results) -> str:
    """Stable hash over the (sorted) set of failing-verifier signals.

    Signal = `verifier_name :: reason` for each failed result. Reason is
    the v3.5 Hook field; if absent, falls back to `message`.

    Returns "" when there are no failures (no fingerprint to compare
    against).
    """
    if not verifier_results:
        return ""
    signals: List[str] = []
    for r in verifier_results:
        if getattr(r, "passed", True):
            continue
        sig = (
            f"{r.verifier_name}::"
            f"{(getattr(r, 'reason', '') or getattr(r, 'message', '') or '')[:200]}"
        )
        signals.append(sig)
    if not signals:
        return ""
    # Sort so the order verifiers ran in doesn't perturb the hash.
    signals.sort()
    blob = "\n".join(signals).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def detect_repetition(
    iter_history: Iterable,
    window: int = 2,
) -> Optional[str]:
    """If the last `window` iters share a fingerprint, return a META text.

    Each element of `iter_history` is a list of VerifierResult (one
    iter's verifier outputs).
    """
    history = list(iter_history)
    if len(history) < window:
        return None
    fingerprints = [failure_fingerprint(h) for h in history[-window:]]
    if not fingerprints[0] or fingerprints[0] == "":
        return None
    if not all(fp == fingerprints[0] for fp in fingerprints):
        return None
    return (
        f"META (repetition):\n"
        f"  Your last {window} iterations produced the IDENTICAL failure "
        f"pattern (fingerprint {fingerprints[0]}).\n"
        f"  Repeating the same approach will not change the result. "
        f"Pick a DIFFERENT direction from the instruction's 3 candidates — "
        f"if you tried (A) on the prior iter and it didn't help, "
        f"try (B) or (C) next."
    )

# Layer: Foundation
"""
ystar.adapters.runtime_contracts  --  Runtime constraint file I/O  v0.49.0
==========================================================================

Read/write the runtime constraint files that Path B (metalearning) produces:

  .ystar_runtime_deny.json   -- tightened constraints (Path B detected risk)
  .ystar_runtime_relax.json  -- relaxed constraints (quality score justifies)

Both files contain serialised IntentContract dicts.  The session contract
(from AGENTS.md / .ystar_session.json) is the ceiling:
  - deny can only be STRICTER than session (monotonicity)
  - relax cannot EXCEED session boundaries

These three layers are merged by merge_contracts() to produce the effective
contract for each hook call:

    effective = merge_contracts(session, deny, relax)

Design constraints:
  - Pure file I/O + validation -- no governance logic here
  - All writes produce a CIEU audit event (applied or rejected)
  - Monotonicity violations are logged and rejected, never silently accepted
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from ystar.kernel.dimensions import IntentContract

_log = logging.getLogger("ystar.adapters.runtime_contracts")

# File names are fixed by convention -- Path B writes them, hook reads them
_DENY_FILENAME = ".ystar_runtime_deny.json"
_RELAX_FILENAME = ".ystar_runtime_relax.json"


def load_runtime_deny(cwd: str) -> Optional[IntentContract]:
    """
    Read .ystar_runtime_deny.json from *cwd*, deserialise to IntentContract.

    Returns None if the file does not exist or cannot be parsed.
    """
    path = Path(cwd) / _DENY_FILENAME
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return IntentContract.from_dict(data)
    except Exception as exc:
        _log.warning("Failed to load %s: %s", path, exc)
        return None


def load_runtime_relax(cwd: str) -> Optional[IntentContract]:
    """
    Read .ystar_runtime_relax.json from *cwd*, deserialise to IntentContract.

    Returns None if the file does not exist or cannot be parsed.
    """
    path = Path(cwd) / _RELAX_FILENAME
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return IntentContract.from_dict(data)
    except Exception as exc:
        _log.warning("Failed to load %s: %s", path, exc)
        return None


def write_runtime_deny(
    contract: IntentContract,
    session_contract: IntentContract,
    cieu_store,
    agent_id: str,
) -> bool:
    """
    Write runtime_deny after validating monotonicity.

    Monotonicity check: *contract* must be a subset of *session_contract*
    (it can only be stricter, never looser).

    On violation  -> writes CIEU ``runtime_deny_rejected``, returns False.
    On success    -> writes file + CIEU ``runtime_deny_applied``, returns True.
    """
    ok, violations = contract.is_subset_of(session_contract)
    if not ok:
        _log.warning(
            "runtime_deny rejected -- monotonicity violation: %s", violations
        )
        if cieu_store is not None:
            try:
                cieu_store.write({
                    "event_type": "runtime_deny_rejected",
                    "agent_id": agent_id,
                    "reason": violations,
                })
            except Exception as exc:
                _log.debug("CIEU write failed: %s", exc)
        return False

    # Passed -- write the file
    path = os.path.join(os.getcwd(), _DENY_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(contract.to_dict(), f, indent=2)
    except Exception as exc:
        _log.error("Failed to write %s: %s", path, exc)
        return False

    if cieu_store is not None:
        try:
            cieu_store.write({
                "event_type": "runtime_deny_applied",
                "agent_id": agent_id,
                "contract": contract.to_dict(),
            })
        except Exception as exc:
            _log.debug("CIEU write failed: %s", exc)

    return True


def write_runtime_relax(
    contract: IntentContract,
    session_contract: IntentContract,
    quality_score: float,
    cieu_store,
    agent_id: str,
) -> bool:
    """
    Write runtime_relax after validating boundary and quality threshold.

    Check 1: *contract* must not exceed *session_contract* boundaries.
    Check 2: *quality_score* must be >= 0.65 (Board threshold).

    Returns True on success, False on rejection.
    """
    # Check 1: boundary
    ok, violations = contract.is_subset_of(session_contract)
    if not ok:
        _log.warning(
            "runtime_relax rejected -- exceeds session boundary: %s", violations
        )
        if cieu_store is not None:
            try:
                cieu_store.write({
                    "event_type": "runtime_relax_rejected",
                    "agent_id": agent_id,
                    "reason": violations,
                })
            except Exception as exc:
                _log.debug("CIEU write failed: %s", exc)
        return False

    # Check 2: quality threshold
    _QUALITY_THRESHOLD = 0.65
    if quality_score < _QUALITY_THRESHOLD:
        _log.warning(
            "runtime_relax rejected -- quality_score %.3f < %.2f threshold",
            quality_score, _QUALITY_THRESHOLD,
        )
        if cieu_store is not None:
            try:
                cieu_store.write({
                    "event_type": "runtime_relax_rejected",
                    "agent_id": agent_id,
                    "reason": f"quality_score {quality_score:.3f} < {_QUALITY_THRESHOLD}",
                })
            except Exception as exc:
                _log.debug("CIEU write failed: %s", exc)
        return False

    # Passed -- write the file
    path = os.path.join(os.getcwd(), _RELAX_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(contract.to_dict(), f, indent=2)
    except Exception as exc:
        _log.error("Failed to write %s: %s", path, exc)
        return False

    if cieu_store is not None:
        try:
            cieu_store.write({
                "event_type": "runtime_relax_applied",
                "agent_id": agent_id,
                "quality_score": quality_score,
            })
        except Exception as exc:
            _log.debug("CIEU write failed: %s", exc)

    return True


def merge_contracts(
    session: IntentContract,
    deny: Optional[IntentContract],
    relax: Optional[IntentContract],
) -> IntentContract:
    """
    Merge three contract layers into the effective runtime contract.

    Layer priority (highest to lowest):
      1. deny  -- always applied (tightens)
      2. session -- the baseline from AGENTS.md
      3. relax -- applied only when deny is absent for a dimension

    Delegates to ystar.kernel.merge.merge_contracts for full three-layer merge
    with monotonicity guarantees.
    """
    from ystar.kernel.merge import merge_contracts as kernel_merge

    return kernel_merge(session=session, deny=deny, relax=relax)

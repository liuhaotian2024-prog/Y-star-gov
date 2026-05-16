"""
CIEU hash-chained event log for the v3 seven-arm full-spectrum experiment.

Same shape as cieu_six_arm.py but pinned to .ystar_runtime_full_spectrum.cieu.jsonl.
We keep the v3 chain separate from v2 to make audit boundaries obvious.

v3 events MUST include these two extra flags on step_7-10:
  - quality_assessment_completed: bool
  - a_vs_a2_judge_completed: bool
The append_event signature accepts arbitrary kwargs to support this without
breaking the v2 helper.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_PATH = Path(__file__).resolve().parent.parent.parent / ".ystar_runtime_full_spectrum.cieu.jsonl"
GENESIS = "GENESIS"


def _event_hash(event: Dict[str, Any]) -> str:
    body = {k: v for k, v in event.items() if k != "event_hash"}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _last_event() -> Optional[Dict[str, Any]]:
    if not LOG_PATH.exists():
        return None
    with LOG_PATH.open("r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    if not lines:
        return None
    return json.loads(lines[-1])


def append_event(
    *,
    milestone_id: str,
    y_star: str,
    actions_taken: List[str],
    y_t_plus_1: str,
    r_t_plus_1: int,
    verify_command: str,
    verify_output_tail: str,
    quality_assessment_completed: Optional[bool] = None,
    a_vs_a2_judge_completed: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    prev = _last_event()
    prev_hash = prev["event_hash"] if prev else GENESIS
    event: Dict[str, Any] = {
        "ts": int(time.time()),
        "milestone_id": milestone_id,
        "y_star": y_star,
        "actions_taken": actions_taken,
        "y_t_plus_1": y_t_plus_1,
        "r_t_plus_1": r_t_plus_1,
        "verify_command": verify_command,
        "verify_output_tail": verify_output_tail[-500:],
        "prev_hash": prev_hash,
    }
    if quality_assessment_completed is not None:
        event["quality_assessment_completed"] = quality_assessment_completed
    if a_vs_a2_judge_completed is not None:
        event["a_vs_a2_judge_completed"] = a_vs_a2_judge_completed
    for k, v in extra.items():
        event[k] = v
    event["event_hash"] = _event_hash(event)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def verify_chain() -> Dict[str, Any]:
    if not LOG_PATH.exists():
        return {"ok": False, "events": 0, "errors": ["log missing"]}
    errors: List[str] = []
    n = 0
    expected_prev = GENESIS
    with LOG_PATH.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            n += 1
            ev = json.loads(line)
            if ev.get("prev_hash") != expected_prev:
                errors.append(f"line {i+1}: prev_hash mismatch")
            recomputed = _event_hash(ev)
            if recomputed != ev.get("event_hash"):
                errors.append(f"line {i+1}: event_hash mismatch ({ev.get('milestone_id')})")
            expected_prev = ev.get("event_hash", expected_prev)
    return {"ok": not errors, "events": n, "errors": errors}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        result = verify_chain()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["ok"] else 1)

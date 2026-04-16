"""
Coordinator Summary Rt Audit Helper
Meta-level enforcement for CEO/CTO replies containing closure language without Rt+1=0.

Board 2026-04-16 catch: CEO wrote "wave 完整收敛" while TaskList held 12+ pending items.
Gate 2 only validated sub-agent receipts, not coordinator-level summaries.

Usage:
    violation = check_summary_rt_drift(
        reply_text="今晚 wave 完整收敛...",
        taskstate=[
            {"id": "T1", "status": "pending", "description": "Fix bug"},
            {"id": "T2", "status": "pending", "description": "defer Phase 2"},
        ]
    )
    if violation:
        # Fire ForgetGuard warn with violation dict
"""

import re
from typing import Optional


def check_summary_rt_drift(
    reply_text: str,
    taskstate: list[dict]
) -> Optional[dict]:
    """
    Detect coordinator (CEO/CTO) claiming closure while pending tasks exist.

    Args:
        reply_text: CEO/CTO reply text (full message)
        taskstate: List of task dicts with keys {id, status, description}

    Returns:
        dict with {violation, claim_phrase, pending_count, unjustified_pending_ids}
        if closure claim + unjustified pending tasks exist, else None

    Closure language regex (Chinese + English):
        收敛, complete, 全部 done, wave.*shipped, 全部 verified, all green,
        fully resolved, landing complete, 所有.*完成
    """
    # Regex pattern for closure language (case-insensitive)
    closure_pattern = re.compile(
        r"("
        r"收敛|complete|全部\s*done|wave\s*.*shipped|"
        r"全部\s*verified|all\s+green|fully\s+resolved|"
        r"landing\s+complete|所有.*完成"
        r")",
        re.IGNORECASE
    )

    match = closure_pattern.search(reply_text)
    if not match:
        # No closure claim → skip
        return None

    claim_phrase = match.group(0)

    # Justified deferral keywords (case-insensitive)
    defer_keywords = [
        "defer",
        "Board-blocked",
        "pending Board",
        "Phase 2",
        "blocked by",
        "awaiting Board",
        "Board approval required",
    ]

    unjustified_pending = []
    for task in taskstate:
        if task.get("status") != "pending":
            continue

        description = task.get("description", "")
        is_justified = any(
            kw.lower() in description.lower()
            for kw in defer_keywords
        )

        if not is_justified:
            unjustified_pending.append(task.get("id", "unknown"))

    if not unjustified_pending:
        # All pending items are justified deferral → no violation
        return None

    return {
        "violation": True,
        "claim_phrase": claim_phrase,
        "pending_count": len(unjustified_pending),
        "unjustified_pending_ids": unjustified_pending,
    }


def check_wave_scope_declared(reply_text: str) -> Optional[dict]:
    """
    Detect wave/batch closure language without explicit TaskID list.

    Board 2026-04-16 batch drift fix: prose wave closure (e.g., "wave shipped")
    without explicit TaskID enumeration creates ambiguous scope.

    Args:
        reply_text: CEO/CTO reply text (full message)

    Returns:
        dict with {violation, wave_term, closure_term}
        if wave-language + closure-language detected but no TaskID list, else None

    Wave language: wave, 本批, 本轮
    Closure language: same as check_summary_rt_drift
    TaskID patterns: #\d+, task[_\s]?id (case-insensitive)
    """
    # Wave-language pattern
    wave_pattern = re.compile(r"(wave|本批|本轮)", re.IGNORECASE)

    # Closure-language pattern (reuse from check_summary_rt_drift)
    closure_pattern = re.compile(
        r"("
        r"收敛|complete|全部\s*done|shipped|"
        r"verified|all\s+green|fully\s+resolved|"
        r"landing\s+complete|所有.*完成"
        r")",
        re.IGNORECASE
    )

    # TaskID pattern (explicit task references)
    taskid_pattern = re.compile(r"(#\d+|task[_\s]?id)", re.IGNORECASE)

    wave_match = wave_pattern.search(reply_text)
    closure_match = closure_pattern.search(reply_text)
    taskid_match = taskid_pattern.search(reply_text)

    # Violation if wave-language + closure-language present but NO TaskID list
    if wave_match and closure_match and not taskid_match:
        return {
            "violation": True,
            "wave_term": wave_match.group(0),
            "closure_term": closure_match.group(0),
        }

    return None

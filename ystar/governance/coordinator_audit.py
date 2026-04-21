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


def is_dispatch_receipt(reply_text: str, agent_id: str = "ceo") -> tuple[bool, str]:
    """
    Stage 1 — Dispatch/Receipt Detection (Semantic 2-stage upgrade per methodology v1 §1-§2).

    Determines if reply is dispatch/receipt requiring 5-tuple structure, or conversational.

    Per reply_scan_detector_methodology_v1.md:
    - §1 TRIGGER: action verbs, artifact landing, state change, Board ASK response
    - §2 EXEMPTION: short ack, pure greeting, clarifying question, no triggers

    Args:
        reply_text: Full reply message text
        agent_id: Agent identifier (for logging, not used in detection logic)

    Returns:
        (is_dispatch, reason) tuple:
        - is_dispatch=True, reason="trigger:X" if reply requires 5-tuple
        - is_dispatch=False, reason="exempt:Y" if conversational, 5-tuple optional

    Examples:
        ("好的", "ceo") → (False, "exempt:short_reply")
        ("NOW 派 eng-platform CZL-99", "ceo") → (True, "trigger:action_verb")
        ("commit a1b2c3d landed", "maya-governance") → (True, "trigger:artifact_landed")
    """
    # §2 EXEMPTION CHECK FIRST (cheap path, avoids regex on short msgs)

    # §2.4: Short reply OR pure ack/greeting
    if len(reply_text.strip()) < 50:
        return False, "exempt:short_reply"

    # Pure conversational acks (Chinese + English)
    CONVERSATIONAL_ACKS = {
        "好的", "收到", "明白", "了解", "是的", "对", "懂", "OK",
        "yes", "ok", "got it", "understood", "roger", "ack", "will do", "on it"
    }
    stripped = reply_text.strip().rstrip("。!！.?？")
    if stripped.lower() in {a.lower() for a in CONVERSATIONAL_ACKS}:
        return False, "exempt:pure_ack"

    # §2.5: Clarifying question pattern
    clarify_pattern = re.compile(
        r"(我理解为|您是指|确认一下|Do you mean|Just to confirm|Clarifying)[^。!！.?？]*[?？]$",
        re.IGNORECASE
    )
    if clarify_pattern.search(reply_text):
        return False, "exempt:clarifying_question"

    # §1 TRIGGER CHECKS (any passes → must be 5-tuple)

    # §1.1: Action verbs to sub-agent
    action_verb_pattern = re.compile(
        r"(派|调起|执行|启动|spawn|分配|命令|指示|让\s+\w+\s+做|dispatch|executing|"
        r"now running|delegating to|routing to|calling|activating)",
        re.IGNORECASE
    )
    if action_verb_pattern.search(reply_text):
        return True, "trigger:action_verb"

    # §1.2: Artifact landing report (file paths, commits, maturity tags, metrics)
    artifact_pattern = re.compile(
        r"(shipped|landed|closed|Rt\+1\s*=\s*\d|L[0-5]\s+(SHIPPED|VALIDATED|TESTED)|"
        r"commit\s+[a-f0-9]{7,}|/Users/\S+\.(md|py|yaml|json|sh)|\d+/\d+\s+tests?\s+PASS|\d+%)",
        re.IGNORECASE
    )
    if artifact_pattern.search(reply_text):
        return True, "trigger:artifact_landed"

    # §1.3: State-change to project (campaign, task, system)
    state_change_pattern = re.compile(
        r"(Wave\s+\w+\s+closed|Subgoal\s+W\d+|Campaign\s+v\d+|Task\s+#\d+|"
        r"P[0-2]\s+escalation|Daemon\s+recycled|enforcement\s+LIVE|hook\s+promoted|"
        r"模式\s+切换|状态\s+变更)",
        re.IGNORECASE
    )
    if state_change_pattern.search(reply_text):
        return True, "trigger:state_change"

    # §1.4: Response to Board ASK (NOTE: requires board_previous_msg context — not implemented here,
    #       future enhancement if Stop hook can pass prior message)
    # Simplified: if reply contains status/metric language AND len >200, assume response
    board_ask_keywords = re.compile(
        r"(状态|进度|结果|status|progress|多少|几个|how many|count|percentage|决定|选择|recommendation)",
        re.IGNORECASE
    )
    if board_ask_keywords.search(reply_text):
        return True, "trigger:board_ask_response"

    # Default: if >200 chars and no triggers fired, treat as conversational
    # (§2.1-2.3: no action verbs, artifacts, metrics detected)
    return False, "exempt:conversational"


def _label_present(label: str, text: str) -> bool:
    """
    Robust label detection handling markdown bold + asterisk collision.

    Adopted from kernel/czl_protocol.py:89 dual-substring pattern.
    Fixes Y* false negatives when markdown bold escapes asterisk.

    Args:
        label: One of "Y*", "Xt", "U", "Yt+1", "Rt+1"
        text: Reply text to search

    Returns:
        True if label present (with or without escape), False otherwise

    Examples:
        _label_present("Y*", "**Y***") → True (raw asterisk)
        _label_present("Y*", "**Y\\***") → True (escaped asterisk)
        _label_present("Yt+1", "**Yt+1**") → True (literal plus)
        _label_present("Yt+1", "**Yt\\+1**") → True (escaped plus)
    """
    # Handle markdown bold + asterisk collision for Y*
    if label == "Y*":
        return ("**Y*" in text) or ("**Y\\*" in text) or ("Y\\*" in text)

    # Handle plus escape collision for Yt+1, Rt+1
    if label == "Yt+1":
        return ("Yt+1" in text) or ("Yt\\+1" in text)
    if label == "Rt+1":
        return ("Rt+1" in text) or ("Rt\\+1" in text)

    # Plain labels (Xt, U) — no escape collision
    return label in text


def validate_5tuple(reply_text: str, strictness: str = "strict") -> tuple[bool, list[str]]:
    """
    Stage 2 — 5-Tuple Structure Validation (Formal predicate per methodology v1 §3 + primer §4).

    Per formal_methods_primer_v1.md §4 worked example:
        Type Reply :: {Dispatch, Receipt, Notification, Query, Acknowledgment}
        Invariant: requires_5tuple(r) → has_labels(r, [Y*, Xt, U, Yt+1, Rt+1])

    Args:
        reply_text: Full reply message text
        strictness: "strict" | "lenient" | "permissive"
            - strict: all 5 labels required, in order, with content (CEO/CTO→Board)
            - lenient: ≥3 of 5 labels required, order flexible (sub-agents)
            - permissive: semantic 5-tuple without literal labels (NOT recommended)

    Returns:
        (passed, missing_labels) tuple:
        - passed=True, missing_labels=[] if validation passes
        - passed=False, missing_labels=["Y*", "Xt", ...] if labels absent

    Examples (strictness="strict"):
        "**Y\***: ... **Xt**: ... **U**: ... **Yt+1**: ... **Rt+1**: ..." → (True, [])
        "**Y\***: ... **U**: ... **Rt+1**: ..." → (False, ["Xt", "Yt+1"])

    Examples (strictness="lenient"):
        "Y*: ... Xt: ... U: ..." → (True, [])  # ≥3 labels present
        "Y*: ... U: ..." → (False, ["<3 labels (2/5)"])  # Only 2 labels
    """
    required_labels = ["Y*", "Xt", "U", "Yt+1", "Rt+1"]

    if strictness == "strict":
        # All 5 labels required, markdown bold syntax: **Label**: or **Label** newline
        # Use robust _label_present helper to handle escape collisions
        missing = []
        for label in required_labels:
            if not _label_present(label, reply_text):
                missing.append(label)
        return (len(missing) == 0, missing)

    elif strictness == "lenient":
        # ≥3 of 5 labels required, abbreviated ok (no bold required)
        labels_found = 0
        # Relaxed patterns: match label with or without markdown, case-insensitive for Xt/U
        lenient_patterns = [
            r"Y\*+",              # Y*, Y**, Y\*, etc.
            r"\bXt\b",            # Xt as word boundary
            r"\bU\b",             # U as word boundary (but avoid matching in URLs)
            r"Yt\+1",             # Yt+1
            r"Rt\+1"              # Rt+1
        ]
        for pattern in lenient_patterns:
            if re.search(pattern, reply_text, re.IGNORECASE):
                labels_found += 1

        passed = labels_found >= 3
        missing = [] if passed else [f"<3 labels found ({labels_found}/5)"]
        return (passed, missing)

    elif strictness == "permissive":
        # Semantic content check (requires NLP/LLM — not implemented, always pass)
        # Per methodology §3.3: NOT recommended for production
        return (True, [])

    else:
        # Unknown strictness: fall back to strict
        missing = []
        for label in required_labels:
            pattern = rf'\*\*{label}\*\*\s*:?\s+\S+'
            if not re.search(pattern, reply_text):
                missing.append(label.replace("\\", ""))
        return (len(missing) == 0, missing)


def check_reply_5tuple_compliance(reply_text: str, strictness: str = "strict", agent_id: str = None) -> Optional[dict]:
    """
    2-Stage Semantic 5-Tuple Compliance Check (Methodology v1 + Formal Primer upgrade).

    Replaces dumb regex with predicate-based dispatch detection + strictness-aware validation.

    Per reply_scan_detector_methodology_v1.md §1-§3 + formal_methods_primer_v1.md §4:
    - Stage 1: is_dispatch_receipt() → determines IF 5-tuple required (§1 trigger vs §2 exemption)
    - Stage 2: validate_5tuple() → validates 5-tuple structure per strictness level (§3 strict/lenient)

    Args:
        reply_text: CEO/CTO/sub-agent reply text (full message, Stop hook intercept)
        strictness: "strict" | "lenient" | "permissive" (default "strict")
                    - strict: all 5 labels required (CEO/Board replies)
                    - lenient: ≥3 of 5 labels required (sub-agent receipts)
                    - permissive: semantic 5-tuple without literal labels (not recommended)
        agent_id: Optional agent_id to auto-determine strictness from STRICTNESS_MAP

    Returns:
        dict with {violation, agent_id, reason, strictness, missing_labels, reply_length}
        if dispatch/receipt detected AND 5-tuple validation fails, else None

    Examples:
        check_reply_5tuple_compliance("好的", agent_id="ceo")
        → None (Stage 1 exempt:short_reply, no violation)

        check_reply_5tuple_compliance("NOW 派 eng-platform CZL-99 修复 X，禁 git。", agent_id="ceo")
        → {violation: True, reason: "trigger:action_verb", missing_labels: ["Y*", "Xt", "U", "Yt+1", "Rt+1"]}

        check_reply_5tuple_compliance("**Y\***: X **Xt**: Y **U**: Z", agent_id="maya-governance")
        → None (Stage 1 trigger:artifact_landed fires, Stage 2 lenient passes with 3/5 labels)
    """
    # Auto-determine strictness from agent_id if provided
    if agent_id:
        strictness = _get_strictness_for_agent(agent_id)

    # Stage 1: Dispatch detection (per methodology §1-§2)
    is_dispatch, reason = is_dispatch_receipt(reply_text, agent_id or "unknown")
    if not is_dispatch:
        # Conversational/exempt reply, 5-tuple optional → no violation
        return None

    # Stage 2: 5-tuple validation (per methodology §3 + primer §4)
    passed, missing_labels = validate_5tuple(reply_text, strictness)
    if passed:
        # 5-tuple structure valid → no violation
        return None

    # Violation: dispatch/receipt detected but 5-tuple missing/incomplete
    return {
        "violation": True,
        "agent_id": agent_id or "unknown",
        "reason": reason,
        "strictness": strictness,
        "missing_labels": missing_labels,
        "reply_length": len(reply_text)
    }


def _get_strictness_for_agent(agent_id: str) -> str:
    """
    Map agent_id to strictness level per reply_scan_detector_methodology_v1.md §3 STRICTNESS_MAP.

    Returns: "strict" | "lenient" | "permissive"
    """
    # Read STRICTNESS_MAP from methodology file (cached at module load)
    # Fallback to hardcoded map if file not available
    STRICTNESS_MAP = {
        "ceo": "strict",
        "Board": "strict",
        "cto": "strict",
        "eng-governance": "lenient",
        "eng-platform": "lenient",
        "eng-kernel": "lenient",
        "eng-domains": "lenient",
        "eng-data": "lenient",
        "eng-security": "lenient",
        "eng-ml": "lenient",
        "eng-perf": "lenient",
        "eng-compliance": "lenient",
        "default": "lenient"
    }

    # Check for eng-* prefix
    if agent_id.startswith("eng-"):
        return "lenient"

    return STRICTNESS_MAP.get(agent_id, STRICTNESS_MAP["default"])


def check_deferred_dispatch_orphan(
    reply_text: str,
    session_recent_actions: list[str]
) -> Optional[dict]:
    """
    Detect CEO/CTO promising future Agent dispatch without same-reply Agent call.

    Board 2026-04-16 P0 directive: CEO exhibits systematic deferred-dispatch hypocrisy
    ("下波派 X", "next round spawn Y", "后续调起 Z") without follow-through Agent calls.

    Root cause: Reply-tail attention dropout + Chinese passive voice + cognitive load overflow.
    Structural fix: ForgetGuard rule `ceo_deferred_dispatch_promise_orphan`.

    Args:
        reply_text: CEO/CTO reply text (full message)
        session_recent_actions: List of recent tool call names (last N actions in session)

    Returns:
        dict with {violation, promise_phrase, expected_engineer, actions_taken_after_promise}
        if deferred-dispatch promise detected AND no Agent call in session_recent_actions, else None

    Promise language patterns (Chinese + English):
        下波派 X, 后续调起 Y, next round spawn Z, next dispatch via W, 等 N 完成再派 M

    Escape valves (legitimate defer, no violation):
        - Explicit task card creation (mentions ".claude/tasks/")
        - Explicit WORLD_STATE.md backlog (mentions "WORLD_STATE.md")
        - Explicit Board escalation (mentions "Board blocked" or "pending Board")
    """
    # Deferred-dispatch promise pattern (case-insensitive)
    promise_pattern = re.compile(
        r"("
        r"下波派\s*([\w\-]+)|"
        r"后续调起\s*([\w\-]+)|"
        r"后续\s+(spawn|调起)\s*([\w\-]+)|"
        r"next\s+round\s+(spawn|dispatch)\s+([\w\-]+)|"
        r"next\s+dispatch\s+via\s+([\w\-]+)|"
        r"等.{1,8}完成.{1,8}(派|spawn|调起)\s*([\w\-]+)"
        r")",
        re.IGNORECASE
    )

    promise_match = promise_pattern.search(reply_text)
    if not promise_match:
        # No deferred-dispatch promise → skip
        return None

    promise_phrase = promise_match.group(0)

    # Extract expected engineer name from promise (heuristic: first captured word group)
    expected_engineer = None
    for group in promise_match.groups()[1:]:  # Skip full match group
        if group and group not in ["派", "spawn", "调起", "dispatch", "via"]:
            expected_engineer = group
            break

    # Check for escape valves (legitimate defer)
    escape_patterns = [
        r"\.claude/tasks/",
        r"WORLD_STATE\.md",
        r"Board\s+(blocked|approval|escalation)",
        r"pending\s+Board",
    ]
    for escape_pattern in escape_patterns:
        if re.search(escape_pattern, reply_text, re.IGNORECASE):
            # Legitimate defer via task card / backlog / Board escalation → no violation
            return None

    # Check if Agent call present in session recent actions
    if "Agent" in session_recent_actions:
        # Promise honored with Agent call in same reply → compliant
        return None

    return {
        "violation": True,
        "promise_phrase": promise_phrase,
        "expected_engineer": expected_engineer or "unknown",
        "actions_taken_after_promise": session_recent_actions,
    }


def check_hardcoded_cadence(text: str) -> Optional[dict]:
    """
    Detect hardcoded human time-grain in methodology/dispatch/receipt text.

    Board 2026-04-16 MEMORY feedback_methodology_no_human_time_grain enforcement:
    Methodology/dispatch/receipt must use dependency-sequence + event-trigger language ONLY.
    Hardcoded calendar cycles (weekly, monthly, quarterly, sprint, etc.) are forbidden.

    Args:
        text: Methodology spec / task dispatch / receipt text

    Returns:
        dict with {violation, matched_phrase, forbidden_keyword}
        if hardcoded cycle language detected, else None

    Forbidden patterns (case-insensitive):
        - Time cycle keywords: weekly, monthly, quarterly, sprint, biweekly, fortnight, annual, 24h, workday
        - Chinese equivalents: 每周, 每月, 每季, 每天
        - Week enumeration: Week 1, Week 2, etc.

    Allowed patterns (dependency-sequence language):
        - "after N atomic completions"
        - "after Board directive"
        - "when X event occurs"
        - "triggered by Y"
        - "following Z completion"

    Examples:
        Forbidden: "weekly review", "30d expiry", "Week 1-4 timeline", "每周检查"
        Allowed: "after 5 atomic completions", "after Board directive", "when OmissionEngine fires"
    """
    # Forbidden time-grain pattern (case-insensitive for English, exact for Chinese)
    # Includes English + Chinese calendar cycle keywords
    # Chinese characters don't need \b word boundaries
    forbidden_pattern = re.compile(
        r"("
        r"\b(weekly|monthly|quarterly|sprint|biweekly|fortnight|annual|24h|workday|Week\s*\d+)\b|"
        r"每周|每月|每季|每天"
        r")",
        re.IGNORECASE
    )

    match = forbidden_pattern.search(text)
    if not match:
        # No hardcoded cycle → compliant
        return None

    matched_phrase = match.group(0)

    # Extract surrounding context (±20 chars) for clarity
    start = max(0, match.start() - 20)
    end = min(len(text), match.end() + 20)
    context = text[start:end]

    return {
        "violation": True,
        "matched_phrase": matched_phrase,
        "forbidden_keyword": matched_phrase,
        "context": context,
    }

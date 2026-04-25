"""
ystar.kernel.czl_protocol — CZL Unified Communication Protocol v1.0
====================================================================

Gate 1/2 validators + legacy task parser for CEO/CTO ↔ sub-agent dispatch.
Extends rt_measurement.py RT_MEASUREMENT schema with communication envelope.

Constitutional Board 2026-04-16, fixes CTO#CZL-1 hallucination root cause.

Design Philosophy:
    - Gate 1: Pre-validator blocks launch if dispatch lacks 5-tuple structure
    - Gate 2: Post-validator rejects hallucinated success via empirical file checks
    - Auto-fill parser: Best-effort extraction from legacy task text

Enforcement Integration:
    - CEO/CTO calls validate_dispatch() BEFORE Agent tool spawn
    - CEO/CTO calls validate_receipt() AFTER sub-agent return
    - ForgetGuard rules (W22.3) wrap these validators for automated blocking

Schema Version: 1.0
Author: eng-kernel
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict


class CZLMessageEnvelope(TypedDict):
    """
    CZL communication envelope extending RT_MEASUREMENT v1.0.

    All CEO/CTO ↔ sub-agent dispatch and receipt messages use this schema.
    """
    # --- Core RT_MEASUREMENT v1.0 fields ---
    schema_version: str  # "1.0"
    task_id: str         # Unique ID (e.g., "ceo_task_42", "W5.1_eng-kernel")
    y_star: str          # Ideal contract (verifiable predicate)
    x_t: str             # Pre-state (measured via tool_use, NOT impression)
    u: list[str]         # Actions to execute (numbered, concrete tool calls)
    y_t_plus_1: str      # Post-state (predicted/measured, verifiable)
    rt_value: float      # Target (dispatch) or actual (receipt); 0.0 = closure

    # --- CZL Communication Extensions ---
    message_type: Literal["dispatch", "receipt"]
    sender: str          # "ceo", "cto", "eng-kernel", etc. (canonical agent ID)
    recipient: str       # Same format as sender
    dispatch_timestamp: str  # ISO8601 UTC when dispatch was sent
    parent_task_id: str | None  # If this is a sub-task, link to parent

    # --- Three-Dimensional Role Tags (K9 3D Audit) ---
    role_tags: dict[str, str]  # {"producer": "ceo", "executor": "eng-kernel", "governed": "eng-kernel"}


# --- Gate 1: Dispatch Pre-Validator ---

def validate_dispatch(prompt: str, agent_id: str | None = None) -> list[str]:
    """
    Validate CEO/CTO dispatch prompt against CZL envelope requirements.

    Extended with Stage 1 exemption (short acks / conversational) + STRICTNESS_MAP.
    Adopted from governance/coordinator_audit.py is_dispatch_receipt taxonomy.

    Args:
        prompt: Full sub-agent dispatch prompt text
        agent_id: Optional agent identifier to apply STRICTNESS_MAP (ceo/cto=strict, eng-*=lenient)

    Returns:
        List of missing/invalid sections (empty = valid, can launch)

    Rejection conditions:
        - Missing Y* (ideal contract)
        - Missing Xt (pre-state) OR Xt contains speculation markers
        - Missing U (actions list)
        - U contains ">15 tool_uses estimate" (violates atomic dispatch)
        - Missing Yt+1 (post-state verifiability clause)
        - Missing rt_value target
        - Missing recipient field
        - Missing task_id

    Exemptions (return [] immediately):
        - Short reply (<50 chars)
        - Pure ack (好的, OK, got it, etc.)
        - No action verbs AND no artifact references (conversational)

    STRICTNESS_MAP (when agent_id provided):
        - ceo/cto/Board: strict (all 5 labels required)
        - eng-*: lenient (≥3 of 5 labels required)

    Example:
        >>> issues = validate_dispatch(ceo_prompt, agent_id="ceo")
        >>> if issues:
        ...     print(f"Cannot launch: {issues}")
        ... else:
        ...     spawn_subagent(ceo_prompt)
    """
    # --- Stage 1: Exemption Short-Circuit (borrowed from coordinator_audit) ---

    # §2.4: Short reply OR pure ack → no validation needed
    if len(prompt.strip()) < 50:
        return []  # Conversational ack, no 5-tuple required

    # Pure conversational acks (Chinese + English)
    CONVERSATIONAL_ACKS = {
        "好的", "收到", "明白", "了解", "是的", "对", "懂", "OK",
        "yes", "ok", "got it", "understood", "roger", "ack", "will do", "on it"
    }
    stripped = prompt.strip().rstrip("。!！.?？")
    if stripped.lower() in {a.lower() for a in CONVERSATIONAL_ACKS}:
        return []  # Pure ack, no 5-tuple required

    # §1 semantic check: if no action verbs AND no artifact references → conversational
    #
    # Important: CZL-labeled text must NOT be exempted merely because it lacks
    # dispatch verbs. A partial envelope such as "Y*/Yt+1/Rt+1/Recipient" is
    # an attempted CZL dispatch and must continue into Gate 1 validation so
    # missing Xt/U can be rejected.
    import re
    czl_marker_pattern = re.compile(
        r"(\*\*Y\\?\*|\*\*Xt|\*\*X_t|\*\*U\b|\*\*Yt\+1|\*\*Y_t\+1|\*\*Rt\+1|rt_value|Recipient:|Task ID:)",
        re.IGNORECASE,
    )
    has_czl_markers = bool(czl_marker_pattern.search(prompt))

    action_pattern = re.compile(
        r"(派|调起|执行|启动|spawn|dispatch|routing|calling|activating|NOW|landed|shipped|commit)",
        re.IGNORECASE
    )
    if not action_pattern.search(prompt) and not has_czl_markers:
        # No dispatch/receipt language and no CZL envelope markers detected
        # → conversational, skip validation.
        return []

    # --- Stage 2: 5-Tuple Validation (apply STRICTNESS_MAP if agent_id provided) ---

    # Determine strictness level
    strictness = _get_strictness_for_agent(agent_id) if agent_id else "strict"

    issues = []

    # Check for 5-tuple structure markers
    if "**Y*" not in prompt and "**Y\\*" not in prompt:
        issues.append("Missing Y* (ideal contract)")

    if "**Xt" not in prompt and "**X_t" not in prompt:
        issues.append("Missing Xt (pre-state)")
    else:
        # Check for speculation markers in Xt
        xt_section = _extract_section(prompt, ["**Xt", "**X_t"])
        speculation_markers_zh = ["印象", "应该", "大概", "估计"]
        speculation_markers_en = ["should", "probably", "likely", "impression"]
        if any(marker in xt_section for marker in speculation_markers_zh + speculation_markers_en):
            issues.append("Xt contains speculation (not measured via tool_use)")

    if "**U" not in prompt:
        issues.append("Missing U (actions list)")
    else:
        # Check for atomic dispatch violation (>15 tool_uses estimate)
        u_section = _extract_section(prompt, ["**U"])
        if ">15 tool" in u_section or ">20 tool" in u_section:
            issues.append("U exceeds atomic dispatch limit (>15 tool_uses)")

    if "**Yt+1" not in prompt and "**Y_t+1" not in prompt:
        issues.append("Missing Yt+1 (post-state)")

    if "**Rt+1" not in prompt and "rt_value" not in prompt:
        issues.append("Missing Rt+1 target (gap threshold)")

    # --- Lenient Mode: ≥3 of 5 labels sufficient (for sub-agents) ---
    if strictness == "lenient":
        labels_found = sum([
            bool("**Y*" in prompt or "**Y\\*" in prompt),
            bool("**Xt" in prompt or "**X_t" in prompt),
            bool("**U" in prompt),
            bool("**Yt+1" in prompt or "**Y_t+1" in prompt),
            bool("**Rt+1" in prompt or "rt_value" in prompt),
        ])
        if labels_found >= 3:
            # ≥3 labels present → lenient pass, clear missing-label issues
            issues = [i for i in issues if not i.startswith("Missing")]

    # Check for recipient and task_id (can be implicit in context, warn only)
    if "recipient" not in prompt.lower() and "eng-" not in prompt:
        issues.append("Warning: No explicit recipient (which engineer?)")

    if "task_id" not in prompt and "Task ID:" not in prompt:
        issues.append("Warning: No explicit task_id")

    return issues


def _get_strictness_for_agent(agent_id: str | None) -> str:
    """
    Map agent_id to strictness level per STRICTNESS_MAP (borrowed from coordinator_audit).

    Returns: "strict" | "lenient" | "permissive"
    """
    if not agent_id:
        return "strict"  # Default to strict if agent_id unknown

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


# --- Gate 2: Receipt Post-Validator (EMPIRICAL VERIFICATION) ---

def validate_receipt(
    receipt: str,
    artifacts_expected: list[Path],
    tests_expected: dict[str, int] | None = None,
) -> tuple[bool, float]:
    """
    Empirically validate sub-agent receipt against declared Yt+1.

    This validator REJECTS hallucinated success claims by verifying artifacts
    on disk, not just parsing receipt text.

    Args:
        receipt: Sub-agent's CIEU 5-tuple receipt text
        artifacts_expected: Paths to files/dirs that MUST exist if Rt+1=0
        tests_expected: Optional test pass counts {"pytest": 6, "mypy": 0}

    Returns:
        (is_valid, actual_rt_plus_1) where:
            is_valid = all artifacts exist AND tests pass AND receipt rt_value ≤ gap
            actual_rt_plus_1 = empirical gap (0.0 = closure, >0 = incomplete)

    Validation steps:
        1. Parse receipt for claimed rt_value
        2. Check EVERY path in artifacts_expected with Path.exists()
        3. If tests_expected given, extract test output from receipt and verify counts
        4. Check receipt contains bash verification output (wc -l, ls -la, pytest -q, etc.)
        5. Compute actual_rt_plus_1:
            - +1.0 for each missing artifact
            - +1.0 if test output not found in receipt
            - +0.5 if claimed rt_value differs from empirical gap
        6. is_valid = (actual_rt_plus_1 == 0.0)

    Example (CTO#CZL-1 hallucination would be caught):
        >>> is_valid, gap = validate_receipt(
        ...     receipt=ethan_reply,
        ...     artifacts_expected=[Path("governance/czl_unified_communication_protocol_v1.md")],
        ... )
        >>> # File doesn't exist → gap = 1.0, is_valid = False
        >>> # CEO re-dispatches instead of reporting false success
    """
    gap = 0.0

    # Step 1: Parse claimed rt_value from receipt
    claimed_rt_match = re.search(r"Rt\+1.*?=\s*([\d.]+)", receipt)
    claimed_rt = float(claimed_rt_match.group(1)) if claimed_rt_match else None

    # Step 2: Check EVERY artifact with Path.exists()
    for artifact_path in artifacts_expected:
        if not artifact_path.exists():
            gap += 1.0

    # Step 3: Verify test output if tests_expected provided
    if tests_expected:
        # Look for pytest output patterns
        if "pytest" in tests_expected:
            expected_pass_count = tests_expected["pytest"]
            # Match patterns like "6 passed" or "12 passed in"
            pytest_match = re.search(r"(\d+)\s+passed", receipt)
            if not pytest_match:
                gap += 1.0
            elif int(pytest_match.group(1)) < expected_pass_count:
                gap += 1.0

    # Step 4: Check for bash verification output in receipt
    bash_verification_patterns = [
        r"ls -la.*?\n",
        r"wc -l.*?\n",
        r"pytest.*?(?:passed|failed)",
        r"git diff --stat",
    ]
    has_bash_verification = any(re.search(pattern, receipt) for pattern in bash_verification_patterns)
    if not has_bash_verification:
        gap += 1.0

    # Step 5: Check for zero-tool hallucination pattern
    # If receipt claims "done" but no tool evidence → instant reject
    zero_tool_patterns = ["我已完成", "done", "completed"]
    tool_evidence_patterns = [r"<function_calls>", r"tool_use", r"```bash"]
    has_completion_claim = any(pattern in receipt.lower() for pattern in zero_tool_patterns)
    has_tool_evidence = any(re.search(pattern, receipt) for pattern in tool_evidence_patterns)
    if has_completion_claim and not has_tool_evidence:
        gap += 5.0  # Instant reject for hallucination

    # Step 6: Compare claimed vs empirical gap
    if claimed_rt is not None and abs(claimed_rt - gap) > 0.1:
        gap += 0.5

    is_valid = (gap == 0.0)
    return is_valid, gap


# --- Auto-Fill Parser for Legacy Tasks ---

def parse_legacy_task_to_envelope(
    task_text: str,
    task_id: str,
    recipient: str,
) -> tuple[CZLMessageEnvelope, list[str]]:
    """
    Best-effort parser for legacy tasks → CZL envelope.

    Args:
        task_text: Raw task description (e.g., from .claude/tasks/ or TaskList)
        task_id: Assigned ID (e.g., "W5.1")
        recipient: Target agent ("eng-kernel", "eng-governance", etc.)

    Returns:
        (envelope, low_confidence_fields) where:
            envelope = CZLMessageEnvelope with auto-filled fields
            low_confidence_fields = list of field names that need human review

    Parsing strategy:
        Y*: Extract from "Acceptance Criteria" / "Success Condition" section
            If missing → use task title + " completed with tests passing"
        Xt: Extract from "Context" / "Current State" section
            If missing → flag as low-confidence, fill with "Not measured (legacy task)"
        U: Extract numbered list from task body
            If missing → infer from Files in Scope + task type (write/test/refactor)
        Yt+1: Mirror Y* with "verified by" clause
        rt_value: Default to 0.0 target
        role_tags: Auto-fill {"producer": "ceo", "executor": recipient, "governed": recipient}

    Low-confidence triggers:
        - No "Acceptance Criteria" section → flag Y*
        - No "Context" section → flag Xt
        - No numbered action list → flag U
        - Task description <50 chars → flag entire envelope

    Example:
        >>> envelope, low_conf = parse_legacy_task_to_envelope(
        ...     task_text=legacy_tasklist_item,
        ...     task_id="W5.1",
        ...     recipient="eng-kernel",
        ... )
        >>> if low_conf:
        ...     print(f"Human review needed: {low_conf}")
    """
    low_confidence_fields = []

    # Extract Y* from Acceptance Criteria / Success Condition
    y_star = _extract_section(task_text, ["Acceptance Criteria", "Success Condition", "**Y*"])
    if not y_star:
        # Fallback: use task title or first non-empty line
        first_line = next((line.strip() for line in task_text.split("\n") if line.strip()), "")
        y_star = f"{first_line} completed with tests passing"
        low_confidence_fields.append("y_star")

    # Extract Xt from Context / Current State
    x_t = _extract_section(task_text, ["Context", "Current State", "**Xt"])
    if not x_t:
        x_t = "Not measured (legacy task)"
        low_confidence_fields.append("x_t")

    # Extract U from numbered list
    u_items = _extract_numbered_list(task_text)
    if not u_items:
        # Fallback: generic actions
        u_items = ["Read relevant files", "Implement changes", "Write tests", "Verify with tools"]
        low_confidence_fields.append("u")

    # Generate Yt+1 from Y*
    y_t_plus_1 = f"{y_star} (verified by empirical checks)"

    # Default rt_value target
    rt_value = 0.0

    # Auto-fill role tags
    role_tags = {
        "producer": "ceo",
        "executor": recipient,
        "governed": recipient,
    }

    # Flag entire envelope if task too sparse
    if len(task_text) < 50:
        low_confidence_fields.extend(["y_star", "x_t", "u", "y_t_plus_1"])

    envelope: CZLMessageEnvelope = {
        "schema_version": "1.0",
        "task_id": task_id,
        "y_star": y_star,
        "x_t": x_t,
        "u": u_items,
        "y_t_plus_1": y_t_plus_1,
        "rt_value": rt_value,
        "message_type": "dispatch",
        "sender": "ceo",
        "recipient": recipient,
        "dispatch_timestamp": datetime.now(timezone.utc).isoformat(),
        "parent_task_id": None,
        "role_tags": role_tags,
    }

    return envelope, list(set(low_confidence_fields))


# --- Internal Helpers ---

def _extract_section(text: str, section_headers: list[str]) -> str:
    """Extract text content after any of the given section headers."""
    for header in section_headers:
        pattern = rf"{re.escape(header)}[:\s]*\n?(.*?)(?=\n\*\*|\n#|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _extract_numbered_list(text: str) -> list[str]:
    """Extract numbered list items (1. 2. 3. or 1) 2) 3))."""
    # Match patterns like "1. Item", "1) Item", "1 Item"
    pattern = r"^\s*(\d+)[.)]\s+(.+)$"
    items = []
    for line in text.split("\n"):
        match = re.match(pattern, line)
        if match:
            items.append(match.group(2).strip())
    return items


__all__ = [
    "CZLMessageEnvelope",
    "validate_dispatch",
    "validate_receipt",
    "parse_legacy_task_to_envelope",
]

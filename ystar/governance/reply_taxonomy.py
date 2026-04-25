"""
Reply Taxonomy Whitelist Validator — Formal Template Enumeration

Authority: eng-governance per CEO Campaign v6 CZL-123 P0 atomic
Upstream: Board 2026-04-16 architectural catch — blacklist→whitelist shift
Downstream: hook_stop_reply_scan.py injector #6 (Stop hook enforcement)
Purpose: Validate agent replies against 5 templates (DISPATCH/RECEIPT/NOTIFICATION/QUERY/ACK)

Mathematical foundation:
  valid_reply(r) := r.tag ∈ T ∧ template_structure_ok(r.tag, r)
  where T = {DISPATCH, RECEIPT, NOTIFICATION, QUERY, ACK}
  Mutual exclusion: ∀ i,j ∈ T, i ≠ j → template_i ∩ template_j = ∅
  Collective exhaustion: All legitimate replies ⊆ ⋃_{t ∈ T} template_t

Usage (Stop hook integration):
    from ystar.governance.reply_taxonomy import audit_reply

    violation = audit_reply(reply_text, agent_id)
    if violation:
        emit_cieu_event("REPLY_TEMPLATE_VIOLATION", violation)
        inject_system_reminder(violation["correction_hint"])
"""

import re
from typing import Optional, Tuple, Dict, List


# ═══ Template Tag Patterns ═══
TAG_PATTERNS = {
    "DISPATCH": re.compile(r'^\s*\[DISPATCH\]', re.IGNORECASE | re.MULTILINE),
    "RECEIPT": re.compile(r'^\s*\[RECEIPT\]', re.IGNORECASE | re.MULTILINE),
    "NOTIFICATION": re.compile(r'^\s*\[NOTIFICATION\]', re.IGNORECASE | re.MULTILINE),
    "QUERY": re.compile(r'^\s*\[QUERY\]', re.IGNORECASE | re.MULTILINE),
    "ACK": re.compile(r'^\s*\[ACK\]', re.IGNORECASE | re.MULTILINE),
}

# ═══ 5-Tuple Label Patterns (for DISPATCH/RECEIPT) ═══
FIVE_TUPLE_LABELS = [
    re.compile(r'\*\*Y\\?\*\*\*', re.IGNORECASE),  # **Y\*** or **Y***
    re.compile(r'\*\*Xt\*\*', re.IGNORECASE),
    re.compile(r'\*\*U\*\*', re.IGNORECASE),
    re.compile(r'\*\*Yt\+1\*\*', re.IGNORECASE),
    re.compile(r'\*\*Rt\+1\*\*', re.IGNORECASE),
]

# ═══ Forbidden Patterns (for DISPATCH/RECEIPT) ═══
DEFER_LANGUAGE = re.compile(
    r'(下波|明天|Phase\s+2|等\s*Board|暂停|defer|next\s+session|明日|tomorrow|Phase\s+3)',
    re.IGNORECASE
)
CHOICE_QUESTION = re.compile(
    r'(请选择|Option\s+[A-Z]|方案[一二三]|您决定|choose\s+[1-9]|select\s+option)',
    re.IGNORECASE
)

# ═══ Action Verbs (for DISPATCH/NOTIFICATION distinction) ═══
ACTION_VERBS = re.compile(
    r'(派|dispatch|spawn|executing|调起|routing\s+to|calling\s+Agent)',
    re.IGNORECASE
)

# ═══ Completion Claims (for RECEIPT/NOTIFICATION distinction) ═══
# Only catch STRONG completion claims (shipped/landed), NOT "closed" (too common in status updates)
COMPLETION_CLAIMS = re.compile(
    r'\b(shipped|landed)\b',
    re.IGNORECASE
)

# ═══ Metric/Artifact Patterns (for NOTIFICATION) ═══
METRIC_ARTIFACT = re.compile(
    r'(/Users/\S+\.\w+|commit\s+[a-f0-9]{7,}|L[0-5]\s+(SHIPPED|VALIDATED|TESTED)|\d+/\d+\s+tests|\d+%)',
    re.IGNORECASE
)


def extract_template_tag(reply_text: str) -> Optional[str]:
    """
    Extract template tag from reply text.

    Args:
        reply_text: Full assistant reply text

    Returns:
        Tag name (DISPATCH/RECEIPT/NOTIFICATION/QUERY/ACK) if found, else None

    Implementation:
        Searches for [TAG] pattern at start of reply (ignoring leading whitespace).
        If multiple tags found → returns first match (mutual exclusion violation
        handled in validate_template as error).
    """
    for tag_name, pattern in TAG_PATTERNS.items():
        if pattern.search(reply_text):
            return tag_name
    return None


def validate_template(tag: str, reply_text: str) -> Tuple[bool, List[str]]:
    """
    Validate reply structure against template requirements.

    Args:
        tag: Template tag (DISPATCH/RECEIPT/NOTIFICATION/QUERY/ACK)
        reply_text: Full assistant reply text

    Returns:
        (is_valid, error_list) tuple:
          - is_valid: True if reply satisfies all template constraints
          - error_list: List of violated constraints (empty if valid)

    Template constraints per governance/reply_taxonomy_whitelist_v1.md §2.
    """
    errors = []

    # ─── Template: DISPATCH ───
    if tag == "DISPATCH":
        # Require all 5-tuple labels
        for i, label_pattern in enumerate(FIVE_TUPLE_LABELS):
            if not label_pattern.search(reply_text):
                label_names = ["Y\*", "Xt", "U", "Yt+1", "Rt+1"]
                errors.append(f"missing_5tuple_label: {label_names[i]}")

        # Require agent_id mention.
        #
        # Accept canonical role IDs (eng-*, cto, secretary, etc.), Claude-style
        # opaque sub-agent IDs, and Bridge Labs staff short names commonly used
        # in human-facing dispatch receipts (e.g. "派 Maya").
        agent_mention = re.search(
            r'(eng-\w+|cto|ceo|cmo|cso|cfo|secretary|sub-agent\s+[a-f0-9]{16}|\b(Maya|Ryan|Leo|Jordan|Ethan|Samantha|Alex|Priya|Carlos|Elena|Aiden)\b)',
            reply_text,
            re.IGNORECASE
        )
        if not agent_mention:
            errors.append("missing_agent_id: no target agent mentioned")

        # Require action verbs
        if not ACTION_VERBS.search(reply_text):
            errors.append("missing_action_verbs: no dispatch/spawn/executing found")

        # Forbid defer language
        if DEFER_LANGUAGE.search(reply_text):
            errors.append("forbidden_defer_language")

        # Forbid choice questions
        if CHOICE_QUESTION.search(reply_text):
            errors.append("forbidden_choice_question")

    # ─── Template: RECEIPT ───
    elif tag == "RECEIPT":
        # Require all 5-tuple labels
        for i, label_pattern in enumerate(FIVE_TUPLE_LABELS):
            if not label_pattern.search(reply_text):
                label_names = ["Y\*", "Xt", "U", "Yt+1", "Rt+1"]
                errors.append(f"missing_5tuple_label: {label_names[i]}")

        # Require Rt+1 value (numeric: "Rt+1: 0" or "Rt+1=0" or "Rt+1=N" or "0 when X" conditional)
        # Use \*\* to match markdown bold: **Rt+1**: 0
        rt_plus_1_value = re.search(r'Rt\+1\*\*\s*[:：]?\s*(\d+|0\s+when|1\s+if)', reply_text, re.IGNORECASE)
        if not rt_plus_1_value:
            errors.append("missing_rt_plus_1_value: must explicitly state Rt+1=N")

        # Require empirical pastes (heuristic: ≥2 code blocks or ls/pytest/grep keywords)
        code_blocks = len(re.findall(r'```', reply_text))
        empirical_keywords = len(re.findall(
            r'(pytest|ls\s+-la|wc\s+-l|grep|git\s+log|commit\s+[a-f0-9]{7})',
            reply_text,
            re.IGNORECASE
        ))
        if code_blocks < 2 and empirical_keywords < 2:
            errors.append("missing_empirical_pastes: require ≥2 code blocks or empirical keywords")

        # Forbid choice questions
        if CHOICE_QUESTION.search(reply_text):
            errors.append("forbidden_choice_question")

    # ─── Template: NOTIFICATION ───
    elif tag == "NOTIFICATION":
        # Require ≥1 metric/artifact
        if not METRIC_ARTIFACT.search(reply_text):
            errors.append("missing_metric_artifact: no file path/commit/count/percentage found")

        # Forbid action verbs (notification is passive state broadcast)
        if ACTION_VERBS.search(reply_text):
            errors.append("forbidden_action_verbs: use [DISPATCH] for task assignment")

        # Forbid completion claims (use [RECEIPT] instead)
        if COMPLETION_CLAIMS.search(reply_text):
            errors.append("forbidden_completion_claims: use [RECEIPT] for shipped/Rt+1=0")

    # ─── Template: QUERY ───
    elif tag == "QUERY":
        # Extract query body (everything after [QUERY] tag)
        query_body = re.sub(r'^\s*\[QUERY\]\s*', '', reply_text, flags=re.IGNORECASE).strip()

        # Require question mark at end of query body
        if not re.search(r'[?？]\s*$', query_body):
            errors.append("missing_question_mark: query must end with ? or ？")

        # Require length ≤120 chars (excluding tag prefix)
        if len(query_body) > 120:
            errors.append(f"query_too_long: {len(query_body)} chars (max 120)")

        # Forbid action verbs in query body
        if ACTION_VERBS.search(query_body):
            errors.append("forbidden_action_verbs: query cannot contain dispatch/executing")

        # Forbid metrics/artifacts in query body (not entire reply — tag itself is OK)
        if METRIC_ARTIFACT.search(query_body):
            errors.append("forbidden_metrics: query cannot report completion (use [RECEIPT])")

    # ─── Template: ACK ───
    elif tag == "ACK":
        # Extract ack body (everything after [ACK] tag)
        ack_body = re.sub(r'^\s*\[ACK\]\s*', '', reply_text, flags=re.IGNORECASE).strip()

        # Require length ≤30 chars (excluding tag prefix)
        if len(ack_body) > 30:
            errors.append(f"ack_too_long: {len(ack_body)} chars (max 30)")

        # Forbid action verbs in ack body
        if ACTION_VERBS.search(ack_body):
            errors.append("forbidden_action_verbs: ack cannot contain action claims")

        # Forbid metrics/artifacts in ack body
        if METRIC_ARTIFACT.search(ack_body):
            errors.append("forbidden_metrics: ack cannot contain Rt+1/commit hash (use [RECEIPT])")

    is_valid = len(errors) == 0
    return is_valid, errors


def audit_reply(reply_text: str, agent_id: str) -> Optional[Dict]:
    """
    Audit agent reply against whitelist taxonomy.

    Args:
        reply_text: Full assistant reply text
        agent_id: Agent identifier (for CIEU event attribution)

    Returns:
        None if reply is valid, else dict with violation details:
          {
            "agent_id": str,
            "violation_type": "missing_tag" | "invalid_template" | "multiple_tags",
            "tag": str or None,
            "errors": [str],
            "correction_hint": str,
          }

    Usage:
        violation = audit_reply(reply_text, "ceo")
        if violation:
            emit_cieu_event("REPLY_TEMPLATE_VIOLATION", violation)
            inject_system_reminder(violation["correction_hint"])
    """
    # Step 1: Extract tag
    tag = extract_template_tag(reply_text)

    if tag is None:
        # No tag found → violation
        return {
            "agent_id": agent_id,
            "violation_type": "missing_tag",
            "tag": None,
            "errors": ["no_template_tag"],
            "correction_hint": (
                "Your reply must start with one of 5 tags: "
                "[DISPATCH], [RECEIPT], [NOTIFICATION], [QUERY], [ACK]. "
                "See governance/reply_taxonomy_whitelist_v1.md for spec."
            ),
        }

    # Step 2: Check for multiple tags (mutual exclusion violation)
    tag_count = sum(1 for pattern in TAG_PATTERNS.values() if pattern.search(reply_text))
    if tag_count > 1:
        return {
            "agent_id": agent_id,
            "violation_type": "multiple_tags",
            "tag": tag,
            "errors": [f"multiple_tags: found {tag_count} tags, expected 1"],
            "correction_hint": (
                "Reply contains multiple template tags. Each reply must have exactly one tag. "
                "Split into multiple sequential replies if needed."
            ),
        }

    # Step 3: Validate template structure
    is_valid, errors = validate_template(tag, reply_text)

    if not is_valid:
        return {
            "agent_id": agent_id,
            "violation_type": "invalid_template",
            "tag": tag,
            "errors": errors,
            "correction_hint": (
                f"[{tag}] template has {len(errors)} constraint violations: "
                f"{', '.join(errors)}. See governance/reply_taxonomy_whitelist_v1.md §2.{list(TAG_PATTERNS.keys()).index(tag)+1}."
            ),
        }

    # All checks passed → valid reply
    return None

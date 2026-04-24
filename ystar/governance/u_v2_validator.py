"""
U_v2 Cognitive Schema Validator
================================

Validates sub-agent receipt text against the U_v2 schema v0.1 (5 required fields).
Returns structured result indicating completeness, missing fields, and theater detection.

Schema source: governance/schemas/u_v2_schema_v0.1.yaml
Experiment: reports/experiments/exp_u_v2_schema_persistence_20260424.md

Platform Engineer: eng-platform
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ── Schema field definitions ──────────────────────────────────────────────

REQUIRED_FIELDS = ("m_tag", "empirical_basis", "counterfactual",
                   "preexisting_search", "rt_plus_1_honest")

M_TAG_ALLOWED = {"M-1", "M-2a", "M-2b", "M-3"}

# Minimum meaningful content lengths (theater detection thresholds)
_MIN_COUNTERFACTUAL_LEN = 30
_MIN_EMPIRICAL_REF_LEN = 3  # e.g. a file path or hash must be >=3 chars


@dataclass
class ValidationResult:
    """Result of U_v2 schema validation against a receipt."""
    is_complete: bool = False
    missing_fields: List[str] = field(default_factory=list)
    theater_fields: List[str] = field(default_factory=list)
    event_type: str = ""  # U_V2_SCHEMA_COMPLETE | _INCOMPLETE_DENY | _THEATER_DETECTED
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "is_complete": self.is_complete,
            "missing_fields": self.missing_fields,
            "theater_fields": self.theater_fields,
            "event_type": self.event_type,
            "details": self.details,
        }


# ── Field extraction from receipt text ────────────────────────────────────

def _extract_field(text: str, field_name: str) -> Optional[str]:
    """
    Extract a U_v2 field value from receipt text.

    Supports multiple formats:
      - **field_name**: value
      - field_name: value
      - ## field_name\nvalue
      - YAML-style field_name: value
    """
    # Pattern 1: **field_name**: value (markdown bold)
    pat_bold = re.compile(
        rf"\*\*{re.escape(field_name)}\*\*\s*[:=]\s*(.+?)(?=\n\*\*|\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pat_bold.search(text)
    if m:
        return m.group(1).strip()

    # Pattern 2: field_name: value (plain, line-start)
    pat_plain = re.compile(
        rf"^{re.escape(field_name)}\s*[:=]\s*(.+?)(?=\n[a-z_]+\s*[:=]|\n##|\Z)",
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    m = pat_plain.search(text)
    if m:
        return m.group(1).strip()

    # Pattern 3: ## field_name followed by content
    pat_heading = re.compile(
        rf"##\s*{re.escape(field_name)}\s*\n(.+?)(?=\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pat_heading.search(text)
    if m:
        return m.group(1).strip()

    return None


def _validate_m_tag(value: Optional[str]) -> Tuple[bool, bool]:
    """Returns (present, is_theater). Theater = present but not in allowed set."""
    if not value:
        return False, False
    clean = value.strip().split()[0] if value.strip() else ""
    # Accept if any allowed value appears in the field text
    for allowed in M_TAG_ALLOWED:
        if allowed in value:
            return True, False
    # Present but no valid enum value = theater
    return True, True


def _validate_empirical_basis(value: Optional[str]) -> Tuple[bool, bool]:
    """Returns (present, is_theater). Theater = present but refs too short."""
    if not value:
        return False, False
    # Must contain at least one reference-like token
    ref_patterns = [
        r"[/\\][\w/.+-]+\.\w+",          # file path
        r"[0-9a-f]{7,40}",               # git hash
        r"SELECT\s+",                     # SQL query
        r"test_\w+\s+(PASS|FAIL)",        # pytest result
        r"[\w/]+:\d+",                    # file:line
    ]
    for pat in ref_patterns:
        if re.search(pat, value, re.IGNORECASE):
            return True, False
    # Something is there but no recognizable reference
    if len(value.strip()) < _MIN_EMPIRICAL_REF_LEN:
        return True, True
    return True, True  # present but unverifiable refs = theater


def _validate_counterfactual(value: Optional[str]) -> Tuple[bool, bool]:
    """Returns (present, is_theater). Theater = present but < min_length."""
    if not value:
        return False, False
    if len(value.strip()) < _MIN_COUNTERFACTUAL_LEN:
        return True, True
    return True, False


def _validate_preexisting_search(value: Optional[str]) -> Tuple[bool, bool]:
    """Returns (present, is_theater). Theater = present but no glob/grep evidence."""
    if not value:
        return False, False
    # Must contain glob pattern or results_count indicator
    has_evidence = bool(re.search(
        r"(glob|grep|find|results?_count|results?:\s*\d|\*\*/|\d+\s+results?|\d+\s+files?)",
        value, re.IGNORECASE
    ))
    if not has_evidence:
        return True, True
    return True, False


def _validate_rt_plus_1_honest(value: Optional[str]) -> Tuple[bool, bool]:
    """
    Returns (present, is_theater).
    Theater = claims 0 without artifact reference, or is pure performative "0".
    """
    if not value:
        return False, False
    stripped = value.strip()
    # "0" alone without artifact ref is performative
    if stripped == "0" or stripped == "0.0":
        return True, True
    # "0 -- metric X met per artifact Y" is legit
    if re.match(r"^0\s*[-—:]+\s*\S", stripped):
        return True, False
    # Non-zero with explanation is honest
    if re.search(r"(non-zero|gap|remaining|not yet|still|pending|TBD)", stripped, re.IGNORECASE):
        return True, False
    return True, False


# ── Main validation entry point ───────────────────────────────────────────

_FIELD_VALIDATORS = {
    "m_tag": _validate_m_tag,
    "empirical_basis": _validate_empirical_basis,
    "counterfactual": _validate_counterfactual,
    "preexisting_search": _validate_preexisting_search,
    "rt_plus_1_honest": _validate_rt_plus_1_honest,
}


def validate_receipt(receipt_text: str) -> ValidationResult:
    """
    Validate a sub-agent receipt against U_v2 schema v0.1.

    Args:
        receipt_text: Full receipt text from sub-agent.

    Returns:
        ValidationResult with event_type set to one of:
          - U_V2_SCHEMA_COMPLETE: all 5 fields present and non-theater
          - U_V2_SCHEMA_INCOMPLETE_DENY: one or more fields missing
          - U_V2_THEATER_DETECTED: fields present but content is empty/shallow
    """
    result = ValidationResult(details={"field_status": {}})

    for field_name in REQUIRED_FIELDS:
        raw_value = _extract_field(receipt_text, field_name)
        validator = _FIELD_VALIDATORS[field_name]
        present, is_theater = validator(raw_value)

        result.details["field_status"][field_name] = {
            "present": present,
            "theater": is_theater,
            "raw_length": len(raw_value) if raw_value else 0,
        }

        if not present:
            result.missing_fields.append(field_name)
        elif is_theater:
            result.theater_fields.append(field_name)

    # Determine event type
    if result.missing_fields:
        result.event_type = "U_V2_SCHEMA_INCOMPLETE_DENY"
        result.is_complete = False
    elif result.theater_fields:
        result.event_type = "U_V2_THEATER_DETECTED"
        result.is_complete = False
    else:
        result.event_type = "U_V2_SCHEMA_COMPLETE"
        result.is_complete = True

    return result

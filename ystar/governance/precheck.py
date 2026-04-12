# Y*gov - Runtime Governance Framework
# Copyright (C) 2026 Y* Bridge Labs
# MIT License
"""
Precheck Engine — Executive precheck validation before Level 2/3 directive execution.

Validates that agent precheck reports match their cognitive profiles defined in
.ystar_session.json. Enforces role-based thinking discipline (Iron Rule 1 compliant).

Usage:
    from ystar.governance.precheck import validate_precheck, PrecheckResult

    result = validate_precheck(
        agent_id="cto",
        directive_level=2,
        primary_dimension="技术可行性",
        primary_risk="技术故障",
        assumption="系统可以在不重启服务的情况下升级",
        worst_case="升级失败导致服务中断",
        cognitive_profiles=config["cognitive_profiles"]
    )

    if not result.passed:
        print(result.reason)
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class PrecheckResult:
    """Result of precheck validation."""
    passed: bool
    reason: str
    allowed_dimensions: List[str]
    allowed_risks: List[str]
    agent_id: str
    directive_level: int
    conclusion: str


def load_cognitive_profile(
    agent_id: str,
    cognitive_profiles: Dict[str, Dict]
) -> Optional[Dict]:
    """Load cognitive profile for an agent from configuration.

    Args:
        agent_id: Agent identifier (e.g. "cto", "cmo", "ceo")
        cognitive_profiles: Dict from .ystar_session.json["cognitive_profiles"]

    Returns:
        Dict with keys: primary_dimensions, primary_risks, success_metrics
        None if agent_id not found (warnings issued, not hard failure)
    """
    return cognitive_profiles.get(agent_id)


def validate_precheck(
    agent_id: str,
    directive_level: int,
    primary_dimension: str,
    primary_risk: str,
    assumption: str,
    worst_case: str,
    cognitive_profiles: Dict[str, Dict],
    cross_dimension_note: str = "",
    conclusion: str = "no_objection",
) -> PrecheckResult:
    """Validate that precheck report matches agent's cognitive profile.

    Validation rules (deterministic, Iron Rule 1 compliant):
    1. Level 1 directives → ALLOW without validation (speed优先)
    2. Load agent's cognitive_profile from config
    3. Check primary_dimension in profile's primary_dimensions list
    4. Check primary_risk in profile's primary_risks list
    5. Check assumption and worst_case length >= 10
    6. If any check fails → DENY with clear guidance
    7. If conclusion == "escalate" → create CEO obligation (handled by caller)

    Args:
        agent_id: Agent submitting the precheck
        directive_level: 1, 2, or 3 (Level 1 bypasses validation)
        primary_dimension: Must match agent's cognitive profile
        primary_risk: Must match agent's cognitive profile
        assumption: Core assumption text (min 10 chars)
        worst_case: Worst case outcome text (min 10 chars)
        cognitive_profiles: Full cognitive_profiles dict from .ystar_session.json
        cross_dimension_note: Optional cross-role observation
        conclusion: "no_objection" | "adjust" | "escalate"

    Returns:
        PrecheckResult with passed, reason, and guidance
    """
    # Level 1 directives bypass validation
    if directive_level == 1:
        return PrecheckResult(
            passed=True,
            reason="Level 1 directive — precheck not required",
            allowed_dimensions=[],
            allowed_risks=[],
            agent_id=agent_id,
            directive_level=directive_level,
            conclusion=conclusion,
        )

    # Load cognitive profile
    profile = load_cognitive_profile(agent_id, cognitive_profiles)

    # Unknown agent — allow with warning
    if profile is None:
        return PrecheckResult(
            passed=True,
            reason=f"WARNING: No cognitive profile found for '{agent_id}' — validation skipped",
            allowed_dimensions=[],
            allowed_risks=[],
            agent_id=agent_id,
            directive_level=directive_level,
            conclusion=conclusion,
        )

    allowed_dims = profile.get("primary_dimensions", [])
    allowed_risks = profile.get("primary_risks", [])

    # Validation checks
    violations = []

    # Check 1: primary_dimension match
    if primary_dimension not in allowed_dims:
        violations.append(
            f"primary_dimension '{primary_dimension}' not in {agent_id}'s cognitive profile. "
            f"Allowed: {allowed_dims}"
        )

    # Check 2: primary_risk match
    if primary_risk not in allowed_risks:
        violations.append(
            f"primary_risk '{primary_risk}' not in {agent_id}'s cognitive profile. "
            f"Allowed: {allowed_risks}"
        )

    # Check 3: assumption length
    if len(assumption.strip()) < 10:
        violations.append(
            f"assumption too short ({len(assumption)} chars) — must be at least 10 characters"
        )

    # Check 4: worst_case length
    if len(worst_case.strip()) < 10:
        violations.append(
            f"worst_case too short ({len(worst_case)} chars) — must be at least 10 characters"
        )

    # Return result
    if violations:
        return PrecheckResult(
            passed=False,
            reason="; ".join(violations),
            allowed_dimensions=allowed_dims,
            allowed_risks=allowed_risks,
            agent_id=agent_id,
            directive_level=directive_level,
            conclusion=conclusion,
        )
    else:
        return PrecheckResult(
            passed=True,
            reason="Precheck validated — matches cognitive profile",
            allowed_dimensions=allowed_dims,
            allowed_risks=allowed_risks,
            agent_id=agent_id,
            directive_level=directive_level,
            conclusion=conclusion,
        )

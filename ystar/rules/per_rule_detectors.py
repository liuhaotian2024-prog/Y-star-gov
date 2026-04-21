# Layer: Foundation
"""
ystar.rules.per_rule_detectors — Per-rule governance telemetry detectors
========================================================================

CZL-ARCH-3: Migrated from ystar-company/scripts/per_rule_detectors.py.

These 6 detectors were previously imported via sys.path.insert into
boundary_enforcer.py, creating a reverse dependency from the Y*gov
kernel package to the ystar-company control plane.  They are now
self-contained RouterRule objects that register into RouterRegistry
and run at Layer 3 during handle_hook_event().

Each detector emits a CIEU telemetry event (decision="allow" with
injected context) rather than blocking.  They are advisory-level
rules (priority 50) — they observe and log but do not deny.

Original author: eng-platform, CZL-78 P1 (2026-04-16).
Migration: eng-governance, CZL-ARCH-3 (2026-04-18).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ystar.governance.router_registry import RouterResult, RouterRule

_log = logging.getLogger("ystar.rules.per_rule_detectors")


# ══════════════════════════════════════════════════════════════════════
# Detector functions (pure: payload -> Optional[dict])
# ══════════════════════════════════════════════════════════════════════

def _detect_dispatch_missing_5tuple(payload: dict) -> Optional[dict]:
    """Detect Agent tool calls with dispatch prompts lacking CZL 5-tuple."""
    tool_name = payload.get("tool_name")
    if tool_name != "Agent":
        return None

    tool_input = payload.get("tool_input", {})
    if not tool_input.get("subagent_type"):
        return None

    prompt = tool_input.get("instructions") or tool_input.get("prompt") or ""
    required = ["Y*", "Xt", "U", "Yt+1", "Rt+1"]
    missing = [s for s in required if not re.search(rf"\*\*{re.escape(s)}\*\*", prompt, re.IGNORECASE)]

    if not missing:
        return None

    return {
        "violation_type": "CZL_DISPATCH_MISSING_5TUPLE",
        "evidence": f"Missing sections: {', '.join(missing)}. Dispatch to {tool_input.get('subagent_type')} lacks CZL structure.",
        "severity": "high",
        "missing_sections": missing,
    }


def _detect_receipt_rt_not_zero(payload: dict) -> Optional[dict]:
    """Detect SendMessage receipts claiming Rt+1=0 without empirical evidence."""
    if payload.get("tool_name") != "SendMessage":
        return None

    tool_input = payload.get("tool_input", {})
    message = tool_input.get("content") or tool_input.get("message") or ""

    rt_match = re.search(r"Rt\+1.*?[=:]\s*([\d.]+)", message, re.IGNORECASE)
    if not rt_match:
        return None

    if float(rt_match.group(1)) != 0.0:
        return None

    bash_markers = ["ls -la", "wc -l", "pytest", "git diff --stat", "grep -r", "find "]
    if any(m in message for m in bash_markers):
        return None

    return {
        "violation_type": "CZL_RECEIPT_RT_NOT_ZERO",
        "evidence": "Receipt claims Rt+1=0 but lacks bash verification output.",
        "severity": "high",
    }


def _detect_charter_drift_mid_session(payload: dict) -> Optional[dict]:
    """Detect mid-session edits to governance files without break-glass."""
    if payload.get("tool_name") not in ("Edit", "Write"):
        return None

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    gov_files = ["AGENTS.md", "governance/WORKING_STYLE.md", "governance/BOARD_CHARTER_AMENDMENTS.md"]
    if not any(file_path.endswith(gf) for gf in gov_files):
        return None

    agent_id = payload.get("agent_id", "unknown")
    ceo_mode = payload.get("ceo_mode", "normal")
    if agent_id in ("secretary", "Samantha-Secretary") or ceo_mode == "break_glass":  # LABS_ALIAS: Samantha-Secretary kept for backward compat
        return None

    return {
        "violation_type": "CHARTER_DRIFT_MID_SESSION",
        "evidence": f"Agent {agent_id} editing {file_path} without break-glass mode.",
        "severity": "high",
        "file_path": file_path,
    }


def _detect_wave_scope_undeclared(payload: dict) -> Optional[dict]:
    """Detect CEO campaign reports without Goal/Scope in first paragraph."""
    if payload.get("tool_name") != "Write":
        return None

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not ("campaign" in file_path.lower() or "wave" in file_path.lower()):
        return None
    if "reports/ceo/" not in file_path:
        return None

    content = tool_input.get("content", "")[:200]
    if any(m in content for m in ["Goal:", "Scope:", "\u76ee\u6807:", "\u8303\u56f4:"]):
        return None

    return {
        "violation_type": "WAVE_SCOPE_UNDECLARED",
        "evidence": f"Campaign report {file_path} lacks Goal/Scope in first paragraph.",
        "severity": "medium",
        "file_path": file_path,
    }


def _detect_subagent_unauthorized_git_op(payload: dict) -> Optional[dict]:
    """Detect sub-agents attempting destructive git operations."""
    if payload.get("tool_name") != "Bash":
        return None

    command = (payload.get("tool_input") or {}).get("command", "")
    destructive = [
        r"git\s+reset\s+--hard",
        r"git\s+push\s+.*--force",
        r"git\s+branch\s+-D",
        r"git\s+clean\s+-f",
        r"git\s+checkout\s+\.",
        r"git\s+restore\s+\.",
    ]
    if not any(re.search(p, command, re.IGNORECASE) for p in destructive):
        return None

    agent_id = payload.get("agent_id", "unknown")
    authorized = {"ceo", "cto", "secretary"}  # canonical role IDs
    # Also accept session-configured aliases for backward compat
    try:
        from ystar.adapters.identity_detector import _load_alias_map
        authorized |= set(_load_alias_map().keys())  # LABS_ALIAS: runtime aliases
    except ImportError:
        pass
    if agent_id in authorized:
        return None

    return {
        "violation_type": "SUBAGENT_UNAUTHORIZED_GIT_OP",
        "evidence": f"Agent {agent_id} attempted destructive git: {command[:80]}",
        "severity": "high",
    }


def _detect_realtime_artifact_archival(payload: dict) -> Optional[dict]:
    """Detect new artifacts in archival scope for SLA tracking."""
    if payload.get("tool_name") not in ("Write", "Edit"):
        return None

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    archival_prefixes = ["reports/", "knowledge/", "products/", "content/", "governance/"]
    if not any(file_path.startswith(p) or ("/" + p) in file_path for p in archival_prefixes):
        return None

    return {
        "violation_type": "ARTIFACT_ARCHIVAL_SCOPE_DETECTED",
        "evidence": f"New artifact in archival scope: {file_path}. Secretary SLA: index <=30min.",
        "severity": "low",
        "file_path": file_path,
    }


# ══════════════════════════════════════════════════════════════════════
# Detector list (same order as original per_rule_detectors.py)
# ══════════════════════════════════════════════════════════════════════

ALL_DETECTOR_FUNCTIONS = [
    _detect_dispatch_missing_5tuple,
    _detect_receipt_rt_not_zero,
    _detect_charter_drift_mid_session,
    _detect_wave_scope_undeclared,
    _detect_subagent_unauthorized_git_op,
    _detect_realtime_artifact_archival,
]


# ══════════════════════════════════════════════════════════════════════
# RouterRule wrappers
# ══════════════════════════════════════════════════════════════════════

def _make_detector_rule(fn, rule_id_suffix: str) -> RouterRule:
    """
    Wrap a detector function into a RouterRule.

    Detector functions return None (no match) or a violation dict.
    The RouterRule detector returns True when the function returns non-None.
    The executor returns an ALLOW result with a log message — these are
    telemetry rules, not blockers.  CIEU events are emitted by the
    executor for audit trail.
    """

    def detector(payload: Dict[str, Any]) -> bool:
        try:
            result = fn(payload)
            # Stash the result on the payload dict for the executor to read
            # (avoids running the detector twice)
            if result is not None:
                payload[f"_prd_{rule_id_suffix}"] = result
                return True
        except Exception as e:
            _log.warning("Detector %s raised %s: %s", rule_id_suffix, type(e).__name__, e)
        return False

    def executor(payload: Dict[str, Any]) -> RouterResult:
        result = payload.pop(f"_prd_{rule_id_suffix}", {})
        violation_type = result.get("violation_type", "UNKNOWN")
        evidence = result.get("evidence", "")
        severity = result.get("severity", "medium")

        # Emit CIEU event for telemetry
        try:
            from ystar.governance.cieu_store import CIEUStore
            import time as _time
            store = CIEUStore()
            store.write_dict({
                "event_type": violation_type,
                "entity_id": payload.get("agent_id", "unknown"),
                "timestamp": _time.time(),
                "params": {
                    "tool_name": payload.get("tool_name", ""),
                    "evidence": evidence,
                    "severity": severity,
                    "source": "ystar.rules.per_rule_detectors",
                }
            })
        except Exception as e:
            _log.debug("CIEU emit failed for %s: %s", violation_type, e)

        _log.info("[PerRuleDetector] %s: %s", violation_type, evidence)

        # Allow — these are telemetry, not blockers
        return RouterResult(
            decision="allow",
            message=f"[telemetry] {violation_type}: {evidence}",
        )

    return RouterRule(
        rule_id=f"builtin.per_rule.{rule_id_suffix}",
        detector=detector,
        executor=executor,
        priority=50,  # Advisory level
        metadata={
            "phase": "ARCH-3",
            "migrated_from": "scripts/per_rule_detectors.py",
            "description": fn.__doc__ or "",
        },
    )


# ══════════════════════════════════════════════════════════════════════
# RULES export (consumed by RouterRegistry.load_rules_dir or
# direct registration via register_builtin_rules())
# ══════════════════════════════════════════════════════════════════════

RULES: List[RouterRule] = [
    _make_detector_rule(_detect_dispatch_missing_5tuple, "dispatch_missing_5tuple"),
    _make_detector_rule(_detect_receipt_rt_not_zero, "receipt_rt_not_zero"),
    _make_detector_rule(_detect_charter_drift_mid_session, "charter_drift_mid_session"),
    _make_detector_rule(_detect_wave_scope_undeclared, "wave_scope_undeclared"),
    _make_detector_rule(_detect_subagent_unauthorized_git_op, "subagent_unauthorized_git_op"),
    _make_detector_rule(_detect_realtime_artifact_archival, "realtime_artifact_archival"),
]


def register_builtin_rules() -> int:
    """
    Register all per-rule detector rules into the default RouterRegistry.

    Returns the number of rules successfully registered.
    Idempotent: already-registered rules are silently skipped.
    """
    from ystar.governance.router_registry import get_default_registry
    registry = get_default_registry()
    registered = 0
    for rule in RULES:
        try:
            registry.register_rule(rule)
            registered += 1
        except ValueError:
            pass  # Already registered
    return registered

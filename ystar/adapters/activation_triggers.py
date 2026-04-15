import os
# Layer: Foundation
"""
ystar.adapters.activation_triggers  —  Proactive Skill Activation Registry  v0.49.0
===================================================================================

AMENDMENT-013: Trigger registry for proactive skill injection.

Instead of waiting for violations to teach, prime agents with relevant skills
BEFORE they execute actions. Transform governance from reactive correction to
proactive teaching.

Design:
  - Each trigger = (detection_pattern, skill_id, rule_name, priority, role_filter)
  - Hook checks triggers before allowing actions
  - ALLOW with skill injection instead of DENY after violation

Usage::

    from ystar.adapters.activation_triggers import ACTIVATION_TRIGGERS, should_activate_skill

    activation = should_activate_skill(
        agent_name="ceo",
        action_type="Write",
        action_params={"content": "autonomous mission to build X"},
        context={}
    )

    if activation:
        # Prepend skill to response, emit CIEU SKILL_ACTIVATION event
        inject_skill(activation)
"""
from __future__ import annotations
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ystar.session import SkillActivation

_log = logging.getLogger("ystar.activation")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*activation] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)


# ── Trigger Definition ──────────────────────────────────────────────────────

@dataclass
class ActivationTrigger:
    """Definition of when/how to activate a skill."""
    trigger_id: str              # unique identifier
    detection_fn: callable       # (agent, action_type, params, context) → bool
    skill_id_template: str       # e.g., "knowledge/{role}/skills/article_11.md"
    rule_name: str               # behavior rule name
    priority: int                # 1=highest
    role_filter: List[str]       # empty = all roles


# ── Trigger Registry (Phase 1: 5 triggers) ──────────────────────────────────

def _detect_autonomous_mission(agent: str, action_type: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Detect autonomous mission declaration.

    Triggers when:
    - Action contains "autonomous" or "自主任务" keywords
    - Agent is making symbol alignment declaration (not just casual mention)
    """
    if action_type not in {"Write", "Edit", "Bash"}:
        return False

    # Check content for autonomous mission keywords
    content = ""
    if "content" in params:
        content = params["content"].lower()
    elif "new_string" in params:
        content = params["new_string"].lower()
    elif "command" in params:
        content = params["command"].lower()

    # Keyword detection
    keywords = ["autonomous mission", "自主任务", "autonomous task", "autonomous campaign"]
    has_keyword = any(kw in content for kw in keywords)

    # Symbol alignment pattern (stronger signal)
    symbol_pattern = re.compile(r"(symbol|符号)\s+(align|alignment|对齐)", re.IGNORECASE)
    has_symbol = symbol_pattern.search(content) is not None

    return has_keyword or has_symbol


def _detect_major_decision(agent: str, action_type: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Detect CEO making major strategic decision.

    Triggers when CEO uses decision/strategic keywords.
    """
    if agent not in {"ceo", "aiden"}:
        return False

    if action_type not in {"Write", "Edit"}:
        return False

    content = params.get("content", "") + params.get("new_string", "")
    content = content.lower()

    # Decision keywords
    keywords = ["决策", "decide", "decision", "战略", "strategic", "strategy", "重大选择", "major choice"]
    return any(kw in content for kw in keywords)


def _detect_code_edit(agent: str, action_type: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Detect code file modification.

    Triggers when agent edits/writes Python files.
    """
    if action_type not in {"Write", "Edit"}:
        return False

    file_path = params.get("file_path", "")
    if not file_path:
        return False

    return file_path.endswith(".py")


def _detect_serial_dispatch(agent: str, action_type: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Detect serial sub-agent dispatch (should use parallel).

    Triggers when agent has dispatched 2+ times in last 60 seconds with <30s gaps.

    TODO: implement dispatch history tracking (needs hook integration)
    """
    # Placeholder: detect Agent tool calls in action params
    if action_type != "Agent":
        return False

    # Phase 1: simple heuristic (delegate mentioned multiple times)
    # Phase 2: track actual dispatch history with timestamps
    return False  # disabled for MVP


def _detect_write_boundary_violation(agent: str, action_type: str, params: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """
    Detect CEO writing outside allowed paths.

    Triggers when CEO tries to write to restricted path (before actual DENY).
    This is PROACTIVE — we activate skill before the boundary check denies.

    NOTE: This is complementary to boundary_enforcer's DENY. We activate skill
    to teach the CORRECT pattern (board_ceo_override.sh or delegation), then
    let boundary_enforcer decide whether to allow/deny.
    """
    if agent not in {"ceo", "aiden"}:
        return False

    if action_type not in {"Write", "Edit"}:
        return False

    file_path = params.get("file_path", "")
    if not file_path:
        return False

    # CEO allowed paths (from AGENTS.md):
    # reports/, DIRECTIVE_TRACKER.md, BOARD_PENDING.md, etc.
    # If CEO is writing to code files, this should trigger skill
    restricted_patterns = [
        "/ystar/",           # Y*gov source code
        "/tests/",           # test files
        "/scripts/",         # infrastructure scripts
        "/.claude/agents/",  # agent definitions
    ]

    return any(pattern in file_path for pattern in restricted_patterns)


# ── Trigger Registry ────────────────────────────────────────────────────────

ACTIVATION_TRIGGERS: List[ActivationTrigger] = [
    ActivationTrigger(
        trigger_id="autonomous_mission_requires_article_11",
        detection_fn=_detect_autonomous_mission,
        skill_id_template="knowledge/{role}/skills/article_11_seven_layers.md",
        rule_name="autonomous_mission_requires_article_11",
        priority=1,
        role_filter=[]  # all roles
    ),
    ActivationTrigger(
        trigger_id="counterfactual_before_major_decision",
        detection_fn=_detect_major_decision,
        skill_id_template="knowledge/ceo/skills/counterfactual_before_major_decision.md",
        rule_name="counterfactual_before_major_decision",
        priority=1,
        role_filter=["ceo", "aiden"]
    ),
    ActivationTrigger(
        trigger_id="root_cause_fix_required",
        detection_fn=_detect_code_edit,
        skill_id_template="knowledge/{role}/skills/root_cause_fix_pattern.md",
        rule_name="root_cause_fix_required",
        priority=2,
        role_filter=["cto", "ethan", "eng-kernel", "eng-platform", "eng-governance", "eng-domains"]
    ),
    ActivationTrigger(
        trigger_id="parallel_dispatch_required",
        detection_fn=_detect_serial_dispatch,
        skill_id_template="knowledge/{role}/skills/parallel_dispatch_pattern.md",
        rule_name="parallel_dispatch_required",
        priority=3,
        role_filter=["ceo", "cto"]  # disabled for MVP
    ),
    ActivationTrigger(
        trigger_id="write_boundary_violation",
        detection_fn=_detect_write_boundary_violation,
        skill_id_template="knowledge/ceo/skills/board_ceo_override_or_delegate.md",
        rule_name="write_boundary_violation",
        priority=1,
        role_filter=["ceo", "aiden"]
    ),
]


# ── Public API ──────────────────────────────────────────────────────────────

def should_activate_skill(
    agent_name: str,
    action_type: str,
    action_params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Optional[SkillActivation]:
    """
    Check if any trigger matches, return SkillActivation or None.

    Args:
        agent_name: current agent (ceo, cto, eng-kernel, etc.)
        action_type: tool name (Write, Edit, Bash, Agent, etc.)
        action_params: tool parameters (file_path, content, command, etc.)
        context: additional context (CIEU history, session state, etc.)

    Returns:
        SkillActivation if triggered, None otherwise
    """
    if context is None:
        context = {}

    # Normalize agent name
    agent_norm = agent_name.lower().replace("-", "_")

    # Check all triggers (priority sorted)
    triggers = sorted(ACTIVATION_TRIGGERS, key=lambda t: t.priority)

    for trigger in triggers:
        # Check role filter
        if trigger.role_filter and agent_norm not in trigger.role_filter:
            continue

        # Check detection function
        try:
            if trigger.detection_fn(agent_norm, action_type, action_params, context):
                # Trigger matched — load skill
                skill_id = trigger.skill_id_template.replace("{role}", _map_agent_to_role(agent_norm))
                skill_content = _load_skill_content(skill_id)

                if not skill_content:
                    _log.warning(f"Skill file not found: {skill_id} (trigger {trigger.trigger_id})")
                    continue  # graceful degradation

                return SkillActivation(
                    skill_id=skill_id,
                    skill_content=skill_content,
                    trigger_rule=trigger.rule_name,
                    priority=trigger.priority,
                    role_filter=trigger.role_filter
                )
        except Exception as e:
            _log.error(f"Error checking trigger {trigger.trigger_id}: {e}")
            continue

    return None


def _map_agent_to_role(agent_name: str) -> str:
    """Map agent name to role directory name."""
    mapping = {
        "ceo": "ceo",
        "aiden": "ceo",
        "cto": "cto",
        "ethan": "cto",
        "eng_kernel": "eng-kernel",
        "eng_platform": "eng-platform",
        "eng_governance": "eng-governance",
        "eng_domains": "eng-domains",
        "cmo": "cmo",
        "sofia": "cmo",
        "cfo": "cfo",
        "marco": "cfo",
        "cso": "cso",
        "zara": "cso",
        "secretary": "secretary",
        "samantha": "secretary",
    }
    return mapping.get(agent_name.lower(), agent_name)


def _load_skill_content(skill_id: str) -> Optional[str]:
    """
    Load skill content from file.

    Args:
        skill_id: relative path like "knowledge/ceo/skills/article_11.md"

    Returns:
        Skill content (markdown) or None if file not found
    """
    # Resolve against ystar-company workspace
    workspace = Path(os.path.expanduser("~/.openclaw/workspace/ystar-company"))
    skill_path = workspace / skill_id

    if not skill_path.exists():
        return None

    try:
        return skill_path.read_text(encoding="utf-8")
    except Exception as e:
        _log.error(f"Error reading skill {skill_id}: {e}")
        return None

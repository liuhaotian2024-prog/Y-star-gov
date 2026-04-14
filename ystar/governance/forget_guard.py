"""
ystar.governance.forget_guard
==============================
ForgetGuard — Detects agents forgetting organizational principles after session restart.

Pattern: Agent applies correct rules in session N, but forgets them in session N+1.
Example: CEO directly assigns code task to engineer (bypassing CTO) after restart.

Mechanism:
- YAML rule file defines forbidden patterns (hierarchy violations, scope drift)
- Hook intercepts agent actions, matches against patterns
- Deny mode blocks action + logs CIEU entry
- dry_run_until field: grace period (24h default) where violations only warn, don't block
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class ForgetGuardRule:
    """Single ForgetGuard rule."""
    name: str
    pattern: str  # Regex or natural language pattern
    mode: str  # "deny" or "warn"
    message: str
    rationale: str
    dry_run_until: Optional[float]  # Unix timestamp; None = enforce immediately
    created_at: str


class ForgetGuard:
    """ForgetGuard engine — detects organizational amnesia."""

    def __init__(self, rules_path: Optional[Path] = None):
        if rules_path is None:
            rules_path = Path(__file__).parent / "forget_guard_rules.yaml"

        self.rules_path = rules_path
        self.rules: List[ForgetGuardRule] = []
        self._load_rules()

    def _load_rules(self):
        """Load rules from YAML file."""
        if not self.rules_path.exists():
            return

        with open(self.rules_path) as f:
            data = yaml.safe_load(f)

        for rule_data in data.get("rules", []):
            self.rules.append(ForgetGuardRule(
                name=rule_data["name"],
                pattern=rule_data["pattern"],
                mode=rule_data.get("mode", "warn"),
                message=rule_data["message"],
                rationale=rule_data["rationale"],
                dry_run_until=rule_data.get("dry_run_until"),
                created_at=rule_data.get("created_at", ""),
            ))

    def check(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check if action violates any ForgetGuard rule.

        Args:
            context: {
                "agent_id": str,
                "action_type": str,  # e.g., "task_assignment", "file_write", "bash_command"
                "action_payload": str,
                "target_agent": Optional[str],
            }

        Returns:
            None if OK, or violation dict if rule triggered:
            {
                "rule_name": str,
                "message": str,
                "mode": "deny" | "warn",
                "in_grace_period": bool,
            }
        """
        agent_id = context.get("agent_id", "")
        action_type = context.get("action_type", "")
        payload = context.get("action_payload", "")
        target_agent = context.get("target_agent", "")

        for rule in self.rules:
            if self._matches_pattern(rule.pattern, context):
                # Check dry_run grace period
                in_grace_period = False
                if rule.dry_run_until is not None:
                    current_time = time.time()
                    if current_time < rule.dry_run_until:
                        in_grace_period = True

                return {
                    "rule_name": rule.name,
                    "message": rule.message,
                    "rationale": rule.rationale,
                    "mode": "warn" if in_grace_period else rule.mode,
                    "in_grace_period": in_grace_period,
                }

        return None

    def _matches_pattern(self, pattern: str, context: Dict[str, Any]) -> bool:
        """
        Match pattern against context.

        Pattern can be:
        - Natural language description (simple keyword matching)
        - Regex (if starts with ^)
        """
        agent_id = context.get("agent_id", "")
        action_type = context.get("action_type", "")
        payload = str(context.get("action_payload", ""))
        target_agent = context.get("target_agent", "")

        # Build searchable text
        search_text = f"{agent_id} {action_type} {payload} {target_agent}".lower()

        # Regex pattern
        if pattern.startswith("^"):
            return bool(re.search(pattern, search_text, re.IGNORECASE))

        # Natural language keyword matching
        # Example pattern: "CEO assigns code|git task to eng-kernel without CTO"
        keywords = re.split(r"[|\s]+", pattern.lower())
        matches = sum(1 for kw in keywords if kw in search_text)
        threshold = len(keywords) * 0.6  # 60% keyword match required

        return matches >= threshold


# Singleton instance
_guard: Optional[ForgetGuard] = None


def get_guard() -> ForgetGuard:
    """Get singleton ForgetGuard instance."""
    global _guard
    if _guard is None:
        _guard = ForgetGuard()
    return _guard


def check_forget_violation(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convenience function for hook integration.

    Returns violation dict or None.
    """
    guard = get_guard()
    return guard.check(context)

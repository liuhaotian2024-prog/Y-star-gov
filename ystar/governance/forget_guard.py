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

Break-glass bypass (INC-2026-04-23 Item #9):
- .k9_rescue_mode flag file: if present, ALL ForgetGuard rules return None (full bypass)
- 3+ consecutive DENYs for same agent in 5 min: auto-downgrade deny → warn (lock-death prevention)
Both paths leave audit trail in violation dict metadata.

Deny history persistence (INC-2026-04-24 Item #9 live-fire fix):
- hook_wrapper.py runs as a fresh subprocess per invocation, so in-memory _deny_history
  was always empty.  Now persisted to /tmp/.ystar_fg_deny_history.json so consecutive
  DENYs accumulate across process boundaries within the 5-min window.
- Return dict includes hook_wrapper-compatible alias keys (action/rule_id/recipe/severity)
  alongside canonical keys (mode/rule_name/message/rationale).
- _matches_pattern now reads both canonical context keys AND hook-wire keys
  (tool/tool_input/file_path/command/content) so pattern matching works when called
  from hook_wrapper.py.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ── Break-glass constants (INC-2026-04-23 Item #9) ──────────────────────────
BREAK_GLASS_FLAG = ".k9_rescue_mode"
CONSECUTIVE_DENY_THRESHOLD = 3
CONSECUTIVE_DENY_WINDOW_SECS = 300  # 5 minutes
# Persistent deny-history file for cross-process accumulation
_DENY_HISTORY_PATH = "/tmp/.ystar_fg_deny_history.json"


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

    def __init__(self, rules_path: Optional[Path] = None,
                 rescue_mode_search_dirs: Optional[List[str]] = None,
                 deny_history_path: Optional[str] = None):
        if rules_path is None:
            rules_path = Path(__file__).parent / "forget_guard_rules.yaml"

        self.rules_path = rules_path
        self.rules: List[ForgetGuardRule] = []
        # Break-glass state: track consecutive denies per agent_id
        # Structure: {agent_id: [(timestamp, rule_name), ...]}
        self._deny_history: Dict[str, List[tuple]] = defaultdict(list)
        # Persistent deny history file path (cross-process accumulation)
        self._deny_history_path = deny_history_path or _DENY_HISTORY_PATH
        # Directories to search for .k9_rescue_mode flag
        self._rescue_mode_dirs = rescue_mode_search_dirs or [
            os.getcwd(),
            os.path.expanduser("~/.openclaw/workspace/ystar-company"),
        ]
        self._load_rules()
        self._load_deny_history()

    def _load_rules(self):
        """Load rules from YAML file(s).

        Supports two schemas:
        - v0.42 (Y-star-gov): name/pattern/mode/message/rationale
        - v1.1 (ystar-company): id/trigger.conditions/action/recipe/severity
        Also loads secondary company-side rules file if it exists.
        """
        import os

        if not self.rules_path.exists():
            return

        with open(self.rules_path) as f:
            data = yaml.safe_load(f) or {}

        # Load secondary rules file (company-side schema 1.1)
        secondary_path = "/Users/haotianliu/.openclaw/workspace/ystar-company/governance/forget_guard_rules.yaml"
        if os.path.exists(secondary_path):
            try:
                with open(secondary_path) as f2:
                    data2 = yaml.safe_load(f2) or {}
                # merge rules arrays
                existing_rules = data.get("rules", [])
                existing_rules.extend(data2.get("rules", []))
                data["rules"] = existing_rules
            except Exception:
                pass

        for rule_data in data.get("rules", []):
            # Schema detection
            if "name" in rule_data and "pattern" in rule_data:
                # v0.42 schema — coerce null pattern to empty string
                self.rules.append(ForgetGuardRule(
                    name=rule_data["name"],
                    pattern=rule_data["pattern"] or "",
                    mode=rule_data.get("mode", "warn"),
                    message=rule_data["message"],
                    rationale=rule_data.get("rationale", ""),
                    dry_run_until=rule_data.get("dry_run_until"),
                    created_at=rule_data.get("created_at", ""),
                ))
            elif "id" in rule_data:
                # schema 1.1 — map to v0.42 equivalent best-effort
                trigger = rule_data.get("trigger", {})
                conds = trigger.get("conditions", []) if isinstance(trigger, dict) else []
                # gather keywords across conditions
                keywords = []
                for c in conds:
                    if isinstance(c, dict):
                        kws = c.get("keywords", [])
                        if isinstance(kws, list):
                            keywords.extend(str(k) for k in kws)
                # pattern = keywords joined by | for keyword-OR matching
                pattern = "|".join(keywords) if keywords else ""
                self.rules.append(ForgetGuardRule(
                    name=rule_data["id"],
                    pattern=pattern,
                    mode=rule_data.get("action", "warn"),
                    message=rule_data.get("recipe", "")[:500] if rule_data.get("recipe") else "",
                    rationale=rule_data.get("description", ""),
                    dry_run_until=None,
                    created_at=rule_data.get("last_reviewed", ""),
                ))
            # else: silently skip malformed rule

    # ── Deny history persistence (cross-process) ─────────────────────────────

    def _load_deny_history(self) -> None:
        """Load deny history from persistent file, pruning expired entries."""
        try:
            if os.path.isfile(self._deny_history_path):
                with open(self._deny_history_path, "r") as f:
                    raw = json.load(f)
                now = time.time()
                cutoff = now - CONSECUTIVE_DENY_WINDOW_SECS
                for agent_id, entries in raw.items():
                    valid = [(ts, rn) for ts, rn in entries if ts >= cutoff]
                    if valid:
                        self._deny_history[agent_id] = valid
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            # Corrupted file — reset (fail-open)
            self._deny_history = defaultdict(list)

    def _save_deny_history(self) -> None:
        """Persist deny history to file for cross-process accumulation."""
        try:
            # Prune expired entries before saving
            now = time.time()
            cutoff = now - CONSECUTIVE_DENY_WINDOW_SECS
            serializable = {}
            for agent_id, entries in self._deny_history.items():
                valid = [(ts, rn) for ts, rn in entries if ts >= cutoff]
                if valid:
                    serializable[agent_id] = valid
            with open(self._deny_history_path, "w") as f:
                json.dump(serializable, f)
        except OSError:
            pass  # fail-open: inability to persist must not crash hook

    def _is_rescue_mode(self) -> bool:
        """Check if .k9_rescue_mode flag exists in any search directory."""
        for d in self._rescue_mode_dirs:
            if os.path.isfile(os.path.join(d, BREAK_GLASS_FLAG)):
                return True
        return False

    def _check_consecutive_deny_escalation(self, agent_id: str) -> bool:
        """Return True if agent has hit CONSECUTIVE_DENY_THRESHOLD denies in window.

        Also prunes expired entries from history.
        """
        if not agent_id:
            return False
        now = time.time()
        cutoff = now - CONSECUTIVE_DENY_WINDOW_SECS
        # Prune old entries
        self._deny_history[agent_id] = [
            (ts, rn) for ts, rn in self._deny_history[agent_id]
            if ts >= cutoff
        ]
        return len(self._deny_history[agent_id]) >= CONSECUTIVE_DENY_THRESHOLD

    def _record_deny(self, agent_id: str, rule_name: str) -> None:
        """Record a deny event for lock-death tracking."""
        if agent_id:
            self._deny_history[agent_id].append((time.time(), rule_name))

    def check(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check if action violates any ForgetGuard rule.

        Break-glass bypass (INC-2026-04-23 Item #9):
        - If .k9_rescue_mode flag exists: return None (full bypass)
        - If agent has 3+ consecutive DENYs in 5min: downgrade deny -> warn

        Args:
            context: {
                "agent_id": str,
                "action_type": str,
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
                "break_glass_downgrade": bool,
            }
        """
        agent_id = context.get("agent_id") or ""

        # Break-glass #1: .k9_rescue_mode flag file bypass
        if self._is_rescue_mode():
            return None

        # Check for consecutive deny escalation BEFORE evaluating rules
        deny_escalation_active = self._check_consecutive_deny_escalation(agent_id)

        for rule in self.rules:
            if self._matches_pattern(rule.pattern, context):
                # Check dry_run grace period
                in_grace_period = False
                if rule.dry_run_until is not None:
                    current_time = time.time()
                    if current_time < rule.dry_run_until:
                        in_grace_period = True

                effective_mode = rule.mode
                break_glass_downgrade = False

                if in_grace_period:
                    effective_mode = "warn"

                # Break-glass #2: consecutive deny -> downgrade to warn
                if effective_mode == "deny":
                    self._record_deny(agent_id, rule.name)
                    if deny_escalation_active:
                        effective_mode = "warn"
                        break_glass_downgrade = True

                return {
                    "rule_name": rule.name,
                    "message": rule.message,
                    "rationale": rule.rationale,
                    "mode": effective_mode,
                    "in_grace_period": in_grace_period,
                    "break_glass_downgrade": break_glass_downgrade,
                }

        return None

    def _matches_pattern(self, pattern: str, context: Dict[str, Any]) -> bool:
        """
        Match pattern against context.

        Pattern can be:
        - Natural language description (simple keyword matching)
        - Regex (if starts with ^)
        """
        # Guard: skip rules with null/empty pattern (schema rot defense)
        if pattern is None or pattern == "":
            return False

        agent_id = context.get("agent_id") or ""
        action_type = context.get("action_type") or ""
        payload = str(context.get("action_payload") or "")
        target_agent = context.get("target_agent") or ""

        # Build searchable text
        search_text = f"{agent_id} {action_type} {payload} {target_agent}".lower()

        # Regex pattern
        if pattern.startswith("^"):
            return bool(re.search(pattern, search_text, re.IGNORECASE))

        # Natural language keyword matching
        # Example pattern: "CEO assigns code|git task to eng-kernel without CTO"
        keywords = re.split(r"[|\s]+", pattern.lower())
        # Use word-boundary regex instead of substring to prevent
        # e.g. "p-1" matching inside "p-10" (Wave-1.5 fix)
        matches = sum(
            1 for kw in keywords
            if re.search(r'\b' + re.escape(kw) + r'\b', search_text)
        )
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

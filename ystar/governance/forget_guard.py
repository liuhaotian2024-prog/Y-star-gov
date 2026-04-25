"""
ystar.governance.forget_guard
==============================
ForgetGuard — Behavioral governance hook (rewritten 2026-04-25).

============================================================================
GOVERNANCE PHILOSOPHY: SPEECH IS NOT BEHAVIOR.
============================================================================

This module enforces ACTIONS, not WORDS.

Wrong design (v0.42, removed 2026-04-25):
    Used regex/keyword bag-of-words matching at 60% threshold against a
    concatenation of agent_id + action_type + payload + target_agent +
    file_path + command + content + tool_input. Agents writing role-
    description documents, completion summaries, governance discussions,
    or any prose that mentioned an action got DENIED as if they were
    *performing* the action.

    Concrete failures observed before purge:
      - CEO writing role architecture doc `cto.yaml` (describing how CTO
        manages engineers) got DENIED 3x by `ceo_direct_engineer_dispatch`
        because the document text contained "engineer" + "task" + "ceo".
      - CEO trying to checkpoint a session was blocked by
        `czl_termination_drift_reply_catch` because the reply contained
        "session close" — preventing the agent from EVER expressing
        "I want to stop", regardless of whether stopping was correct.
      - Receipts containing "完成" / "shipped" / "verified" tripped
        `coordinator_summary_rt_audit` and `missing_l_tag` simultaneously,
        making any completion report impossible to write.
      - 31 of 35 v0.42 rules had this structural defect.

The defect was not "rules badly tuned"; it was **conflating speech with
behavior**. An agent describing an action, debating an action, refusing an
action, or quoting someone else's action are NOT the action itself. A
runtime DENY hook that pattern-matches free text cannot distinguish these
contexts. The category of "rule expressible only as text-keywords" is
exactly the category of rule that DOES NOT BELONG in a runtime enforcement
hook.

============================================================================
RIGHT DESIGN (v0.5, this file): STRUCTURED CONDITIONS ONLY.
============================================================================

A rule lives here only if it can be expressed as a check over STRUCTURED
EVENT FIELDS:
    - tool_name (e.g., "bash_command", "file_write")
    - agent_role (e.g., "ceo", "eng_kernel", "human")
    - parsed command tokens (first token, subcommand)
    - typed event metadata (sub_agent_return.claimed_tool_uses vs
      actual_tool_uses_from_metadata)
    - file path scope membership

If a governance concern requires reading payload TEXT to decide whether
to fire — that concern belongs in:
    (a) post-hoc semantic audit (run later, advisory only), OR
    (b) a typed validator on STRUCTURED data (e.g., receipt schema
        validator, not text grep), OR
    (c) human review, NOT runtime enforcement.

It does NOT belong here. This is enforced structurally:
  - The rule loader REJECTS any rule containing a `pattern:` field.
  - The rule loader REJECTS any rule without `type: structured`.
  - There is NO `_matches_pattern` function in this module. Removed
    physically, not deprecated, so future contributors cannot reach for it.
  - Adding a new rule requires writing a `conditions:` dict referencing
    typed fields.

============================================================================
WHY THIS GUARD IS STRUCTURAL, NOT ADVISORY.
============================================================================

Past observation: agents (and human contributors) under cognitive pressure
revert to "ban the word" thinking — they cannot keep "speech ≠ behavior"
in working memory while debugging a real failure. The keyword-blacklist
pattern grows back after any partial cleanup unless the *engine itself*
refuses to load such rules.

So this module makes adding a keyword-matching rule mechanically impossible:
the YAML loader raises ForgetGuardSchemaError on startup if any rule has
a `pattern:` field or lacks `type: structured`. The system will not start
with such a rule present. This is intentional: it is cheaper to break
startup once than to debug another 8-hour false-positive cascade.

============================================================================
"""
from __future__ import annotations

import json
import os
import shlex
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml


# ── Break-glass support (kept from v0.42, retained for edge cases) ─────────
# Rationale for keeping: even with structured-only rules, a real behavioral
# DENY (e.g., sub-agent attempting git push) might fire repeatedly under a
# legitimate retry storm. Keeping the auto-downgrade as a safety valve is
# cheap and orthogonal to the speech-vs-behavior fix. If it never fires
# again because all rules are well-formed, fine — it costs nothing.
BREAK_GLASS_FLAG = ".k9_rescue_mode"
CONSECUTIVE_DENY_THRESHOLD = 3
CONSECUTIVE_DENY_WINDOW_SECS = 300  # 5 minutes
_DENY_HISTORY_PATH = "/tmp/.ystar_fg_deny_history.json"


class ForgetGuardSchemaError(ValueError):
    """Raised at startup when a rule violates the v0.5 structured-only schema.

    This is a HARD error. The system refuses to start rather than silently
    accept a malformed rule. Reason: silent acceptance is what allowed the
    keyword-blacklist defect to accumulate to 38 rules over weeks.
    """


@dataclass
class ForgetGuardRule:
    """A v0.5 structured ForgetGuard rule.

    No `pattern` field. Conditions only. If you find yourself wanting to add
    a `pattern` field, see module docstring — that concern belongs elsewhere.
    """
    name: str
    conditions: Dict[str, Any]
    mode: str  # "deny" | "warn" | "audit"
    message: str
    rationale: str = ""
    created_at: str = ""


class ForgetGuard:
    """Behavioral governance engine — structured conditions only."""

    def __init__(
        self,
        rules_path: Optional[Path] = None,
        rescue_mode_search_dirs: Optional[List[str]] = None,
        deny_history_path: Optional[str] = None,
    ):
        if rules_path is None:
            rules_path = Path(__file__).parent / "forget_guard_rules.yaml"
        self.rules_path = Path(rules_path)
        self.rules: List[ForgetGuardRule] = []
        self._deny_history: Dict[str, List[tuple]] = defaultdict(list)
        self._deny_history_path = deny_history_path or _DENY_HISTORY_PATH
        self._rescue_mode_dirs = rescue_mode_search_dirs or [
            os.getcwd(),
            os.path.expanduser("~/.openclaw/workspace/ystar-company"),
        ]
        self._load_rules()
        self._load_deny_history()

    # ── Rule loading with schema enforcement ──────────────────────────────

    def _load_rules(self) -> None:
        """Load rules from YAML. Raises ForgetGuardSchemaError on any v0.42-style rule.

        This is intentionally hard-fail. The previous behavior of silently
        coercing/skipping malformed rules is what allowed the keyword
        blacklist to accumulate. Hard failure forces contributors to confront
        the schema requirement at the moment they write a bad rule.
        """
        if not self.rules_path.exists():
            return
        with open(self.rules_path) as f:
            data = yaml.safe_load(f) or {}

        rules_list = data.get("rules") or []
        errors: List[str] = []

        for i, rule_data in enumerate(rules_list):
            name = rule_data.get("name") or f"<unnamed#{i}>"

            # Hard schema gate #1: no `pattern` field allowed
            if "pattern" in rule_data:
                errors.append(
                    f"Rule '{name}': contains forbidden `pattern` field. "
                    f"Keyword/regex matching against payload text is not allowed in v0.5 — "
                    f"it conflates speech with behavior. Express the intent via `conditions:` "
                    f"over typed event fields, or move the concern to post-hoc audit."
                )
                continue

            # Hard schema gate #2: must declare type: structured
            if rule_data.get("type") != "structured":
                errors.append(
                    f"Rule '{name}': missing `type: structured` declaration. "
                    f"All v0.5 rules must explicitly declare structured-condition type."
                )
                continue

            # Hard schema gate #3: must have non-empty conditions dict
            conditions = rule_data.get("conditions")
            if not isinstance(conditions, dict) or not conditions:
                errors.append(
                    f"Rule '{name}': missing or empty `conditions:` dict."
                )
                continue

            self.rules.append(ForgetGuardRule(
                name=name,
                conditions=conditions,
                mode=rule_data.get("mode", "warn"),
                message=rule_data.get("message", ""),
                rationale=rule_data.get("rationale", ""),
                created_at=rule_data.get("created_at", ""),
            ))

        if errors:
            joined = "\n  - ".join(errors)
            raise ForgetGuardSchemaError(
                f"ForgetGuard refuses to start: {len(errors)} rule(s) violate v0.5 "
                f"structured-only schema. See module docstring for rationale.\n"
                f"  - {joined}\n\n"
                f"Fix: rewrite each offending rule using `type: structured` + "
                f"`conditions:` over typed event fields. Do NOT use `pattern:`."
            )

    # ── Deny history (cross-process accumulation, retained from v0.42) ────

    def _load_deny_history(self) -> None:
        """Load deny history from persistent file, pruning expired entries."""
        try:
            if os.path.isfile(self._deny_history_path):
                with open(self._deny_history_path) as f:
                    raw = json.load(f)
                cutoff = time.time() - CONSECUTIVE_DENY_WINDOW_SECS
                self._deny_history = defaultdict(list, {
                    k: [(ts, rn) for ts, rn in v if ts >= cutoff]
                    for k, v in raw.items()
                })
        except (OSError, json.JSONDecodeError):
            pass  # corrupted file → start fresh

    def _save_deny_history(self) -> None:
        try:
            with open(self._deny_history_path, "w") as f:
                json.dump({k: list(v) for k, v in self._deny_history.items()}, f)
        except OSError:
            pass

    def _check_consecutive_deny_escalation(self, agent_id: str) -> bool:
        if not agent_id:
            return False
        self._load_deny_history()  # pick up other process invocations
        cutoff = time.time() - CONSECUTIVE_DENY_WINDOW_SECS
        self._deny_history[agent_id] = [
            (ts, rn) for ts, rn in self._deny_history[agent_id] if ts >= cutoff
        ]
        return len(self._deny_history[agent_id]) >= CONSECUTIVE_DENY_THRESHOLD

    def _record_deny(self, agent_id: str, rule_name: str) -> None:
        if agent_id:
            self._deny_history[agent_id].append((time.time(), rule_name))
            self._save_deny_history()

    def _is_in_rescue_mode(self) -> bool:
        for d in self._rescue_mode_dirs:
            if os.path.isfile(os.path.join(d, BREAK_GLASS_FLAG)):
                return True
        return False

    def _normalize_context_aliases(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize hook-wire field names to canonical condition field names.

        Caller may pass either the canonical name or a wire alias; we always
        provide both in the returned context so rules can reference whichever.

        Aliases:
            tool          ↔ tool_name
            active_agent  → agent_id (if agent_id missing)
        """
        ctx = dict(context)  # don't mutate caller's dict
        if "tool_name" not in ctx and "tool" in ctx:
            ctx["tool_name"] = ctx["tool"]
        if "tool" not in ctx and "tool_name" in ctx:
            ctx["tool"] = ctx["tool_name"]
        if not ctx.get("agent_id") and ctx.get("active_agent"):
            ctx["agent_id"] = ctx["active_agent"]
        # If hook passed `tool_input` as dict and `command`/`path` not at top,
        # surface them so rules referencing `command` / `path` work.
        ti = ctx.get("tool_input")
        if isinstance(ti, dict):
            if "command" not in ctx and "command" in ti:
                ctx["command"] = ti["command"]
            if "path" not in ctx and "file_path" in ti:
                ctx["path"] = ti["file_path"]
            if "path" not in ctx and "path" in ti:
                ctx["path"] = ti["path"]
        # `file_path` (hook wire) → `path` (canonical)
        if "path" not in ctx and "file_path" in ctx:
            ctx["path"] = ctx["file_path"]
        return ctx

    # ── Public API ────────────────────────────────────────────────────────

    def check(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Check whether the action described by `context` violates any rule.

        `context` is a dict of STRUCTURED event fields. Common keys:
            - agent_id, agent_role, tool_name, event_type
            - command (for bash_command), path (for file_write)
            - claimed_tool_uses, actual_tool_uses_from_metadata

        Free-form text payloads (markdown bodies, reply text, commit message
        bodies) are NOT inspected here. If you need to inspect text, use a
        typed validator (e.g., receipt schema validator) and pass its
        boolean/numeric output as a structured field.

        Returns None if OK, else a violation dict with both canonical keys
        (rule_name/message/mode/rationale) and hook-wire alias keys
        (action/rule_id/recipe/severity) for hook_wrapper compatibility.
        """
        if self._is_in_rescue_mode():
            return None

        # Field-name aliases for hook_wrapper compatibility.
        # hook_wrapper passes `tool` and `active_agent`; rules reference
        # `tool_name` and `agent_id`. Normalize before evaluation so rule
        # authors don't need to know the wire format.
        context = self._normalize_context_aliases(context)

        agent_id = context.get("agent_id") or ""

        for rule in self.rules:
            if self._evaluate_conditions(rule.conditions, context):
                effective_mode = rule.mode
                break_glass_downgrade = False

                if rule.mode == "deny":
                    self._record_deny(agent_id, rule.name)
                    if self._check_consecutive_deny_escalation(agent_id):
                        effective_mode = "warn"
                        break_glass_downgrade = True

                return {
                    # Canonical
                    "rule_name": rule.name,
                    "message": self._format_message(rule.message, context),
                    "rationale": rule.rationale,
                    "mode": effective_mode,
                    "break_glass_downgrade": break_glass_downgrade,
                    # Hook-wire aliases (hook_wrapper.py reads these)
                    "action": effective_mode,
                    "rule_id": rule.name,
                    "recipe": rule.message,
                    "severity": "high" if effective_mode == "deny" else "low",
                }
        return None

    def dry_run(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return ALL rules that WOULD trigger for this context.

        Lets agents check before acting: "would this action violate any rule?"
        This interface was missing in v0.42 — agents could only discover rule
        contents by triggering DENY and reading the message, which forced
        trial-and-error rewriting of payloads (a major false-positive amplifier).
        """
        context = self._normalize_context_aliases(context)
        return [
            {
                "rule_name": r.name,
                "mode": r.mode,
                "message": self._format_message(r.message, context),
                "rationale": r.rationale,
            }
            for r in self.rules
            if self._evaluate_conditions(r.conditions, context)
        ]

    # ── Structured condition evaluation ───────────────────────────────────

    def _evaluate_conditions(self, conditions: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """All conditions must hold (AND)."""
        return all(self._check_one_condition(k, v, context) for k, v in conditions.items())

    def _check_one_condition(self, key: str, expected: Any, context: Dict[str, Any]) -> bool:
        """Evaluate one structured condition.

        Order matters: NAMED handlers run BEFORE generic suffix handlers,
        because some named keys end in `_in` (e.g. command_parsed_subcommand_in).

        Supported keys:
          - command_parsed_first_token: x        — first shell token == x
          - command_parsed_subcommand_in: [...]  — second shell token in list
          - has_field: name                      — context[name] non-empty
          - mismatch_metric: <expr>              — eval'd expr on context
          - check: <named_check>                 — call registered fn
          - <field>_in: [...]                    — context[field] in list
          - <field>_under_any: [...]             — context[field] startswith any prefix
          - <field>: value                       — context[field] == value
        """
        # ── Named handlers (must run first) ──
        if key == "command_parsed_first_token":
            cmd = context.get("command") or ""
            try:
                tokens = shlex.split(cmd)
            except ValueError:
                tokens = cmd.split()
            return bool(tokens) and tokens[0] == expected

        if key == "command_parsed_subcommand_in":
            cmd = context.get("command") or ""
            try:
                tokens = shlex.split(cmd)
            except ValueError:
                tokens = cmd.split()
            return len(tokens) >= 2 and tokens[1] in expected

        if key == "has_field":
            v = context.get(expected)
            return v is not None and v != ""

        if key == "mismatch_metric":
            try:
                return bool(eval(
                    expected,
                    {"__builtins__": {}, "abs": abs, "min": min, "max": max},
                    dict(context),
                ))
            except Exception:
                return False

        if key == "check":
            fn = _NAMED_CHECKS.get(expected)
            return bool(fn(context)) if fn else False

        if key in ("grace_window_minutes",):
            return True  # advisory metadata

        # ── Generic suffix handlers ──
        if key.endswith("_under_any"):
            field = key[: -len("_under_any")]
            actual = context.get(field) or ""
            return any(actual.startswith(p) for p in expected)

        if key.endswith("_in"):
            field = key[:-3]
            actual = context.get(field)
            return actual in expected if actual is not None else False

        # Default: equality on the named field
        return context.get(key) == expected

    def _format_message(self, template: str, context: Dict[str, Any]) -> str:
        """Format {placeholders} in message safely."""
        try:
            claimed = context.get("claimed_tool_uses")
            actual = context.get("actual_tool_uses_from_metadata")
            return template.format(
                **context,
                claimed=claimed if claimed is not None else "?",
                actual=actual if actual is not None else "?",
                diff=abs((claimed or 0) - (actual or 0)),
            )
        except (KeyError, ValueError, IndexError):
            return template


# ── Named checks registry (extension point for typed behavioral checks) ───
# NOT for text-matching. If you find yourself adding a function here that
# does string.search() or re.match() on payload text, stop — that's the
# v0.42 anti-pattern. Use a typed validator and pass its result as a field.
_NAMED_CHECKS: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    "file_path_not_in_archive_index": lambda ctx: False,  # stub
}


# ── Module-level singleton + entry points ─────────────────────────────────

_guard: Optional[ForgetGuard] = None


def get_guard() -> ForgetGuard:
    global _guard
    if _guard is None:
        _guard = ForgetGuard()
    return _guard


def check_forget_violation(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Hook integration entry point. Backward-compatible signature."""
    return get_guard().check(context)


def dry_run_check(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Agent self-query entry point. Returns rules that would trigger."""
    return get_guard().dry_run(context)


def reload_rules() -> None:
    """Force reload of rules from disk (used after rule file edits)."""
    global _guard
    _guard = None

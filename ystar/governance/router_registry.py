# Layer: Foundation
"""
ystar.governance.router_registry  --  Enforce-as-Router Registry  v1.0.0
=========================================================================

Central registry for enforce-as-router rules. Each rule pairs a **detector**
(callable that decides whether a payload matches a routing condition) with an
**executor** (callable that carries out the routed action).

Architecture (Board 2026-04-18 -- enforce_as_router_migration_plan):

    ┌──────────────────────────────────────────────────────────┐
    │ enforce hook receives tool call payload                  │
    │        ↓                                                 │
    │ RouterRegistry.find_matching_rules(payload)              │
    │        ↓ (sorted by priority, highest first)             │
    │ For each matching rule:                                  │
    │   executor(payload) → RouterResult                       │
    │   If result.decision != ALLOW: return early              │
    │        ↓                                                 │
    │ No match → fall through to normal enforce() path         │
    └──────────────────────────────────────────────────────────┘

This is the API skeleton for Phase 2-b/c/d migrations. When registering
a new router rule:

    from ystar.governance.router_registry import RouterRegistry, RouterRule

    registry = RouterRegistry()

    rule = RouterRule(
        rule_id="session_boot_auto",
        detector=lambda payload: payload.get("event_type") == "session_start",
        executor=lambda payload: RouterResult(
            decision="invoke",
            script="/path/to/session_boot.py",
            args={"agent_id": payload.get("agent_id")},
        ),
        priority=100,
        metadata={"phase": "2-b", "migrated_from": "governance_boot.sh"},
    )
    registry.register_rule(rule)

    # At enforce time:
    matches = registry.find_matching_rules(payload)
    for rule in matches:
        result = registry.execute_rule(rule, payload)
        if result.decision != "allow":
            return result

Design decisions:
  - Detector receives the full hook payload dict (not parsed event)
  - Executor receives the same payload, returns RouterResult
  - Priority is int: higher = evaluated first (default 0)
  - Rule IDs must be unique (register_rule raises on duplicate)
  - max_depth guard prevents INVOKE chains from looping (default 5)
  - Thread-safe via simple dict operations (GIL-protected for CPython)

Downstream dependencies (Phase 2-b/c/d):
  - Session Boot workflow → register detector for SESSION_START
  - Dispatch workflow → register detector for Agent tool calls
  - Protocol enforcement → register detectors for governance protocol rules
"""
from __future__ import annotations

import importlib.util
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

_log = logging.getLogger("ystar.router")


# ═══════════════════════════════════════════════════════════════════════
# 1a. IngressRequest — Normalized payload from any adapter
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class IngressRequest:
    """
    Normalized inbound request from any adapter (Claude Code / MCP / CLI).

    Every adapter translates its platform-specific payload into this uniform
    format before forwarding to Layer 3 (RouterRegistry).  This eliminates
    stringly-typed dict-sniffing in detectors/executors.

    Fields:
        tool_name:  The tool being invoked (e.g. "Bash", "Write", "Read").
        tool_input: The tool's input parameters as a dict.
        agent_id:   The agent identity performing the call.
        session_id: The current session identifier.
        source:     Origin adapter: "claude_code", "mcp", or "cli".
    """
    tool_name:  str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    agent_id:   str = ""
    session_id: str = ""
    source:     str = ""  # "claude_code" | "mcp" | "cli"

    @classmethod
    def from_claude_code(cls, payload: Dict[str, Any]) -> "IngressRequest":
        """Normalize a Claude Code hook payload into IngressRequest."""
        tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
        tool_input = payload.get("tool_input", {}) or payload.get("input", {})
        agent_id = (
            payload.get("agent_id", "")
            or payload.get("agentId", "")
            or tool_input.get("agent_id", "")
        )
        session_id = payload.get("session_id", "") or payload.get("sessionId", "")
        return cls(
            tool_name=tool_name,
            tool_input=tool_input if isinstance(tool_input, dict) else {},
            agent_id=agent_id,
            session_id=session_id,
            source="claude_code",
        )

    @classmethod
    def from_mcp(cls, mcp_call: Dict[str, Any]) -> "IngressRequest":
        """Normalize an MCP JSON-RPC tool call into IngressRequest."""
        params = mcp_call.get("params", {})
        tool_name = mcp_call.get("method", "") or params.get("name", "")
        tool_input = params.get("arguments", {}) or params.get("input", {})
        meta = mcp_call.get("_meta", {}) or params.get("_meta", {})
        agent_id = meta.get("agent_id", "")
        session_id = meta.get("session_id", "") or meta.get("sessionId", "")
        return cls(
            tool_name=tool_name,
            tool_input=tool_input if isinstance(tool_input, dict) else {},
            agent_id=agent_id,
            session_id=session_id,
            source="mcp",
        )

    @classmethod
    def from_cli(cls, args: Dict[str, Any]) -> "IngressRequest":
        """Normalize CLI arguments into IngressRequest."""
        tool_name = args.get("command", "") or args.get("tool", "")
        raw_input = args.get("args", {}) or args.get("input", {})
        agent_id = args.get("agent_id", "") or args.get("agent", "")
        session_id = args.get("session_id", "") or args.get("session", "")
        return cls(
            tool_name=tool_name,
            tool_input=raw_input if isinstance(raw_input, dict) else {},
            agent_id=agent_id,
            session_id=session_id,
            source="cli",
        )

    def to_payload(self) -> Dict[str, Any]:
        """Convert back to a plain dict for legacy APIs that expect payload dicts."""
        return {
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "source": self.source,
        }


# ═══════════════════════════════════════════════════════════════════════
# 1b. Data Models
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class RouterResult:
    """
    Result returned by a router rule executor.

    decision: One of the EnforceDecision values as string:
        "allow"     - proceed normally (no routing action taken)
        "deny"      - block the action
        "redirect"  - return fix instructions + allow retry
        "invoke"    - execute a script/function automatically
        "inject"    - append context to the allow message
        "auto_post" - auto-post a task card to whiteboard

    message: Human-readable description of what the router did.
    script: For INVOKE decisions, the path/name of the invoked script.
    args: For INVOKE decisions, the arguments passed to the script.
    injected_context: For INJECT decisions, the context markdown to append.
    task_card: For AUTO_POST decisions, the task card dict to post.
    """
    decision:         str = "allow"
    message:          str = ""
    script:           str = ""
    args:             Dict[str, Any] = field(default_factory=dict)
    injected_context: str = ""
    task_card:        Optional[Dict[str, Any]] = None
    rule_id:          str = ""  # Which rule produced this result
    execution_ms:     float = 0.0  # How long the executor took


@dataclass
class RouterRule:
    """
    A single routing rule: detector + executor + priority + metadata.

    detector: callable(payload: dict) -> bool
        Returns True if this rule applies to the given payload.
        Must be fast (< 1ms) -- heavy logic goes in the executor.
        Must be pure (no side effects).

    executor: callable(payload: dict) -> RouterResult
        Executes the routing action when the detector matches.
        May have side effects (write files, call APIs, etc.).

    priority: int
        Higher values are evaluated first. Default 0.
        Convention:
          1000+ : constitutional rules (identity, break-glass)
          100-999: workflow rules (session boot, dispatch)
          1-99  : advisory rules (SOP injection, knowledge surface)
          0     : default / catch-all

    metadata: dict
        Free-form metadata for introspection/debugging.
        Recommended keys: phase, migrated_from, description, author.
    """
    rule_id:   str
    detector:  Callable[[Dict[str, Any]], bool]
    executor:  Callable[[Dict[str, Any]], RouterResult]
    priority:  int = 0
    metadata:  Dict[str, Any] = field(default_factory=dict)
    enabled:   bool = True
    created_at: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════════
# 2. Router Registry
# ═══════════════════════════════════════════════════════════════════════

class RouterRegistry:
    """
    Central registry for router rules.

    Thread-safe for CPython (GIL-protected dict operations).
    For multi-process deployments, each process maintains its own registry.

    Usage:
        registry = RouterRegistry()
        registry.register_rule(rule)
        matches = registry.find_matching_rules(payload)
        for rule in matches:
            result = registry.execute_rule(rule, payload)
    """

    # Guard against INVOKE chain loops (Board risk #2 in migration plan)
    MAX_CHAIN_DEPTH = 5

    def __init__(self) -> None:
        self._rules: Dict[str, RouterRule] = {}
        self._execution_depth: int = 0  # Current chain depth

    # ── Registration ─────────────────────────────────────────────────

    def register_rule(self, rule: RouterRule) -> None:
        """
        Register a router rule.

        Raises ValueError if rule_id already exists (prevents silent overwrite).
        Use update_rule() for intentional replacement.
        """
        if rule.rule_id in self._rules:
            raise ValueError(
                f"RouterRule '{rule.rule_id}' already registered. "
                f"Use update_rule() to replace, or unregister_rule() first."
            )
        self._rules[rule.rule_id] = rule
        _log.info("Registered router rule: %s (priority=%d)", rule.rule_id, rule.priority)

    def update_rule(self, rule: RouterRule) -> None:
        """Replace an existing rule (or register if new)."""
        self._rules[rule.rule_id] = rule
        _log.info("Updated router rule: %s (priority=%d)", rule.rule_id, rule.priority)

    def unregister_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if removed, False if not found."""
        removed = self._rules.pop(rule_id, None)
        if removed:
            _log.info("Unregistered router rule: %s", rule_id)
        return removed is not None

    def unregister_all(self) -> int:
        """Remove all registered rules. Returns count of rules removed."""
        count = len(self._rules)
        self._rules.clear()
        self._execution_depth = 0
        _log.info("Unregistered all %d router rules", count)
        return count

    def load_rules_dir(self, path: str) -> int:
        """
        Load router rules from all .py files in *path*.

        Each .py file (excluding ``_``-prefixed) is imported as a module.
        Any module-level ``RULES`` list is iterated; each ``RouterRule``
        instance is registered.  Already-registered rule_ids are silently
        skipped (idempotent).

        Returns:
            Number of rules successfully registered.
        """
        if not os.path.isdir(path):
            _log.warning("load_rules_dir: %s is not a directory, skipping", path)
            return 0

        loaded = 0
        for fname in sorted(os.listdir(path)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            fpath = os.path.join(path, fname)
            try:
                spec = importlib.util.spec_from_file_location(
                    f"ystar_rules.{fname[:-3]}", fpath,
                )
                if spec is None or spec.loader is None:
                    _log.warning("load_rules_dir: could not create spec for %s", fpath)
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                rules = getattr(mod, "RULES", [])
                for rule in rules:
                    if isinstance(rule, RouterRule):
                        try:
                            self.register_rule(rule)
                            loaded += 1
                        except ValueError:
                            pass  # Already registered — idempotent
                _log.info("load_rules_dir: loaded %d rules from %s", len(rules), fname)
            except Exception as e:
                _log.warning("load_rules_dir: failed to load %s: %s", fname, e)
        return loaded

    def get_rule(self, rule_id: str) -> Optional[RouterRule]:
        """Get a rule by ID, or None if not found."""
        return self._rules.get(rule_id)

    @property
    def rule_count(self) -> int:
        """Number of registered rules."""
        return len(self._rules)

    def all_rules(self) -> List[RouterRule]:
        """Return all rules sorted by priority (highest first)."""
        return sorted(
            self._rules.values(),
            key=lambda r: r.priority,
            reverse=True,
        )

    # ── Matching ─────────────────────────────────────────────────────

    def find_matching_rules(
        self,
        payload: Dict[str, Any],
    ) -> List[RouterRule]:
        """
        Find all enabled rules whose detector returns True for this payload.

        Returns rules sorted by priority (highest first).
        Detector errors are caught and logged (rule is skipped, not matched).
        """
        matches: List[RouterRule] = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            try:
                if rule.detector(payload):
                    matches.append(rule)
            except Exception as e:
                _log.warning(
                    "Router rule '%s' detector raised %s: %s — skipping",
                    rule.rule_id, type(e).__name__, e,
                )
        # Sort by priority descending
        matches.sort(key=lambda r: r.priority, reverse=True)
        return matches

    # ── Execution ────────────────────────────────────────────────────

    def execute_rule(
        self,
        rule: RouterRule,
        payload: Dict[str, Any],
    ) -> RouterResult:
        """
        Execute a single rule's executor with the given payload.

        - Enforces MAX_CHAIN_DEPTH to prevent INVOKE loops.
        - Catches executor exceptions and returns an error RouterResult.
        - Measures execution time.
        """
        if self._execution_depth >= self.MAX_CHAIN_DEPTH:
            _log.error(
                "Router chain depth exceeded (%d >= %d) — aborting rule '%s'",
                self._execution_depth, self.MAX_CHAIN_DEPTH, rule.rule_id,
            )
            return RouterResult(
                decision="deny",
                message=f"Router chain depth exceeded (max={self.MAX_CHAIN_DEPTH})",
                rule_id=rule.rule_id,
            )

        self._execution_depth += 1
        start = time.monotonic()
        try:
            result = rule.executor(payload)
            result.rule_id = rule.rule_id
            result.execution_ms = (time.monotonic() - start) * 1000
            return result
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            _log.error(
                "Router rule '%s' executor raised %s: %s (%.1fms)",
                rule.rule_id, type(e).__name__, e, elapsed,
            )
            return RouterResult(
                decision="deny",
                message=f"Router executor error: {e}",
                rule_id=rule.rule_id,
                execution_ms=elapsed,
            )
        finally:
            self._execution_depth -= 1

    def execute_rules(
        self,
        payload: Dict[str, Any],
        rules: Optional[Sequence[RouterRule]] = None,
        stop_on_non_allow: bool = True,
    ) -> List[RouterResult]:
        """
        Execute multiple rules in priority order.

        If stop_on_non_allow=True (default), stops at the first rule
        that returns a non-ALLOW decision (DENY, REDIRECT, INVOKE, etc.).

        Returns list of RouterResults (one per executed rule).
        """
        if rules is None:
            rules = self.find_matching_rules(payload)

        results: List[RouterResult] = []
        for rule in rules:
            result = self.execute_rule(rule, payload)
            results.append(result)
            if stop_on_non_allow and result.decision != "allow":
                break
        return results

    # ── Introspection ────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return registry statistics for diagnostics (ystar doctor)."""
        enabled = sum(1 for r in self._rules.values() if r.enabled)
        disabled = len(self._rules) - enabled
        priorities = {}
        for r in self._rules.values():
            bucket = "constitutional" if r.priority >= 1000 else \
                     "workflow" if r.priority >= 100 else \
                     "advisory" if r.priority >= 1 else "default"
            priorities[bucket] = priorities.get(bucket, 0) + 1
        return {
            "total_rules": len(self._rules),
            "enabled": enabled,
            "disabled": disabled,
            "priority_buckets": priorities,
            "max_chain_depth": self.MAX_CHAIN_DEPTH,
        }

    def describe_rules(self) -> List[Dict[str, Any]]:
        """Return human-readable summary of all rules (for debug/docs)."""
        return [
            {
                "rule_id": r.rule_id,
                "priority": r.priority,
                "enabled": r.enabled,
                "metadata": r.metadata,
                "created_at": r.created_at,
            }
            for r in self.all_rules()
        ]


# ═══════════════════════════════════════════════════════════════════════
# 3. Module-level singleton (optional convenience)
# ═══════════════════════════════════════════════════════════════════════

# Applications can create their own RouterRegistry instances.
# This singleton is provided for simple single-registry deployments.
_default_registry: Optional[RouterRegistry] = None


def _governance_rules_dir() -> str:
    """Return the path to the governance/rules/ directory (package-relative)."""
    return os.path.join(os.path.dirname(__file__), "rules")


def load_governance_rules(registry: Optional[RouterRegistry] = None) -> int:
    """
    Load governance-layer router rules from ystar/governance/rules/.

    If *registry* is None, loads into the default singleton registry.
    Returns the number of rules successfully registered.

    This function is idempotent: already-registered rule IDs are skipped.
    """
    reg = registry if registry is not None else get_default_registry()
    rules_dir = _governance_rules_dir()
    return reg.load_rules_dir(rules_dir)


def get_default_registry() -> RouterRegistry:
    """Get or create the default singleton RouterRegistry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = RouterRegistry()
        # Auto-load governance rules on first creation
        _default_registry.load_rules_dir(_governance_rules_dir())
    return _default_registry


def reset_default_registry() -> None:
    """Reset the default registry (for testing)."""
    global _default_registry
    _default_registry = None


__all__ = [
    "IngressRequest",
    "RouterResult",
    "RouterRule",
    "RouterRegistry",
    "get_default_registry",
    "load_governance_rules",
    "reset_default_registry",
]

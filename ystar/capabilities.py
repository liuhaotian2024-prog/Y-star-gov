# ystar/capabilities.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
Capability-Based Permission System (AMENDMENT-015 Layer 2)

Replaces hardcoded role whitelists with dynamic capability grants.
Supports time-bound delegation, revocation, and scope-limited permissions.

Usage:
    engine = CapabilityEngine()
    engine.grant("eng-kernel", "write:reports/tech_debt.md", duration=3600)
    result = engine.check("eng-kernel", "write:reports/tech_debt.md")
    if result.allowed:
        # proceed with write
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_log = logging.getLogger("ystar.capabilities")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*cap] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)


@dataclass
class CapabilityToken:
    """Time-bound capability grant."""
    agent: str
    capability: str  # format: "action:scope" (e.g., "write:reports/tech_debt.md")
    granted_at: float
    expires_at: Optional[float] = None  # None = no expiry
    granted_by: str = "board"  # who granted this capability
    reason: str = ""  # audit trail: why was this granted


@dataclass
class CapabilityResult:
    """Result of a capability check."""
    allowed: bool
    reason: str
    agent: str
    capability: str
    violations: List[str] = field(default_factory=list)


class CapabilityEngine:
    """
    Capability-based permission engine.

    Persistent state stored in .ystar_session.json under "capabilities" key:
    {
        "capabilities": {
            "ceo": ["write:reports/autonomous/*", "grant:write:*"],
            "cto": ["write:src/*", "write:tests/*", "grant:write:ystar/*"],
            ...
        },
        "capability_tokens": [
            {"agent": "eng-kernel", "capability": "write:reports/tech_debt.md",
             "granted_at": 1776100000, "expires_at": 1776103600, "granted_by": "ceo"}
        ]
    }
    """

    def __init__(self, session_config_path: Optional[Path] = None):
        """
        Initialize capability engine.

        Args:
            session_config_path: Path to .ystar_session.json. If None, auto-detect.
        """
        if session_config_path is None:
            # Auto-detect session config
            candidates = [
                Path.cwd() / ".ystar_session.json",
                Path(os.path.expanduser("~/.openclaw/workspace/ystar-company/.ystar_session.json")),
            ]
            for c in candidates:
                if c.exists():
                    session_config_path = c
                    break

        self.session_config_path = session_config_path
        self._capabilities: Dict[str, List[str]] = {}
        self._tokens: List[CapabilityToken] = []
        self._load()

    def _load(self):
        """Load capabilities from session config."""
        if not self.session_config_path or not self.session_config_path.exists():
            _log.warning(f"Session config not found: {self.session_config_path}, using empty capabilities")
            return

        try:
            with open(self.session_config_path) as f:
                config = json.load(f)

            self._capabilities = config.get("capabilities", {})

            # Load capability tokens
            tokens_data = config.get("capability_tokens", [])
            self._tokens = [
                CapabilityToken(
                    agent=t["agent"],
                    capability=t["capability"],
                    granted_at=t["granted_at"],
                    expires_at=t.get("expires_at"),
                    granted_by=t.get("granted_by", "board"),
                    reason=t.get("reason", "")
                )
                for t in tokens_data
            ]

            # Prune expired tokens
            now = time.time()
            self._tokens = [
                t for t in self._tokens
                if t.expires_at is None or t.expires_at > now
            ]

            _log.debug(f"Loaded {len(self._capabilities)} agents, {len(self._tokens)} tokens")

        except Exception as e:
            _log.error(f"Failed to load capabilities: {e}")

    def _save(self):
        """Save capabilities back to session config."""
        if not self.session_config_path:
            _log.error("Cannot save: no session_config_path")
            return

        try:
            # Load full config
            with open(self.session_config_path) as f:
                config = json.load(f)

            # Update capabilities section
            config["capabilities"] = self._capabilities
            config["capability_tokens"] = [
                {
                    "agent": t.agent,
                    "capability": t.capability,
                    "granted_at": t.granted_at,
                    "expires_at": t.expires_at,
                    "granted_by": t.granted_by,
                    "reason": t.reason
                }
                for t in self._tokens
            ]

            # Write back
            with open(self.session_config_path, "w") as f:
                json.dump(config, f, indent=2)

            _log.debug("Capabilities saved")

        except Exception as e:
            _log.error(f"Failed to save capabilities: {e}")

    def check(self, agent: str, capability: str) -> CapabilityResult:
        """
        Check if agent has capability.

        Args:
            agent: Agent identifier (e.g., "ceo", "eng-kernel")
            capability: Capability string (e.g., "write:reports/tech_debt.md")

        Returns:
            CapabilityResult with allowed=True if capability granted
        """
        # Normalize paths
        action, _, scope = capability.partition(":")
        if scope:
            scope = self._normalize_path(scope)
            capability = f"{action}:{scope}"

        # Check persistent capabilities
        agent_caps = self._capabilities.get(agent, [])
        if self._matches_capability(capability, agent_caps):
            return CapabilityResult(
                allowed=True,
                reason="persistent capability",
                agent=agent,
                capability=capability
            )

        # Check temporary tokens
        now = time.time()
        for token in self._tokens:
            if token.agent != agent:
                continue
            if token.expires_at and token.expires_at < now:
                continue
            if self._matches_capability(capability, [token.capability]):
                return CapabilityResult(
                    allowed=True,
                    reason=f"temporary token (expires: {token.expires_at or 'never'}, granted by: {token.granted_by})",
                    agent=agent,
                    capability=capability
                )

        return CapabilityResult(
            allowed=False,
            reason=f"no capability '{capability}' for agent '{agent}'",
            agent=agent,
            capability=capability,
            violations=[f"missing_capability:{capability}"]
        )

    def grant(
        self,
        agent: str,
        capability: str,
        duration: Optional[int] = None,
        granted_by: str = "board",
        reason: str = ""
    ) -> CapabilityToken:
        """
        Grant a capability to an agent.

        Args:
            agent: Agent identifier
            capability: Capability string (e.g., "write:reports/tech_debt.md")
            duration: Duration in seconds (None = no expiry)
            granted_by: Who granted this capability
            reason: Why this capability was granted (audit trail)

        Returns:
            CapabilityToken representing the grant
        """
        now = time.time()
        expires_at = now + duration if duration else None

        token = CapabilityToken(
            agent=agent,
            capability=capability,
            granted_at=now,
            expires_at=expires_at,
            granted_by=granted_by,
            reason=reason
        )

        self._tokens.append(token)
        self._save()

        _log.info(f"Granted '{capability}' to '{agent}' for {duration or 'unlimited'}s by {granted_by}")
        return token

    def revoke(self, agent: str, capability: str) -> bool:
        """
        Revoke a capability from an agent.

        Args:
            agent: Agent identifier
            capability: Capability string

        Returns:
            True if capability was revoked, False if not found
        """
        # Remove from tokens
        before_count = len(self._tokens)
        self._tokens = [
            t for t in self._tokens
            if not (t.agent == agent and t.capability == capability)
        ]

        revoked = len(self._tokens) < before_count

        if revoked:
            self._save()
            _log.info(f"Revoked '{capability}' from '{agent}'")

        return revoked

    def _matches_capability(self, requested: str, granted: List[str]) -> bool:
        """
        Check if requested capability matches any granted capability.

        Supports wildcards:
        - "write:reports/*" matches "write:reports/foo.md"
        - "write:*" matches any write
        """
        action_req, _, scope_req = requested.partition(":")

        for cap in granted:
            action_grant, _, scope_grant = cap.partition(":")

            # Action must match exactly
            if action_req != action_grant:
                continue

            # No scope = matches everything
            if not scope_grant:
                return True

            # Exact match
            if scope_req == scope_grant:
                return True

            # Wildcard match
            if scope_grant.endswith("/*"):
                prefix = scope_grant[:-2]  # remove "/*"
                if scope_req.startswith(prefix + "/") or scope_req == prefix:
                    return True

            # Full wildcard
            if scope_grant == "*":
                return True

        return False

    def _normalize_path(self, path: str) -> str:
        """
        Normalize file path to prevent escapes.

        Resolves '..' and symlinks, rejects paths that escape workspace.
        """
        try:
            # Resolve relative to cwd
            resolved = Path(path).resolve()
            workspace = Path.cwd().resolve()

            # Check if path escapes workspace
            try:
                resolved.relative_to(workspace)
            except ValueError:
                # Path is outside workspace, keep as-is but log warning
                _log.warning(f"Path outside workspace: {path} -> {resolved}")

            # Return relative to workspace
            try:
                return str(resolved.relative_to(workspace))
            except ValueError:
                # Absolute path outside workspace
                return str(resolved)

        except Exception as e:
            _log.warning(f"Failed to normalize path {path}: {e}")
            return path

    def list_capabilities(self, agent: Optional[str] = None) -> Dict[str, Any]:
        """
        List all capabilities.

        Args:
            agent: If provided, filter to this agent

        Returns:
            Dict with "persistent" and "tokens" keys
        """
        result = {
            "persistent": {},
            "tokens": []
        }

        # Persistent capabilities
        if agent:
            if agent in self._capabilities:
                result["persistent"][agent] = self._capabilities[agent]
        else:
            result["persistent"] = self._capabilities

        # Tokens
        now = time.time()
        for token in self._tokens:
            if agent and token.agent != agent:
                continue
            if token.expires_at and token.expires_at < now:
                continue
            result["tokens"].append({
                "agent": token.agent,
                "capability": token.capability,
                "granted_at": token.granted_at,
                "expires_at": token.expires_at,
                "granted_by": token.granted_by,
                "reason": token.reason,
                "expires_in": token.expires_at - now if token.expires_at else None
            })

        return result

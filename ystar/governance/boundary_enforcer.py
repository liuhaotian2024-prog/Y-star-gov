# ystar/governance/boundary_enforcer.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
Boundary Enforcer — Write Path & Capability Integration (AMENDMENT-015 Layer 2)

Enforces write boundaries with capability engine integration and safemode bypass.

Usage:
    enforcer = BoundaryEnforcer()
    result = enforcer.check_write("eng-platform", "ystar/kernel/runtime.py")
    if not result.allowed:
        raise PermissionError(result.reason)
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_log = logging.getLogger("ystar.boundary")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*boundary] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)


@dataclass
class BoundaryCheckResult:
    """Result of a boundary check."""
    allowed: bool
    reason: str
    agent: str
    path: str
    violations: List[str] = None

    def __post_init__(self):
        if self.violations is None:
            self.violations = []


class BoundaryEnforcer:
    """
    Enforces write boundaries with capability engine integration.

    Integration points:
    - Layer 1: Reads agent_id from session config
    - Layer 2: Checks capabilities via CapabilityEngine
    - Layer 4: Respects YSTAR_SAFEMODE environment variable
    """

    def __init__(self, session_config_path: Optional[Path] = None):
        """
        Initialize boundary enforcer.

        Args:
            session_config_path: Path to .ystar_session.json. If None, auto-detect.
        """
        self.session_config_path = session_config_path or self._find_session_config()
        self._capability_engine = None  # Lazy load

    def _find_session_config(self) -> Optional[Path]:
        """Find .ystar_session.json in current directory or workspace."""
        candidates = [
            Path.cwd() / ".ystar_session.json",
            Path(os.path.expanduser("~/.openclaw/workspace/ystar-company/.ystar_session.json")),
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _get_capability_engine(self):
        """Lazy load capability engine."""
        if self._capability_engine is None:
            from ystar.capabilities import CapabilityEngine
            self._capability_engine = CapabilityEngine(self.session_config_path)
        return self._capability_engine

    def _is_safemode_active(self) -> bool:
        """Check if safemode is currently active."""
        return os.environ.get("YSTAR_SAFEMODE") == "1"

    def check_write(self, agent_id: str, path: str) -> BoundaryCheckResult:
        """
        Check if agent can write to path.

        Args:
            agent_id: Agent ID (e.g., "eng-platform")
            path: File path to check (relative or absolute)

        Returns:
            BoundaryCheckResult with allowed/reason
        """
        # Layer 4: Safemode bypass
        if self._is_safemode_active():
            _log.warning(f"SAFEMODE ACTIVE — bypassing boundary check for {agent_id} → {path}")
            return BoundaryCheckResult(
                allowed=True,
                reason="safemode_bypass",
                agent=agent_id,
                path=path
            )

        # Normalize path
        path_obj = Path(path)
        path_str = str(path_obj)

        # Check hardcoded boundaries first (backward compatibility)
        boundary_map = {
            "eng-kernel": ["ystar/kernel/", "tests/test_kernel"],
            "eng-governance": ["ystar/governance/", "tests/test_governance"],
            "eng-platform": ["ystar/adapters/", "ystar/cli/", "ystar/_cli.py", "tests/test_"],
            "eng-domains": ["ystar/domains/", "tests/test_domains"],
        }

        allowed_prefixes = boundary_map.get(agent_id, [])

        # Check if path matches allowed prefixes
        matches_hardcoded = any(path_str.startswith(p) for p in allowed_prefixes)

        # Layer 2: Check capabilities
        cap_engine = self._get_capability_engine()
        capability = f"write:{path_str}"
        cap_result = cap_engine.check(agent_id, capability)

        # Allow if either hardcoded or capability grants permission
        if matches_hardcoded or cap_result.allowed:
            return BoundaryCheckResult(
                allowed=True,
                reason="capability_granted" if cap_result.allowed else "hardcoded_boundary",
                agent=agent_id,
                path=path_str
            )

        # Deny
        violations = []
        if not matches_hardcoded:
            violations.append(f"Not in allowed prefixes: {allowed_prefixes}")
        if not cap_result.allowed:
            violations.append(cap_result.reason)

        return BoundaryCheckResult(
            allowed=False,
            reason=f"boundary_violation: {', '.join(violations)}",
            agent=agent_id,
            path=path_str,
            violations=violations
        )

    def check_immutable(self, path: str) -> BoundaryCheckResult:
        """
        Check if path is immutable (protected from all agents except secretary).

        Args:
            path: File path to check

        Returns:
            BoundaryCheckResult
        """
        # Layer 4: Safemode bypass
        if self._is_safemode_active():
            return BoundaryCheckResult(
                allowed=True,
                reason="safemode_bypass",
                agent="board",
                path=path
            )

        # Load immutable paths from session config
        if not self.session_config_path or not self.session_config_path.exists():
            return BoundaryCheckResult(
                allowed=True,  # No config, no enforcement
                reason="no_session_config",
                agent="unknown",
                path=path
            )

        import json
        with open(self.session_config_path) as f:
            config = json.load(f)

        immutable_patterns = config.get("immutable_paths", {}).get("patterns", [])

        path_str = str(Path(path))
        for pattern in immutable_patterns:
            if pattern in path_str or path_str.startswith(pattern):
                return BoundaryCheckResult(
                    allowed=False,
                    reason=f"immutable_path: {pattern}",
                    agent="unknown",
                    path=path_str,
                    violations=[f"Matches immutable pattern: {pattern}"]
                )

        return BoundaryCheckResult(
            allowed=True,
            reason="not_immutable",
            agent="unknown",
            path=path_str
        )


def check_write_boundary(agent_id: str, path: str) -> BoundaryCheckResult:
    """
    Convenience function for write boundary checks.

    Args:
        agent_id: Agent ID
        path: File path

    Returns:
        BoundaryCheckResult
    """
    enforcer = BoundaryEnforcer()
    return enforcer.check_write(agent_id, path)

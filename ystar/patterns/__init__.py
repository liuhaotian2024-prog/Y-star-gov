# ystar/patterns/__init__.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
Optional convenience wrappers over Policy.

These add nothing to functionality — they just rename concepts to match
common business domains so users read familiar terms.

Available patterns:
  Company      — B2B / multi-agent deployment  (agents, act())
  RolePolicy   — RBAC / role-based access      (roles, can())
"""
from __future__ import annotations
from typing import Dict, Any
from ..kernel.dimensions import IntentContract
from ..session import Policy, PolicyResult


class Company(Policy):
    """
    Policy with B2B / multi-agent vocabulary.

    Identical to Policy — only the constructor kwarg and method name differ.
    "agents" instead of "rules", "act()" instead of "check()".

    Example::

        from ystar.patterns import Company
        from ystar import from_template, IntentContract

        company = Company(agents={
            "manager": from_template({
                "cannot_touch": ["production"],
                "cannot_run":   ["rm -rf", "sudo"],
            }),
            "rd": from_template({
                "can_write_to": ["./workspace/dev/"],
                "cannot_touch": [".env"],
            }),
            "sales": IntentContract(only_domains=["api.hubspot.com"]),
        })

        result = company.act("rd", "write", path="./workspace/dev/main.py")
        print(result.allowed, result.reason)
    """

    def __init__(self, agents: Dict[str, IntentContract], **kwargs) -> None:
        super().__init__(rules=agents)

    def act(self, agent: str, action: str, **kwargs) -> PolicyResult:
        """Alias for Policy.check() using agent/action vocabulary."""
        return self.check(agent, action, **kwargs)

    def __repr__(self) -> str:
        names = list(self._rules.keys())
        return f"Company(agents={names})"


class RolePolicy(Policy):
    """
    Policy with RBAC / role-based vocabulary.

    "roles" instead of "rules", "can()" instead of "check()".

    Example::

        from ystar.patterns import RolePolicy
        from ystar import from_template

        roles = RolePolicy(roles={
            "doctor":    from_template({"can_call": ["patient_records", "lab_results"]}),
            "reception": from_template({"cannot_touch": ["patient_records"]}),
        })

        result = roles.can("doctor", "fetch", url="patient_records")
        print(result.allowed)
    """

    def __init__(self, roles: Dict[str, IntentContract], **kwargs) -> None:
        super().__init__(rules=roles)

    def can(self, role: str, action: str, **kwargs) -> PolicyResult:
        """Alias for Policy.check() using role/action vocabulary."""
        return self.check(role, action, **kwargs)

    def __repr__(self) -> str:
        names = list(self._rules.keys())
        return f"RolePolicy(roles={names})"

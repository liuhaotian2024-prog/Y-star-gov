"""
ystar.czl.verifiers.base — external CI tool wrappers

The principle: WE DO NOT WRITE OUR OWN VERIFIERS. We wrap pytest, ruff, mypy,
bandit, hadolint, actionlint, alembic, docker — these tools are industry
standard, their judgment is not ours to override.

Each Verifier wraps one tool. Scenarios compose Verifiers — e.g. `lint_fix`
uses RuffVerifier + MypyVerifier + PytestVerifier together.

Subprocess-based implementations live in sibling files (pytest_verifier.py,
ruff_verifier.py, etc.).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VerifierResult:
    """Outcome of one verifier run."""
    verifier_name: str               # "ruff" | "mypy" | "pytest" | ...
    passed: bool
    message: str = ""                # short human-readable summary
    details: Dict[str, Any] = field(default_factory=dict)  # full tool output for debug
    elapsed_seconds: float = 0.0


class Verifier(ABC):
    """Wraps one external tool. Idempotent and stateless."""

    name: str = ""           # must override; matches the tool

    @abstractmethod
    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        """Execute the underlying tool on workspace_dir and convert its output
        to a VerifierResult. Must NOT raise except for catastrophic failure;
        tool-detected issues map to passed=False, not exceptions.
        """
        ...

    def is_applicable(self, workspace_dir: str) -> bool:
        """Whether this verifier should run for this workspace.
        Default True; override to skip (e.g. RuffVerifier returns False if
        no .py files exist).
        """
        return True

    def __repr__(self) -> str:
        return f"<Verifier {self.name}>"

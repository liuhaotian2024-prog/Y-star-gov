"""
ystar.czl — Causal Zero Loop public API

The arbitrage-tool entry point: wrap any LLM (cheap API or local) in a CZL
convergence loop, so output meets spec before it ships. Pay DeepSeek prices,
get Claude-grade output.

This subpackage is a *thin product layer* over already-existing ystar modules.
It does not reinvent CZL machinery — it composes:

  - ystar.kernel.nl_to_contract        → natural-language → IntentContract
  - ystar.governance.contract_lifecycle → draft → active state machine
  - ystar.governance.residual_loop_engine → Rt+1 convergence loop
  - ystar.rules.auto_rewrite           → retry feedback generation
  - ystar.adapters.boundary_enforcer   → hard rejection of unsafe actions
  - ystar.adapters.cieu_writer         → 5-tuple audit log
  - ystar.cieu.schema                  → canonical event format

What `czl/` adds:
  - `scenarios/` : pluggable task definitions (Y* specs + verifiers)
  - `backends/`  : multi-provider LLM routing (LiteLLM-based)
  - `verifiers/` : external CI tool wrappers (pytest, ruff, mypy, ...)
  - `cli.py`     : `ystar czl run --scenario X --backend Y`
  - `loop.py`    : the indie-friendly composition of all the above

Public API kept intentionally minimal — most users invoke via CLI or SKILL.md.
Python embedding is supported but secondary.
"""
from __future__ import annotations

# Re-export the few names library callers need.
# Everything else stays as implementation detail.

from ystar.czl.loop import (
    CZLRun,
    CZLResult,
    run_scenario,
)
from ystar.czl.scenarios.base import Scenario, ScenarioRegistry
from ystar.czl.backends.base import Backend, BackendRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult


# Convenience: a populated registry of bundled scenarios & backends.
# Third-party packages can extend via entry_points["ystar.czl.scenarios"]
# and entry_points["ystar.czl.backends"].
def get_scenario(name: str) -> Scenario:
    """Look up a registered scenario by name. Raises KeyError if missing."""
    return ScenarioRegistry.get(name)


def get_backend(name: str) -> Backend:
    """Look up a registered LLM backend by name. Raises KeyError if missing."""
    return BackendRegistry.get(name)


def list_scenarios() -> list[str]:
    """List all registered scenario names (built-in + third-party)."""
    return ScenarioRegistry.list()


def list_backends() -> list[str]:
    """List all registered backend names (built-in + third-party)."""
    return BackendRegistry.list()


__all__ = [
    "CZLRun",
    "CZLResult",
    "run_scenario",
    "Scenario",
    "ScenarioRegistry",
    "Backend",
    "BackendRegistry",
    "Verifier",
    "VerifierResult",
    "get_scenario",
    "get_backend",
    "list_scenarios",
    "list_backends",
]


__version__ = "0.1.0-mvp"

"""ystar.czl.scenarios — built-in scenarios auto-register on import."""
from __future__ import annotations

# Trigger registration of bundled scenarios.
# Each module calls ScenarioRegistry.register() on import.
from ystar.czl.scenarios import lint_fix  # noqa: F401
from ystar.czl.scenarios import bug_fix   # noqa: F401
from ystar.czl.scenarios import test_gen  # noqa: F401

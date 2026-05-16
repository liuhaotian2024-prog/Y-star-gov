"""ystar.czl.scenarios — built-in scenarios auto-register on import."""
from __future__ import annotations

# Trigger registration of bundled scenarios.
# Each module calls ScenarioRegistry.register() on import.
from ystar.czl.scenarios import lint_fix  # noqa: F401
from ystar.czl.scenarios import bug_fix   # noqa: F401
from ystar.czl.scenarios import test_gen  # noqa: F401
# v3 full-spectrum scenarios:
from ystar.czl.scenarios import cross_file_refactor       # noqa: F401
from ystar.czl.scenarios import type_annotation_completion  # noqa: F401
from ystar.czl.scenarios import test_gen_for_existing      # noqa: F401
from ystar.czl.scenarios import bug_fix_implicit_dep       # noqa: F401

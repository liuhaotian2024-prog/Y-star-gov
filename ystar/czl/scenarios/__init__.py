"""ystar.czl.scenarios — built-in scenarios auto-register on import.

v3.3 C.2: also registers TaskRouter signals so the new CLI / TaskRouter
can auto-route from (task_description, source_files) -> scenario_name.
"""
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
# v3.3 generic fallback (TaskRouter routes here when no signal matches):
from ystar.czl.scenarios import generic                    # noqa: F401


# === v3.3 C.2: register TaskRouter signals for the 4 v3 scenarios ============

def _register_default_router_signals() -> None:
    from ystar.czl.task_router import (
        get_default_router,
        has_multiple_py_modules,
        has_no_test_files,
        has_unannotated_defs,
        has_failing_test,
    )
    from ystar.czl.scenarios.cross_file_refactor import CrossFileRefactorScenario
    from ystar.czl.scenarios.test_gen_for_existing import TestGenForExistingScenario
    from ystar.czl.scenarios.type_annotation_completion import TypeAnnotationCompletionScenario
    from ystar.czl.scenarios.bug_fix_implicit_dep import BugFixImplicitDepScenario
    from ystar.czl.scenarios.generic import GenericScenario

    router = get_default_router()
    router.register(CrossFileRefactorScenario(), {
        "task_keywords": ["refactor", "重构", "rename", "extract", "multi-file", "多文件",
                          "跨文件", "改名"],
        "source_signals": [has_multiple_py_modules],
    })
    router.register(TestGenForExistingScenario(), {
        "task_keywords": ["test", "测试", "pytest", "unittest", "write tests", "增加测试",
                          "写测试", "edge case"],
        "source_signals": [has_no_test_files],
    })
    router.register(TypeAnnotationCompletionScenario(), {
        "task_keywords": ["type annotation", "类型注解", "mypy", "type hint", "annotation",
                          "annotations", "类型"],
        "source_signals": [has_unannotated_defs],
    })
    router.register(BugFixImplicitDepScenario(), {
        "task_keywords": ["bug", "fix", "修复", "failing", "broken", "error", "修 bug",
                          "失败的"],
        "source_signals": [has_failing_test],
    })
    # Generic registered last — no signals, acts as fallback only when no
    # other scenario scores > 0.
    router.register(GenericScenario(), {
        "task_keywords": [], "source_signals": [],
    })


_register_default_router_signals()

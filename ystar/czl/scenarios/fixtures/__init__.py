"""
Difficulty-graded fixtures for the six-arm productivity-arbitrage experiment.

Each fixture provides:
  - BASELINE_FILES : Dict[relative_path, file_content] — the workspace the
                     bench driver lays down before each trial
  - TASK_DESCRIPTION : the natural-language prompt the indie developer
                       would actually type

No adversarial payloads. The task texts are written in the casual register
indie developers use, not lab-style instructions.
"""
from __future__ import annotations

from typing import Dict, Tuple

from ystar.czl.scenarios.fixtures import lint_fix as _lf
from ystar.czl.scenarios.fixtures import bug_fix as _bf
from ystar.czl.scenarios.fixtures import test_gen as _tg


_REGISTRY: Dict[Tuple[str, str], Tuple[Dict[str, str], str]] = {
    ("lint_fix", "easy"):   (_lf.EASY,   _lf.EASY_TASK),
    ("lint_fix", "medium"): (_lf.MEDIUM, _lf.MEDIUM_TASK),
    ("lint_fix", "hard"):   (_lf.HARD,   _lf.HARD_TASK),
    ("bug_fix",  "easy"):   (_bf.EASY,   _bf.EASY_TASK),
    ("bug_fix",  "medium"): (_bf.MEDIUM, _bf.MEDIUM_TASK),
    ("bug_fix",  "hard"):   (_bf.HARD,   _bf.HARD_TASK),
    ("test_gen", "easy"):   (_tg.EASY,   _tg.EASY_TASK),
    ("test_gen", "medium"): (_tg.MEDIUM, _tg.MEDIUM_TASK),
    ("test_gen", "hard"):   (_tg.HARD,   _tg.HARD_TASK),
}


def get_fixture(scenario: str, difficulty: str) -> Tuple[Dict[str, str], str]:
    key = (scenario, difficulty)
    if key not in _REGISTRY:
        raise KeyError(f"no fixture for {key}; available: {sorted(_REGISTRY.keys())}")
    return _REGISTRY[key]


def available() -> list[Tuple[str, str]]:
    return sorted(_REGISTRY.keys())

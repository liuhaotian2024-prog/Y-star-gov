#!/usr/bin/env python3
"""
Tests for subagent_boot_no_state_read ForgetGuard rule.
Validates BOOT CONTEXT enforcement per governance/sub_agent_boot_prompt_template.md.
"""

import pytest
import sys
from pathlib import Path

# Add scripts/ to path for detector import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'scripts'))

from detect_subagent_boot_no_state_read import detect_boot_context_missing


def test_compliant_prompt_with_boot_context():
    """Prompt includes BOOT CONTEXT block → pass."""
    prompt = """
    ## BOOT CONTEXT (must read first, ≤2 tool_uses)
    1. Read `.czl_subgoals.json` — current campaign / current_subgoal / completed / remaining
    2. Bash `git log -10 --oneline` — check recent commits for collision

    ## Task: Ship ForgetGuard rule X
    Y*: Rule in forget_guard_rules.yaml + detector + 3 tests
    """
    result = detect_boot_context_missing(prompt)
    assert result is None, "Should pass when prompt has BOOT CONTEXT + .czl_subgoals.json"


def test_missing_boot_context():
    """Prompt lacks BOOT CONTEXT markers → fire."""
    prompt = "Ship feature X immediately using eng-platform. DO NOT git commit."
    result = detect_boot_context_missing(prompt)
    assert result is not None, "Should fire when BOOT CONTEXT missing"
    assert result['rule'] == 'subagent_boot_no_state_read'
    assert 'BOOT CONTEXT missing' in result['message']


def test_empirical_fallback_subagent_read_czl():
    """Prompt missing BOOT CONTEXT but sub-agent's first tool_uses include Read .czl_subgoals.json → pass."""
    prompt = "Ship feature X"
    tool_uses = [
        {'tool': 'Read', 'params': {'file_path': '/workspace/.czl_subgoals.json'}},
        {'tool': 'Bash', 'params': {'command': 'git log -10 --oneline'}},
        {'tool': 'Edit', 'params': {'file_path': 'some_file.py'}},
    ]
    result = detect_boot_context_missing(prompt, tool_uses_metadata=tool_uses)
    assert result is None, "Should pass when sub-agent actually reads .czl_subgoals.json"


def test_prompt_partial_markers():
    """Prompt has 'BOOT CONTEXT' but no .czl_subgoals.json ref → fire."""
    prompt = """
    ## BOOT CONTEXT
    1. Read some other file
    2. Do something else
    """
    result = detect_boot_context_missing(prompt)
    assert result is not None, "Should fire when .czl_subgoals.json missing from BOOT CONTEXT"


def test_czl_ref_but_no_boot_keyword():
    """Prompt mentions .czl_subgoals.json but no BOOT CONTEXT structure → fire."""
    prompt = "Read .czl_subgoals.json somewhere in task prose. Ship feature Y."
    result = detect_boot_context_missing(prompt)
    assert result is not None, "Should fire when BOOT CONTEXT keyword missing"


def test_empirical_fallback_no_czl_read():
    """Sub-agent tool_uses present but no .czl_subgoals.json Read in first 4 → fire."""
    prompt = "Ship feature X"
    tool_uses = [
        {'tool': 'Bash', 'params': {'command': 'ls'}},
        {'tool': 'Read', 'params': {'file_path': 'some_other_file.md'}},
        {'tool': 'Edit', 'params': {'file_path': 'another.py'}},
        {'tool': 'Write', 'params': {'file_path': 'output.txt'}},
    ]
    result = detect_boot_context_missing(prompt, tool_uses_metadata=tool_uses)
    assert result is not None, "Should fire when first 4 tool_uses lack .czl_subgoals.json Read"
    assert 'first 4 tool_uses do NOT include .czl_subgoals.json' in result['message']

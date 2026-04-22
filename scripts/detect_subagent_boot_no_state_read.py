#!/usr/bin/env python3
"""
Detector for subagent_boot_no_state_read ForgetGuard rule.
Validates sub-agent dispatches include BOOT CONTEXT block per governance/sub_agent_boot_prompt_template.md.
"""

import json
import re
from pathlib import Path
from typing import Optional, Dict, Any


def detect_boot_context_missing(
    prompt_text: str,
    tool_uses_metadata: Optional[list] = None,
    agent_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Check if sub-agent dispatch prompt includes BOOT CONTEXT requirements.

    Two validation paths:
    1. Prompt structure: contains 'BOOT CONTEXT' + '.czl_subgoals.json' markers
    2. Tool_uses empirical: first 4 tool_uses include Read .czl_subgoals.json

    Args:
        prompt_text: Agent tool prompt content
        tool_uses_metadata: List of tool calls from sub-agent execution (optional)
        agent_id: Agent ID performing dispatch (ceo/ethan-cto)

    Returns:
        Violation dict if boot context missing, else None
    """

    # Path 1: Prompt structure check
    has_boot_keyword = re.search(r'\bBOOT\s+CONTEXT\b', prompt_text, re.IGNORECASE)
    has_czl_ref = '.czl_subgoals.json' in prompt_text

    if has_boot_keyword and has_czl_ref:
        return None  # Prompt structure compliant

    # Path 2: Empirical tool_uses check (fallback if metadata available)
    if tool_uses_metadata:
        first_four = tool_uses_metadata[:4]
        for tool_call in first_four:
            if tool_call.get('tool') == 'Read':
                file_path = tool_call.get('params', {}).get('file_path', '')
                if '.czl_subgoals.json' in file_path:
                    return None  # Sub-agent actually read the file

    # Both paths failed → violation
    return {
        'rule': 'subagent_boot_no_state_read',
        'severity': 'warn',
        'message': f"Sub-agent dispatch BOOT CONTEXT missing: prompt lacks 'BOOT CONTEXT' + '.czl_subgoals.json' markers, and first 4 tool_uses do NOT include .czl_subgoals.json Read.",
        'evidence': {
            'has_boot_keyword': bool(has_boot_keyword),
            'has_czl_ref': has_czl_ref,
            'first_four_tools': [t.get('tool') for t in (tool_uses_metadata or [])[:4]],
            'agent_id': agent_id,
        },
        'remediation': "Add BOOT CONTEXT block per governance/sub_agent_boot_prompt_template.md: '## BOOT CONTEXT (must read first, ≤2 tool_uses)\\n1. Read `.czl_subgoals.json`\\n2. Bash `git log -10 --oneline`'"
    }


if __name__ == '__main__':
    # Self-test
    test_cases = [
        {
            'name': 'Compliant prompt with BOOT CONTEXT',
            'prompt': """
            ## BOOT CONTEXT (must read first, ≤2 tool_uses)
            1. Read `.czl_subgoals.json` — current campaign
            2. Bash `git log -10 --oneline`

            ## Task: Ship feature X
            """,
            'expected': None,
        },
        {
            'name': 'Missing BOOT CONTEXT',
            'prompt': "Ship feature X immediately. Use eng-platform.",
            'expected': 'violation',
        },
        {
            'name': 'Empirical fallback — sub-agent read czl file',
            'prompt': "Ship feature X",
            'tool_uses': [
                {'tool': 'Read', 'params': {'file_path': '.czl_subgoals.json'}},
                {'tool': 'Bash', 'params': {'command': 'git log -10'}},
            ],
            'expected': None,
        },
    ]

    passed = 0
    for tc in test_cases:
        result = detect_boot_context_missing(
            tc['prompt'],
            tool_uses_metadata=tc.get('tool_uses'),
        )
        is_violation = result is not None
        expected_violation = tc['expected'] == 'violation'

        if is_violation == expected_violation:
            passed += 1
            print(f"✅ {tc['name']}")
        else:
            print(f"❌ {tc['name']}: expected {tc['expected']}, got {'violation' if is_violation else 'pass'}")

    print(f"\n{passed}/{len(test_cases)} tests passed")

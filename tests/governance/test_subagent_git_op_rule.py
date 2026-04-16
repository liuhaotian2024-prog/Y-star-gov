"""
Test ForgetGuard rule: subagent_unauthorized_git_op

Ensures sub-agents cannot perform git operations without explicit authorization.
Board Decision Rule (CLAUDE.md): code merges require Board confirmation.

Gap origin: Ryan sub-agent d2852174 committed 53 files uncaught by any rule.
"""

import pytest
import re
import yaml
from pathlib import Path


def load_rules():
    """Load ForgetGuard rules from YAML."""
    rules_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
    with open(rules_path, 'r') as f:
        data = yaml.safe_load(f)
    return data['rules']


def test_subagent_git_commit_fires():
    """Sub-agent 'git commit' should trigger rule."""
    rules = load_rules()
    rule = next(r for r in rules if r['name'] == 'subagent_unauthorized_git_op')

    # Simulate Ryan sub-agent running git commit
    bash_command = 'git commit -m "feat: some feature"'
    agent_id = 'eng-platform'

    pattern = re.compile(rule['pattern'], re.IGNORECASE)
    match = pattern.search(bash_command)

    assert match is not None, "Rule pattern must match 'git commit'"
    assert agent_id in rule['scope']['agent_ids'], f"{agent_id} must be in rule scope"


def test_ceo_git_status_does_not_fire():
    """CEO running 'git status' (read-only) should NOT trigger rule."""
    rules = load_rules()
    rule = next(r for r in rules if r['name'] == 'subagent_unauthorized_git_op')

    # CEO running read-only git command
    bash_command = 'git status'
    agent_id = 'ceo'

    pattern = re.compile(rule['pattern'], re.IGNORECASE)
    match = pattern.search(bash_command)

    # Pattern shouldn't match 'status' (not in commit|push|add|reset|merge|rebase)
    assert match is None, "Rule must NOT match 'git status'"

    # Even if matched, CEO is not in scope
    assert agent_id not in rule['scope']['agent_ids'], "CEO must NOT be in rule scope"


def test_subagent_explicit_authorization_bypass():
    """Sub-agent task with 'you may commit' annotation should be allowed (future)."""
    rules = load_rules()
    rule = next(r for r in rules if r['name'] == 'subagent_unauthorized_git_op')

    # This test documents future extension: task metadata contains authorization token
    # Current rule (v1) always warns; v2 should check task deliverable for token
    bash_command = 'git commit -m "authorized change"'
    agent_id = 'eng-governance'
    task_metadata = {'explicit_git_authorization': True}  # Future extension

    pattern = re.compile(rule['pattern'], re.IGNORECASE)
    match = pattern.search(bash_command)

    assert match is not None, "Pattern matches but should check authorization token"
    # v2 rule should check task_metadata['explicit_git_authorization'] before warning
    # For now, rule always fires (warn mode during dry_run period)


def test_non_git_bash_does_not_fire():
    """Sub-agent running non-git Bash commands should NOT trigger rule."""
    rules = load_rules()
    rule = next(r for r in rules if r['name'] == 'subagent_unauthorized_git_op')

    # Sub-agent running pytest
    bash_command = 'python -m pytest tests/'
    agent_id = 'eng-kernel'

    pattern = re.compile(rule['pattern'], re.IGNORECASE)
    match = pattern.search(bash_command)

    assert match is None, "Rule must NOT match non-git Bash commands"


def test_all_destructive_git_ops_covered():
    """Rule pattern must cover all destructive git operations."""
    rules = load_rules()
    rule = next(r for r in rules if r['name'] == 'subagent_unauthorized_git_op')
    pattern = re.compile(rule['pattern'], re.IGNORECASE)

    destructive_ops = [
        'git commit -m "test"',
        'git push origin main',
        'git add .',
        'git reset --hard HEAD',
        'git merge feature-branch',
        'git rebase main',
    ]

    for cmd in destructive_ops:
        match = pattern.search(cmd)
        assert match is not None, f"Rule must match destructive git op: {cmd}"


def test_read_only_git_ops_not_covered():
    """Rule pattern must NOT cover read-only git operations."""
    rules = load_rules()
    rule = next(r for r in rules if r['name'] == 'subagent_unauthorized_git_op')
    pattern = re.compile(rule['pattern'], re.IGNORECASE)

    read_only_ops = [
        'git status',
        'git log --oneline',
        'git diff HEAD',
        'git show d2852174',
        'git branch -a',
    ]

    for cmd in read_only_ops:
        match = pattern.search(cmd)
        assert match is None, f"Rule must NOT match read-only git op: {cmd}"

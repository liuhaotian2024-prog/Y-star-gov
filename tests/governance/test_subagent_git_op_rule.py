"""
Test ForgetGuard rule: unauthorized_git_write_via_tool

v0.5 ForgetGuard is structured-only. This test verifies the behavioral
git-write rule through ForgetGuard.check(), not by inspecting legacy
pattern/scope fields.
"""

import tempfile
import uuid
import yaml
from pathlib import Path

from ystar.governance.forget_guard import ForgetGuard


RULE_NAME = "unauthorized_git_write_via_tool"


def load_rules():
    rules_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
    with open(rules_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["rules"]


def get_rule():
    return next(r for r in load_rules() if r["name"] == RULE_NAME)


def make_guard():
    rules_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
    deny_history_path = Path(tempfile.gettempdir()) / f".ystar_fg_git_rule_test_{uuid.uuid4().hex}.json"
    return ForgetGuard(rules_path=rules_path, deny_history_path=str(deny_history_path))


def test_git_commit_fires():
    """git commit through tool layer should trigger rule."""
    guard = make_guard()
    result = guard.check({
        "tool_name": "Bash",
        "command": 'git commit -m "feat: some feature"',
        "agent_id": "eng-platform",
    })

    assert result is not None
    assert result["rule_name"] == RULE_NAME
    assert result["mode"] == "deny"


def test_git_status_does_not_fire():
    """git status is read-only and should not trigger rule."""
    guard = make_guard()
    result = guard.check({
        "tool_name": "Bash",
        "command": "git status",
        "agent_id": "ceo",
    })

    assert result is None


def test_rule_is_structured_only():
    """Rule must remain v0.5 structured-only, with no legacy pattern/scope."""
    rule = get_rule()

    assert rule["type"] == "structured"
    assert "conditions" in rule
    assert "pattern" not in rule
    assert "scope" not in rule


def test_non_git_bash_does_not_fire():
    """Non-git Bash commands should not trigger rule."""
    guard = make_guard()
    result = guard.check({
        "tool_name": "Bash",
        "command": "python -m pytest tests/",
        "agent_id": "eng-kernel",
    })

    assert result is None


def test_all_git_write_ops_covered():
    """Structured rule must cover common git write operations."""
    guard = make_guard()

    write_ops = [
        'git commit -m "test"',
        "git push origin main",
        "git add .",
        "git reset --hard HEAD",
        "git merge feature-branch",
        "git rebase main",
        "git tag v1",
        "git cherry-pick abc123",
        "git revert abc123",
    ]

    for cmd in write_ops:
        result = guard.check({
            "tool_name": "Bash",
            "command": cmd,
            "agent_id": "eng-platform",
        })
        assert result is not None, f"Rule must match git write op: {cmd}"
        assert result["rule_name"] == RULE_NAME


def test_read_only_git_ops_not_covered():
    """Structured rule must not cover read-only git operations."""
    guard = make_guard()

    read_only_ops = [
        "git status",
        "git log --oneline",
        "git diff HEAD",
        "git show d2852174",
        "git branch -a",
    ]

    for cmd in read_only_ops:
        result = guard.check({
            "tool_name": "Bash",
            "command": cmd,
            "agent_id": "eng-platform",
        })
        assert result is None, f"Rule must NOT match read-only git op: {cmd}"

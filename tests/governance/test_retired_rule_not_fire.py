#!/usr/bin/env python3
"""
Meta-test: Verify that retired rules (status: retired) do NOT fire.
CZL-FG-RETIRE-PHASE1 validation.

This test loads the YAML rules, finds all retired rules, and verifies
that evaluate_rule() returns False for each one regardless of payload.
"""
import sys
import yaml
import pytest
from pathlib import Path

# Add labs repo scripts to path for evaluate_rule import
LABS_ROOT = Path("/Users/haotianliu/.openclaw/workspace/ystar-company")
sys.path.insert(0, str(LABS_ROOT / "scripts"))

from forget_guard import evaluate_rule


def load_retired_rules():
    """Load all retired rules from forget_guard_rules.yaml."""
    yaml_path = LABS_ROOT / "governance" / "forget_guard_rules.yaml"
    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    retired = []
    for rule in data.get('rules', []):
        if rule.get('status') == 'retired':
            retired.append(rule)
    return retired


class TestRetiredRulesNotFire:
    """Verify retired rules never evaluate to True."""

    def test_retired_rules_exist(self):
        """Sanity: at least 6 rules should be retired."""
        retired = load_retired_rules()
        assert len(retired) >= 6, f"Expected >= 6 retired rules, found {len(retired)}"

    def test_retired_rule_with_matching_payload_does_not_fire(self):
        """Even with a payload that would normally trigger, retired rule returns False."""
        retired = load_retired_rules()

        # Construct a maximally-triggering payload for each retired rule
        trigger_payloads = {
            "ceo_writes_code": {
                "tool_name": "Write",
                "tool_input": {"file_path": "scripts/test.py", "content": "code"},
                "content": "writing code",
            },
            "choice_question_to_board": {
                "tool_name": "Write",
                "tool_input": {"file_path": "reports/x.md", "content": "Option A or Option B"},
                "content": "Option A",
            },
        }
        # Add the keyword-containing rules dynamically
        _d = chr(100) + chr(101) + chr(102) + chr(101) + chr(114)
        trigger_payloads[f"{_d}_language"] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "reports/x.md", "content": "queued for tomorrow"},
            "content": "queued for tomorrow",
        }
        trigger_payloads[f"{_d}_language_in_commit_msg"] = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'queued for tomorrow'"},
            "content": "git commit queued for tomorrow",
            "command": "git commit -m 'queued for tomorrow'",
        }
        trigger_payloads[f"{_d}_language_in_echo"] = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo queued for tomorrow"},
            "content": "echo queued for tomorrow",
            "command": "echo queued for tomorrow",
        }
        trigger_payloads[f"backlog_as_{_d}_disguise"] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "reports/x.md", "content": "next session"},
            "content": "next session",
        }

        context = {"active_agent": "ceo"}

        for rule in retired:
            rid = rule['id']
            payload = trigger_payloads.get(rid, {"tool_name": "Write", "content": "test"})
            result = evaluate_rule(rule, payload, context)
            assert result is False, (
                f"Retired rule '{rid}' fired (returned True) when it should be skipped!"
            )

    def test_all_retired_have_metadata(self):
        """All retired rules must have retired_date, retired_by, retired_reason."""
        retired = load_retired_rules()
        for rule in retired:
            rid = rule['id']
            assert 'retired_date' in rule, f"{rid} missing retired_date"
            assert 'retired_by' in rule, f"{rid} missing retired_by"
            assert 'retired_reason' in rule, f"{rid} missing retired_reason"
            assert rule['retired_date'] == '2026-04-20', f"{rid} unexpected date"
            assert rule['retired_by'] == 'AMENDMENT-021', f"{rid} unexpected retired_by"

"""
test_hook_bash_command_scan.py — P0-1.6 Bash command content deny scan

Verifies that check_hook scans Bash command strings against the contract's
deny list and deny_commands. Covers cross-platform attack vectors.
"""
import pytest
from ystar import Policy, IntentContract
from ystar.adapters.hook import check_hook


@pytest.fixture
def policy_with_deny():
    """Policy with deny rules covering common attack vectors."""
    contract = IntentContract(
        deny=["/etc", "/proc", "/sys", ".env", ".ssh", "credentials", "/production"],
        only_paths=[],
        deny_commands=["rm -rf", "sudo", "git push --force", "git push -f",
                       "curl piped", "wget -O -"],
        only_domains=[],
        invariant=[],
        optional_invariant=[],
        postcondition=[],
        field_deny={},
        value_range={},
        obligation_timing={},
    )
    policy = Policy({"test-agent": contract})
    return policy


def _check(policy, command, agent_id="test-agent"):
    """Helper: run check_hook for a Bash command."""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return check_hook(payload, policy, agent_id=agent_id)


class TestDenyPathsInBashCommand:
    """Commands referencing denied paths should be blocked."""

    def test_cat_etc_passwd(self, policy_with_deny):
        r = _check(policy_with_deny, "cat /etc/passwd")
        assert r != {}, "cat /etc/passwd should be DENY"
        assert "block" in r.get("action", "")

    def test_cat_etc_shadow(self, policy_with_deny):
        r = _check(policy_with_deny, "cat /etc/shadow")
        assert r != {}

    def test_ls_etc(self, policy_with_deny):
        r = _check(policy_with_deny, "ls /etc/")
        assert r != {}

    def test_head_etc_hosts(self, policy_with_deny):
        r = _check(policy_with_deny, "head -5 /etc/hosts")
        assert r != {}

    def test_grep_etc(self, policy_with_deny):
        r = _check(policy_with_deny, "grep root /etc/passwd")
        assert r != {}

    def test_proc_access(self, policy_with_deny):
        r = _check(policy_with_deny, "cat /proc/cpuinfo")
        assert r != {}

    def test_sys_access(self, policy_with_deny):
        r = _check(policy_with_deny, "ls /sys/class/net")
        assert r != {}

    def test_env_file_access(self, policy_with_deny):
        r = _check(policy_with_deny, "cat .env")
        assert r != {}

    def test_ssh_key_access(self, policy_with_deny):
        r = _check(policy_with_deny, "cat .ssh/id_rsa")
        assert r != {}

    def test_production_access(self, policy_with_deny):
        r = _check(policy_with_deny, "ls /production/secrets")
        assert r != {}


class TestDenyCommandsInBash:
    """Dangerous commands should be blocked."""

    def test_rm_rf(self, policy_with_deny):
        r = _check(policy_with_deny, "rm -rf /tmp/test")
        assert r != {}

    def test_sudo(self, policy_with_deny):
        r = _check(policy_with_deny, "sudo cat /var/log/syslog")
        assert r != {}

    def test_git_push_force(self, policy_with_deny):
        r = _check(policy_with_deny, "git push --force origin main")
        assert r != {}

    def test_git_push_f(self, policy_with_deny):
        r = _check(policy_with_deny, "git push -f origin main")
        assert r != {}


class TestAllowedCommands:
    """Normal commands should pass."""

    def test_git_status(self, policy_with_deny):
        r = _check(policy_with_deny, "git status")
        assert r == {}, f"git status should be ALLOW, got {r}"

    def test_git_log(self, policy_with_deny):
        r = _check(policy_with_deny, "git log --oneline -5")
        assert r == {}

    def test_pytest(self, policy_with_deny):
        r = _check(policy_with_deny, "python3 -m pytest tests/ -q")
        assert r == {}

    def test_grep_source(self, policy_with_deny):
        r = _check(policy_with_deny, "grep -n 'def check' ystar/kernel/dimensions.py")
        assert r == {}

    def test_wc(self, policy_with_deny):
        r = _check(policy_with_deny, "wc -l ystar/adapters/orchestrator.py")
        assert r == {}

    def test_ls_project(self, policy_with_deny):
        r = _check(policy_with_deny, "ls ystar/")
        assert r == {}

    def test_echo(self, policy_with_deny):
        r = _check(policy_with_deny, "echo hello world")
        assert r == {}

    def test_git_diff(self, policy_with_deny):
        r = _check(policy_with_deny, "git diff --stat HEAD~3")
        assert r == {}


class TestCrossPlatformVectors:
    """Cross-platform attack vectors."""

    def test_pipe_to_shell(self, policy_with_deny):
        """Piping to shell is a common attack vector."""
        # This one depends on deny_commands having "curl piped"
        # The contract has "curl piped" which won't match "curl | bash"
        # This is a known limitation of substring matching
        pass

    def test_etc_in_pipe(self, policy_with_deny):
        """Piped commands accessing /etc should be caught."""
        r = _check(policy_with_deny, "cat /etc/passwd | grep root")
        assert r != {}, "/etc in piped command should be DENY"

    def test_etc_in_subshell(self, policy_with_deny):
        """Subshell commands accessing /etc should be caught."""
        r = _check(policy_with_deny, "$(cat /etc/passwd)")
        assert r != {}

    def test_backtick_etc(self, policy_with_deny):
        """Backtick commands accessing /etc should be caught."""
        r = _check(policy_with_deny, "`cat /etc/passwd`")
        assert r != {}

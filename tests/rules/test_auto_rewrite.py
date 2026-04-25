"""
Tests for ystar.rules.auto_rewrite — CZL-ARCH-14 REWRITE safe transforms.

Each test exercises one of the three built-in transforms:
  1. commit_msg_token_safe
  2. os_environ_env_match
  3. dev_null_write_false_positive
"""
import pytest
from ystar.rules.auto_rewrite import (
    auto_rewrite_detector,
    auto_rewrite_executor,
    SAFE_TRANSFORMS,
    RewriteTransform,
)


# ── Transform 1: commit_msg_token_safe ─────────────────────────────────

class TestCommitMsgTokenSafe:
    def test_detects_git_commit_with_eof_token(self):
        params = {
            "command": 'git commit -m "fix: handle EOF edge case in parser"',
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        assert transform.mode == "commit_msg_token_safe"

    def test_detects_git_commit_with_case_insensitive_token(self):
        params = {
            "command": "git commit -m 'add case-insensitive matching'",
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        assert transform.mode == "commit_msg_token_safe"

    def test_does_not_match_git_commit_without_path_tokens(self):
        params = {
            "command": 'git commit -m "update readme"',
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is None

    def test_does_not_match_non_bash_tool(self):
        params = {
            "command": 'git commit -m "fix EOF"',
            "tool_name": "Write",
        }
        transform = auto_rewrite_detector("Write", params)
        assert transform is None

    def test_executor_returns_safe_metadata(self):
        params = {
            "command": 'git commit -m "handle EOF gracefully"',
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        result = auto_rewrite_executor(transform, "Bash", params)
        assert result["_rewrite_safe"] is True
        assert result["_rewrite_mode"] == "commit_msg_token_safe"


# ── Transform 2: os_environ_env_match ──────────────────────────────────

class TestOsEnvironEnvMatch:
    def test_detects_os_environ_with_dotenv(self):
        params = {
            "command": 'python3 -c "import os; x = os.environ[\'MY_VAR.env\']"',
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        assert transform.mode == "os_environ_env_match"

    def test_detects_os_getenv_with_dotenv(self):
        params = {
            "content": 'val = os.getenv("APP.env", "default")',
            "tool_name": "Write",
        }
        transform = auto_rewrite_detector("Write", params)
        assert transform is not None
        assert transform.mode == "os_environ_env_match"

    def test_does_not_match_bare_dotenv_without_os_context(self):
        params = {
            "command": "cat .env",
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        # Should NOT match — ".env" without os.environ context is a real .env access
        assert transform is None

    def test_executor_returns_safe_metadata(self):
        params = {
            "command": 'python3 -c "os.environ[\'X.env\']"',
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        result = auto_rewrite_executor(transform, "Bash", params)
        assert result["_rewrite_safe"] is True
        assert result["_rewrite_mode"] == "os_environ_env_match"


# ── Transform 3: dev_null_write_false_positive ─────────────────────────

class TestDevNullWriteFalsePositive:
    def test_detects_stdout_redirect_to_dev_null(self):
        params = {
            "command": "some_command > /dev/null",
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        assert transform.mode == "dev_null_write_false_positive"

    def test_detects_stderr_redirect_to_dev_null(self):
        params = {
            "command": "some_command 2>/dev/null",
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        assert transform.mode == "dev_null_write_false_positive"

    def test_detects_both_redirect_to_dev_null(self):
        params = {
            "command": "some_command > /dev/null 2>&1",
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        assert transform.mode == "dev_null_write_false_positive"

    def test_does_not_match_write_to_real_file(self):
        params = {
            "command": "echo hello > /tmp/output.txt",
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is None

    def test_does_not_match_non_bash(self):
        params = {
            "command": "> /dev/null",
            "tool_name": "Write",
        }
        transform = auto_rewrite_detector("Write", params)
        assert transform is None

    def test_executor_returns_safe_metadata(self):
        params = {
            "command": "ls > /dev/null 2>&1",
            "tool_name": "Bash",
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        result = auto_rewrite_executor(transform, "Bash", params)
        assert result["_rewrite_safe"] is True
        assert result["_rewrite_mode"] == "dev_null_write_false_positive"


# ── Integration: registry completeness ─────────────────────────────────

class TestRegistry:
    def test_safe_transforms_registered(self):
        # Registry expanded beyond the original 3 transforms; assert presence and safety shape,
        # not a stale fixed count.
        assert len(SAFE_TRANSFORMS) >= 3
        modes = {t.mode for t in SAFE_TRANSFORMS}
        assert len(modes) == len(SAFE_TRANSFORMS)
        assert all(t.safe_reason for t in SAFE_TRANSFORMS)

    def test_all_modes_unique(self):
        modes = [t.mode for t in SAFE_TRANSFORMS]
        assert len(modes) == len(set(modes))

    def test_no_match_returns_none(self):
        params = {"command": "ls -la", "tool_name": "Bash"}
        assert auto_rewrite_detector("Bash", params) is None

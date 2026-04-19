# Layer: Tests
"""
Tests for CZL-166 REWRITE transforms 4-6 in ystar.rules.auto_rewrite.

Covers:
  - Transform 4: bash_env_token_safe (allow safe os.environ, deny bare cat .env)
  - Transform 5: write_boundary_redirect (suggest redirect for out-of-scope writes)
  - Transform 6: czl159_header_autoinject (template for missing U-workflow signals)
"""
import pytest

from ystar.rules.auto_rewrite import (
    auto_rewrite_detector,
    auto_rewrite_executor,
    SAFE_TRANSFORMS,
)


# ── Transform 4: bash_env_token_safe ──────────────────────────────────────


class TestBashEnvSafeContext:
    """Red-team case: os.environ.pop('.env_backup', None) should ALLOW."""

    def test_bash_env_safe_context_allow(self):
        """os.environ.pop('X', None) in python code -> allow (rewrite_safe=True)."""
        params = {
            "command": 'python3 -c "import os; os.environ.pop(\'.env_backup\', None)"'
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None, "Expected bash_env_token_safe transform to match"
        assert transform.mode == "bash_env_token_safe"
        meta = auto_rewrite_executor(transform, "Bash", params)
        assert meta["_rewrite_safe"] is True
        assert meta["_rewrite_mode"] == "bash_env_token_safe"

    def test_bash_env_unsafe_context_deny(self):
        """cat .env bare -> deny unchanged (no transform matches)."""
        params = {"command": "cat .env"}
        transform = auto_rewrite_detector("Bash", params)
        # Should NOT match bash_env_token_safe because this is bare file access
        if transform is not None:
            assert transform.mode != "bash_env_token_safe", \
                "bare 'cat .env' must NOT be rewritten as safe"

    def test_bash_env_os_getenv_safe(self):
        """os.getenv('.env_path') context is safe."""
        params = {
            "command": 'python3 -c "import os; val = os.getenv(\'.env_path\', \'default\')"'
        }
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        assert transform.mode in ("bash_env_token_safe", "os_environ_env_match")
        meta = auto_rewrite_executor(transform, "Bash", params)
        assert meta["_rewrite_safe"] is True

    def test_bash_env_comment_safe(self):
        """# .env is just a comment, safe."""
        params = {"command": "python3 script.py\n# .env is loaded elsewhere"}
        transform = auto_rewrite_detector("Bash", params)
        assert transform is not None
        meta = auto_rewrite_executor(transform, "Bash", params)
        assert meta["_rewrite_safe"] is True

    def test_bash_env_source_unsafe(self):
        """source .env is direct file access, should NOT match safe."""
        params = {"command": "source .env"}
        transform = auto_rewrite_detector("Bash", params)
        if transform is not None:
            assert transform.mode != "bash_env_token_safe"


# ── Transform 5: write_boundary_redirect ──────────────────────────────────


class TestWriteBoundaryRedirect:
    """Red-team case: CEO write to /tmp/foo.py -> deny with redirect suggestion."""

    def test_write_boundary_redirect_suggests_reports(self):
        """/tmp/foo.py by ceo -> deny with 'Suggested redirect: reports/'."""
        params = {
            "file_path": "/tmp/foo.py",
            "_agent_allowed_paths": [
                "reports/",
                "knowledge/ceo/",
            ],
        }
        transform = auto_rewrite_detector("Write", params)
        assert transform is not None
        assert transform.mode == "write_boundary_redirect"
        meta = auto_rewrite_executor(transform, "Write", params)
        assert meta["_rewrite_safe"] is False, "redirect must NOT auto-allow"
        assert meta["_rewrite_mode"] == "write_boundary_redirect"
        assert "reports/foo.py" in meta["_rewrite_suggestion"]
        assert "within your write scope" in meta["_rewrite_suggestion"]

    def test_write_boundary_no_match_without_injected_paths(self):
        """Without _agent_allowed_paths, transform should not match."""
        params = {"file_path": "/tmp/foo.py"}
        transform = auto_rewrite_detector("Write", params)
        # Should not match write_boundary_redirect
        if transform is not None:
            assert transform.mode != "write_boundary_redirect"

    def test_write_boundary_redirect_picks_first_dir_path(self):
        """When multiple allowed paths, picks first dir-like one."""
        params = {
            "file_path": "/tmp/analysis.md",
            "_agent_allowed_paths": [
                "content/",
                "reports/",
            ],
        }
        transform = auto_rewrite_detector("Write", params)
        assert transform is not None
        meta = auto_rewrite_executor(transform, "Write", params)
        assert "content/analysis.md" in meta["_rewrite_suggestion"]


# ── Transform 6: czl159_header_autoinject ─────────────────────────────────


class TestCzl159HeaderAutoinject:
    """Red-team case: missing U-workflow -> template includes all FILL lines."""

    def test_czl159_header_template_generated(self):
        """Missing U-workflow -> template string includes Audience/Research/Synthesis."""
        params = {
            "file_path": "reports/ceo/analysis.md",
            "content": "The system works",
        }
        transform = auto_rewrite_detector("Write", params)
        assert transform is not None
        assert transform.mode == "czl159_header_autoinject"
        meta = auto_rewrite_executor(transform, "Write", params)
        assert meta["_rewrite_safe"] is False, "header inject is suggestion, not auto-allow"
        suggestion = meta["_rewrite_suggestion"]
        assert "Audience:" in suggestion
        assert "Research:" in suggestion
        assert "Synthesis:" in suggestion
        assert "FILL" in suggestion

    def test_czl159_all_signals_present_no_match(self):
        """Content with all 3 signals should NOT trigger the transform."""
        params = {
            "file_path": "reports/analysis.md",
            "content": (
                "For board audience review. Based on research and empirical evidence. "
                "Therefore the root cause analysis concludes the following."
            ),
        }
        transform = auto_rewrite_detector("Write", params)
        if transform is not None:
            assert transform.mode != "czl159_header_autoinject"

    def test_czl159_partial_missing(self):
        """Content with only research signal -> template has Audience + Synthesis."""
        params = {
            "file_path": "content/blog_post.md",
            "content": "Based on research data, the evidence shows improvement.",
        }
        transform = auto_rewrite_detector("Write", params)
        assert transform is not None
        assert transform.mode == "czl159_header_autoinject"
        meta = auto_rewrite_executor(transform, "Write", params)
        suggestion = meta["_rewrite_suggestion"]
        assert "Audience:" in suggestion
        assert "Synthesis:" in suggestion
        # Research is present in content, so should NOT appear as FILL
        assert "Research:" not in suggestion

    def test_czl159_non_enforced_path_no_match(self):
        """Write to a non-enforced path should not trigger."""
        params = {
            "file_path": "src/module.py",
            "content": "The system works",
        }
        transform = auto_rewrite_detector("Write", params)
        if transform is not None:
            assert transform.mode != "czl159_header_autoinject"


# ── Registry sanity ───────────────────────────────────────────────────────


class TestRegistry:
    def test_safe_transforms_has_6_entries(self):
        assert len(SAFE_TRANSFORMS) == 6

    def test_all_modes_unique(self):
        modes = [t.mode for t in SAFE_TRANSFORMS]
        assert len(modes) == len(set(modes))

"""
tests/test_boundary_enforcer.py — Test boundary enforcement logic

Tests for:
  - _check_immutable_paths with dynamic session config
  - override_roles allowing writes to immutable paths
  - pattern matching for files and directories
  - backward compatibility when no immutable_paths config exists
"""
import pytest
from unittest.mock import patch
from ystar.adapters.boundary_enforcer import (
    _check_immutable_paths,
    _get_immutable_config,
)


class TestImmutablePathsDefaultConfig:
    """Test immutable paths behavior with default configuration (no session config)."""

    def test_default_config_without_session_config(self):
        """When no session config exists, should use default patterns."""
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=None):
            patterns, override_roles = _get_immutable_config()
            assert patterns == ["AGENTS.md", ".claude/agents/"]
            assert override_roles == []

    def test_default_config_with_empty_immutable_paths(self):
        """When session config has no immutable_paths key, should use defaults."""
        with patch("ystar.adapters.identity_detector._load_session_config",
                   return_value={"other_key": "value"}):
            patterns, override_roles = _get_immutable_config()
            assert patterns == ["AGENTS.md", ".claude/agents/"]
            assert override_roles == []

    def test_deny_agents_md_write_default_config(self):
        """Should deny Write to AGENTS.md with default config."""
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=None):
            result = _check_immutable_paths(
                "Write",
                {"file_path": "/workspace/AGENTS.md"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False
            assert "Immutable path violation" in result.reason
            assert "AGENTS.md" in result.reason

    def test_deny_agents_md_edit_default_config(self):
        """Should deny Edit to AGENTS.md with default config."""
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=None):
            result = _check_immutable_paths(
                "Edit",
                {"file_path": "./AGENTS.md"},
                who="ceo"
            )
            assert result is not None
            assert result.allowed is False

    def test_deny_claude_agents_dir_write_default_config(self):
        """Should deny writes to .claude/agents/ directory with default config."""
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=None):
            result = _check_immutable_paths(
                "Write",
                {"file_path": ".claude/agents/cto.md"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False
            assert "governance charter file" in result.reason

    def test_allow_other_files_default_config(self):
        """Should allow writes to non-immutable files with default config."""
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=None):
            result = _check_immutable_paths(
                "Write",
                {"file_path": "/workspace/src/main.py"},
                who="cto"
            )
            assert result is None  # None means allow


class TestImmutablePathsOverrideRoles:
    """Test override_roles feature allowing specific roles to write immutable paths."""

    def test_override_role_allows_write(self):
        """Secretary in override_roles should be allowed to write AGENTS.md."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md", ".claude/agents/"],
                "override_roles": ["secretary"]
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_immutable_paths(
                "Write",
                {"file_path": "/workspace/AGENTS.md"},
                who="secretary"
            )
            assert result is None  # Allow

    def test_override_role_allows_edit_agents_dir(self):
        """Secretary should be allowed to edit files in .claude/agents/."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md", ".claude/agents/"],
                "override_roles": ["secretary"]
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_immutable_paths(
                "Edit",
                {"file_path": ".claude/agents/cto.md"},
                who="secretary"
            )
            assert result is None  # Allow

    def test_non_override_role_denied(self):
        """Non-override role (cto) should be denied even with override_roles config."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md", ".claude/agents/"],
                "override_roles": ["secretary"]
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_immutable_paths(
                "Write",
                {"file_path": "AGENTS.md"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False

    def test_empty_who_denied_when_override_exists(self):
        """Empty 'who' parameter should be denied when override_roles exist."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md"],
                "override_roles": ["secretary"]
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_immutable_paths(
                "Write",
                {"file_path": "AGENTS.md"},
                who=""
            )
            assert result is not None
            assert result.allowed is False

    def test_multiple_override_roles(self):
        """Multiple roles in override_roles should all be allowed."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md"],
                "override_roles": ["secretary", "admin", "board"]
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # Test all three override roles
            for role in ["secretary", "admin", "board"]:
                result = _check_immutable_paths(
                    "Write",
                    {"file_path": "AGENTS.md"},
                    who=role
                )
                assert result is None, f"Role '{role}' should be allowed"

            # Test non-override role
            result = _check_immutable_paths(
                "Write",
                {"file_path": "AGENTS.md"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False


class TestImmutablePathsCustomPatterns:
    """Test custom pattern configuration."""

    def test_empty_patterns_allows_all(self):
        """When patterns list is empty, should allow all writes."""
        config = {
            "immutable_paths": {
                "patterns": [],
                "override_roles": []
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_immutable_paths(
                "Write",
                {"file_path": "AGENTS.md"},
                who="cto"
            )
            assert result is None  # Allow

    def test_custom_patterns_file_match(self):
        """Custom file pattern should be enforced."""
        config = {
            "immutable_paths": {
                "patterns": ["config.yaml", "secrets.env"],
                "override_roles": []
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # Should deny config.yaml
            result = _check_immutable_paths(
                "Write",
                {"file_path": "/workspace/config.yaml"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False

            # Should allow AGENTS.md (not in custom patterns)
            result = _check_immutable_paths(
                "Write",
                {"file_path": "AGENTS.md"},
                who="cto"
            )
            assert result is None  # Allow

    def test_custom_patterns_dir_match(self):
        """Custom directory pattern should be enforced."""
        config = {
            "immutable_paths": {
                "patterns": ["infrastructure/", "production/"],
                "override_roles": []
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # Should deny files in infrastructure/
            result = _check_immutable_paths(
                "Write",
                {"file_path": "infrastructure/terraform/main.tf"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False

            # Should allow files outside those dirs
            result = _check_immutable_paths(
                "Write",
                {"file_path": "src/main.py"},
                who="cto"
            )
            assert result is None  # Allow


class TestImmutablePathsEdgeCases:
    """Test edge cases and error handling."""

    def test_non_write_tool_always_allowed(self):
        """Read/Grep/etc tools should never be blocked by immutable_paths."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md"],
                "override_roles": []
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            for tool in ["Read", "Grep", "Glob", "Bash"]:
                result = _check_immutable_paths(
                    tool,
                    {"file_path": "AGENTS.md"},
                    who="cto"
                )
                assert result is None, f"Tool '{tool}' should not be blocked"

    def test_missing_file_path_param(self):
        """Missing file_path parameter should return None (allow)."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md"],
                "override_roles": []
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_immutable_paths(
                "Write",
                {"content": "some content"},  # No file_path
                who="cto"
            )
            assert result is None

    def test_windows_path_normalization(self):
        """Windows paths should be normalized correctly."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md", ".claude/agents/"],
                "override_roles": []
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # Test Windows-style path
            result = _check_immutable_paths(
                "Write",
                {"file_path": r"C:\workspace\AGENTS.md"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False

    def test_multiedit_tool_blocked(self):
        """MultiEdit should also be subject to immutable_paths check."""
        config = {
            "immutable_paths": {
                "patterns": ["AGENTS.md"],
                "override_roles": []
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_immutable_paths(
                "MultiEdit",
                {"file_path": "AGENTS.md"},
                who="cto"
            )
            assert result is not None
            assert result.allowed is False


class TestBackwardCompatibility:
    """Ensure backward compatibility when session config is missing keys."""

    def test_partial_config_uses_defaults(self):
        """Partial immutable_paths config should use defaults for missing keys."""
        config = {
            "immutable_paths": {
                "patterns": ["custom.md"]
                # Missing override_roles
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            patterns, override_roles = _get_immutable_config()
            assert patterns == ["custom.md"]
            assert override_roles == []  # Default to empty list

    def test_override_roles_without_patterns(self):
        """Can specify override_roles without patterns (uses default patterns)."""
        config = {
            "immutable_paths": {
                "override_roles": ["secretary"]
                # Missing patterns
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            patterns, override_roles = _get_immutable_config()
            assert patterns == ["AGENTS.md", ".claude/agents/"]  # Default
            assert override_roles == ["secretary"]

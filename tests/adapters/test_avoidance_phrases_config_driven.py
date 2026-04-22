"""Regression tests for CZL-YSTAR-HARDCODED-AVOIDANCE-PHRASES.

Verifies that _load_avoidance_phrases() is fully config-driven:
1. yaml does not exist -> empty list -> product does not block
2. yaml exists + phrase match -> product blocks
3. workspace is None -> empty list -> product does not block
"""

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


def _reset_cache():
    """Reset the module-level avoidance phrases cache between tests."""
    from ystar.adapters import hook
    hook._avoidance_phrases_cache = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def reset_avoidance_cache():
    """Ensure each test starts with a clean cache."""
    _reset_cache()
    yield
    _reset_cache()


class TestAvoidancePhrasesConfigDriven:
    """Three required regression cases for config-driven avoidance phrases."""

    def test_yaml_not_exist_returns_empty(self, tmp_path):
        """Case 1: yaml does not exist -> empty list -> product does not block."""
        # Point to a workspace dir that exists but has no yaml
        ws_dir = tmp_path / "fake_labs"
        ws_dir.mkdir()
        (ws_dir / "knowledge" / "shared").mkdir(parents=True)
        (ws_dir / "governance").mkdir(parents=True)
        # Neither knowledge/shared/avoidance_phrases.yaml nor governance/avoidance_phrases.yaml exists

        with patch("ystar.adapters.hook.get_labs_workspace", return_value=ws_dir, create=True):
            # Need to also patch the import inside the function
            with patch.dict("sys.modules", {"ystar.workspace_config": types.ModuleType("ystar.workspace_config")}):
                mod = sys.modules["ystar.workspace_config"]
                mod.get_labs_workspace = lambda: ws_dir  # type: ignore[attr-defined]

                from ystar.adapters.hook import _load_avoidance_phrases
                result = _load_avoidance_phrases()

        assert result == [], f"Expected empty list when yaml missing, got: {result}"

    def test_yaml_exists_returns_phrases(self, tmp_path):
        """Case 2: yaml exists with phrases -> returns those phrases."""
        ws_dir = tmp_path / "fake_labs"
        (ws_dir / "knowledge" / "shared").mkdir(parents=True)

        yaml_content = 'phrases:\n  - "test_phrase_alpha"\n  - "test_phrase_beta"\nstatus_note: "test"\n'
        yaml_path = ws_dir / "knowledge" / "shared" / "avoidance_phrases.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        with patch.dict("sys.modules", {"ystar.workspace_config": types.ModuleType("ystar.workspace_config")}):
            mod = sys.modules["ystar.workspace_config"]
            mod.get_labs_workspace = lambda: ws_dir  # type: ignore[attr-defined]

            from ystar.adapters.hook import _load_avoidance_phrases
            result = _load_avoidance_phrases()

        assert "test_phrase_alpha" in result, f"Expected phrase in list, got: {result}"
        assert "test_phrase_beta" in result, f"Expected phrase in list, got: {result}"
        assert len(result) == 2

    def test_workspace_none_returns_empty(self):
        """Case 3: workspace is None (standalone product install) -> empty list."""
        with patch.dict("sys.modules", {"ystar.workspace_config": types.ModuleType("ystar.workspace_config")}):
            mod = sys.modules["ystar.workspace_config"]
            mod.get_labs_workspace = lambda: None  # type: ignore[attr-defined]

            from ystar.adapters.hook import _load_avoidance_phrases
            result = _load_avoidance_phrases()

        assert result == [], f"Expected empty list when workspace is None, got: {result}"

    def test_governance_fallback_path(self, tmp_path):
        """Bonus: yaml in governance/ fallback works when knowledge/shared/ is missing."""
        ws_dir = tmp_path / "fake_labs"
        (ws_dir / "knowledge" / "shared").mkdir(parents=True)
        (ws_dir / "governance").mkdir(parents=True)
        # Only governance/ yaml exists, not knowledge/shared/
        yaml_content = 'phrases:\n  - "gov_phrase"\nstatus_note: "fallback test"\n'
        (ws_dir / "governance" / "avoidance_phrases.yaml").write_text(yaml_content, encoding="utf-8")

        with patch.dict("sys.modules", {"ystar.workspace_config": types.ModuleType("ystar.workspace_config")}):
            mod = sys.modules["ystar.workspace_config"]
            mod.get_labs_workspace = lambda: ws_dir  # type: ignore[attr-defined]

            from ystar.adapters.hook import _load_avoidance_phrases
            result = _load_avoidance_phrases()

        assert result == ["gov_phrase"], f"Expected governance fallback phrase, got: {result}"

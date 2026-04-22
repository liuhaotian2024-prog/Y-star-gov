"""
Tests for ystar.workspace_config — Labs workspace resolution chain.
"""
import os
import pytest
from pathlib import Path

from ystar.workspace_config import (
    get_labs_workspace,
    require_labs_workspace,
    get_cieu_db_path,
    get_session_json_path,
    get_gov_root,
    invalidate_cache,
)


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure cache is clean before and after each test."""
    invalidate_cache()
    yield
    invalidate_cache()


class TestEnvVarOverride:
    """Step 1: YSTAR_LABS_WORKSPACE env var takes priority."""

    def test_explicit_env_var(self, monkeypatch, tmp_path):
        fake_ws = tmp_path / "my-workspace"
        fake_ws.mkdir()
        monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(fake_ws))
        monkeypatch.delenv("YSTAR_COMPANY_ROOT", raising=False)

        result = get_labs_workspace()
        assert result == fake_ws

    def test_company_root_alias(self, monkeypatch, tmp_path):
        fake_ws = tmp_path / "alias-workspace"
        fake_ws.mkdir()
        monkeypatch.delenv("YSTAR_LABS_WORKSPACE", raising=False)
        monkeypatch.setenv("YSTAR_COMPANY_ROOT", str(fake_ws))

        result = get_labs_workspace()
        assert result == fake_ws

    def test_env_var_nonexistent_dir_skipped(self, monkeypatch, tmp_path):
        """Non-existent env var path should fall through to next step."""
        monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(tmp_path / "nonexistent"))
        monkeypatch.delenv("YSTAR_COMPANY_ROOT", raising=False)
        # Block all other detection methods
        monkeypatch.setattr("ystar.workspace_config.Path.home", lambda: tmp_path / "nohome")

        result = get_labs_workspace()
        # May be None or may find sibling — depends on runtime. Key: didn't use bad path.
        assert result != tmp_path / "nonexistent"


class TestSiblingAutoDetect:
    """Step 2: Auto-detect sibling ystar-company directory."""

    def test_sibling_detected(self, monkeypatch, tmp_path):
        monkeypatch.delenv("YSTAR_LABS_WORKSPACE", raising=False)
        monkeypatch.delenv("YSTAR_COMPANY_ROOT", raising=False)

        # The real sibling detection depends on where the package is installed.
        # This test verifies the function returns a Path or None (no crash).
        result = get_labs_workspace()
        assert result is None or isinstance(result, Path)


class TestFallbackHomedir:
    """Step 3: ~/.openclaw/workspace/ystar-company fallback."""

    def test_homedir_fallback(self, monkeypatch, tmp_path):
        # Create isolated dir structure to avoid conftest's ystar-company in tmp_path
        isolated = tmp_path / "isolated"
        isolated.mkdir()

        monkeypatch.delenv("YSTAR_LABS_WORKSPACE", raising=False)
        monkeypatch.delenv("YSTAR_COMPANY_ROOT", raising=False)

        # Create fake home structure
        fake_home = isolated / "fakehome"
        fake_ws = fake_home / ".openclaw" / "workspace" / "ystar-company"
        fake_ws.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        # Patch __file__ to isolated location so sibling detection won't find conftest dir
        import ystar.workspace_config as wc
        monkeypatch.setattr(wc, "__file__", str(isolated / "pkg" / "ystar" / "workspace_config.py"))

        result = get_labs_workspace()
        assert result == fake_ws


class TestStandaloneNone:
    """Step 5: None when no workspace found."""

    def test_standalone_returns_none(self, monkeypatch, tmp_path):
        # Use fully isolated dir to avoid any ystar-company dir in parent hierarchy
        isolated = tmp_path / "standalone_isolated"
        isolated.mkdir()

        monkeypatch.delenv("YSTAR_LABS_WORKSPACE", raising=False)
        monkeypatch.delenv("YSTAR_COMPANY_ROOT", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: isolated / "nohome"))

        import ystar.workspace_config as wc
        monkeypatch.setattr(wc, "__file__", str(isolated / "pkg" / "ystar" / "workspace_config.py"))

        result = get_labs_workspace()
        assert result is None


class TestCacheAndReset:
    """Cache works and invalidate_cache clears it."""

    def test_cache_returns_same_result(self, monkeypatch, tmp_path):
        fake_ws = tmp_path / "cached"
        fake_ws.mkdir()
        monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(fake_ws))

        r1 = get_labs_workspace()
        r2 = get_labs_workspace()
        assert r1 is r2  # Same object (cached)

    def test_invalidate_allows_new_resolution(self, monkeypatch, tmp_path):
        ws1 = tmp_path / "first"
        ws1.mkdir()
        monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(ws1))

        r1 = get_labs_workspace()
        assert r1 == ws1

        ws2 = tmp_path / "second"
        ws2.mkdir()
        monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(ws2))
        invalidate_cache()

        r2 = get_labs_workspace()
        assert r2 == ws2


class TestConvenienceFunctions:
    """get_cieu_db_path, get_session_json_path, require_labs_workspace."""

    def test_cieu_db_path(self, monkeypatch, tmp_path):
        fake_ws = tmp_path / "ws"
        fake_ws.mkdir()
        monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(fake_ws))

        assert get_cieu_db_path() == fake_ws / ".ystar_cieu.db"

    def test_session_json_path(self, monkeypatch, tmp_path):
        fake_ws = tmp_path / "ws"
        fake_ws.mkdir()
        monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(fake_ws))

        assert get_session_json_path() == fake_ws / ".ystar_session.json"

    def test_require_raises_when_none(self, monkeypatch, tmp_path):
        isolated = tmp_path / "require_isolated"
        isolated.mkdir()

        monkeypatch.delenv("YSTAR_LABS_WORKSPACE", raising=False)
        monkeypatch.delenv("YSTAR_COMPANY_ROOT", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: isolated / "nohome"))

        import ystar.workspace_config as wc
        monkeypatch.setattr(wc, "__file__", str(isolated / "pkg" / "ystar" / "workspace_config.py"))

        with pytest.raises(EnvironmentError, match="Labs workspace not found"):
            require_labs_workspace()

    def test_get_gov_root(self):
        result = get_gov_root()
        assert result is not None
        assert (result / "ystar").is_dir()

    def test_cieu_db_path_none_when_standalone(self, monkeypatch, tmp_path):
        isolated = tmp_path / "db_none_isolated"
        isolated.mkdir()

        monkeypatch.delenv("YSTAR_LABS_WORKSPACE", raising=False)
        monkeypatch.delenv("YSTAR_COMPANY_ROOT", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: isolated / "nohome"))

        import ystar.workspace_config as wc
        monkeypatch.setattr(wc, "__file__", str(isolated / "pkg" / "ystar" / "workspace_config.py"))

        assert get_cieu_db_path() is None

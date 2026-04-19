"""CZL-ARCH-PERF-1: policy bundle cache tests."""
import os, time
from pathlib import Path
from unittest.mock import MagicMock

from ystar.kernel._policy_bundle_cache import get_cached_policy, clear_cache


def _mkmd(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("# Agents\n\n## CEO Agent\n\n### Role\ntest\n")
    return str(p)


def test_cache_disabled_always_compiles(tmp_path, monkeypatch):
    monkeypatch.delenv("YSTAR_POLICY_CACHE", raising=False)
    monkeypatch.setenv("YSTAR_POLICY_CACHE_DIR", str(tmp_path / "cache"))
    md = _mkmd(tmp_path)
    fn = MagicMock(return_value="bundle_v1")
    r1 = get_cached_policy(md, fn)
    r2 = get_cached_policy(md, fn)
    assert r1 == r2 == "bundle_v1"
    assert fn.call_count == 2


def test_cache_hit_skips_compile(tmp_path, monkeypatch):
    monkeypatch.setenv("YSTAR_POLICY_CACHE", "1")
    monkeypatch.setenv("YSTAR_POLICY_CACHE_DIR", str(tmp_path / "cache"))
    md = _mkmd(tmp_path)
    fn = MagicMock(return_value="bundle_v1")
    r1 = get_cached_policy(md, fn)
    r2 = get_cached_policy(md, fn)
    assert r1 == r2 == "bundle_v1"
    assert fn.call_count == 1


def test_cache_invalidated_by_mtime(tmp_path, monkeypatch):
    monkeypatch.setenv("YSTAR_POLICY_CACHE", "1")
    monkeypatch.setenv("YSTAR_POLICY_CACHE_DIR", str(tmp_path / "cache"))
    md = _mkmd(tmp_path)
    fn = MagicMock(side_effect=lambda p: f"bundle_{os.path.getsize(p)}")
    r1 = get_cached_policy(md, fn)
    time.sleep(0.01)
    Path(md).write_text(Path(md).read_text() + "\n### more\n")
    r2 = get_cached_policy(md, fn)
    assert r1 != r2
    assert fn.call_count == 2

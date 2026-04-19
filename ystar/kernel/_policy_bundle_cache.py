"""ystar.kernel._policy_bundle_cache — on-disk compiled policy bundle cache.

Purpose (audience: future engineers): eliminate 14s hook overhead caused
by Policy.from_agents_md recompiling AGENTS.md on every tool_use.

Research: OPA Bundle Persistence pattern. Policies written once (at
AGENTS.md change), read on every decision. Pickled bundle keyed by
(abspath + mtime_ns + size) ensures invalidation on edit.

Synthesis: additive, opt-in via YSTAR_POLICY_CACHE=1 env. Default OFF =
existing Policy.from_agents_md behavior unchanged. On cache miss, falls
back to compile_fn (same as original path).
"""
from __future__ import annotations
import hashlib, logging, os, pickle
from pathlib import Path
from typing import Any, Callable, Optional

_log = logging.getLogger("ystar.kernel.policy_cache")


def _cache_dir() -> Path:
    override = os.environ.get("YSTAR_POLICY_CACHE_DIR")
    return Path(override) if override else (Path.home() / ".ystar" / "policy_cache")


def _cache_enabled() -> bool:
    return os.environ.get("YSTAR_POLICY_CACHE", "").strip() in ("1", "true", "yes", "on")


def _cache_key(agents_md_path: str) -> Optional[str]:
    try:
        abs_path = os.path.abspath(agents_md_path)
        stat = os.stat(abs_path)
        raw = f"{abs_path}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
    except Exception:
        return None


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.pkl"


def get_cached_policy(agents_md_path: str, compile_fn: Callable[[str], Any]) -> Any:
    if not _cache_enabled():
        return compile_fn(agents_md_path)
    key = _cache_key(agents_md_path)
    if key is None:
        return compile_fn(agents_md_path)
    path = _cache_path(key)
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            _log.warning("policy_cache corrupt: %s, recompiling", e)
    bundle = compile_fn(agents_md_path)
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".pkl.tmp")
        with open(tmp, "wb") as f:
            pickle.dump(bundle, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception as e:
        _log.warning("policy_cache store failed: %s", e)
    return bundle


def clear_cache() -> int:
    d = _cache_dir()
    if not d.exists():
        return 0
    n = 0
    for f in d.glob("*.pkl"):
        try:
            f.unlink(); n += 1
        except Exception:
            pass
    return n


__all__ = ["get_cached_policy", "clear_cache"]

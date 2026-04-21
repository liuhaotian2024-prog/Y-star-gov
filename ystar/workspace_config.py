"""
Y*gov workspace configuration — single source of truth for Labs workspace path.

Resolution order (5-step chain):
1. YSTAR_LABS_WORKSPACE env var (explicit override)
2. YSTAR_COMPANY_ROOT env var (alias, backward compat)
3. Auto-detect: walk up from __file__ looking for sibling 'ystar-company' dir
4. Fallback: ~/.openclaw/workspace/ystar-company (if exists)
5. None (no Labs workspace available — product running standalone)

Zero internal ystar imports to avoid circular deps.
"""
import os
from pathlib import Path
from typing import Optional

_cached: Optional[Path] = None
_cache_set: bool = False  # Distinguish cached None from unset


def get_labs_workspace() -> Optional[Path]:
    """Return Labs workspace root, or None if not available."""
    global _cached, _cache_set
    if _cache_set:
        return _cached

    # Step 1: Explicit env var (primary)
    env_val = os.environ.get("YSTAR_LABS_WORKSPACE") or os.environ.get("YSTAR_COMPANY_ROOT")
    if env_val:
        p = Path(env_val)
        if p.is_dir():
            _cached = p
            _cache_set = True
            return _cached

    # Step 2: Auto-detect sibling directory
    try:
        pkg_root = Path(__file__).resolve().parent.parent  # Y-star-gov/
        sibling = pkg_root.parent / "ystar-company"
        if sibling.is_dir():
            _cached = sibling
            _cache_set = True
            return _cached
    except Exception:
        pass

    # Step 3: Default ~/.openclaw/workspace/ystar-company
    default = Path.home() / ".openclaw" / "workspace" / "ystar-company"
    if default.is_dir():
        _cached = default
        _cache_set = True
        return _cached

    # Step 4: Multi-user shared location
    shared = Path("/Users/Shared/ystar-company")
    if shared.is_dir():
        _cached = shared
        _cache_set = True
        return _cached

    # Step 5: None — standalone product mode
    _cached = None
    _cache_set = True
    return None


def require_labs_workspace() -> Path:
    """Return Labs workspace root or raise EnvironmentError."""
    ws = get_labs_workspace()
    if ws is None:
        raise EnvironmentError(
            "Y*gov Labs workspace not found. "
            "Set YSTAR_LABS_WORKSPACE env var or ensure "
            "~/.openclaw/workspace/ystar-company/ exists."
        )
    return ws


def get_cieu_db_path() -> Optional[Path]:
    """Convenience: return path to .ystar_cieu.db in Labs workspace."""
    ws = get_labs_workspace()
    return ws / ".ystar_cieu.db" if ws else None


def get_session_json_path() -> Optional[Path]:
    """Convenience: return path to .ystar_session.json in Labs workspace."""
    ws = get_labs_workspace()
    return ws / ".ystar_session.json" if ws else None


def get_gov_root() -> Optional[Path]:
    """Convenience: return Y-star-gov package root (parent of ystar/)."""
    try:
        return Path(__file__).resolve().parent.parent
    except Exception:
        return None


def invalidate_cache():
    """Reset cached workspace path. Use in tests."""
    global _cached, _cache_set
    _cached = None
    _cache_set = False


__all__ = [
    "get_labs_workspace",
    "require_labs_workspace",
    "get_cieu_db_path",
    "get_session_json_path",
    "get_gov_root",
    "invalidate_cache",
]

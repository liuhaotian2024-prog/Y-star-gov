"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: governance/cieu_store.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.cieu_store import ...

    # New (canonical):
    from ystar.governance.cieu_store import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.governance.cieu_store")

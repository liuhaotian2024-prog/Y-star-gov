"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: governance/omission_engine.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.omission_engine import ...

    # New (canonical):
    from ystar.governance.omission_engine import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.governance.omission_engine")

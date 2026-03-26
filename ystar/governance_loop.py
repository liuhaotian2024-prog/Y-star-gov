"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: governance/governance_loop.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.governance_loop import ...

    # New (canonical):
    from ystar.governance.governance_loop import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.governance.governance_loop")

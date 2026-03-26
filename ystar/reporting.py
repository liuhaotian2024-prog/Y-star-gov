"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: governance/reporting.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.reporting import ...

    # New (canonical):
    from ystar.governance.reporting import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.governance.reporting")

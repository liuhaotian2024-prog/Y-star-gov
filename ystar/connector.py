"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: adapters/connector.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.connector import ...

    # New (canonical):
    from ystar.adapters.connector import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.adapters.connector")

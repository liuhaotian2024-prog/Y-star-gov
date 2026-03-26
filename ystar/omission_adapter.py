"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: adapters/omission_adapter.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.omission_adapter import ...

    # New (canonical):
    from ystar.adapters.omission_adapter import ...
"""
# This shim redirects the module to the canonical implementation,
# including private names (e.g. _extract_constraints_from_text).
import importlib as _il
import sys as _sys

_canonical = _il.import_module("ystar.adapters.omission_adapter")
_sys.modules[__name__] = _canonical

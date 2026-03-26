"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: kernel/prefill.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.prefill import ...

    # New (canonical):
    from ystar.kernel.prefill import ...
"""
# This shim redirects the module to the canonical implementation,
# including private names (e.g. _extract_constraints_from_text).
import importlib as _il
import sys as _sys

_canonical = _il.import_module("ystar.kernel.prefill")
_sys.modules[__name__] = _canonical

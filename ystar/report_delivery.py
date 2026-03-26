"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: adapters/report_delivery.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.report_delivery import ...

    # New (canonical):
    from ystar.adapters.report_delivery import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.adapters.report_delivery")

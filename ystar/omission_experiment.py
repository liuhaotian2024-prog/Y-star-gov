"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: products/omission_experiment.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.omission_experiment import ...

    # New (canonical):
    from ystar.products.omission_experiment import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.products.omission_experiment")

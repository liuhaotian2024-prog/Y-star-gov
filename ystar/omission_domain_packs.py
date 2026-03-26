"""
Backward-compatibility alias — DO NOT USE IN NEW CODE.

Canonical location: domains/omission_domain_packs.py

New projects should import directly from the canonical path::

    # Old (deprecated):
    from ystar.omission_domain_packs import ...

    # New (canonical):
    from ystar.domains.omission_domain_packs import ...
"""
import importlib as _il
import sys as _sys
_sys.modules[__name__] = _il.import_module("ystar.domains.omission_domain_packs")

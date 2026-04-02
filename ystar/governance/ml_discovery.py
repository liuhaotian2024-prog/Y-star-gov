# STATUS: LEGACY — not on the main governance runtime path
"""
ystar.governance.ml_discovery  —  Parameter Discovery
Physical sub-module of metalearning.py (was 2858 lines → 6 focused modules).
Canonical import: from ystar.governance.ml_discovery import ...
"""
from ystar.governance.metalearning import (
    ParameterHint, discover_parameters, DomainContext,
)

__all__ = ['ParameterHint', 'discover_parameters', 'DomainContext']

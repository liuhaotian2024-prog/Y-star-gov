# STATUS: LEGACY — not on the main governance runtime path
"""
ystar.governance.ml_loop  —  Learning Loop
Physical sub-module of metalearning.py (was 2858 lines → 6 focused modules).
Canonical import: from ystar.governance.ml_loop import ...
"""
from ystar.governance.metalearning import (
    learn, DimensionDiscovery, YStarLoop, learn_from_jsonl,
)

__all__ = ['learn', 'DimensionDiscovery', 'YStarLoop', 'learn_from_jsonl']

"""
K9Audit v2 Adapter — Y*gov integration for K9 daily patrol rules.

Y* = K9 v2 Rules 6-10 enforcement
Xt = K9Audit legacy read-only (CLAUDE.md)
U = (1) active agent marker (2) new module rules_6_10.py (3) hook CIEU check (4) inline test (5) commit
Yt+1 = k9_adapter live + hook CIEU marker check enforced
Rt+1=0 = 2 commit + test pass + CIEU events ≥ 12

CIEU_LAYER_0: module init, K9 adapter namespace established.
"""
from ystar.governance.k9_adapter.rules_6_10 import (
    check_orphan_process,
    check_untracked_critical,
    check_hardcoded_path,
    check_fail_open_surge,
    check_multi_clone,
    K9Finding,
)

__all__ = [
    "check_orphan_process",
    "check_untracked_critical",
    "check_hardcoded_path",
    "check_fail_open_surge",
    "check_multi_clone",
    "K9Finding",
]

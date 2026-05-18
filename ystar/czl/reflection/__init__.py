"""
ystar.czl.reflection — v3.5 "coach" layer.

Two TRULY NEW capabilities (not ported from v2.x / v21):
  - cluster.py: failure clustering — N failures sharing one bottom-frame
                file:line are grouped, model is told "ONE root cause".
  - repetition.py: failure fingerprint — last 2 iters identical →
                   model is told "same approach won't work".

The Y*gov Hook 4-field structure (reason / instruction / reference /
example) is NOT new — that's a port. Lives on VerifierResult directly
(see verifiers.base). This reflection package only adds the cross-iter
and cross-failure inference.

ReflectionAnalyzer in analyzer.py composes both signals into one META
block that loop._format_feedback_for_retry prepends to the next prompt.
"""
from ystar.czl.reflection.cluster import (
    FailureCluster,
    cluster_pytest_failures,
    render_cluster_text,
)
# v5.0 Task E: repetition + no_progress modules retired.
#   - v3.5 repetition META → replaced by ResidualLoopEngine._oscillation_detected
#   - v3.8 no_progress (is_no_progress_v3_8 / adaptive_no_progress_window /
#     query_safeguard_wall_cap) → replaced by RLE's max_iterations + oscillation
# These imports are intentionally removed. Files retained on disk for git
# history; not loaded by the runtime.
from ystar.czl.reflection.transitions import (
    TransitionTracker,
    extract_test_status,
    parse_pytest_v_outcomes,
    render_regression_meta,
)
from ystar.czl.reflection.analyzer import (
    ReflectionAnalyzer,
    ReflectionMeta,
)

__all__ = [
    "FailureCluster",
    "cluster_pytest_failures",
    "render_cluster_text",
    "TransitionTracker",
    "extract_test_status",
    "parse_pytest_v_outcomes",
    "render_regression_meta",
    "ReflectionAnalyzer",
    "ReflectionMeta",
]

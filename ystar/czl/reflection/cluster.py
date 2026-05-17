"""
ystar.czl.reflection.cluster — v3.5 T3 failure clustering.

Parse pytest --tb=short stdout, group every FAILED test by its bottom-frame
(file, lineno, function_name). When >= 2 tests share the same bottom frame,
emit a META block telling the model "this is ONE root cause, not N".

Solves the v3.4 sanity blocker: gemma 4B saw 3 failing tests all tracing
to the `_create_file` fixture but couldn't connect the dots across the
3 separate test reports. Cluster surfaces that single shared root.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FailureCluster:
    file: str
    lineno: int
    function_name: Optional[str]
    error_type: Optional[str]
    test_names: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.test_names)


# ---------------------------------------------------------------------------
# pytest --tb=short / --tb=long output parser
# ---------------------------------------------------------------------------

# Each FAILED test's block starts with a header like:
#   ___________________________ test_load_records_success __________________________
# We use a relaxed pattern that tolerates trailing whitespace and varying
# underscore widths (5+).
_TEST_BLOCK_HEADER_RE = re.compile(
    r"^_{5,}\s*(?P<name>[A-Za-z_][A-Za-z0-9_:.\[\]\-]*?)\s*_{5,}\s*$",
    re.MULTILINE,
)

# Inside a test's body, each frame is of the form:
#   path/to/file.py:18: in func_name
# (pytest --tb=short uses this; --tb=long is similar but with more context.)
_FRAME_RE = re.compile(
    r"^(?P<file>[^\s:]+(?:\.py)?):(?P<lineno>\d+):\s+in\s+(?P<func>\S+)\s*$",
    re.MULTILINE,
)

# Error type at the end of a frame block:
#   E   TypeError: write() argument must be str, not list
_ERROR_RE = re.compile(
    r"^E\s+(?P<err_type>\w+(?:Error|Exception|Warning))(?::\s+(?P<msg>.*))?\s*$",
    re.MULTILINE,
)


def parse_pytest_failures(stdout: str) -> List[Dict[str, Any]]:
    """Parse pytest stdout. Returns one dict per FAILED test with the
    BOTTOM frame (the deepest call in the traceback — that's where the
    error actually occurred, vs the test_X frame which is just the entry
    point).

    Returns: [{test_name, file, lineno, function_name, error_type,
               error_msg}, ...]
    """
    if not stdout:
        return []
    # Extract the FAILURES section if it's wrapped in a delimiter; else use whole text.
    fail_section_match = re.search(
        r"={5,}\s*FAILURES\s*={5,}(.*?)(?:={5,}\s*(?:short\s+)?test\s+summary|\Z)",
        stdout, re.DOTALL,
    )
    section = fail_section_match.group(1) if fail_section_match else stdout

    # Split section into test-block chunks by header.
    headers = list(_TEST_BLOCK_HEADER_RE.finditer(section))
    out: List[Dict[str, Any]] = []
    for i, m in enumerate(headers):
        name = m.group("name").strip()
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(section)
        body = section[start:end]
        # Frames: take the LAST one before an error marker. That's the bottom frame.
        frames = list(_FRAME_RE.finditer(body))
        if not frames:
            continue
        bottom = frames[-1]
        err_match = _ERROR_RE.search(body, pos=bottom.end())
        out.append({
            "test_name": name,
            "file": bottom.group("file"),
            "lineno": int(bottom.group("lineno")),
            "function_name": bottom.group("func"),
            "error_type": err_match.group("err_type") if err_match else None,
            "error_msg": (err_match.group("msg") or "").strip() if err_match else "",
        })
    return out


def cluster_pytest_failures(pytest_stdout: str) -> List[FailureCluster]:
    """Top-level: parse stdout, group by (file, lineno, function_name).
    Sort by descending count so the dominant cluster is first.
    """
    failures = parse_pytest_failures(pytest_stdout)
    if not failures:
        return []
    by_key: Dict[tuple, FailureCluster] = {}
    for f in failures:
        key = (f["file"], f["lineno"], f["function_name"])
        if key not in by_key:
            by_key[key] = FailureCluster(
                file=f["file"], lineno=f["lineno"],
                function_name=f["function_name"],
                error_type=f["error_type"],
            )
        by_key[key].test_names.append(f["test_name"])
    return sorted(by_key.values(), key=lambda c: -c.count)


# ---------------------------------------------------------------------------
# META rendering
# ---------------------------------------------------------------------------

def render_cluster_text(clusters: List[FailureCluster],
                        min_cluster_size: int = 2) -> Optional[str]:
    """Render a META block for clusters with count >= threshold. Returns
    None if no cluster meets the threshold.
    """
    qualified = [c for c in clusters if c.count >= min_cluster_size]
    if not qualified:
        return None
    lines: List[str] = ["META (cluster signal):"]
    for c in qualified[:3]:  # cap at top 3 clusters
        fn = c.function_name or "<unknown>"
        sample = c.test_names[:3]
        more = f" (+{len(c.test_names) - 3} more)" if len(c.test_names) > 3 else ""
        err = f"  Common error: {c.error_type}" if c.error_type else ""
        lines.append(
            f"  {c.count} failing tests all trace back to {c.file}:{c.lineno} (in `{fn}`)."
        )
        lines.append(f"  Tests: {', '.join(sample)}{more}")
        if err:
            lines.append(err)
        lines.append(
            f"  This is ONE root cause, not {c.count}. Fix the issue at "
            f"{c.file}:{c.lineno} and the {c.count} failing tests will all "
            f"pass together."
        )
        lines.append("")
    return "\n".join(lines).rstrip()

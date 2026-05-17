"""
ast_distance_verifier.py — AST structural distance between candidate
trial's test files and the arm-A reference test files.

Lives in the quality_assessment phase (NOT in the CZL inner loop). Reads
candidate post_state_files vs reference post_state_files, computes a
normalized tree-edit-distance via the `zss` library, returns a signal
that informs the iteration_confidence weighting downstream.

This is a weighting signal, NOT a gating verifier — passed=True always,
but details.distance_ratio is read by the agreement-rate calculator.
"""
from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Tuple

try:
    import zss
except ImportError:  # pragma: no cover
    zss = None  # type: ignore


# === AST → zss tree conversion ==============================================

_IGNORED_NODE_TYPES = (ast.Load, ast.Store, ast.Del, ast.AugLoad, ast.AugStore,
                       ast.Param)


def _ast_to_zss(node: ast.AST) -> "zss.Node":
    """Convert an ast.AST node into a zss.Node tree. Node labels are the
    AST class name. Docstrings (first Expr+Constant in a body) and
    contextual decoration nodes (Load/Store) are stripped to focus the
    distance metric on structural code shape rather than syntactic chaff.
    """
    if zss is None:
        raise ImportError("zss is required for AST distance — pip install zss")
    z = zss.Node(type(node).__name__)
    body = list(ast.iter_child_nodes(node))
    # strip leading docstring expression in function/class bodies
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
    for child in body:
        if isinstance(child, _IGNORED_NODE_TYPES):
            continue
        z.addkid(_ast_to_zss(child))
    return z


def _count_nodes(z: "zss.Node") -> int:
    n = 1
    for c in zss.Node.get_children(z):
        n += _count_nodes(c)
    return n


# === collect TEST files from a trial post_state ============================

def _is_test_file(rel_path: str) -> bool:
    base = os.path.basename(rel_path)
    return (base.startswith("test_") and base.endswith(".py")) or base == "conftest.py"


def _collect_test_source(post_state_files: Dict[str, str]) -> str:
    """Concatenate all test_*.py file content into one canonical source
    blob for AST distance comparison. Order = sorted relative paths.
    """
    parts: List[str] = []
    for rel in sorted(post_state_files.keys()):
        if not _is_test_file(rel):
            continue
        parts.append(post_state_files[rel])
    return "\n\n".join(parts)


# === public API =============================================================

def ast_distance_ratio(
    reference_files: Dict[str, str],
    candidate_files: Dict[str, str],
) -> Dict[str, Any]:
    """Compute AST tree-edit-distance ratio = dist / max(ref_size, cand_size).

    Returns dict with keys:
      - ratio (float, 0 = identical, 1.0 ≈ completely different)
      - distance (int, raw zss tree-edit cost)
      - ref_node_count (int)
      - cand_node_count (int)
      - structural_drift (bool, True if ratio > 0.5)
      - error (optional string)
    """
    out: Dict[str, Any] = {
        "ratio": None, "distance": None,
        "ref_node_count": 0, "cand_node_count": 0,
        "structural_drift": False, "error": None,
    }
    if zss is None:
        out["error"] = "zss not installed"
        return out
    ref_src = _collect_test_source(reference_files)
    cand_src = _collect_test_source(candidate_files)
    if not ref_src.strip() or not cand_src.strip():
        out["error"] = "no test files in reference or candidate"
        return out
    try:
        ref_tree = ast.parse(ref_src)
        cand_tree = ast.parse(cand_src)
    except SyntaxError as e:
        out["error"] = f"SyntaxError: {e}"
        return out
    try:
        ref_z = _ast_to_zss(ref_tree)
        cand_z = _ast_to_zss(cand_tree)
        ref_n = _count_nodes(ref_z)
        cand_n = _count_nodes(cand_z)
        out["ref_node_count"] = ref_n
        out["cand_node_count"] = cand_n
        dist = zss.simple_distance(ref_z, cand_z)
    except Exception as e:  # pragma: no cover
        out["error"] = f"zss compute failed: {type(e).__name__}: {e}"
        return out
    out["distance"] = int(dist)
    denom = max(ref_n, cand_n)
    ratio = (dist / denom) if denom > 0 else 0.0
    out["ratio"] = round(ratio, 3)
    out["structural_drift"] = ratio > 0.5
    return out

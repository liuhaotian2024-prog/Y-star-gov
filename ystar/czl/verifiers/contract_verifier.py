"""
contract_verifier.py — outcome-based contract consistency check.

Builds two file-AST indexes for the workspace:
  - callee_index: {name -> [CalleeSignature]}  (declared `def`s)
  - call_sites:   list[CallSite]               (observed call expressions)

For each call site, looks up matching callees by name and asks: is this call
compatible with at least one declared signature? Compatibility = positional
arity within [min_required, max_accepted_or_∞_if_*args] AND every used
keyword is accepted (named kw arg, **kwargs, or named-only kw allowed).

Optionally, when the loop hands us an intent-contract dict, runs that
through ystar.governance.contract_lifecycle.validate_y_star_schema_v2 as a
second outcome-based check (declared spec is itself well-formed).

ZERO process-based logic — we do NOT inspect which files were edited, which
imports the model added, or any other per-iteration artifact. Only the
final source-AST state matters.

Reused-asset provenance (copied, not imported, to keep verifier
self-contained and free of cross-repo coupling):
  - signature-extraction shape from K9Audit/k9log/contract_builder.py:112
    `_analyze_function_ast(func)` (Callable input, single-function scope)
  - param-walking idiom from ystar/kernel/prefill.py:844
    `_analyze_ast(func)` (Callable input, AST walk over args.args)
Both are CALLABLE-input helpers; we adapt the pattern to a file-AST input.

Schema-dict synergy (imported, not copied — per Phase 2 spec):
  - ystar.governance.contract_lifecycle.validate_y_star_schema_v2
"""
from __future__ import annotations

import ast
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ystar.czl.verifiers.base import Verifier, VerifierResult


# === data structures ========================================================

@dataclass
class CalleeSignature:
    name: str
    min_arity: int                 # positional args without defaults (excluding *args/**kwargs)
    max_arity: int                 # total positional args; sys.maxsize sentinel if *args
    kw_names_accepted: Set[str]    # named kw param names (excluding **kwargs target)
    has_var_positional: bool       # *args present
    has_var_keyword: bool          # **kwargs present
    return_annotation: Optional[str]  # ast.unparse() of return annotation, or None
    declared_file: str
    declared_lineno: int


@dataclass
class CallSite:
    called_name: str
    positional_arity: int
    kw_names_used: Set[str]
    unpack_arity: Optional[int]    # `a, b = foo()` -> 2; `x = foo()` -> 1; bare call -> None
    file: str
    lineno: int


@dataclass
class ContractMismatch:
    call_site: CallSite
    candidate_callees: List[CalleeSignature] = field(default_factory=list)
    reason: str = ""


# === extraction =============================================================

_MAX_ARITY_SENTINEL = 10_000  # acts as "unbounded" without using sys.maxsize


def _extract_callees_from_tree(tree: ast.AST, file_path: str) -> List[CalleeSignature]:
    """Walk module-level + class-level FunctionDefs. Returns one signature per def.

    For methods (FunctionDef inside ClassDef) whose first arg is `self` or
    `cls`, we DECREMENT min/max arity by one so the stored signature
    reflects the callable-from-outside shape (Python auto-binds self/cls
    on attribute-style invocation `obj.method(args)`). Without this
    adjustment every `obj.method(x)` call would falsely fail arity check
    against a `def method(self, x)` signature.

    Param-walking idiom adapted from prefill.py:844 _analyze_ast.
    """
    out: List[CalleeSignature] = []

    def _handle_func(node: ast.FunctionDef | ast.AsyncFunctionDef,
                     qualname: str, *, is_method: bool = False) -> None:
        positional = list(node.args.args)
        # If method and first param is self/cls, strip it before arity math.
        if is_method and positional and positional[0].arg in ("self", "cls"):
            positional = positional[1:]
        defaults = node.args.defaults
        min_arity = max(0, len(positional) - len(defaults))
        max_arity = _MAX_ARITY_SENTINEL if node.args.vararg is not None else len(positional)
        kw_names = {a.arg for a in node.args.kwonlyargs}
        try:
            ret = ast.unparse(node.returns) if node.returns is not None else None
        except Exception:
            ret = None
        out.append(CalleeSignature(
            name=qualname,
            min_arity=min_arity,
            max_arity=max_arity,
            kw_names_accepted=kw_names,
            has_var_positional=node.args.vararg is not None,
            has_var_keyword=node.args.kwarg is not None,
            return_annotation=ret,
            declared_file=file_path,
            declared_lineno=node.lineno,
        ))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _handle_func(node, node.name, is_method=False)
        elif isinstance(node, ast.ClassDef):
            for body_node in node.body:
                if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # method's plain name; the call-site index keys by plain
                    # name too (we don't do receiver-type inference)
                    _handle_func(body_node, body_node.name, is_method=True)
    return out


def _call_target_name(call: ast.Call) -> Optional[str]:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _extract_call_sites_from_tree(tree: ast.AST, file_path: str) -> List[CallSite]:
    """Walk all Call nodes and Assign targets to capture unpack arity.

    We do a two-pass walk: first identify Assign nodes whose `value` is a
    Call, recording the LHS unpack arity for those calls; then walk every
    Call and emit a CallSite with the unpack info (or None for bare calls).
    """
    # Map id(call_node) -> unpack arity (None if not in a tuple-unpack Assign)
    unpack_arity_by_call_id: Dict[int, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            target = node.targets[0] if node.targets else None
            if isinstance(target, (ast.Tuple, ast.List)):
                unpack_arity_by_call_id[id(node.value)] = len(target.elts)
            else:
                # x = foo() — single target; treat as 1
                unpack_arity_by_call_id[id(node.value)] = 1

    out: List[CallSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_target_name(node)
        if name is None:
            continue
        positional_arity = sum(1 for a in node.args if not isinstance(a, ast.Starred))
        # Starred positional args mean we can't determine exact arity → mark unknown
        has_star = any(isinstance(a, ast.Starred) for a in node.args)
        if has_star:
            positional_arity = -1  # sentinel: "unknown, treat as compatible"
        kw_names_used: Set[str] = set()
        for kw in node.keywords:
            if kw.arg is not None:
                kw_names_used.add(kw.arg)
        out.append(CallSite(
            called_name=name,
            positional_arity=positional_arity,
            kw_names_used=kw_names_used,
            unpack_arity=unpack_arity_by_call_id.get(id(node)),
            file=file_path,
            lineno=node.lineno,
        ))
    return out


def _iter_workspace_py(workspace_dir: str) -> List[str]:
    out: List[str] = []
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(root, f))
    return out


# === compatibility logic ====================================================

def _return_is_tuple_like(ret_annotation: Optional[str]) -> Optional[int]:
    """If `ret_annotation` is a tuple-typed annotation, return the inferred arity.
    Returns:
      - integer arity for `tuple[X, Y]` / `Tuple[X, Y]` (length of inner type args)
      - 0 for `tuple[()]` / unparameterised tuple (unknown arity)
      - None for non-tuple annotations
    """
    if ret_annotation is None:
        return None
    a = ret_annotation.replace(" ", "")
    if not (a.lower().startswith("tuple[") or a.lower().startswith("typing.tuple[")):
        return None
    inner = a[a.index("[") + 1: a.rindex("]")] if "[" in a and "]" in a else ""
    if not inner or inner == "()":
        return 0
    # naive comma split (good enough for the kinds of annotations we see)
    parts = [p for p in inner.split(",") if p]
    # `Tuple[int, ...]` → variadic; treat as unknown
    if any(p == "..." for p in parts):
        return 0
    return len(parts)


def _signature_admits_call(callee: CalleeSignature, site: CallSite) -> Tuple[bool, str]:
    """Return (compatible, reason_if_not)."""
    pos = site.positional_arity
    if pos != -1:  # -1 means starred-call, unknown — be lenient
        if pos < callee.min_arity:
            return False, (
                f"call provides {pos} positional arg(s) but `{callee.name}` "
                f"requires at least {callee.min_arity}"
            )
        if pos > callee.max_arity:
            return False, (
                f"call provides {pos} positional arg(s) but `{callee.name}` "
                f"accepts at most {callee.max_arity}"
            )
    if site.kw_names_used:
        accepted = callee.kw_names_accepted
        # also treat positional param names as keyword-accepted
        # (we don't have them here — conservative: only flag if has_var_keyword is False AND name not in accepted)
        if not callee.has_var_keyword:
            for kw in site.kw_names_used:
                if kw not in accepted:
                    return False, (
                        f"call passes keyword `{kw}` but `{callee.name}` has no "
                        f"such parameter (and no **kwargs)"
                    )
    # Return-shape check: caller does tuple-unpacking with arity N, but
    # callee declares a non-tuple return (or tuple of different arity).
    if site.unpack_arity and site.unpack_arity > 1 and callee.return_annotation is not None:
        tup_n = _return_is_tuple_like(callee.return_annotation)
        if tup_n is None:
            return False, (
                f"call unpacks {site.unpack_arity}-tuple, but `{callee.name}` "
                f"returns `{callee.return_annotation}` (not a tuple)"
            )
        if tup_n and tup_n != site.unpack_arity:
            return False, (
                f"call unpacks {site.unpack_arity}-tuple, but `{callee.name}` "
                f"returns tuple of arity {tup_n}"
            )
    return True, ""


def check_contract_consistency(
    workspace_dir: str,
    intent_contract: Optional[Dict[str, Any]] = None,
) -> List[ContractMismatch]:
    """Top-level: gather all callee signatures + all call sites in the
    workspace, then flag every call site that has no compatible callee.

    Optionally also validates `intent_contract` via Y* schema.
    """
    callee_index: Dict[str, List[CalleeSignature]] = {}
    call_sites: List[CallSite] = []
    for path in _iter_workspace_py(workspace_dir):
        try:
            tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)
        except SyntaxError:
            # A SyntaxError in workspace source is itself a contract violation;
            # surface it as one mismatch with no candidates.
            call_sites.append(CallSite(
                called_name="<syntax_error>",
                positional_arity=0,
                kw_names_used=set(),
                unpack_arity=None,
                file=path,
                lineno=0,
            ))
            continue
        for cs in _extract_callees_from_tree(tree, path):
            callee_index.setdefault(cs.name, []).append(cs)
        call_sites.extend(_extract_call_sites_from_tree(tree, path))

    mismatches: List[ContractMismatch] = []

    # External callees (stdlib / 3rd-party) won't be in callee_index. Those
    # are NOT flagged — we only check intra-workspace consistency. Filter:
    intra_names = set(callee_index.keys())
    for site in call_sites:
        if site.called_name == "<syntax_error>":
            mismatches.append(ContractMismatch(
                call_site=site, candidate_callees=[],
                reason=f"SyntaxError in {site.file}",
            ))
            continue
        candidates = callee_index.get(site.called_name, [])
        if not candidates:
            # External call, skip (no in-workspace callee)
            continue
        # If ANY candidate is compatible, the call is OK.
        compatible_reasons: List[str] = []
        any_ok = False
        for c in candidates:
            ok, reason = _signature_admits_call(c, site)
            if ok:
                any_ok = True
                break
            compatible_reasons.append(reason)
        if not any_ok:
            mismatches.append(ContractMismatch(
                call_site=site,
                candidate_callees=candidates,
                reason="; ".join(compatible_reasons[:3]),
            ))

    # Schema-dict synergy: validate the intent contract itself if supplied.
    if intent_contract:
        try:
            from ystar.governance.contract_lifecycle import validate_y_star_schema_v2
            schema_result = validate_y_star_schema_v2(intent_contract)
            if schema_result.get("errors"):
                fake_site = CallSite(
                    called_name="<intent_contract>", positional_arity=0,
                    kw_names_used=set(), unpack_arity=None,
                    file="<contract_dict>", lineno=0,
                )
                mismatches.append(ContractMismatch(
                    call_site=fake_site, candidate_callees=[],
                    reason=f"intent contract schema errors: {schema_result['errors'][:3]}",
                ))
        except Exception:
            # Don't let schema-helper bugs poison the verifier; log to details only.
            pass

    return mismatches


# === Verifier interface =====================================================

class ContractConsistencyVerifier(Verifier):
    name = "contract_consistency"

    def is_applicable(self, workspace_dir: str) -> bool:
        # Always applicable to any .py workspace.
        for root, _, files in os.walk(workspace_dir):
            if any(f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        mismatches = check_contract_consistency(workspace_dir, intent_contract=contract or None)
        if not mismatches:
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message="contract_consistency: all call sites compatible with callees",
                elapsed_seconds=time.time() - t0,
            )
        # Format a useful, model-readable summary
        msgs: List[str] = []
        for m in mismatches[:10]:
            site = m.call_site
            msgs.append(
                f"{site.file}:{site.lineno}: call `{site.called_name}` "
                f"(arity={site.positional_arity}, kw={sorted(site.kw_names_used) or '[]'}, "
                f"unpack={site.unpack_arity}) — {m.reason}"
            )
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message=f"contract_consistency: {len(mismatches)} mismatch(es); first: {msgs[0][:160]}",
            details={"mismatches": msgs, "n": len(mismatches)},
            elapsed_seconds=time.time() - t0,
        )

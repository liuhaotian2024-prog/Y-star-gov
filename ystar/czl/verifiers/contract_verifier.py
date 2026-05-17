"""
contract_verifier.py — outcome-based contract consistency check (v3.3).

Builds two file-AST indexes for the workspace:
  - callee_index: {name -> [CalleeSignature]}  (declared `def`s)
  - call_sites:   list[CallSite]               (observed call expressions)

For each call site, looks up matching callees by name and asks: is this call
compatible with at least one declared signature?

v3.3 changes (from v3.2):
  - **A.1**: Replaced single `unpack=N` field with four explicit counts:
      positional_count / keyword_count / starred_count / double_starred_count
    (call.args / call.keywords are walked as in standard ast practice;
     the old `unpack=1` for ordinary single-target assigns was misleading.)
  - **A.2**: When starred_count > 0 OR double_starred_count > 0, the call's
    arity is not statically determinable. Skip from mismatch list (do NOT
    emit a false positive); record to details.skipped_unpacking_calls.
  - **A.3**: Mismatch reason rendered as multi-line natural-language prose
    including the call source, def-site, declared signature, docstring
    first line, and a concrete suggested fix. Stored as `reason_natural`
    on ContractMismatch; the verifier's VerifierResult fills BOTH
    `message` (structured-for-large-model) and `message_natural`
    (prose-for-small-model).
  - **D.2**: VerifierResult.message_natural set.
  - **E.2**: class metadata set (applies_to_tasks, min_model_capacity, ...).

ZERO process-based logic — we do NOT inspect which files were edited.
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
    max_arity: int                 # total positional args; _MAX_ARITY_SENTINEL if *args
    kw_names_accepted: Set[str]    # named kw param names (excluding **kwargs target)
    has_var_positional: bool       # *args present
    has_var_keyword: bool          # **kwargs present
    return_annotation: Optional[str]  # ast.unparse() of return annotation, or None
    declared_file: str
    declared_lineno: int
    param_names: Tuple[str, ...] = ()       # v3.3: ordered positional param names (post self/cls strip)
    docstring_first_line: Optional[str] = None  # v3.3: for human-readable error messages


@dataclass
class CallSite:
    called_name: str
    # v3.3 split: four explicit counts. positional_count = args without `*`;
    # starred_count = args using `*` (e.g. f(*args)); keyword_count = named
    # kwargs (f(x=1)); double_starred_count = `**kwargs` calls (f(**d)).
    positional_count: int
    keyword_count: int
    starred_count: int
    double_starred_count: int
    kw_names_used: Set[str]
    lhs_unpack_arity: Optional[int]    # LHS unpack arity (`a, b = foo()` -> 2; bare → None)
    file: str
    lineno: int
    call_source: str = ""              # v3.3: ast.unparse of the call expression (for human msg)


@dataclass
class ContractMismatch:
    call_site: CallSite
    candidate_callees: List[CalleeSignature] = field(default_factory=list)
    reason: str = ""                       # structured (for large model)
    reason_natural: str = ""               # v3.3: multi-line prose (for small model)


# === extraction =============================================================

_MAX_ARITY_SENTINEL = 10_000  # acts as "unbounded" without using sys.maxsize


def _extract_callees_from_tree(tree: ast.AST, file_path: str) -> List[CalleeSignature]:
    """Walk module-level + class-level FunctionDefs. Returns one signature per def."""
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
        param_names = tuple(a.arg for a in positional)
        # docstring_first_line via ast.get_docstring (returns clean text or None)
        doc = ast.get_docstring(node)
        doc_first = doc.split("\n", 1)[0].strip() if doc else None
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
            param_names=param_names,
            docstring_first_line=doc_first,
        ))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _handle_func(node, node.name, is_method=False)
        elif isinstance(node, ast.ClassDef):
            for body_node in node.body:
                if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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
    """Walk all Call nodes and Assign targets to capture LHS unpack arity.

    v3.3: separates the 4 call-side counts (positional / keyword / starred /
    double_starred) so downstream logic can correctly skip statically-
    undeterminable cases without confusing them with LHS unpack arity.
    """
    # Map id(call_node) -> LHS unpack arity (None if not in a tuple-unpack Assign)
    lhs_unpack_by_call_id: Dict[int, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            target = node.targets[0] if node.targets else None
            if isinstance(target, (ast.Tuple, ast.List)):
                lhs_unpack_by_call_id[id(node.value)] = len(target.elts)
            else:
                # Single-target assign — NOT a tuple-unpack situation.
                # v3.2's confused convention of recording this as `unpack=1`
                # made `f(a, b)` look like unpacking; we now leave this None.
                pass

    out: List[CallSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_target_name(node)
        if name is None:
            continue
        # v3.3 — explicit 4-count breakdown
        positional_count = sum(1 for a in node.args if not isinstance(a, ast.Starred))
        starred_count = sum(1 for a in node.args if isinstance(a, ast.Starred))
        keyword_count = sum(1 for kw in node.keywords if kw.arg is not None)
        double_starred_count = sum(1 for kw in node.keywords if kw.arg is None)
        kw_names_used: Set[str] = {kw.arg for kw in node.keywords if kw.arg is not None}
        try:
            call_source = ast.unparse(node)
        except Exception:
            call_source = f"{name}(…)"
        out.append(CallSite(
            called_name=name,
            positional_count=positional_count,
            keyword_count=keyword_count,
            starred_count=starred_count,
            double_starred_count=double_starred_count,
            kw_names_used=kw_names_used,
            lhs_unpack_arity=lhs_unpack_by_call_id.get(id(node)),
            file=file_path,
            lineno=node.lineno,
            call_source=call_source,
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
    """If `ret_annotation` is a tuple-typed annotation, return the inferred arity."""
    if ret_annotation is None:
        return None
    a = ret_annotation.replace(" ", "")
    if not (a.lower().startswith("tuple[") or a.lower().startswith("typing.tuple[")):
        return None
    inner = a[a.index("[") + 1: a.rindex("]")] if "[" in a and "]" in a else ""
    if not inner or inner == "()":
        return 0
    parts = [p for p in inner.split(",") if p]
    if any(p == "..." for p in parts):
        return 0
    return len(parts)


def _signature_admits_call(callee: CalleeSignature, site: CallSite) -> Tuple[bool, str]:
    """Return (compatible, reason_if_not). v3.3 uses split call-site fields."""
    pos = site.positional_count
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
        accepted = callee.kw_names_accepted | set(callee.param_names)
        if not callee.has_var_keyword:
            for kw in site.kw_names_used:
                if kw not in accepted:
                    return False, (
                        f"call passes keyword `{kw}` but `{callee.name}` has no "
                        f"such parameter (and no **kwargs)"
                    )
    # LHS-unpack return-shape check
    if site.lhs_unpack_arity and site.lhs_unpack_arity > 1 and callee.return_annotation is not None:
        tup_n = _return_is_tuple_like(callee.return_annotation)
        if tup_n is None:
            return False, (
                f"call unpacks {site.lhs_unpack_arity}-tuple, but `{callee.name}` "
                f"returns `{callee.return_annotation}` (not a tuple)"
            )
        if tup_n and tup_n != site.lhs_unpack_arity:
            return False, (
                f"call unpacks {site.lhs_unpack_arity}-tuple, but `{callee.name}` "
                f"returns tuple of arity {tup_n}"
            )
    return True, ""


def _render_natural_mismatch(site: CallSite,
                             best_candidate: CalleeSignature,
                             structured_reason: str) -> str:
    """v3.3 A.3: render multi-line Chinese prose for the mismatch."""
    # Construct the declared signature display: name(param1, param2, ...)
    sig_params = list(best_candidate.param_names)
    if best_candidate.has_var_positional:
        sig_params.append("*args")
    if best_candidate.kw_names_accepted:
        for kw in sorted(best_candidate.kw_names_accepted):
            sig_params.append(kw)
    if best_candidate.has_var_keyword:
        sig_params.append("**kwargs")
    sig_display = f"{best_candidate.name}({', '.join(sig_params)})"

    # Choose the suggested fix
    fix_hint = ""
    if site.positional_count > best_candidate.max_arity:
        diff = site.positional_count - best_candidate.max_arity
        if diff == 1:
            fix_hint = "可能的修正: 删除多出的 1 个参数; 或检查你是否调用了正确的函数."
        else:
            fix_hint = f"可能的修正: 删除多出的 {diff} 个参数; 或检查你是否调用了正确的函数."
    elif site.positional_count < best_candidate.min_arity:
        missing = best_candidate.min_arity - site.positional_count
        fix_hint = f"可能的修正: 补充缺少的 {missing} 个位置参数; 或检查函数签名是否变了."
    elif site.kw_names_used and not best_candidate.has_var_keyword:
        unknown_kws = site.kw_names_used - (best_candidate.kw_names_accepted | set(best_candidate.param_names))
        if unknown_kws:
            kw = sorted(unknown_kws)[0]
            fix_hint = f"可能的修正: 删除关键字参数 `{kw}=…`; 或确认函数签名."
    elif site.lhs_unpack_arity and site.lhs_unpack_arity > 1:
        fix_hint = f"可能的修正: 不要解包返回值 (改 `x = {best_candidate.name}(…)`); 或确认函数确实返回 tuple."

    docstring_line = (
        f"Docstring 首行: {best_candidate.docstring_first_line}"
        if best_candidate.docstring_first_line
        else "Docstring 首行: (函数无 docstring)"
    )

    pieces = [
        f"{site.file}:{site.lineno}",
        f"你的调用: {site.call_source} 用了 {site.positional_count} 个位置参数"
        + (f" + {site.keyword_count} 个关键字参数" if site.keyword_count else "")
        + ".",
        f"函数定义只接受 {best_candidate.min_arity} ~ "
        + ("∞" if best_candidate.max_arity == _MAX_ARITY_SENTINEL else str(best_candidate.max_arity))
        + " 个位置参数.",
        "",
        f"函数定义位置: {best_candidate.declared_file}:{best_candidate.declared_lineno}",
        f"签名: {sig_display}",
        docstring_line,
    ]
    if fix_hint:
        pieces.append("")
        pieces.append(fix_hint)
    # Append the original structured reason as a debug-trace line
    pieces.append("")
    pieces.append(f"(structured: {structured_reason})")
    return "\n".join(pieces)


def check_contract_consistency(
    workspace_dir: str,
    intent_contract: Optional[Dict[str, Any]] = None,
) -> Tuple[List[ContractMismatch], List[Dict[str, Any]]]:
    """v3.3: returns (mismatches, skipped_unpacking_calls).

    A.2: when a call uses `*args` or `**kwargs` (starred_count > 0 OR
    double_starred_count > 0), its arity is not statically determinable;
    we MUST NOT emit a mismatch. Such calls are recorded into the second
    return value so the verifier can log them in details for transparency.
    """
    callee_index: Dict[str, List[CalleeSignature]] = {}
    call_sites: List[CallSite] = []
    for path in _iter_workspace_py(workspace_dir):
        try:
            tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)
        except SyntaxError:
            call_sites.append(CallSite(
                called_name="<syntax_error>",
                positional_count=0, keyword_count=0,
                starred_count=0, double_starred_count=0,
                kw_names_used=set(), lhs_unpack_arity=None,
                file=path, lineno=0, call_source="",
            ))
            continue
        for cs in _extract_callees_from_tree(tree, path):
            callee_index.setdefault(cs.name, []).append(cs)
        call_sites.extend(_extract_call_sites_from_tree(tree, path))

    mismatches: List[ContractMismatch] = []
    skipped_unpacking: List[Dict[str, Any]] = []

    for site in call_sites:
        if site.called_name == "<syntax_error>":
            mismatches.append(ContractMismatch(
                call_site=site, candidate_callees=[],
                reason=f"SyntaxError in {site.file}",
                reason_natural=f"{site.file} 有 Python 语法错误, 无法解析. 请修正语法后重试.",
            ))
            continue
        candidates = callee_index.get(site.called_name, [])
        if not candidates:
            # External call (stdlib / 3rd-party), skip — we only check intra-workspace consistency.
            continue
        # A.2: skip calls with `*args` or `**kwargs` unpacking — arity not
        # statically determinable. Conservative: never emit a false positive.
        if site.starred_count > 0 or site.double_starred_count > 0:
            skipped_unpacking.append({
                "file": site.file, "lineno": site.lineno,
                "call_source": site.call_source,
                "starred_count": site.starred_count,
                "double_starred_count": site.double_starred_count,
                "reason": "arity not statically determinable due to *args/**kwargs",
            })
            continue
        compatible_reasons: List[str] = []
        any_ok = False
        for c in candidates:
            ok, reason = _signature_admits_call(c, site)
            if ok:
                any_ok = True
                break
            compatible_reasons.append(reason)
        if not any_ok:
            best = candidates[0]
            structured = "; ".join(compatible_reasons[:3])
            mismatches.append(ContractMismatch(
                call_site=site,
                candidate_callees=candidates,
                reason=structured,
                reason_natural=_render_natural_mismatch(site, best, structured),
            ))

    # Schema-dict synergy: validate intent contract if supplied.
    if intent_contract:
        try:
            from ystar.governance.contract_lifecycle import validate_y_star_schema_v2
            schema_result = validate_y_star_schema_v2(intent_contract)
            if schema_result.get("errors"):
                fake_site = CallSite(
                    called_name="<intent_contract>",
                    positional_count=0, keyword_count=0,
                    starred_count=0, double_starred_count=0,
                    kw_names_used=set(), lhs_unpack_arity=None,
                    file="<contract_dict>", lineno=0,
                )
                err_summary = f"intent contract schema errors: {schema_result['errors'][:3]}"
                mismatches.append(ContractMismatch(
                    call_site=fake_site, candidate_callees=[],
                    reason=err_summary,
                    reason_natural=f"任务的意图 contract 不符合 Y* schema: {err_summary}",
                ))
        except Exception:
            pass

    return mismatches, skipped_unpacking


# === Verifier interface =====================================================

class ContractConsistencyVerifier(Verifier):
    name = "contract_consistency"
    # E.2 metadata
    applies_to_tasks: List[str] = ["all"]
    min_model_capacity: str = "small"
    feedback_complexity: str = "medium"
    known_limitations: List[str] = [
        "intra-workspace only (no stdlib/3rd-party type-check)",
        "skips calls using *args/**kwargs (statically undeterminable, A.2 safety policy)",
    ]

    def is_applicable(self, workspace_dir: str, contract: Optional[Dict[str, Any]] = None) -> bool:
        for root, _, files in os.walk(workspace_dir):
            if any(f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        mismatches, skipped = check_contract_consistency(
            workspace_dir, intent_contract=contract or None
        )
        if not mismatches:
            details: Dict[str, Any] = {}
            if skipped:
                details["skipped_unpacking_calls"] = skipped
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message="contract_consistency: all call sites compatible with callees",
                message_natural="所有调用都与函数定义匹配, 没有 arity / 关键字 / 返回 shape 错误.",
                details=details,
                elapsed_seconds=time.time() - t0,
            )
        # v3.3 structured + natural messages
        structured: List[str] = []
        natural_blocks: List[str] = []
        for m in mismatches[:10]:
            site = m.call_site
            structured.append(
                f"{site.file}:{site.lineno}: call `{site.called_name}` "
                f"(positional={site.positional_count}, keyword={site.keyword_count}, "
                f"kw_names={sorted(site.kw_names_used) or '[]'}) — {m.reason}"
            )
            natural_blocks.append(m.reason_natural)
        details = {
            "mismatches": structured,
            "n": len(mismatches),
        }
        if skipped:
            details["skipped_unpacking_calls"] = skipped
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message=f"contract_consistency: {len(mismatches)} mismatch(es); first: {structured[0][:200]}",
            message_natural="\n\n---\n\n".join(natural_blocks),
            details=details,
            elapsed_seconds=time.time() - t0,
        )

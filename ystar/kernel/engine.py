# Layer: Foundation
#
# ystar — Human Intent to Machine Predicate
# Copyright (C) 2026 Haotian Liu
# MIT License
#
# v0.2.0 — Security patch (2026-03)
# Fixes applied:
#   FIX-1  only_paths:    path-traversal bypass → abspath normalisation (same-CWD scope)
#   FIX-2  invariant:     eval sandbox escape   → AST whitelist evaluator (Subscript-safe)
#   FIX-3  only_domains:  subdomain spoofing    → disallow dots in subdomain prefix
#   FIX-4  check() entry: type-confusion bypass → non-primitive params → type_safety violation
"""
Runtime execution engine: checks whether an actual call satisfies an IntentContract.

This is the core of the Y*_t system. Given a contract (intent) and an actual
function call (behavior), it produces a CheckResult that records:
- whether the call was within specification
- which specific constraints were violated and why
- the severity of each violation

All checks are deterministic: same contract + same params = same result.

v0.2.0 security note on only_paths (FIX-1):
  Path comparison is now done via os.path.abspath() which resolves relative to
  the process CWD at call time. This is correct when both the allowlist entry
  and the parameter value are expressed in the same form (both relative or both
  absolute). Mixing absolute allowlist paths with relative parameter values, or
  vice versa, may produce unexpected results — use consistent path forms.
"""
from __future__ import annotations

import ast as _ast
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ystar.kernel.dimensions import IntentContract
from ystar.kernel.scope_encoding import split_scopes


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class Violation:
    dimension:  str    # which dimension was violated
    field:      str    # which parameter caused the violation
    message:    str    # human-readable description
    actual:     Any    # the actual value that caused the violation
    constraint: str    # the constraint that was violated
    severity:   float  = 0.8  # 0.0 - 1.0

    def to_dict(self) -> dict:
        """Serialise to a language-agnostic wire format."""
        return {
            "dimension":  self.dimension,
            "field":      self.field,
            "message":    self.message,
            "actual":     str(self.actual)[:500],
            "constraint": self.constraint,
            "severity":   self.severity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Violation":
        return cls(
            dimension  = d["dimension"],
            field      = d["field"],
            message    = d["message"],
            actual     = d.get("actual", ""),
            constraint = d.get("constraint", ""),
            severity   = float(d.get("severity", 0.8)),
        )


@dataclass
class CheckResult:
    """Result of checking a function call against an IntentContract."""
    passed:     bool
    violations: List[Violation] = field(default_factory=list)
    contract:   Optional[IntentContract] = None

    def __bool__(self) -> bool:
        return self.passed

    def summary(self) -> str:
        if self.passed:
            return "PASS"
        msgs = "; ".join(v.message for v in self.violations)
        return f"VIOLATION: {msgs}"


# ── Parameter classification helpers ─────────────────────────────────────────

_PATH_PARAM_NAMES = {
    "path", "file", "dir", "folder", "filepath", "filename",
    "dest", "src", "source", "target", "output", "input",
}

# パスチェックから明示的に除外するパラメータ名
# これらは文字列値がパスのように見えても、セマンティクス的にパスではない
# 通用语义参数名——这些参数的值即使形如路径也不应被当作路径处理
# 域层可以通过 register_non_path_params() 追加自己的参数名
_NON_PATH_PARAM_NAMES: set = {
    "description", "message", "reason", "note",
    "comment", "summary", "label", "title", "text",
    "name", "tag", "category", "type", "status",
}

def register_non_path_params(names) -> None:
    """注册额外的「非路径」参数名到内核。
    域层（如 OpenClaw）在 import 时调用此函数，把自己的
    语义参数名（task_intent、patch_summary 等）注入进来。
    内核本身不知道任何域的参数命名约定。
    """
    _NON_PATH_PARAM_NAMES.update(names)
_URL_PARAM_NAMES = {
    "url", "endpoint", "uri", "href", "host", "domain",
    "address", "base_url", "api_url", "webhook",
}
_COMMAND_PARAM_NAMES = {
    "command", "cmd", "shell", "exec", "run", "script", "args",
}

# Primitive types considered safe for parameter values (FIX-4)
_PRIMITIVE_TYPES = (str, int, float, bool, type(None), bytes)


# ── FIX-C2/C3: Value-shape parameter classifier ──────────────────────────────
# 当参数名不在已知关键词列表里时，按值的实际形态补充分类。
# 纯确定性：只用正则匹配，零LLM依赖。

_PATH_VALUE_RE = re.compile(
    r'^(\.{0,2}/|[A-Za-z]:\\|~/)' # ./ ../ / C:\ ~/
    r'|\.(py|txt|json|yaml|yml|cfg|ini|env|sh|log|csv|xml|html|md|key|pem|crt)$',
    re.IGNORECASE,
)
_URL_VALUE_RE = re.compile(
    r'^https?://'                                          # http:// https://
    r'|^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'       # IP address
    r'|^([a-zA-Z0-9][a-zA-Z0-9\-]*\.)+[a-zA-Z]{2,6}/', # domain/path (requires /)
)


def _classify_by_value(value: str) -> Optional[str]:
    """
    Classify a parameter's semantic type by the shape of its value (FIX-C2/C3).

    Used as a fallback when the parameter name is not in any known keyword set.
    Returns 'path', 'url', or None.

    Examples:
        _classify_by_value('/etc/passwd')       → 'path'
        _classify_by_value('./projects/app.py') → 'path'
        _classify_by_value('https://evil.com')  → 'url'
        _classify_by_value('192.168.1.1')       → 'url'
        _classify_by_value('alice')             → None
    """
    if not isinstance(value, str) or len(value) < 2:
        return None
    if _PATH_VALUE_RE.search(value):
        return "path"
    if _URL_VALUE_RE.search(value):
        return "url"
    return None




def _is_path_param(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in _PATH_PARAM_NAMES)


def _is_url_param(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in _URL_PARAM_NAMES) or n.endswith("url")


def _is_command_param(name: str) -> bool:
    n = name.lower()
    return any(kw in n for kw in _COMMAND_PARAM_NAMES)


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
        return (parsed.hostname or "").lower()
    except Exception:
        return url.lower()


# ── FIX-3: Strict domain allowlist matching ───────────────────────────────────

def _domain_is_allowed(domain: str, allowed_domains: List[str]) -> bool:
    """
    Strict domain allowlist check (FIX-3).

    Permits:
      - Exact match:          domain == allowed
      - Single-label subdomain: x.allowed where x contains no dots

    Rejects (was accepted in v0.1.0):
      - Multi-part prefix:    a.b.allowed  (e.g. evil.com.api.github.com)
      - Suffix spoof:         allowed.evil.com
    """
    domain = domain.lower()
    for ad in allowed_domains:
        ad = ad.lower()
        if domain == ad:
            return True
        suffix = "." + ad
        if domain.endswith(suffix):
            prefix = domain[: -len(suffix)]
            # FIX-3: reject if prefix itself contains a dot.
            # "sub.api.github.com"      → prefix="sub"      → no dot → allow
            # "evil.com.api.github.com" → prefix="evil.com" → has dot → reject
            if "." not in prefix:
                return True
    return False


# ── FIX-2: AST-whitelisted expression evaluator ──────────────────────────────

_SAFE_AST_NODES = {
    _ast.Expression, _ast.BoolOp, _ast.BinOp, _ast.UnaryOp, _ast.Compare,
    _ast.Constant, _ast.Name, _ast.Load, _ast.And, _ast.Or, _ast.Not,
    _ast.Add, _ast.Sub, _ast.Mult, _ast.Div, _ast.Mod, _ast.FloorDiv, _ast.Pow,
    _ast.Eq, _ast.NotEq, _ast.Lt, _ast.LtE, _ast.Gt, _ast.GtE,
    _ast.Is, _ast.IsNot, _ast.In, _ast.NotIn,
    _ast.IfExp, _ast.Tuple, _ast.List, _ast.Call, _ast.Attribute,
    # Subscript retained for backward compatibility: result['status'] in postconditions.
    # Security note: Subscript itself is safe; the attack vector is class-hierarchy
    # traversal via __class__/__subclasses__, which is blocked by _BLOCKED_ATTRS.
    _ast.Subscript, _ast.Index, _ast.Slice,
}

_BLOCKED_ATTRS = {
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__builtins__", "__import__", "__code__", "__closure__",
    "__mro__", "__dict__", "__reduce__", "__reduce_ex__",
    "__init__", "__new__", "__del__", "__getattribute__",
}


def _safe_eval(expr: str, namespace: dict):
    """
    AST-whitelisted expression evaluator (FIX-2).

    Replaces bare eval() + {"__builtins__": {}} which is bypassable via
    Python's class hierarchy (__class__.__bases__[0].__subclasses__() ...).
    See CVE-equivalent analysis in ystar_paper.md Appendix A.3.

    The whitelist permits arithmetic, comparison, simple attribute access
    (result.get(...)), and dict subscript (result['key']) — all patterns
    that appear in typical invariant/postcondition expressions.
    All dunder attributes and free function calls are blocked at the AST
    level before any bytecode is executed.

    Returns: (result_value, error_message_or_None)
      If error_message is not None, the expression was rejected or failed.
    """
    try:
        tree = _ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return None, f"SyntaxError: {e}"

    for node in _ast.walk(tree):
        if type(node) not in _SAFE_AST_NODES:
            return None, f"Blocked AST node type: {type(node).__name__}"
        if isinstance(node, _ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            return None, f"Blocked attribute access: '{node.attr}'"
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name):
            # Allow method calls (result.get(...)) but not free function calls.
            # Free function calls require a Name node as the func — e.g. open(),
            # eval(), __import__(). Method calls use an Attribute node.
            return None, f"Blocked free function call: '{node.func.id}'"

    try:
        return eval(
            compile(tree, "<invariant>", "eval"),
            {"__builtins__": {}},
            namespace,
        ), None
    except Exception as e:
        return None, str(e)


# ── FIX-4: Parameter type validation ─────────────────────────────────────────

def _validate_param_types(params: dict) -> List[str]:
    """
    Detect non-primitive parameter values (FIX-4).

    Objects with a custom __str__ can show an innocent string representation
    while carrying a malicious payload that bypasses deny/only_paths checks.
    Returns the names of parameters whose types are not primitive.
    """
    bad = []
    for k, v in params.items():
        if isinstance(v, _PRIMITIVE_TYPES):
            continue
        if isinstance(v, (list, tuple)) and all(isinstance(e, _PRIMITIVE_TYPES) for e in v):
            continue
        bad.append(k)
    return bad


# ── Core check function ───────────────────────────────────────────────────────

def check(
    params:   Dict[str, Any],
    result:   Any,
    contract: IntentContract,
) -> CheckResult:
    """
    Check whether a function call satisfies an IntentContract.

    Args:
        params:   the actual function parameters {param_name: value}
        result:   the actual function return value (for postcondition checks)
        contract: the intent contract to check against

    Returns:
        CheckResult with passed=True if all constraints hold, False otherwise.

    v0.2.0 security changes vs v0.1.0:
        FIX-1: only_paths uses os.path.abspath+normpath (blocks ../ traversal)
        FIX-2: invariant/postcondition use AST-whitelisted _safe_eval() (blocks RCE)
        FIX-3: only_domains uses _domain_is_allowed() (blocks multi-part subdomain spoof)
        FIX-4: non-primitive params produce type_safety violations

    v0.42.0 contract legitimacy lifecycle:
        Checks contract effective_status() before enforcing constraints.
        Draft contracts are denied. Expired/stale contracts proceed with audit.
    """
    violations: List[Violation] = []

    # ── Contract legitimacy check (v0.42.0) ──────────────────────────────────
    eff_status = contract.effective_status()
    if eff_status == "draft":
        # Unconfirmed contracts deny everything
        return CheckResult(passed=False, violations=[
            Violation(
                dimension="legitimacy",
                field="contract",
                message="Contract not confirmed (status=draft)",
                actual="draft",
                constraint="confirmed contract required",
                severity=1.0,
            )
        ])
    if eff_status == "suspended":
        return CheckResult(passed=False, violations=[
            Violation(
                dimension="legitimacy",
                field="contract",
                message="Contract suspended by governance",
                actual="suspended",
                constraint="active contract required",
                severity=1.0,
            )
        ])

    # Expired and stale: record violations but don't block (audit mode)
    if eff_status == "expired":
        violations.append(Violation(
            dimension="contract_status",
            field="contract",
            message="Contract has expired (past valid_until)",
            actual="expired",
            constraint="active contract expected",
            severity=0.6,
        ))
    elif eff_status == "stale":
        violations.append(Violation(
            dimension="contract_status",
            field="contract",
            message="Contract legitimacy score has decayed below minimum threshold",
            actual="stale",
            constraint="active contract expected",
            severity=0.3,
        ))

    # ── FIX-4: type safety pre-check ─────────────────────────────────────────
    for k in _validate_param_types(params):
        violations.append(Violation(
            dimension  = "type_safety",
            field      = k,
            message    = (f"Parameter '{k}' has non-primitive type "
                          f"'{type(params[k]).__name__}' — string checks may be evaded"),
            actual     = type(params[k]).__name__,
            constraint = "primitive types only (str, int, float, bool, None, bytes)",
            severity   = 0.7,
        ))

    # ── 1. deny: no parameter value may contain these strings ────────────────
    for pattern in contract.deny:
        if not pattern or len(pattern) <= 1:
            continue
        for p_name, p_value in params.items():
            v_str = str(p_value) if not isinstance(p_value, str) else p_value
            if pattern.lower() in v_str.lower():
                violations.append(Violation(
                    dimension  = "deny",
                    field      = p_name,
                    message    = f"'{pattern}' is not allowed in {p_name}",
                    actual     = p_value,
                    constraint = f"deny contains '{pattern}'",
                    severity   = 0.8,
                ))

    # ── 2. only_paths: path params must be within allowed paths ──────────────
    # FIX-1: use abspath+normpath exclusively; the original raw startswith()
    # checks allowed "./projects/../../../etc/passwd" to pass a whitelist of
    # ["./projects/"] because the string literally starts with that prefix.
    # Note: both sides resolve relative to the process CWD — see module docstring.
    # FIX-C2/C3: also classify by value shape when name-based classification fails.
    # GAP-1 (meta-agent): recognize "module:" prefix for module scope constraints
    if contract.only_paths:
        # Separate module, external, external_domain, and filesystem path constraints
        module_constraints, external_constraints, external_domain_constraints, path_constraints = \
            split_scopes(contract.only_paths)

        # Item 5: Check external agent scope (same pattern as module: prefix)
        if external_constraints:
            ext_agent_id = params.get("external_agent_id", "")
            if ext_agent_id and ext_agent_id not in external_constraints:
                violations.append(Violation(
                    dimension  = "external_scope",
                    field      = "external_agent_id",
                    message    = f"External agent scope violation: '{ext_agent_id}' not in allowed agents {external_constraints}",
                    actual     = ext_agent_id,
                    constraint = f"only_paths=[external:{', external:'.join(external_constraints)}]",
                    severity   = 0.9,
                ))

        # T17: Check external_domain scope (same pattern as module: and external:)
        # Allows Y*gov to enforce domain-specific external governance at kernel level.
        # Usage: only_paths=["external_domain:finance"] validates the external_domain param.
        if external_domain_constraints:
            ext_domain = params.get("external_domain", "")
            if ext_domain and ext_domain not in external_domain_constraints:
                violations.append(Violation(
                    dimension  = "external_domain_scope",
                    field      = "external_domain",
                    message    = f"External domain scope violation: '{ext_domain}' not in allowed domains {external_domain_constraints}",
                    actual     = ext_domain,
                    constraint = f"only_paths=[external_domain:{', external_domain:'.join(external_domain_constraints)}]",
                    severity   = 0.9,
                ))

        # Check module scope if module_id/source_id/target_id present
        if module_constraints:
            for param_name in ["module_id", "source_id", "target_id", "plan_nodes"]:
                if param_name not in params:
                    continue
                param_value = params[param_name]
                # 3.1: plan_nodes is a list — check each element
                if isinstance(param_value, list):
                    for item in param_value:
                        item_str = str(item)
                        if item_str not in module_constraints:
                            violations.append(Violation(
                                dimension  = "module_scope",
                                field      = param_name,
                                message    = f"Module scope violation: '{item_str}' not in allowed modules {module_constraints}",
                                actual     = item_str,
                                constraint = f"only_paths=[module:{', module:'.join(module_constraints)}]",
                                severity   = 0.9,
                            ))
                else:
                    param_str = str(param_value)
                    if param_str not in module_constraints:
                        violations.append(Violation(
                            dimension  = "module_scope",
                            field      = param_name,
                            message    = f"Module scope violation: '{param_str}' not in allowed modules {module_constraints}",
                            actual     = param_str,
                            constraint = f"only_paths=[module:{', module:'.join(module_constraints)}]",
                            severity   = 0.9,
                        ))

        # Check filesystem paths as before
        if path_constraints:
            for p_name, p_value in params.items():
                # 明示的な非パスパラメータは除外
                if p_name.lower() in _NON_PATH_PARAM_NAMES:
                    continue
                is_path = _is_path_param(p_name)
                if not is_path and isinstance(p_value, str):
                    is_path = _classify_by_value(p_value) == "path"
                if not is_path:
                    continue
                v_str = str(p_value)
                allowed = False
                for allowed_path in path_constraints:
                    norm_path    = os.path.normpath(os.path.abspath(v_str))
                    norm_allowed = os.path.normpath(os.path.abspath(allowed_path))
                    if norm_path == norm_allowed or norm_path.startswith(norm_allowed + os.sep):
                        allowed = True
                        break
                if not allowed:
                    violations.append(Violation(
                        dimension  = "only_paths",
                        field      = p_name,
                        message    = f"Path '{p_value}' is not in allowed paths {path_constraints}",
                        actual     = p_value,
                        constraint = f"only_paths={path_constraints}",
                        severity   = 0.9,
                    ))

    # ── 3. deny_commands: command params must not start with these ────────────
    for cmd_pattern in contract.deny_commands:
        if not cmd_pattern:
            continue
        for p_name, p_value in params.items():
            if not _is_command_param(p_name):
                # Also check if any string param contains the command pattern
                if isinstance(p_value, str) and cmd_pattern.lower() in p_value.lower():
                    violations.append(Violation(
                        dimension  = "deny_commands",
                        field      = p_name,
                        message    = f"Command '{cmd_pattern}' is blocked",
                        actual     = p_value,
                        constraint = f"deny_commands contains '{cmd_pattern}'",
                        severity   = 0.9,
                    ))
                continue
            v_str = str(p_value).strip()
            if (v_str.lower().startswith(cmd_pattern.lower()) or
                    cmd_pattern.lower() in v_str.lower()):
                violations.append(Violation(
                    dimension  = "deny_commands",
                    field      = p_name,
                    message    = f"Command '{cmd_pattern}' is blocked in {p_name}",
                    actual     = p_value,
                    constraint = f"deny_commands contains '{cmd_pattern}'",
                    severity   = 0.9,
                ))

    # ── 4. only_domains: URL params must be within allowed domains ────────────
    # FIX-3: replaced inline endswith() with _domain_is_allowed() which rejects
    # multi-part subdomain prefixes (e.g. evil.com.api.github.com).
    # FIX-C2/C3: also classify by value shape when name-based classification fails.
    if contract.only_domains:
        for p_name, p_value in params.items():
            is_url = _is_url_param(p_name)
            if not is_url and isinstance(p_value, str):
                is_url = _classify_by_value(p_value) == "url"
            if not is_url:
                continue
            if not isinstance(p_value, str):
                continue
            # Skip non-HTTP schemes
            if p_value.startswith(("file://", "data:", "ftp://")):
                continue
            domain = _extract_domain(p_value)
            if not domain:
                continue
            if not _domain_is_allowed(domain, contract.only_domains):
                violations.append(Violation(
                    dimension  = "only_domains",
                    field      = p_name,
                    message    = f"Domain '{domain}' is not in allowed domains {contract.only_domains}",
                    actual     = p_value,
                    constraint = f"only_domains={contract.only_domains}",
                    severity   = 0.8,
                ))

    # ── 5. invariant: Python expressions on input params ─────────────────────
    # FIX-2: replaced eval()+{__builtins__:{}} with _safe_eval() (AST whitelist).
    for expr in contract.invariant:
        if not expr.strip():
            continue
        namespace = dict(params)
        namespace["params"] = params
        result_val, eval_err = _safe_eval(expr, namespace)
        if eval_err:
            if "is not defined" in str(eval_err):
                # FIX-C1: NameError means the invariant references a variable
                # that doesn't match any actual parameter name.
                # Previously silently skipped — now surfaced as phantom_variable
                # so the user knows the invariant is NOT being enforced.
                import re as _re
                m = _re.search(r"name '(\w+)' is not defined", str(eval_err))
                phantom = m.group(1) if m else "unknown"
                actual_names = list(params.keys())
                violations.append(Violation(
                    dimension  = "phantom_variable",
                    field      = "params",
                    message    = (
                        f"Invariant '{expr}' was skipped — "
                        f"'{phantom}' is not present in this call's parameters "
                        f"(got: {actual_names}).\n"
                        f"  Tip: use optional_invariant=['{expr}'] to check only "
                        f"when '{phantom}' is present, or fix the parameter name."
                    ),
                    actual     = phantom,
                    constraint = f"invariant: {expr}",
                    severity   = 0.6,  # warning-level: not blocked, but not enforced
                ))
            else:
                # Blocked by AST whitelist or other error — hard violation
                violations.append(Violation(
                    dimension  = "invariant",
                    field      = "params",
                    message    = f"Invariant expression rejected: '{expr}' — {eval_err}",
                    actual     = expr,
                    constraint = f"invariant: {expr}",
                    severity   = 1.0,
                ))
        elif not result_val:
            violations.append(Violation(
                dimension  = "invariant",
                field      = "params",
                message    = f"Invariant violated: '{expr}'",
                actual     = {k: v for k, v in params.items()},
                constraint = f"invariant: {expr}",
                severity   = 0.9,
            ))

    # ── 5b. optional_invariant: like invariant, but SILENT when variable absent
    # v0.12: designed for multi-agent systems where different agents pass
    # different parameter subsets. If the referenced variable is absent from
    # params, the expression is skipped silently (no phantom_variable warning).
    # If the variable IS present, the expression is evaluated exactly like invariant.
    for expr in contract.optional_invariant:
        if not expr.strip():
            continue
        namespace = dict(params)
        namespace["params"] = params
        result_val, eval_err = _safe_eval(expr, namespace)
        if eval_err:
            if "is not defined" in str(eval_err):
                # Variable absent → skip silently (key difference from invariant)
                # This is the intended behavior for optional_invariant
                pass
            else:
                # Blocked by AST whitelist or other error → hard violation
                violations.append(Violation(
                    dimension  = "optional_invariant",
                    field      = "params",
                    message    = f"Optional invariant expression rejected: '{expr}' — {eval_err}",
                    actual     = expr,
                    constraint = f"optional_invariant: {expr}",
                    severity   = 1.0,
                ))
        elif not result_val:
            # Variable present AND expression evaluates to False → violation
            violations.append(Violation(
                dimension  = "optional_invariant",
                field      = "params",
                message    = f"Optional invariant violated: '{expr}'",
                actual     = {k: v for k, v in params.items()},
                constraint = f"optional_invariant: {expr}",
                severity   = 0.9,
            ))

    # ── 6. postcondition: Python expressions on output result ─────────────────
    # FIX-2: same _safe_eval() replacement as invariant.
    for expr in contract.postcondition:
        if not expr.strip():
            continue
        # Unwrap result if it's a dict with a 'result' key (K9Audit format)
        actual_result = result
        if isinstance(result, dict) and "result" in result:
            actual_result = result["result"]
        namespace = dict(params)
        namespace["params"]  = params
        namespace["result"]  = actual_result
        # Also allow result["key"] shorthand via Subscript (safe — see _SAFE_AST_NODES)
        if isinstance(actual_result, dict):
            namespace.update(actual_result)
        result_val, eval_err = _safe_eval(expr, namespace)
        if eval_err:
            violations.append(Violation(
                dimension  = "postcondition",
                field      = "result",
                message    = f"Postcondition expression rejected: '{expr}' — {eval_err}",
                actual     = expr,
                constraint = f"postcondition: {expr}",
                severity   = 1.0,
            ))
        elif not result_val:
            violations.append(Violation(
                dimension  = "postcondition",
                field      = "result",
                message    = f"Postcondition violated: '{expr}'",
                actual     = actual_result,
                constraint = f"postcondition: {expr}",
                severity   = 0.8,
            ))

    # ── 7. field_deny: per-field value blocklist ──────────────────────────────
    for field_name, blocked_values in contract.field_deny.items():
        if field_name not in params:
            continue
        p_value = str(params[field_name]).lower()
        for blocked in blocked_values:
            if blocked.lower() in p_value:
                violations.append(Violation(
                    dimension  = "field_deny",
                    field      = field_name,
                    message    = f"Value '{blocked}' is blocked in field '{field_name}'",
                    actual     = params[field_name],
                    constraint = f"field_deny[{field_name}] contains '{blocked}'",
                    severity   = 0.8,
                ))
                break

    # ── 8. value_range: numeric bounds ────────────────────────────────────────
    for param_name, bounds in contract.value_range.items():
        if param_name not in params:
            continue
        try:
            val = float(params[param_name])
        except (TypeError, ValueError):
            continue
        min_val = bounds.get("min")
        max_val = bounds.get("max")
        if min_val is not None and val < float(min_val):
            violations.append(Violation(
                dimension  = "value_range",
                field      = param_name,
                message    = f"{param_name}={val} is below minimum {min_val}",
                actual     = val,
                constraint = f"value_range[{param_name}].min={min_val}",
                severity   = 0.8,
            ))
        if max_val is not None and val > float(max_val):
            violations.append(Violation(
                dimension  = "value_range",
                field      = param_name,
                message    = f"{param_name}={val} exceeds maximum {max_val}",
                actual     = val,
                constraint = f"value_range[{param_name}].max={max_val}",
                severity   = 0.8,
            ))

    # ── 9. obligation_timing: task completion deadlines ───────────────────────
    # Task #5: Check whether obligations are completed within required time limits.
    # Only checks if contract defines obligation_timing AND params contain both
    # obligation_type and elapsed_seconds.
    if contract.obligation_timing:
        obligation_type = params.get("obligation_type")
        elapsed_seconds = params.get("elapsed_seconds")

        if obligation_type and elapsed_seconds is not None:
            # Check if this obligation type has a deadline defined
            if obligation_type in contract.obligation_timing:
                deadline = contract.obligation_timing[obligation_type]
                try:
                    elapsed = float(elapsed_seconds)
                    if elapsed > deadline:
                        violations.append(Violation(
                            dimension  = "obligation_timing",
                            field      = "elapsed_seconds",
                            message    = (f"Obligation '{obligation_type}' exceeded deadline: "
                                        f"{elapsed:.1f}s > {deadline}s"),
                            actual     = elapsed,
                            constraint = f"obligation_timing[{obligation_type}]={deadline}",
                            severity   = 0.9,
                        ))
                except (TypeError, ValueError):
                    # elapsed_seconds is not numeric — skip check
                    pass

    # Only violations with severity >= 0.7 cause passed=False
    # Lower severity violations (expired=0.6, stale=0.3) are audit-only
    blocking_violations = [v for v in violations if v.severity >= 0.7]

    return CheckResult(
        passed     = len(blocking_violations) == 0,
        violations = violations,
        contract   = contract,
    )


# ══════════════════════════════════════════════════════════════════════════════
# v0.15.0  EnforcementMode — 产品模式矩阵

class ContractViolationError(Exception):
    """Raised by enforce() in FAIL_CLOSED mode when violations are detected."""
    pass

# ══════════════════════════════════════════════════════════════════════════════

from enum import Enum

class EnforcementMode(Enum):
    """
    Y*的执行模式矩阵——回答"约束被违反时发生什么"。

    选择哪种模式是调用方的决策，Y*提供判断，不强制决定后果。

    OBSERVE_ONLY:    仅记录违规，不影响执行流程（适合初期接入/调试）
    CHECK_AND_RETURN:返回通过/违规结果，调用方决定如何处理（默认模式）
    FAIL_OPEN:       违规时记录并继续（生产降级保护）
    FAIL_CLOSED:     违规时阻断，抛出异常（严格合规场景）
    HOLD_FOR_APPROVAL:违规时挂起，等待人工审批（高风险操作）
    SIMULATE_ONLY:   仅模拟检查，输出假设性报告，不影响任何状态
    """
    OBSERVE_ONLY     = "observe_only"
    CHECK_AND_RETURN = "check_and_return"
    FAIL_OPEN        = "fail_open"
    FAIL_CLOSED      = "fail_closed"
    HOLD_FOR_APPROVAL= "hold_for_approval"
    SIMULATE_ONLY    = "simulate_only"


class EnforcementResult:
    """check()在指定模式下的完整结果"""
    __slots__ = ("check_result", "mode", "action_taken", "requires_approval")

    def __init__(self, check_result: "CheckResult",
                 mode: "EnforcementMode",
                 action_taken: str,
                 requires_approval: bool = False):
        self.check_result       = check_result
        self.mode               = mode
        self.action_taken       = action_taken
        self.requires_approval  = requires_approval

    @property
    def passed(self) -> bool:
        return self.check_result.passed

    @property
    def violations(self):
        return self.check_result.violations

    def __repr__(self):
        return (f"EnforcementResult(mode={self.mode.value}, "
                f"passed={self.passed}, action={self.action_taken})")


def enforce(
    params:   dict,
    result:   dict,
    contract: "IntentContract",
    mode:     "EnforcementMode" = EnforcementMode.CHECK_AND_RETURN,
) -> "EnforcementResult":
    """
    带模式的约束检查。比 check() 多一层执行语义。

    Args:
        params:   调用参数
        result:   调用结果
        contract: 意图合约
        mode:     执行模式（默认 CHECK_AND_RETURN）

    Returns:
        EnforcementResult（含原始CheckResult）

    Raises:
        ContractViolationError: 仅在 FAIL_CLOSED 模式且有违规时
    """
    r = check(params, result, contract)

    if mode == EnforcementMode.OBSERVE_ONLY:
        return EnforcementResult(r, mode, "logged")

    elif mode == EnforcementMode.CHECK_AND_RETURN:
        return EnforcementResult(r, mode, "returned")

    elif mode == EnforcementMode.FAIL_OPEN:
        action = "violation_logged" if not r.passed else "passed"
        return EnforcementResult(r, mode, action)

    elif mode == EnforcementMode.FAIL_CLOSED:
        if not r.passed:
            msgs = "; ".join(v.message[:60] for v in r.violations[:3])
            raise ContractViolationError(
                f"[FAIL_CLOSED] {len(r.violations)} violation(s): {msgs}"
            )
        return EnforcementResult(r, mode, "passed")

    elif mode == EnforcementMode.HOLD_FOR_APPROVAL:
        if not r.passed:
            return EnforcementResult(r, mode, "held", requires_approval=True)
        return EnforcementResult(r, mode, "passed")

    elif mode == EnforcementMode.SIMULATE_ONLY:
        return EnforcementResult(r, mode, "simulated")

    return EnforcementResult(r, mode, "unknown")

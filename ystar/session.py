# ystar/session.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
Policy: universal multi-entity constraint registry.

Zero business assumptions — "who" can be agent/player/role/user/employee/
anything; "what" can be write/fetch/execute/buy/heal/move/anything.

Usage::

    from ystar import Policy, from_template, IntentContract

    policy = Policy({
        "rd":    from_template({"can_write_to": ["./workspace/dev/"]}),
        "sales": IntentContract(only_domains=["api.hubspot.com"]),
    })

    result = policy.check("rd", "write", path="./workspace/dev/main.py")
    print(result.allowed)  # True
    print(result.reason)   # "ok"

    result2 = policy.check("rd", "write", path="./.env")
    print(result2.allowed)  # False
    print(result2.reason)   # "'.env' is not allowed in file_path"
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .kernel.dimensions import IntentContract
from .kernel.engine import check as _check

# Verb → canonical field name for check()
# Users say "write", "fetch", "execute" — we map to what check() understands.
_VERB_TO_FIELD: Dict[str, str] = {
    "write":      "file_path",
    "read":       "file_path",
    "save":       "file_path",
    "create":     "file_path",
    "delete":     "file_path",
    "fetch":      "url",
    "get":        "url",
    "request":    "url",
    "call":       "url",
    "post":       "url",
    "execute":    "command",
    "run":        "command",
    "exec":       "command",
    "cmd":        "command",
}

# kwarg aliases users naturally write → canonical param name
_KWARG_ALIASES: Dict[str, str] = {
    "path":       "file_path",
    "file":       "file_path",
    "filepath":   "file_path",
    "file_path":  "file_path",
    "url":        "url",
    "endpoint":   "url",
    "uri":        "url",
    "command":    "command",
    "cmd":        "command",
    "shell":      "command",
}


@dataclass
class PolicyResult:
    """Result of a Policy.check() call."""
    allowed:    bool
    reason:     str                   # "ok" or human-readable denial reason
    who:        str
    what:       str
    violations: List[Any] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        status = "allow" if self.allowed else f"deny({self.reason})"
        return f"PolicyResult({self.who}.{self.what} → {status})"


class Policy:
    """
    Universal multi-entity constraint registry.

    Maps names to IntentContracts and evaluates actions against them.
    No framework assumptions, no business-domain assumptions.

    Args:
        rules: dict mapping entity names to IntentContracts.
               Values can be IntentContract instances or dicts produced
               by from_template().
    """

    def __init__(self, rules: Dict[str, Any]) -> None:
        # Accept IntentContract directly OR TemplateResult (auto-unpack)
        from .template import TemplateResult as _TR
        resolved = {}
        for name, val in rules.items():
            if isinstance(val, _TR):
                resolved[name] = val.contract
                # store higher_order for potential future use
                if val.higher_order is not None:
                    self._higher_order = getattr(self, "_higher_order", {})
                    self._higher_order[name] = val.higher_order
            else:
                resolved[name] = val
        self._rules: Dict[str, IntentContract] = resolved

    # ── public API ────────────────────────────────────────────────

    def check(self, who: str, what: str, **kwargs) -> PolicyResult:
        """
        Check whether *who* is allowed to perform *what*.

        Args:
            who:     entity name (agent / player / role / user / …)
            what:    action verb (write / fetch / execute / …) or any string
            **kwargs: action parameters.  Common patterns::

                policy.check("rd", "write", path="./workspace/dev/main.py")
                policy.check("sales", "fetch", url="https://api.company.com")
                policy.check("finance", "execute", command="SELECT * FROM orders")
                policy.check("manager", "action", amount=500, account="vendor")

        Returns:
            PolicyResult with .allowed (bool) and .reason (str).
        """
        contract = self._rules.get(who)
        if contract is None:
            return PolicyResult(
                allowed=False,
                reason=f"no contract registered for '{who}'",
                who=who, what=what,
            )

        params = self._build_params(what, kwargs)
        result = _check(params, {}, contract)

        # filter phantom_variable — these are optional_invariant misses,
        # not real violations in this context
        real_viols = [
            v for v in result.violations
            if v.dimension != "phantom_variable"
        ]
        allowed = len(real_viols) == 0
        reason = real_viols[0].message if real_viols else "ok"
        return PolicyResult(
            allowed=allowed, reason=reason,
            who=who, what=what, violations=real_viols,
        )

    def add(self, who: str, contract: IntentContract) -> None:
        """Register or replace a contract for *who*."""
        self._rules[who] = contract

    def remove(self, who: str) -> None:
        """Remove the contract for *who*."""
        self._rules.pop(who, None)

    def __contains__(self, who: str) -> bool:
        return who in self._rules

    def __repr__(self) -> str:
        names = list(self._rules.keys())
        return f"Policy(entities={names})"

    # ── 从 AGENTS.md 构建 ──────────────────────────────────────────

    @classmethod
    def from_agents_md(
        cls,
        path: Optional[str] = None,
        confirm: bool = True,
        role: str = "agent",
        api_call_fn=None,
    ) -> "Policy":
        """
        从 AGENTS.md / CLAUDE.md 构建 Policy（主路径入口）。

        用 LLM 把自然语言规则翻译成 IntentContract，可选让用户确认。
        LLM 不可用时自动回退到正则解析器。

        Args:
            path:        AGENTS.md 路径（None = 自动查找当前目录）
            confirm:     True = 在终端展示翻译结果并等待确认（推荐）
            role:        生成的 Policy 里角色的名字，默认 "agent"
            api_call_fn: 注入的 LLM 调用函数（测试用）

        Returns:
            Policy 对象，包含翻译后的合约

        Example::

            # 最简单的用法 — 自动找 AGENTS.md，翻译，确认
            policy = Policy.from_agents_md()

            # 跳过确认（适合 CI / 已验证过的规则）
            policy = Policy.from_agents_md(confirm=False)

            # 指定路径
            policy = Policy.from_agents_md("./config/AGENTS.md")
        """
        from .kernel.nl_to_contract import load_and_translate
        from .kernel.dimensions import IntentContract, normalize_aliases

        contract_dict, source_path = load_and_translate(
            path=path,
            confirm=confirm,
            api_call_fn=api_call_fn,
        )

        if contract_dict is None:
            # 用户拒绝或文件未找到 → 返回空 Policy
            import warnings
            warnings.warn(
                "Policy.from_agents_md(): no contract loaded. "
                "Returning empty Policy (all actions allowed).",
                UserWarning,
                stacklevel=2,
            )
            return cls({role: IntentContract()})

        # 构建 IntentContract
        # normalize_aliases 接受 **kwargs，把 temporal 等高阶字段分离出去
        temporal = contract_dict.pop("temporal", None)
        try:
            # normalize_aliases 返回 IntentContract 对象
            contract = normalize_aliases(**contract_dict)
        except Exception:
            # 字段有问题时回退到空合约，避免崩溃
            contract = IntentContract()

        if source_path:
            contract.name = source_path

        policy = cls({role: contract})

        # 简单提示
        n_rules = sum(
            bool(v) for v in contract.__dict__.values()
            if isinstance(v, (list, dict))
        )
        print(f"\n  ✅ Policy 已加载（{n_rules} 条规则生效）\n")
        return policy

    # ── internals ─────────────────────────────────────────────────

    def _build_params(self, what: str, kwargs: dict) -> dict:
        """
        Translate (what, **kwargs) into the flat params dict that check() uses.

        Resolution order:
        1. Verb → canonical field (write→file_path, fetch→url, execute→command)
        2. Kwarg alias normalisation (path→file_path, url→url, cmd→command)
        3. Pass remaining kwargs through unchanged
        """
        params: Dict[str, Any] = {"action": what}

        # normalise kwarg aliases first
        normalised: Dict[str, Any] = {}
        for k, v in kwargs.items():
            canonical = _KWARG_ALIASES.get(k.lower(), k)
            normalised[canonical] = v

        # fill canonical field from verb if not already provided
        verb_field = _VERB_TO_FIELD.get(what.lower().split("_")[0])
        if verb_field and verb_field not in normalised:
            # look for any kwarg that maps to this field
            for k, v in list(normalised.items()):
                if _KWARG_ALIASES.get(k, k) == verb_field:
                    normalised[verb_field] = v
                    break

        params.update(normalised)
        return params

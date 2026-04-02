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

    # ── 从 AGENTS.md 构建多角色 Policy ─────────────────────────────

    @classmethod
    def from_agents_md_multi(
        cls,
        path: Optional[str] = None,
    ) -> "Policy":
        """
        从 AGENTS.md 解析出 per-agent IntentContract。

        与 from_agents_md() 的区别：
        - from_agents_md() → 1 个通用合约（所有 agent 共享）
        - from_agents_md_multi() → N 个角色合约 + 1 个 fallback

        每个角色合约包含：
        - 全局 deny（禁止路径）+ 角色特有 deny
        - 全局 deny_commands（禁止命令）
        - 角色名用于 CIEU 审计归属

        注意：写路径边界（only_paths）由 hook 层的 _check_write_boundary()
        单独执行，因为 only_paths 会同时限制读操作，而 AGENTS.md 规定
        "Everyone reads everything"。
        """
        from pathlib import Path as _Path

        # 查找 AGENTS.md
        if path is None:
            for candidate in [_Path("AGENTS.md"), _Path.cwd() / "AGENTS.md"]:
                if candidate.exists():
                    path = str(candidate)
                    break
        if path is None or not _Path(path).exists():
            import warnings
            warnings.warn(
                "from_agents_md_multi(): AGENTS.md not found. "
                "Returning single-agent fallback.",
                UserWarning, stacklevel=2,
            )
            return cls({"agent": IntentContract()})

        import re

        with open(path, encoding="utf-8") as f:
            text = f.read()

        # ── 1. 解析全局禁止项 ─────────────────────────────────────────
        global_deny: list = []
        global_deny_commands: list = []

        # 提取 "Forbidden Paths" 节的列表项
        fp_match = re.search(
            r"###\s*Forbidden Paths.*?\n((?:\s*-\s*.+\n)+)", text)
        if fp_match:
            for line in fp_match.group(1).strip().splitlines():
                item = line.strip().lstrip("- ").strip()
                if item and not item.startswith("Any "):
                    for part in re.split(r",\s*", item):
                        part = part.strip().rstrip("*")
                        if part:
                            global_deny.append(part)

        # 提取 "Forbidden Commands" 节的列表项
        fc_match = re.search(
            r"###\s*Forbidden Commands.*?\n((?:\s*-\s*.+\n)+)", text)
        if fc_match:
            for line in fc_match.group(1).strip().splitlines():
                item = line.strip().lstrip("- ").strip()
                if item:
                    global_deny_commands.append(item)

        # ── 2. 解析每个 Agent 角色 ────────────────────────────────────
        # 匹配 "## XXX Agent" 节，提取角色名
        agent_sections = re.split(r"\n## ", text)
        contracts: Dict[str, IntentContract] = {}

        for section in agent_sections:
            # Match any "XXX Agent" header - role names are user-defined
            # Examples: "CEO Agent", "Sales Agent", "Support Agent", etc.
            role_match = re.match(
                r"(\w[\w\s]*?)\s*Agent\s*(?:\(.*?\))?\s*\n", section)
            if not role_match:
                continue

            role_title = role_match.group(1).strip()  # Extract role name

            # Convert to lowercase key for policy lookup
            # No hardcoded roles - any user-defined role name is valid
            agent_key = role_title.lower()

            # Users can override the agent_key via agent .md name: field

            # 提取该角色的 deny（从 "cannot access" 或 "Prohibited" 描述）
            extra_deny: list = []
            deny_match = re.search(
                r"(?:cannot access|absolutely cannot|Prohibited)[:\s]*(.+?)(?:\n\n|\n###|\n##|\Z)",
                section, re.DOTALL | re.IGNORECASE)
            if deny_match:
                for item in re.split(r",\s*|\n\s*-\s*", deny_match.group(1)):
                    item = item.strip().strip("`").strip()
                    if item and len(item) < 100:
                        extra_deny.append(item)

            contracts[agent_key] = IntentContract(
                deny=global_deny + extra_deny,
                deny_commands=global_deny_commands,
                name=f"{agent_key} (from AGENTS.md)",
            )

        # 通用 fallback（未识别身份时使用，仅全局规则）
        contracts["agent"] = IntentContract(
            deny=global_deny,
            deny_commands=global_deny_commands,
            name="generic agent (from AGENTS.md)",
        )

        policy = cls(contracts)
        n = len(contracts) - 1  # 不算 fallback
        import sys
        print(f"  ✅ Multi-agent Policy: {n} roles loaded from AGENTS.md",
              file=sys.stderr)
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

"""
Y* Domain Packs

Domain Packs are the second layer of Y*'s three-layer architecture:

  Layer 1  ystar/ (kernel)  — industry-agnostic constraint compiler
  Layer 2  domains/          — pluggable domain vocabulary and contract templates
  Layer 3  scenarios/        — full scenario experiments within a domain

A domain pack provides:
  - Domain vocabulary (DomainVocabulary)
  - Domain constitutional contract (ConstitutionalContract)
  - Pre-built domain IntentContracts
  - Domain prefill extensions (additional Source patterns)

Usage:
  from ystar.domains.finance import FinanceDomainPack
  pack = FinanceDomainPack()
  constitution = pack.constitutional_contract()
  contract = pack.make_contract(role="execution_agent", context={...})
"""
from abc import ABC, abstractmethod
from typing import Optional


class DomainPack(ABC):
    """
    Y* domain pack base class.
    All domain packs inherit from this class to ensure substitutability.

    Mandatory interface:
      domain_name          — short identifier, e.g. "finance"
      version              — SemVer string, e.g. "1.0.0"
      constitutional_contract() — returns ConstitutionalContract
      vocabulary()         — returns the domain vocabulary dict
      make_contract(role)  — returns IntentContract for a given role

    Optional interface (provided with a default implementation):
      describe()           — human-readable summary line
      schema_version       — config schema version (for auditing)
    """

    @property
    @abstractmethod
    def domain_name(self) -> str:
        """Domain name, e.g. 'finance', 'devops', 'healthcare'."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Domain pack version (SemVer), e.g. '1.0.0'."""

    @property
    def schema_version(self) -> str:
        """
        Config schema version for this pack (used for auditability).
        Override in subclasses if the pack supports external configuration.
        Returns 'n/a' by default.
        """
        return "n/a"

    @abstractmethod
    def constitutional_contract(self):
        """
        Return the constitutional contract for this domain (ConstitutionalContract).
        Contains global constraints for this domain that can never be relaxed.
        """

    @abstractmethod
    def vocabulary(self) -> dict:
        """
        Return the domain vocabulary dict:
        {
          "deny_keywords":    [...]   # domain-specific deny keywords
          "role_names":       [...]   # role names available via make_contract()
          "param_names":      [...]   # important parameter names
          "env_keywords":     [...]   # environment/context keywords
        }
        """

    def make_contract(self, role: str, context: dict = None):
        """
        Return the IntentContract for the given role.
        Override in subclasses to provide role-specific contracts.
        Default implementation returns an empty contract.
        """
        from ystar import IntentContract
        return IntentContract()

    def describe(self) -> str:
        """Return a one-line human-readable summary of this pack."""
        roles = self.vocabulary().get("role_names", [])
        return (
            f"DomainPack(domain={self.domain_name!r}, "
            f"version={self.version!r}, "
            f"roles={len(roles)})"
        )

    @classmethod
    def compose(cls, *packs: "DomainPack",
                name: str = "composed") -> "ComposedDomainPack":
        """
        v0.41: 跨 domain 合约组合。

        按照"取最严"原则合并多个 domain pack 的 constitutional contract：
          - deny / deny_commands / invariant: 取并集（黑名单只增不减）
          - only_paths / only_domains:        取交集（白名单越来越严）
          - value_range:                      取最严格值（max 取最小，min 取最大）
          - field_deny:                       取并集

        冲突检测：
          - only_paths / only_domains 白名单交集为空时抛出 ValueError，
            因为空白名单等价于"拒绝所有请求"，是静默陷阱。

        示例：
            from ystar.domains.finance import FinanceDomainPack
            from ystar.domains.devops import DevOpsDomainPack
            composed = DomainPack.compose(FinanceDomainPack(), DevOpsDomainPack())
            contract = composed.constitutional_contract()

        Args:
            *packs: 要组合的 DomainPack 实例（至少2个）
            name:   组合后的 domain 名称（用于日志和调试）

        Returns:
            ComposedDomainPack — 行为与普通 DomainPack 相同

        Raises:
            ValueError: 当 only_paths 或 only_domains 的交集为空时
        """
        if len(packs) < 1:
            raise ValueError("compose() requires at least one DomainPack")
        return ComposedDomainPack(list(packs), name=name)


class ComposedDomainPack(DomainPack):
    """
    v0.41: 多 domain pack 的组合结果。
    由 DomainPack.compose() 创建，不要直接实例化。
    """

    def __init__(self, packs: list, name: str = "composed"):
        self._packs = packs
        self._name  = name
        self._composed_contract = None  # 惰性计算

    @property
    def domain_name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "composed"

    def constitutional_contract(self):
        """
        合并所有 pack 的 constitutional contract，取最严值。
        结果惰性缓存（合约不可变，计算一次即可）。
        """
        if self._composed_contract is not None:
            return self._composed_contract

        from ystar.kernel.dimensions import ConstitutionalContract

        contracts = []
        for pack in self._packs:
            try:
                contracts.append(pack.constitutional_contract())
            except Exception:
                pass

        if not contracts:
            self._composed_contract = ConstitutionalContract()
            return self._composed_contract

        # 合并所有维度
        deny          = []
        deny_commands = []
        invariant     = []
        optional_inv  = []
        only_paths    = None   # None = 未受限（交集语义）
        only_domains  = None
        field_deny    = {}
        value_range   = {}

        for c in contracts:
            # 黑名单：取并集
            deny          = list(dict.fromkeys(deny + list(c.deny)))
            deny_commands = list(dict.fromkeys(deny_commands + list(c.deny_commands)))
            invariant     = list(dict.fromkeys(invariant + list(c.invariant)))
            optional_inv  = list(dict.fromkeys(optional_inv + list(c.optional_invariant)))

            # field_deny：并集
            for field_name, blocked in c.field_deny.items():
                existing = field_deny.get(field_name, [])
                field_deny[field_name] = list(dict.fromkeys(existing + list(blocked)))

            # value_range：取最严格（max 取最小，min 取最大）
            for param, bounds in c.value_range.items():
                if param not in value_range:
                    value_range[param] = dict(bounds)
                else:
                    existing = value_range[param]
                    new_max = bounds.get("max")
                    new_min = bounds.get("min")
                    if new_max is not None:
                        existing["max"] = min(
                            float(existing.get("max", new_max)),
                            float(new_max)
                        )
                    if new_min is not None:
                        existing["min"] = max(
                            float(existing.get("min", new_min)),
                            float(new_min)
                        )

            # only_paths：取交集（白名单越来越严）
            if c.only_paths:
                if only_paths is None:
                    only_paths = list(c.only_paths)
                else:
                    # 两个白名单取交集：保留双方都允许的路径
                    intersection = [
                        p for p in only_paths
                        if any(p.startswith(q.rstrip("/"))
                               or q.startswith(p.rstrip("/"))
                               for q in c.only_paths)
                    ]
                    only_paths = intersection

            # only_domains：取交集
            if c.only_domains:
                if only_domains is None:
                    only_domains = list(c.only_domains)
                else:
                    intersection = [d for d in only_domains if d in c.only_domains]
                    only_domains = intersection

        # 冲突检测：空白名单是陷阱（会拒绝所有请求）
        if only_paths is not None and len(only_paths) == 0:
            domain_names = [p.domain_name for p in self._packs if p.constitutional_contract().only_paths]
            raise ValueError(
                f"DomainPack.compose(): only_paths 白名单交集为空——"
                f"合并 {domain_names} 后没有任何路径被允许。"
                f"这会导致所有文件操作被拒绝。"
                f"请手动指定 only_paths，或去掉其中一个 pack 的 only_paths 约束。"
            )
        if only_domains is not None and len(only_domains) == 0:
            domain_names = [p.domain_name for p in self._packs if p.constitutional_contract().only_domains]
            raise ValueError(
                f"DomainPack.compose(): only_domains 白名单交集为空——"
                f"合并 {domain_names} 后没有任何域名被允许。"
                f"这会导致所有网络请求被拒绝。"
                f"请手动指定 only_domains，或调整其中一个 pack 的约束。"
            )

        self._composed_contract = ConstitutionalContract(
            deny          = deny,
            deny_commands = deny_commands,
            only_paths    = only_paths or [],
            only_domains  = only_domains or [],
            invariant     = invariant,
            optional_invariant = optional_inv,
            field_deny    = field_deny,
            value_range   = value_range,
            name          = self._name,
        )
        return self._composed_contract

    def vocabulary(self) -> dict:
        """合并所有 pack 的 vocabulary（取并集）。"""
        merged: dict = {
            "deny_keywords": [],
            "role_names":    [],
            "param_names":   [],
            "env_keywords":  [],
        }
        for pack in self._packs:
            try:
                v = pack.vocabulary()
                for key in merged:
                    merged[key] = list(dict.fromkeys(
                        merged[key] + list(v.get(key, []))
                    ))
            except Exception:
                pass
        return merged

    def make_contract(self, role: str, context: dict = None):
        """
        在组合 pack 中查找 role，返回第一个匹配的 contract，
        再与 composed constitutional contract 合并（取最严）。
        """
        from ystar.kernel.dimensions import IntentContract
        base = IntentContract()
        for pack in self._packs:
            try:
                c = pack.make_contract(role, context or {})
                if c and not c.is_empty():
                    base = c
                    break
            except Exception:
                pass
        return base

    def describe(self) -> str:
        sub = ", ".join(p.domain_name for p in self._packs)
        return f"ComposedDomainPack({sub})"

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
import time
import hashlib
from pathlib import Path as _Path
from .kernel.dimensions import IntentContract
from .kernel.engine import check as _check
from .kernel.cieu import emit

# Re-export Remediation + SkillActivation for convenience (AMENDMENT-012, 013)
__all__ = ["Policy", "PolicyResult", "Remediation", "SkillActivation", "IntentContract"]

# Static policy cache (keyed by AGENTS.md content hash)
_STATIC_POLICY_CACHE: Dict[str, Dict[str, Any]] = {}

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
class Remediation:
    """
    Structured remediation payload for DENY responses (AMENDMENT-012).

    Transform governance from "you can't" to "here's how you should".
    Every denial becomes a teaching moment with executable guidance.
    """
    wrong_action: str           # Agent 刚才做了什么（code/command 原样）
    correct_steps: list[str]    # 正确步骤序列（可执行代码/MCP 调用）
    skill_ref: str | None       # knowledge/{role}/skills/*.md 路径（完整参考）
    lesson_ref: str | None      # knowledge/{role}/lessons/*.md 或 CIEU incident_id
    rule_name: str              # Behavior rule 名称（可查 .ystar_session.json）
    rule_context: str | None = None  # 为什么有这条规则（1 句话背景）


@dataclass
class SkillActivation:
    """
    Proactive skill injection payload for ALLOW responses (AMENDMENT-013).

    Instead of waiting for violations, prime agent with relevant skills/templates
    before they execute actions. Every predictable pattern becomes a teaching moment.
    """
    skill_id: str               # e.g., "knowledge/ceo/skills/article_11_seven_layers.md"
    skill_content: str          # parsed markdown payload (not just path)
    trigger_rule: str           # which rule triggered this activation
    priority: int = 1           # when multiple skills activate, order matters (1=highest)
    role_filter: List[str] = field(default_factory=list)  # only activate for these roles (empty = all)


@dataclass
class PolicyResult:
    """Result of a Policy.check() call."""
    allowed:    bool
    reason:     str                   # "ok" or human-readable denial reason
    who:        str
    what:       str
    violations: List[Any] = field(default_factory=list)
    remediation: Optional[Remediation] = None      # AMENDMENT-012: structured teaching on DENY
    activation: Optional[SkillActivation] = None   # AMENDMENT-013: proactive skill injection on ALLOW

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        status = "allow" if self.allowed else f"deny({self.reason})"
        parts = [f"PolicyResult({self.who}.{self.what} → {status})"]
        if self.remediation:
            parts.append(f"[remediation: {self.remediation.rule_name}]")
        if self.activation:
            parts.append(f"[activation: {self.activation.skill_id}]")
        return " ".join(parts)


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

    @staticmethod
    def _compute_agents_md_hash(file_path: str) -> str:
        """Compute MD5 hash of AGENTS.md for cache key."""
        p = _Path(file_path)
        if not p.exists():
            return ""
        with open(p, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    @classmethod
    def _parse_static_policy(cls, file_path: str) -> Dict[str, Any]:
        """
        Parse static parts of AGENTS.md (never change per-session).

        Returns dict with:
        - global_deny: List[str]
        - global_deny_commands: List[str]
        """
        # Check cache first
        cache_key = cls._compute_agents_md_hash(file_path)
        if cache_key and cache_key in _STATIC_POLICY_CACHE:
            return _STATIC_POLICY_CACHE[cache_key]

        # Parse AGENTS.md
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        static_policy = {
            "global_deny": [],
            "global_deny_commands": [],
        }

        # Extract Forbidden Paths section
        for header in ["### Forbidden Paths", "## Forbidden Paths"]:
            if header in content:
                section = content.split(header)[1].split("#")[0]
                for line in section.split('\n'):
                    stripped = line.strip()
                    if stripped.startswith('-'):
                        path_str = stripped[1:].strip()
                        # Handle comma-separated paths (e.g., "- .env, .secret")
                        if ',' in path_str:
                            paths = [p.strip() for p in path_str.split(',')]
                            for p in paths:
                                if p and not p.startswith('#'):
                                    static_policy["global_deny"].append(p)
                        elif path_str and not path_str.startswith('#'):
                            static_policy["global_deny"].append(path_str)
                break

        # Extract Forbidden Commands section
        for header in ["### Forbidden Commands", "## Forbidden Commands"]:
            if header in content:
                section = content.split(header)[1].split("#")[0]
                for line in section.split('\n'):
                    stripped = line.strip()
                    if stripped.startswith('-'):
                        cmd = stripped[1:].strip()
                        if cmd and not cmd.startswith('#'):
                            static_policy["global_deny_commands"].append(cmd)
                break

        # Cache result
        if cache_key:
            _STATIC_POLICY_CACHE[cache_key] = static_policy

        return static_policy

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

        Performance: Static policy (Forbidden Paths/Commands) is cached by
        AGENTS.md content hash. Cache hit: <1ms. Cache miss: ~100-200ms.
        """
        from pathlib import Path as _Path

        # Performance timing
        start = time.perf_counter()

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

        # ── 1. Parse static policy (cached) ───────────────────────────
        cache_key = cls._compute_agents_md_hash(path)
        cache_hit = cache_key in _STATIC_POLICY_CACHE

        static = cls._parse_static_policy(path)
        global_deny = static["global_deny"]
        global_deny_commands = static["global_deny_commands"]

        # ── 2. Parse dynamic policy (per-agent roles) ─────────────────
        with open(path, encoding="utf-8") as f:
            text = f.read()

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


# ── Layer 1: Identity Source of Truth (AMENDMENT-015 Phase 4) ────────

# Session schema required keys (Patch 2 from CIEU K9 Ryan rsync disaster 2026-04-14)
_SESSION_SCHEMA_REQUIRED = [
    "immutable_paths",
    "override_roles",
    "contract",
    "agent_behavior_rules"
]


def _validate_session_schema(config: Dict[str, Any], path: str) -> None:
    """
    Validate session config has required schema keys.

    Raises SESSION_JSON_SCHEMA_VIOLATION CIEU + SchemaError if required keys missing.
    This prevents silent acceptance of truncated/corrupted session.json (e.g., rsync --delete
    overwriting with test fixture).

    Args:
        config: Session config dict
        path: Path to session file (for CIEU context)

    Raises:
        ValueError: If required keys missing
    """
    missing = [k for k in _SESSION_SCHEMA_REQUIRED if k not in config]
    if missing:
        emit(
            "SESSION_JSON_SCHEMA_VIOLATION",
            who="kernel",
            what="load_session_config",
            legitimacy=False,
            reason=f"Missing required keys {missing} in {path}",
            context={
                "path": path,
                "missing_keys": missing,
                "present_keys": list(config.keys())
            }
        )
        raise ValueError(
            f"Invalid session config at {path}: missing required keys {missing}. "
            f"This is likely a corrupted/truncated session.json. "
            f"Found keys: {list(config.keys())}"
        )


def load_session_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load .ystar_session.json from disk (single source of truth).

    Args:
        path: Explicit path to session config. If None, searches current dir.

    Returns:
        Session config dict, or empty dict if not found.

    Raises:
        ValueError: If session config missing required schema keys (Patch 2)
    """
    import json

    if path is None:
        # Search current directory
        candidate = _Path(".ystar_session.json")
        if candidate.exists():
            path = str(candidate)
        else:
            return {}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Validate schema (Patch 2: prevent silent acceptance of corrupted session.json)
        if config:  # Only validate non-empty configs
            _validate_session_schema(config, path)

        return config
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_session_config(config: Dict[str, Any], path: Optional[str] = None) -> None:
    """
    Save session config to .ystar_session.json atomically.

    Args:
        config: Session config dict
        path: Explicit path. If None, writes to .ystar_session.json in cwd.
    """
    import json

    if path is None:
        path = ".ystar_session.json"

    # Atomic write: write to temp file, then rename
    temp_path = f"{path}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

    _Path(temp_path).replace(path)


def current_agent() -> str:
    """
    Get current active agent ID from session config.

    Returns:
        Agent ID string (e.g., 'ceo', 'cto', 'eng-kernel'), or 'agent' as fallback.
    """
    config = load_session_config()

    # Check agent_stack first (top of stack is current agent)
    agent_stack = config.get("agent_stack", [])
    if agent_stack:
        return agent_stack[-1]

    # Fallback to legacy agent_id field
    agent_id = config.get("agent_id", "")
    if agent_id:
        return agent_id

    # Ultimate fallback
    return "agent"


def push_agent(agent_id: str, session_config_path: Optional[str] = None) -> None:
    """
    Push new agent onto identity stack (for sub-agent delegation).

    Args:
        agent_id: Agent ID to activate (e.g., 'cto')
        session_config_path: Path to session config (None = auto-detect)

    Example:
        # CEO delegates to CTO
        push_agent('cto')
        # Now current_agent() returns 'cto'
    """
    config = load_session_config(session_config_path)

    # Initialize agent_stack if not present
    if "agent_stack" not in config:
        # Bootstrap from legacy agent_id if present
        existing = config.get("agent_id", "agent")
        config["agent_stack"] = [existing]

    # Push new agent
    config["agent_stack"].append(agent_id)

    # Update legacy agent_id field for backward compatibility
    config["agent_id"] = agent_id

    save_session_config(config, session_config_path)

    # Emit CIEU event (fail-open)
    try:
        from .governance.cieu_store import CIEUStore
        store = CIEUStore()
        store.write_dict({
            "event_type": "AGENT_PUSH",
            "agent_id": agent_id,
            "decision": "allow",
            "evidence_grade": "ops",
            "params": {"agent_stack": config["agent_stack"]},
        })
    except Exception:
        pass  # fail-open


def pop_agent(session_config_path: Optional[str] = None) -> str:
    """
    Pop agent from identity stack (restore caller after sub-agent completes).

    Args:
        session_config_path: Path to session config (None = auto-detect)

    Returns:
        Restored agent ID (now current)

    Example:
        # CTO sub-agent completes, restore CEO
        restored = pop_agent()
        # Now current_agent() returns 'ceo'
    """
    config = load_session_config(session_config_path)

    agent_stack = config.get("agent_stack", [])
    if not agent_stack:
        # Nothing to pop, return fallback
        return "agent"

    if len(agent_stack) == 1:
        # Don't pop the last agent (root agent must remain)
        return agent_stack[0]

    # Pop sub-agent
    popped = agent_stack.pop()

    # Update legacy agent_id field
    config["agent_id"] = agent_stack[-1]

    save_session_config(config, session_config_path)

    # Emit CIEU event (fail-open)
    try:
        from .governance.cieu_store import CIEUStore
        store = CIEUStore()
        store.write_dict({
            "event_type": "AGENT_POP",
            "agent_id": agent_stack[-1],
            "decision": "allow",
            "evidence_grade": "ops",
            "params": {
                "popped_agent": popped,
                "restored_agent": agent_stack[-1],
                "agent_stack": agent_stack
            },
        })
    except Exception:
        pass  # fail-open

    return agent_stack[-1]


def set_agent(agent_id: str, session_config_path: Optional[str] = None) -> None:
    """
    Set agent ID directly (replace entire stack with single agent).

    Use this for initial session setup. For delegation, use push_agent/pop_agent.

    Args:
        agent_id: Agent ID to set (e.g., 'ceo')
        session_config_path: Path to session config (None = auto-detect)
    """
    config = load_session_config(session_config_path)

    # Replace stack with single agent
    config["agent_stack"] = [agent_id]
    config["agent_id"] = agent_id

    save_session_config(config, session_config_path)

    # Emit CIEU event (fail-open)
    try:
        from .governance.cieu_store import CIEUStore
        store = CIEUStore()
        store.write_dict({
            "event_type": "AGENT_SET",
            "agent_id": agent_id,
            "decision": "allow",
            "evidence_grade": "ops",
            "params": {"agent_stack": [agent_id]},
        })
    except Exception:
        pass  # fail-open


def check_agent_stack_timeout(timeout_seconds: int = 300, session_config_path: Optional[str] = None) -> bool:
    """
    Check if agent_stack is stale (unchanged for > timeout_seconds).

    If stale, auto-pop to root agent. Guards against sub-agent crashes.

    Args:
        timeout_seconds: Timeout threshold (default 300s = 5min)
        session_config_path: Path to session config (None = auto-detect)

    Returns:
        True if stack was stale and auto-popped, False otherwise
    """
    config = load_session_config(session_config_path)

    agent_stack = config.get("agent_stack", [])
    if len(agent_stack) <= 1:
        # Only root agent, nothing to timeout
        return False

    # Check last_agent_change timestamp
    last_change = config.get("agent_stack_last_change", 0)
    now = time.time()

    if now - last_change > timeout_seconds:
        # Timeout: reset to root agent
        root_agent = agent_stack[0]
        config["agent_stack"] = [root_agent]
        config["agent_id"] = root_agent
        config["agent_stack_last_change"] = now

        save_session_config(config, session_config_path)

        # Emit CIEU event
        try:
            from .governance.cieu_store import CIEUStore
            store = CIEUStore()
            store.write_dict({
                "event_type": "AGENT_STACK_TIMEOUT",
                "agent_id": root_agent,
                "decision": "allow",
                "evidence_grade": "ops",
                "params": {
                    "stale_stack": agent_stack,
                    "restored_agent": root_agent,
                    "timeout_seconds": timeout_seconds,
                },
            })
        except Exception:
            pass  # fail-open

        return True

    return False

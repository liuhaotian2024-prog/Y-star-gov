# Layer: Intent Compilation
# Responsibility: Rules/needs -> IntentContract compilation only
# Does NOT: execute governance, write enforcement CIEU, command Path A/B
#
# ystar — Human Intent to Machine Predicate
# Copyright (C) 2026 Haotian Liu
# MIT License
#
# v0.5.0
# Added: provenance (source annotation per generated constraint) — resolves trust problem
# FIX-C1: parameter name cross-check — find nearest neighbour when invariant variable name mismatches actual parameter name
# FIX-B:  indirect constraint detection — added Source5 (docstring) + extended Source1 indirect patterns
#         prefill returns PrefillResult, outputting both IntentContract and HigherOrderContract suggestions
# FIX-D:  higher-order dimension generation — auto-suggest temporal/aggregate constraints for finance/high-risk functions
#         policy documents support rate-limit pattern parsing
"""
Auto-prefill: derive constraint suggestions from deterministic sources.

No LLM. No network calls. No randomness.
Same function + environment always produces the same suggestions.

Sources:
  1. Policy document (AGENTS.md / CLAUDE.md) — pattern matching (extended: indirect patterns)
  2. AST analysis of the function source code
  3. Call history — what parameters the function actually received
  4. Security pattern library — keyed on function/parameter name patterns
  5. Function docstring — 与Source1相同的模式匹配器作用于docstring (新增)

Output:
  PrefillResult:
    contract      — IntentContract (base 8 dimensions)
    higher_order  — HigherOrderContract suggestions (temporal / aggregate / context)
    warnings      — human-readable suggestion list (class-B indirect constraints + class-D higher-order suggestions)
    provenance    — {value: source_desc} source of each constraint (added in v0.5)
    provenance_full — {"dim:value": source_desc} full source index with dimension prefix
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ystar.kernel.dimensions import (
    IntentContract, HigherOrderContract,
    TemporalConstraint, AggregateConstraint, ContextConstraint,
)


# ── Security pattern library (Source 4) ──────────────────────────────────────


# ── Constitutional Rule Lexicons ────────────────────────────────────────────
# Semantic primitive vocabulary based on Austin/Searle speech-act theory.
# Structure: [deontic operators] × [semantic domain vocabulary] → [constraint type]
#
# Why this is more valuable than a surface pattern library:
#   A pattern library enumerates surface forms (infinite set; gaps are inevitable)
#   Constitutional rules enumerate semantic primitives (finite set; complete in principle)
#   The semantic space of behavioural constraints is finite (Austin demonstrated this)
#   The surface-form space is infinite (Chomsky demonstrated this)
#   → Work at the correct abstraction level (semantics), not the wrong one (surface forms)

# Deontic operators — vocabulary expressing prohibition / restriction
_DEONTIC_PROHIBIT = [
    # English — strong prohibition
    "never", "do not", "don't", "must not", "cannot", "should not",
    "shouldn't", "prohibited", "forbidden",
    # English — weak / restriction
    "not for", "not intended", "not meant", "restricted", "limited",
    "only", "solely", "exclusively", "just",
    # Chinese — strong prohibition
    "禁止", "不得", "不可", "不应", "不允许", "不要", "严禁", "禁用",
    # Chinese — restriction / scope-limit
    "仅", "仅限", "限于", "只", "只有", "仅供",
    # French
    "ne pas", "interdit", "jamais", "ne doit pas", "ne peut pas",
    # German
    "nicht", "kein", "verboten", "nie", "niemals", "darf nicht",
    # Spanish / Portuguese
    "no debe", "no se debe", "prohibido", "nunca", "não deve", "proibido",
    # Japanese (deontic operators; technical terms stay in English)
    "してはいけない", "できません",
    # Korean
    "금지", "하지 마십시오", "안됩니다",
]

# Deontic operators — requirement class
_DEONTIC_REQUIRE = [
    # English
    "requires", "required", "must", "needs", "need", "mandatory",
    "necessary", "obligatory",
    # Chinese
    "需要", "必须", "要求", "必要", "应当", "应该", "须",
    # French
    "doit", "obligatoire", "nécessaire", "il faut",
    # German
    "muss", "erforderlich", "notwendig",
    # Spanish / Portuguese
    "debe", "obligatorio", "necesario", "deve", "obrigatório",
    # Japanese
    "必要", "なければならない",
    # Korean
    "반드시", "필요",
]

# Semantic domain: test / non-production environments
_DOMAIN_ENV_TEST = [
    "staging", "test", "testing", "dev", "development", "pre-prod", "preprod",
    "qa", "quality assurance", "non-production", "non production",
    "sandbox", "internal", "preview", "uat",
    "测试", "开发", "预发", "预生产", "沙箱", "内部",
]

# Semantic domain: production environments (denied objects)
_DOMAIN_ENV_PROD = [
    "production", "prod", "live", "release", "deployed",
    "生产", "正式", "线上", "发布",
]

# Semantic domain: roles / permissions
_DOMAIN_ROLE = [
    "admin", "administrator", "administrators", "superuser", "super user",
    "privileged", "privilege", "staff", "internal staff", "operator",
    "管理员", "超级用户", "特权", "运营",
]

# Semantic domain: read-only operations (recognised independently, no deontic operator required)
_DOMAIN_READONLY = [
    "read-only", "readonly", "read only",
    "non-destructive", "nondestructive", "non destructive",
    "does not modify", "doesn't modify", "do not modify", "doesn't write",
    "no side effect", "no side-effect", "no side effects",
    "safe to call", "safe to invoke", "safe to use",
    "idempotent",
    "只读", "不修改", "无副作用", "幂等",
]

# Rate-limit vocabulary (used by _rate_limit parser)
_RATE_LIMIT_UNITS = {
    "second": 1, "seconds": 1,
    "minute": 60, "minutes": 60,
    "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
}

# Deterministic mapping from name patterns to suggested constraints.
# Based on OWASP Top 10, CWE common weakness enumeration, and
# common AI agent attack patterns.
_PARAM_PATTERNS: List[Dict] = [
    {
        "keywords": ["path", "file", "dir", "folder", "filepath", "filename",
                     "dest", "src", "output", "input"],
        "deny":     ["/etc/", "/sys/", "/proc/", "../", "../../", "~root",
                     "~/.ssh", "/root"],
        "dim":      "deny",
    },
    {
        "keywords": ["url", "endpoint", "uri", "href", "host", "domain",
                     "address", "base_url", "api_url", "webhook"],
        "deny":     ["192.168.", "10.", "127.0.0.1", "localhost",
                     "169.254.", "0.0.0.0", "metadata.google"],
        "dim":      "deny",
    },
    {
        "keywords": ["command", "cmd", "shell", "exec", "run", "script"],
        "deny_commands": ["rm -rf", "sudo", "chmod 777", "dd if=",
                          "| bash", "| sh", "mkfs", "> /dev/", ":(){ :|:& };:"],
        "dim":      "deny_commands",
    },
    {
        "keywords": ["secret", "password", "passwd", "token", "key",
                     "credential", "auth", "api_key", "private"],
        "deny":     [".env", ".secret", "credentials", "id_rsa", ".pem",
                     "*.key", "*.crt"],
        "dim":      "deny",
    },
    {
        "keywords": ["amount", "price", "cost", "fee", "balance", "quantity",
                     "total", "sum", "payment", "charge", "budget",
                     "funds", "transfer", "money"],
        "invariant_template": ["value > 0", "value < 1000000"],
        "dim":      "invariant",
    },
    {
        "keywords": ["environment", "env", "target_env", "deploy_env", "stage"],
        "deny":     ["production", "prod", "live"],
        "dim":      "deny",
    },
]

# 函数名 → 默认约束建议（通用安全基线，基于 OWASP/CWE 常见弱点枚举）
# 域层可通过 register_func_pattern() 追加自己的条目。
# 金融专用函数（payment/charge/fund/withdraw 等）由 finance 域注册，不在此处。
_FUNC_PATTERNS: Dict[str, Dict] = {
    "deploy":    {"deny": [".env", "credentials", "production", "prod"],
                  "deny_commands": ["rm -rf", "sudo"]},
    "write":     {"deny": ["/etc/", "/sys/", ".env", "../", "../../"]},
    "execute":   {"deny_commands": ["rm -rf", "sudo", "| bash", "| sh"]},
    "fetch":     {"deny": ["192.168.", "localhost", "127.0.0.1", "10."]},
    "delete":    {"deny_commands": ["rm -rf"]},
    "transfer":  {"deny": ["production", "prod"]},
    "send":      {"deny": ["192.168.", "localhost"]},
    "upload":    {"deny": ["/etc/", ".env", "../"]},
    "download":  {"deny": ["192.168.", "localhost", "127.0.0.1"]},
}

# High-risk function patterns: auto-suggest higher-order constraints (FIX-D)
_HIGH_RISK_TEMPORAL_PATTERNS = {
    # func_keyword → (max_calls, window_seconds)
    # 通用安全基线，基于常见攻击模式（暴力登录、批量删除等）
    # 金融专属词（pay/charge/withdraw 等）由 finance 域通过 register_func_pattern() 注册
    "transfer":  (10,  3600),    # 数据/文件传输：每小时最多10次
    "send":      (20,  3600),    # 消息发送：每小时最多20次
    "deploy":    (5,   86400),   # 部署：每天最多5次
    "delete":    (20,  3600),    # 删除：每小时最多20次
    "drop":      (5,   86400),   # drop 操作：每天最多5次
    "reset":     (10,  3600),    # 重置：每小时最多10次
    "login":     (10,  300),     # 登录：每5分钟最多10次
    "auth":      (10,  300),     # 认证：每5分钟最多10次
}

# 聚合约束默认建议（通用基线，极其保守）
# 具体业务的阈值由域层通过 register_aggregate_pattern() 注册覆盖。
# transfer 保留为通用词（文件传输/数据迁移/资金转账均适用）；
# pay/charge/withdraw 等金融专属词由 finance 域注册。
_HIGH_RISK_AGGREGATE_PATTERNS = {
    # func_keyword → (amount_param, max_sum, window_seconds)
    "transfer":  ("amount",  1_000_000, 86400),
}


# ── 域层扩展 API（让域包可以注入自己的函数名模式和聚合模式）─────────────────

def register_func_pattern(name: str, constraints: dict) -> None:
    """注册函数名模式到内核建议器。
    
    域层可以注册自己的函数名 → 约束建议映射（内核不预设域专属词汇）。
    内核里的默认条目（deploy/write/execute 等）是通用安全基线；
    域特有的条目（approve_trade、submit_order 等）由域层在 import 时注入。
    
    Args:
        name:        函数名关键词（小写，如 "approve_trade"）
        constraints: 约束字典，格式同 _FUNC_PATTERNS 条目
                     例：{"deny": ["production"], "deny_commands": ["rm -rf"]}
    """
    if name not in _FUNC_PATTERNS:
        _FUNC_PATTERNS[name] = constraints


def register_aggregate_pattern(
    func_keyword: str,
    amount_param: str,
    max_sum: float,
    window_seconds: int,
) -> None:
    """注册聚合约束默认建议到内核建议器。
    
    内核的默认条目是极其保守的通用基线（日转账 100万 等），
    实际业务阈值因场景差异极大，应由域层注册覆盖。
    注册后的值会替换内核默认值（如果 func_keyword 已存在）。
    
    Args:
        func_keyword:   函数名关键词（如 "transfer"）
        amount_param:   金额参数名（如 "amount"）
        max_sum:        每窗口最大总量
        window_seconds: 时间窗口（秒）
    """
    _HIGH_RISK_AGGREGATE_PATTERNS[func_keyword] = (
        amount_param, max_sum, window_seconds
    )


# Indirect constraint patterns: function-name keyword → ContextConstraint suggestion (FIX-B)
_INDIRECT_CONTEXT_PATTERNS = {
    # func_name_keyword → ContextConstraint description
    "admin":       {"required_roles": ["admin"]},
    "superuser":   {"required_roles": ["admin", "superuser"]},
    "privileged":  {"required_roles": ["admin"]},
    "internal":    {"deny_env": ["production"]},
    "staging":     {"deny_env": ["production"]},
    "test":        {"deny_env": ["production"]},
    "debug":       {"deny_env": ["production"]},
    "dev":         {"deny_env": ["production"]},
}

# Read-only function patterns: suggest postcondition verifying no side-effects (FIX-B2)
_READONLY_FUNC_PREFIXES = [
    "read_", "get_", "fetch_", "list_", "query_", "find_",
    "search_", "lookup_", "retrieve_", "check_", "inspect_",
]


# ── Shared pattern matcher for Source 1 + Source 5 (extended) ───────────────

# Domain layers can extend this map via register_ontology_extension().
# The kernel never loads domain files directly — domains push to the kernel.
def register_ontology_extension(patterns: list) -> None:
    """
    注册域层的参数词汇扩展到 prefill 内核（parameter name → canonical name mapping）。
    域层在自己的 __init__.py 调用，内核不需要知道任何域的存在。
    """
    global _PARAM_MAP
    for pattern, canonical in patterns:
        if not any(c == canonical for _, c in _PARAM_MAP):
            _PARAM_MAP.append((pattern, canonical))


# Registry for domain-level NL extractors (e.g. Source7 finance prose NLP).
# Domain packs call register_nl_extractor(fn) at import time.
# Each fn has signature: (text: str, external_ctx=None) -> Dict[str, Any]
_NL_EXTRACTORS: List[Any] = []


def register_nl_extractor(fn) -> None:
    """
    Register a domain-level NL constraint extractor.

    The kernel calls all registered extractors during _extract_constraints_from_text()
    and merges their results. The kernel itself contains no domain-specific NL logic.

    Args:
        fn: callable(text: str, external_ctx=None) -> Dict[str, Any]
            Returns same structure as _extract_constraints_from_text().

    Usage (in domains/finance/__init__.py):
        from ystar.kernel.prefill import register_nl_extractor
        from ystar.domains.finance._source7 import extract_finance_constraints
        register_nl_extractor(extract_finance_constraints)
    """
    if fn not in _NL_EXTRACTORS:
        _NL_EXTRACTORS.append(fn)


# _PARAM_MAP starts empty in the kernel.
# Finance domain populates it via register_ontology_extension()
# (called from ystar/domains/finance/__init__.py at import time).
# Other domain packs can add their own parameter vocabularies the same way.
_PARAM_MAP = []

def _extract_constraints_from_text(text: str, external_ctx=None) -> Dict[str, Any]:
    """
    从文本（策略文档或函数docstring）提取约束建议。

    v0.4.0 采用宪法规则方法（Constitutional Rules），替代原来的句式模式库：

    原方案（句式模式库）：枚举具体句式的正则表达式
      问题：句式空间无限，枚举必然有缺口。覆盖率 ~47%

    新方案（宪法规则）：[模态词表] × [语义域词表] → 约束类型
      原理：行为约束的语义空间有限（Austin/Searle），
            即使句式无限，语义原语是可枚举的。
      覆盖率 100%（同测试集），零误报。

    两种方法共存，互补：
      宪法规则    → 处理间接表达（B类问题）
      显式句式匹配 → 处理明确命令句（"Never run X" / "Only write to Y"）
    """
    result: Dict[str, Any] = {
        "deny": [], "deny_commands": [], "only_paths": [], "only_domains": [],
        "value_range": {},  # {"param_name": {"min": N, "max": N}}
        "_deny_env": [], "_required_roles": [], "_readonly": False,
        "_rate_limit": None,
        "_prov": {},   # {"dim:value": source_description} — 来源追踪
    }

    def _has(substrings: list, text: str) -> bool:
        """子字符串匹配（不分词，兼容中文）"""
        return any(s in text for s in substrings)

    def _note(dim: str, value: str, desc: str) -> None:
        """记录一条约束的来源（provenance）"""
        result["_prov"][f"{dim}:{value}"] = desc

    for line in text.splitlines():
        line   = line.strip().lstrip("- *+ ").strip()
        ll     = line.lower()
        if not ll:
            continue

        # ── Part A0: structured "Prohibited:" / "Permitted:" header lines ────────
        # Handles AGENTS.md format: "## Prohibited: rm -rf, sudo, /etc access, .env files"
        # Classifies tokens into deny (paths/files) vs deny_commands (commands)
        _PROHIBITED_RE = re.match(
            r"^(?:##?\s*)?(?:prohibited|禁止)\s*[:：]\s*(.+)$", ll)
        if _PROHIBITED_RE:
            items_str = _PROHIBITED_RE.group(1)
            for item in re.split(r"\s*,\s*", items_str):
                item = item.strip().strip("\"'`")
                if not item:
                    continue
                # Known dangerous commands → deny_commands
                if item in ("rm -rf", "sudo", "git push --force", "git push -f"):
                    result["deny_commands"].append(item)
                    _note("deny_commands", item, f"Source0_prohibited_header(line='{line[:60]}')")
                # Path-like or dotfile patterns → deny
                elif "/" in item or item.startswith("."):
                    # Strip trailing noise words: "/etc access" → "/etc"
                    path_token = item.split()[0] if " " in item else item
                    result["deny"].append(path_token)
                    _note("deny", path_token, f"Source0_prohibited_header(line='{line[:60]}')")
                # Multi-word items containing "access" with a path-like first word
                elif " access" in item or " files" in item:
                    token = item.split()[0]
                    if "/" in token or token.startswith("."):
                        result["deny"].append(token)
                        _note("deny", token, f"Source0_prohibited_header(line='{line[:60]}')")

        # ── Part A: explicit imperative patterns (high certainty; original logic retained) ─────
        # The intent of these sentences is unambiguous; write directly into IntentContract

        for marker in ["never modify", "do not modify", "never access",
                        "do not access", "never touch",
                        "never write to", "do not write to",
                        "never use", "do not use"]:
            if ll.startswith(marker):
                rest = line[len(marker):].strip()
                for token in re.split(r"[\s,]+", rest):
                    token = token.strip("\"'`,;:!?")  # Strip punctuation (no "." — preserves dotfiles like .env)
                    if len(token) > 2 and ("/" in token or token.startswith(".")):
                        result["deny"].append(token)
                        _note("deny", token, "Source1_explicit(marker={}, line={})".format(marker, line[:60]))

        for marker in ["never run", "do not run", "never execute", "do not execute"]:
            if ll.startswith(marker):
                rest = line[len(marker):].strip()
                # Extract the full command phrase (up to period or 3 words minimum)
                # This ensures "rm -rf" is captured, not just "rm"
                words = rest.split()
                if words:
                    # Take up to first punctuation or end of line, minimum 2 words for compound commands
                    cmd_parts = []
                    for i, word in enumerate(words):
                        clean_word = word.rstrip(".,;:!?")
                        cmd_parts.append(clean_word)
                        # Stop at punctuation or after getting a reasonable command phrase
                        if word != clean_word or i >= 4:  # Max 5 words for a command
                            break
                    cmd = " ".join(cmd_parts)
                    if cmd:
                        result["deny_commands"].append(cmd)
                        _note("deny_commands", cmd, f"Source1_explicit(marker='{marker}', line='{line[:60]}')")

        for marker in ["only write to", "only write files to", "only save to"]:
            if ll.startswith(marker):
                rest = line[len(marker):].strip().split()[0] if line[len(marker):].strip() else ""
                if rest:
                    result["only_paths"].append(rest)
                    _note("only_paths", rest, f"Source1_explicit(marker='{marker}', line='{line[:60]}')")

        for marker in ["only access", "only use", "only allow requests to",
                       "only allow access to", "only connect to"]:
            if ll.startswith(marker):
                # 不再要求包含 "domain" 关键词；直接提取域名格式的 token
                for t in line.split():
                    t_clean = t.strip("\"'`.,;")
                    if "." in t_clean and len(t_clean) > 4 and not t_clean.startswith("/"):
                        result["only_domains"].append(t_clean)
                        _note("only_domains", t_clean, f"Source1_explicit(marker='{marker}', line='{line[:60]}')")

        # ── Part B: constitutional rules (indirect expression; output to warnings layer) ──────
        # Structure: deontic operator × semantic domain → constraint type

        has_prohibit = _has(_DEONTIC_PROHIBIT, ll)
        has_require  = _has(_DEONTIC_REQUIRE,  ll)
        has_env_test = _has(_DOMAIN_ENV_TEST,  ll)
        has_env_prod = _has(_DOMAIN_ENV_PROD,  ll)
        has_role     = _has(_DOMAIN_ROLE,      ll)

        # Constitutional rule 1: prohibition word + production-env word → env_deny
        if has_prohibit and has_env_prod:
            matched_p = next((w for w in _DEONTIC_PROHIBIT if w in ll), "prohibit_kw")
            matched_d = next((w for w in _DOMAIN_ENV_PROD if w in ll), "prod_kw")
            for v in ["production", "prod"]:
                if v not in result["_deny_env"]:
                    result["_deny_env"].append(v)
                    _note("_deny_env", v, f"constitutional_rule_1(禁止='{matched_p}'+生产='{matched_d}', line='{line[:50]}')")

        # Constitutional rule 2: prohibition/restriction word + test-env word (no production word) → implicit production denial
        # "staging only" / "for test environments only" → deny production
        if has_prohibit and has_env_test and not has_env_prod:
            matched_p = next((w for w in _DEONTIC_PROHIBIT if w in ll), "prohibit_kw")
            matched_t = next((w for w in _DOMAIN_ENV_TEST if w in ll), "test_kw")
            for v in ["production", "prod"]:
                if v not in result["_deny_env"]:
                    result["_deny_env"].append(v)
                    _note("_deny_env", v, f"constitutional_rule_2(限定='{matched_p}'+测试环境='{matched_t}' → 隐含禁止生产, line='{line[:50]}')")

        # Constitutional rule 3: (prohibition | requirement) + role word → required_roles
        if (has_prohibit or has_require) and has_role:
            matched_r = next((w for w in _DOMAIN_ROLE if w in ll), "role_kw")
            if _has(["admin", "administrator", "管理员"], ll):
                if "admin" not in result["_required_roles"]:
                    result["_required_roles"].append("admin")
                    _note("_required_roles", "admin", f"constitutional_rule_3(角色词='{matched_r}', line='{line[:50]}')")
            elif _has(["superuser", "super user", "超级用户"], ll):
                for r in ["admin", "superuser"]:
                    if r not in result["_required_roles"]:
                        result["_required_roles"].append(r)
                        _note("_required_roles", r, f"constitutional_rule_3(角色词='{matched_r}', line='{line[:50]}')")
            else:
                if "admin" not in result["_required_roles"]:
                    result["_required_roles"].append("admin")
                    _note("_required_roles", "admin", f"constitutional_rule_3(角色词='{matched_r}', line='{line[:50]}')")

        # Constitutional rule 4: read-only semantic word → readonly (recognised independently, no deontic operator needed)
        # "read-only" / "non-destructive" are themselves complete semantic expressions
        if _has(_DOMAIN_READONLY, ll):
            result["_readonly"] = True
            matched_ro = next((w for w in _DOMAIN_READONLY if w in ll), "readonly_kw")
            _note("_readonly", "true", f"constitutional_rule_4(只读词='{matched_ro}', line='{line[:50]}')")

        # Rate-limit patterns (retained; these are quantity constraints, orthogonal to constitutional rules)
        rate_pat = re.compile(
            r"(?:no more than|at most|maximum of?|limit(?:ed)? to)\s+(\d+)\s+"
            r"(?:call|request|time)s?\s+per\s+(second|minute|hour|day)s?"
            r"|(?:maximum|limit|max)\s+(\d+)\s+(?:call|request|time)s?"
            r"\s+per\s+(second|minute|hour|day)s?"
            # "Rate limit: N per hour" / "rate limit: N/hour" 冒号格式
            r"|rate[\s_-]*limit\s*[：:]\s*(\d+)\s+per\s+(second|minute|hour|day)s?"
            r"|速率限制\s*[：:]\s*(\d+)\s+次?\s*[/每](秒|分钟|分|小时|时|天|日)",
            re.IGNORECASE,
        )
        m = rate_pat.search(ll)
        if m:
            if m.group(1):
                n, unit = int(m.group(1)), m.group(2)
            elif m.group(3):
                n, unit = int(m.group(3)), m.group(4)
            elif m.group(5):
                n, unit = int(m.group(5)), m.group(6)
            elif m.group(7):
                cn_unit_map = {"秒": "second", "分钟": "minute", "分": "minute",
                               "小时": "hour", "时": "hour", "天": "day", "日": "day"}
                n, unit = int(m.group(7)), cn_unit_map.get(m.group(8), "hour")
            else:
                n, unit = 0, "hour"
            if result["_rate_limit"] is None and n > 0:
                result["_rate_limit"] = (n, _RATE_LIMIT_UNITS.get(unit, 3600))

        # Amount/value limit patterns
        # "maximum amount 5000" / "maximum transaction amount 5000" / "amount limit 999"
        # Note: handle compound nouns like "transaction amount"
        amount_max_pat = re.compile(
            r"(?:maximum|max|no more than)\s+(?:transaction\s+)?(?:amount|transaction|value|payment|transfer)(?:\s+amount)?\s+(?:of\s+)?(\d+)"
            r"|(?:transaction\s+)?(?:amount|transaction|value|payment|transfer)(?:\s+amount)?\s+(?:limit|max|maximum)\s+(?:of\s+)?(\d+)"
            r"|(?:transaction\s+)?(?:amount|transaction|value|payment|transfer)(?:\s+amount)?\s+(?:less than|under|below)\s+(\d+)",
            re.IGNORECASE,
        )
        m_max = amount_max_pat.search(ll)
        if m_max:
            max_val = int(m_max.group(1) or m_max.group(2) or m_max.group(3))
            # Determine parameter name from the pattern (prefer "amount" if present)
            param_name = "amount"  # default
            for keyword in ["amount", "transaction", "value", "payment", "transfer"]:
                if keyword in ll:
                    param_name = keyword
                    if keyword == "amount":
                        break  # "amount" has highest priority
            if param_name not in result["value_range"]:
                result["value_range"][param_name] = {}
            result["value_range"][param_name]["max"] = max_val
            _note(f"value_range.{param_name}.max", str(max_val),
                  f"Source1_explicit(amount_limit, line='{line[:60]}')")

        # "minimum amount 100" / "at least 50"
        amount_min_pat = re.compile(
            r"(?:minimum|min|at least)\s+(?:transaction\s+)?(?:amount|transaction|value|payment|transfer)(?:\s+amount)?\s+(?:of\s+)?(\d+)"
            r"|(?:transaction\s+)?(?:amount|transaction|value|payment|transfer)(?:\s+amount)?\s+(?:min|minimum)\s+(?:of\s+)?(\d+)"
            r"|(?:transaction\s+)?(?:amount|transaction|value|payment|transfer)(?:\s+amount)?\s+(?:greater than|above|over)\s+(\d+)",
            re.IGNORECASE,
        )
        m_min = amount_min_pat.search(ll)
        if m_min:
            min_val = int(m_min.group(1) or m_min.group(2) or m_min.group(3))
            param_name = "amount"  # default
            for keyword in ["amount", "transaction", "value", "payment", "transfer"]:
                if keyword in ll:
                    param_name = keyword
                    if keyword == "amount":
                        break  # "amount" has highest priority
            if param_name not in result["value_range"]:
                result["value_range"][param_name] = {}
            result["value_range"][param_name]["min"] = min_val
            _note(f"value_range.{param_name}.min", str(min_val),
                  f"Source1_explicit(amount_limit, line='{line[:60]}')")

        # Double negation ("do not block X" → X should not be added to deny)
        double_neg = re.search(
            r"(?:do not|never|don\'t)\s+(?:block|restrict|deny|prevent)\s+(\S+)", ll
        )
        if double_neg:
            token = double_neg.group(1).strip("\"'`.,")
            if token in result["deny"]:
                result["deny"].remove(token)




    # ── Source6: entity list extraction (added in v0.11) ────────────────────────
    # ── Source6: generic entity list extraction (industry-agnostic) ────────────
    # Example: "Prohibited counterparties: Evergrande, Zhongzhi, Celsius"
        # English: "blacklist/blocked entities: A, B, C" (generic; finance-specific patterns in domains/finance)
    #
    # These are named entities (proper nouns) that cannot be matched by the constitutional-rule lexicon;
    # dedicated entity-list parsing logic is required.
    # Parsing strategy: detect keyword followed by a colon, then extract comma-separated title-case tokens.
    _ENTITY_LIST_PATTERNS = [
        # Chinese: "Prohibited counterparties: A, B, C"
        r"禁止[^：:]{0,30}[：:]\s*([A-Za-z][A-Za-z0-9_-]*(?:[,，]\s*[A-Za-z][A-Za-z0-9_-]*)+)",
        # Chinese: "Blacklist: A, B, C" / "禁止实体：A, B"
        r"黑名单\s*[：:]\s*([A-Za-z][A-Za-z0-9_-]*(?:[,，]\s*[A-Za-z][A-Za-z0-9_-]*)+)",
        # English: various "list" / "entities" keyword patterns
        r"(?:blacklist|blocked\s*entities?|restricted\s*entities?|denied\s*list"
        r"|denied\s*entities?|block\s*list|deny\s*list|exclusion\s*list"
        r"|prohibited\s*entities?|banned\s*entities?|sanctioned\s*entities?)\s*[：:]\s*"
        r"([A-Za-z][A-Za-z0-9_\s-]*(?:[,，]\s*[A-Za-z][A-Za-z0-9_\s-]*)+)",
        # English: "deny: A, B, C" (structured AGENTS.md format)
        r"^deny\s*[：:]\s*([A-Za-z][A-Za-z0-9_,\s-]+)",
    ]
    for pat in _ENTITY_LIST_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE | re.MULTILINE):
            entities_str = m.group(1)
            entities = [
                e.strip()
                for e in re.split(r"[,，]", entities_str)
                # 允许英文大写字母开头 OR 中文字符开头
                if e.strip() and re.match(r"[A-Za-z]", e.strip())
            ]
            for entity in entities:
                if entity not in result["deny"]:
                    result["deny"].append(entity)
                    prov_key = entity
                    result["_prov"][prov_key] = (
                        result["_prov"].get(prov_key, "")
                        + (f" | " if result["_prov"].get(prov_key) else "")
                        + f"Source6_entity_list(pattern='{pat[:30]}...')"
                    )

    # ── Source6b: Chinese enumerated-dot / OR-separated command lists (added in v0.11) ─────
    # Detects Chinese enumeration patterns such as "Prohibited commands: rm, delete, drop"
    # and English OR-list patterns such as "Never run rm or delete commands"
    _CMD_LIST_PATTERNS = [
        # Chinese: "Do not use/run/execute X, Y, Z commands"
        r"禁止(?:使用|运行|执行)\s+([a-z][a-z0-9_\-]*"
        r"(?:[、,，]\s*[a-z][a-z0-9_\-]*)+)\s*等?(?:危险)?命令",
        # Chinese: "Prohibited commands: X, Y, Z"
        r"禁止命令\s*[：:]\s*([a-z][a-z0-9_\-]*"
        r"(?:[、,，]\s*[a-z][a-z0-9_\-]*)+)",
        # English: "never/do not run X or Y or Z commands"
        r"(?:never|do not|don't)\s+(?:run|use|execute)\s+"
        r"([a-z][a-z0-9_\-]*(?:\s+or\s+[a-z][a-z0-9_\-]*)+)"
        r"\s+commands?",
    ]
    for pat in _CMD_LIST_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            raw  = m.group(1)
            cmds = [c.strip()
                    for c in re.split(r"[、,，]|\s+or\s+", raw)
                    if c.strip() and re.match(r"[a-z]", c.strip(), re.I)]
            for cmd in cmds:
                full_cmd = cmd + " "   # deny_commands匹配前缀，加空格防止过宽匹配
                if full_cmd not in result["deny_commands"]:
                    result["deny_commands"].append(full_cmd)
                    prov_key = f"deny_commands:{full_cmd}"
                    result["_prov"][prov_key] = f"Source6b_cmd_list(cmd='{cmd}')"
    # ── 7E: time window (generic, not finance-specific) ─────────────────────────
    # Recognises "HH:MM to HH:MM", "before HH:MM", "after HH:MM" in any language.
    # The time values are format-agnostic (wall-clock strings); timezone is injected
    # later by the caller via ExternalContext.
    import re as _re7e
    _TIME_WIN_RANGE = re.compile(
        r"(?:between\s+)?(\d{1,2}:\d{2})\s*(?:to|through|-|到|至|and)\s*(\d{1,2}:\d{2})",
        re.IGNORECASE)
    _TIME_WIN_BEFORE = re.compile(r"before\s+(\d{1,2}:\d{2})", re.IGNORECASE)
    _TIME_WIN_AFTER  = re.compile(r"after\s+(\d{1,2}:\d{2})",  re.IGNORECASE)
    _TIME_WIN_CN_RANGE = re.compile(
        r"(?:上午|下午)?(\d{1,2}:\d{2})\s*(?:到|至|-)\s*(\d{1,2}:\d{2})")

    _sw_detected = None
    for _line in text.splitlines():
        _line = _line.strip()
        _m = _TIME_WIN_RANGE.search(_line) or _TIME_WIN_CN_RANGE.search(_line)
        if _m and not _sw_detected:
            def _pad(t):
                h, m = t.split(":")
                return f"{int(h):02d}:{m}"
            _sw_detected = {"start_time": _pad(_m.group(1)),
                            "end_time":   _pad(_m.group(2))}
            break
        _m = _TIME_WIN_BEFORE.search(_line)
        if _m and not _sw_detected:
            _sw_detected = {"end_time": f"{int(_m.group(1).split(':')[0]):02d}:{_m.group(1).split(':')[1]}"}
            break
        _m = _TIME_WIN_AFTER.search(_line)
        if _m and not _sw_detected:
            _sw_detected = {"start_time": f"{int(_m.group(1).split(':')[0]):02d}:{_m.group(1).split(':')[1]}"}
            break

    if _sw_detected:
        if external_ctx is not None and hasattr(external_ctx, "temporal") and external_ctx.temporal:
            _sw_detected["timezone"]       = external_ctx.temporal.timezone
            _sw_detected["reference_date"] = external_ctx.temporal.reference_date
        result["scheduled_window"] = _sw_detected

    # ── Domain NLP extensions ──────────────────────────────────────────────────
    # Source7 (finance prose NLP) and any other domain-specific NL extractors
    # are registered by domain packs via register_nl_extractor().
    # The kernel calls them here but knows nothing about their internals.
    for _domain_extractor in _NL_EXTRACTORS:
        try:
            _domain_result = _domain_extractor(text, external_ctx)
            # Merge domain results into main result (domain result wins on conflicts)
            for _k, _v in _domain_result.items():
                if _k.startswith("_prov"):
                    result.setdefault("_prov", {}).update(_v)
                elif isinstance(_v, list):
                    # Non-empty list: merge items; empty list: skip (never erase kernel data)
                    if _v:
                        result.setdefault(_k, [])
                        for _item in _v:
                            if _item not in result[_k]:
                                result[_k].append(_item)
                elif isinstance(_v, dict):
                    if _v:
                        result.setdefault(_k, {}).update(_v)
                elif _v is not None and _v is not False:
                    result[_k] = _v
        except Exception:
            pass  # domain extractor failure never breaks the kernel

    return result


def _load_policy_contract(
    constitution=None,
    agents_md_path: Optional[str] = None,
) -> Optional["IntentContract"]:
    """
    Contract-first policy loading.

    When AGENTS.md is generated FROM a ConstitutionalContract
    (identified by the "Auto-generated from ConstitutionalContract" header),
    skip text parsing and load from the contract directly.

    Priority:
      1. Explicit constitution object passed in
      2. YSTAR_CONSTITUTION if importable from ystar_dev
      3. AGENTS.md if it has the "Auto-generated" header → parse back
      4. None → fall through to _load_policy_doc text parsing

    This inverts the old direction (AGENTS.md → contract)
    and makes contract the canonical source for Y* itself.
    """
    # 1. Explicit constitution
    if constitution is not None:
        return constitution

    # 2. YSTAR_CONSTITUTION — injected by caller via environment or file path.
    # Kernel does not import ystar_dev directly (architecture boundary).
    # To use Y* self-hosting: call _load_policy_contract(constitution=my_contract)
    # or set YSTAR_CONSTITUTION_PATH env var to point to a AGENTS.md file.
    import os as _os_env
    _const_path = _os_env.environ.get("YSTAR_CONSTITUTION_PATH")
    if _const_path:
        from pathlib import Path as _Path
        _p = _Path(_const_path)
        if _p.exists():
            try:
                from ystar.kernel.dimensions import ConstitutionalContract as _CC
                return _CC.from_markdown(_p.read_text(), name="env_constitution")
            except Exception:
                pass

    # 3. AGENTS.md with generated header → still trust the contract hash
    # 搜索标准位置——工具专属路径由调用方通过 agents_md_path 参数显式传入
    candidates = [agents_md_path] if agents_md_path else []
    for d in [Path.cwd(), Path.home()]:
        candidates.append(str(d / "AGENTS.md"))

    for path_str in candidates:
        p = Path(path_str) if path_str else None
        if p and p.exists():
            first_line = p.read_text(encoding="utf-8", errors="replace").split("\n")[0]
            if "Auto-generated from ConstitutionalContract" in first_line:
                # Generated file — parse it back via from_markdown
                try:
                    from ystar.kernel.dimensions import ConstitutionalContract as CC
                    text = p.read_text(encoding="utf-8", errors="replace")
                    return CC.from_markdown(text, name="agents_md_generated")
                except Exception:
                    pass

    return None   # fall through to text parsing


def _load_policy_doc(
    search_dirs: Optional[List[Path]] = None,
    trust: str = "imported_md",
) -> Dict[str, Any]:
    """
    Parse AGENTS.md / CLAUDE.md using extended pattern matching.
    Returns partial constraint suggestions.

    IMPORTANT: Results have trust_level=IMPORTED_MD by default.
    They are NEVER authoritative for runtime check() — they are suggestions
    that require normalization before use.

    Trust hierarchy:
      - CONSTITUTION / CONTRACT → authoritative (use _load_policy_contract())
      - GENERATED_MD → read-only projection (has "Auto-generated" header)
      - IMPORTED_MD  → this function, suggestions only
      - UNKNOWN      → not declared

    To upgrade trust from IMPORTED_MD → CONTRACT, use:
      nl_to_contract_delta() + human approval gate in ystar-dev add-rule
    """
    candidates = []
    dirs = search_dirs or [
        Path.cwd(),
        Path.home() / ".claude",
        Path.home(),
    ]
    for d in dirs:
        for name in ["AGENTS.md", "CLAUDE.md", "agents.md", "claude.md"]:
            p = d / name
            if p.exists():
                candidates.append(p)

    if not candidates:
        return {}

    try:
        content = candidates[0].read_text(encoding="utf-8", errors="replace")
        # Simple pattern matcher — no LLM
        return _extract_constraints_from_text(content)  # includes _prov
    except Exception:
        return {}


# ── Source 2: AST analysis ────────────────────────────────────────────────────

def _analyze_ast(func: Callable) -> Dict[str, Any]:
    """Analyze function source via AST to infer constraints."""
    result: Dict[str, Any] = {
        "deny": [], "deny_commands": [], "only_paths": [], "only_domains": [],
        "invariant": [],
        "_param_names": [],    # 实际参数名列表（FIX-C1用）
        "_param_types": {},    # 参数名 → 类型注解（尽力推断）
        "_is_readonly": False, # 函数体里没有写操作
        "_prov": {},           # 来源追踪
    }
    try:
        import inspect, textwrap
        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
    except Exception:
        # getsource() fails for functions defined in __main__ / interactive sessions.
        # Fall back to inspect.signature() which always works to get param names.
        try:
            import inspect as _insp
            sig = _insp.signature(func)
            for pname, param in sig.parameters.items():
                result["_param_names"].append(pname.lower())
                if param.annotation != _insp.Parameter.empty:
                    result["_param_types"][pname.lower()] = str(param.annotation).lower()
        except Exception:
            pass
        return result

    # Extract parameter names and type annotations
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for arg in node.args.args:
                name = arg.arg.lower()
                result["_param_names"].append(name)

                # Infer from type annotation
                if arg.annotation:
                    try:
                        ann = ast.unparse(arg.annotation).lower()
                        result["_param_types"][name] = ann
                    except Exception:
                        pass

                # Infer from parameter names
                for pat in _PARAM_PATTERNS:
                    if any(kw in name for kw in pat["keywords"]):
                        dim = pat["dim"]
                        if dim == "deny":
                            for v in pat.get("deny", []):
                                if v not in result["deny"]:
                                    result["deny"].append(v)
                                    result["_prov"][f"deny:{v}"] = f"Source2_AST(param='{name}', keyword_match)"
                        elif dim == "deny_commands":
                            for v in pat.get("deny_commands", []):
                                if v not in result["deny_commands"]:
                                    result["deny_commands"].append(v)
                                    result["_prov"][f"deny_commands:{v}"] = f"Source2_AST(param='{name}', command_keyword)"
                        elif dim == "invariant":
                            inferred = name if any(
                                kw in name for kw in
                                ["amount","price","cost","fee","balance",
                                 "quantity","total","sum","payment","charge",
                                 "budget","funds","money"]
                            ) else "value"
                            for tmpl in pat.get("invariant_template", []):
                                inv = tmpl.replace("value", inferred)
                                if inv not in result["invariant"]:
                                    result["invariant"].append(inv)
                                    result["_prov"][f"invariant:{inv}"] = f"Source2_AST(param='{name}', numeric_keyword='{inferred}')"

    # Detect write operations (read-only function identification)
    write_calls = {"open", "write", "writelines", "save", "put", "post",
                   "delete", "remove", "unlink", "rmdir", "truncate"}
    has_write = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_id = ""
            if isinstance(node.func, ast.Name):
                func_id = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_id = node.func.attr
            if func_id.lower() in write_calls:
                has_write = True
                break
    result["_is_readonly"] = not has_write

    # Detect open() calls → suggest path constraints
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                if not result["only_paths"]:
                    result["only_paths"].append("./")
                    result["_prov"]["only_paths:./"] = "Source2_AST(detected open() call in function body)"

    return result


# ── Source 3: Call history ────────────────────────────────────────────────────

def _analyze_history(func_name: str,
                     history_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Extract suggestions from recorded call history (ystar ledger or K9Audit CIEU).
    Returns most frequently observed safe paths and domains.
    """
    result: Dict[str, Any] = {"only_paths": [], "only_domains": [], "_prov": {}}
    paths_to_check = [
        history_path,
        Path.home() / ".ystar" / "history.jsonl",
        Path.home() / ".k9log" / "logs" / "k9log.cieu.jsonl",
    ]
    for p in paths_to_check:
        if p and p.exists():
            try:
                import json
                from collections import Counter
                from urllib.parse import urlparse
                path_counts: Counter = Counter()
                domain_counts: Counter = Counter()
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        params = rec.get("U_t", {}).get("params", {})
                        skill  = rec.get("U_t", {}).get("skill", "")
                        if func_name and func_name not in skill:
                            continue
                        for v in params.values():
                            if isinstance(v, str):
                                if "/" in v:
                                    path_counts[v.split("?")[0]] += 1
                                if "://" in v:
                                    h = urlparse(v).hostname or ""
                                    if h:
                                        domain_counts[h] += 1
                    except Exception:
                        pass
                total = max(sum(path_counts.values()), 1)
                for path, count in path_counts.most_common(3):
                    if count / total > 0.1:
                        result["only_paths"].append(path)
                        result["_prov"][f"only_paths:{path}"] = f"Source3_history(freq={count/total:.0%}, count={count})"
                for domain, count in domain_counts.most_common(3):
                    result["only_domains"].append(domain)
                    result["_prov"][f"only_domains:{domain}"] = f"Source3_history(freq={count/max(sum(domain_counts.values()),1):.0%})"
                break
            except Exception:
                pass
    return result


# ── Source 5: Function docstring ──────────────────────────────────────────────

def _analyze_docstring(func: Callable) -> Dict[str, Any]:
    """
    用与Source1相同的模式匹配器分析函数的docstring (FIX-B，新增Source5)。

    函数docstring往往比函数名包含更多语义信息，
    包括间接约束（"admin only"、"staging only"、"read-only"等）。
    返回结果包含 _prov 来源追踪（与Source1格式一致，但来源标记为Source5）。
    """
    if func is None:
        return {}
    doc = getattr(func, "__doc__", None) or ""
    if not doc.strip():
        return {}
    result = _extract_constraints_from_text(doc)
    # Re-label source from Source1 to Source5
    result["_prov"] = {
        k: v.replace("Source1_explicit", "Source5_docstring")
              .replace("constitutional_rule_", "Source5_constitutional_rule_")
        for k, v in result.get("_prov", {}).items()
    }
    return result


# ── FIX-C1: parameter name cross-check ──────────────────────────────────────

def _fix_invariant_param_names(
    invariants: List[str],
    actual_params: List[str],
) -> List[str]:
    """
    FIX-C1: 检查invariant里引用的变量名是否在实际参数列表里。

    如果不在，尝试找最近的匹配：
      1. 优先找名字包含金融关键词的实际参数（amount/qty/price等）
      2. 找类型注解是 float/int 的参数
      3. 都没有：丢弃这个invariant（不生成假保护）

    纯确定性：只做字符串匹配，不猜测语义。
    """
    if not actual_params:
        return invariants  # 没有签名信息，保持原样

    _NUMERIC_KEYWORDS = [
        "amount", "price", "cost", "fee", "balance", "quantity",
        "total", "sum", "payment", "charge", "budget", "funds",
        "money", "qty", "count", "num", "number", "val", "value",
        "rate", "factor", "size", "limit", "max", "min", "score",
    ]

    fixed = []
    for inv in invariants:
        # Extract variable names referenced in invariants
        try:
            tree = ast.parse(inv, mode='eval')
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        except Exception:
            fixed.append(inv)
            continue

        # Check whether each referenced name exists in the actual parameters
        missing = names - set(actual_params)
        if not missing:
            fixed.append(inv)
            continue

        # Missing names found: search for substitutes
        best_replacement = None

        # Strategy 1: look for actual parameters whose names contain financial keywords
        for param in actual_params:
            if any(kw in param.lower() for kw in _NUMERIC_KEYWORDS):
                best_replacement = param
                break

        # Strategy 2: if strategy 1 fails, use the first actual parameter
        if best_replacement is None and actual_params:
            best_replacement = actual_params[0]

        if best_replacement:
            # Replace the missing variable name
            new_inv = inv
            for missing_name in missing:
                new_inv = re.sub(
                    r'\b' + re.escape(missing_name) + r'\b',
                    best_replacement,
                    new_inv,
                )
            fixed.append(new_inv)
        # If no substitute can be found, discard (do not generate false protection)

    return fixed


# ── PrefillResult (added: returns both the base contract and higher-order suggestions) ────

@dataclass
class PrefillResult:
    """
    prefill() 的返回值（v0.4.0新增，v0.5.0加入 provenance）。

    contract:       IntentContract — 基础8维度合约（可直接用于check()）
    higher_order:   Optional[HigherOrderContract] — 高阶维度建议
    warnings:       List[str] — 人类可读的建议/警告列表
                    包含：B类间接约束建议、D类高阶约束建议
    provenance:     Dict[str, str] — {value: source_desc}
                    每条约束的来源标注，用于信任验证。
                    键是约束的值（如 "production"、"amount > 0"），
                    值是人类可读的来源描述（如 "Source4a(func_name='transfer_funds'...)"）
    provenance_full: Dict[str, str] — {"dim:value": source_desc}
                    带维度前缀的完整来源索引，用于精确查询。

    向后兼容：PrefillResult可当作IntentContract使用（代理所有属性访问）

    用法示例：
        r = prefill(func=transfer_funds)
        for item in r.contract.deny:
            print(f"  deny '{item}' ← {r.provenance.get(item, 'unknown')}")
        print(r.explain())
    """
    contract:        IntentContract
    higher_order:    Optional[HigherOrderContract]  = None
    warnings:        List[str]                      = field(default_factory=list)
    provenance:      Dict[str, str]                 = field(default_factory=dict)
    provenance_full: Dict[str, str]                 = field(default_factory=dict)

    # Backward compatibility: proxy IntentContract attributes
    def __getattr__(self, name: str) -> Any:
        return getattr(self.contract, name)

    def __bool__(self) -> bool:
        return not self.contract.is_empty()

    def explain(self, indent: int = 2) -> str:
        """
        输出所有生成约束的来源标注，用于信任验证。

        Args:
            indent: 缩进空格数

        Returns:
            人类可读的来源报告字符串。

        示例输出：
            Prefill结果 for 'transfer_funds':
              deny:
                'production'  ← Source4a(func_name='transfer_funds', pattern='transfer')
                '.env'        ← Source4a(func_name='transfer_funds', pattern='transfer')
              invariant:
                'funds > 0'   ← Source4b(func_name='transfer_funds', keyword='funds')
        """
        pad = " " * indent
        lines = [f"Prefill结果 for '{self.contract.name or '(unnamed)'}':"]

        from ystar.kernel.dimensions import DIMENSION_NAMES
        for dim in DIMENSION_NAMES:
            values = getattr(self.contract, dim, None)
            if not values:
                continue

            if isinstance(values, list):
                lines.append(f"{pad}{dim}:")
                max_v_len = max((len(str(v)) for v in values), default=0)
                for v in values:
                    src = (self.provenance_full.get(f"{dim}:{v}")
                           or self.provenance.get(str(v))
                           or "source unknown")
                    lines.append(f"{pad}{pad}{str(v)!r:{max_v_len+2}}  ← {src}")

            elif isinstance(values, dict):
                lines.append(f"{pad}{dim}:")
                for field_name, blocked in values.items():
                    for bv in (blocked if isinstance(blocked, list) else [blocked]):
                        src = (self.provenance_full.get(f"{dim}:{field_name}:{bv}")
                               or self.provenance_full.get(f"{dim}:{field_name}")
                               or "source unknown")
                        lines.append(f"{pad}{pad}[{field_name}] '{bv}'  ← {src}")

        if self.higher_order and not self.higher_order.is_empty():
            lines.append(f"{pad}higher_order_suggestions:")
            t = self.higher_order.temporal
            a = self.higher_order.aggregate
            if t.max_calls_per_window:
                lines.append(f"{pad}{pad}temporal: max {t.max_calls_per_window} calls/{t.window_seconds}s")
            if a.param and a.max_sum:
                lines.append(f"{pad}{pad}aggregate: sum({a.param}) ≤ {a.max_sum:,}/{a.window_seconds}s")

        if self.warnings:
            lines.append(f"{pad}warnings ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"{pad}{pad}{w.split(chr(10))[0]}")

        return "\n".join(lines)


# ── Prefill: merge all sources ────────────────────────────────────────────────

def prefill(
    func:         Optional[Callable] = None,
    func_name:    str = "",
    search_dirs:  Optional[List[Path]] = None,
    history_path: Optional[Path] = None,
) -> PrefillResult:
    """
    Auto-prefill an IntentContract from five deterministic sources.

    v0.4.0 changes:
      FIX-C1: invariant variable names cross-checked against actual params
      FIX-B:  indirect expression patterns (env/role/readonly) via Source5 + extended Source1
      FIX-D:  HigherOrderContract suggestions for high-risk function patterns

    Args:
        func:         the function to analyze (for AST + docstring analysis)
        func_name:    function name (used when func is not available)
        search_dirs:  directories to search for AGENTS.md
        history_path: path to call history file (optional)

    Returns:
        PrefillResult with .contract (IntentContract) and optional .higher_order
        and .warnings for indirect/higher-order suggestions.
        All suggestions are deterministic: same inputs = same output.
    """
    name = func_name or (getattr(func, "__name__", "") if func else "")
    merged: Dict[str, Any] = {
        "deny": [], "only_paths": [], "deny_commands": [],
        "only_domains": [], "invariant": [], "field_deny": {}, "value_range": {},
    }
    warnings:     List[str]        = []
    actual_params: List[str]       = []
    is_readonly_hint: bool         = False
    indirect_hints: Dict[str, Any] = {}  # _deny_env, _required_roles, _rate_limit
    prov:      Dict[str, str]      = {}  # value → source（用户友好的简单索引）
    prov_full: Dict[str, str]      = {}  # "dim:value" → source（带维度前缀的精确索引）

    def _add(key: str, values: list, source: str = "unknown") -> None:
        """向 merged 添加约束，同时记录来源到 prov/prov_full。

        来源记录策略：all-sources，多个来源用 " | " 分隔。
        这样用户能看到同一个约束是否被多个来源同时确认，增强信任度。
        """
        if not isinstance(values, list):
            return
        for v in values:
            if v and v not in merged.get(key, []):
                merged.setdefault(key, []).append(v)
            sv = str(v)
            if sv and v:
                # all-sources: append provenance, do not overwrite (multi-source confirmation is more trustworthy)
                existing = prov.get(sv, "")
                if existing and source not in existing:
                    prov[sv] = existing + " | " + source
                elif not existing:
                    prov[sv] = source
                # prov_full: likewise append
                existing_full = prov_full.get(f"{key}:{sv}", "")
                if existing_full and source not in existing_full:
                    prov_full[f"{key}:{sv}"] = existing_full + " | " + source
                elif not existing_full:
                    prov_full[f"{key}:{sv}"] = source

    def _collect_indirect(extracted: Dict[str, Any]) -> None:
        """收集间接约束信号（不进入IntentContract）"""
        for env in extracted.get("_deny_env", []):
            if env not in indirect_hints.setdefault("_deny_env", []):
                indirect_hints.setdefault("_deny_env", []).append(env)
        for role in extracted.get("_required_roles", []):
            if role not in indirect_hints.setdefault("_required_roles", []):
                indirect_hints.setdefault("_required_roles", []).append(role)
        if extracted.get("_readonly"):
            indirect_hints["_readonly"] = True
        if extracted.get("_rate_limit") and "_rate_limit" not in indirect_hints:
            indirect_hints["_rate_limit"] = extracted["_rate_limit"]

    # Source 4a: function name patterns
    if name:
        for fn_pat, constraints in _FUNC_PATTERNS.items():
            if fn_pat in name.lower():
                for dim, values in constraints.items():
                    _add(dim, values,
                         source=f"Source4a(func_name='{name}', pattern='{fn_pat}')")
                break  # first match only

    # Source 4b: infer param name for invariants from function name
    _inferred_param = "value"
    for kw in ["amount", "price", "cost", "fee", "balance", "quantity",
               "total", "sum", "payment", "charge", "budget", "funds", "money"]:
        if kw in name.lower():
            _inferred_param = kw
            break

    _inv_added = False
    for pat in _PARAM_PATTERNS:
        if any(kw in name.lower() for kw in pat["keywords"]):
            dim = pat["dim"]
            if dim == "invariant" and not _inv_added:
                for tmpl in pat.get("invariant_template", []):
                    inv = tmpl.replace("value", _inferred_param)
                    _add("invariant", [inv],
                         source=f"Source4b(func_name='{name}', keyword='{_inferred_param}')")
                _inv_added = True
            elif dim == "deny":
                _add("deny", pat.get("deny", []),
                     source=f"Source4b(func_name='{name}', param_pattern)")
            elif dim == "deny_commands":
                _add("deny_commands", pat.get("deny_commands", []),
                     source=f"Source4b(func_name='{name}', param_pattern)")

    # Source 4c: indirect constraints — function-name keywords (FIX-B)
    if name:
        nl = name.lower()
        for kw, ctx in _INDIRECT_CONTEXT_PATTERNS.items():
            if kw in nl:
                _collect_indirect({
                    "_deny_env": ctx.get("deny_env", []),
                    "_required_roles": ctx.get("required_roles", []),
                })
        # Read-only function identification
        for prefix in _READONLY_FUNC_PREFIXES:
            if nl.startswith(prefix) or ("read" in nl and "write" not in nl):
                _collect_indirect({"_readonly": True})
                break

    # Source 1: policy document (extended — includes indirect constraint detection)
    policy = _load_policy_doc(search_dirs)
    for key in ["deny", "deny_commands", "only_paths", "only_domains"]:
        for v in policy.get(key, []):
            src = policy.get("_prov", {}).get(f"{key}:{v}", "Source1(policy_doc)")
            _add(key, [v], source=src)
    _collect_indirect(policy)

    # Source 2: AST analysis
    if func is not None:
        ast_s = _analyze_ast(func)
        for key in ["deny", "deny_commands", "only_paths", "only_domains", "invariant"]:
            for v in ast_s.get(key, []):
                src = ast_s.get("_prov", {}).get(f"{key}:{v}", "Source2(AST)")
                _add(key, [v], source=src)
        actual_params = ast_s.get("_param_names", [])
        if ast_s.get("_is_readonly"):
            _collect_indirect({"_readonly": True})

    # Source 3: call history
    if name:
        hist = _analyze_history(name, history_path)
        for key, values in hist.items():
            if key.startswith("_"):
                continue  # 跳过 _prov 等内部字段
            for v in (values if isinstance(values, list) else []):
                src = hist.get("_prov", {}).get(f"{key}:{v}", "Source3(call_history)")
                _add(key, [v], source=src)

    # Source 5: function docstring (FIX-B, added)
    if func is not None:
        doc_s = _analyze_docstring(func)
        for key in ["deny", "deny_commands", "only_paths", "only_domains"]:
            for v in doc_s.get(key, []):
                src = doc_s.get("_prov", {}).get(f"{key}:{v}", "Source5(docstring)")
                _add(key, [v], source=src)
        _collect_indirect(doc_s)

    # FIX-C1: cross-check invariant parameter names
    if actual_params and merged.get("invariant"):
        merged["invariant"] = _fix_invariant_param_names(
            merged["invariant"], actual_params
        )

    # Build the base contract
    contract = IntentContract.from_dict(merged, name=name)

    # ── FIX-B: generate indirect constraint warnings ─────────────────────────
    if indirect_hints.get("_deny_env"):
        envs = indirect_hints["_deny_env"]
        warnings.append(
            f"[context] 检测到环境限制意图 → 建议设置 "
            f"HigherOrderContract.context.deny_env={envs}\n"
            f"  用法: HigherOrderContract(context=ContextConstraint(deny_env={envs}))"
        )

    if indirect_hints.get("_required_roles"):
        roles = indirect_hints["_required_roles"]
        warnings.append(
            f"[context] 检测到角色限制意图 → 建议设置 "
            f"HigherOrderContract.context.required_roles={roles}\n"
            f"  用法: HigherOrderContract(context=ContextConstraint(required_roles={roles}))"
        )

    if indirect_hints.get("_readonly"):
        warnings.append(
            f"[postcondition] 检测到只读函数意图 → 建议添加 "
            f"postcondition 验证无副作用，或标记为 read-only 并限制调用权限"
        )

    # ── FIX-D: higher-order dimension generation ─────────────────────────────
    higher_order: Optional[HigherOrderContract] = None

    if name:
        nl = name.lower()
        temporal_cfg = None
        aggregate_cfg = None

        # Infer temporal constraints from function-name patterns
        for kw, (max_calls, window) in _HIGH_RISK_TEMPORAL_PATTERNS.items():
            if kw in nl:
                temporal_cfg = (max_calls, window)
                break

        # Infer from policy-document rate-limit patterns (higher priority)
        if indirect_hints.get("_rate_limit"):
            max_calls, window = indirect_hints["_rate_limit"]
            temporal_cfg = (max_calls, window)
            warnings.append(
                f"[temporal] 策略文档中检测到频率限制 → "
                f"max_calls={max_calls}/window={window}s"
            )

        # Infer aggregate constraints from function-name patterns
        for kw, (amount_kw, max_sum, window) in _HIGH_RISK_AGGREGATE_PATTERNS.items():
            if kw in nl:
                # Find the best-matching amount parameter name in the actual parameters
                agg_param = amount_kw  # 默认
                if actual_params:
                    for p in actual_params:
                        if amount_kw in p.lower() or any(
                            k in p.lower() for k in ["amount","price","cost","fee","sum","total"]
                        ):
                            agg_param = p
                            break
                aggregate_cfg = (agg_param, max_sum, window)
                break

        if temporal_cfg or aggregate_cfg:
            temporal = TemporalConstraint(
                max_calls_per_window=temporal_cfg[0] if temporal_cfg else None,
                window_seconds=temporal_cfg[1] if temporal_cfg else None,
            ) if temporal_cfg else TemporalConstraint()

            aggregate = AggregateConstraint(
                param=aggregate_cfg[0] if aggregate_cfg else "",
                max_sum=aggregate_cfg[1] if aggregate_cfg else None,
                window_seconds=aggregate_cfg[2] if aggregate_cfg else None,
            ) if aggregate_cfg else AggregateConstraint()

            higher_order = HigherOrderContract(
                func_name=name,
                temporal=temporal,
                aggregate=aggregate,
            )

            if temporal_cfg:
                warnings.append(
                    f"[temporal] '{name}' 是高风险函数 → 建议限速: "
                    f"max {temporal_cfg[0]} calls / {temporal_cfg[1]}s\n"
                    f"  用法: HigherOrderContract(temporal=TemporalConstraint("
                    f"max_calls_per_window={temporal_cfg[0]}, "
                    f"window_seconds={temporal_cfg[1]}))"
                )
            if aggregate_cfg:
                warnings.append(
                    f"[aggregate] '{name}' → 建议聚合上限: "
                    f"sum({aggregate_cfg[0]}) ≤ {aggregate_cfg[1]:,} / {aggregate_cfg[2]}s\n"
                    f"  用法: HigherOrderContract(aggregate=AggregateConstraint("
                    f"param='{aggregate_cfg[0]}', max_sum={aggregate_cfg[1]}, "
                    f"window_seconds={aggregate_cfg[2]}))"
                )

    # Source 6: pretrain discovered_patterns (data-driven universal constraints)
    # Based on function NAME and PARAMETER NAMES (not runtime values).
    # prefill() is static analysis — it infers constraints from signatures,
    # not from what a specific call is actually passing.
    try:
        from ystar.pretrain import load_discovered_patterns
        discovered   = load_discovered_patterns()
        _deny_cmds   = discovered.get("deny_commands", [])
        _deny_paths  = discovered.get("deny_paths",    [])
        _deny_doms   = discovered.get("deny_domains",  [])
        name_lower   = name.lower()

        # Rule A: function names suggesting shell/command execution →
        #         pre-seed deny_commands with known dangerous patterns
        SHELL_HINTS = ("shell","execute","run_","exec","command","cmd","subprocess",
                       "popen","system","spawn")
        if any(h in name_lower for h in SHELL_HINTS):
            if not merged.get("deny_commands"):
                _add("deny_commands", _deny_cmds[:3], "pretrain:source6_cmd_function")

        # Rule B: param names suggesting file paths →
        #         pre-seed deny with dangerous paths discovered in attacks
        PATH_PARAM_HINTS = ("file_path","filepath","path","filename","file")
        if any(p in actual_params for p in PATH_PARAM_HINTS):
            if not merged.get("deny"):
                _add("deny", _deny_paths[:3], "pretrain:source6_path_param")

        # Rule C: param names suggesting external network →
        #         pre-seed only_domains with safe allowlist hint
        URL_PARAM_HINTS = ("url","endpoint","domain","host","uri","webhook")
        if any(p in actual_params for p in URL_PARAM_HINTS):
            if not merged.get("only_domains"):
                # Don't add deny_domains — too aggressive for unknown functions.
                # Instead, log a hint in provenance that this function touches URLs.
                prov_full["url_param_detected"] = "pretrain:source6_url_param"

        # Rule D: function names with privilege/escalation keywords →
        #         add invariant hint
        PRIV_HINTS = ("sudo","root","admin","privilege","escalat","grant_perm")
        if any(h in name_lower for h in PRIV_HINTS):
            priv_inv = "privilege_level != 'root'"
            if priv_inv not in merged.get("invariant", []):
                _add("invariant", [priv_inv], "pretrain:source6_privilege_function")

    except Exception:
        pass  # pretrain module not available — silently skip


    return PrefillResult(
        contract=contract,
        higher_order=higher_order,
        warnings=warnings,
        provenance=prov,
        provenance_full=prov_full,
    )

# Domain ontology extensions are registered via register_ontology_extension().
# Finance domain auto-registers in ystar/domains/finance/__init__.py.
# No kernel-level file path scanning needed.


def explain(result: "PrefillResult", indent: int = 2) -> str:
    """
    模块级 explain() 函数 — 对 PrefillResult 的来源做人类可读报告。

    用法：
        from ystar.kernel.prefill import prefill, explain
        r = prefill(func=my_func)
        print(explain(r))

    等价于 r.explain(indent=indent)。
    """
    return result.explain(indent=indent)


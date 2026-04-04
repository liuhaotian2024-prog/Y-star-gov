# Layer: Foundation
#
# ystar — Human Intent to Machine Predicate
# Copyright (C) 2026 Haotian Liu
# MIT License
#
# v0.3.0
# Added: ConstitutionalContract (constitutional layer)
# Added: HigherOrderContract (temporal/aggregate/context/resource higher-order dimensions)
# Improved: IntentContract.merge() — statutory layer inherits from constitutional layer
"""
Eight constraint dimensions + constitutional layer + four higher-order dimensions.

Each dimension corresponds to a class of behavioral constraint that appears
in natural language policy documents (AGENTS.md, system prompts, etc.).

All dimensions are deterministic: given the same constraint definition and
the same input, check() always returns the same result.

Architecture:
  ConstitutionalContract  — global constitutional layer, inherited by all functions; can only be tightened
  IntentContract          — function-level statutory layer, 8 base dimensions
  HigherOrderContract     — higher-order dimensions: temporal / aggregate / context / resource

Semantic space covered by the translation layer (behavioural constraint subspace):
  Content filtering  deny / deny_commands / field_deny
  Whitelists         only_paths / only_domains
  Logic predicates   invariant / postcondition
  Numeric bounds     value_range
  Temporal           temporal   (new)
  Aggregate          aggregate  (new)
  Caller context     context    (new)
  Resource           resource   (new)
"""
from __future__ import annotations

import re
import json
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ── Contract Legitimacy Lifecycle (v0.42.0) ──────────────────────────────────

class ContractStatus(str, Enum):
    """
    Contract lifecycle status.

    DRAFT      - Translated from natural language, not yet confirmed by human
    CONFIRMED  - Human confirmed, active and enforceable
    STALE      - Review trigger fired, awaiting reconfirmation
    SUSPENDED  - Governance loop suspended it due to policy violation
    EXPIRED    - Past valid_until timestamp
    SUPERSEDED - Replaced by newer version
    """
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    STALE = "stale"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


# ── Snapshot checker registry (P1d) ─────────────────────────────────────────
_SNAPSHOT_CHECKERS: List[Any] = []

def register_snapshot_checker(fn) -> None:
    """Register a domain snapshot validator for check_all().
    fn: (snapshot, params: dict, contract) -> List[Violation]
    """
    if fn not in _SNAPSHOT_CHECKERS:
        _SNAPSHOT_CHECKERS.append(fn)


# ── Timezone offset registry (P2b/P3) ────────────────────────────────────────
# The kernel ships with a minimal UTC/GMT-only default.
# Domain packs and callers register their own timezone offsets.
# This keeps city-specific geographic knowledge out of the kernel.
_TIMEZONE_OFFSETS: Dict[str, float] = {
    "UTC": 0.0, "GMT": 0.0,
}

def register_timezone_offset(name: str, offset_hours: float) -> None:
    """Register a timezone offset (hours from UTC) with the kernel.
    Called by domain packs or application code at startup.
    Example: register_timezone_offset("America/New_York", -5.0)
    """
    _TIMEZONE_OFFSETS[name] = offset_hours
from urllib.parse import urlparse


# ── Base 8-dimension definitions ─────────────────────────────────────────────

DIMENSION_NAMES = [
    "deny",               # strings that must not appear in any parameter
    "only_paths",         # allowed filesystem paths (whitelist)
    "deny_commands",      # blocked shell command prefixes
    "only_domains",       # allowed network domains (whitelist)
    "invariant",          # Python expressions on inputs that must hold
    "optional_invariant", # v0.12: like invariant, but silent when variable absent
    "postcondition",      # Python expressions on outputs that must hold
    "field_deny",         # per-field value blocklist
    "value_range",        # numeric parameter bounds {param: {min: N, max: M}}
    "obligation_timing",  # v0.40.0: task completion deadlines {key: seconds}
]

# Human-readable labels for each dimension
DIMENSION_LABELS = {
    "deny":           "Content to deny",
    "only_paths":     "Allowed paths only",
    "deny_commands":  "Commands to deny",
    "only_domains":   "Allowed domains only",
    "invariant":          "Input invariants",
    "optional_invariant": "Conditional invariants (silent when absent)",
    "postcondition":      "Output postconditions",
    "field_deny":     "Field value blocklist",
    "value_range":    "Numeric bounds",
    "obligation_timing": "Task obligation deadlines (seconds)",
}

# Example hints shown to users during interactive contract building
DIMENSION_HINTS = {
    "deny":           "e.g. .env, /etc/, 192.168.",
    "only_paths":     "e.g. ./projects/, ./output/",
    "deny_commands":  "e.g. rm -rf, sudo, chmod 777",
    "only_domains":   "e.g. api.github.com, api.example.com",
    "invariant":          "Python expression: amount > 0",
    "optional_invariant": "Python expression (only checked when variable exists): confidence > 0.5",
    "postcondition":      "Python expression: result.get('status') == 'ok'",
    "field_deny":     "e.g. production, prod, live",
    "value_range":    "param:min:max e.g. amount:0:1000000",
}


# ── Policy Source Trust Model ───────────────────────────────────────────────
# Iron law: Contract is the ONLY authoritative runtime source.
# Markdown is ONLY: import inlet | human-readable projection | compatibility layer.
#
# Trust hierarchy (highest → lowest):
#   CONSTITUTION > CONTRACT > GENERATED_MD > IMPORTED_MD > UNKNOWN

class PolicySourceTrust:
    """
    Trust-level constants for constraint sources.

    Rules (encoded in Y* architecture, enforced in code):
      - Only CONSTITUTION and CONTRACT are authoritative for runtime check().
      - GENERATED_MD: read-only projection. Importing back requires
        explicit nl_to_contract_delta() + human approval.
      - IMPORTED_MD: untrusted until normalized through prefill pipeline.
      - Trust never auto-upgrades; upgrade requires explicit approval gate.
    """
    CONSTITUTION = "constitution"   # YSTAR_CONSTITUTION — highest trust
    CONTRACT     = "contract"       # IntentContract from DelegationChain
    GENERATED_MD = "generated_md"   # AGENTS.md exported FROM contract
    IMPORTED_MD  = "imported_md"    # External AGENTS.md / CLAUDE.md
    UNKNOWN      = "unknown"

    _ORDER = {
        "unknown": 0, "imported_md": 1,
        "generated_md": 2, "contract": 3, "constitution": 4,
    }

    @classmethod
    def is_runtime_authoritative(cls, trust: str) -> bool:
        """Only CONSTITUTION and CONTRACT can drive runtime check()."""
        return trust in (cls.CONSTITUTION, cls.CONTRACT)

    @classmethod
    def requires_approval_to_upgrade(cls, from_t: str, to_t: str) -> bool:
        """Any move toward higher trust requires human approval."""
        return cls._ORDER.get(to_t, 0) > cls._ORDER.get(from_t, 0)


@dataclass
class IntentContract:
    """
    A formal intent contract: the Y*_t field in a causal audit chain.
    Function-level intent contract (statutory layer).

    An IntentContract defines what a function is *supposed* to do —
    the constraints that must hold for the function to be operating
    within specification.

    Expresses "what this function is supposed to do" — 8 base dimensions covering
    content filtering, whitelists, logic predicates, and numeric bounds.
    Call merge(constitutional) to inherit global constraints from the constitutional layer.

    Attributes:
        deny:          strings that must not appear in any parameter value
        only_paths:    if non-empty, file path params must be within these paths
        deny_commands: command params must not begin with these prefixes
        only_domains:  if non-empty, URL params must be within these domains
        invariant:          Python expressions evaluated against input params
                           (phantom_variable if referenced variable is absent)
        optional_invariant: Like invariant, but SILENT when the referenced variable
                           is absent from params. Use for conditional bounds in
                           multi-agent systems where different agents pass different
                           parameter subsets. E.g. optional_invariant=["settlement_risk < 0.8"]
                           will only check if `settlement_risk` is actually passed.
        postcondition:     Python expressions evaluated against output result
        field_deny:    per-field value blocklists {field_name: [blocked_values]}
        value_range:   numeric bounds {param_name: {min: N, max: M}}
        name:          optional human-readable name for this contract
        hash:          SHA256 of the canonical JSON (computed automatically)
    """
    deny:          List[str]             = field(default_factory=list)
    only_paths:    List[str]             = field(default_factory=list)
    deny_commands: List[str]             = field(default_factory=list)
    only_domains:  List[str]             = field(default_factory=list)
    invariant:          List[str]             = field(default_factory=list)
    optional_invariant: List[str]             = field(default_factory=list)
    # v0.12: like invariant, but silent when referenced variable is absent.
    # Use for conditional constraints in multi-agent systems where different
    # agents pass different parameter subsets.
    postcondition:      List[str]             = field(default_factory=list)
    field_deny:    Dict[str, List[str]]  = field(default_factory=dict)
    value_range:   Dict[str, Dict]       = field(default_factory=dict)

    # v0.40.0: 义务时限（与 temporal 的频率限制明确分开）
    # temporal = 行动频率上限（agent 能做多快）
    # obligation_timing = 承诺完成时限（agent 必须多快做）
    # 单位：秒。支持的键：
    #   delegation      任务分配时限（planner 必须在此时间内分配）
    #   acknowledgement 任务确认时限（worker 必须在此时间内接受）
    #   status_update   状态更新时限（worker 必须在此时间内汇报进度）
    #   completion      任务完成时限（worker 必须在此时间内完成）
    #   escalation      升级响应时限（收到阻塞后必须在此时间内升级）
    #   closure         任务关闭时限（完成后必须在此时间内正式关闭）
    #   result_publication 结果发布时限
    #
    # 例：{"acknowledgement": 300, "completion": 3600}
    # 无此字段 → 由 domain pack 配置，或使用规则默认值
    obligation_timing: Dict[str, float]  = field(default_factory=dict)

    # ── Contract Legitimacy Lifecycle (v0.42.0) ──────────────────────────────
    # Tracks the lifecycle state and decay of contract legitimacy.
    # Unconfirmed contracts (status=draft) are denied by check().
    # Confirmed contracts decay over time and may become stale.
    confirmed_by:      str                = ""           # who confirmed (e.g. "alice@example.com")
    confirmed_at:      float              = 0.0          # Unix timestamp
    valid_until:       float              = 0.0          # 0 = never expires
    review_triggers:   List[str]          = field(default_factory=list)  # ["personnel_change", "regulatory_update"]
    status:            str                = ""           # Use str for JSON compat (empty = legacy confirmed)
    superseded_by:     str                = ""           # contract hash that replaces this one
    version:           int                = 1
    legitimacy_decay:  Dict[str, float]   = field(default_factory=dict)
    # Keys: half_life_days, personnel_weight, regulatory_weight, minimum_score

    name:          str                   = ""
    hash:          str                   = ""

    def __post_init__(self):
        if not self.hash:
            self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def legitimacy_score(self, now: float = None) -> float:
        """
        Compute current legitimacy based on time decay and triggers.

        Returns a score from 0.0 to 1.0:
          1.0 = fully legitimate (recently confirmed, no triggers)
          0.0 = no legitimacy (never confirmed)

        Decay factors:
          - Time: exponential decay with half_life_days
          - Triggers: each fired trigger reduces score by its weight
        """
        if now is None:
            now = time.time()
        if not self.confirmed_at or self.confirmed_at == 0:
            return 0.0  # Never confirmed = no legitimacy

        # Base: time decay (half-life)
        half_life = self.legitimacy_decay.get("half_life_days", 0)
        if half_life > 0:
            days_elapsed = (now - self.confirmed_at) / 86400
            time_score = 0.5 ** (days_elapsed / half_life)
        else:
            time_score = 1.0

        # Deductions from triggers
        # Triggers reduce score when fired (marked as "fired:<trigger_name>")
        trigger_deduction = 0.0
        for trigger in self.review_triggers:
            if trigger.startswith("fired:"):
                weight_key = trigger.split(":")[1] + "_weight"
                trigger_deduction += self.legitimacy_decay.get(weight_key, 0.1)

        score = max(time_score - trigger_deduction,
                    self.legitimacy_decay.get("minimum_score", 0.0))
        return round(score, 4)

    def effective_status(self, now: float = None) -> str:
        """
        Compute effective status considering expiration and legitimacy decay.

        Status priority (highest to lowest):
          SUPERSEDED → SUSPENDED → EXPIRED → STALE → status field

        Returns ContractStatus value as string.
        """
        if now is None:
            now = time.time()

        # Superseded and suspended take precedence
        if self.status == "superseded":
            return "superseded"
        if self.status == "suspended":
            return "suspended"

        # Check expiration
        if self.valid_until > 0 and now > self.valid_until:
            return "expired"

        # BACKWARD COMPAT: legacy contracts (no status field) are treated as confirmed
        if not self.status:
            if not self.confirmed_by:
                # Empty status AND empty confirmed_by → legacy confirmed contract
                return "confirmed"
            else:
                # Has confirmed_by but no status → treat as confirmed
                return "confirmed"

        # Check legitimacy score for confirmed contracts
        if self.status == "confirmed":
            score = self.legitimacy_score(now)
            min_score = self.legitimacy_decay.get("minimum_score", 0.3)
            # Stale when score has decayed to the minimum floor
            if score <= min_score:
                return "stale"

        return self.status

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict (excludes name and hash)."""
        d = {}
        if self.deny:          d["deny"]          = self.deny
        if self.only_paths:    d["only_paths"]    = self.only_paths
        if self.deny_commands: d["deny_commands"] = self.deny_commands
        if self.only_domains:  d["only_domains"]  = self.only_domains
        if self.invariant:          d["invariant"]          = self.invariant
        if self.optional_invariant: d["optional_invariant"] = self.optional_invariant
        if self.postcondition:      d["postcondition"]      = self.postcondition
        if self.field_deny:    d["field_deny"]    = self.field_deny
        if self.value_range:   d["value_range"]   = self.value_range
        if self.obligation_timing: d["obligation_timing"] = self.obligation_timing

        # v0.42.0: Contract legitimacy lifecycle fields
        if self.confirmed_by:     d["confirmed_by"]     = self.confirmed_by
        if self.confirmed_at:     d["confirmed_at"]     = self.confirmed_at
        if self.valid_until:      d["valid_until"]      = self.valid_until
        if self.review_triggers:  d["review_triggers"]  = self.review_triggers
        if self.status:           d["status"]           = self.status
        if self.superseded_by:    d["superseded_by"]    = self.superseded_by
        if self.version != 1:     d["version"]          = self.version
        if self.legitimacy_decay: d["legitimacy_decay"] = self.legitimacy_decay

        return d

    def diff(self, other: "IntentContract") -> dict:
        """
        Compute the semantic difference between two IntentContracts.

        Returns a dict describing what changed:
          added:   constraints in `other` but not in `self`
          removed: constraints in `self`  but not in `other`
          tightened / loosened: value_range changes

        Use cases:
          - version management: what changed between v0.24 and v0.25?
          - drift detection: did a child contract quietly loosen something?
          - self-hosting: show developer exactly what their patch changes

        Returns {} if contracts are semantically equivalent.
        """
        delta: dict = {}

        def list_diff(a, b, key):
            added   = sorted(set(b) - set(a))
            removed = sorted(set(a) - set(b))
            if added or removed:
                delta[key] = {}
                if added:   delta[key]["added"]   = added
                if removed: delta[key]["removed"] = removed

        list_diff(self.deny,          other.deny,          "deny")
        list_diff(self.deny_commands, other.deny_commands, "deny_commands")
        list_diff(self.only_paths,    other.only_paths,    "only_paths")
        list_diff(self.only_domains,  other.only_domains,  "only_domains")
        list_diff(self.invariant,     other.invariant,     "invariant")
        list_diff(self.optional_invariant, other.optional_invariant, "optional_invariant")

        # value_range: detect tightened vs loosened
        all_params = set(self.value_range) | set(other.value_range)
        vr_delta = {}
        for p in all_params:
            s_bounds = self.value_range.get(p, {})
            o_bounds = other.value_range.get(p, {})
            if s_bounds != o_bounds:
                change = {}
                for k in ("min", "max"):
                    sv, ov = s_bounds.get(k), o_bounds.get(k)
                    if sv != ov:
                        # Tightened: max decreased OR min increased
                        if k == "max" and sv is not None and ov is not None:
                            change[k] = {"from": sv, "to": ov,
                                         "direction": "tightened" if ov < sv else "loosened"}
                        elif k == "min" and sv is not None and ov is not None:
                            change[k] = {"from": sv, "to": ov,
                                         "direction": "tightened" if ov > sv else "loosened"}
                        else:
                            change[k] = {"from": sv, "to": ov}
                if change:
                    vr_delta[p] = change
        if vr_delta:
            delta["value_range"] = vr_delta

        # field_deny
        fd_delta = {}
        all_fields = set(self.field_deny) | set(other.field_deny)
        for f in all_fields:
            sp = self.field_deny.get(f, [])
            op = other.field_deny.get(f, [])
            added   = sorted(set(op) - set(sp))
            removed = sorted(set(sp) - set(op))
            if added or removed:
                fd_delta[f] = {}
                if added:   fd_delta[f]["added"]   = added
                if removed: fd_delta[f]["removed"] = removed
        if fd_delta:
            delta["field_deny"] = fd_delta

        return delta

    def is_equivalent(self, other: "IntentContract") -> bool:
        """Return True if contracts are semantically identical."""
        return self.diff(other) == {}

    @classmethod
    def from_dict(cls, d: dict, name: str = "") -> "IntentContract":
        """Deserialize from dict."""
        return cls(
            deny          = d.get("deny", []),
            only_paths    = d.get("only_paths", []),
            deny_commands = d.get("deny_commands", []),
            only_domains  = d.get("only_domains", []),
            invariant          = d.get("invariant", []),
            optional_invariant = d.get("optional_invariant", []),
            postcondition      = d.get("postcondition", []),
            field_deny    = d.get("field_deny", {}),
            value_range   = d.get("value_range", {}),
            obligation_timing = d.get("obligation_timing", {}),
            # v0.42.0: Contract legitimacy lifecycle
            confirmed_by      = d.get("confirmed_by", ""),
            confirmed_at      = d.get("confirmed_at", 0.0),
            valid_until       = d.get("valid_until", 0.0),
            review_triggers   = d.get("review_triggers", []),
            status            = d.get("status", ""),
            superseded_by     = d.get("superseded_by", ""),
            version           = d.get("version", 1),
            legitimacy_decay  = d.get("legitimacy_decay", {}),
            name          = name,
        )

    def merge(self, constitutional: "ConstitutionalContract") -> "IntentContract":
        """
        Inherit constraints from the constitutional layer and return a merged contract.

        Inheritance rule: the statutory layer can only be stricter than the constitutional layer,
        never looser. Constitutional constraints are unconditionally propagated; statutory
        constraints are preserved.

        only_paths / only_domains in the constitutional layer are whitelists —
        the statutory whitelist must be a subset of the constitutional whitelist.
        """
        def merge_list(a: list, b: list) -> list:
            return list(dict.fromkeys(a + b))

        def merge_whitelist(statutory: list, constitutional: list) -> list:
            # When the constitutional whitelist exists, the statutory layer must be a subset
            # If the statutory layer has no whitelist of its own, inherit from the constitutional layer
            if not statutory:
                return constitutional
            if not constitutional:
                return statutory
            # Both exist: keep the statutory whitelist (already stricter than constitutional)
            return statutory

        def merge_field_deny(a: dict, b: dict) -> dict:
            merged = dict(a)
            for k, v in b.items():
                if k in merged:
                    merged[k] = list(dict.fromkeys(merged[k] + v))
                else:
                    merged[k] = v
            return merged

        def merge_value_range(a: dict, b: dict) -> dict:
            merged = dict(a)
            for param, bounds in b.items():
                if param not in merged:
                    merged[param] = bounds
                else:
                    # Take stricter: max(min), min(max)
                    existing = merged[param]
                    new_min = bounds.get("min")
                    new_max = bounds.get("max")
                    if new_min is not None:
                        existing["min"] = max(
                            float(existing.get("min", new_min)),
                            float(new_min)
                        )
                    if new_max is not None:
                        existing["max"] = min(
                            float(existing.get("max", new_max)),
                            float(new_max)
                        )
                    merged[param] = existing
            return merged

        return IntentContract(
            deny               = merge_list(self.deny, constitutional.deny),
            only_paths         = merge_whitelist(self.only_paths, constitutional.only_paths),
            deny_commands      = merge_list(self.deny_commands, constitutional.deny_commands),
            only_domains       = merge_whitelist(self.only_domains, constitutional.only_domains),
            invariant          = merge_list(self.invariant, constitutional.invariant),
            optional_invariant = merge_list(self.optional_invariant,
                                            constitutional.optional_invariant),
            postcondition      = merge_list(self.postcondition, constitutional.postcondition),
            field_deny         = merge_field_deny(self.field_deny, constitutional.field_deny),
            value_range        = merge_value_range(self.value_range, constitutional.value_range),
            name               = self.name,
        )

    def is_empty(self) -> bool:
        return not any([
            self.deny, self.only_paths, self.deny_commands,
            self.only_domains, self.invariant, self.optional_invariant,
            self.postcondition, self.field_deny, self.value_range,
        ])

    def is_subset_of(self, parent: "IntentContract") -> tuple:
        """
        Check whether this contract is a strict subset of (no looser than) parent.

        Monotonicity rules for delegation:
          deny          : child must include all parent denials (deny-list only grows)
          deny_commands : child must include all parent deny_commands
          only_paths    : if parent restricts, child must be equal or stricter subset
          only_domains  : same as only_paths
          invariant     : child must include all parent invariants
          value_range   : child max ≤ parent max; child min ≥ parent min
          action_scope  : compared at DelegationContract level, not IntentContract

        Returns:
            (is_subset: bool, violations: List[str])
        """
        violations = []

        # deny: child must have all parent denials
        missing_deny = set(parent.deny) - set(self.deny)
        if missing_deny:
            violations.append(
                f"Child drops parent deny rules: {sorted(missing_deny)}"
            )

        # deny_commands: child must have all parent deny_commands
        missing_dc = set(parent.deny_commands) - set(self.deny_commands)
        if missing_dc:
            violations.append(
                f"Child drops parent deny_commands: {sorted(missing_dc)}"
            )

        # only_paths: if parent restricts, child must be a subset
        if parent.only_paths:
            if not self.only_paths:
                violations.append(
                    "Child removes only_paths restriction (parent had whitelist)"
                )
            else:
                # every child path must be WITHIN a parent path
                # i.e. child_path starts with parent_path (child is narrower/more specific)
                # CORRECT:   './src/payments' ⊆ './src'       → './src/payments/'.startswith('./src/') ✓
                # VIOLATION: './src'          ⊃ './src/payments' → './src/'.startswith('./src/payments/') ✗
                for cp in self.only_paths:
                    cp_norm = cp.rstrip("/") + "/"
                    if not any(
                        cp_norm.startswith(pp.rstrip("/") + "/")
                        for pp in parent.only_paths
                    ):
                        violations.append(
                            f"Child only_paths '{cp}' is not within parent "
                            f"whitelist {parent.only_paths} (child scope is wider)"
                        )

        # only_domains: if parent restricts, child must be a subset
        if parent.only_domains:
            if not self.only_domains:
                violations.append(
                    "Child removes only_domains restriction (parent had whitelist)"
                )
            else:
                for cd in self.only_domains:
                    if cd not in parent.only_domains:
                        violations.append(
                            f"Child only_domains '{cd}' not in parent whitelist {parent.only_domains}"
                        )

        # invariant: child must preserve all parent invariants
        missing_inv = set(parent.invariant) - set(self.invariant)
        if missing_inv:
            violations.append(
                f"Child drops parent invariants: {sorted(missing_inv)}"
            )

        # value_range: child must be at least as strict
        for param, pbounds in parent.value_range.items():
            if param not in self.value_range:
                violations.append(
                    f"Child drops value_range constraint on '{param}' "
                    f"(parent had {pbounds})"
                )
                continue
            cbounds = self.value_range[param]
            p_max = pbounds.get("max")
            c_max = cbounds.get("max")
            if p_max is not None and c_max is not None:
                if float(c_max) > float(p_max):
                    violations.append(
                        f"Child loosens value_range['{param}'].max: "
                        f"{c_max} > parent {p_max}"
                    )
            p_min = pbounds.get("min")
            c_min = cbounds.get("min")
            if p_min is not None and c_min is not None:
                if float(c_min) < float(p_min):
                    violations.append(
                        f"Child loosens value_range['{param}'].min: "
                        f"{c_min} < parent {p_min}"
                    )

        return (len(violations) == 0, violations)

    def to_markdown(self, title: str = "Intent Contract", include_metadata: bool = False) -> str:
        """
        Render this IntentContract as human-readable Markdown.

        Useful for debugging, reporting, and human review of contracts.
        Consistent with ConstitutionalContract.to_markdown() API.

        Args:
            title: The document title
            include_metadata: If True, include legitimacy and lifecycle fields

        Returns:
            Markdown-formatted string representation
        """
        lines = []

        # Header with hash
        hash_short = self.hash[:16] if self.hash else "no-hash"
        lines.append(f"# {title}")
        if self.name:
            lines.append(f"**Name**: `{self.name}`")
        lines.append(f"**Hash**: `{hash_short}...`")
        lines.append("")

        def section(header: str, items: list, bullet: str = "- ") -> None:
            if items:
                lines.append(f"### {header}")
                for item in items:
                    lines.append(f"{bullet}{item}")
                lines.append("")

        # Base 8 dimensions
        section("Absolute Denials", self.deny)
        section("Denied Commands", self.deny_commands)
        section("Allowed Paths Only", self.only_paths)
        section("Allowed Domains Only", self.only_domains)
        section("Invariants (hard)", self.invariant)
        section("Invariants (optional)", self.optional_invariant)
        section("Postconditions", self.postcondition)

        if self.field_deny:
            lines.append("### Field Deny Rules")
            for field_name, blocked in self.field_deny.items():
                lines.append(f"- field `{field_name}` must not contain:")
                for b in blocked:
                    lines.append(f"    - {b}")
            lines.append("")

        if self.value_range:
            lines.append("### Value Range Constraints")
            for param, bounds in self.value_range.items():
                parts = []
                if "min" in bounds:
                    parts.append(f"min={bounds['min']}")
                if "max" in bounds:
                    parts.append(f"max={bounds['max']}")
                lines.append(f"- `{param}`: {', '.join(parts)}")
            lines.append("")

        if self.obligation_timing:
            lines.append("### Obligation Timing (seconds)")
            for key, seconds in self.obligation_timing.items():
                lines.append(f"- `{key}`: {seconds}s")
            lines.append("")

        # Contract legitimacy lifecycle (optional)
        if include_metadata and (self.confirmed_by or self.status):
            lines.append("### Lifecycle Metadata")
            if self.status:
                lines.append(f"- **Status**: {self.status}")
            if self.confirmed_by:
                lines.append(f"- **Confirmed by**: {self.confirmed_by}")
            if self.confirmed_at:
                import datetime
                dt = datetime.datetime.fromtimestamp(self.confirmed_at)
                lines.append(f"- **Confirmed at**: {dt.isoformat()}")
            if self.valid_until:
                import datetime
                dt = datetime.datetime.fromtimestamp(self.valid_until)
                lines.append(f"- **Valid until**: {dt.isoformat()}")
            if self.review_triggers:
                lines.append(f"- **Review triggers**: {', '.join(self.review_triggers)}")
            if self.version != 1:
                lines.append(f"- **Version**: {self.version}")
            lines.append("")

        return "\n".join(lines).rstrip()

    def __str__(self) -> str:
        parts = []
        if self.deny:          parts.append(f"deny={self.deny}")
        if self.only_paths:    parts.append(f"only_paths={self.only_paths}")
        if self.deny_commands: parts.append(f"deny_commands={self.deny_commands}")
        if self.only_domains:  parts.append(f"only_domains={self.only_domains}")
        if self.invariant:          parts.append(f"invariant={self.invariant}")
        if self.optional_invariant: parts.append(f"optional_invariant={self.optional_invariant}")
        if self.postcondition: parts.append(f"postcondition={self.postcondition}")
        name = f"<{self.name}> " if self.name else ""
        return f"IntentContract({name}{', '.join(parts)})"


# ── Constitutional layer ─────────────────────────────────────────────────────

@dataclass
class ConstitutionalContract:
    """
    Global constitutional layer constraints.

    Applied to every function in the system via IntentContract.merge().
    Constitutional constraints can only be tightened, never overridden by the statutory layer.

    Design principle:
      The constitutional layer expresses "system-level intent" — universal constraints across all functions.
      The statutory layer expresses "function-level intent" — specific constraints for a particular function.

    Example:
      ConstitutionalContract(
          deny=["production", "/etc/"],       # no function may touch production or system files
          only_domains=["api.internal.com"],  # all network calls must stay on the internal network
          value_range={"amount": {"max": 1000000}},  # global amount ceiling
      )
    """
    deny:          List[str]            = field(default_factory=list)
    only_paths:    List[str]            = field(default_factory=list)
    deny_commands: List[str]            = field(default_factory=list)
    only_domains:  List[str]            = field(default_factory=list)
    invariant:          List[str]            = field(default_factory=list)
    optional_invariant: List[str]            = field(default_factory=list)
    postcondition:      List[str]            = field(default_factory=list)
    field_deny:         Dict[str, List[str]] = field(default_factory=dict)
    value_range:        Dict[str, Dict]      = field(default_factory=dict)
    name:          str                  = "constitutional"
    hash:          str                  = ""

    def __post_init__(self):
        if not self.hash:
            d = {
                "deny": self.deny, "only_paths": self.only_paths,
                "deny_commands": self.deny_commands,
                "only_domains": self.only_domains,
                "invariant": self.invariant,
            }
            canonical = json.dumps(d, sort_keys=True, ensure_ascii=True)
            self.hash = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def is_empty(self) -> bool:
        return not any([
            self.deny, self.only_paths, self.deny_commands,
            self.only_domains, self.invariant, self.postcondition,
            self.field_deny, self.value_range,
        ])

    def to_markdown(self, title: str = "Constraints", indent: int = 0) -> str:
        """
        Render this ConstitutionalContract as human-readable Markdown.

        This is the reverse of parsing AGENTS.md.
        The contract is the canonical source; Markdown is a derived view.
        """
        pad = "  " * indent
        lines = []

        def section(header, items, bullet="- "):
            if items:
                lines.append(f"\n{pad}### {header}")
                for item in items:
                    lines.append(f"{pad}{bullet}{item}")

        lines.append(f"# {title}  (hash: {self.hash[:16]}...)")
        lines.append(f"# Auto-generated from ConstitutionalContract — DO NOT EDIT MANUALLY")
        lines.append(f"# Edit the contract in ystar/domains/ystar_dev/__init__.py")
        lines.append("")

        section("Absolute Denials", self.deny)
        section("Denied Commands", self.deny_commands)
        section("Allowed Paths Only", self.only_paths)
        section("Allowed Domains Only", self.only_domains)
        section("Invariants (hard)", self.invariant)
        section("Invariants (optional)", self.optional_invariant)
        section("Postconditions", self.postcondition)

        if self.field_deny:
            lines.append(f"\n{pad}### Field Deny Rules")
            for field_name, blocked in self.field_deny.items():
                lines.append(f"{pad}- field `{field_name}` must not contain:")
                for b in blocked:
                    lines.append(f"{pad}    - {b}")

        if self.value_range:
            lines.append(f"\n{pad}### Value Range Constraints")
            for param, bounds in self.value_range.items():
                parts = []
                if "min" in bounds:
                    parts.append(f"min={bounds['min']}")
                if "max" in bounds:
                    parts.append(f"max={bounds['max']}")
                lines.append(f"{pad}- `{param}`: {', '.join(parts)}")

        return "\n".join(lines)

    def to_agents_md(self, path: str = "AGENTS.md") -> str:
        """
        Write this contract as AGENTS.md.

        This inverts the current AGENTS.md → contract flow.
        The contract IS the truth; AGENTS.md is its human-readable projection.
        """
        md = self.to_markdown(title="Y* Development Constraints — AGENTS.md (generated)")
        if path:
            with open(path, "w") as f:
                f.write(md + "\n")
        return md

    def diff(self, other: "ConstitutionalContract") -> dict:
        """
        Compare two ConstitutionalContracts — same semantics as IntentContract.diff().
        Critical for tracking YSTAR_CONSTITUTION evolution across versions.
        """
        # Reuse IntentContract.diff() by projecting down
        from_ic = IntentContract(
            deny=self.deny, deny_commands=self.deny_commands,
            only_paths=self.only_paths, only_domains=self.only_domains,
            invariant=self.invariant, optional_invariant=self.optional_invariant,
            field_deny=self.field_deny, value_range=self.value_range,
        )
        to_ic = IntentContract(
            deny=other.deny, deny_commands=other.deny_commands,
            only_paths=other.only_paths, only_domains=other.only_domains,
            invariant=other.invariant, optional_invariant=other.optional_invariant,
            field_deny=other.field_deny, value_range=other.value_range,
        )
        return from_ic.diff(to_ic)

    def to_prefill_params(self) -> dict:
        """
        Export this contract as a prefill-compatible params dict.

        This allows ConstitutionalContract to feed directly into the prefill
        pipeline without going through AGENTS.md text parsing.

        The returned dict has the same structure as _extract_constraints_from_text()
        output, so it slots in as a drop-in replacement for Source 1.
        """
        return {
            "_prov": {
                "source": "ConstitutionalContract",
                "hash":   self.hash[:32],
                "name":   self.name,
            },
            "deny":          list(self.deny),
            "deny_commands": list(self.deny_commands),
            "only_paths":    list(self.only_paths),
            "only_domains":  list(self.only_domains),
            "invariant":     list(self.invariant),
            "optional_invariant": list(self.optional_invariant),
            "field_deny":    {k: list(v) for k, v in self.field_deny.items()},
            "value_range":   dict(self.value_range),
        }

    @classmethod
    def from_markdown(cls, text: str, name: str = "parsed") -> "ConstitutionalContract":
        """
        Parse a Markdown rule document into a ConstitutionalContract.

        This is the NL→contract direction, used by:
          - prefill layer (Source7)
          - ystar-dev when a human wants to add a new rule in plain language
        """
        deny, deny_commands, only_paths, only_domains = [], [], [], []
        invariant, optional_invariant = [], []

        current_section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("### "):
                current_section = stripped[4:].lower()
                continue
            if not stripped.startswith("- "):
                continue
            item = stripped[2:].strip()

            if "absolute denial" in current_section or "denial" in current_section:
                deny.append(item)
            elif "command" in current_section:
                deny_commands.append(item)
            elif "path" in current_section:
                only_paths.append(item)
            elif "domain" in current_section:
                only_domains.append(item)
            elif "optional" in current_section:
                optional_invariant.append(item)
            elif "invariant" in current_section:
                invariant.append(item)

        return cls(
            deny=deny, deny_commands=deny_commands,
            only_paths=only_paths, only_domains=only_domains,
            invariant=invariant, optional_invariant=optional_invariant,
            name=name,
        )


# ── Higher-order dimensions ──────────────────────────────────────────────────

@dataclass
class TemporalConstraint:
    """
    Temporal constraint: time and ordering relationships across calls.

    Expresses constraints that the base 8 dimensions cannot:
      "The same account may transfer at most 3 times in 24 hours."
      "authenticate() must be called before transfer()."
      "No more than 100 calls per minute."

    Fields:
      max_calls_per_window: maximum number of calls within the time window
      window_seconds:       length of the time window (seconds)
      requires_before:      list of functions that must be called before this one
      min_interval_seconds: minimum interval between consecutive calls
      key_param:            parameter name used to identify the same subject (e.g. "account_id")
    """
    max_calls_per_window: Optional[int]   = None
    window_seconds:       Optional[float] = None
    requires_before:      List[str]       = field(default_factory=list)
    min_interval_seconds: Optional[float] = None
    key_param:            str             = ""

    def is_empty(self) -> bool:
        return not any([
            self.max_calls_per_window, self.window_seconds,
            self.requires_before, self.min_interval_seconds,
        ])



# ══════════════════════════════════════════════════════════════════════════════
# v0.17.0  TemporalContext + ScheduledWindow — time synchronisation
# ══════════════════════════════════════════════════════════════════════════════

# ── TimeWindow: kernel-level temporal primitive ──────────────────────────────
# The kernel's only temporal concept: a bounded time interval in epoch seconds.
# Domain packs (e.g. finance) build ScheduledWindow on top of this.

@dataclass
class TimeWindow:
    """
    A time interval defined entirely by epoch timestamps.
    This is the kernel-level primitive for temporal constraints.

    Domain packs convert wall-clock times + timezones to epoch timestamps
    and pass a TimeWindow to the kernel — the kernel never interprets
    timezone names or HH:MM strings.
    """
    valid_from:  Optional[float] = None  # epoch seconds; None = no lower bound
    valid_until: Optional[float] = None  # epoch seconds; None = no upper bound

    def contains(self, now: float) -> bool:
        if self.valid_from  is not None and now < self.valid_from:  return False
        if self.valid_until is not None and now > self.valid_until: return False
        return True

    def is_empty(self) -> bool:
        return self.valid_from is None and self.valid_until is None

    def to_dict(self) -> dict:
        return {"valid_from": self.valid_from, "valid_until": self.valid_until}

    @classmethod
    def from_dict(cls, d: dict) -> "TimeWindow":
        return cls(valid_from=d.get("valid_from"), valid_until=d.get("valid_until"))


@dataclass
class TemporalContext:
    """
    Session-level temporal context, injected once by the caller at session start.

    Solves the core problem of class-B constraints: Y* itself does not need to "know" the time;
    it only needs the caller to tell it "what time it is and in which timezone".

    Usage:
        ctx = TemporalContext(
            reference_date="2026-03-20",
            timezone="America/New_York",
        )
        # Pass to any time-aware operation
        sw = ScheduledWindow.from_text("10:00 to 11:30", ctx)
        sw.is_within_window()  # check whether the current time is inside the window

    Fields:
        reference_date: session date (YYYY-MM-DD), used to convert wall-clock time to epoch
        timezone:       timezone name, defaults to UTC
        now_override:   optional override for time.time() (useful for testing / back-testing)
    """
    reference_date: str   = ""        # "2026-03-20"
    timezone:       str   = "UTC"     # "America/New_York" / "Asia/Shanghai"
    now_override:   float = 0.0       # 0.0 = use time.time()

    def now(self) -> float:
        """Return the current timestamp in seconds."""
        import time as _time
        return self.now_override if self.now_override > 0 else _time.time()

    def to_epoch(self, time_str: str) -> float:
        """
        Convert "HH:MM" or "HH:MM:SS" to today's epoch timestamp.

        time_str: "10:00" / "14:30" / "09:30:00"
        Returns: float epoch timestamp
        """
        import datetime as _dt

        # Parse time string
        time_str = time_str.strip()
        if len(time_str) == 5:   # "HH:MM"
            h, m, s = int(time_str[:2]), int(time_str[3:5]), 0
        elif len(time_str) == 8:  # "HH:MM:SS"
            h, m, s = int(time_str[:2]), int(time_str[3:5]), int(time_str[6:8])
        else:
            raise ValueError(f"Unsupported time format: {time_str!r}")

        # Parse date
        if self.reference_date:
            parts = self.reference_date.split("-")
            date = _dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            date = _dt.date.today()

        # Build naive datetime, then convert to UTC epoch
        naive = _dt.datetime(date.year, date.month, date.day, h, m, s)

        # Timezone offset: look up via module-level registry (extensible by domain packs)
        # Domain packs call register_timezone_offset(name, hours) to add more.
        offset_h = _TIMEZONE_OFFSETS.get(self.timezone, 0)
        utc_epoch = naive.timestamp() - offset_h * 3600
        return utc_epoch

    def to_dict(self) -> dict:
        return {"reference_date": self.reference_date,
                "timezone": self.timezone, "now_override": self.now_override}

    @classmethod
    def from_dict(cls, d: dict) -> "TemporalContext":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class ScheduledWindow:
    """
    Fixed-window constraint: execution is permitted only within a specified time slot.

    Difference from TemporalConstraint:
      TemporalConstraint: rolling window ("at most X calls in N seconds")
      ScheduledWindow:    fixed slot   ("permitted only between 10:00 and 11:30")

    Usage:
        sw = ScheduledWindow(start_time="10:00", end_time="11:30")
        ctx = TemporalContext(reference_date="2026-03-20",
                               timezone="America/New_York")
        if not sw.is_within_window(ctx):
            # current time is outside the execution window
            ...

        # Can also be used inside an IntentContract check() pipeline
        violations = sw.check(ctx)  # → [] or [Violation(...)]
    """
    start_time:  str = ""   # "09:30" / "10:00" / "" (no lower bound)
    end_time:    str = ""   # "16:00" / "11:30" / "" (no upper bound)
    timezone:    str = "UTC"
    description: str = ""   # human-readable description, used in violation messages

    def is_within_window(self, ctx: Optional["TemporalContext"] = None,
                          now: Optional[float] = None) -> bool:
        """Return True if the current time falls within the window."""
        import time as _t
        _ctx  = ctx or TemporalContext()
        _now  = now or _ctx.now()

        if self.start_time:
            start_epoch = _ctx.to_epoch(self.start_time)
            if _now < start_epoch:
                return False

        if self.end_time:
            end_epoch = _ctx.to_epoch(self.end_time)
            if _now > end_epoch:
                return False

        return True

    def check(self, ctx: Optional["TemporalContext"] = None,
               now: Optional[float] = None) -> list:
        """
        Return a list of violation strings (aligned with the check() pipeline).

        Returns:
            [] if within the window
            [str] if outside the window (violation description)
        """
        import time as _t
        _ctx = ctx or TemporalContext()
        _now = now or _ctx.now()

        import datetime as _dt
        now_readable = _dt.datetime.fromtimestamp(_now).strftime("%H:%M:%S")

        if self.start_time and self.end_time:
            window_desc = f"[{self.start_time}, {self.end_time}]"
        elif self.start_time:
            window_desc = f"[{self.start_time}, ∞)"
        elif self.end_time:
            window_desc = f"(-∞, {self.end_time}]"
        else:
            return []  # 无限制

        if not self.is_within_window(_ctx, _now):
            return [
                f"Current time {now_readable} is outside scheduled window "
                f"{window_desc}. "
                f"{self.description or 'Execution not permitted at this time.'}"
            ]
        return []

    def seconds_until_open(self, ctx: Optional["TemporalContext"] = None) -> float:
        """Seconds until the window opens (0 if already open)."""
        _ctx = ctx or TemporalContext()
        _now = _ctx.now()
        if not self.start_time:
            return 0.0
        start_epoch = _ctx.to_epoch(self.start_time)
        return max(0.0, start_epoch - _now)

    def seconds_until_close(self, ctx: Optional["TemporalContext"] = None) -> float:
        """Seconds until the window closes (0 if already closed)."""
        _ctx = ctx or TemporalContext()
        _now = _ctx.now()
        if not self.end_time:
            return float("inf")
        end_epoch = _ctx.to_epoch(self.end_time)
        return max(0.0, end_epoch - _now)

    @classmethod
    def from_text(cls, text: str,
                   ctx: Optional["TemporalContext"] = None) -> "ScheduledWindow":
        """
        Parse a scheduled window from natural-language text.

        Supported formats:
          "10:00 to 11:30"
          "between 10:00 and 11:30"
          "09:30 AM to 04:00 PM"
          "before 11:30"
          "after 09:30"
        """
        import re
        tz = ctx.timezone if ctx else "UTC"
        text_l = text.lower().strip()

        # Time regex: matches HH:MM or H:MM with optional AM/PM
        _T = r"(\d{1,2}:\d{2})(?:\s*([ap]m))?"

        # Pattern 1: X to/through/- Y
        m = re.search(
            r"(?:between\s+)?" + _T + r"\s*(?:to|through|-|到|至|and)\s*" + _T,
            text_l, re.IGNORECASE
        )
        if m:
            start_raw, start_ampm, end_raw, end_ampm = m.groups()
            start = cls._normalize_time(start_raw, start_ampm)
            end   = cls._normalize_time(end_raw,   end_ampm)
            return cls(start_time=start, end_time=end, timezone=tz,
                        description=f"Parsed from: '{text}'")

        # Pattern 2: before X
        m = re.search(r"before\s+" + _T, text_l, re.IGNORECASE)
        if m:
            end_raw, end_ampm = m.groups()
            return cls(end_time=cls._normalize_time(end_raw, end_ampm),
                        timezone=tz, description=f"Parsed from: '{text}'")

        # Pattern 3: after X
        m = re.search(r"after\s+" + _T, text_l, re.IGNORECASE)
        if m:
            start_raw, start_ampm = m.groups()
            return cls(start_time=cls._normalize_time(start_raw, start_ampm),
                        timezone=tz, description=f"Parsed from: '{text}'")

        return cls(timezone=tz)  # unable to parse — return unrestricted window

    @staticmethod
    def _normalize_time(time_str: str, ampm: Optional[str]) -> str:
        """Normalise "9:30" + "am" → "09:30"; add 12 hours for PM."""
        h, m = time_str.split(":")
        h_int = int(h)
        if ampm:
            if ampm.lower() == "pm" and h_int != 12:
                h_int += 12
            elif ampm.lower() == "am" and h_int == 12:
                h_int = 0
        return f"{h_int:02d}:{m}"

    def to_dict(self) -> dict:
        return {"start_time": self.start_time, "end_time": self.end_time,
                "timezone": self.timezone, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduledWindow":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def __str__(self) -> str:
        if self.start_time and self.end_time:
            return f"ScheduledWindow({self.start_time}–{self.end_time} {self.timezone})"
        elif self.start_time:
            return f"ScheduledWindow(after {self.start_time} {self.timezone})"
        elif self.end_time:
            return f"ScheduledWindow(before {self.end_time} {self.timezone})"
        return "ScheduledWindow(unrestricted)"


@dataclass
class ExternalContext:
    """
    Session-level external context, injected once by the caller.

    Kernel principle: Y* is a constraint compiler, not an information system.
    The caller fetches domain values and injects them here; Y* ensures they
    do not drift across the multi-agent system.

    For domain-specific fields (approved venues, brokers, risk snapshots etc.)
    use the domain's own subclass, e.g.:
        from ystar.domains.finance.adapters import FinanceExternalContext

    Fields:
        temporal:  temporal context (date / timezone)
        custom:    arbitrary domain-specific extension fields
    """
    temporal: Optional["TemporalContext"] = None
    custom:   Dict[str, Any] = field(default_factory=dict)

    def has_temporal(self) -> bool:
        return self.temporal is not None

    def to_dict(self) -> dict:
        d: Dict[str, Any] = {"custom": self.custom}
        if self.temporal:
            d["temporal"] = self.temporal.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ExternalContext":
        temporal_d = d.get("temporal")
        temporal   = TemporalContext.from_dict(temporal_d) if temporal_d else None
        return cls(temporal=temporal, custom=d.get("custom", {}))


@dataclass
class AggregateConstraint:
    """
    Aggregate constraint: cumulative-value constraint across multiple calls.

    Expresses constraints that the base 8 dimensions cannot:
      "Total transfers today must not exceed $1 000 000."
      "Total amount received by the same recipient within 1 hour must not exceed $100 000."

    Fields:
      param:          name of the parameter to aggregate
      max_sum:        upper bound on the aggregate value
      min_sum:        lower bound on the aggregate value
      window_seconds: aggregation time window
      group_by:       parameter to group by before aggregating (e.g. "recipient")
    """
    param:          str             = ""
    max_sum:        Optional[float] = None
    min_sum:        Optional[float] = None
    window_seconds: Optional[float] = None
    group_by:       str             = ""

    def is_empty(self) -> bool:
        return not self.param


@dataclass
class ContextConstraint:
    """
    Caller context constraint: restricts who may call this function.

    Expresses constraints that the base 8 dimensions cannot:
      "Only role=admin may call this."
      "Permitted only in environment=staging."
      "Caller must have completed 2FA verification."

    Fields:
      required_roles:  list of permitted caller roles
      required_env:    list of permitted environments (staging / dev / etc.)
      deny_env:        list of forbidden environments (production / etc.)
      required_flags:  flags that must be True in the caller context
    """
    required_roles: List[str] = field(default_factory=list)
    required_env:   List[str] = field(default_factory=list)
    deny_env:       List[str] = field(default_factory=list)
    required_flags: List[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([
            self.required_roles, self.required_env,
            self.deny_env, self.required_flags,
        ])


@dataclass
class ResourceConstraint:
    """
    Resource consumption constraint: caps on resources used during function execution.

    Expresses constraints that the base 8 dimensions cannot:
      "Execution time must not exceed 5 seconds."
      "Memory usage must not exceed 512 MB."

    Fields:
      max_execution_seconds: maximum execution time
      max_memory_mb:         maximum memory usage
      max_output_bytes:      maximum output size
    """
    max_execution_seconds: Optional[float] = None
    max_memory_mb:         Optional[float] = None
    max_output_bytes:      Optional[int]   = None

    def is_empty(self) -> bool:
        return not any([
            self.max_execution_seconds,
            self.max_memory_mb,
            self.max_output_bytes,
        ])


@dataclass
class HigherOrderContract:
    """
    Higher-order contract: 4 constraint types not covered by the base 8 dimensions.

    Used together with IntentContract:
      IntentContract      → per-call parameter/result constraints (stateless)
      HigherOrderContract → cross-call temporal/aggregate/context/resource constraints (stateful)

    Higher-order dimension checks require external state (call history, caller info)
    and are therefore separate from the base 8-dimension check().
    """
    temporal:          TemporalConstraint  = field(default_factory=TemporalConstraint)
    aggregate:         AggregateConstraint = field(default_factory=AggregateConstraint)
    context:           ContextConstraint   = field(default_factory=ContextConstraint)
    resource:          ResourceConstraint  = field(default_factory=ResourceConstraint)
    scheduled_window:  Optional["ScheduledWindow"]  = None   # v0.17: fixed-slot constraint
    temporal_context:  Optional["TemporalContext"]  = None   # v0.17: timezone / date context
    func_name: str                 = ""

    def is_empty(self) -> bool:
        return all([
            self.temporal.is_empty(), self.aggregate.is_empty(),
            self.context.is_empty(), self.resource.is_empty(),
        ])

    def check_context(self, caller_context: Dict[str, Any]) -> List[str]:
        """
        Check caller context constraints.
        Returns a list of violation descriptions; empty list means all passed.
        caller_context example: {"role": "user", "env": "production", "2fa": True}
        """
        violations = []
        c = self.context

        if c.required_roles and caller_context.get("role") not in c.required_roles:
            violations.append(
                f"caller role '{caller_context.get('role')}' "
                f"not in required roles {c.required_roles}"
            )
        if c.deny_env and caller_context.get("env") in c.deny_env:
            violations.append(
                f"environment '{caller_context.get('env')}' is denied"
            )
        if c.required_env and caller_context.get("env") not in c.required_env:
            violations.append(
                f"environment '{caller_context.get('env')}' "
                f"not in required environments {c.required_env}"
            )
        for flag in c.required_flags:
            if not caller_context.get(flag):
                violations.append(f"required flag '{flag}' is not set")

        return violations

    def check_temporal(
        self,
        call_history: List[Dict],   # [{"ts": float, "key": str}, ...]
        current_ts:   float,
        current_key:  str = "",
    ) -> List[str]:
        """
        Check temporal (rate-limit) constraints.
        call_history: past call records, each containing a timestamp and a key value
        current_ts: timestamp of the current call
        current_key: key value of the current call (e.g. account ID)
        """
        violations = []
        t = self.temporal

        if t.max_calls_per_window and t.window_seconds:
            window_start = current_ts - t.window_seconds
            relevant = [
                c for c in call_history
                if c.get("ts", 0) >= window_start
                and (not t.key_param or c.get("key", "") == current_key)
            ]
            if len(relevant) >= t.max_calls_per_window:
                violations.append(
                    f"rate limit exceeded: {len(relevant)} calls in "
                    f"{t.window_seconds}s window "
                    f"(max {t.max_calls_per_window})"
                )

        if t.min_interval_seconds and call_history:
            last_relevant = [
                c for c in call_history
                if not t.key_param or c.get("key", "") == current_key
            ]
            if last_relevant:
                last_ts = max(c.get("ts", 0) for c in last_relevant)
                interval = current_ts - last_ts
                if interval < t.min_interval_seconds:
                    violations.append(
                        f"minimum interval {t.min_interval_seconds}s not met "
                        f"(actual: {interval:.2f}s)"
                    )

        return violations

    def check_aggregate(
        self,
        call_history: List[Dict],   # [{"ts": float, "value": float, "group": str}]
        current_ts:   float,
        current_value: float = 0.0,
        current_group: str = "",
    ) -> List[str]:
        """Check aggregate constraints."""
        violations = []
        a = self.aggregate

        if not a.param or a.max_sum is None:
            return violations

        window_start = current_ts - (a.window_seconds or float("inf"))
        relevant = [
            c for c in call_history
            if c.get("ts", 0) >= window_start
            and (not a.group_by or c.get("group", "") == current_group)
        ]
        total = sum(c.get("value", 0) for c in relevant) + current_value

        if a.max_sum is not None and total > a.max_sum:
            violations.append(
                f"aggregate sum {total} exceeds max {a.max_sum} "
                f"in {a.window_seconds}s window"
                + (f" for group '{current_group}'" if current_group else "")
            )

        return violations

    def check_resource(self, execution_seconds: float = 0.0,
                       memory_mb: float = 0.0,
                       output_bytes: int = 0) -> List[str]:
        """Check resource consumption constraints."""
        violations = []
        r = self.resource
        if r.max_execution_seconds and execution_seconds > r.max_execution_seconds:
            violations.append(
                f"execution time {execution_seconds:.2f}s "
                f"exceeds limit {r.max_execution_seconds}s"
            )
        if r.max_memory_mb and memory_mb > r.max_memory_mb:
            violations.append(
                f"memory {memory_mb:.1f}MB exceeds limit {r.max_memory_mb}MB"
            )
        if r.max_output_bytes and output_bytes > r.max_output_bytes:
            violations.append(
                f"output {output_bytes} bytes exceeds limit {r.max_output_bytes}"
            )
        return violations

    def check_window(self,
                     ctx=None,
                     now=None):
        """
        Verify current time is within scheduled_window.
        Returns [] if within window or no window set,
        or [violation_str] if outside window.
        """
        if self.scheduled_window is None:
            return []
        _ctx = ctx or self.temporal_context or TemporalContext()
        return self.scheduled_window.check(_ctx, now)

    def is_within_window(self, ctx=None, now=None) -> bool:
        """Return True if current time is within scheduled_window (or no window set)."""
        if self.scheduled_window is None:
            return True
        _ctx = ctx or self.temporal_context or TemporalContext()
        return self.scheduled_window.is_within_window(_ctx, now)

    def check_all(
        self,
        params,
        result,
        contract,
        history=None,
        caller_context=None,
        temporal_ctx=None,
        now=None,
    ):
        """
        Unified stateful check: combines IntentContract + HigherOrderContract violations.

        Args:
            params:         call parameters
            result:         call result
            contract:       IntentContract (8-dimension base constraints)
            history:        call history list (for temporal/aggregate checks)
            caller_context: caller role/env dict (for context checks)
            temporal_ctx:   TemporalContext (overrides self.temporal_context)
            now:            current timestamp override

        Returns:
            CheckResult with violations from all dimensions combined.
        """
        import time as _time
        from ystar.kernel.engine import check as _check, Violation, CheckResult

        base_result = _check(params, result, contract)
        all_violations = list(base_result.violations)

        # Resolve temporal context — temporal_ctx may be a TemporalContext OR an
        # ExternalContext (which carries a .temporal field).  Accept both.
        _ext_ctx_arg = None
        if temporal_ctx is not None and isinstance(temporal_ctx, ExternalContext):
            # It is an ExternalContext — extract the inner TemporalContext
            _ext_ctx_arg = temporal_ctx
            _ctx = (temporal_ctx.temporal
                    or self.temporal_context
                    or TemporalContext())
        else:
            _ctx = temporal_ctx or self.temporal_context or TemporalContext()

        _now = now or _ctx.now()

        # ScheduledWindow: fixed-time-slot constraint
        if self.scheduled_window:
            for msg in self.check_window(_ctx, _now):
                all_violations.append(Violation(
                    dimension  = "scheduled_window",
                    field      = "execution_time",
                    message    = msg,
                    actual     = str(_now),
                    constraint = str(self.scheduled_window),
                    severity   = 1.0,
                ))

        # TemporalConstraint: rolling window rate limit
        if history is not None and self.temporal and self.temporal.max_calls_per_window:
            hist_ts = []
            for i, r in enumerate(history[-100:]):
                ts = getattr(r, "timestamp", 0.0)
                if ts == 0.0:
                    ts = _now - (len(history[-100:]) - i) * 10
                hist_ts.append({"ts": ts, "value": 1})
            for msg in self.check_temporal(hist_ts, _now):
                all_violations.append(Violation(
                    dimension  = "temporal_rate",
                    field      = "call_rate",
                    message    = msg,
                    actual     = str(len(history)),
                    constraint = f"max {self.temporal.max_calls_per_window} per window",
                    severity   = 0.8,
                ))

        # AggregateConstraint: budget conservation
        if history is not None and self.aggregate and self.aggregate.param:
            agg_param   = self.aggregate.param
            current_val = params.get(agg_param, 0)
            if current_val:
                hist_agg = []
                for i, r in enumerate(history[-200:]):
                    ts = getattr(r, "timestamp", 0.0)
                    # Records with ts=0 have no real timestamp; assign relative time
                    if ts == 0.0:
                        ts = _now - (len(history[-200:]) - i) * 10
                    hist_agg.append({
                        "ts":    ts,
                        "value": getattr(r, "params", {}).get(agg_param, 0)
                    })
                for msg in self.check_aggregate(hist_agg, _now, current_val):
                    all_violations.append(Violation(
                        dimension  = "aggregate",
                        field      = agg_param,
                        message    = msg,
                        actual     = str(current_val),
                        constraint = f"aggregate sum <= {self.aggregate.max_sum}",
                        severity   = 0.9,
                    ))

        # ContextConstraint
        if caller_context and self.context:
            for msg in self.check_context(caller_context):
                all_violations.append(Violation(
                    dimension  = "context",
                    field      = "caller",
                    message    = msg,
                    actual     = str(caller_context.get("role", "")),
                    constraint = f"required_roles={self.context.required_roles}",
                    severity   = 0.9,
                ))

        # ── Snapshot checks (domain-injected) ────────────────────────────────────
        # Domain packs register validators via register_snapshot_checker().
        # The kernel dispatches to them; it contains no domain-specific risk logic.
        _snapshot = getattr(_ext_ctx_arg, "risk_snapshot", None) if _ext_ctx_arg else None
        if _snapshot is not None:
            for _snap_fn in _SNAPSHOT_CHECKERS:
                try:
                    _snap_viols = _snap_fn(_snapshot, params or {}, contract)
                    if _snap_viols:
                        all_violations.extend(_snap_viols)
                except Exception:
                    pass
        real_viols = [v for v in all_violations if v.dimension != "phantom_variable"]
        return CheckResult(
            passed     = (len(real_viols) == 0),
            violations = all_violations,
        )


# ── Alias normalization ───────────────────────────────────────────────────────

def normalize_aliases(**kwargs) -> IntentContract:
    """
    Convert simplified alias params to an IntentContract.

    Accepts both the simplified alias names and the internal dimension names.
    Legacy K9Audit names (deny_content, allowed_paths, etc.) are also accepted.

    Examples:
        normalize_aliases(deny=[".env"], only_paths=["./projects/"])
        normalize_aliases(deny_content=[".env"], allowed_paths=["./projects/"])
    """
    # Alias → dimension name mapping
    alias_map = {
        # New simplified names
        "deny":            "deny",
        "only_paths":      "only_paths",
        "deny_commands":   "deny_commands",
        "only_domains":    "only_domains",
        "invariant":          "invariant",
        "optional_invariant": "optional_invariant",
        "postcondition":   "postcondition",
        "field_deny":      "field_deny",
        "value_range":     "value_range",
        "obligation_timing": "obligation_timing",   # v0.40.0: 义务时限
        # Legacy K9Audit names
        "deny_content":    "deny",
        "allowed_paths":   "only_paths",
        "allowed_domains": "only_domains",
    }

    resolved: Dict[str, Any] = {}
    for k, v in kwargs.items():
        dim = alias_map.get(k, k)
        if dim in DIMENSION_NAMES:
            # Merge lists if dimension appears under multiple aliases
            if isinstance(v, list) and isinstance(resolved.get(dim), list):
                resolved[dim] = list(dict.fromkeys(resolved[dim] + v))
            else:
                resolved[dim] = v

    # Handle command.blocklist dict format (K9Audit legacy)
    if "command" in kwargs:
        cmd = kwargs["command"]
        if isinstance(cmd, dict) and "blocklist" in cmd:
            existing = resolved.get("deny_commands", [])
            resolved["deny_commands"] = list(dict.fromkeys(
                existing + cmd["blocklist"]))

    return IntentContract.from_dict(resolved)


# ── v0.6.0: Multi-agent delegation propagation semantics ──────────────────────
#
# Y* is not just a human-machine translation layer; it is also the constraint
# propagation layer in multi-agent collaboration.
# Core insight: multi-agent collaboration is not a message-passing problem —
# it is a constraint propagation problem.
#   When A delegates to B, what is transmitted is not just "a task" but
#   "intent with boundaries".
#   Is B authorised to sub-delegate part of it to C?
#   When C executes, is it still bound by the original constraints?
#
# Implementation (existing code already provides the foundation):
#   - IntentContract.merge()   already implements the "can only tighten" inheritance semantics
#   - ConstitutionalContract   already implements the global floor across all functions
#   - Added: delegate()        semantic alias for merge(), explicitly expressing inter-agent delegation
#   - Added: DelegationContract delegation bundle: packages intent + permissions + constraints for transmission
#   - Added: DelegationChain   delegation chain: records the full authorisation propagation path


def _make_delegate_method():
    """
    Generate the delegate() method for IntentContract.

    delegate() is a semantic alias for merge(), used for constraint propagation
    in multi-agent scenarios.

    Difference:
      merge(constitutional)  — inherits from the constitutional layer; global propagation within one system
      delegate(grantor)      — inherits from the granting agent; propagation across multiple agents

    Both use the identical inheritance algorithm (can only tighten, never loosen),
    but delegate() takes another IntentContract (the grantor's contract) as its argument,
    which more clearly expresses "B inherits constraints from A; B can only be a subset of A".
    """
    pass  # 方法直接定义在下方


# Dynamically attach the delegate() method to IntentContract at runtime
def _intent_contract_delegate(
    self,
    grantor_contract: "IntentContract",
    max_delegation_depth: int = 0,  # 还允许再往下传几层（0=不可再转授权）
) -> "IntentContract":
    """
    Delegation inheritance: derive the delegatee's contract from the grantor's contract.

    This is the semantic alias for merge() in multi-agent scenarios.

    Rules (identical to merge()):
      - The delegatee's constraints can only be stricter than the grantor's, never looser
      - The grantor's deny list is unconditionally propagated to the delegatee
      - Whitelists (only_paths / only_domains) take the intersection (smaller set)
      - Numeric bounds (value_range): max(min), min(max)

    Args:
        grantor_contract: the grantor's IntentContract (upper bound for the delegatee)
        max_delegation_depth: how many further delegation hops are permitted
                              (stored in the returned contract's metadata)

    Returns:
        IntentContract — the delegatee's contract (strict intersection of grantor and self)

    Example:
        # Agent A has a broad contract
        a_contract = IntentContract(
            value_range={"amount": {"max": 10000}},
            deny=["production"],
        )

        # Agent B wants to delegate to Agent C with a tighter amount limit
        b_contract = IntentContract(
            value_range={"amount": {"max": 500}},  # B is stricter than A
        )

        # C inherits from B (which already inherited from A);
        # C's contract is the stricter intersection of both
        c_contract = b_contract.delegate(a_contract)
        # c_contract.value_range["amount"]["max"] == 500  (smaller value wins)
        # c_contract.deny == ["production"]               (propagated from A)
    """
    # Wrap grantor_contract as a ConstitutionalContract to reuse the merge() algorithm.
    # Semantically equivalent: the grantor's contract is the delegatee's "constitution".
    from dataclasses import fields as _fields
    grantor_as_constitutional = ConstitutionalContract(
        deny               = list(grantor_contract.deny),
        only_paths         = list(grantor_contract.only_paths),
        deny_commands      = list(grantor_contract.deny_commands),
        only_domains       = list(grantor_contract.only_domains),
        invariant          = list(grantor_contract.invariant),
        optional_invariant = list(grantor_contract.optional_invariant),
        postcondition      = list(grantor_contract.postcondition),
        field_deny         = dict(grantor_contract.field_deny),
        value_range        = dict(grantor_contract.value_range),
        name               = f"delegated_from:{grantor_contract.name or 'grantor'}",
    )
    result = self.merge(grantor_as_constitutional)
    result.name = (
        f"{self.name or 'delegatee'}"
        f"←{grantor_contract.name or 'grantor'}"
    )
    return result


# 运行时挂载到 IntentContract 类
IntentContract.delegate = _intent_contract_delegate


# ── DelegationContract ────────────────────────────────────────────────────────

@dataclass
class DelegationContract:
    """
    Delegation bundle: packages intent, permissions, and constraints for transmission between agents.

    This is the core transmission unit for Y* in multi-agent scenarios.
    One delegation = who (principal) authorises whom (actor) to do what under which constraints (contract).

    Fields:
        principal:          identifier of the granting agent (who is delegating)
        actor:              identifier of the delegatee agent (who is being delegated to)
        contract:           the IntentContract the delegatee must honour
        action_scope:       list of actions the delegatee may perform (empty = unrestricted)
        delegation_depth:   how many further re-delegation hops are permitted (0 = none)
        allow_redelegate:   whether re-delegation is permitted (requires delegation_depth > 0)
        prerequisites:      preconditions (Python expressions; all must hold for the grant to be active)
        liability_scope:    liability attribution: shared / delegated / non-transferable
        valid_until:        authorisation expiry (Unix timestamp; None = permanent)
        grant_id:           unique authorisation identifier (for audit trail)
        nonce:              cryptographic nonce (UUID4) — prevents replay attacks;
                            must be unique per grant and verified before use
        hash:               SHA-256 hash of the DelegationContract (tamper-evident)
        constitution_source_ref: file path to the actor's constitution (for provider routing)

    Design principles:
        1. Constraints can only shrink: the actor's contract is a strict subset of the principal's
        2. Propagation is bounded: delegation_depth limits the re-delegation depth
        3. Auditability: hash anchoring, grant_id tracking, principal chain is fully reconstructible
        4. Anti-replay: each grant carries a unique nonce; callers use NonceLedger to reject duplicates
    """
    principal:        str                        # granting agent
    actor:            str                        # delegatee agent
    contract:         IntentContract             # constraint bundle
    action_scope:     List[str]                  = field(default_factory=list)
    delegation_depth: int                        = 0
    allow_redelegate: bool                       = False
    prerequisites:    List[str]                  = field(default_factory=list)
    liability_scope:  str                        = "delegated"   # shared / delegated / non-transferable
    valid_until:      Optional[float]            = None
    grant_id:         str                        = ""
    nonce:            str                        = ""   # UUID4 anti-replay nonce
    hash:             str                        = ""
    content_hash:     str                        = ""
    constitution_source_ref: str                 = ""   # path to actor's constitution (for provider routing)
    children:         List['DelegationContract'] = field(default_factory=list)  # child delegations (tree structure)

    def __post_init__(self):
        import uuid
        if not self.grant_id:
            self.grant_id = str(uuid.uuid4())[:8]
        if not self.nonce:
            self.nonce = str(uuid.uuid4())
        if not self.hash:
            self.hash = self._compute_hash()
        if not self.content_hash:
            self.content_hash = self._compute_content_hash()

    def _compute_content_hash(self) -> str:
        """
        Compute a hash of the authorisation *content* — excluding the nonce.

        Two grants with identical principal, actor, contract, action_scope,
        delegation_depth, prerequisites, liability_scope, valid_until, and
        grant_id will have the same content_hash regardless of when they were
        issued (i.e. regardless of their nonce).

        Use cases:
          - "Are these two grants semantically equivalent?"
          - Deduplication in CIEU records
          - Caching / memoisation of constraint checks
          - Comparing grants across re-issuance

        See also: ``hash`` (instance hash, nonce-bound, used for tamper-detection
        and NonceLedger anti-replay).
        """
        d = {
            "principal":        self.principal,
            "actor":            self.actor,
            "contract":         self.contract.to_dict(),
            "action_scope":     sorted(self.action_scope),
            "delegation_depth": self.delegation_depth,
            "prerequisites":    self.prerequisites,
            "liability_scope":  self.liability_scope,
            "valid_until":      self.valid_until,
            "grant_id":         self.grant_id,
            # nonce intentionally excluded
        }
        canonical = json.dumps(d, sort_keys=True, ensure_ascii=True)
        return "content:" + hashlib.sha256(canonical.encode()).hexdigest()

    def _compute_hash(self) -> str:
        """
        Compute the instance hash — includes the nonce.

        This hash uniquely identifies *this specific issuance* of the grant.
        Any two grants with different nonces will have different instance hashes,
        even if their content is identical.

        Use cases:
          - Tamper detection: ``verify_hash()`` checks that the stored hash
            still matches the current fields (including nonce).
          - NonceLedger binding: the nonce is part of the hash, so swapping
            the nonce invalidates the hash.

        See also: ``content_hash`` (content-only, nonce-excluded, stable across
        re-issuance of equivalent grants).
        """
        d = {
            "principal":        self.principal,
            "actor":            self.actor,
            "contract":         self.contract.to_dict(),
            "action_scope":     sorted(self.action_scope),
            "delegation_depth": self.delegation_depth,
            "prerequisites":    self.prerequisites,
            "liability_scope":  self.liability_scope,
            "valid_until":      self.valid_until,
            "grant_id":         self.grant_id,
            "nonce":            self.nonce,
        }
        canonical = json.dumps(d, sort_keys=True, ensure_ascii=True)
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def verify_hash(self) -> bool:
        """Return True if the stored instance hash matches a fresh computation (tamper-detection)."""
        return self.hash == self._compute_hash()

    def is_semantically_equivalent(self, other: "DelegationContract") -> bool:
        """
        Return True if this grant carries the same authorisation as ``other``.

        Two grants are semantically equivalent if they have the same content_hash
        — i.e. same principal, actor, contract, scope, depth, prerequisites,
        liability_scope, valid_until, and grant_id — regardless of nonce or
        issue time.
        """
        return self.content_hash == other.content_hash

    def to_dict(self) -> dict:
        """Serialise to a language-agnostic wire format."""
        d: dict = {
            "principal":    self.principal,
            "actor":        self.actor,
            "contract":     self.contract.to_dict(),
            "grant_id":     self.grant_id,
            "nonce":        self.nonce,
            "hash":         self.hash,
            "content_hash": self.content_hash,
        }
        if self.action_scope:     d["action_scope"]     = list(self.action_scope)
        if self.prerequisites:    d["prerequisites"]    = list(self.prerequisites)
        if self.allow_redelegate: d["allow_redelegate"] = self.allow_redelegate
        if self.delegation_depth: d["delegation_depth"] = self.delegation_depth
        if self.valid_until:      d["valid_until"]      = self.valid_until
        if self.liability_scope:  d["liability_scope"]  = self.liability_scope
        if self.children:         d["children"]         = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DelegationContract":
        """Deserialise from wire format."""
        raw_vu = d.get("valid_until", None)
        valid_until = float(raw_vu) if raw_vu is not None else None
        children_data = d.get("children", [])
        children = [cls.from_dict(child) for child in children_data]
        return cls(
            principal        = d["principal"],
            actor            = d["actor"],
            contract         = IntentContract.from_dict(d["contract"]),
            action_scope     = d.get("action_scope", []),
            prerequisites    = d.get("prerequisites", []),
            allow_redelegate = d.get("allow_redelegate", False),
            delegation_depth = d.get("delegation_depth", 0),
            valid_until      = valid_until,
            liability_scope  = d.get("liability_scope", ""),
            grant_id         = d.get("grant_id", ""),
            nonce            = d.get("nonce", ""),
            hash             = d.get("hash", ""),
            content_hash     = d.get("content_hash", ""),
            children         = children,
        )

    def is_valid(self, current_time: Optional[float] = None) -> bool:
        """Check whether the delegation is still within its validity period."""
        if self.valid_until is None:
            return True
        import time
        t = current_time if current_time is not None else time.time()
        return t <= self.valid_until

    def can_redelegate(self) -> bool:
        """Return True if further re-delegation is permitted."""
        return self.allow_redelegate and self.delegation_depth > 0

    def redelegate(
        self,
        new_actor:    str,
        sub_contract: Optional[IntentContract] = None,
    ) -> "DelegationContract":
        """
        Generate a downstream delegation bundle.

        Rules:
          - May only be called when can_redelegate() is True
          - The downstream contract is a strict subset of the current one (enforced by delegate())
          - delegation_depth is decremented by 1
          - principal becomes the current actor (the authorisation chain propagates downward)

        Args:
            new_actor:    identifier of the downstream delegatee agent
            sub_contract: optional further-restricted contract (must be stricter than the current one);
                          if None, the current contract is inherited unchanged

        Returns:
            New DelegationContract (delegation_depth - 1)
        """
        if not self.can_redelegate():
            raise ValueError(
                f"DelegationContract(grant_id={self.grant_id}) "
                f"does not allow redelegation "
                f"(allow_redelegate={self.allow_redelegate}, "
                f"delegation_depth={self.delegation_depth})"
            )

        # Downstream contract is a strict subset of the current one
        if sub_contract is not None:
            inherited = sub_contract.delegate(self.contract)
        else:
            inherited = IntentContract.from_dict(
                self.contract.to_dict(),
                name=f"redelegated_to:{new_actor}",
            )

        return DelegationContract(
            principal        = self.actor,   # current actor becomes the new principal
            actor            = new_actor,
            contract         = inherited,
            action_scope     = list(self.action_scope),  # inherit action scope
            delegation_depth = self.delegation_depth - 1,
            allow_redelegate = self.delegation_depth - 1 > 0,
            prerequisites    = list(self.prerequisites),
            liability_scope  = self.liability_scope,
            valid_until      = self.valid_until,
        )

    def check_prerequisites(
        self,
        context: Dict[str, Any],
        safe_eval_fn: Optional[Any] = None,
    ) -> List[str]:
        """
        Check whether all preconditions are satisfied.

        Args:
            context:      current context dict (e.g. {"kyc_verified": True, "env": "staging"})
            safe_eval_fn: optional evaluator; defaults to ystar.engine._safe_eval

        Returns:
            List of unsatisfied preconditions (empty list means all passed)
        """
        if not self.prerequisites:
            return []

        if safe_eval_fn is None:
            from ystar.kernel.engine import _safe_eval
            safe_eval_fn = _safe_eval

        failed = []
        for expr in self.prerequisites:
            result, err = safe_eval_fn(expr, context)
            if err:
                failed.append(f"prerequisite eval error: '{expr}' — {err}")
            elif not result:
                failed.append(f"prerequisite not met: '{expr}'")
        return failed

    def __str__(self) -> str:
        depth_info = (f", redelegate_depth={self.delegation_depth}"
                      if self.allow_redelegate else ", no_redelegate")
        return (f"DelegationContract("
                f"{self.principal}→{self.actor}, "
                f"grant={self.grant_id}"
                f"{depth_info})")


# ── DelegationChain ───────────────────────────────────────────────────────────

@dataclass
class DelegationChain:
    """
    Delegation chain: records the full authorisation propagation path.

    Supports both linear chain (legacy) and tree structure (v0.48+).

    Tree structure allows CEO to delegate to multiple direct reports simultaneously:
        CEO -> CTO -> eng-kernel
            -> CMO
            -> CSO

    Use cases:
        - Answer "who originally authorised this action?"
        - Verify that each step's contract is a strict subset of the previous step's
        - Check that the chain length does not exceed the permitted depth
        - Provide the K9 audit layer with complete authorisation proof

    Example (legacy linear):
        chain = DelegationChain()
        chain.append(org_to_a)    # org → Agent A
        chain.append(a_to_b)      # Agent A → Agent B
        chain.append(b_to_c)      # Agent B → Agent C

        errors = chain.validate()
        print(chain.explain())    # print the full authorisation chain

    Example (tree structure):
        root = DelegationContract(principal="system", actor="CEO", ...)
        cto = DelegationContract(principal="CEO", actor="CTO", ...)
        root.children.append(cto)
        chain = DelegationChain(root=root)

        path = chain.find_path("CTO")
        valid, violations = chain.validate_tree()
    """
    links: List[DelegationContract] = field(default_factory=list)  # legacy linear chain
    root: Optional[DelegationContract] = None  # tree structure root (v0.48+)
    all_contracts: Dict[str, DelegationContract] = field(default_factory=dict)  # agent_id -> contract index

    def __post_init__(self):
        """Build agent_id -> contract index if tree structure is used."""
        if self.root is not None:
            self._build_index(self.root)

    def _build_index(self, node: DelegationContract):
        """Recursively build agent_id -> contract index."""
        self.all_contracts[node.actor] = node
        for child in node.children:
            self._build_index(child)

    def find_path(self, agent_id: str) -> List[DelegationContract]:
        """
        Find authorization path from root to specified agent (tree mode only).

        Returns path of all DelegationContracts from root to target (inclusive).
        Returns empty list if agent not found or chain is in linear mode.
        """
        if self.root is None:
            return []
        path: List[DelegationContract] = []
        if self._find_path_recursive(self.root, agent_id, path):
            return path
        return []

    def _find_path_recursive(self, node: DelegationContract, target: str, path: List[DelegationContract]) -> bool:
        """Recursive path finding helper."""
        path.append(node)

        if node.actor == target:
            return True

        for child in node.children:
            if self._find_path_recursive(child, target, path):
                return True

        path.pop()
        return False

    def validate_tree(self) -> tuple:
        """
        Validate tree structure (tree mode only).

        Validation rules:
        1. Child contract must be subset of parent contract (monotonicity)
        2. Child delegated_tools must be within parent delegated_tools
        3. No cycles (agent_id must be unique)

        Returns:
            (is_valid: bool, violations: List[str])
        """
        if self.root is None:
            return (True, [])

        violations: List[str] = []
        visited: set = set()

        self._validate_node(self.root, None, visited, violations)

        return (len(violations) == 0, violations)

    def _validate_node(self, node: DelegationContract, parent: Optional[DelegationContract],
                      visited: set, violations: List[str]):
        """Recursively validate tree node."""
        # Check for cycles
        if node.actor in visited:
            violations.append(f"Cycle detected: {node.actor} appears multiple times")
            return
        visited.add(node.actor)

        # Check monotonicity with parent
        if parent is not None:
            # Tool constraints
            parent_tools = set(parent.action_scope) if parent.action_scope else set()
            node_tools = set(node.action_scope) if node.action_scope else set()

            # If parent has restrictions and child has tools, check subset
            if parent.action_scope and node.action_scope:
                if not node_tools.issubset(parent_tools):
                    violations.append(
                        f"{node.actor}'s action_scope exceeds {parent.actor}'s authorization"
                    )
            elif parent.action_scope and not node.action_scope:
                # Parent restricts but child has no scope = child removes restriction
                violations.append(
                    f"{node.actor} removes action_scope restriction from {parent.actor}"
                )

            # Contract constraints (use is_subset_of)
            ok, vlist = node.contract.is_subset_of(parent.contract)
            if not ok:
                violations.append(
                    f"{node.actor}'s contract exceeds {parent.actor}'s constraints: {'; '.join(vlist)}"
                )

        # Recursively validate children
        for child in node.children:
            self._validate_node(child, node, visited, violations)

    def append(self, dc: DelegationContract) -> "DelegationChain":
        """Append a delegation node; returns self for method chaining."""
        self.links.append(dc)
        return self

    @property
    def depth(self) -> int:
        """Depth of the chain (number of delegation hops)."""
        return len(self.links)

    @property
    def origin(self) -> Optional[str]:
        """The original grantor (principal of the first link)."""
        return self.links[0].principal if self.links else None

    @property
    def terminal_actor(self) -> Optional[str]:
        """The terminal actor (actor of the last link)."""
        return self.links[-1].actor if self.links else None

    @property
    def terminal_contract(self) -> Optional[IntentContract]:
        """The terminal actor's contract (the strictest constraints)."""
        return self.links[-1].contract if self.links else None

    def validate(self, current_time: Optional[float] = None) -> List[str]:
        """
        Validate the entire delegation chain.

        Checks:
          1. Continuity: each link's actor is the next link's principal
          2. Validity: every delegation is within its validity period
          3. Re-delegation authority: each link's delegation_depth supports the remaining chain length
          4. Contract subset: each link's contract is a strict subset of the previous link's

        Returns:
            List of error descriptions; empty list means the chain is valid.
        """
        errors = []

        for i, link in enumerate(self.links):
            # Validity check
            if not link.is_valid(current_time):
                errors.append(
                    f"Link[{i}] {link.principal}→{link.actor} "
                    f"(grant={link.grant_id}): expired"
                )

            # Continuity check
            if i > 0:
                prev = self.links[i - 1]
                if prev.actor != link.principal:
                    errors.append(
                        f"Chain broken at link[{i}]: "
                        f"prev.actor={prev.actor!r} != "
                        f"link.principal={link.principal!r}"
                    )
                # Re-delegation authority check
                if not prev.can_redelegate():
                    errors.append(
                        f"Link[{i-1}] {prev.principal}→{prev.actor} "
                        f"(grant={prev.grant_id}) "
                        f"does not allow redelegation, "
                        f"but chain continues"
                    )

                # Contract monotonicity: child contract must be ≤ parent contract
                ok, violations = link.contract.is_subset_of(prev.contract)
                if not ok:
                    for v in violations:
                        errors.append(
                            f"Link[{i}] {link.principal}→{link.actor} "
                            f"(grant={link.grant_id}) violates monotonicity: {v}"
                        )

                # action_scope monotonicity: child scope must be ⊆ parent scope
                if prev.action_scope and link.action_scope:
                    extra = set(link.action_scope) - set(prev.action_scope)
                    if extra:
                        errors.append(
                            f"Link[{i}] {link.principal}→{link.actor} "
                            f"(grant={link.grant_id}) expands action_scope "
                            f"beyond parent: {sorted(extra)}"
                        )
                elif not prev.action_scope and link.action_scope:
                    pass  # parent unrestricted → child can restrict, always ok
                # if parent restricts but child has no scope = inherits all = ok only if same set
                elif prev.action_scope and not link.action_scope:
                    errors.append(
                        f"Link[{i}] {link.principal}→{link.actor} "
                        f"(grant={link.grant_id}) removes action_scope restriction "
                        f"(parent had {prev.action_scope})"
                    )

        return errors

    def is_valid(self, current_time: Optional[float] = None) -> bool:
        """Return True if the entire chain is valid (no validation errors)."""
        return len(self.validate(current_time)) == 0

    def explain(self) -> str:
        """Return the full delegation chain in human-readable format."""
        if not self.links:
            return "DelegationChain: (empty)"

        lines = [f"DelegationChain (depth={self.depth}):"]
        for i, link in enumerate(self.links):
            prefix = "  " + "  " * i
            arrow = "→"
            scope = (f" [scope={link.action_scope}]"
                     if link.action_scope else "")
            redelegate = (f" [can_redelegate×{link.delegation_depth}]"
                          if link.can_redelegate() else " [no_redelegate]")
            expiry = (f" [expires={link.valid_until:.0f}]"
                      if link.valid_until else "")
            lines.append(
                f"{prefix}{link.principal} {arrow} {link.actor}"
                f"  (grant={link.grant_id})"
                f"{scope}{redelegate}{expiry}"
            )
            # Contract summary
            c = link.contract
            if c.deny:
                lines.append(f"{prefix}  deny={c.deny}")
            if c.value_range:
                lines.append(f"{prefix}  value_range={c.value_range}")
            if c.invariant:
                lines.append(f"{prefix}  invariant={c.invariant}")

        terminal = self.links[-1]
        lines.append(
            f"\nTerminal actor: {terminal.actor!r}"
            f"  (origin: {self.origin!r})"
        )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """序列化到 JSON 兼容的 dict（用于 session.json 持久化）。"""
        d = {}
        # Support both legacy linear and new tree structure
        if self.links:
            d["links"] = [lk.to_dict() for lk in self.links]
        if self.root is not None:
            d["root"] = self.root.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DelegationChain":
        """从 dict 反序列化（从 session.json 加载委托链）。"""
        import logging
        _log = logging.getLogger("ystar.dimensions")
        chain = cls()

        # Load legacy linear chain if present
        for i, lk_dict in enumerate(d.get("links", [])):
            try:
                chain.links.append(DelegationContract.from_dict(lk_dict))
            except Exception as exc:
                _log.warning(
                    "DelegationChain.from_dict: skipped link[%d]: %s", i, exc
                )

        # Load tree structure if present
        root_data = d.get("root")
        if root_data:
            try:
                chain.root = DelegationContract.from_dict(root_data)
                chain._build_index(chain.root)
            except Exception as exc:
                _log.warning("DelegationChain.from_dict: failed to load root: %s", exc)

        return chain




# ── NonceLedger — anti-replay protection for DelegationContract ───────────────

class NonceLedger:
    """
    In-process nonce registry that prevents DelegationContract replay attacks.

    Each DelegationContract carries a unique nonce (UUID4).  Before honouring a
    grant, callers should call ``ledger.consume(dc)`` which:

    1. Verifies the contract hash has not been tampered with.
    2. Checks the nonce has not already been consumed.
    3. Marks the nonce as used (preventing future replays).

    Usage::

        ledger = NonceLedger()
        ok, reason = ledger.consume(dc)
        if not ok:
            raise ValueError(f"Delegation rejected: {reason}")

    Notes:
        - NonceLedger is in-process only. For distributed systems, subclass it
          and override ``has_nonce`` / ``record_nonce`` to use a shared store.
        - Expired grants are rejected before nonce consumption so that replayed
          expired grants are caught early.
    """

    def __init__(self):
        self._used: set = set()
        self._lock = None

    def _get_lock(self):
        if self._lock is None:
            import threading
            self._lock = threading.Lock()
        return self._lock

    def has_nonce(self, nonce: str) -> bool:
        """Return True if this nonce has already been consumed."""
        with self._get_lock():
            return nonce in self._used

    def record_nonce(self, nonce: str) -> None:
        """Mark a nonce as consumed. Override in subclasses for distributed stores."""
        with self._get_lock():
            self._used.add(nonce)

    def _consume_nonce_check(self, grant_id: str, nonce: str) -> "tuple[bool, str]":
        """
        Internal: check and consume a nonce only (no hash / expiry checks).
        Used for testing and for distributed backends that perform those checks externally.
        """
        if not nonce:
            return False, (
                f"Grant {grant_id!r}: missing nonce — cannot verify anti-replay"
            )
        if self.has_nonce(nonce):
            return False, (
                f"Grant {grant_id!r}: nonce {nonce!r} has already been consumed "
                f"(replay attack detected)"
            )
        self.record_nonce(nonce)
        return True, ""

    def consume(
        self,
        dc: "DelegationContract",
        current_time: Optional[float] = None,
    ) -> "tuple[bool, str]":
        """
        Validate and consume a DelegationContract grant.

        Checks (in order):
          1. Hash integrity  — detects tampering
          2. Validity period — rejects expired grants
          3. Nonce freshness — rejects replays

        Returns:
            (True, "")           if the grant is accepted and the nonce is consumed
            (False, reason_str)  if the grant is rejected (nonce is NOT consumed)
        """
        import time as _time

        # 1. Hash integrity
        if not dc.verify_hash():
            return False, (
                f"Grant {dc.grant_id!r}: hash mismatch — contract may have been tampered with"
            )

        # 2. Validity period
        if dc.valid_until is not None:
            t = current_time if current_time is not None else _time.time()
            if t > dc.valid_until:
                return False, (
                    f"Grant {dc.grant_id!r}: expired at {dc.valid_until:.0f} "
                    f"(current={t:.0f})"
                )

        # 3. Nonce freshness
        nonce = dc.nonce
        if not nonce:
            return False, (
                f"Grant {dc.grant_id!r}: missing nonce — cannot verify anti-replay"
            )
        if self.has_nonce(nonce):
            return False, (
                f"Grant {dc.grant_id!r}: nonce {nonce!r} has already been consumed "
                f"(replay attack detected)"
            )

        # All checks passed — consume the nonce
        self.record_nonce(nonce)
        return True, ""

    def size(self) -> int:
        """Number of consumed nonces in the ledger."""
        with self._get_lock():
            return len(self._used)

    def reset(self) -> None:
        """Clear all consumed nonces (use only in tests)."""
        with self._get_lock():
            self._used.clear()

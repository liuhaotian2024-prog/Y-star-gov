# ystar/template.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
from_template(): structured fill-in-the-blanks contract builder.

Converts a plain-English key/value dict into an (IntentContract, HigherOrderContract)
pair. No Python knowledge required — users fill values, not code.

─────────────────────────────────────────────────────────────────
LAYER 1 — Basic (covers 95% of governance needs)
─────────────────────────────────────────────────────────────────
  can_write_to          list[str]   paths allowed to write
  can_call              list[str]   domains/URLs allowed to fetch
  cannot_touch          list[str]   strings blocked in any parameter
  cannot_run            list[str]   command prefixes blocked
  cannot_access         list[str]   alias for cannot_touch
  blocked               list[str]   alias for cannot_touch
  allowed_paths         list[str]   alias for can_write_to
  allowed_domains       list[str]   alias for can_call
  block_commands        list[str]   alias for cannot_run
  field_NAME_deny       list[str]   block specific values for named param
                                    e.g. field_env_deny=["prod","live"]
  XYZ_limit             number      maximum value for parameter XYZ
  XYZ_max               number      alias for XYZ_limit
  XYZ_min               number      minimum value for parameter XYZ
  XYZ_range             dict        {"min": N, "max": N} for parameter XYZ

─────────────────────────────────────────────────────────────────
LAYER 2 — Advanced (HigherOrderContract dimensions)
─────────────────────────────────────────────────────────────────
  Temporal / rate:
    max_calls_per_minute  int       rate limit: max calls per minute
    max_calls_per_hour    int       rate limit: max calls per hour
    max_calls_per_day     int       rate limit: max calls per day
    min_interval_seconds  float     minimum seconds between calls
    requires_before       list[str] actions that must happen before this

  Aggregate / cumulative:
    aggregate_param       str       parameter name to aggregate (e.g. "amount")
    aggregate_daily_max   float     max cumulative value per day
    aggregate_hourly_max  float     max cumulative value per hour
    aggregate_window_max  float     max cumulative value (use with aggregate_window_seconds)
    aggregate_window_seconds float  window for aggregate_window_max

  Context / roles / environment:
    required_roles        list[str] roles required to perform this action
    required_env          list[str] environments where this is allowed
    deny_env              list[str] environments where this is blocked
    required_flags        list[str] feature flags that must be set

  Scheduled window:
    allowed_hours         str       "HH:MM-HH:MM" e.g. "09:30-16:00"
    allowed_timezone      str       timezone for allowed_hours (default UTC)

  Resource:
    max_execution_seconds float     max time allowed for execution
    max_memory_mb         float     max memory in MB
    max_output_bytes      int       max output size in bytes

─────────────────────────────────────────────────────────────────
LAYER 3 — Expert (direct IntentContract fields, optional)
─────────────────────────────────────────────────────────────────
  invariant             list[str]   Python expressions on inputs (e.g. "amount > 0")
  optional_invariant    list[str]   same, only checked when parameter is present
  postcondition         list[str]   Python expressions on return value

─────────────────────────────────────────────────────────────────
Returns:
  TemplateResult with .contract (IntentContract) and .higher_order (HigherOrderContract|None)
─────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from .kernel.dimensions import (
    IntentContract,
    HigherOrderContract,
    TemporalConstraint,
    AggregateConstraint,
    ContextConstraint,
    ScheduledWindow,
    ResourceConstraint,
)


@dataclass
class TemplateResult:
    """
    Result of from_template().

    Attributes:
        contract:     IntentContract ready for use with Policy / check()
        higher_order: HigherOrderContract if any Layer-2 keys were set, else None
    """
    contract:     IntentContract
    higher_order: Optional[HigherOrderContract]

    def __iter__(self):
        """Allow unpacking: contract, ho = from_template(...)"""
        yield self.contract
        yield self.higher_order


# ── Layer-1 key → canonical IntentContract dimension ──────────────────────────
_KEY_MAP: Dict[str, str] = {
    "can_write_to":    "only_paths",
    "allowed_paths":   "only_paths",
    "only_paths":      "only_paths",
    "can_call":        "only_domains",
    "allowed_domains": "only_domains",
    "only_domains":    "only_domains",
    "cannot_touch":    "deny",
    "cannot_access":   "deny",
    "blocked":         "deny",
    "deny":            "deny",
    "cannot_run":      "deny_commands",
    "block_commands":  "deny_commands",
    "no_commands":     "deny_commands",
    "deny_commands":   "deny_commands",
    # Layer-3 expert pass-through
    "invariant":          "invariant",
    "optional_invariant": "optional_invariant",
    "postcondition":      "postcondition",
}

# ── Layer-2 rate/temporal keys ─────────────────────────────────────────────────
_RATE_WINDOWS = {
    "max_calls_per_minute": 60,
    "max_calls_per_hour":   3600,
    "max_calls_per_day":    86400,
}


def from_template(template: Dict[str, Any]) -> TemplateResult:
    """
    Build an (IntentContract, HigherOrderContract) pair from a fill-in-the-blanks dict.

    Example (Layer 1 only — basic user)::

        result = from_template({
            "can_write_to":  ["./workspace/dev/"],
            "cannot_touch":  [".env", "production", "prod"],
            "cannot_run":    ["rm -rf", "git push --force"],
            "amount_limit":  10000,
            "amount_min":    1,
            "field_env_deny": ["production", "prod", "live"],
        })
        policy = Policy({"rd": result})   # TemplateResult is accepted directly

    Example (Layer 2 — advanced user)::

        result = from_template({
            "can_call":            ["api.hubspot.com"],
            "max_calls_per_hour":  100,
            "aggregate_param":     "amount",
            "aggregate_daily_max": 50000,
            "required_roles":      ["operator"],
            "allowed_hours":       "09:30-17:00",
        })
        contract, higher_order = result   # unpack

    Example (Layer 3 — expert)::

        result = from_template({
            "can_write_to":     ["./workspace/"],
            "invariant":        ["amount > 0", "amount <= budget"],
            "postcondition":    ["result.get('status') == 'ok'"],
        })
    """
    # ── Layer-1: IntentContract fields ────────────────────────────────────────
    deny: List[str]          = []
    deny_commands: List[str] = []
    only_paths: List[str]    = []
    only_domains: List[str]  = []
    value_range: Dict        = {}
    field_deny: Dict         = {}
    invariant: List[str]     = []
    optional_invariant: List[str] = []
    postcondition: List[str] = []

    def _extend(lst: list, value: Any) -> None:
        items = value if isinstance(value, list) else [value]
        for item in items:
            if item not in lst:
                lst.append(item)

    for key, value in template.items():
        # ── numeric suffix patterns ──────────────────────────────────────────
        if key.endswith("_limit") or key.endswith("_max"):
            suffix = "_limit" if key.endswith("_limit") else "_max"
            param = key[: -len(suffix)]
            # avoid collisions with layer-2 keys
            if param not in ("aggregate_window", "aggregate_daily", "aggregate_hourly"):
                if isinstance(value, (int, float)):
                    value_range.setdefault(param, {})["max"] = float(value)
                    continue

        if key.endswith("_min"):
            param = key[:-4]
            if isinstance(value, (int, float)):
                value_range.setdefault(param, {})["min"] = float(value)
                continue

        if key.endswith("_range") and not key.startswith("aggregate_"):
            param = key[:-6]
            if isinstance(value, dict):
                value_range[param] = {
                    k: float(v) for k, v in value.items() if k in ("min", "max")
                }
                continue

        # ── field_NAME_deny ──────────────────────────────────────────────────
        if key.startswith("field_") and key.endswith("_deny"):
            field_name = key[6:-5]
            field_deny[field_name] = value if isinstance(value, list) else [value]
            continue

        # ── canonical dimension mapping ──────────────────────────────────────
        dim = _KEY_MAP.get(key)
        if dim == "deny":            _extend(deny, value)
        elif dim == "deny_commands": _extend(deny_commands, value)
        elif dim == "only_paths":    _extend(only_paths, value)
        elif dim == "only_domains":  _extend(only_domains, value)
        elif dim == "invariant":
            _extend(invariant, value)
        elif dim == "optional_invariant":
            _extend(optional_invariant, value)
        elif dim == "postcondition":
            _extend(postcondition, value)
        # Layer-2 keys handled below — not consumed here

    contract = IntentContract(
        deny=deny,
        deny_commands=deny_commands,
        only_paths=only_paths,
        only_domains=only_domains,
        value_range=value_range,
        field_deny=field_deny,
        invariant=invariant,
        optional_invariant=optional_invariant,
        postcondition=postcondition,
    )

    # ── Layer-2: HigherOrderContract ──────────────────────────────────────────
    temporal   = _build_temporal(template)
    aggregate  = _build_aggregate(template)
    context    = _build_context(template)
    scheduled  = _build_scheduled_window(template)
    resource   = _build_resource(template)

    has_ho = any(x is not None for x in [temporal, aggregate, context, scheduled, resource])
    if not has_ho:
        higher_order = None
    else:
        higher_order = HigherOrderContract(
            temporal         = temporal  or TemporalConstraint(),
            aggregate        = aggregate or AggregateConstraint(),
            context          = context   or ContextConstraint(),
            scheduled_window = scheduled,
            resource         = resource,
        )

    return TemplateResult(contract=contract, higher_order=higher_order)


# ── Layer-2 builders ──────────────────────────────────────────────────────────

def _build_temporal(t: dict) -> Optional[TemporalConstraint]:
    max_calls = None
    window_s  = None

    for key, window in _RATE_WINDOWS.items():
        if key in t and t[key]:
            try:
                max_calls = int(t[key])
                window_s  = float(window)
            except (TypeError, ValueError):
                pass
            break

    min_interval = _float(t, "min_interval_seconds")
    requires     = _liststr(t, "requires_before")

    if max_calls is None and min_interval is None and not requires:
        return None

    return TemporalConstraint(
        max_calls_per_window = max_calls,
        window_seconds       = window_s,
        min_interval_seconds = min_interval,
        requires_before      = requires,
    )


def _build_aggregate(t: dict) -> Optional[AggregateConstraint]:
    param = t.get("aggregate_param", "")
    if not param:
        return None

    # aggregate_daily_max  → window=86400
    # aggregate_hourly_max → window=3600
    # aggregate_window_max → use aggregate_window_seconds
    max_sum = None
    window_s = None

    if "aggregate_daily_max" in t:
        max_sum  = _float(t, "aggregate_daily_max")
        window_s = 86400.0
    elif "aggregate_hourly_max" in t:
        max_sum  = _float(t, "aggregate_hourly_max")
        window_s = 3600.0
    elif "aggregate_window_max" in t:
        max_sum  = _float(t, "aggregate_window_max")
        window_s = _float(t, "aggregate_window_seconds") or 86400.0

    if max_sum is None:
        return None

    return AggregateConstraint(
        param          = str(param),
        max_sum        = max_sum,
        window_seconds = window_s,
    )


def _build_context(t: dict) -> Optional[ContextConstraint]:
    roles    = _liststr(t, "required_roles")
    req_env  = _liststr(t, "required_env")
    deny_env = _liststr(t, "deny_env")
    flags    = _liststr(t, "required_flags")

    if not any([roles, req_env, deny_env, flags]):
        return None

    return ContextConstraint(
        required_roles = roles,
        required_env   = req_env,
        deny_env       = deny_env,
        required_flags = flags,
    )


def _build_scheduled_window(t: dict) -> Optional[ScheduledWindow]:
    hours = t.get("allowed_hours", "")
    if not hours or "-" not in hours:
        return None
    parts = hours.split("-", 1)
    return ScheduledWindow(
        start_time = parts[0].strip(),
        end_time   = parts[1].strip(),
        timezone   = t.get("allowed_timezone", "UTC"),
    )


def _build_resource(t: dict) -> Optional[ResourceConstraint]:
    max_exec = _float(t, "max_execution_seconds")
    max_mem  = _float(t, "max_memory_mb")
    max_out  = t.get("max_output_bytes")
    if max_out is not None:
        try: max_out = int(max_out)
        except (TypeError, ValueError): max_out = None

    if max_exec is None and max_mem is None and max_out is None:
        return None
    return ResourceConstraint(
        max_execution_seconds = max_exec,
        max_memory_mb         = max_mem,
        max_output_bytes      = max_out,
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _float(t: dict, key: str) -> Optional[float]:
    v = t.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _liststr(t: dict, key: str) -> List[str]:
    v = t.get(key, [])
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v] if v else []

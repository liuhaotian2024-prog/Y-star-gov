"""
ystar.domains.finance._source7
================================
Source7: Finance prose NLP extractor.

Moved from kernel/prefill.py (v0.38.x architectural cleanup).
The kernel contains no domain-specific NL logic. This module
registers itself with the kernel at finance domain import time.

Usage (automatic — called from ystar/domains/finance/__init__.py):
    from ystar.domains.finance._source7 import register
    register()
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING


# ── Finance parameter vocabulary ────────────────────────────────────────────
# (was _FINANCE_PARAM_MAP in kernel/prefill.py)
_FINANCE_PARAM_MAP: List[tuple] = [
    (r"participation[\s_]rate",   "participation_rate"),
    (r"参与率|参与度",              "participation_rate"),
    (r"daily[\s_]turnover|single[\s_]day[\s_]turnover|单日换手|单日.*turnover|日.*换手", "daily_turnover"),
    (r"日[\s_]?换手|换手率",        "daily_turnover"),
    (r"\bturnover\b",              "daily_turnover"),
    (r"cash[\s_]buffer",           "cash_buffer"),
    (r"现金缓冲|现金储备",          "cash_buffer"),
    (r"tracking[\s_]error",        "tracking_error"),
    (r"跟踪误差",                   "tracking_error"),
    (r"\bVaR\b|intraday[\s_]var|intraday_var|日内.*var", "intraday_var"),
    (r"日内VaR|日内风险|VaR不",      "intraday_var"),
    (r"cash[\s_]substitution",     "cash_substitution_pct"),
    (r"现金替代",                   "cash_substitution_pct"),
    (r"creation[\s_]units",        "creation_units"),
    (r"申赎单位",                   "creation_units"),
    (r"margin[\s_]usage|margin\b", "margin_usage"),
    (r"保证金",                     "margin_usage"),
    (r"leverage|杠杆率",            "leverage"),
    (r"杠杆",                       "leverage"),
    (r"single[\s_]name[\s_]position|position[\s_]concentration|单股集中度|个股集中度", "position_concentration"),
    (r"position[\s_]size|position\b", "position_size"),
    (r"仓位|头寸",                  "position_size"),
    (r"risk[\s_]budget",           "risk_budget_used"),
    (r"风险预算",                   "risk_budget_used"),
    (r"venue[\s_]concentration",   "venue_concentration"),
    (r"settlement[\s_]risk",       "settlement_risk"),
    (r"结算风险",                   "settlement_risk"),
]

# ── Finance prohibited terms (Source7 7A) ────────────────────────────────────
_FINANCE_DENY_TERMS = {
    "dark pool routing":              "dark_pool_route",
    "dark pool":                      "dark_pool",
    "dark pools":                     "dark_pool",
    "darkpool":                       "dark_pool",
    "暗池":                            "dark_pool",
    "unfiltered sponsored":           "unfiltered_sponsored_access",
    "sponsored access":               "sponsored_access",
    "front running":                  "front_running",
    "front-running":                  "front_running",
    "抢跑":                            "front_running",
    "wash sale":                      "wash_sale",
    "wash trading":                   "wash_trading",
    "洗售":                            "wash_sale",
    "spoofing":                       "spoofing",
    "欺骗性报价":                      "spoofing",
    "layering":                       "layering",
    "insider trading":                "insider_trading",
    "内幕交易":                        "insider_trading",
    "benchmark manipulation":         "benchmark_manipulation",
    "操纵基准":                        "benchmark_manipulation",
    "quote stuffing":                 "quote_stuffing",
    "momentum ignition":              "momentum_ignition",
    "market ramping":                 "market_ramping",
    "哄抬价格":                        "market_ramping",
    "short squeeze manipulation":     "short_squeeze_manipulation",
    "market cornering":               "market_cornering",
    "操纵市场":                        "market_manipulation",
    "override compliance":            "override_compliance",
    "bypass approval":                "bypass_approval",
    "mandate breach":                 "mandate_breach",
    "authority breach":               "authority_breach",
    "self dealing":                   "self_dealing",
    "cherry picking":                 "cherry_picking",
    "利益冲突":                        "conflict_of_interest",
    "conflict of interest":           "conflict_of_interest",
    "rebalance without approval":     "rebalance_without_approval",
    "increase position without":      "increase_position_without_approval",
    "increase position":              "increase_position",
    "override risk gate":             "override_risk_gate",
    "bypass risk controls":           "bypass_risk",
    "bypass risk":                    "bypass_risk_gate",
    "override stop loss":             "override_stop_loss",
    "override kill switch":           "override_kill_switch",
    "override basket constraint":     "override_basket_constraint",
    "override basket":                "override_basket_constraint",
    "自行平仓":                        "unauthorized_close",
    "unauthorized close":             "unauthorized_close",
    "force execute":                  "force_execute",
    "bypass compliance":              "bypass_compliance",
    "copy delegation":                "copy_delegation",
    "self authorize":                 "self_authorize",
    "grant admin":                    "grant_admin",
}

# ── Finance precondition vocabulary ──────────────────────────────────────────
_FINANCE_PREREQ_MAP = [
    (r"risk[\s_]officer[\s_]approv",  "risk_officer_approved"),
    (r"risk[\s_]officer",             "risk_officer_approved"),
    (r"风险官.*批准|risk officer.*批准", "risk_officer_approved"),
    (r"risk[\s_]gate[\s_]passed",      "risk_gate_passed"),
    (r"risk[\s_]gate",                 "risk_gate_passed"),
    (r"风控门|风控.*通过",              "risk_gate_passed"),
    (r"ap[\s_]authorized",             "ap_authorized"),
    (r"authorized[\s_]participant",    "ap_authorized"),
    (r"venue[\s_]approved",            "venue_approved"),
    (r"position[\s_]approved",         "position_approved"),
    (r"signal[\s_]processed",          "signal_processed"),
    (r"risk[\s_]gate[\s_](?:not|未).*(?:发单|order)",  None),
]

# ── Bound vocabulary (finance-specific numeric patterns) ─────────────────────
_PROHIBIT_EN = [
    "do not", "must not", "no dark", "no wash", "no front", "no ", "never use", "not use",
    "never ", "must never", "prohibited", "forbidden", "not allowed", "not permitted",
    "avoid using",
    "禁止", "不得", "不要", "不允许", "不能",
]
_UPPER_BOUND_CN = ["不得超过", "不超过", "不能超过", "上限", "不大于", "不高于", "最大.*%", "最多"]
_UPPER_BOUND_EN = [
    "must not exceed", "not to exceed", "not exceed", "≤", "<=", "not more than",
    " cap ", " cap:", " limit ", " limit:", " budget ", " threshold ",
    "no more than", "maximum of", "max of", r"\bmax\b", "at most", "capped at",
    "not go above", "not above", "not higher than", "must not go above",
]
_LOWER_BOUND_CN = ["不得低于", "不低于", "不能低于", "下限", "不小于", "保持在", "不少于", "至少"]
_LOWER_BOUND_EN_EXTRA = ["≥", ">="]
_LOWER_BOUND_EN = [
    "must remain above", "must stay above", "must be above",
    "must not fall below", "must not go below",
    "minimum of", r"\bmin\b", "at least", "not below",
    "no less than", "remain above", "stay above", "not drop below",
]
_PREREQ_TRIGGER_EN = [
    "prerequisite", "requires.*true", "must be true",
    "must pass", "must be passed", "before sending",
    "before placing", "requires approval",
    "only.*approved", "not.*without approval",
]
_ABS_QTY_PATTERNS = [
    r"(\d[\d,，]*(?:\.\d+)?)\s*(?:万)(?:股|手|张|份|lots?|shares?|contracts?)?",
    r"(\d[\d,，]*(?:\.\d+)?)\s*(?:shares?|lots?|contracts?|units?)\b",
    r"(\d+(?:\.\d+)?)[kK]\s*(?:shares?|lots?|contracts?|units?)\b",
    r"(\d+(?:\.\d+)?)[mM]\s*(?:shares?|lots?|contracts?|units?)\b",
    # 英文上限句式：order size / quantity must not exceed N
    r"(?:order\s*size|order\s*qty|order\s*quantity|position\s*size|trade\s*size)"
    r"\s+(?:must\s+not|should\s+not|cannot|shall\s+not)\s+exceed\s+(\d[\d,]*)",
    # "not exceed N" / "no more than N" (standalone number, no unit suffix)
    r"(?:not\s+exceed|no\s+more\s+than|not\s+more\s+than|limited\s+to|limit\s+of)"
    r"\s+(\d[\d,]{3,})\b",   # 至少4位数，避免误匹配小数字
]
_ABS_QTY_SINGLE = ["单笔", "每笔", "each.*trade", "per.*trade", "single.*order", "per.*order"]
_ABS_QTY_UPPER  = ["不得超过", "上限", "最多", "must not exceed", "limit", "no more than", "up to", "max"]
_VENUE_NEED_CN  = ["已批准的", "经批准的", "批准的"]
_VENUE_NEED_EN  = ["approved venues", "approved venue", "permitted venues"]
_BROKER_NEED_CN = ["已批准的.*经纪", "经批准.*经纪", "批准.*broker"]
_BROKER_NEED_EN = ["approved broker", "approved dealers", "permitted broker"]


def _s7_prohibit(ll: str) -> bool:
    return any(p in ll for p in _PROHIBIT_EN)


def _s7_normalize_param(ll: str) -> str:
    for pat, canon in _FINANCE_PARAM_MAP:
        if re.search(pat, ll, re.IGNORECASE):
            return canon
    return ""


def _s7_extract_pct(line: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
    if m: return float(m.group(1)) / 100.0
    m2 = re.search(r"(\d+(?:\.\d+)?)\s*percent", line, re.IGNORECASE)
    if m2: return float(m2.group(1)) / 100.0
    m_bps = re.search(r"(\d+(?:\.\d+)?)\s*(?:bps|bp)\b", line, re.IGNORECASE)
    if m_bps: return float(m_bps.group(1))
    m_years = re.search(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b", line, re.IGNORECASE)
    if m_years: return float(m_years.group(1))
    m_k = re.search(r"\$?(\d+(?:\.\d+)?)\s*[kK]\b", line)
    if m_k: return float(m_k.group(1)) * 1000
    m_m = re.search(r"\$?(\d+(?:\.\d+)?)\s*[mM]\b", line)
    if m_m: return float(m_m.group(1)) * 1_000_000
    m3 = re.search(r"\b(0\.\d+)\b", line)
    if m3: return float(m3.group(1))
    return 0.0


def _s7_is_command_term(canon: str) -> bool:
    return any(c in canon for c in [
        "_route", "_access", "_execute", "_check", "_basket",
        "_position", "_constraint", "_bucket", "_stop", "_risk",
        "_compliance", "_delegation", "reweight", "increase_", "bypass_",
        "override_", "force_", "copy_",
    ])


def extract_finance_constraints(text: str, external_ctx=None) -> Dict[str, Any]:
    """
    Source7: Finance prose NLP extractor.
    Processes financial language in policy text.
    Returns same structure as _extract_constraints_from_text().
    """
    result: Dict[str, Any] = {
        "deny": [], "deny_commands": [], "_prov": {},
        "_value_range": {}, "_invariant_s7": [], "_scheduled_window": None,
        "_aggregate_hints": {}, "_whitelist_needed": [],
    }

    def _note(dim: str, value: str, desc: str) -> None:
        result["_prov"][f"{dim}:{value}"] = desc

    # Split on sentence boundaries (protect numeric commas)
    sentences = re.split(
        r"(?<![\d,，])(?:[。！!\n]|(?<=\D),(?=\s*[^\d]))",
        text
    )

    for line in sentences:
        line = line.strip().lstrip("- *+ ").strip()
        ll = line.lower()
        if not ll:
            continue

        # 7A: prohibition word + financial term → deny / deny_commands
        if _s7_prohibit(ll):
            for term_text, canonical in _FINANCE_DENY_TERMS.items():
                if term_text.lower() in ll:
                    if _s7_is_command_term(canonical):
                        if canonical not in result["deny_commands"]:
                            result["deny_commands"].append(canonical)
                            _note("deny_commands", canonical,
                                  f"Source7(7A: prohibit+term='{term_text}', line='{line[:50]}')")
                    else:
                        if canonical not in result["deny"]:
                            result["deny"].append(canonical)
                            _note("deny", canonical,
                                  f"Source7(7A: prohibit+term='{term_text}', line='{line[:50]}')")

        # 7B/7C: numeric upper/lower bound → value_range
        has_lower_cn = any(p in line for p in _LOWER_BOUND_CN)
        has_lower_en = any(p in ll   for p in _LOWER_BOUND_EN)
        has_upper_cn = any(p in line for p in _UPPER_BOUND_CN)
        has_upper_en = any(p in ll   for p in _UPPER_BOUND_EN)

        _has_geq = any(s in line for s in ["≥", ">="])
        is_lower = _has_geq or has_lower_cn or (has_lower_en and
                   not any(p in line for p in ["不得超过", "不超过", "不能超过"]))
        is_upper = (has_upper_cn or has_upper_en) and not is_lower

        param = _s7_normalize_param(ll)
        val   = _s7_extract_pct(line)
        if param and val > 0:
            vr = result["_value_range"].setdefault(param, {})
            if is_upper:
                vr["max"] = val
                _note("value_range", f"{param}:max",
                      f"Source7_finance(upper={val:.4f}, param='{param}', line='{line[:50]}')")
            elif is_lower:
                vr["min"] = val
                _note("value_range", f"{param}:min",
                      f"Source7_finance(lower={val:.4f}, param='{param}', line='{line[:50]}')")

        # 7D: precondition trigger + finance precondition parameter
        _no_pass_cn = re.search(r"没.{0,15}通过|未.{0,15}通过", line)
        _needs_cn   = re.search(r"需要.{0,20}(批准|通过|满足)|必须.{0,15}(通过|满足|批准)|才能.{0,10}[发执行]", line)
        _needs_en   = re.search(r"requires?[\s\w]+(approval|authorization)", ll, re.IGNORECASE)
        has_prereq  = (any(p in ll for p in _PREREQ_TRIGGER_EN) or
                       bool(_no_pass_cn) or bool(_needs_cn) or bool(_needs_en))
        if has_prereq:
            for prereq_pat, prereq_canon in _FINANCE_PREREQ_MAP:
                if prereq_canon and re.search(prereq_pat, ll, re.IGNORECASE):
                    inv = f"{prereq_canon} == True"
                    if inv not in result["_invariant_s7"]:
                        result["_invariant_s7"].append(inv)
                        _note("invariant_s7", prereq_canon,
                              f"Source7_finance(prereq, pattern='{prereq_pat}', line='{line[:50]}')")

        # 7F: absolute quantity detection
        import re as _re7f
        for qty_pat in _ABS_QTY_PATTERNS:
            m = _re7f.search(qty_pat, line, _re7f.IGNORECASE)
            if m:
                raw_num = m.group(1).replace(",", "").replace("，", "")
                try:
                    qty = float(raw_num)
                    if "万" in line[max(0,m.start()-2):m.end()+3]:
                        qty *= 10000
                    elif _re7f.search(r"[kK]\s*(?:shares?|lots?)", line[m.start():m.end()+12]):
                        qty *= 1000
                    elif _re7f.search(r"[mM]\s*(?:shares?|lots?)", line[m.start():m.end()+12]):
                        qty *= 1000000
                    is_single = any(p in ll for p in _ABS_QTY_SINGLE)
                    hint = {"max_sum": qty, "is_single": is_single,
                            "source": f"Source7_7F(line='{line[:40]}')"}
                    result["_aggregate_hints"]["child_order_qty"] = hint
                    _note("aggregate_hints", "child_order_qty",
                          f"Source7_7F(qty={qty})")
                except (ValueError, IndexError):
                    pass
                break

        # 7G: venue/broker whitelist flags
        if any(p in ll for p in [p.lower() for p in _VENUE_NEED_CN] + _VENUE_NEED_EN):
            if "approved_venues" not in result["_whitelist_needed"]:
                result["_whitelist_needed"].append("approved_venues")
        if any(re.search(p, ll) for p in _BROKER_NEED_CN + _BROKER_NEED_EN):
            if "approved_brokers" not in result["_whitelist_needed"]:
                result["_whitelist_needed"].append("approved_brokers")

    # Post-processing: merge into canonical fields
    out: Dict[str, Any] = {"deny": result["deny"], "deny_commands": result["deny_commands"],
                            "_prov": result["_prov"]}

    if result["_value_range"]:
        out["value_range"] = {}
        for param, bounds in result["_value_range"].items():
            out["value_range"][param] = bounds

    if result["_invariant_s7"]:
        out["invariant_s7"] = result["_invariant_s7"]

    if result["_aggregate_hints"]:
        out["aggregate_hints"] = result["_aggregate_hints"]

    if result["_whitelist_needed"]:
        out["_whitelist_needed"] = result["_whitelist_needed"]
        out["whitelist_needed"]  = list(dict.fromkeys(result["_whitelist_needed"]))

    # ExternalContext injection
    if external_ctx is not None:
        if hasattr(external_ctx, "approved_venues") and external_ctx.approved_venues:
            if "approved_venues" in result.get("_whitelist_needed", []):
                out["only_domains"] = list(external_ctx.approved_venues)
        if hasattr(external_ctx, "approved_brokers") and external_ctx.approved_brokers:
            if "approved_brokers" in result.get("_whitelist_needed", []):
                out["approved_brokers"] = external_ctx.approved_brokers
        if hasattr(external_ctx, "order_qty") and external_ctx.order_qty:
            out.setdefault("aggregate_hints", {})["order_qty"] = {
                "max_sum": external_ctx.order_qty, "is_single": False,
                "source": "ExternalContext.order_qty",
            }
        if hasattr(external_ctx, "temporal") and external_ctx.temporal:
            out["temporal_context"] = external_ctx.temporal.to_dict()

    return out





# ── Finance snapshot checker (B3: VaR + ADV participation) ──────────────────
def _finance_snapshot_check(snapshot, params: dict, contract) -> list:
    """
    Finance-domain snapshot validator for check_all().
    Checks:
      1. VaR headroom: current_var must not exceed var_limit
      2. ADV participation: requested qty must not exceed ADV × max_participation_rate
    """
    from ystar.kernel.engine import Violation
    violations = []

    # 1. VaR headroom
    current_var = getattr(snapshot, "current_var", None)
    var_limit   = getattr(snapshot, "var_limit", None)
    if current_var is not None and var_limit is not None:
        if current_var > var_limit:
            violations.append(Violation(
                dimension  = "risk_snapshot",
                field      = "current_var",
                message    = (f"VaR limit breached: current_var={current_var:.4f} "
                              f"exceeds var_limit={var_limit:.4f}"),
                actual     = str(current_var),
                constraint = f"current_var <= {var_limit}",
                severity   = 1.0,
            ))

    # 2. ADV participation
    adv_data = getattr(snapshot, "adv_data", {})
    if adv_data and params:
        ticker = (params.get("ticker") or params.get("symbol")
                  or params.get("instrument"))
        qty    = (params.get("qty") or params.get("order_qty")
                  or params.get("shares"))
        if ticker and qty and ticker in adv_data:
            pr_bounds = {}
            if hasattr(contract, "value_range") and contract.value_range:
                pr_bounds = contract.value_range.get("participation_rate", {})
            max_pr    = pr_bounds.get("max", 0.10)
            adv       = adv_data[ticker]
            adv_limit = adv * max_pr
            if float(qty) > adv_limit:
                violations.append(Violation(
                    dimension  = "risk_snapshot",
                    field      = "order_qty",
                    message    = (f"ADV participation limit exceeded for {ticker}: "
                                  f"qty={qty} > ADV\u00d7{max_pr:.0%}={adv_limit:.0f}"),
                    actual     = str(qty),
                    constraint = f"qty <= ADV({ticker})\u00d7{max_pr:.0%}={adv_limit:.0f}",
                    severity   = 0.9,
                ))
    return violations


def register() -> None:
    """Register Source7 NL extractor + snapshot checker with the kernel."""
    from ystar.kernel.prefill import register_nl_extractor, register_ontology_extension
    from ystar.kernel.dimensions import register_snapshot_checker
    register_nl_extractor(extract_finance_constraints)
    register_ontology_extension(_FINANCE_PARAM_MAP)
    register_snapshot_checker(_finance_snapshot_check)

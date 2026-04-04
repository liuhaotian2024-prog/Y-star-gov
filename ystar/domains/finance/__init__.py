"""
Y* Finance Domain Pack

Financial services domain pack, applicable to:
  - Trade execution and compliance
  - Multi-agent delegation chains (human → risk agent → execution agent → settlement agent)
  - Normative interaction for causally-grounded agents
  - Intent contract propagation in regulated environments

This pack encapsulates all finance-specific knowledge,
keeping the Y* kernel industry-agnostic.

Usage:
  from ystar.domains.finance import FinanceDomainPack, make_etf_chain
  pack = FinanceDomainPack()
  constitution = pack.constitutional_contract()
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ystar.domains import DomainPack
from ystar import IntentContract, ConstitutionalContract, DelegationContract


# ══════════════════════════════════════════════════════════════════
# Finance Domain Pack
# ══════════════════════════════════════════════════════════════════

class FinanceDomainPack(DomainPack):
    """
    Finance domain pack.

    Supports external configuration (no Python changes required):
      pack = FinanceDomainPack.from_json_file("config/finance.json")
      pack = FinanceDomainPack.from_dict({"sanctioned_entities": [...]})
    """

    def __init__(self, config=None):
        self._config = config  # FinancePackConfig or None (uses defaults)

    @classmethod
    def from_dict(cls, config_dict: dict) -> "FinanceDomainPack":
        """Create from a configuration dictionary (no Python changes required)."""
        from ystar.domains.finance.config import FinancePackConfig
        return cls(config=FinancePackConfig.from_dict(config_dict))

    @classmethod
    def from_json_file(cls, path: str) -> "FinanceDomainPack":
        """Create from a JSON configuration file."""
        from ystar.domains.finance.config import FinancePackConfig
        return cls(config=FinancePackConfig.from_json_file(path))

    @classmethod
    def from_yaml_file(cls, path: str) -> "FinanceDomainPack":
        """Create from a YAML configuration file."""
        from ystar.domains.finance.config import FinancePackConfig
        return cls(config=FinancePackConfig.from_yaml_file(path))

    @property
    def domain_name(self) -> str:
        return "finance"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def schema_version(self) -> str:
        """Returns the config schema version if an external config is loaded."""
        if self._config is not None:
            return self._config.pack_version
        return "1.0.0"

    def vocabulary(self) -> dict:
        return {
            # 金融特定的禁止词汇（可被合规团队扩展）
            "deny_keywords": [
                "sanctioned_entity",
                "unauthorized_venue",
                "unregistered_basket_component",
            ],
            # 金融角色名称
            "role_names": [
                "authorized_participant", "head_trader", "risk_manager",
                "execution_agent", "settlement_agent", "compliance_officer",
                "portfolio_manager", "fx_dealer", "quant_analyst", "prime_broker",
            ],
            # 金融重要参数名（用于ParameterDiscovery的优先级提示）
            "param_names": [
                "creation_units", "participation_rate", "cash_substitution_pct",
                "venue_concentration", "settlement_t_plus", "settlement_risk",
                "nav_deviation", "basket_tracking_error",
            ],
            # 金融环境词
            "env_keywords": ["simulation", "paper_trading", "backtest"],
            # prefill Source扩展：金融专用的制裁实体list patterns
            "entity_list_patterns": [
                # 中文金融合规文本
                r"禁止交易(?:以下|如下)[^：:]{0,30}[：:]\s*"
                r"([A-Za-z][A-Za-z0-9_-]*(?:[,，]\s*[A-Za-z][A-Za-z0-9_-]*)+)",
                # 英文金融合规文本
                r"(?:sanctioned\s*counterpart\w*|restricted\s*entities?|"
                r"blocked\s*counterpart\w*)\s*[：:]\s*"
                r"([A-Za-z][A-Za-z0-9_-]*(?:[,，\s]+[A-Za-z][A-Za-z0-9_-]*)+)",
            ],
        }

    def constitutional_contract(self) -> ConstitutionalContract:
        """
        金融宪法层合约（可通过外置配置自定义）。
        """
        cfg = self._config
        base_deny = [
            "non_ap_entity", "unauthorized_venue", "sanctioned_entity",
            "override_basket", "bypass_risk_gate",
        ]
        # 外置配置可追加制裁实体和额外禁止词
        if cfg:
            base_deny += cfg.sanctioned_entities + cfg.extra_deny
            cmds = cfg.dangerous_commands
            sr_threshold = cfg.risk_thresholds.get("settlement_risk", 0.8)
            kyc_min = cfg.risk_thresholds.get("kyc_score_min", 0.5)
            vc_max  = cfg.risk_thresholds.get("venue_concentration_max", 0.60)
        else:
            cmds = ["force_execute ", "bypass_compliance ", "copy_delegation "]
            sr_threshold = 0.8
            kyc_min = 0.5
            vc_max  = 0.60

        return ConstitutionalContract(
            deny=list(dict.fromkeys(base_deny)),  # dedup
            deny_commands=cmds,
            optional_invariant=[
                f"settlement_risk < {sr_threshold}",
                f"kyc_score > {kyc_min}",
            ],
            value_range={
                "creation_units":        {"min": 0, "max": 10},
                "participation_rate":    {"min": 0.0, "max": 0.25},
                "cash_substitution_pct": {"min": 0.0, "max": 0.20},
                "venue_concentration":   {"min": 0.0, "max": vc_max},
            },
        )

    # ── 角色合约工厂 ──────────────────────────────────────────────

    def make_contract(self, role: str, context: dict = None) -> IntentContract:
        """
        Generate the IntentContract for the given role.
        All role contracts inherit from the constitutional layer.

        Args:
            role: 'head_trader' | 'risk_manager' | 'execution_agent' |
                  'settlement_agent' | 'compliance_officer' |
                  'portfolio_manager' | 'fx_dealer' | 'quant_analyst' | 'prime_broker'
            context: optional context parameters, e.g. {"max_amount": 2_000_000}

        Returns:
            IntentContract — the role contract (with the constitutional layer already merged in)
        """
        ctx = context or {}
        constitution = self.constitutional_contract()

        role_contracts = {
            "head_trader": IntentContract(
                invariant=["ap_authorized == True"],
                value_range={
                    "amount": {"max": ctx.get("max_amount", 10_000_000)},
                    "creation_units": {"max": ctx.get("max_units", 5)},
                },
                obligation_timing={
                    "acknowledgement": 300,       # 5 min to ack order
                    "status_update": 3600,        # 1 hour status update
                    "result_publication": 1800,   # 30 min to publish result
                    "escalation": 600,            # 10 min to escalate issue
                },
            ),
            "risk_manager": IntentContract(
                invariant=["ap_authorized == True", "risk_gate_approved == True"],
                value_range={
                    "amount":            {"max": ctx.get("max_amount", 2_000_000)},
                    "participation_rate": {"max": 0.20},
                    "creation_units":    {"max": ctx.get("max_units", 2)},
                },
                obligation_timing={
                    "acknowledgement": 180,       # 3 min to ack risk check
                    "status_update": 1800,        # 30 min status update
                    "result_publication": 3600,   # 1 hour to publish risk decision
                    "escalation": 300,            # 5 min to escalate risk issue
                },
            ),
            "execution_agent": IntentContract(
                invariant=["ap_authorized == True", "risk_gate_approved == True",
                           "venue_approved == True"],
                value_range={
                    "amount":            {"max": ctx.get("max_amount", 500_000)},
                    "participation_rate": {"max": 0.15},
                    "creation_units":    {"max": ctx.get("max_units", 0.5)},
                },
                obligation_timing={
                    "acknowledgement": 60,        # 1 min to ack execution request
                    "status_update": 300,         # 5 min status update
                    "result_publication": 900,    # 15 min to publish fill
                    "escalation": 120,            # 2 min to escalate execution issue
                },
            ),
            "settlement_agent": IntentContract(
                invariant=["ap_authorized == True", "settlement_confirmed == True"],
                optional_invariant=["settlement_risk < 0.7"],  # 比宪法层更严
                value_range={
                    "amount":         {"max": ctx.get("max_amount", 500_000)},
                    "settlement_t_plus": {"max": 2},
                },
                obligation_timing={
                    "acknowledgement": 3600,      # 1 hour to ack settlement request
                    "status_update": 21600,       # 6 hours status update
                    "result_publication": 86400,  # 24 hours to confirm settlement
                    "escalation": 1800,           # 30 min to escalate settlement issue
                },
            ),
            "compliance_officer": IntentContract(
                invariant=["compliance_role == True"],
                deny=["unauthorized_exception"],
                obligation_timing={
                    "acknowledgement": 1800,      # 30 min to ack compliance check
                    "status_update": 14400,       # 4 hours status update
                    "result_publication": 28800,  # 8 hours to publish compliance decision
                    "escalation": 900,            # 15 min to escalate compliance violation
                },
            ),

            # ── A3 new roles ─────────────────────────────────────────
            "portfolio_manager": IntentContract(
                # Portfolio manager: owns the overall portfolio strategy; may rebalance,
                # but is subject to tracking-error and turnover constraints
                invariant=["pm_authorized == True", "risk_gate_approved == True"],
                value_range={
                    "tracking_error_budget": {"max": ctx.get("tracking_error_budget", 0.02)},
                    "daily_turnover":        {"max": ctx.get("daily_turnover", 0.10)},
                    "factor_exposure":       {"min": ctx.get("factor_exposure_min", -0.5),
                                              "max": ctx.get("factor_exposure_max",  0.5)},
                    "cash_buffer":           {"min": ctx.get("cash_buffer_min", 0.02)},
                    "amount":                {"max": ctx.get("max_amount", 50_000_000)},
                },
                deny=["style_drift_unhedged", "benchmark_deviation_unapproved"],
                obligation_timing={
                    "acknowledgement": 900,       # 15 min to ack rebalance request
                    "status_update": 7200,        # 2 hours status update
                    "result_publication": 14400,  # 4 hours to publish rebalance result
                    "escalation": 1800,           # 30 min to escalate portfolio issue
                },
            ),

            "fx_dealer": IntentContract(
                # FX dealer: executes FX conversions and hedges;
                # must operate within approved venues and currency pairs
                invariant=["fx_authorized == True", "venue_approved == True"],
                value_range={
                    "order_notional": {"max": ctx.get("max_notional", 5_000_000)},
                    "spread_bps":     {"max": ctx.get("max_spread_bps", 10)},
                    "position_concentration": {"max": ctx.get("max_position_concentration", 0.25)},
                },
                deny=["sanctioned_currency_pair", "undisclosed_fx_markup"],
                obligation_timing={
                    "acknowledgement": 120,       # 2 min to ack FX order
                    "status_update": 600,         # 10 min status update
                    "result_publication": 1800,   # 30 min to publish FX fill
                    "escalation": 180,            # 3 min to escalate FX issue
                },
            ),

            "quant_analyst": IntentContract(
                # Quant analyst: may read data, run simulations, and submit signals;
                # may not directly execute live trades
                invariant=["quant_authorized == True"],
                value_range={
                    "net_beta":        {"min": ctx.get("net_beta_min", -0.3),
                                        "max": ctx.get("net_beta_max",  1.3)},
                    "factor_exposure": {"min": ctx.get("factor_exposure_min", -1.0),
                                        "max": ctx.get("factor_exposure_max",  1.0)},
                },
                deny=["live_execution_without_approval", "model_override_undocumented"],
                obligation_timing={
                    "acknowledgement": 1800,      # 30 min to ack model request
                    "status_update": 10800,       # 3 hours status update
                    "result_publication": 21600,  # 6 hours to publish model signal
                    "escalation": 3600,           # 1 hour to escalate model issue
                },
            ),

            "prime_broker": IntentContract(
                # Prime broker: handles custody, financing, and collateral management;
                # must maintain the credit-rating floor and concentration ceiling
                invariant=["pb_authorized == True", "margin_approved == True"],
                value_range={
                    "position_concentration": {"max": ctx.get("max_position_concentration", 0.20)},
                    "credit_rating_floor":    {"min": ctx.get("credit_rating_floor", 6)},  # e.g. 6 = BBB
                    "amount":                 {"max": ctx.get("max_amount", 100_000_000)},
                },
                deny=["rehypothecation_without_consent", "margin_call_suppression"],
                obligation_timing={
                    "acknowledgement": 7200,      # 2 hours to ack prime broker request
                    "status_update": 28800,       # 8 hours status update
                    "result_publication": 86400,  # 24 hours to publish margin decision
                    "escalation": 3600,           # 1 hour to escalate margin issue
                },
            ),
        }

        base = role_contracts.get(role, IntentContract())
        return base.merge(constitution)


# ══════════════════════════════════════════════════════════════════
# Convenience：构建标准委托链
# ══════════════════════════════════════════════════════════════════

def make_etf_delegation_chain(
    pack: FinanceDomainPack = None,
    max_amount: float = 5_000_000,
    max_units: float = 2.0,
) -> "DelegationChain":
    """
    构建标准ETF申赎委托链：
    Head Trader → Risk Manager → Execution Agent

    这是Y*金融场景的典型委托链，
    封装在域包里，内核不知道ETF是什么。
    """
    from ystar import DelegationChain
    import time

    if pack is None:
        pack = FinanceDomainPack()

    ctx = {"max_amount": max_amount, "max_units": max_units}

    ht_contract   = pack.make_contract("head_trader",    ctx)
    rm_contract   = pack.make_contract("risk_manager",   {"max_amount": max_amount * 0.4, "max_units": max_units})
    exec_contract = pack.make_contract("execution_agent", {"max_amount": max_amount * 0.1, "max_units": max_units * 0.25})

    from ystar import IntentContract
    # exec_contract must inherit rm_contract constraints (monotonicity)
    exec_contract_inherited = IntentContract(
        deny          = list(dict.fromkeys(exec_contract.deny + rm_contract.deny)),
        deny_commands = list(dict.fromkeys(exec_contract.deny_commands + rm_contract.deny_commands)),
        only_paths    = exec_contract.only_paths or rm_contract.only_paths,
        only_domains  = exec_contract.only_domains or rm_contract.only_domains,
        invariant     = list(dict.fromkeys(exec_contract.invariant + rm_contract.invariant)),
        optional_invariant = list(dict.fromkeys(
            exec_contract.optional_invariant + rm_contract.optional_invariant)),
        value_range   = {**rm_contract.value_range, **exec_contract.value_range},
        name          = "execution_agent_inherited",
    )

    chain = DelegationChain([
        DelegationContract(
            principal="head_trader", actor="risk_manager_agent",
            contract=rm_contract,
            action_scope=["validate_risk", "approve_trade", "execute_trade", "route_order"],
            prerequisites=["market_open == True"],
            allow_redelegate=True,
            delegation_depth=1,
            valid_until=time.time() + 28800,
            grant_id="GRANT-HT-RM",
        ),
        DelegationContract(
            principal="risk_manager_agent", actor="execution_agent",
            contract=exec_contract_inherited,
            action_scope=["execute_trade", "route_order"],   # ⊆ parent scope
            prerequisites=["risk_gate_approved == True"],
            delegation_depth=0,
            grant_id="GRANT-RM-EXEC",
        ),
    ])
    return chain


# ── 主动注册 ontology 到 kernel prefill ──────────────────────────────────────
# 正确方向：域层主动推送，内核被动接收。
# kernel/prefill.py 不再需要知道 finance/ontology.py 的路径。

def _register_finance_func_patterns():
    """向内核注册金融场景专属的函数名约束建议。"""
    try:
        from ystar.kernel.prefill import register_func_pattern, register_aggregate_pattern
        # 金融操作函数名 → 默认拒绝生产环境
        for name in ("payment", "pay", "charge", "fund", "invest",
                     "withdraw", "redeem", "subscribe", "purchase"):
            register_func_pattern(name, {"deny": ["production", "prod"]})
        # 金融函数时间窗口速率建议（每小时次数限制）
        # 注意：register_func_pattern 只支持 deny/deny_commands，
        # 速率限制通过 _HIGH_RISK_TEMPORAL_PATTERNS 的同名条目生效
        for kw, max_calls, window in [
            ("pay",      10, 3600),
            ("charge",   10, 3600),
            ("withdraw",  5, 3600),
            ("redeem",   10, 3600),
            ("purchase", 20, 3600),
        ]:
            _temporal = (max_calls, window)
            try:
                from ystar.kernel.prefill import _HIGH_RISK_TEMPORAL_PATTERNS
                if kw not in _HIGH_RISK_TEMPORAL_PATTERNS:
                    _HIGH_RISK_TEMPORAL_PATTERNS[kw] = _temporal
            except Exception:
                pass
        # 金融聚合约束默认建议（日限额，极其保守，实际阈值应由合规官配置覆盖）
        register_aggregate_pattern("pay",      "amount", 1_000_000, 86400)
        register_aggregate_pattern("charge",   "amount",   500_000, 86400)
        register_aggregate_pattern("withdraw", "amount",   100_000, 86400)
        register_aggregate_pattern("redeem",   "amount", 1_000_000, 86400)
    except Exception:
        pass

def _register_finance_ontology():
    try:
        from ystar.domains.finance.ontology import CORE_FINANCE_ONTOLOGY
        from ystar.kernel.prefill import register_ontology_extension
        patterns = CORE_FINANCE_ONTOLOGY.export_to_source7_param_map()
        register_ontology_extension(patterns)
    except Exception:
        pass  # ontology 不存在时静默跳过，不影响内核功能


def _register_finance_source7():
    """Register Source7 (finance prose NLP) with the kernel extractor pipeline."""
    try:
        from ystar.domains.finance._source7 import register
        register()
    except Exception:
        pass



def _register_finance_timezones():
    """Register common financial-market timezone offsets with the kernel."""
    try:
        from ystar.kernel.dimensions import register_timezone_offset
        # Major financial centre timezones (simplified — DST not modelled)
        _FINANCE_TIMEZONES = {
            "America/New_York":    -5.0,   # NYSE, NASDAQ
            "America/Chicago":     -6.0,   # CME
            "America/Los_Angeles": -8.0,
            "Europe/London":        0.0,   # LSE
            "Europe/Frankfurt":     1.0,   # XETRA
            "Asia/Tokyo":           9.0,   # TSE
            "Asia/Shanghai":        8.0,   # SSE, SZSE
            "Asia/Hong_Kong":       8.0,   # HKEX
            "Asia/Singapore":       8.0,   # SGX
            "Australia/Sydney":    10.0,   # ASX
        }
        for tz_name, offset in _FINANCE_TIMEZONES.items():
            register_timezone_offset(tz_name, offset)
    except Exception:
        pass


_register_finance_ontology()
_register_finance_source7()
_register_finance_timezones()
_register_finance_func_patterns()

"""
Y* Crypto Domain Pack

Cryptocurrency trading domain pack, applicable to:
  - Spot and derivatives trading on centralised exchanges (CEX)
  - Perpetual and fixed-term futures: funding rate, open interest, liquidation price
  - DeFi protocol interactions: collateral ratio, health factor, slippage
  - Multi-agent execution: signal agent → risk agent → order agent

This pack demonstrates that the Y* kernel is finance-agnostic —
the same DomainPack interface applied to crypto-specific constraints.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ystar.domains import DomainPack
from ystar import IntentContract, ConstitutionalContract, DelegationContract


class CryptoDomainPack(DomainPack):
    """
    Cryptocurrency domain pack.

    Roles available via make_contract():
      signal_agent, risk_manager, order_agent, settlement_agent,
      compliance_officer, liquidation_monitor
    """

    def __init__(self, config=None):
        self._config = config

    @property
    def domain_name(self) -> str:
        return "crypto"

    @property
    def version(self) -> str:
        return "1.0.0"

    def vocabulary(self) -> dict:
        return {
            "deny_keywords": [
                "sanctioned_address",
                "mixer_protocol",
                "unregistered_exchange",
                "wash_trade_crypto",
            ],
            "role_names": [
                "signal_agent", "risk_manager", "order_agent",
                "settlement_agent", "compliance_officer", "liquidation_monitor",
            ],
            "param_names": [
                "funding_rate", "open_interest_pct", "liquidation_price",
                "collateral_ratio", "health_factor", "leverage",
                "position_size_usd", "slippage_bps", "order_notional",
            ],
            "env_keywords": ["testnet", "simulation", "paper_trading", "sandbox"],
            "entity_list_patterns": [
                r"(?:sanctioned\s*address(?:es)?|blocked\s*address(?:es)?)\s*[:\xef\xbc\x9a]\s*"
                r"(0x[0-9a-fA-F]{4,}(?:[,\xef\xbc\x8c\s]+0x[0-9a-fA-F]{4,})*)",
            ],
        }

    def constitutional_contract(self) -> ConstitutionalContract:
        """
        Crypto constitutional layer:
          - No sanctioned addresses or mixer protocols
          - Leverage <= 20x (tightened per role)
          - health_factor >= 1.0 at all times
        """
        cfg = self._config or {}
        sanctioned  = list(cfg.get("sanctioned_addresses", []))
        extra_deny  = list(cfg.get("extra_deny", []))
        max_leverage= cfg.get("max_leverage", 20.0)
        min_hf      = cfg.get("min_health_factor", 1.0)

        return ConstitutionalContract(
            deny          = ["sanctioned_address", "mixer_protocol",
                             "unregistered_exchange"] + sanctioned + extra_deny,
            deny_commands = ["force_liquidate_all", "bypass_margin_check"],
            optional_invariant = [f"health_factor >= {min_hf}"],
            value_range   = {"leverage": {"max": max_leverage}},
        )

    def make_contract(self, role: str, context: dict = None) -> IntentContract:
        """
        Generate the IntentContract for the given role.
        All role contracts inherit from the constitutional layer.

        Args:
            role:    one of signal_agent | risk_manager | order_agent |
                     settlement_agent | compliance_officer | liquidation_monitor
            context: optional overrides, e.g. {"max_leverage": 5.0}
        """
        ctx          = context or {}
        constitution = self.constitutional_contract()

        role_contracts = {
            "signal_agent": IntentContract(
                invariant   = ["signal_authorized == True"],
                value_range = {
                    "funding_rate":      {"max": ctx.get("max_funding_rate", 0.01)},
                    "open_interest_pct": {"max": ctx.get("max_oi_pct",       0.05)},
                },
                deny = ["market_manipulation", "wash_trade_crypto",
                        "live_order_without_approval"],
                obligation_timing={
                    "acknowledgement": 60,        # 1 min to ack signal request
                    "status_update": 300,         # 5 min status update
                    "result_publication": 600,    # 10 min to publish signal
                    "escalation": 120,            # 2 min to escalate market anomaly
                },
            ),

            "risk_manager": IntentContract(
                invariant   = ["risk_authorized == True", "risk_gate_approved == True"],
                value_range = {
                    "leverage":          {"max": ctx.get("max_leverage",        10.0)},
                    "funding_rate":      {"max": ctx.get("max_funding_rate",   0.005)},
                    "open_interest_pct": {"max": ctx.get("max_oi_pct",         0.03)},
                    "position_size_usd": {"max": ctx.get("max_position_usd", 500_000)},
                    "collateral_ratio":  {"min": ctx.get("min_collateral_ratio", 1.5)},
                },
                deny = ["sanctioned_address", "mixer_protocol"],
                obligation_timing={
                    "acknowledgement": 30,        # 30 sec to ack risk check
                    "status_update": 180,         # 3 min status update
                    "result_publication": 300,    # 5 min to publish risk decision
                    "escalation": 60,             # 1 min to escalate risk breach
                },
            ),

            "order_agent": IntentContract(
                invariant   = ["risk_gate_approved == True", "venue_approved == True"],
                value_range = {
                    "leverage":          {"max": ctx.get("max_leverage",          5.0)},
                    "slippage_bps":      {"max": ctx.get("max_slippage_bps",       50)},
                    "order_notional":    {"max": ctx.get("max_order_notional", 100_000)},
                    "position_size_usd": {"max": ctx.get("max_position_usd",   200_000)},
                },
                deny = ["sanctioned_address", "mixer_protocol",
                        "market_manipulation", "wash_trade_crypto"],
                obligation_timing={
                    "acknowledgement": 30,        # 30 sec to ack order
                    "status_update": 120,         # 2 min status update
                    "result_publication": 300,    # 5 min to complete order
                    "escalation": 60,             # 1 min to escalate order failure
                },
            ),

            "settlement_agent": IntentContract(
                invariant   = ["settlement_authorized == True",
                               "withdrawal_confirmed == True"],
                value_range = {
                    "order_notional": {"max": ctx.get("max_notional", 50_000)},
                },
                deny = ["sanctioned_address", "mixer_protocol",
                        "unregistered_exchange", "unverified_withdrawal_address"],
                obligation_timing={
                    "acknowledgement": 600,       # 10 min to ack settlement
                    "status_update": 1800,        # 30 min status update
                    "result_publication": 3600,   # 1 hour to confirm on-chain
                    "escalation": 900,            # 15 min to escalate settlement issue
                },
            ),

            "compliance_officer": IntentContract(
                invariant = ["compliance_role == True"],
                deny      = ["bypass_kyc", "bypass_aml", "unauthorized_exception"],
                obligation_timing={
                    "acknowledgement": 1800,      # 30 min to ack compliance check
                    "status_update": 7200,        # 2 hours status update
                    "result_publication": 14400,  # 4 hours to publish AML report
                    "escalation": 900,            # 15 min to escalate sanctions match
                },
            ),

            "liquidation_monitor": IntentContract(
                invariant   = ["monitor_authorized == True"],
                value_range = {
                    "health_factor":     {"min": ctx.get("min_health_factor",    1.05)},
                    "collateral_ratio":  {"min": ctx.get("min_collateral_ratio", 1.3)},
                    "liquidation_price": {"min": ctx.get("min_liquidation_price", 0.0)},
                },
                deny = ["force_liquidate_without_approval",
                        "suppress_liquidation_alert"],
                obligation_timing={
                    "acknowledgement": 60,        # 1 min to ack liquidation alert
                    "status_update": 300,         # 5 min status update
                    "result_publication": 600,    # 10 min to publish health status
                    "escalation": 30,             # 30 sec to escalate critical liquidation
                },
            ),
        }

        base = role_contracts.get(role, IntentContract())
        return base.merge(constitution)


def make_crypto_delegation_chain(
    pack:             CryptoDomainPack = None,
    max_leverage:     float = 5.0,
    max_position_usd: float = 200_000,
) -> "DelegationChain":
    """
    Build a standard signal → risk → order delegation chain for crypto.

    v0.24.0: monotonicity enforced — each link's contract is a strict subset
    of the parent's contract; action_scope only narrows, never expands.
    """
    from ystar import DelegationChain, IntentContract
    import time

    if pack is None:
        pack = CryptoDomainPack()

    ctx = {"max_leverage": max_leverage, "max_position_usd": max_position_usd}

    rm_contract = pack.make_contract("risk_manager", {
        **ctx,
        "max_leverage":     max_leverage * 0.8,
        "max_position_usd": max_position_usd * 0.5,
    })
    order_contract_base = pack.make_contract("order_agent", {
        **ctx,
        "max_leverage":     max_leverage * 0.5,
        "max_position_usd": max_position_usd * 0.25,
    })
    # Inherit rm_contract constraints so order_contract ⊆ rm_contract
    order_contract = IntentContract(
        deny          = list(dict.fromkeys(order_contract_base.deny + rm_contract.deny)),
        deny_commands = list(dict.fromkeys(order_contract_base.deny_commands + rm_contract.deny_commands)),
        only_paths    = order_contract_base.only_paths or rm_contract.only_paths,
        only_domains  = order_contract_base.only_domains or rm_contract.only_domains,
        invariant     = list(dict.fromkeys(order_contract_base.invariant + rm_contract.invariant)),
        optional_invariant = list(dict.fromkeys(
            order_contract_base.optional_invariant + rm_contract.optional_invariant)),
        value_range   = {**rm_contract.value_range, **order_contract_base.value_range},
        name          = "order_agent_inherited",
    )

    # Parent action_scope must be superset of child scope
    sa_to_rm = DelegationContract(
        principal        = "signal_agent",
        actor            = "risk_manager_agent",
        contract         = rm_contract,
        action_scope     = ["approve_position", "reject_position", "submit_order", "cancel_order"],
        delegation_depth = 1,
        allow_redelegate = True,
        valid_until      = time.time() + 86_400,
    )
    rm_to_order = DelegationContract(
        principal        = "risk_manager_agent",
        actor            = "order_agent",
        contract         = order_contract,
        action_scope     = ["submit_order", "cancel_order"],   # ⊆ parent scope
        delegation_depth = 0,
        allow_redelegate = False,
        valid_until      = time.time() + 86_400,
    )

    return DelegationChain().append(sa_to_rm).append(rm_to_order)

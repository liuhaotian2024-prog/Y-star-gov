"""
ystar.governance.domain_context
================================
可选的领域 taxonomy 枚举（DomainContext）。

设计原则
--------
治理核心（metalearning.py 等）不内置任何行业分类。
DomainContext 是一个「用户便利层」——给调用者提供
常见行业的标准化字符串常量，避免每次手写 "equity_execution"。

使用方式
--------
- 不传 domain_context：inquiry 函数按「通用场景」工作，不附加行业上下文
- 传字符串：任意自定义上下文，完全自由
- 传 DomainContext.XXX：使用此处预定义的行业标准名称

此文件可以被任何团队替换/扩展，而不影响核心治理逻辑。
"""
import enum as _enum
import warnings as _warnings


class DomainContext(_enum.Enum):
    """
    Standard domain context taxonomy for SemanticInquiry.

    Passing a DomainContext enum value (rather than a free-form string) ensures
    consistent prompt construction and reproducible LLM suggestions across callers.

    Backward compatibility: all functions that accept domain_context still accept
    plain strings; passing an unrecognised string emits a UserWarning but does not
    raise.  The canonical string values below are the authoritative labels.

    Values
    ------
    EQUITY_EXECUTION
        Institutional equity execution: VWAP/TWAP/participation-rate strategies,
        single-stock or basket orders on lit/dark venues.
    FIXED_INCOME
        Fixed income trading: bonds, credit, rates; duration, convexity, spread constraints.
    FUTURES_DERIVATIVES
        Futures and listed derivatives: roll windows, open-interest limits,
        DV01, options Greeks.
    PORTFOLIO_REBALANCING
        Portfolio rebalancing and index tracking: tracking error, factor exposure,
        turnover, cash buffer.
    FX
        Foreign exchange execution and hedging: spot, forward, NDF;
        spread, notional, currency-pair restrictions.
    CRYPTO
        Cryptocurrency trading: funding rate, liquidation price, open interest.
    DEVOPS
        DevOps / production control: deployment permissions, change approval chains,
        command execution constraints.
    HEALTHCARE
        Healthcare / clinical data: PHI access, consent gating, audit logging.
    GENERIC
        No specific domain; use when context is unknown or intentionally broad.
    """
    EQUITY_EXECUTION     = "equity_execution"
    FIXED_INCOME         = "fixed_income"
    FUTURES_DERIVATIVES  = "futures_derivatives"
    PORTFOLIO_REBALANCING= "portfolio_rebalancing"
    FX                   = "fx"
    CRYPTO               = "crypto"
    DEVOPS               = "devops"
    HEALTHCARE           = "healthcare"
    GENERIC              = "generic"

    @classmethod
    def _missing_(cls, value):
        """Allow case-insensitive lookup; return None (not an error) for unknowns."""
        if isinstance(value, str):
            for member in cls:
                if member.value == value.lower():
                    return member
        return None

    @classmethod
    def from_string(cls, s: str) -> "_enum.Enum":
        """
        Convert a string to DomainContext.

        Returns the matching member if found (case-insensitive); emits a UserWarning
        and returns DomainContext.GENERIC if the string is not in the taxonomy.
        """
        if not s:
            return cls.GENERIC
        # Case-insensitive lookup against canonical values
        s_lower = s.lower()
        for member in cls:
            if member.value == s_lower:
                return member

        # ── Alias / fuzzy mapping for common non-canonical strings ──────────
        # Allows callers to pass plain-English descriptions without warnings.
        _ALIAS_MAP = {
            # ETF variants
            "etf":                         cls.EQUITY_EXECUTION,
            "etf settlement":              cls.EQUITY_EXECUTION,
            "etf creation":                cls.EQUITY_EXECUTION,
            "etf redemption":              cls.EQUITY_EXECUTION,
            "etf creation/redemption":     cls.EQUITY_EXECUTION,
            "etf creation/redemption risk management": cls.EQUITY_EXECUTION,
            "etf trading":                 cls.EQUITY_EXECUTION,
            # Equity variants
            "equity execution":            cls.EQUITY_EXECUTION,
            "equity":                      cls.EQUITY_EXECUTION,
            "equity trading":              cls.EQUITY_EXECUTION,
            "institutional equity":        cls.EQUITY_EXECUTION,
            "us equity":                   cls.EQUITY_EXECUTION,
            "stock trading":               cls.EQUITY_EXECUTION,
            # Fixed income variants
            "fixed income":                cls.FIXED_INCOME,
            "bonds":                       cls.FIXED_INCOME,
            "credit":                      cls.FIXED_INCOME,
            "rates":                       cls.FIXED_INCOME,
            "bond trading":                cls.FIXED_INCOME,
            # Futures variants
            "futures":                     cls.FUTURES_DERIVATIVES,
            "derivatives":                 cls.FUTURES_DERIVATIVES,
            "options":                     cls.FUTURES_DERIVATIVES,
            "cta":                         cls.FUTURES_DERIVATIVES,
            # Portfolio variants
            "portfolio":                   cls.PORTFOLIO_REBALANCING,
            "rebalancing":                 cls.PORTFOLIO_REBALANCING,
            "basket rebalance":            cls.PORTFOLIO_REBALANCING,
            "index tracking":              cls.PORTFOLIO_REBALANCING,
            # FX variants
            "foreign exchange":            cls.FX,
            "forex":                       cls.FX,
            "fx trading":                  cls.FX,
            # Crypto variants
            "crypto":                      cls.CRYPTO,
            "cryptocurrency":              cls.CRYPTO,
            "defi":                        cls.CRYPTO,
            "stablecoin":                  cls.CRYPTO,
            # DevOps variants
            "devops":                      cls.DEVOPS,
            "deployment":                  cls.DEVOPS,
            "cicd":                        cls.DEVOPS,
            "production control":          cls.DEVOPS,
            # Healthcare variants
            "healthcare":                  cls.HEALTHCARE,
            "clinical":                    cls.HEALTHCARE,
            "medical":                     cls.HEALTHCARE,
            "hipaa":                       cls.HEALTHCARE,
        }
        # Also try prefix/substring match for multi-word descriptions
        matched = _ALIAS_MAP.get(s_lower)
        if matched is not None:
            return matched
        # Substring match: if any canonical value (with underscore→space) appears in the string
        for member in cls:
            normalised = member.value.replace("_", " ")
            if normalised in s_lower and member != cls.GENERIC:
                return member

        # Not found — warn and fall back
        _warnings.warn(
            f"DomainContext: unrecognised domain string '{s}'. "
            f"Valid values: {[m.value for m in cls]}. "
            f"Falling back to DomainContext.GENERIC. "
            f"Pass a DomainContext enum member to suppress this warning.",
            UserWarning,
            stacklevel=3,
        )
        return cls.GENERIC

    def to_prompt_string(self) -> str:
        """Return the human-readable label used in LLM prompts."""
        _LABELS = {
            "equity_execution":      "institutional equity execution",
            "fixed_income":          "fixed income / credit / rates trading",
            "futures_derivatives":   "futures and listed derivatives",
            "portfolio_rebalancing": "portfolio rebalancing and index tracking",
            "fx":                    "foreign exchange execution and hedging",
            "crypto":                "cryptocurrency trading",
            "devops":                "DevOps and production control",
            "healthcare":            "healthcare and clinical data management",
            "generic":               "general financial / operational context",
        }
        return _LABELS.get(self.value, self.value)


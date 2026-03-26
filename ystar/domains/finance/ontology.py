"""
Finance Parameter Ontology — knowledge layer for the FinanceDomainPack

This is the data container for the "LLM-assisted → human review → Y* consumption" pipeline.

Design principles:
  - LLM handles candidate collation (bulk alias and usage extraction)
  - Humans act as gatekeepers (controlled via review_status)
  - Y* only consumes APPROVED entries
  - Final destination: config.py + Source7 _FINANCE_PARAM_MAP

Data hierarchy:
  prefill_patterns → Source7 real-time extraction (compile-time)
  aliases          → vocabulary alignment (bulk build phase)
  typical_operator → ParameterDiscovery hints
  example_phrases  → translation quality evaluation corpus
"""

import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class ParameterOntologyEntry:
    """
    Complete ontology definition for a single finance parameter.

    review_status lifecycle:
      DRAFT    → LLM-generated candidate, not yet reviewed
      APPROVED → confirmed by a human; may be promoted to Source7 and config
      REJECTED → rejected by a human (ambiguous / inaccurate / overly specific)
    """
    canonical_name:   str                   # "child_order_qty" (canonical parameter name in Y*)
    aliases:          List[str]             # ["slice size", "clip size", "child order count"]
    unit:             str = ""              # "shares" / "%" / "bps" / "USD"
    context:          str = ""             # "execution" / "risk" / "portfolio" / "futures"
    typical_operator: str = "max"          # "max" / "min" / "max_abs" / "range"
    prefill_patterns: List[str] = field(default_factory=list)  # 进Source7的正则pattern
    example_phrases:  List[str] = field(default_factory=list)  # 示例句子
    review_status:    str = "DRAFT"        # DRAFT / APPROVED / REJECTED
    source:           str = "human"        # "human" / "llm_assisted" / "statistical"
    notes:            str = ""
    confidence:       float = 1.0          # < 1.0 for LLM-generated; 1.0 after human confirmation

    VALID_STATUSES = frozenset(["DRAFT", "APPROVED", "REJECTED"])

    def approve(self, notes: str = "") -> "ParameterOntologyEntry":
        return ParameterOntologyEntry(**{**self.__dict__,
            "review_status": "APPROVED", "confidence": 1.0,
            "notes": notes or self.notes})

    def reject(self, notes: str = "") -> "ParameterOntologyEntry":
        return ParameterOntologyEntry(**{**self.__dict__,
            "review_status": "REJECTED",
            "notes": notes or self.notes})

    def to_source7_patterns(self) -> List[str]:
        """把aliases转成Source7可用的正则pattern（保守的词组匹配）"""
        patterns = []
        for alias in self.aliases + self.prefill_patterns:
            # Lowercase, escape special characters, match as phrase
            safe = alias.lower().replace("(","\\(").replace(")","\\)")
            patterns.append(safe)
        return list(dict.fromkeys(patterns))  # dedup

    def to_dict(self) -> dict:
        return {
            "canonical_name":   self.canonical_name,
            "aliases":          self.aliases,
            "unit":             self.unit,
            "context":          self.context,
            "typical_operator": self.typical_operator,
            "prefill_patterns": self.prefill_patterns,
            "example_phrases":  self.example_phrases,
            "review_status":    self.review_status,
            "source":           self.source,
            "notes":            self.notes,
            "confidence":       self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ParameterOntologyEntry":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class FinanceParameterOntology:
    """
    Finance Domain的参数本体注册表。

    职责：
      1. 存储所有参数定义（包括DRAFT/APPROVED/REJECTED）
      2. 提供批量审核工作流
      3. 导出到Source7 _FINANCE_PARAM_MAP格式
      4. 导出到domains/finance/config.py的vocabulary格式
    """

    def __init__(self, entries: Optional[List[ParameterOntologyEntry]] = None):
        self._entries: Dict[str, ParameterOntologyEntry] = {}
        for e in (entries or []):
            self._entries[e.canonical_name] = e

    def add(self, entry: ParameterOntologyEntry) -> None:
        self._entries[entry.canonical_name] = entry

    def get(self, canonical_name: str) -> Optional[ParameterOntologyEntry]:
        return self._entries.get(canonical_name)

    def by_status(self, status: str) -> List[ParameterOntologyEntry]:
        return [e for e in self._entries.values() if e.review_status == status]

    def by_context(self, context: str) -> List[ParameterOntologyEntry]:
        return [e for e in self._entries.values() if e.context == context]

    def approve(self, canonical_name: str, notes: str = "") -> None:
        e = self._entries.get(canonical_name)
        if e:
            self._entries[canonical_name] = e.approve(notes)

    def reject(self, canonical_name: str, notes: str = "") -> None:
        e = self._entries.get(canonical_name)
        if e:
            self._entries[canonical_name] = e.reject(notes)

    def export_to_source7_param_map(self) -> List[tuple]:
        """
        导出为Source7 _FINANCE_PARAM_MAP格式。
        只包含APPROVED的条目。

        返回: [(regex_pattern, canonical_name), ...]
        可以直接append到prefill.py的_FINANCE_PARAM_MAP列表
        """
        result = []
        for entry in self.by_status("APPROVED"):
            # Build a single OR-regex from all aliases
            patterns = entry.to_source7_patterns()
            if patterns:
                regex = "|".join(f"(?:{p})" for p in patterns)
                result.append((regex, entry.canonical_name))
        return result

    def export_to_config_vocabulary(self) -> dict:
        """
        导出为FinancePackConfig兼容的vocabulary格式。
        可以直接写入domains/finance/config.py
        """
        approved = self.by_status("APPROVED")
        return {
            "param_names":  [e.canonical_name for e in approved],
            "param_aliases": {
                e.canonical_name: e.aliases
                for e in approved
            },
            "param_units": {
                e.canonical_name: e.unit
                for e in approved if e.unit
            },
            "param_contexts": {
                e.canonical_name: e.context
                for e in approved if e.context
            },
        }

    def summary(self) -> str:
        from collections import Counter
        status_counts   = Counter(e.review_status for e in self._entries.values())
        context_counts  = Counter(e.context for e in self._entries.values()
                                   if e.review_status == "APPROVED")
        lines = [
            f"FinanceParameterOntology: {len(self._entries)} entries",
            f"  DRAFT:    {status_counts.get('DRAFT', 0)}",
            f"  APPROVED: {status_counts.get('APPROVED', 0)}",
            f"  REJECTED: {status_counts.get('REJECTED', 0)}",
        ]
        if context_counts:
            lines.append("  Approved by context:")
            for ctx, n in sorted(context_counts.items()):
                lines.append(f"    {ctx:12} {n}")
        return "\n".join(lines)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            {"entries": [e.to_dict() for e in self._entries.values()]},
            indent=indent, ensure_ascii=False
        )

    @classmethod
    def from_json(cls, json_str: str) -> "FinanceParameterOntology":
        d = json.loads(json_str)
        return cls([ParameterOntologyEntry.from_dict(e) for e in d["entries"]])

    @classmethod
    def from_json_file(cls, path: str) -> "FinanceParameterOntology":
        with open(path) as f:
            return cls.from_json(f.read())

    def to_json_file(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_json())


# ── Pre-populated core finance parameter ontology (human-confirmed) ─────────────
# This is the starting point of the data-asset moat — parameter definitions confirmed by humans

CORE_FINANCE_ONTOLOGY = FinanceParameterOntology([

    # ── Execution layer ──────────────────────────────────────────────────────
    ParameterOntologyEntry(
        canonical_name="participation_rate",
        aliases=["participation rate", "参与率", "adv participation",
                  "participation limit", "adv limit"],
        unit="%", context="execution", typical_operator="max",
        prefill_patterns=["participation rate", "参与率", "adv participation"],
        example_phrases=["participation rate must not exceed 8%",
                          "参与率不超过ADV的8%"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="child_order_qty",
        aliases=["slice size", "clip size", "child order size",
                  "child order qty", "子单数量", "slice量",
                  "per order size", "order slice"],
        unit="shares", context="execution", typical_operator="max",
        prefill_patterns=["slice size", "clip size", "child order", "子单"],
        example_phrases=["slice size not to exceed 50k shares",
                          "child order单笔不超过5万股"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="order_notional",
        aliases=["notional limit", "order notional", "名义价值上限",
                  "notional cap", "max notional"],
        unit="USD", context="execution", typical_operator="max",
        prefill_patterns=["notional limit", "notional cap", "名义价值"],
        example_phrases=["notional limit $5M per order"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="min_fill_qty",
        aliases=["minimum fill", "min fill size", "minimum fill size",
                  "min fill", "最小成交量"],
        unit="shares", context="execution", typical_operator="min",
        prefill_patterns=["minimum fill", "min fill", "最小成交"],
        example_phrases=["minimum fill size: 1000 shares"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    # ── Risk / compliance layer ──────────────────────────────────────────────
    ParameterOntologyEntry(
        canonical_name="sector_concentration",
        aliases=["sector concentration", "concentration limit",
                  "sector limit", "板块集中度", "行业集中度"],
        unit="%", context="risk", typical_operator="max",
        prefill_patterns=["concentration limit", "sector concentration", "集中度"],
        example_phrases=["concentration limit 20% per sector"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="position_concentration",
        aliases=["single name position", "single stock limit",
                  "position concentration", "单股集中度", "个股限额"],
        unit="% of NAV", context="risk", typical_operator="max",
        prefill_patterns=["single name position", "single stock", "个股"],
        example_phrases=["single name position ≤ 5% of NAV"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="spread_bps",
        aliases=["spread", "bid-ask spread", "spread threshold",
                  "价差", "买卖价差"],
        unit="bps", context="risk", typical_operator="max",
        prefill_patterns=["spread threshold", "bid-ask spread", "价差"],
        example_phrases=["spread threshold: 5 bps", "spread不超过5bps"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="commission_rate",
        aliases=["commission", "commission cap", "commission rate",
                  "佣金", "手续费"],
        unit="%", context="risk", typical_operator="max",
        prefill_patterns=["commission cap", "commission rate", "佣金"],
        example_phrases=["commission cap 0.1%"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="implementation_shortfall",
        aliases=["shortfall", "implementation shortfall",
                  "IS tolerance", "shortfall tolerance", "冲击成本"],
        unit="bps", context="risk", typical_operator="max",
        prefill_patterns=["shortfall tolerance", "implementation shortfall"],
        example_phrases=["shortfall tolerance ≤ 15bps"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    # ── Futures / derivatives layer ───────────────────────────────────────────
    ParameterOntologyEntry(
        canonical_name="roll_window_days",
        aliases=["roll window", "roll within", "换月窗口", "roll期限"],
        unit="days", context="futures", typical_operator="max",
        prefill_patterns=["roll within", "roll window", "换月窗口"],
        example_phrases=["roll within 3 days of first notice"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="open_interest_pct",
        aliases=["open interest", "OI limit", "open interest limit",
                  "持仓量比例"],
        unit="%", context="futures", typical_operator="max",
        prefill_patterns=["open interest limit", "OI limit", "持仓量"],
        example_phrases=["open interest limit 15%"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="dv01_limit",
        aliases=["DV01", "notional DV01", "dollar duration", "利率敏感度"],
        unit="USD", context="futures", typical_operator="max",
        prefill_patterns=["DV01", "dollar duration", "notional DV01"],
        example_phrases=["notional DV01 ≤ $50k"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    # ── Portfolio management layer ────────────────────────────────────────────
    ParameterOntologyEntry(
        canonical_name="tracking_error_budget",
        aliases=["TE budget", "tracking error budget", "TE limit",
                  "跟踪误差预算", "TE上限"],
        unit="bps", context="portfolio", typical_operator="max",
        prefill_patterns=["TE budget", "tracking error budget", "跟踪误差预算"],
        example_phrases=["TE budget 30bps per day"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="factor_exposure",
        aliases=["factor exposure", "factor limit", "因子暴露"],
        unit="sigma", context="portfolio", typical_operator="max_abs",
        prefill_patterns=["factor exposure", "因子暴露"],
        example_phrases=["factor exposure ≤ 0.5 sigma"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="net_beta",
        aliases=["net beta", "beta exposure", "net beta exposure",
                  "贝塔暴露", "净贝塔"],
        unit="ratio", context="portfolio", typical_operator="range",
        prefill_patterns=["net beta", "beta exposure", "贝塔暴露"],
        example_phrases=["net beta exposure -0.1 to +0.1"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    # ── Pre-existing entries (keep aligned) ──────────────────────────────────
    ParameterOntologyEntry(
        canonical_name="daily_turnover",
        aliases=["daily turnover", "turnover", "单日换手", "日换手率",
                  "single day turnover"],
        unit="%", context="portfolio", typical_operator="max",
        prefill_patterns=["daily turnover", "turnover", "换手", "单日"],
        example_phrases=["daily turnover must not exceed 15%",
                          "单日turnover不超过15%"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),

    ParameterOntologyEntry(
        canonical_name="cash_buffer",
        aliases=["cash buffer", "cash reserve", "现金缓冲", "现金储备"],
        unit="%", context="portfolio", typical_operator="min",
        prefill_patterns=["cash buffer", "cash reserve", "现金缓冲"],
        example_phrases=["cash buffer must remain above 2%",
                          "现金缓冲不得低于2%"],
        review_status="APPROVED", source="human", confidence=1.0,
    ),
    # ══════════════════════════════════════════════════════════════════════
    # Fixed Income / Credit — LLM-assisted extraction, human-reviewed, v0.17.3
    # ══════════════════════════════════════════════════════════════════════
    ParameterOntologyEntry(
        canonical_name="yield_spread",
        aliases=["yield spread","spread to benchmark","credit spread",
                  "asset swap spread","z-spread","OAS"],
        unit="bps", context="fixed_income", typical_operator="max",
        prefill_patterns=["yield spread","credit spread","z-spread","OAS"],
        example_phrases=["yield spread must not exceed 200bps"],
        review_status="APPROVED", source="llm_assisted", confidence=0.88,
        notes="标准信用利差指标",
    ),
    ParameterOntologyEntry(
        canonical_name="duration",
        aliases=["duration","modified duration","effective duration",
                  "DV01 duration","久期","修正久期"],
        unit="years", context="fixed_income", typical_operator="max",
        prefill_patterns=["modified duration","effective duration","久期","duration limit"],
        example_phrases=["portfolio duration must not exceed 5 years","久期不得超过5年"],
        review_status="APPROVED", source="llm_assisted", confidence=0.92,
        notes="债券组合久期标准指标",
    ),
    ParameterOntologyEntry(
        canonical_name="convexity",
        aliases=["convexity","positive convexity","negative convexity","凸性"],
        unit="ratio", context="fixed_income", typical_operator="min",
        prefill_patterns=["convexity limit","convexity threshold","凸性"],
        example_phrases=["minimum convexity threshold 0.5"],
        review_status="APPROVED", source="llm_assisted", confidence=0.75,
        notes="凸性约束常见于利率对冲",
    ),
    ParameterOntologyEntry(
        canonical_name="credit_rating_floor",
        aliases=["credit rating","minimum rating","rating floor",
                  "investment grade","IG threshold","信用评级下限"],
        unit="grade", context="fixed_income", typical_operator="min",
        prefill_patterns=["minimum rating","rating floor","investment grade","信用评级"],
        example_phrases=["minimum credit rating BBB-","no below-investment-grade securities"],
        review_status="APPROVED", source="llm_assisted", confidence=0.91,
        notes="监管要求IG以上",
    ),
    ParameterOntologyEntry(
        canonical_name="bond_concentration",
        aliases=["single issuer concentration","issuer limit",
                  "issuer concentration","单一发行人集中度"],
        unit="%", context="fixed_income", typical_operator="max",
        prefill_patterns=["issuer limit","issuer concentration","单一发行人"],
        example_phrases=["single issuer limit 5% of portfolio"],
        review_status="APPROVED", source="llm_assisted", confidence=0.89,
        notes="单一发行人集中度标准",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # Options / Derivatives Greeks — LLM-assisted extraction, human-reviewed, v0.17.3
    # ══════════════════════════════════════════════════════════════════════
    ParameterOntologyEntry(
        canonical_name="delta",
        aliases=["delta","delta limit","net delta","delta exposure",
                  "delta中性","Delta对冲"],
        unit="ratio", context="options", typical_operator="max_abs",
        prefill_patterns=["delta limit","net delta","delta exposure"],
        example_phrases=["net delta must not exceed 0.3","delta中性不得超过±0.2"],
        review_status="APPROVED", source="llm_assisted", confidence=0.93,
        notes="期权Delta对冲基础",
    ),
    ParameterOntologyEntry(
        canonical_name="vega",
        aliases=["vega","vega exposure","vega limit","implied vol exposure","Vega风险"],
        unit="USD per 1% vol", context="options", typical_operator="max",
        prefill_patterns=["vega limit","vega exposure","Vega"],
        example_phrases=["vega exposure must not exceed $500k per 1% vol"],
        review_status="APPROVED", source="llm_assisted", confidence=0.87,
        notes="波动率暴露核心指标",
    ),
    ParameterOntologyEntry(
        canonical_name="gamma",
        aliases=["gamma","gamma exposure","gamma limit","Gamma风险"],
        unit="USD per 1% move", context="options", typical_operator="max",
        prefill_patterns=["gamma limit","gamma exposure"],
        example_phrases=["gamma not to exceed $100k per 1%"],
        review_status="APPROVED", source="llm_assisted", confidence=0.82,
        notes="Gamma风险管理",
    ),
    ParameterOntologyEntry(
        canonical_name="implied_vol",
        aliases=["implied volatility","IV","implied vol","vol surface","隐含波动率"],
        unit="%", context="options", typical_operator="range",
        prefill_patterns=["implied vol","implied volatility","IV range","隐含波动率"],
        example_phrases=["implied vol must be within 15% to 60%"],
        review_status="APPROVED", source="llm_assisted", confidence=0.86,
        notes="隐含波动率区间约束",
    ),
    ParameterOntologyEntry(
        canonical_name="theta",
        aliases=["theta","theta decay","daily theta","时间价值损耗"],
        unit="USD/day", context="options", typical_operator="max",
        prefill_patterns=["theta limit","theta decay","时间价值"],
        example_phrases=["daily theta must not exceed $50k"],
        review_status="APPROVED", source="llm_assisted", confidence=0.79,
        notes="时间价值损耗上限",
    ),

])


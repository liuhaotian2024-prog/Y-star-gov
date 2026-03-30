"""
External data adapters — standard interfaces for class-B gaps

B1: Sanctions entity list (SanctionsFeed)
B2: Trading calendar (TradingCalendar)
B3: Live risk data (RiskDataProvider)

Design principles:
  - Y* does not depend on these adapters (core functionality requires no external data)
  - Adapters are simply standardised fillers for ExternalContext
  - Real implementations are provided by the caller; these are interface definitions + mock implementations
"""
import json
import datetime
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional, Set

from ystar.kernel.dimensions import ExternalContext, TemporalContext


# ══════════════════════════════════════════════════════════════════════════════
# B1: Sanctions entity list adapter
# ══════════════════════════════════════════════════════════════════════════════

# ── FinanceExternalContext ────────────────────────────────────────────────────
# ExternalContext subclass that carries finance-domain runtime values.
# The kernel's ExternalContext only knows about temporal + custom;
# finance-specific fields live here in the domain layer where they belong.

@dataclass
class FinanceExternalContext(ExternalContext):
    """
    Finance-domain runtime context, injected once at session start.

    Extends the kernel's ExternalContext with fields specific to
    financial multi-agent execution systems.

    Fields:
        approved_venues:      exchange/venue whitelist for today (from compliance DB)
        approved_instruments: instrument allowlist for this session
        approved_brokers:     broker/dealer whitelist (from compliance DB)
        order_qty:            parent-order total quantity (shares/lots/contracts)
        order_notional:       parent-order notional value (currency units)
        risk_snapshot:        live risk data (RiskDataSnapshot), injected by risk system
    """
    approved_venues:      List[str]       = field(default_factory=list)
    approved_instruments: List[str]       = field(default_factory=list)
    approved_brokers:     List[str]       = field(default_factory=list)
    order_qty:            Optional[int]   = None
    order_notional:       Optional[float] = None
    risk_snapshot:        Optional[Any]   = None

    def has_risk_snapshot(self) -> bool:
        return self.risk_snapshot is not None

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "approved_venues":      self.approved_venues,
            "approved_instruments": self.approved_instruments,
            "approved_brokers":     self.approved_brokers,
            "order_qty":            self.order_qty,
            "order_notional":       self.order_notional,
        })
        if self.risk_snapshot is not None:
            try:
                d["risk_snapshot"] = self.risk_snapshot.to_external_context_fields()
            except AttributeError:
                d["risk_snapshot"] = str(self.risk_snapshot)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FinanceExternalContext":
        from ystar.kernel.dimensions import TemporalContext
        temporal_d = d.get("temporal")
        temporal   = TemporalContext.from_dict(temporal_d) if temporal_d else None
        return cls(
            temporal             = temporal,
            custom               = d.get("custom", {}),
            approved_venues      = d.get("approved_venues", []),
            approved_instruments = d.get("approved_instruments", []),
            approved_brokers     = d.get("approved_brokers", []),
            order_qty            = d.get("order_qty"),
            order_notional       = d.get("order_notional"),
        )


class SanctionsFeed:
    """
    Standard interface for the sanctions entity list.

    Real implementations must connect to:
      - OFAC SDN List (https://www.treasury.gov/ofac/downloads/sdn.xml)
      - EU Consolidated Sanctions List
      - UN Security Council Sanctions
      - CSRC regulatory watchlist

    Usage:
        feed = SanctionsFeed.from_ofac_csv("sdn.csv")
        ctx = ExternalContext(
            temporal=...,
            approved_venues=[...],
            # deny list automatically populated from the sanctions feed
        )
        # Or inject directly into FinanceDomainPack
        pack = FinanceDomainPack.from_dict(
            feed.to_finance_pack_config()
        )
    """

    def __init__(self, sanctioned_entities: Optional[List[str]] = None,
                  last_updated: str = ""):
        self._entities:    Set[str]  = set(sanctioned_entities or [])
        self.last_updated: str       = last_updated
        self.source:       str       = ""

    def add(self, entity: str) -> None:
        self._entities.add(entity.strip())

    def add_many(self, entities: List[str]) -> None:
        for e in entities:
            self.add(e)

    def is_sanctioned(self, entity: str) -> bool:
        """Return True if the entity is on the sanctions list (case-insensitive)."""
        return entity.strip().lower() in {e.lower() for e in self._entities}

    def entities(self) -> List[str]:
        return sorted(self._entities)

    def to_finance_pack_config(self) -> dict:
        """Convert to a format compatible with FinanceDomainPack.from_dict()."""
        return {"sanctioned_entities": self.entities()}

    @classmethod
    def from_list(cls, entities: List[str],
                   source: str = "manual") -> "SanctionsFeed":
        feed = cls(entities)
        feed.source = source
        feed.last_updated = datetime.date.today().isoformat()
        return feed

    @classmethod
    def from_json_file(cls, path: str) -> "SanctionsFeed":
        """Load from a JSON file with format: {"entities": [...], "last_updated": "...", "source": "..."}"""
        with open(path) as f:
            d = json.load(f)
        feed = cls(d.get("entities", []))
        feed.last_updated = d.get("last_updated", "")
        feed.source       = d.get("source", "json_file")
        return feed

    def to_json_file(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({
                "entities":     self.entities(),
                "last_updated": self.last_updated,
                "source":       self.source,
                "count":        len(self._entities),
            }, f, indent=2)

    @classmethod
    def from_ofac_csv(cls, path: str) -> "SanctionsFeed":
        """
        Load from an OFAC SDN CSV file (real implementation).
        CSV format reference: https://www.treasury.gov/ofac/downloads/sdn.csv

        Example caller implementation:
            feed = SanctionsFeed.from_ofac_csv("path/to/sdn.csv")
        """
        import csv
        entities = []
        try:
            with open(path, encoding="latin-1") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        entities.append(row[0].strip())
        except FileNotFoundError:
            raise FileNotFoundError(
                f"OFAC CSV not found: {path}\n"
                f"Download from: https://www.treasury.gov/ofac/downloads/sdn.csv"
            )
        feed = cls(entities)
        feed.source = f"OFAC_SDN:{path}"
        feed.last_updated = datetime.date.today().isoformat()
        return feed

    def __len__(self) -> int:
        return len(self._entities)

    def __repr__(self) -> str:
        return (f"SanctionsFeed(entities={len(self._entities)}, "
                f"source={self.source!r}, updated={self.last_updated})")


# ══════════════════════════════════════════════════════════════════════════════
# B2: Trading calendar
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradingCalendar:
    """
    Exchange calendar: fills the gap left by ScheduledWindow regarding public holidays.

    ScheduledWindow knows "10:00–11:30", but does not know whether today is a trading day.
    TradingCalendar provides that context.

    Usage:
        cal = TradingCalendar.nyse_2026()
        if cal.is_trading_day(date.today()):
            # Normal trading session; proceed
            ctx = ExternalContext(temporal=TemporalContext(...))
        else:
            # Non-trading day; execution should not proceed
            raise TradingDayError("Non-trading day")

        # Fetch today's trading hours
        session = cal.get_session("2026-03-20")
        sw = ScheduledWindow(start_time=session.open,
                              end_time=session.close)
    """
    name:           str
    timezone:       str   = "America/New_York"
    regular_open:   str   = "09:30"
    regular_close:  str   = "16:00"
    holidays:       List[str] = field(default_factory=list)   # YYYY-MM-DD
    early_close_days: Dict[str, str] = field(default_factory=dict)  # date→close_time

    def is_trading_day(self, date: "datetime.date") -> bool:
        """Return True if date is a trading day (excludes weekends and holidays)."""
        date_str = date.isoformat()
        if date.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return date_str not in self.holidays

    def get_close_time(self, date_str: str) -> str:
        """Return the closing time for the given date (accounts for early closes)."""
        return self.early_close_days.get(date_str, self.regular_close)

    def to_scheduled_window(self, date_str: Optional[str] = None,
                              timezone: Optional[str] = None) -> "ScheduledWindow":
        """
        Convert the trading calendar into a ScheduledWindow for direct use in HigherOrderContract.
        """
        from ystar.kernel.dimensions import ScheduledWindow
        _date = date_str or datetime.date.today().isoformat()
        _tz   = timezone or self.timezone
        close = self.get_close_time(_date)
        return ScheduledWindow(
            start_time=self.regular_open,
            end_time=close,
            timezone=_tz,
            description=f"{self.name} trading session {_date}",
        )

    def next_trading_day(self, from_date: "datetime.date") -> "datetime.date":
        """Return the next trading day after from_date."""
        d = from_date + datetime.timedelta(days=1)
        while not self.is_trading_day(d):
            d += datetime.timedelta(days=1)
        return d

    @classmethod
    def nyse_2026(cls) -> "TradingCalendar":
        """Static 2026 NYSE calendar (known holidays pre-populated)."""
        return cls(
            name="NYSE",
            timezone="America/New_York",
            regular_open="09:30",
            regular_close="16:00",
            holidays=[
                "2026-01-01",  # New Year's Day
                "2026-01-19",  # MLK Day
                "2026-02-16",  # Presidents Day
                "2026-04-03",  # Good Friday
                "2026-05-25",  # Memorial Day
                "2026-07-03",  # Independence Day (observed)
                "2026-09-07",  # Labor Day
                "2026-11-26",  # Thanksgiving
                "2026-12-25",  # Christmas
            ],
            early_close_days={
                "2026-07-02": "13:00",  # Day before Independence Day
                "2026-11-27": "13:00",  # Day after Thanksgiving
                "2026-12-24": "13:00",  # Christmas Eve
            },
        )

    @classmethod
    def sse_2026(cls) -> "TradingCalendar":
        """Static 2026 Shanghai Stock Exchange (SSE) calendar."""
        return cls(
            name="SSE",
            timezone="Asia/Shanghai",
            regular_open="09:30",
            regular_close="15:00",
            holidays=[
                "2026-01-01",  # New Year's Day
                "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",  # Spring Festival (Chinese New Year)
                "2026-04-05",  # Qingming Festival
                "2026-05-01",  # Labour Day
                "2026-06-19",  # Dragon Boat Festival
                "2026-09-26",  # Mid-Autumn Festival
                "2026-10-01", "2026-10-02", "2026-10-05",  # National Day (Golden Week)
            ],
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "timezone": self.timezone,
                "regular_open": self.regular_open, "regular_close": self.regular_close,
                "holidays": self.holidays, "early_close_days": self.early_close_days}

    @classmethod
    def from_dict(cls, d: dict) -> "TradingCalendar":
        return cls(**d)

    @classmethod
    def from_json_file(cls, path: str) -> "TradingCalendar":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    # ── B2: pandas_market_calendars integration ───────────────────────────────

    @classmethod
    def from_market_calendar(
        cls,
        exchange: str,
        year:     int,
        *,
        local_tz: Optional[str] = None,
    ) -> "TradingCalendar":
        """
        Build a TradingCalendar from a live pandas_market_calendars feed.

        Requires ``pandas_market_calendars`` to be installed::

            pip install pandas_market_calendars

        Args:
            exchange: Exchange code recognised by pandas_market_calendars,
                      e.g. "NYSE", "NASDAQ", "LSE", "SSE", "HKEX", "EUREX".
                      Call ``pandas_market_calendars.get_calendar_names()`` for
                      the full list.
            year:     Calendar year to load (e.g. 2026).
            local_tz: Override the local timezone used for open/close times.
                      Defaults to the exchange's own timezone from _EXCHANGE_TZ,
                      or UTC if the exchange is not in the mapping.

        Returns:
            TradingCalendar — fully populated with real holidays and early-close
            days for the requested year.

        Raises:
            ImportError:  pandas_market_calendars is not installed.
            ValueError:   exchange code is not recognised by the library.
        """
        try:
            import pandas_market_calendars as mcal
        except ImportError as exc:
            raise ImportError(
                "pandas_market_calendars is required for TradingCalendar.from_market_calendar(). "
                "Install it with: pip install pandas_market_calendars"
            ) from exc

        available = mcal.get_calendar_names()
        if exchange not in available:
            raise ValueError(
                f"Exchange '{exchange}' is not recognised by pandas_market_calendars. "
                f"Available exchanges: {sorted(available)}"
            )

        cal = mcal.get_calendar(exchange)
        tz  = local_tz or cls._EXCHANGE_TZ.get(exchange, "UTC")

        # ── Holidays ──────────────────────────────────────────────────────────
        holidays = [
            str(d)[:10]
            for d in cal.holidays().holidays
            if str(d)[:4] == str(year)
        ]

        # ── Schedule (open / close per session) ───────────────────────────────
        start = f"{year}-01-01"
        end   = f"{year}-12-31"
        schedule = cal.schedule(start_date=start, end_date=end)

        # Derive regular open/close from the most common session times
        import collections
        open_counter  = collections.Counter()
        close_counter = collections.Counter()
        for _, row in schedule.iterrows():
            o = row["market_open"].tz_convert(tz).strftime("%H:%M")
            c = row["market_close"].tz_convert(tz).strftime("%H:%M")
            open_counter[o]  += 1
            close_counter[c] += 1

        regular_open  = open_counter.most_common(1)[0][0]  if open_counter  else "09:30"
        regular_close = close_counter.most_common(1)[0][0] if close_counter else "16:00"

        # ── Early-close days ──────────────────────────────────────────────────
        early = cal.early_closes(schedule)
        early_close_days: Dict[str, str] = {}
        for ts, row in early.iterrows():
            date_str   = str(ts)[:10]
            close_time = row["market_close"].tz_convert(tz).strftime("%H:%M")
            if close_time != regular_close:
                early_close_days[date_str] = close_time

        return cls(
            name             = exchange,
            timezone         = tz,
            regular_open     = regular_open,
            regular_close    = regular_close,
            holidays         = sorted(holidays),
            early_close_days = early_close_days,
        )


# Class-level constant — defined outside the dataclass to avoid mutable-default error.
# Maps exchange code → local timezone string.
TradingCalendar._EXCHANGE_TZ = {
    "NYSE":   "America/New_York",
    "NASDAQ": "America/New_York",
    "LSE":    "Europe/London",
    "TSX":    "America/Toronto",
    "SSE":    "Asia/Shanghai",
    "HKEX":   "Asia/Hong_Kong",
    "EUREX":  "Europe/Berlin",
}


# ══════════════════════════════════════════════════════════════════════════════
# B3: Live risk data provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RiskDataSnapshot:
    """
    Single risk data snapshot: the caller fetches this from their risk system and injects it into ExternalContext.

    This solves the B3 problem: Y* does not need to connect to a risk system;
    the caller provides a single snapshot at session start.

    Usage:
        # Caller fetches this from their internal risk system
        snapshot = RiskDataSnapshot(
            adv_data={"XYZ": 5_000_000, "ABC": 2_000_000},
            current_var=0.018,
            var_limit=0.020,
            margin_available=0.75,
            timestamp=time.time(),
        )
        ctx = ExternalContext(
            temporal=...,
            approved_venues=[...],
            risk_snapshot=snapshot,    # inject
        )
    """
    adv_data:           Dict[str, float] = field(default_factory=dict)   # ticker→ADV
    current_var:        Optional[float]  = None
    var_limit:          Optional[float]  = None
    margin_available:   Optional[float]  = None
    margin_used:        Optional[float]  = None
    gross_exposure:     Optional[float]  = None
    net_exposure:       Optional[float]  = None
    timestamp:          float            = 0.0
    source:             str              = ""

    def get_adv_participation_limit(self, ticker: str,
                                     max_pct: float = 0.08) -> Optional[float]:
        """Return the ADV-based participation-rate limit (shares) for ticker; None if no ADV data."""
        adv = self.adv_data.get(ticker)
        return adv * max_pct if adv else None

    def var_headroom_pct(self) -> Optional[float]:
        """Return the remaining VaR headroom as a fraction (0–1); None if data is unavailable."""
        if self.current_var and self.var_limit:
            return max(0.0, 1.0 - self.current_var / self.var_limit)
        return None

    def to_external_context_fields(self) -> dict:
        """Convert to a dict of fields compatible with ExternalContext.custom."""
        d = {}
        if self.adv_data:
            d["adv_data"] = self.adv_data
        if self.current_var is not None:
            d["current_var"]  = self.current_var
            d["var_limit"]    = self.var_limit
            d["var_headroom"] = self.var_headroom_pct()
        if self.margin_available is not None:
            d["margin_available"] = self.margin_available
            d["margin_used"]      = self.margin_used
        return d

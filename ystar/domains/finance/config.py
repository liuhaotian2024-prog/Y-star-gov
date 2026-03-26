"""
Finance Domain Pack external configuration

Allows business teams to configure the domain pack via YAML/JSON
without modifying any Python code.

Usage:
  # Load from YAML file
  pack = FinanceDomainPack.from_yaml("config/finance_pack.yaml")

  # Load from dict
  pack = FinanceDomainPack.from_dict({
    "sanctioned_entities": ["NewEntity1", "NewEntity2"],
    "max_trade_amount": 3_000_000,
    "participation_rate_limit": 0.15,
  })

Supports overriding:
  - pack_version:        semver string identifying the config schema version
  - sanctioned_entities: sanctions / blocklist entities (maintained by compliance team)
  - dangerous_commands:  dangerous command prefixes (maintained by security team)
  - role_limits:         numeric limits per role (maintained by risk team)
  - extra_deny:          additional deny keywords (extensible)
  - risk_thresholds:     optional risk-metric thresholds (maintained by risk team)
"""
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ── Schema descriptor ─────────────────────────────────────────────────────────
# Maps field name → (expected Python type, description)
_FIELD_SCHEMA: Dict[str, tuple] = {
    "pack_version":        (str,  "SemVer string, e.g. '1.0.0'"),
    "sanctioned_entities": (list, "List[str] of sanctioned entity identifiers"),
    "dangerous_commands":  (list, "List[str] of dangerous command prefixes"),
    "extra_deny":          (list, "List[str] of additional deny keywords"),
    "role_limits":         (dict, "Dict[role_name, Dict[limit_key, value]]"),
    "risk_thresholds":     (dict, "Dict[metric_name, float threshold]"),
}

_CURRENT_SCHEMA_VERSION = "1.1"   # bumped when new required fields are added


@dataclass
class FinancePackConfig:
    """
    External configuration model for the Finance Domain Pack.

    Business teams modify this configuration file without touching Python code.

    Schema validation is applied at load time:
    - Type mismatches raise TypeError with a descriptive message.
    - Unknown keys emit a warning (not an error) to allow forward-compatible configs.
    - pack_version is stored for auditability; a mismatch does not block loading.
    """
    # ── Version / auditability ────────────────────────────────────────────────
    pack_version:       str  = "1.0.0"   # config schema version

    # Maintained by compliance team: sanctioned / blocklisted entities
    sanctioned_entities: List[str] = field(default_factory=list)

    # Maintained by security team: dangerous command prefixes
    dangerous_commands: List[str] = field(default_factory=lambda: [
        "force_execute ", "bypass_compliance ", "copy_delegation ",
    ])

    # Additional deny keywords (can be appended at any time)
    extra_deny: List[str] = field(default_factory=list)

    # Numeric limits per role
    role_limits: Dict[str, Dict] = field(default_factory=lambda: {
        "head_trader":     {"max_amount": 10_000_000, "max_units": 5},
        "risk_manager":    {"max_amount": 2_000_000,  "max_units": 2},
        "execution_agent": {"max_amount": 500_000,    "max_units": 0.5},
        "settlement_agent":{"max_amount": 500_000},
    })

    # Optional risk-metric thresholds
    risk_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "settlement_risk":        0.8,
        "kyc_score_min":          0.5,
        "venue_concentration_max":0.6,
    })

    # ── Schema validation ─────────────────────────────────────────────────────

    def validate(self) -> List[str]:
        """
        Validate field types against _FIELD_SCHEMA.

        Returns a list of error strings (empty = valid).
        Does NOT raise; call ``validate_or_raise()`` if you want an exception.
        """
        errors = []
        for fname, (expected_type, desc) in _FIELD_SCHEMA.items():
            val = getattr(self, fname, None)
            if val is None:
                continue
            if not isinstance(val, expected_type):
                errors.append(
                    f"Field '{fname}': expected {expected_type.__name__}, "
                    f"got {type(val).__name__}. ({desc})"
                )
        return errors

    def validate_or_raise(self) -> "FinancePackConfig":
        """Raise TypeError if validation fails. Returns self for chaining."""
        errors = self.validate()
        if errors:
            raise TypeError(
                f"FinancePackConfig schema validation failed "
                f"({len(errors)} error(s)):\n" +
                "\n".join(f"  • {e}" for e in errors)
            )
        return self

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "FinancePackConfig":
        """
        Load from a dictionary (supports partial override; unspecified fields use defaults).

        Unknown keys are silently ignored (forward-compatible).
        Type errors raise TypeError after full loading.
        """
        import warnings as _w
        cfg = cls()
        unknown = []
        for key, val in d.items():
            if hasattr(cfg, key):
                setattr(cfg, key, val)
            else:
                unknown.append(key)
        if unknown:
            _w.warn(
                f"FinancePackConfig: unknown config keys {unknown} — ignored. "
                f"Known fields: {list(_FIELD_SCHEMA)}",
                UserWarning,
                stacklevel=2,
            )
        cfg.validate_or_raise()
        return cfg

    @classmethod
    def from_json(cls, json_str: str) -> "FinancePackConfig":
        """Load from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_yaml_file(cls, path: str) -> "FinancePackConfig":
        """Load from a YAML file (requires pyyaml: pip install pyyaml)."""
        try:
            import yaml
            with open(path) as f:
                return cls.from_dict(yaml.safe_load(f))
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML config: pip install pyyaml"
            )
        except FileNotFoundError:
            raise FileNotFoundError(f"Config file not found: {path}")

    @classmethod
    def from_json_file(cls, path: str) -> "FinancePackConfig":
        """Load from a JSON file."""
        with open(path) as f:
            return cls.from_dict(json.load(f))

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "pack_version":        self.pack_version,
            "sanctioned_entities": self.sanctioned_entities,
            "dangerous_commands":  self.dangerous_commands,
            "extra_deny":          self.extra_deny,
            "role_limits":         self.role_limits,
            "risk_thresholds":     self.risk_thresholds,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialise to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

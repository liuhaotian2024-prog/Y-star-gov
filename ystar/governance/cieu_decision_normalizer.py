"""
ystar.governance.cieu_decision_normalizer
==========================================

Normalizes raw CIEU ``decision`` field values to a canonical 8-bucket set.

The ``decision`` column in ``cieu_events`` contains 20+ distinct raw values
including case variance (``ALLOW`` vs ``allow``), near-synonyms
(``warn`` vs ``warning``), and embedded JSON corruption.  This module maps
every known raw value to one of eight canonical values:

    allow | deny | escalate | rewrite | route | info | unknown | escape

The ``route`` bucket captures routing/dispatch decisions (ROUTING_GATE_CHECK,
CTO_BROKER dispatches) that were previously misclassified under ``rewrite``.
Per Maya CZL-REWRITE-AUDIT (2026-04-19): 46 ROUTING_GATE_CHECK + 3 CTO_BROKER
dispatch events are routing decisions, not corrective rewrites.

The ``escape`` bucket captures events where a violation was detected but the
action was allowed through (warn+passed=0 semantics, and allow+passed=0
rare cases).  This is distinct from ``escalate`` which implies the violation
was flagged for human/system review.

Design constraints (CTO Ruling CZL-BRAIN-BIPARTITE Q2/Q5, Board 2026-04-19):
  - Pure function, unit-testable without a database.
  - Case-insensitive matching.
  - Typo tolerance via stripped/lowered lookup.
  - Embedded JSON fragments map to ``unknown``.
  - Original ``decision`` column is NEVER modified (audit trail preserved).
  - v2: normalize() accepts both raw_decision AND passed flag for
    context-dependent classification (warn+passed=0 -> escape).

Author: Leo Chen (eng-kernel)
Date: 2026-04-19
Updated: 2026-04-19 (v2: escape bucket + passed-aware normalization)
Updated: 2026-04-19 (v3: route bucket split from rewrite per CZL-REWRITE-AUDIT)
Spec: reports/ceo/governance/cieu_bipartite_learning_v1.md Section 2
Ruling: reports/cto/CZL-BRAIN-BIPARTITE-ruling.md Q2/Q5
Board: 2026-04-19 Finding 1 (warn is escape, not escalate)
"""

from __future__ import annotations

from typing import FrozenSet

# ── Canonical value set ───────────────────────────────────────────────
CANONICAL_VALUES: FrozenSet[str] = frozenset({
    "allow", "deny", "escalate", "rewrite", "route", "info", "unknown", "escape",
})

# ── Raw-to-canonical mapping ─────────────────────────────────────────
# Keys are lowercase.  The normalize() function lowercases input before
# lookup, providing case-insensitive matching for free.
#
# v2 NOTE: warn/warning are NO LONGER in this static map.  They require
# the ``passed`` flag to disambiguate (warn+passed=0 -> escape,
# warn+passed=1 -> allow).  See _PASSED_DEPENDENT_KEYS below.
_RAW_TO_CANONICAL: dict[str, str] = {
    # allow bucket
    "allow":    "allow",
    "accept":   "allow",
    "approved": "allow",
    "pass":     "allow",
    "passed":   "allow",

    # deny bucket
    "deny":     "deny",
    "reject":   "deny",
    "blocked":  "deny",
    "denied":   "deny",

    # escalate bucket (v2: warn/warning removed -- now passed-dependent)
    "escalate": "escalate",

    # rewrite bucket -- corrective rewrites (auto_rewrite.py transforms)
    "rewrite":  "rewrite",

    # route bucket -- routing/dispatch decisions (split from rewrite v3)
    # Per Maya CZL-REWRITE-AUDIT: 46 ROUTING_GATE_CHECK + 3 CTO_BROKER
    # dispatch events were misclassified as rewrite; they are routing decisions.
    "route":    "route",
    "dispatch": "route",

    # info bucket -- non-supervisory signals
    "info":     "info",
    "complete": "info",
    "log":      "info",

    # unknown bucket -- error / corruption / unrecognized
    "unknown":  "unknown",
    "error":    "unknown",
    "partial":  "unknown",
}

# Keys that require the ``passed`` flag for correct classification.
# When passed is None (unknown), these fall back to ``escalate`` (v1 compat).
_PASSED_DEPENDENT_KEYS: frozenset[str] = frozenset({"warn", "warning"})

# Keys in the allow family that become escape when passed=0
_ALLOW_FAMILY_KEYS: frozenset[str] = frozenset({
    "allow", "accept", "approved", "pass", "passed",
})


def normalize(raw_decision: str, passed: int | None = None) -> str:
    """
    Map a raw ``decision`` value to one of the 8 canonical values.

    v2 signature: accepts optional ``passed`` flag (0 or 1) from the
    ``passed`` column of ``cieu_events``.  When ``passed`` is provided,
    context-dependent rules apply:

    - warn/warning + passed=0 -> ``escape`` (violation detected, action allowed)
    - warn/warning + passed=1 -> ``allow`` (warned but passed check)
    - warn/warning + passed=None -> ``escalate`` (v1 backwards compatibility)
    - allow-family + passed=0 -> ``escape`` (rare allow-but-fail)
    - All other combinations -> standard lookup

    Rules applied in order:
    1. Strip whitespace, lowercase.
    2. If the result starts with ``{`` or ``[``, it is an embedded JSON
       fragment (corruption) -> ``"unknown"``.
    3. Check passed-dependent keys (warn/warning).
    4. Check allow-family + passed=0 escape path.
    5. Direct lookup in ``_RAW_TO_CANONICAL``.
    6. If no match, return ``"unknown"`` (safe default).

    This function is pure and deterministic -- no IO, no side effects.

    >>> normalize("ALLOW")
    'allow'
    >>> normalize("warn", passed=0)
    'escape'
    >>> normalize("warn", passed=1)
    'allow'
    >>> normalize("warn")
    'escalate'
    >>> normalize('{"last_cieu_age_secs": 4}')
    'unknown'
    >>> normalize("   Warning  ", passed=0)
    'escape'
    """
    if not raw_decision:
        return "unknown"

    cleaned = raw_decision.strip().lower()

    if not cleaned:
        return "unknown"

    # Embedded JSON detection (corruption pattern from empirical data)
    if cleaned.startswith("{") or cleaned.startswith("["):
        return "unknown"

    # ── Passed-dependent: warn/warning ──────────────────────────────
    if cleaned in _PASSED_DEPENDENT_KEYS:
        if passed is None:
            # v1 backwards compatibility: no passed info -> escalate
            return "escalate"
        if passed == 0:
            # warn + failed check = escape (violation detected, action allowed)
            return "escape"
        # passed == 1 (or any truthy): warned but still passed
        return "allow"

    # ── Allow-family escape: allow/accept/etc + passed=0 ────────────
    if passed == 0 and cleaned in _ALLOW_FAMILY_KEYS:
        return "escape"

    return _RAW_TO_CANONICAL.get(cleaned, "unknown")


def provenance_for_agent(agent_id: str) -> str | None:
    """
    Determine provenance tag for a CIEU event based on agent_id.

    Per CTO Ruling Q6 (self-referential guard):
      - agent_id starting with ``system:`` -> ``'system:brain'``
      - all others -> ``None``

    This tag is used by the bipartite loader to EXCLUDE system-generated
    events from the training corpus (WHERE agent_id NOT LIKE 'system:%').
    """
    if not agent_id:
        return None
    if agent_id.startswith("system:"):
        return "system:brain"
    return None

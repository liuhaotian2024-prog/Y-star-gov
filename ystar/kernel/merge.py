# Layer: Foundation
#
# ystar -- Human Intent to Machine Predicate
# Copyright (C) 2026 Haotian Liu
# MIT License
#
# v0.48.0
# Three-layer contract merge with monotonicity guarantee.
"""
Three-layer constraint merge for runtime governance.

Architecture:
  Layer 1 (session)       -- User-authoritative static baseline.  Immutable upper bound.
  Layer 2 (runtime_deny)  -- Path-B tightening.  Can only be stricter than session.
  Layer 3 (runtime_relax) -- Metalearning relaxation.  Can loosen deny but never exceed session.

Monotonicity invariant:
  For every dimension d:  session[d] >= merged[d]
  (where >= means "at least as permissive as")

  Equivalently: the merged contract is never more permissive than session.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from ystar.kernel.dimensions import IntentContract


def merge_contracts(
    session: Optional[IntentContract],
    deny: Optional[IntentContract] = None,
    relax: Optional[IntentContract] = None,
) -> IntentContract:
    """
    Merge three constraint layers with monotonicity guarantee.

    Parameters
    ----------
    session : IntentContract or None
        Layer 1 -- the user-authoritative baseline.  This is the immutable
        upper bound of permissiveness.  If None, returns an empty contract.
    deny : IntentContract or None
        Layer 2 -- runtime deny (Path B).  Can only tighten session; any
        loosening attempt is silently ignored.
    relax : IntentContract or None
        Layer 3 -- runtime relax (metalearning).  Can only undo deny's
        tightening; cannot exceed session boundary.

    Returns
    -------
    IntentContract
        The merged contract.  Guaranteed to be no more permissive than session.

    Dimension merge rules
    ---------------------
    Blacklist dimensions (deny, deny_commands, field_deny):
      - deny ADDS items  -> union(session, deny)
      - relax REMOVES deny-added items -> but session baseline items are preserved
      Result: session items + (deny items - relax items)

    Whitelist dimensions (only_paths, only_domains):
      - deny NARROWS the whitelist (must be subset of session)
      - relax WIDENS back toward session (must stay within session)
      Result: items that are in deny's narrowed set PLUS relax additions,
              but never exceeding session boundary

    Logic predicate dimensions (invariant, postcondition, optional_invariant):
      - deny ADDS predicates
      - relax REMOVES deny-added predicates (session predicates are preserved)

    Numeric range dimension (value_range):
      - deny TIGHTENS (raise min, lower max)
      - relax LOOSENS but never beyond session bounds

    Obligation timing dimension (obligation_timing):
      - deny TIGHTENS (shorter deadlines)
      - relax LOOSENS but never beyond session limits
    """
    # --- Base case: no session means no constraints ---
    if session is None:
        return IntentContract()

    if deny is None and relax is None:
        return _clone_contract(session)

    # Effective deny/relax (empty contracts if None)
    d = deny if deny is not None else IntentContract()
    r = relax if relax is not None else IntentContract()

    return IntentContract(
        deny=_merge_blacklist(session.deny, d.deny, r.deny),
        deny_commands=_merge_blacklist(
            session.deny_commands, d.deny_commands, r.deny_commands
        ),
        only_paths=_merge_whitelist_paths(
            session.only_paths, d.only_paths, r.only_paths
        ),
        only_domains=_merge_whitelist_domains(
            session.only_domains, d.only_domains, r.only_domains
        ),
        invariant=_merge_predicates(
            session.invariant, d.invariant, r.invariant
        ),
        optional_invariant=_merge_predicates(
            session.optional_invariant, d.optional_invariant, r.optional_invariant
        ),
        postcondition=_merge_predicates(
            session.postcondition, d.postcondition, r.postcondition
        ),
        field_deny=_merge_field_deny(
            session.field_deny, d.field_deny, r.field_deny
        ),
        value_range=_merge_value_range(
            session.value_range, d.value_range, r.value_range
        ),
        obligation_timing=_merge_obligation_timing(
            session.obligation_timing, d.obligation_timing, r.obligation_timing
        ),
        name=session.name,
    )


# ---------------------------------------------------------------------------
# Blacklist merge: deny, deny_commands
# ---------------------------------------------------------------------------

def _merge_blacklist(
    session_items: List[str],
    deny_items: List[str],
    relax_items: List[str],
) -> List[str]:
    """
    Blacklist merge.

    1. Start with session baseline (immutable).
    2. Add deny items (tightening).
    3. Relax can remove deny-added items, but NEVER session items.
    """
    session_set: Set[str] = set(session_items)
    deny_added: Set[str] = set(deny_items) - session_set
    relax_set: Set[str] = set(relax_items)

    # deny-added items that relax wants to remove
    surviving_deny = deny_added - relax_set

    # Final: session baseline + surviving deny additions
    merged = list(dict.fromkeys(session_items + sorted(surviving_deny)))
    return merged


# ---------------------------------------------------------------------------
# Whitelist merge: only_paths
# ---------------------------------------------------------------------------

def _is_path_within(child: str, parent: str) -> bool:
    """Check if child path is within parent path (prefix match with /)."""
    cn = child.rstrip("/") + "/"
    pn = parent.rstrip("/") + "/"
    return cn.startswith(pn)


def _merge_whitelist_paths(
    session_paths: List[str],
    deny_paths: List[str],
    relax_paths: List[str],
) -> List[str]:
    """
    Whitelist path merge.

    - If session has no whitelist, result is empty (no restriction).
    - deny NARROWS: only keeps deny paths that are within session paths.
    - relax WIDENS: adds paths back, but only if within session boundary.

    If deny is empty, session is used as-is.
    """
    if not session_paths:
        return []

    # Step 1: Apply deny narrowing
    if deny_paths:
        # Only keep deny paths that are within at least one session path
        after_deny = [
            p for p in deny_paths
            if any(_is_path_within(p, sp) for sp in session_paths)
        ]
        # If deny produced an empty list (all invalid), fall back to session
        if not after_deny:
            after_deny = list(session_paths)
    else:
        after_deny = list(session_paths)

    # Step 2: Apply relax widening (within session boundary)
    if relax_paths:
        result_set = set(after_deny)
        for rp in relax_paths:
            # Relax path must be within at least one session path
            if any(_is_path_within(rp, sp) for sp in session_paths):
                result_set.add(rp)
        return list(dict.fromkeys(after_deny + [
            rp for rp in relax_paths
            if rp in result_set and rp not in after_deny
        ]))

    return after_deny


# ---------------------------------------------------------------------------
# Whitelist merge: only_domains
# ---------------------------------------------------------------------------

def _merge_whitelist_domains(
    session_domains: List[str],
    deny_domains: List[str],
    relax_domains: List[str],
) -> List[str]:
    """
    Whitelist domain merge.

    - deny NARROWS: removes domains from session whitelist.
    - relax WIDENS: adds domains back, but only if in session set.
    """
    if not session_domains:
        return []

    session_set = set(session_domains)

    # Step 1: Apply deny narrowing
    if deny_domains:
        # deny_domains specifies the narrowed whitelist (must be subset of session)
        after_deny = [d for d in deny_domains if d in session_set]
        if not after_deny:
            after_deny = list(session_domains)
    else:
        after_deny = list(session_domains)

    # Step 2: Apply relax widening (within session boundary)
    if relax_domains:
        after_deny_set = set(after_deny)
        for rd in relax_domains:
            if rd in session_set and rd not in after_deny_set:
                after_deny.append(rd)
                after_deny_set.add(rd)

    return after_deny


# ---------------------------------------------------------------------------
# Predicate merge: invariant, postcondition, optional_invariant
# ---------------------------------------------------------------------------

def _merge_predicates(
    session_preds: List[str],
    deny_preds: List[str],
    relax_preds: List[str],
) -> List[str]:
    """
    Predicate merge.  Same pattern as blacklist: deny adds, relax removes
    deny-added predicates.  Session predicates are immutable.
    """
    session_set = set(session_preds)
    deny_added = set(deny_preds) - session_set
    relax_set = set(relax_preds)

    surviving_deny = deny_added - relax_set
    merged = list(dict.fromkeys(session_preds + sorted(surviving_deny)))
    return merged


# ---------------------------------------------------------------------------
# Value range merge
# ---------------------------------------------------------------------------

def _merge_value_range(
    session_vr: Dict[str, Dict],
    deny_vr: Dict[str, Dict],
    relax_vr: Dict[str, Dict],
) -> Dict[str, Dict]:
    """
    Numeric range merge.

    For each parameter:
    1. Start with session bounds (immutable upper bound of permissiveness).
    2. deny tightens: raise min, lower max.
    3. relax loosens: lower min, raise max -- but never beyond session.
    """
    all_params = set(session_vr) | set(deny_vr) | set(relax_vr)
    result: Dict[str, Dict] = {}

    for param in sorted(all_params):
        s_bounds = session_vr.get(param, {})
        d_bounds = deny_vr.get(param, {})
        r_bounds = relax_vr.get(param, {})

        s_min = s_bounds.get("min")
        s_max = s_bounds.get("max")

        # --- Apply deny tightening ---
        # deny can only make bounds stricter (raise min, lower max)
        d_min = d_bounds.get("min")
        d_max = d_bounds.get("max")

        if s_min is not None and d_min is not None:
            after_deny_min = max(float(s_min), float(d_min))
        elif d_min is not None:
            after_deny_min = float(d_min)
        elif s_min is not None:
            after_deny_min = float(s_min)
        else:
            after_deny_min = None

        if s_max is not None and d_max is not None:
            after_deny_max = min(float(s_max), float(d_max))
        elif d_max is not None:
            # deny adds a max where session had none -- this is tightening
            after_deny_max = float(d_max)
        elif s_max is not None:
            after_deny_max = float(s_max)
        else:
            after_deny_max = None

        # --- Apply relax loosening (bounded by session) ---
        r_min = r_bounds.get("min")
        r_max = r_bounds.get("max")

        final_min = after_deny_min
        final_max = after_deny_max

        if r_min is not None and after_deny_min is not None:
            # relax wants to lower min -- but not below session min
            proposed_min = float(r_min)
            session_floor = float(s_min) if s_min is not None else proposed_min
            final_min = max(session_floor, min(after_deny_min, proposed_min))

        if r_max is not None and after_deny_max is not None:
            # relax wants to raise max -- but not above session max
            proposed_max = float(r_max)
            session_ceiling = float(s_max) if s_max is not None else proposed_max
            final_max = min(session_ceiling, max(after_deny_max, proposed_max))

        bounds: Dict = {}
        if final_min is not None:
            bounds["min"] = final_min
        if final_max is not None:
            bounds["max"] = final_max
        if bounds:
            result[param] = bounds

    return result


# ---------------------------------------------------------------------------
# Field deny merge
# ---------------------------------------------------------------------------

def _merge_field_deny(
    session_fd: Dict[str, List[str]],
    deny_fd: Dict[str, List[str]],
    relax_fd: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """
    Field deny merge.  Per-field blacklist, same pattern as deny/deny_commands.
    """
    all_fields = set(session_fd) | set(deny_fd) | set(relax_fd)
    result: Dict[str, List[str]] = {}

    for field_name in sorted(all_fields):
        s_items = session_fd.get(field_name, [])
        d_items = deny_fd.get(field_name, [])
        r_items = relax_fd.get(field_name, [])

        merged = _merge_blacklist(s_items, d_items, r_items)
        if merged:
            result[field_name] = merged

    return result


# ---------------------------------------------------------------------------
# Obligation timing merge
# ---------------------------------------------------------------------------

def _merge_obligation_timing(
    session_ot: Dict[str, float],
    deny_ot: Dict[str, float],
    relax_ot: Dict[str, float],
) -> Dict[str, float]:
    """
    Obligation timing merge.

    Smaller deadline = stricter (less time allowed).
    - deny tightens: use min(session, deny) per key.
    - relax loosens: raise toward session, but never exceed session.
    """
    all_keys = set(session_ot) | set(deny_ot) | set(relax_ot)
    result: Dict[str, float] = {}

    for key in sorted(all_keys):
        s_val = session_ot.get(key)
        d_val = deny_ot.get(key)
        r_val = relax_ot.get(key)

        # Apply deny: tighten (shorter deadline)
        if s_val is not None and d_val is not None:
            after_deny = min(s_val, d_val)
        elif d_val is not None:
            after_deny = d_val
        elif s_val is not None:
            after_deny = s_val
        else:
            continue

        # Apply relax: loosen (longer deadline) but not beyond session
        if r_val is not None:
            session_ceiling = s_val if s_val is not None else r_val
            final = min(session_ceiling, max(after_deny, r_val))
        else:
            final = after_deny

        result[key] = final

    return result


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _clone_contract(c: IntentContract) -> IntentContract:
    """Deep-copy an IntentContract (constraint fields only)."""
    return IntentContract(
        deny=list(c.deny),
        only_paths=list(c.only_paths),
        deny_commands=list(c.deny_commands),
        only_domains=list(c.only_domains),
        invariant=list(c.invariant),
        optional_invariant=list(c.optional_invariant),
        postcondition=list(c.postcondition),
        field_deny={k: list(v) for k, v in c.field_deny.items()},
        value_range={k: dict(v) for k, v in c.value_range.items()},
        obligation_timing=dict(c.obligation_timing),
        name=c.name,
    )

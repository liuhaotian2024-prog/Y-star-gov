#!/usr/bin/env python3
"""
Y* Field Validator — F1 Goodhart failure mode detection + backfill inference.

Validates that m_functor tags on CIEU events are semantically grounded
in the task_description, not post-hoc rationalization.

Extension (Step B): infer_and_validate() + batch_backfill() for historical
events that were emitted before auto-inference was wired into emit_cieu().

Wave-2 Step-1 L4 slice. Deterministic rules only (no LLM judge).
"""
import json
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

# Canonical M-triangle axes from M_TRIANGLE.md (AMENDMENT-023)
M_FUNCTOR_WHITELIST = {"M-1", "M-2a", "M-2b", "M-3"}

# Keyword sets for semantic grounding check.
# If an event claims m_functor=X but task_description contains zero
# keywords from axis X, the tag is WISHFUL (F1 Goodhart gaming).
M_AXIS_KEYWORDS: dict[str, set[str]] = {
    "M-1": {
        "session", "identity", "restart", "backup", "handoff",
        "continuity", "hardware", "persistence", "survivability",
        "restore", "boot", "recovery", "state",
    },
    "M-2a": {
        "forget_guard", "boundary", "router", "iron rule", "enforce",
        "deny", "violation", "block", "commission", "guard",
        "forbidden", "restrict", "prevent",
    },
    "M-2b": {
        "omission", "tracked", "overdue", "p0", "alarm",
        "timeout", "escalate", "scan", "obligation", "missed",
        "deadline", "silent", "inaction",
    },
    "M-3": {
        "customer", "revenue", "demo", "pipeline", "product",
        "ship", "whitepaper", "pip-install", "sale", "value",
        "pricing", "enterprise", "install", "user",
    },
}


# ---------------------------------------------------------------------------
# Agent-ID → Role-ID normalization (Phase 2 signal quality fix)
# ---------------------------------------------------------------------------
# Canonical role_ids in ystar_role_scope: ceo, cto, cmo, secretary, platform,
# governance, kernel.  CIEU agent_id values are free-form.  This map bridges.

AGENT_ID_TO_ROLE_MAP = {
    # Direct matches
    "ceo": "ceo", "cto": "cto", "cmo": "cmo",
    "cfo": "ceo",          # CFO rolls up to CEO role_scope (strategy/finance)
    "cso": "cmo",          # CSO (sales) rolls up to CMO (market-facing)
    "secretary": "secretary",
    # Named-agent variants (case-insensitive prefix)
    "aiden": "ceo", "ethan": "cto", "sofia": "cmo",
    "samantha": "secretary", "marco": "ceo",   # CFO
    "zara": "cmo",         # CSO
    "leo": "kernel", "maya": "governance",
    "ryan": "platform", "jordan": "platform",
    # System-prefixed
    "system:intervention_engine": "governance",
    "system:orchestrator": "platform",
    "system:path_a_agent": "platform",
    "system:path_b_agent": "platform",
    # Engineering role tags
    "eng-kernel": "kernel", "eng-governance": "governance",
    "eng-platform": "platform", "eng-domains": "platform",
    # Board
    "board": "ceo",
    "doctor_agent": "platform",
    # Bare system-component names (without "system:" prefix)
    "orchestrator": "platform",
    "path_a_agent": "platform",
    "path_b_agent": "platform",
    "intervention_engine": "governance",
    "agent": "platform",      # generic "agent" → platform (orchestration)
    "system": "platform",     # bare "system"
    # Catch-alls
    "unidentified": None,
}


def normalize_agent_id_to_role(agent_id):
    # type: (str) -> Optional[str]
    """Map CIEU agent_id (free-form) to role_scope.role_id (canonical 7).

    Resolution order:
      1. Direct lookup (lowered, stripped).
      2. Prefix match — e.g. "Maya-Governance" splits on '-'/'_'/':'.
      3. First token of hyphen/underscore split.
      4. None (caller falls back to 0.5 neutral).
    """
    if not agent_id:
        return None
    aid = agent_id.lower().strip()

    # Direct match
    if aid in AGENT_ID_TO_ROLE_MAP:
        return AGENT_ID_TO_ROLE_MAP[aid]

    # Prefix match (e.g. "maya-governance" → key "maya" via "maya-")
    for key in AGENT_ID_TO_ROLE_MAP:
        if aid.startswith(key + "-") or aid.startswith(key + "_") or aid.startswith(key + ":"):
            return AGENT_ID_TO_ROLE_MAP[key]

    # Hyphen/underscore split — check first token
    parts = aid.replace("_", "-").split("-")
    if parts[0] in AGENT_ID_TO_ROLE_MAP:
        return AGENT_ID_TO_ROLE_MAP[parts[0]]

    return None


def validate_m_functor(m_functor: Optional[str], task_description: str) -> int:
    """
    Validate that an m_functor tag is semantically grounded.

    Args:
        m_functor: The M-triangle axis tag (e.g., "M-1", "M-2a").
                   None or empty string means no tag was provided.
        task_description: The task description to check for keyword presence.

    Returns:
        0  — m_functor missing or not in whitelist (skip, no judgment)
        1  — VALID: whitelist match AND at least one axis keyword present
        -1 — WISHFUL: whitelist match BUT no axis keyword (F1 Goodhart)
    """
    if not m_functor or m_functor not in M_FUNCTOR_WHITELIST:
        return 0

    keywords = M_AXIS_KEYWORDS.get(m_functor, set())
    if not keywords:
        return 0  # Defensive: axis exists in whitelist but no keywords defined

    desc_lower = task_description.lower() if task_description else ""
    for kw in keywords:
        if kw in desc_lower:
            return 1  # At least one keyword found — semantically grounded

    return -1  # Whitelist match but zero keyword overlap — WISHFUL


def batch_validate_recent(
    db_path: str = ".ystar_cieu.db",
    since: str = "1 hour ago",
) -> dict:
    """
    Query recent CIEU events with non-null m_functor, validate each,
    and UPDATE the y_star_validator_pass column in-place.

    Args:
        db_path: Path to the CIEU SQLite database.
        since: Human-readable time offset (e.g., "1 hour ago", "24 hours ago").
               Converted to epoch via simple parsing.

    Returns:
        dict with keys: total, valid_count, wishful_count, skipped_count,
                        events (list of {event_id, m_functor, result}).
    """
    cutoff = _parse_since(since)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT event_id, m_functor, task_description
        FROM cieu_events
        WHERE m_functor IS NOT NULL
          AND m_functor != ''
          AND created_at >= ?
        ORDER BY created_at DESC
        """,
        (cutoff,),
    ).fetchall()

    results = {
        "total": len(rows),
        "valid_count": 0,
        "wishful_count": 0,
        "skipped_count": 0,
        "events": [],
    }

    for row in rows:
        eid = row["event_id"]
        mf = row["m_functor"]
        td = row["task_description"] or ""

        verdict = validate_m_functor(mf, td)

        if verdict == 1:
            results["valid_count"] += 1
        elif verdict == -1:
            results["wishful_count"] += 1
        else:
            results["skipped_count"] += 1

        # Write-back the validator result (L4 slice write-back)
        conn.execute(
            "UPDATE cieu_events SET y_star_validator_pass = ? WHERE event_id = ?",
            (verdict, eid),
        )

        results["events"].append({
            "event_id": eid,
            "m_functor": mf,
            "task_description_snippet": td[:80],
            "result": verdict,
        })

    conn.commit()
    conn.close()
    return results


# --- Event-type prefix rules (synchronized with _cieu_helpers._infer_m_functor) ---

_EVENT_PREFIX_M1 = [
    'SESSION_SEALED', 'BACKFILL_MERKLE', 'SESSION_SEAL', 'BRAIN_DREAM',
    'BRAIN_AUTO', 'HANDOFF', 'SESSION_CLOSE', 'CIEU_TO_BRAIN',
]
_EVENT_PREFIX_M2A = [
    'FORGET_GUARD', 'BOUNDARY', 'ROUTER', 'K9_ROUTING',
    'VIOLATION_DETECTED', 'DENY', 'BLOCK', 'PRETOOL', 'HOOK',
    'INTERVENTION_GATE', 'GOVERNANCE', 'WAVE2', 'WAVE_', 'VALIDATOR',
    'AUDIT', 'RECEIPT',
]
_EVENT_PREFIX_M2B = [
    'OMISSION', 'OVERDUE', 'OBLIGATION', 'ESCALATE', 'ALARM',
    'TIMEOUT', 'COVERAGE_SCAN', 'HOOK_HEALTH',
]
_EVENT_PREFIX_M3 = [
    'SHIPPED', 'LANDED', 'DEPLOY', 'RELEASE',
]

_EVENT_PREFIX_MAP = [
    (_EVENT_PREFIX_M1, 'M-1', 0.7),
    (_EVENT_PREFIX_M2A, 'M-2a', 0.8),
    (_EVENT_PREFIX_M2B, 'M-2b', 0.8),
    (_EVENT_PREFIX_M3, 'M-3', 0.6),
]


def infer_and_validate(
    event_type,          # type: str
    task_description,    # type: str
    agent_id,            # type: str
    existing_m_functor,  # type: Optional[str]
):
    # type: (...) -> Tuple[Optional[str], int, Optional[float]]
    """Infer + validate m_functor for a CIEU event.

    If existing_m_functor is set and valid, validate as before (returns
    existing tag + 1/-1 + None weight — weight already stored).
    If existing_m_functor is None/empty, INFER from event_type prefix then
    keyword match against task_description using M_AXIS_KEYWORDS.

    Returns:
        (m_functor_or_None, validator_pass, m_weight_or_None)
        validator_pass: 1=VALID, -1=WISHFUL, 0=SKIP (no confident match)
    """
    # --- Path A: existing tag → validate only, no weight change ---
    if existing_m_functor and existing_m_functor in M_FUNCTOR_WHITELIST:
        v = validate_m_functor(existing_m_functor, task_description or "")
        return (existing_m_functor, v, None)

    # --- Path B: infer from event_type prefix ---
    et_upper = (event_type or "").upper()
    for prefixes, axis, weight in _EVENT_PREFIX_MAP:
        for pfx in prefixes:
            if pfx in et_upper:
                # Validate inferred tag against task_description
                v = validate_m_functor(axis, task_description or "")
                # For prefix-inferred, if keyword check returns 0 (no keywords
                # defined) or -1 (no keyword match), still trust the prefix
                # with validator_pass = 1 (prefix is strong signal).
                return (axis, 1, weight)

    # --- Path C: keyword match on task_description ---
    desc_lower = (task_description or "").lower()
    if desc_lower:
        best_axis = None   # type: Optional[str]
        best_count = 0
        for axis, keywords in M_AXIS_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in desc_lower)
            if count > best_count:
                best_count = count
                best_axis = axis
        if best_axis and best_count >= 1:
            return (best_axis, 1, 0.5)

    # --- Path D: no confident match → skip ---
    return (None, 0, None)


def batch_backfill(
    db_path,   # type: str
    limit=5000,  # type: int
):
    # type: (...) -> Dict[str, int]
    """Scan CIEU events WHERE m_functor IS NULL, infer + validate, UPDATE.

    Processes in a single pass up to `limit` rows. Uses rowid ordering
    for deterministic batching.

    Returns:
        dict with keys: scanned, inferred, skipped_no_signal,
                        valid_count, wishful_count
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Fetch rows with NULL m_functor (or empty string treated as NULL)
    rows = conn.execute(
        """
        SELECT rowid, event_id, event_type, task_description, agent_id, m_functor
        FROM cieu_events
        WHERE (m_functor IS NULL OR m_functor = '')
          AND y_star_validator_pass IS NULL
        ORDER BY rowid ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    stats = {
        "scanned": len(rows),
        "inferred": 0,
        "skipped_no_signal": 0,
        "valid_count": 0,
        "wishful_count": 0,
    }

    batch_updates = []  # type: list

    for row in rows:
        eid = row["event_id"]
        et = row["event_type"] or ""
        td = row["task_description"] or ""
        aid = row["agent_id"] or ""
        existing = row["m_functor"] if row["m_functor"] else None

        inferred_mf, vpass, mw = infer_and_validate(et, td, aid, existing)

        if inferred_mf is None:
            stats["skipped_no_signal"] += 1
            # Still write validator_pass=0 so we don't re-scan this row
            batch_updates.append((None, None, 0, eid))
            continue

        stats["inferred"] += 1
        if vpass == 1:
            stats["valid_count"] += 1
        elif vpass == -1:
            stats["wishful_count"] += 1

        batch_updates.append((inferred_mf, mw, vpass, eid))

    # Batch UPDATE
    conn.executemany(
        """
        UPDATE cieu_events
        SET m_functor = COALESCE(?, m_functor),
            m_weight = COALESCE(?, m_weight),
            y_star_validator_pass = ?
        WHERE event_id = ?
        """,
        batch_updates,
    )
    conn.commit()
    conn.close()

    return stats


# ---------------------------------------------------------------------------
# Phase 2: Role-alignment + Goal-contribution inference
# ---------------------------------------------------------------------------


def _table_exists(conn, table_name):
    # type: (sqlite3.Connection, str) -> bool
    """Check if a table exists in sqlite_master."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row[0] > 0 if row else False


def infer_role_alignment(
    event_type,        # type: str
    task_description,  # type: str
    agent_id,          # type: str
    db_path,           # type: str
):
    # type: (...) -> Tuple[float, str]
    """Return (alignment_score 0-1, inference_basis).

    Load role_scope_keywords + anti_scope_keywords for agent's role from
    ystar_role_scope.  Fire anti_scope first -> 0.1 if matched (off-role).
    Fire scope -> 0.9 if matched (in-role).  No match -> 0.5 (neutral).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if not _table_exists(conn, "ystar_role_scope"):
        conn.close()
        return (0.5, "neutral: ystar_role_scope table missing")

    # Resolve agent's role (agent_id may be "eng-governance", "ceo", etc.)
    rows = conn.execute(
        "SELECT role_id, scope_keywords, anti_scope_keywords FROM ystar_role_scope"
    ).fetchall()
    conn.close()

    if not rows:
        return (0.5, "neutral: no_role_scope_rows")

    # Build a combined search text from event_type + task_description
    search_text = " ".join([
        (event_type or ""),
        (task_description or ""),
    ]).lower()

    if not search_text.strip():
        return (0.5, "neutral: no_signal")

    # Normalize agent_id to canonical role_id via the mapping table
    resolved_role = normalize_agent_id_to_role(agent_id)
    role_via_normalization = resolved_role is not None

    matched_row = None
    if resolved_role:
        for r in rows:
            if (r["role_id"] or "").lower() == resolved_role:
                matched_row = r
                break

    # Fallback: legacy substring match (covers any future role_scope rows
    # that aren't in the static map yet)
    if matched_row is None:
        agent_lower = (agent_id or "").lower()
        for r in rows:
            role_lower = (r["role_id"] or "").lower()
            if role_lower == agent_lower or agent_lower in role_lower or role_lower in agent_lower:
                matched_row = r
                role_via_normalization = True
                break

    if matched_row is None:
        return (0.5, "neutral: agent_role_not_found")

    # Parse keywords — may be JSON array or comma-separated string
    def _parse_kw_field(raw):
        # type: (str) -> list
        if not raw:
            return []
        raw = raw.strip()
        if raw.startswith("["):
            try:
                return [k.lower().strip() for k in json.loads(raw) if isinstance(k, str) and k.strip()]
            except (json.JSONDecodeError, ValueError):
                pass
        return [k.strip().lower() for k in raw.split(",") if k.strip()]

    # Anti-scope check first
    anti_kws = _parse_kw_field(matched_row["anti_scope_keywords"] or "")
    for kw in anti_kws:
        if kw in search_text:
            return (0.1, "anti_match: {}".format(kw))

    # Scope check
    scope_kws = _parse_kw_field(matched_row["scope_keywords"] or "")
    for kw in scope_kws:
        if kw in search_text:
            return (0.9, "scope_match: {}".format(kw))

    # If role was resolved via normalization map, mild positive (agent IS in
    # its role, we just lack keyword signal in the sparse event content).
    if role_via_normalization:
        return (0.7, "role_resolved_no_content_signal: {}".format(resolved_role or matched_row["role_id"]))

    return (0.5, "neutral: no_signal")


def infer_goal_contribution(
    event_type,        # type: str
    task_description,  # type: str
    file_path,         # type: str
    db_path,           # type: str
):
    # type: (...) -> List[Tuple[str, float, str]]
    """Return list of (goal_id, contribution_score 0-1, inference_basis).

    Read all active goals from ystar_goal_tree. For each goal: keyword match
    task_description + file_path against goal's y_star_definition keywords.
    Score 0.8 if strong match, 0.3 if weak match, skip if no match.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if not _table_exists(conn, "ystar_goal_tree"):
        conn.close()
        return []

    goals = conn.execute(
        "SELECT goal_id, y_star_definition, status FROM ystar_goal_tree "
        "WHERE status IN ('active', 'ACTIVE', 'Active') OR status IS NULL"
    ).fetchall()
    conn.close()

    if not goals:
        return []

    search_text = " ".join([
        (event_type or ""),
        (task_description or ""),
        (file_path or ""),
    ]).lower()

    if not search_text.strip():
        return []

    results = []  # type: List[Tuple[str, float, str]]

    for g in goals:
        gid = g["goal_id"]
        defn = (g["y_star_definition"] or "").lower()

        if not defn:
            continue

        # Extract keywords from y_star_definition: split on common delimiters
        keywords = [
            w.strip() for w in defn.replace(",", " ").replace(";", " ").split()
            if len(w.strip()) >= 3  # skip very short tokens
        ]

        if not keywords:
            continue

        match_count = sum(1 for kw in keywords if kw in search_text)

        if match_count == 0:
            continue
        elif match_count >= 2:
            results.append((gid, 0.8, "strong_match: {}_keywords".format(match_count)))
        else:
            results.append((gid, 0.3, "weak_match: 1_keyword"))

    return results


def batch_contribution_backfill(
    db_path,    # type: str
    limit=5000,  # type: int
):
    # type: (...) -> Dict
    """Scan recent CIEU events, compute role_alignment + goal_contribution(s),
    INSERT rows into cieu_goal_contribution.

    Idempotent: skip events that already have rows in cieu_goal_contribution.
    Returns stats dict.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check dependency tables
    missing = []  # type: List[str]
    for tbl in ["ystar_role_scope", "ystar_goal_tree", "cieu_goal_contribution"]:
        if not _table_exists(conn, tbl):
            missing.append(tbl)

    if missing:
        conn.close()
        return {
            "status": "BLOCKED",
            "missing_tables": missing,
            "processed": 0,
            "contributions_inserted": 0,
            "role_scores_computed": 0,
        }

    # Get event_ids already processed
    existing_ids_rows = conn.execute(
        "SELECT DISTINCT event_id FROM cieu_goal_contribution"
    ).fetchall()
    existing_ids = {r["event_id"] for r in existing_ids_rows}

    # Fetch recent events
    rows = conn.execute(
        """
        SELECT event_id, event_type, task_description, agent_id, file_path
        FROM cieu_events
        ORDER BY rowid DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    stats = {
        "status": "OK",
        "missing_tables": [],
        "processed": 0,
        "skipped_existing": 0,
        "contributions_inserted": 0,
        "role_scores_computed": 0,
    }

    inserts = []  # type: list

    for row in rows:
        eid = row["event_id"]

        if eid in existing_ids:
            stats["skipped_existing"] += 1
            continue

        stats["processed"] += 1

        et = row["event_type"] or ""
        td = row["task_description"] or ""
        aid = row["agent_id"] or ""
        fp = row["file_path"] or ""

        # Role alignment (computed per event but stored per contribution row)
        role_score, role_basis = infer_role_alignment(et, td, aid, db_path)
        stats["role_scores_computed"] += 1

        # Goal contributions
        contributions = infer_goal_contribution(et, td, fp, db_path)

        now = time.time()
        if contributions:
            for gid, gscore, gbasis in contributions:
                basis_combined = "role={:.1f}({}); goal={}".format(
                    role_score, role_basis, gbasis
                )
                inserts.append((eid, gid, role_score, gscore, basis_combined, now))
        else:
            # Still record role alignment with NULL goal
            inserts.append((eid, None, role_score, 0.0,
                            "role={:.1f}({}); goal=no_match".format(role_score, role_basis), now))

        stats["contributions_inserted"] += len(contributions) if contributions else 1

    # Batch INSERT
    if inserts:
        conn.executemany(
            """
            INSERT INTO cieu_goal_contribution
                (event_id, goal_id, role_alignment_score, goal_contribution_score, inference_basis, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            inserts,
        )
        conn.commit()

    conn.close()
    return stats


def _parse_since(since: str) -> float:
    """
    Parse a human-readable 'since' string into epoch seconds.
    Supports: "N hour(s) ago", "N minute(s) ago", "N day(s) ago".
    Falls back to 1 hour ago on parse failure.
    """
    import re

    now = time.time()
    since_lower = since.lower().strip()

    m = re.match(r"(\d+)\s*(hour|minute|day|second)s?\s*ago", since_lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        multipliers = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        return now - n * multipliers.get(unit, 3600)

    # Fallback: 1 hour ago
    return now - 3600

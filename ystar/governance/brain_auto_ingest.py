#!/usr/bin/env python3
"""
Brain Auto-Ingest — Boundary (c)+(d) pattern for aiden_brain.db.

Scans reports/, knowledge/, memory/ and .ystar_cieu.db for new/changed
files and CIEU events since last ingest. Extracts node candidates, applies
via add_node/add_edge (both now preserve state), writes activation_log
entries, and increments access_count for re-activated nodes.

Called at session boundaries:
  - governance_boot.sh  (mode=delta, post ALL-SYSTEMS-GO)
  - session_close_yml.py (mode=delta, pre continuation write)

Per CTO ruling CZL-BRAIN-AUTO-INGEST: boundary hooks provide natural retry.
If this module crashes, session is fully functional without brain. No queue,
no retry daemon.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Directories to scan (relative to COMPANY_ROOT)
INGEST_DIRS = ["reports", "knowledge", "memory"]

# Default company root (caller can override)
_DEFAULT_COMPANY_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "ystar-company",
)


def _company_root():
    return os.environ.get("YSTAR_COMPANY_ROOT", _DEFAULT_COMPANY_ROOT)


def _brain_db_path():
    return os.environ.get(
        "AIDEN_BRAIN_DB",
        os.path.join(_company_root(), "aiden_brain.db"),
    )


def _cieu_db_path():
    return os.environ.get(
        "YSTAR_CIEU_DB",
        os.path.join(_company_root(), ".ystar_cieu.db"),
    )


def _sentinel_path():
    return os.path.join(_company_root(), "scripts", ".brain_ingest_sentinel.json")


def _session_id() -> str:
    session_file = os.path.join(_company_root(), ".ystar_session.json")
    try:
        with open(session_file, "r") as f:
            return json.load(f).get("session_id", "unknown")
    except (FileNotFoundError, json.JSONDecodeError):
        return "unknown"


# ---------------------------------------------------------------------------
# Sentinel — tracks last ingest timestamp + processed hashes
# ---------------------------------------------------------------------------

def _read_sentinel(sentinel_path: Optional[str] = None) -> dict:
    sp = sentinel_path or _sentinel_path()
    try:
        with open(sp, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_ingest_ts": 0.0, "file_hashes": {}, "last_cieu_id": 0}


def _write_sentinel(data: dict, sentinel_path: Optional[str] = None):
    sp = sentinel_path or _sentinel_path()
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    """SHA-256 truncated to 16 hex chars, matching aiden_import convention."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Node ID + type inference from path
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "reports": "report",
    "knowledge": "knowledge",
    "memory": "memory",
}

_DEPTH_MAP = {
    "ceo": "foundational",
    "cto": "operational",
    "cmo": "operational",
    "cso": "operational",
    "cfo": "operational",
    "wisdom": "kernel",
    "lessons": "tactical",
    "methodology": "operational",
    "receipts": "tactical",
    "autonomous": "tactical",
    "shared": "foundational",
}


def _make_node_id(rel_path: str) -> str:
    """Deterministic node ID from relative path.  Uses / separator, strips .md."""
    return rel_path.replace(os.sep, "/").replace(".md", "").replace(" ", "_")


def _infer_type(rel_path: str) -> str:
    parts = rel_path.replace(os.sep, "/").split("/")
    if parts:
        return _TYPE_MAP.get(parts[0], "misc")
    return "misc"


def _infer_depth(rel_path: str) -> str:
    """Infer depth label from path. More-specific segments (wisdom, lessons)
    take priority over broader ones (ceo, cto), so we scan deepest first."""
    parts = rel_path.replace(os.sep, "/").split("/")
    # Scan from deepest to shallowest so specific labels win
    for p in reversed(parts):
        if p in _DEPTH_MAP:
            return _DEPTH_MAP[p]
    return "operational"


def _extract_summary(text: str, fallback: str) -> str:
    """First meaningful line after optional frontmatter."""
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    for line in body.split("\n"):
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("---") and len(line) > 10:
            return line[:120]
    return fallback[:120] if fallback else ""


# ---------------------------------------------------------------------------
# scan_sources — find new/changed files since last sentinel
# ---------------------------------------------------------------------------

def scan_sources(
    company_root: Optional[str] = None,
    sentinel_path: Optional[str] = None,
    ingest_dirs: Optional[list] = None,
) -> list:
    """Walk INGEST_DIRS and return list of candidate dicts for new/changed .md files.

    Each candidate:
        {"file_path": str, "rel_path": str, "content": str, "hash": str,
         "node_id": str, "node_type": str, "depth_label": str,
         "name": str, "summary": str}
    """
    root = company_root or _company_root()
    sentinel = _read_sentinel(sentinel_path)
    known_hashes = sentinel.get("file_hashes", {})
    dirs = ingest_dirs or INGEST_DIRS

    candidates = []
    for d in dirs:
        dir_path = os.path.join(root, d)
        if not os.path.isdir(dir_path):
            continue
        for dirpath, _dirs, files in os.walk(dir_path):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(dirpath, fname)
                rel = os.path.relpath(fpath, root)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except (OSError, IOError):
                    continue  # skip unreadable files

                h = content_hash(text)
                if known_hashes.get(rel) == h:
                    continue  # unchanged — dedup

                node_id = _make_node_id(rel)
                name = fname.replace(".md", "").replace("_", " ").title()
                candidates.append({
                    "file_path": fpath,
                    "rel_path": rel,
                    "content": text,
                    "hash": h,
                    "node_id": node_id,
                    "node_type": _infer_type(rel),
                    "depth_label": _infer_depth(rel),
                    "name": name,
                    "summary": _extract_summary(text, name),
                })

    return candidates


# ---------------------------------------------------------------------------
# scan_cieu_events — find CIEU events since last sentinel
# ---------------------------------------------------------------------------

def scan_cieu_events(
    cieu_db: Optional[str] = None,
    sentinel_path: Optional[str] = None,
) -> list:
    """Return CIEU events since last_cieu_id for activation_log integration.

    Each entry: {"event_id": int, "event_type": str, "payload": dict, "timestamp": float}
    """
    db_path = cieu_db or _cieu_db_path()
    sentinel = _read_sentinel(sentinel_path)
    last_id = sentinel.get("last_cieu_id", 0)

    if not os.path.exists(db_path):
        return []

    events = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        rows = conn.execute(
            "SELECT rowid, * FROM cieu_events WHERE rowid > ? ORDER BY rowid",
            (last_id,),
        ).fetchall()
        for row in rows:
            row_dict = dict(row)
            payload = {}
            try:
                raw = row_dict.get("payload", "")
                if raw:
                    payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
            events.append({
                "event_id": row_dict.get("rowid", 0),
                "event_type": row_dict.get("event_type", ""),
                "payload": payload,
                "timestamp": row_dict.get("timestamp", 0.0),
            })
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass  # CIEU DB unavailable — non-fatal

    return events


# ---------------------------------------------------------------------------
# extract_candidates — unified extraction from files + CIEU events
# ---------------------------------------------------------------------------

def extract_candidates(
    company_root: Optional[str] = None,
    sentinel_path: Optional[str] = None,
    cieu_db: Optional[str] = None,
    ingest_dirs: Optional[list] = None,
) -> dict:
    """Return {"file_candidates": [...], "cieu_events": [...], "stats": {...}}."""
    file_cands = scan_sources(company_root, sentinel_path, ingest_dirs)
    cieu_events = scan_cieu_events(cieu_db, sentinel_path)
    return {
        "file_candidates": file_cands,
        "cieu_events": cieu_events,
        "stats": {
            "files_scanned": len(file_cands),
            "cieu_events_scanned": len(cieu_events),
        },
    }


# ---------------------------------------------------------------------------
# increment_access_count — the missing code path (CTO ruling Q8)
# ---------------------------------------------------------------------------

def increment_access_count(node_id: str, db_path: Optional[str] = None):
    """Atomically increment access_count and update last_accessed for a node.

    This fixes the gap where activation_log writes never updated the nodes
    table, causing access_count to remain 0 despite repeated activations.
    """
    db = db_path or _brain_db_path()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "UPDATE nodes SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
        (time.time(), node_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _write_activation_log — record auto-ingest activation entry
# ---------------------------------------------------------------------------

def _write_activation_log(
    node_ids: list,
    file_path: str,
    session_id: str,
    db_path: str,
    activation_level: float = 0.3,
):
    """Write one activation_log entry per ingested file/event.

    Per CTO ruling section 5: auto-ingest activation_level = 0.3 (moderate
    warmth, not 1.0). Auto-ingest does NOT increment access_count (only
    explicit activate() and touch_node() do).
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")
    activated = json.dumps([
        {"node_id": nid, "activation_level": activation_level}
        for nid in node_ids
    ])
    conn.execute(
        "INSERT INTO activation_log (query, activated_nodes, session_id, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (f"auto_ingest:{file_path}", activated, session_id, time.time()),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# apply_ingest — merge candidates into brain via add_node/add_edge
# ---------------------------------------------------------------------------

def apply_ingest(
    candidates: dict,
    company_root: Optional[str] = None,
    brain_db: Optional[str] = None,
    sentinel_path: Optional[str] = None,
) -> dict:
    """Apply extracted candidates to aiden_brain.db.

    Returns: {"ingested": int, "skipped": int, "errors": int,
              "total_scanned": int, "cieu_activations": int}
    """
    root = company_root or _company_root()
    db = brain_db or _brain_db_path()
    sp = sentinel_path or _sentinel_path()
    sentinel = _read_sentinel(sp)
    session_id = _session_id()

    # Ensure brain DB is initialised
    _ensure_brain_tables(db)

    file_cands = candidates.get("file_candidates", [])
    cieu_events = candidates.get("cieu_events", [])

    ingested = 0
    skipped = 0
    errors = 0

    # Group by directory for co-activation
    dir_groups = {}

    for cand in file_cands:
        try:
            _upsert_node(
                db=db,
                node_id=cand["node_id"],
                name=cand["name"],
                file_path=cand["rel_path"],
                node_type=cand["node_type"],
                depth_label=cand["depth_label"],
                summary=cand["summary"],
                chash=cand["hash"],
            )

            # Write activation_log entry (per CTO ruling section 5)
            _write_activation_log(
                [cand["node_id"]], cand["rel_path"], session_id, db,
            )

            # Track directory grouping for co-activation
            parent_dir = os.path.dirname(cand["rel_path"])
            dir_groups.setdefault(parent_dir, []).append(cand["node_id"])

            # Update sentinel hash
            sentinel.setdefault("file_hashes", {})[cand["rel_path"]] = cand["hash"]
            ingested += 1
        except Exception:
            errors += 1

    # Co-activation for same-directory batch (CTO ruling section 5)
    for _dir, node_ids in dir_groups.items():
        if len(node_ids) > 1:
            _record_co_activation_batch(node_ids, db)

    # CIEU event activations
    cieu_activations = 0
    max_cieu_id = sentinel.get("last_cieu_id", 0)
    for ev in cieu_events:
        eid = ev.get("event_id", 0)
        if eid > max_cieu_id:
            max_cieu_id = eid
        # Map CIEU events to node activations — increment access_count
        # for nodes mentioned in the event payload
        payload = ev.get("payload", {})
        node_ref = payload.get("node_id") or payload.get("agent_id")
        if node_ref:
            increment_access_count(node_ref, db)
            cieu_activations += 1

    # Update sentinel
    sentinel["last_ingest_ts"] = time.time()
    sentinel["last_cieu_id"] = max_cieu_id
    _write_sentinel(sentinel, sp)

    return {
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
        "total_scanned": len(file_cands),
        "cieu_activations": cieu_activations,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_brain_tables(db_path: str):
    """Create brain tables if they don't exist (idempotent)."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            file_path   TEXT,
            node_type   TEXT,
            depth_label TEXT,
            content_hash TEXT,
            dim_y       REAL DEFAULT 0.5,
            dim_x       REAL DEFAULT 0.5,
            dim_z       REAL DEFAULT 0.5,
            dim_t       REAL DEFAULT 0.5,
            dim_phi     REAL DEFAULT 0.5,
            dim_c       REAL DEFAULT 0.5,
            base_activation REAL DEFAULT 0.0,
            last_accessed   REAL DEFAULT 0.0,
            access_count    INTEGER DEFAULT 0,
            created_at      REAL DEFAULT 0.0,
            updated_at      REAL DEFAULT 0.0,
            principles  TEXT,
            triggers    TEXT,
            summary     TEXT
        );

        CREATE TABLE IF NOT EXISTS edges (
            source_id   TEXT NOT NULL,
            target_id   TEXT NOT NULL,
            edge_type   TEXT DEFAULT 'explicit',
            weight      REAL DEFAULT 0.5,
            created_at  REAL DEFAULT 0.0,
            updated_at  REAL DEFAULT 0.0,
            co_activations INTEGER DEFAULT 0,
            PRIMARY KEY (source_id, target_id),
            FOREIGN KEY (source_id) REFERENCES nodes(id),
            FOREIGN KEY (target_id) REFERENCES nodes(id)
        );

        CREATE TABLE IF NOT EXISTS activation_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT,
            activated_nodes TEXT,
            session_id  TEXT,
            timestamp   REAL
        );

        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
    """)
    conn.commit()
    conn.close()


def _upsert_node(
    db: str,
    node_id: str,
    name: str,
    file_path: str,
    node_type: str,
    depth_label: str,
    summary: str,
    chash: str,
):
    """INSERT ... ON CONFLICT DO UPDATE, preserving access_count/last_accessed/created_at."""
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA busy_timeout=5000")
    now = time.time()
    conn.execute("""
        INSERT INTO nodes
        (id, name, file_path, node_type, depth_label,
         dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c,
         base_activation, last_accessed, access_count,
         created_at, updated_at, principles, summary, content_hash)
        VALUES (?, ?, ?, ?, ?,
                0.5, 0.5, 0.5, 0.5, 0.5, 0.5,
                0.0, 0.0, 0,
                ?, ?, '[]', ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            file_path = excluded.file_path,
            node_type = excluded.node_type,
            depth_label = excluded.depth_label,
            updated_at = excluded.updated_at,
            summary = excluded.summary,
            content_hash = excluded.content_hash
    """, (node_id, name, file_path, node_type, depth_label,
          now, now, summary, chash))
    conn.commit()
    conn.close()


def _record_co_activation_batch(node_ids: list, db_path: str):
    """Strengthen edges between nodes ingested in the same directory batch.

    Per CTO ruling section 5: same-directory → co-activation with hebbian edge.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")
    now = time.time()
    for i, a in enumerate(node_ids):
        for b in node_ids[i + 1:]:
            for src, tgt in [(a, b), (b, a)]:
                conn.execute("""
                    INSERT INTO edges
                    (source_id, target_id, edge_type, weight,
                     created_at, updated_at, co_activations)
                    VALUES (?, ?, 'proximity', 0.3, ?, ?, 1)
                    ON CONFLICT(source_id, target_id) DO UPDATE SET
                        co_activations = co_activations + 1,
                        updated_at = excluded.updated_at
                """, (src, tgt, now, now))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """CLI: brain_auto_ingest.py --mode delta|full [--company-root PATH]"""
    import argparse

    parser = argparse.ArgumentParser(description="Brain auto-ingest boundary hook")
    parser.add_argument("--mode", choices=["delta", "full"], default="delta",
                        help="delta = hash-compare skip unchanged; full = re-import all")
    parser.add_argument("--company-root", default=None,
                        help="Override company root directory")
    parser.add_argument("--brain-db", default=None,
                        help="Override brain database path")
    parser.add_argument("--sentinel-path", default=None,
                        help="Override sentinel file path")
    args = parser.parse_args()

    if args.company_root:
        os.environ["YSTAR_COMPANY_ROOT"] = args.company_root
    if args.brain_db:
        os.environ["AIDEN_BRAIN_DB"] = args.brain_db

    # In full mode, clear sentinel to force re-scan
    sp = args.sentinel_path or _sentinel_path()
    if args.mode == "full":
        _write_sentinel({"last_ingest_ts": 0.0, "file_hashes": {}, "last_cieu_id": 0}, sp)

    candidates = extract_candidates(
        company_root=args.company_root,
        sentinel_path=sp,
        ingest_dirs=INGEST_DIRS,
    )

    result = apply_ingest(
        candidates,
        company_root=args.company_root,
        brain_db=args.brain_db,
        sentinel_path=sp,
    )

    # Output JSON summary to stdout (consumed by boundary scripts)
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    main()

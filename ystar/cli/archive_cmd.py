"""CIEU Archive Command — Hot/Cold Data Tiering + Permanent Preservation

Hot data  (≤7 days)  → stays in local SQLite, normal query path
Cold data (>7 days)  → compressed .jsonl.gz in cieu_archive/, deleted from DB

Merkle chain integrity:
  Before deletion, all affected sessions are sealed. The sealed_sessions table
  retains the merkle_root so chain verification still works after cold records
  are removed. A boundary tombstone (the newest archived event_id per session)
  is kept in a lightweight `archive_boundaries` table for auditability.

CLI:
  ystar archive                      — archive cold data (>7 days)
  ystar archive --days 30            — archive data older than 30 days
  ystar archive --query 2026-03-15   — query archived data for a date
  ystar archive --dry-run            — show what would be archived
  ystar archive-cieu                 — legacy full export (no deletion)
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional


# ── Core archive logic ──────────────────────────────────────────────────────

DEFAULT_HOT_DAYS = 7
DEFAULT_ARCHIVE_DIR = "data/cieu_archive"
DEFAULT_DB_PATH = ".ystar_cieu.db"


def archive_cold_data(
    db_path: str = DEFAULT_DB_PATH,
    archive_dir: str = DEFAULT_ARCHIVE_DIR,
    hot_days: int = DEFAULT_HOT_DAYS,
    dry_run: bool = False,
) -> dict:
    """Move cold CIEU records (older than hot_days) to compressed archive.

    Returns dict with archive stats.
    """
    db = Path(db_path)
    if not db.exists():
        return {"error": f"CIEU database not found: {db}"}

    cutoff = time.time() - (hot_days * 86400)
    out_dir = Path(archive_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    # 1. Count cold records
    cold_count = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE created_at < ?", (cutoff,)
    ).fetchone()[0]

    if cold_count == 0:
        conn.close()
        return {"archived": 0, "message": "No cold data to archive"}

    # 2. Fetch cold records
    rows = conn.execute(
        "SELECT * FROM cieu_events WHERE created_at < ? ORDER BY created_at",
        (cutoff,),
    ).fetchall()
    events = [dict(r) for r in rows]

    if dry_run:
        conn.close()
        oldest = datetime.fromtimestamp(events[0]["created_at"]).isoformat()
        newest = datetime.fromtimestamp(events[-1]["created_at"]).isoformat()
        return {
            "dry_run": True,
            "would_archive": len(events),
            "oldest": oldest,
            "newest": newest,
            "cutoff_days": hot_days,
        }

    # 3. Seal affected sessions before archiving
    session_ids = list({e.get("session_id", "") for e in events if e.get("session_id")})
    sealed_sessions = _seal_sessions(conn, session_ids)

    # 4. Write compressed JSONL
    today = datetime.now().strftime("%Y-%m-%d")
    archive_file = out_dir / f"{today}.jsonl.gz"
    # Append if archive for today already exists
    mode = "ab" if archive_file.exists() else "wb"
    with gzip.open(archive_file, mode) as f:
        for event in events:
            line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
            f.write(line.encode("utf-8"))

    # 5. Record archive boundaries (for chain auditability)
    _ensure_boundary_table(conn)
    for sid in session_ids:
        session_events = [e for e in events if e.get("session_id") == sid]
        if session_events:
            boundary_event_id = session_events[-1].get("event_id", "")
            boundary_ts = session_events[-1].get("created_at", 0)
            conn.execute(
                """INSERT OR REPLACE INTO archive_boundaries
                   (session_id, boundary_event_id, boundary_ts, archive_file, archived_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (sid, boundary_event_id, boundary_ts, str(archive_file), len(session_events)),
            )

    # 6. Delete cold records from main DB
    conn.execute("DELETE FROM cieu_events WHERE created_at < ?", (cutoff,))
    conn.commit()

    # 7. VACUUM to reclaim space
    conn.execute("VACUUM")
    conn.close()

    # 8. Update metadata
    _write_metadata(out_dir, archive_file, len(events), sealed_sessions)

    return {
        "archived": len(events),
        "archive_file": str(archive_file),
        "sessions_sealed": len(sealed_sessions),
        "cutoff_days": hot_days,
        "db_path": str(db),
    }


def query_archive(
    date_str: str,
    archive_dir: str = DEFAULT_ARCHIVE_DIR,
    keyword: str = "",
    limit: int = 50,
) -> dict:
    """Query archived CIEU records for a given date.

    Args:
        date_str: Date in YYYY-MM-DD format.
        archive_dir: Archive directory path.
        keyword: Optional keyword filter (searches all fields).
        limit: Max results to return.
    """
    out_dir = Path(archive_dir)

    # Find matching archive files (exact date or scan all)
    candidates: List[Path] = []
    gz_file = out_dir / f"{date_str}.jsonl.gz"
    jsonl_file = out_dir / f"{date_str}.jsonl"
    if gz_file.exists():
        candidates.append(gz_file)
    if jsonl_file.exists():
        candidates.append(jsonl_file)

    if not candidates:
        # Scan all archives for records matching the date
        for f in sorted(out_dir.glob("*.jsonl.gz")):
            candidates.append(f)
        for f in sorted(out_dir.glob("*.jsonl")):
            if not f.name.startswith("."):
                candidates.append(f)

    if not candidates:
        return {"error": f"No archive files found in {out_dir}", "results": []}

    # Parse target date range
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        day_start = target_date.timestamp()
        day_end = (target_date + timedelta(days=1)).timestamp()
    except ValueError:
        day_start, day_end = 0, float("inf")

    results = []
    files_scanned = 0

    for archive_file in candidates:
        files_scanned += 1
        opener = gzip.open if archive_file.suffix == ".gz" else open
        try:
            with opener(archive_file, "rt", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = record.get("created_at", 0)
                    if not (day_start <= ts < day_end):
                        continue

                    if keyword and keyword.lower() not in json.dumps(record).lower():
                        continue

                    results.append(record)
                    if len(results) >= limit:
                        break
        except Exception:
            continue

        if len(results) >= limit:
            break

    return {
        "date": date_str,
        "total": len(results),
        "files_scanned": files_scanned,
        "results": results,
    }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _seal_sessions(conn: sqlite3.Connection, session_ids: List[str]) -> List[str]:
    """Seal sessions that haven't been sealed yet. Returns list of newly sealed IDs."""
    import hashlib

    # Ensure sealed_sessions table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sealed_sessions (
            session_id   TEXT    PRIMARY KEY,
            sealed_at    REAL    NOT NULL,
            event_count  INTEGER NOT NULL,
            merkle_root  TEXT    NOT NULL,
            prev_root    TEXT,
            db_path      TEXT
        )
    """)

    sealed = []
    for sid in session_ids:
        if not sid:
            continue
        # Check if already sealed
        existing = conn.execute(
            "SELECT 1 FROM sealed_sessions WHERE session_id = ?", (sid,)
        ).fetchone()
        if existing:
            continue

        # Compute merkle root
        event_ids = [
            r[0] for r in conn.execute(
                "SELECT event_id FROM cieu_events WHERE session_id = ? ORDER BY seq_global",
                (sid,),
            ).fetchall()
        ]
        if not event_ids:
            continue

        merkle_data = "\n".join(event_ids)
        merkle_root = hashlib.sha256(merkle_data.encode()).hexdigest()

        # Get prev_root from last sealed session
        prev = conn.execute(
            "SELECT merkle_root FROM sealed_sessions ORDER BY sealed_at DESC LIMIT 1"
        ).fetchone()
        prev_root = prev[0] if prev else None

        now = time.time()
        conn.execute(
            """INSERT INTO sealed_sessions (session_id, sealed_at, event_count, merkle_root, prev_root)
               VALUES (?, ?, ?, ?, ?)""",
            (sid, now, len(event_ids), merkle_root, prev_root),
        )

        # Mark events as sealed
        conn.execute(
            "UPDATE cieu_events SET sealed = 1 WHERE session_id = ?", (sid,)
        )

        sealed.append(sid)

    if sealed:
        conn.commit()
    return sealed


def _ensure_boundary_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_boundaries (
            session_id       TEXT PRIMARY KEY,
            boundary_event_id TEXT NOT NULL,
            boundary_ts      REAL NOT NULL,
            archive_file     TEXT NOT NULL,
            archived_count   INTEGER NOT NULL,
            created_at       REAL DEFAULT (strftime('%s', 'now'))
        )
    """)


def _write_metadata(
    archive_dir: Path, archive_file: Path, event_count: int, sealed_sessions: List[str]
) -> None:
    meta_file = archive_dir / ".archive_metadata.json"
    metadata = {
        "last_archive": datetime.now().isoformat(),
        "archive_file": str(archive_file),
        "event_count": event_count,
        "sealed_sessions": sealed_sessions,
    }
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


# ── CLI entry points ────────────────────────────────────────────────────────

def _cmd_archive(args: list) -> None:
    """ystar archive — hot/cold data tiering with compression."""
    import sys

    # Parse args
    hot_days = DEFAULT_HOT_DAYS
    archive_dir = DEFAULT_ARCHIVE_DIR
    db_path = DEFAULT_DB_PATH
    dry_run = False
    query_date: Optional[str] = None

    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            hot_days = int(args[i + 1])
            i += 2
        elif args[i] == "--output-dir" and i + 1 < len(args):
            archive_dir = args[i + 1]
            i += 2
        elif args[i] == "--db-path" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--query" and i + 1 < len(args):
            query_date = args[i + 1]
            i += 2
        else:
            i += 1

    # Query mode
    if query_date:
        result = query_archive(query_date, archive_dir=archive_dir)
        if result.get("error"):
            print(f"  [!] {result['error']}")
            return

        print(f"  Archive query: {result['date']}")
        print(f"  Files scanned: {result['files_scanned']}")
        print(f"  Records found: {result['total']}")
        print()
        for r in result["results"]:
            ts = datetime.fromtimestamp(r.get("created_at", 0)).strftime("%H:%M:%S")
            decision = r.get("decision", "?")
            event_type = r.get("event_type", "?")
            agent = r.get("agent_id", "?")
            print(f"  [{ts}] {decision:>6}  {event_type:<30}  agent={agent}")
        return

    # Archive mode
    result = archive_cold_data(
        db_path=db_path,
        archive_dir=archive_dir,
        hot_days=hot_days,
        dry_run=dry_run,
    )

    if result.get("error"):
        print(f"  [✗] {result['error']}")
        sys.exit(1)

    if result.get("dry_run"):
        print(f"  [DRY RUN] Would archive {result['would_archive']} records")
        print(f"    Oldest: {result['oldest']}")
        print(f"    Newest: {result['newest']}")
        print(f"    Cutoff: >{result['cutoff_days']} days old")
        return

    if result.get("archived", 0) == 0:
        print(f"  [✓] {result.get('message', 'Nothing to archive')}")
        return

    print(f"  [✓] Archived {result['archived']} cold records to {result['archive_file']}")
    print(f"  [✓] Sealed {result['sessions_sealed']} sessions")
    print(f"  [✓] Hot data cutoff: {hot_days} days")
    print(f"  [✓] DB compacted: {result['db_path']}")


def _cmd_archive_cieu(args: list) -> None:
    """Legacy: ystar archive-cieu — full export without deletion."""
    import sys

    experiment = None
    output_dir = DEFAULT_ARCHIVE_DIR
    db_path = DEFAULT_DB_PATH

    i = 0
    while i < len(args):
        if args[i] == "--experiment" and i + 1 < len(args):
            experiment = args[i + 1]
            i += 2
        elif args[i] == "--output-dir" and i + 1 < len(args):
            output_dir = args[i + 1]
            i += 2
        elif args[i] == "--db-path" and i + 1 < len(args):
            db_path = args[i + 1]
            i += 2
        else:
            i += 1

    db = Path(db_path)
    if not db.exists():
        print(f"  [✗] CIEU database not found: {db}")
        sys.exit(1)

    archive_dir = Path(output_dir)
    if experiment:
        archive_dir = Path("data/experiments")
        archive_file = archive_dir / f"{experiment}_cieu.jsonl"
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        archive_file = archive_dir / f"{today}.jsonl"

    archive_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM cieu_events ORDER BY created_at").fetchall()
    events = [dict(r) for r in rows]
    conn.close()

    with archive_file.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    meta_file = archive_dir / ".archive_metadata.json"
    metadata = {
        "last_archive": datetime.now().isoformat(),
        "archive_file": str(archive_file),
        "event_count": len(events),
        "experiment": experiment,
    }
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"  [✓] Archived {len(events)} CIEU events to {archive_file}")
    print(f"  [✓] Metadata saved to {meta_file}")

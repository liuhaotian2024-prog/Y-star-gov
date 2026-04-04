# ystar/cli/report_cmd.py — report, verify, seal, audit commands
"""
Report, verification, sealing, and audit commands.
Moved from ystar/_cli.py for modularization.
"""
import sys
import json
import pathlib
from typing import Optional


def _auto_detect_db_path() -> Optional[str]:
    """Try to read .ystar_session.json from cwd and extract cieu_db path."""
    for d in [pathlib.Path.cwd(), pathlib.Path.home()]:
        cfg_path = d / ".ystar_session.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                db = cfg.get("cieu_db")
                if db:
                    return db
            except Exception:
                pass
    return None


def _cmd_audit(args: list) -> None:
    """
    Causal audit report: intent contract vs actual actions.
    """
    session_id = None
    db_path    = ".ystar_cieu.db"
    limit      = 10

    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]; i += 2
        elif args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]; i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(db_path)
    except Exception as e:
        print(f"\n  Cannot open database {db_path}: {e}\n")
        return

    if store.count() == 0:
        print()
        print("  CIEU database is empty. Run your Agent first.")
        print()
        return

    stats = store.stats(session_id=session_id)
    total_n    = stats.get("total", 0)
    by_dec     = stats.get("by_decision", {})
    allow_n    = by_dec.get("allow", 0)
    deny_n     = by_dec.get("deny", 0)
    escalate_n = by_dec.get("escalate", 0)

    print()
    print("  Y* Causal Audit Report")
    print("  " + "=" * 50)
    if session_id:
        print(f"  Session: {session_id}")
    print()

    # Seal verification
    if session_id:
        vr = store.verify_session_seal(session_id)
        if "error" in vr or "valid" not in vr:
            seal_line = "Not sealed -- run `ystar seal --session` to generate cryptographic proof"
        elif vr["valid"]:
            root_short = vr["stored_root"][:16]
            seal_line  = (f"Sealed (Merkle root: {root_short}...  "
                          f"events: {vr['stored_count']})")
        else:
            tamper = vr.get("tamper_evidence", "unknown reason")
            seal_line = f"SEAL VERIFICATION FAILED -- {tamper}"
        print(f"  Seal status: {seal_line}")
        print()

    # Summary
    print("  Summary")
    print("  " + "-" * 50)
    print(f"  Audit events total:    {total_n} (with full parameter snapshots)")
    print(f"  Allowed:               {allow_n}")
    print(f"  Denied (blocked):      {deny_n}")
    if escalate_n:
        print(f"  Escalated:             {escalate_n}")

    # Violation dimension distribution
    top_viols = stats.get("top_violations", [])
    if top_viols:
        print()
        print("  Violation Dimensions")
        for dim, count in top_viols:
            bar = "=" * min(count * 2, 20)
            print(f"    {dim:<20} {bar} {count}")

    # Consistency conclusion
    print()
    if deny_n == 0 and escalate_n == 0:
        print("  Intent-action consistency: All operations within contract bounds")
    else:
        print(f"  Intent-action consistency: {deny_n + escalate_n} out-of-bounds operation(s) blocked")
    print()

    # Violation scene replay
    deny_records = store.query(
        session_id=session_id,
        decision="deny",
        limit=limit,
    )
    if not deny_records:
        print("  (No violations in this session)")
        print()
        return

    print(f"  Violation Details (most recent {min(limit, len(deny_records))})")
    print("  " + "-" * 50)

    import datetime
    for idx, r in enumerate(deny_records, 1):
        ts = datetime.datetime.fromtimestamp(r.created_at).strftime("%m-%d %H:%M:%S")
        target = (r.file_path or r.command or r.url or r.event_type or "?")
        if len(target) > 45:
            target = target[:42] + "..."

        # Extract dimension from violations structure
        # Handle two formats:
        # 1. New format: [{'reason': '{"action": "block", "violations": [...]}'}]
        # 2. Old format: [{'dimension': 'deny', 'message': '...'}]
        dim = "?"
        reason_msg = "?"
        if r.violations:
            try:
                viol = r.violations[0] if isinstance(r.violations, list) else r.violations

                # Format 1: violations with nested 'reason' JSON string
                if isinstance(viol, dict) and 'reason' in viol:
                    try:
                        # Handle Python literal syntax (single quotes)
                        import ast
                        reason_data = ast.literal_eval(viol['reason'])
                        if 'violations' in reason_data and reason_data['violations']:
                            dim = reason_data['violations'][0].get('dimension', '?')
                            reason_msg = reason_data['violations'][0].get('message', '?')
                        else:
                            reason_msg = reason_data.get('message', '?')
                            # Try to infer dimension from message
                            if 'denied' in viol.get('reason', '').lower():
                                dim = 'denied'
                    except (ValueError, SyntaxError):
                        # Fallback: try JSON parsing
                        try:
                            reason_data = json.loads(viol['reason'].replace("'", '"'))
                            if 'violations' in reason_data and reason_data['violations']:
                                dim = reason_data['violations'][0].get('dimension', '?')
                                reason_msg = reason_data['violations'][0].get('message', '?')
                        except Exception:
                            pass

                # Format 2: direct dimension key
                elif isinstance(viol, dict) and 'dimension' in viol:
                    dim = viol['dimension']
                    reason_msg = viol.get('message', '?')

            except Exception:
                pass

        print(f"  [{idx}] {ts}  {r.agent_id}")
        print(f"       Dimension: {dim}")
        print(f"       Target:    {target}")

        if r.violations:
            print(f"       Reason:    {reason_msg}")

        if r.params_json:
            try:
                params = json.loads(r.params_json)
                shown = {}
                for key in ("file_path", "command", "url", "amount",
                            "risk_approved", "action"):
                    if key in params and params[key] not in (None, ""):
                        val = params[key]
                        if isinstance(val, str) and len(val) > 40:
                            val = val[:37] + "..."
                        shown[key] = val
                if shown:
                    param_str = "  ".join(f"{k}={repr(v)}" for k, v in shown.items())
                    print(f"       Params:    {param_str}")
            except Exception:
                pass

        meta_parts = []
        if r.human_initiator:
            meta_parts.append(f"initiator: {r.human_initiator}")
        if r.lineage_path:
            try:
                chain = json.loads(r.lineage_path)
                meta_parts.append("chain: " + " -> ".join(chain))
            except Exception:
                pass
        if meta_parts:
            print(f"       {' | '.join(meta_parts)}")

        print()

    if deny_n > limit:
        print(f"  ... {deny_n - limit} more, use --limit {deny_n} to see all")
        print()


def _cmd_verify(args: list) -> None:
    """
    ystar verify [--db <path>] [--session <id>]
    Verify CIEU database cryptographic integrity.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="ystar verify")
    parser.add_argument("--db", default=_auto_detect_db_path() or ".ystar_cieu.db", help="CIEU DB path")
    parser.add_argument("--session", default=None, help="Session ID")
    parser.add_argument("--seal", action="store_true", help="Seal before verifying")
    parsed = parser.parse_args(args)

    print()
    print("  Y*gov Verify -- CIEU Integrity Check")
    print("  " + "-" * 41)
    print()

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(parsed.db)
        stats = store.stats()
        print(f"  Database: {parsed.db}")
        print(f"  Total records: {stats['total']}")
        print()

        if parsed.seal or parsed.session:
            target = parsed.session or "default"
            if parsed.seal:
                print(f"  Sealing session '{target}'...")
                seal_result = store.seal_session(target)
                if seal_result.get("event_count", 0) == 0:
                    print(f"  No records found for session '{target}'")
                else:
                    print(f"  Sealed: {seal_result['event_count']} events")
                    print(f"     Merkle root: {seal_result['merkle_root'][:32]}...")
                    if seal_result.get("prev_root"):
                        print(f"     Chain link:  {seal_result['prev_root'][:32]}...")
                print()

            if parsed.session:
                print(f"  Verifying session '{parsed.session}'...")
                v = store.verify_session_seal(parsed.session)
                if v.get("valid"):
                    print(f"  Integrity OK: {v.get('stored_count',0)} events verified")
                    print(f"     Root: {v.get('stored_root','?')[:32]}...")
                else:
                    print(f"  INTEGRITY FAILURE")
                    print(f"     Expected: {v.get('stored_root','?')[:32]}...")
                    print(f"     Computed: {v.get('computed_root','?')[:32]}...")
                    if v.get("count_mismatch"):
                        print(f"     Record count mismatch: stored={v.get('stored_count')} "
                              f"current={v.get('current_count')}")
        else:
            print("  Usage examples:")
            print("    ystar verify --db .ystar_cieu.db --seal --session my_session")
            print("    ystar verify --db .ystar_cieu.db --session my_session")
            print()
            print("  Tip: use 'ystar seal' to auto-seal the current session")

    except Exception as e:
        print(f"  Error: {e}")
    print()


def _cmd_seal(args: list) -> None:
    """
    ystar seal [--db <path>] [--session <id>]
    Seal current session CIEU records, generate Merkle root.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="ystar seal")
    parser.add_argument("--db", default=None, help="CIEU DB path")
    parser.add_argument("--session", default=None, help="Session ID")
    parsed = parser.parse_args(args)

    db_path = parsed.db
    session_id = parsed.session
    if not db_path or not session_id:
        for d in [pathlib.Path.cwd(), pathlib.Path.home()]:
            cfg_path = d / ".ystar_session.json"
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text())
                    db_path = db_path or cfg.get("cieu_db", ".ystar_cieu.db")
                    session_id = session_id or cfg.get("session_id", "default")
                    break
                except Exception:
                    pass
    db_path = db_path or ".ystar_cieu.db"
    session_id = session_id or "default"

    print()
    print("  Y*gov Seal -- Seal CIEU Records")
    print(f"  Database: {db_path}")
    print(f"  Session:  {session_id}")
    print()

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(db_path)
        result = store.seal_session(session_id)

        if result.get("event_count", 0) == 0:
            print(f"  No records found for session '{session_id}'")
        else:
            print(f"  Sealed {result['event_count']} events")
            print(f"     Merkle root: {result['merkle_root']}")
            if result.get("prev_root"):
                print(f"     Chain prev:  {result['prev_root'][:32]}...")
            print()
            print(f"  Run 'ystar verify --session {session_id}' to confirm integrity")
    except Exception as e:
        print(f"  Seal failed: {e}")
    print()


def _cmd_report_enhanced(args: list) -> None:
    """
    ystar report [--db <path>] [--format json|text|md]
    Enhanced report: full CIEU telemetry analysis.
    """
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(prog="ystar report")
    parser.add_argument("--db", default=".ystar_cieu.db")
    parser.add_argument("--format", default="text", choices=["text", "json", "md"])
    parser.add_argument("positional", nargs="?", default=None,
                        help="DB path (compat: ystar report path.db)")
    parsed = parser.parse_args(args)

    db_path = parsed.positional or parsed.db

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(db_path)
        stats = store.stats()
    except Exception as e:
        print(f"Cannot open database: {e}")
        return

    total = stats.get("total", 0)
    if total == 0:
        print("No CIEU records found.")
        return

    by_decision = stats.get("by_decision", {})
    allow_n = by_decision.get("allow", 0)
    deny_n  = by_decision.get("deny", 0)
    esc_n   = by_decision.get("escalate", 0)

    top_blocked = []
    omission_stats = []
    agent_stats = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT COALESCE(file_path, command, url, 'unknown') as target,
                   COUNT(*) as cnt
            FROM cieu_events
            WHERE decision = 'deny'
            GROUP BY target
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()
        top_blocked = [(r["target"], r["cnt"]) for r in rows]

        omission_rows = conn.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM cieu_events
            WHERE event_type LIKE '%omission%' OR event_type LIKE '%overdue%'
               OR event_type LIKE '%violation%'
            GROUP BY event_type
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()
        omission_stats = [(r["event_type"], r["cnt"]) for r in omission_rows]

        agent_rows = conn.execute("""
            SELECT agent_id, COUNT(*) as total,
                   SUM(CASE WHEN decision='deny' THEN 1 ELSE 0 END) as denied
            FROM cieu_events
            GROUP BY agent_id
            ORDER BY total DESC
            LIMIT 10
        """).fetchall()
        agent_stats = [(r["agent_id"], r["total"], r["denied"]) for r in agent_rows]
        conn.close()
    except Exception:
        pass

    if parsed.format == "json":
        output = {
            "total": total,
            "allow": allow_n,
            "deny": deny_n,
            "escalate": esc_n,
            "deny_rate": round(deny_n / max(total, 1), 3),
            "top_blocked_paths": [{"path": p, "count": c} for p, c in top_blocked],
            "omission_events": [{"type": t, "count": c} for t, c in omission_stats],
            "agents": [{"id": a, "total": t, "denied": d} for a, t, d in agent_stats],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    sep = "-" * 50
    h = "##" if parsed.format == "md" else " "

    print()
    print(f"{h} Y*gov CIEU Report -- {db_path}")
    print(sep)
    print(f"  Total decisions : {total:,}")
    print(f"  Allow           : {allow_n:,}  ({allow_n/max(total,1):.1%})")
    print(f"  Deny            : {deny_n:,}   ({deny_n/max(total,1):.1%})")
    if esc_n:
        print(f"  Escalate        : {esc_n:,}  ({esc_n/max(total,1):.1%})")

    if top_blocked:
        print()
        print(f"{h} Top Blocked Paths/Commands")
        print(sep)
        for path, cnt in top_blocked:
            bar = "=" * min(cnt, 30)
            print(f"  {cnt:5d}  {bar}  {path[:60]}")

    if agent_stats:
        print()
        print(f"{h} By Agent")
        print(sep)
        print(f"  {'Agent':<30} {'Total':>8} {'Denied':>8} {'Deny%':>7}")
        for agent_id, total_a, denied_a in agent_stats:
            pct = f"{denied_a/max(total_a,1):.0%}"
            print(f"  {agent_id:<30} {total_a:>8,} {denied_a:>8,} {pct:>7}")

    if omission_stats:
        print()
        print(f"{h} Omission / Obligation Events")
        print(sep)
        for etype, cnt in omission_stats:
            print(f"  {cnt:5d}  {etype}")

    print()

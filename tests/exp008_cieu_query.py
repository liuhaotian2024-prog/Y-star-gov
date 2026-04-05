"""Query CIEU records from EXP-008 v3."""
import sqlite3
import json
from datetime import datetime

DB = ".ystar_cieu.db"

# v3 ran from ~04:40 to ~04:46 UTC on 2026-04-05
# That's epoch ~1775362800 to ~1775363160
V3_START = 1775362800  # 04:40 UTC
V3_END   = 1775363200  # 04:46 UTC

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Total records in window
total = conn.execute(
    "SELECT COUNT(*) FROM cieu_events WHERE created_at > ? AND created_at < ?",
    (V3_START, V3_END)
).fetchone()[0]
print(f"EXP-008 v3 CIEU records: {total}")
print(f"Time window: {datetime.fromtimestamp(V3_START).isoformat()} to {datetime.fromtimestamp(V3_END).isoformat()}")

# Group by event_type, decision
print(f"\n=== By event_type + decision ===")
rows = conn.execute("""
    SELECT event_type, decision, COUNT(*) as cnt
    FROM cieu_events
    WHERE created_at > ? AND created_at < ?
    GROUP BY event_type, decision
    ORDER BY cnt DESC
""", (V3_START, V3_END)).fetchall()

for r in rows:
    print(f"  {r['event_type']:<35} {r['decision']:<10} {r['cnt']:>5}")

# Deny records detail
print(f"\n=== DENY records ===")
denies = conn.execute("""
    SELECT agent_id, event_type, decision, command, violations, created_at
    FROM cieu_events
    WHERE created_at > ? AND created_at < ? AND decision = 'deny'
    ORDER BY created_at
""", (V3_START, V3_END)).fetchall()

print(f"Total DENY: {len(denies)}")
for r in denies:
    ts = datetime.fromtimestamp(r['created_at']).strftime('%H:%M:%S')
    cmd = (r['command'] or '')[:50]
    agent = r['agent_id'] or ''
    viols = ''
    try:
        v = json.loads(r['violations']) if r['violations'] else []
        if v and isinstance(v, list) and isinstance(v[0], dict):
            viols = v[0].get('message', '')[:40]
    except:
        pass
    print(f"  [{ts}] {agent:<15} {r['event_type']:<25} {cmd or viols}")

# Check for auto_routed field
print(f"\n=== auto_routed field check ===")
# CIEU schema doesn't have an auto_routed column
# Check if any record has it in params_json or task_description
cols = conn.execute("PRAGMA table_info(cieu_events)").fetchall()
col_names = [c['name'] for c in cols]
print(f"CIEU columns: {col_names}")
has_auto_routed = 'auto_routed' in col_names
print(f"Has auto_routed column: {has_auto_routed}")

if not has_auto_routed:
    print("  auto_routed is NOT a CIEU column.")
    print("  It exists only in GOV MCP gov_check responses,")
    print("  not in the PreToolUse hook CIEU records.")
    print("  The hook writes standard CIEU fields: agent_id, event_type, decision, etc.")

# Allow records
print(f"\n=== ALLOW records ===")
allows = conn.execute("""
    SELECT COUNT(*) FROM cieu_events
    WHERE created_at > ? AND created_at < ? AND decision = 'allow'
""", (V3_START, V3_END)).fetchone()[0]
print(f"Total ALLOW: {allows}")

# Summary
print(f"\n=== SUMMARY ===")
print(f"  Total records:     {total}")
print(f"  ALLOW:             {allows}")
print(f"  DENY:              {len(denies)}")
print(f"  Other:             {total - allows - len(denies)}")
print(f"  auto_routed field: NOT in CIEU schema (GOV MCP concept only)")

conn.close()

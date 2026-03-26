---
name: ystar-report
description: >
  Generate a Y*gov governance report from CIEU audit data.
  Use when user asks for: governance report, audit log, compliance summary,
  CIEU analysis, what was blocked, deny rate, agent activity report,
  ystar report, who accessed what, delegation history.
disable-model-invocation: false
allowed-tools: Bash, Read
---

# Y*gov CIEU Report

Generate a governance report from the CIEU audit database.

## Step 1: Find the database

```bash
# Look for CIEU database in common locations
ls -la .ystar_cieu.db 2>/dev/null || \
ls -la ~/.ystar/*.db 2>/dev/null || \
echo "No CIEU database found"
```

## Step 2: Generate the report

If Y*gov is installed:

```bash
ystar report --db .ystar_cieu.db --format text 2>/dev/null || \
python3 -c "
import os, sys
db = '.ystar_cieu.db'
if not os.path.exists(db):
    print('No CIEU database found. Run some Claude Code sessions with Y*gov active first.')
    sys.exit(0)
try:
    from ystar.governance.cieu_store import CIEUStore
    store = CIEUStore(db)
    stats = store.stats()
    total = stats.get('total', 0)
    by_decision = stats.get('by_decision', {})
    allow_n = by_decision.get('allow', 0)
    deny_n  = by_decision.get('deny', 0)
    print(f'Y*gov CIEU Report')
    print(f'─' * 40)
    print(f'Total decisions : {total:,}')
    print(f'Allow           : {allow_n:,} ({allow_n/max(total,1):.0%})')
    print(f'Deny            : {deny_n:,} ({deny_n/max(total,1):.0%})')
    print()
    if total == 0:
        print('No records yet. Governance checks will appear here once active.')
except ImportError:
    print('Y*gov not installed. Run: pip install ystar')
"
```

## Step 3: Present the results

Show the report clearly. If there are DENY decisions, list the top blocked paths or commands. If there are no records, explain that Y*gov needs to be active during Claude Code sessions to generate data.

Offer to:
- Seal the current session: `ystar seal --session default`
- Verify integrity: `ystar verify --session default`
- Export data: `ystar report --format json > governance_report.json`

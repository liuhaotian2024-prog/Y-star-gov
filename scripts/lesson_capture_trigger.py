#!/usr/bin/env python3
"""
scripts/lesson_capture_trigger.py
==================================
Auto-trigger lesson capture when DRIFT events spike.

Logic:
- Query .ystar_cieu.db for DRIFT event count in last 7d
- If count > 3x baseline (7d rolling average from prior 4 weeks), emit LESSON_CAPTURE_DUE
- Create stub file knowledge/lessons/drift_YYYYMMDD.md with trigger context
- Schedule: cron @daily or every 6h

Usage:
    python3 scripts/lesson_capture_trigger.py [--db PATH] [--threshold N]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


def get_drift_count(db_path: Path, days: int = 7) -> int:
    """Count DRIFT events in last N days."""
    cutoff = time.time() - (days * 86400)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM cieu_log
        WHERE event_type = 'DRIFT'
        AND timestamp >= ?
    """, (cutoff,))

    count = cur.fetchone()[0]
    conn.close()
    return count


def get_baseline_drift_rate(db_path: Path, weeks: int = 4) -> float:
    """Calculate 7d rolling average DRIFT count from prior N weeks."""
    end_time = time.time() - (7 * 86400)  # Start 7d ago (exclude current week)
    start_time = end_time - (weeks * 7 * 86400)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) FROM cieu_log
        WHERE event_type = 'DRIFT'
        AND timestamp >= ?
        AND timestamp < ?
    """, (start_time, end_time))

    total_count = cur.fetchone()[0]
    conn.close()

    # Average per 7d window
    return total_count / weeks if weeks > 0 else 0


def emit_lesson_capture_event(db_path: Path, context: dict):
    """Emit LESSON_CAPTURE_DUE event to CIEU log."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO cieu_log
        (timestamp, event_type, agent_id, action, outcome, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        time.time(),
        "LESSON_CAPTURE_DUE",
        "system",
        "drift_spike_detected",
        "triggered_lesson_capture",
        str(context),
    ))

    conn.commit()
    conn.close()


def create_lesson_stub(output_dir: Path, context: dict):
    """Create lesson capture stub file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    stub_path = output_dir / f"drift_{datetime.now().strftime('%Y%m%d')}.md"

    content = f"""# DRIFT Spike Lesson Capture — {datetime.now().strftime('%Y-%m-%d')}

**Auto-triggered by lesson_capture_trigger.py**

## Trigger Context

- Current 7d DRIFT count: {context['current_count']}
- Baseline (4w avg): {context['baseline']:.1f}
- Spike ratio: {context['spike_ratio']:.1f}x
- Threshold: {context['threshold']}x

## Analysis Required

1. **What changed?** Identify system/process/agent changes in last 7 days.
2. **Root cause?** Why did DRIFT events spike now?
3. **Pattern?** Is this a recurring pattern or one-time event?
4. **Fix?** What needs to change to prevent future spikes?

## CIEU Query Commands

```bash
# Get all DRIFT events from last 7d
ystar recall --event-type DRIFT --days 7

# Causal chain analysis
python3 scripts/cieu_trace.py --event-type DRIFT --limit 20
```

## Next Steps

- [ ] CEO/CTO review DRIFT events
- [ ] Identify root cause
- [ ] Update AGENTS.md or governance rules if needed
- [ ] Archive this file to knowledge/lessons/archive/ when resolved
"""

    stub_path.write_text(content)
    print(f"[LESSON_STUB] Created: {stub_path}")


def main():
    parser = argparse.ArgumentParser(description="DRIFT spike detector + lesson capture trigger")
    parser.add_argument("--db", type=Path, default=Path.cwd() / ".ystar_cieu.db", help="Path to CIEU database")
    parser.add_argument("--threshold", type=float, default=3.0, help="Spike threshold (multiple of baseline)")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "knowledge/lessons", help="Lesson stub output directory")
    parser.add_argument("--quiet", action="store_true", help="Suppress output (for cron)")

    args = parser.parse_args()

    if not args.db.exists():
        if not args.quiet:
            print(f"[ERROR] CIEU database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    # Get current 7d DRIFT count
    current_count = get_drift_count(args.db, days=7)

    # Get baseline (4-week rolling average)
    baseline = get_baseline_drift_rate(args.db, weeks=4)

    # Calculate spike ratio
    spike_ratio = current_count / baseline if baseline > 0 else 0

    if not args.quiet:
        print(f"[DRIFT CHECK] Current 7d: {current_count}, Baseline: {baseline:.1f}, Ratio: {spike_ratio:.1f}x")

    # Trigger if spike > threshold
    if spike_ratio >= args.threshold:
        context = {
            "current_count": current_count,
            "baseline": baseline,
            "spike_ratio": spike_ratio,
            "threshold": args.threshold,
        }

        emit_lesson_capture_event(args.db, context)
        create_lesson_stub(args.output_dir, context)

        if not args.quiet:
            print(f"[LESSON_CAPTURE_DUE] DRIFT spike detected ({spike_ratio:.1f}x threshold). Lesson stub created.")
        sys.exit(2)  # Exit code 2 = lesson capture triggered

    else:
        if not args.quiet:
            print("[OK] No DRIFT spike detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()

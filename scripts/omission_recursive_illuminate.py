#!/usr/bin/env python3
"""
omission_recursive_illuminate.py  --  CLI for OmissionEngine Level 2 + Level 3
==============================================================================

Board directive 2026-04-19:
  "有了就要照亮更多的无" -- each shipped feature MUST illuminate at least one
  new absence. This script is the recursive illumination engine.

Level 2 (manifest self-audit, "无的无"):
  Scans CIEU for DENY/ERROR/VIOLATION event types that the phase lifecycle
  manifest does not reference. These are unnamed failure categories -- gaps
  in the manifest's own awareness.

Level 3 (downstream obligation derivation, "无的生成性"):
  Given a shipped feature, traverses the 6D ecosystem entanglement map and
  checks whether downstream artifacts (tests, docs, backup plans) exist.
  Missing artifacts become new obligations.

Usage:
  python3 scripts/omission_recursive_illuminate.py --feature arch18_cieu_brain
  python3 scripts/omission_recursive_illuminate.py --feature arch18_cieu_brain --window-days 14
  python3 scripts/omission_recursive_illuminate.py --feature arch18_cieu_brain --json

Output: JSON with two top-level keys:
  - "level2_manifest_audit": gaps the manifest doesn't name
  - "level3_derived_obligations": missing downstream artifacts
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure ystar package is importable
_ystar_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ystar_root))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OmissionEngine Recursive Illumination (Level 2 + Level 3)",
    )
    parser.add_argument(
        "--feature",
        required=True,
        help="Feature ID to illuminate (e.g. arch18_cieu_brain)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="CIEU lookback window in days (default: 7)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to phase_lifecycle_manifest.yaml (auto-detected if omitted)",
    )
    parser.add_argument(
        "--cieu-db",
        default=None,
        help="Path to .ystar_cieu.db (auto-detected if omitted)",
    )
    parser.add_argument(
        "--k9-path",
        default=None,
        help="Path to K9Audit repo (default: /tmp/K9Audit)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON (default: human-readable)",
    )
    args = parser.parse_args()

    # Resolve paths
    ystar_gov_root = str(_ystar_root)
    labs_root = str(_ystar_root.parent / "ystar-company")

    manifest_path = args.manifest or str(
        _ystar_root / "docs" / "arch" / "phase_lifecycle_manifest.yaml"
    )

    # Auto-detect CIEU DB: prefer ystar-company (real operational data), fallback to Y-star-gov
    cieu_db_path = args.cieu_db
    if cieu_db_path is None:
        candidates = [
            Path(labs_root) / ".ystar_cieu.db",
            _ystar_root / ".ystar_cieu.db",
        ]
        for c in candidates:
            if c.exists():
                cieu_db_path = str(c)
                break
        if cieu_db_path is None:
            cieu_db_path = str(candidates[0])  # Will produce empty results

    k9_path = args.k9_path or "/tmp/K9Audit"

    # ── Level 2: Manifest Self-Audit ──────────────────────────────────────
    from ystar.governance.omission_engine import audit_manifest_completeness

    level2_result = audit_manifest_completeness(
        manifest_path=manifest_path,
        cieu_db_path=cieu_db_path,
        window_days=args.window_days,
    )

    # ── Level 3: Downstream Obligation Derivation ─────────────────────────
    from ystar.governance.omission_engine import derive_new_obligations_from_ship

    ship_event = {
        "feature_id": args.feature,
        "event_type": f"{args.feature}_shipped",
    }

    level3_result = derive_new_obligations_from_ship(
        ship_event=ship_event,
        manifest_path=manifest_path,
        k9_adapter_path=k9_path,
        ystar_gov_root=ystar_gov_root,
        labs_root=labs_root,
    )

    # ── Assemble output ──────────────────────────────────────────────────
    output = {
        "feature": args.feature,
        "window_days": args.window_days,
        "level2_manifest_audit": level2_result,
        "level3_derived_obligations": level3_result,
        "summary": {
            "uncovered_failure_types": len(level2_result.get("gaps", [])),
            "derived_obligations": len(level3_result.get("derived_obligations", [])),
            "k9_causal_obligations": len(level3_result.get("k9_causal_obligations", [])),
            "total_new_absences_illuminated": (
                len(level2_result.get("gaps", []))
                + len(level3_result.get("derived_obligations", []))
                + len(level3_result.get("k9_causal_obligations", []))
            ),
            "meta_events_emitted": (
                level2_result.get("meta_events_emitted", 0)
                + level3_result.get("meta_events_emitted", 0)
            ),
        },
    }

    if args.json_output:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print("=" * 72)
        print(f"  OmissionEngine Recursive Illumination: {args.feature}")
        print(f"  Window: {args.window_days} days  |  CIEU DB: {cieu_db_path}")
        print("=" * 72)
        print()

        # Level 2
        gaps = level2_result.get("gaps", [])
        print(f"--- Level 2: Manifest Self-Audit ({len(gaps)} uncovered failure types) ---")
        if gaps:
            for g in gaps:
                print(f"  [GAP] {g['failure_type']} (count={g['count']})")
                print(f"        suggested_marker: {g['suggested_marker']}")
        else:
            print("  (no uncovered failure types)")
        print()

        # Level 3
        derived = level3_result.get("derived_obligations", [])
        k9_derived = level3_result.get("k9_causal_obligations", [])
        print(f"--- Level 3: Derived Obligations ({len(derived)} from ecosystem, "
              f"{len(k9_derived)} from K9) ---")
        if derived:
            for d in derived:
                print(f"  [MISSING] {d['missing_artifact']} ({d['priority']})")
                print(f"            reason: {d['reason']}")
                print(f"            source: {d['source_node']}")
        if k9_derived:
            for d in k9_derived:
                print(f"  [K9]      {d['missing_artifact']} ({d['priority']})")
                print(f"            reason: {d['reason']}")
        if not derived and not k9_derived:
            print("  (no missing downstream artifacts)")
        print()

        # Summary
        s = output["summary"]
        print("--- Summary ---")
        print(f"  Total new absences illuminated: {s['total_new_absences_illuminated']}")
        print(f"  CIEU meta-events emitted:       {s['meta_events_emitted']}")
        print(f"  K9 integration used:            {level3_result.get('k9_used', False)}")

        if s["total_new_absences_illuminated"] == 0:
            print()
            print("  WARNING: Zero absences illuminated. The recursive illumination")
            print("  engine is broken if 有 produces no new 无.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
omission_knowledge_action_scan.py — CLI for Level 4 Knowledge-Action Gap Detection

Usage:
    python3 scripts/omission_knowledge_action_scan.py [--window SECONDS] [--registry PATH] [--cieu-db PATH]

Board 2026-04-19: "OmissionEngine 也应该是知行合一的重要引擎"
Wang Yangming: knowing X without doing X = omission failure.
"""
import argparse
import json
import sys
import os

# Ensure the ystar package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar.governance.omission_engine import (
    detect_knowledge_action_gaps,
    enumerate_open_knowledge_action_gaps,
)


def main():
    parser = argparse.ArgumentParser(
        description="Scan CIEU for knowledge-action gaps (knowing X without doing X)"
    )
    parser.add_argument(
        "--window", type=int, default=3600,
        help="Scan window in seconds (default: 3600 = 1 hour)"
    )
    parser.add_argument(
        "--registry", type=str, default=None,
        help="Path to knowledge_action_registry.yaml (default: docs/arch/)"
    )
    parser.add_argument(
        "--cieu-db", type=str, default=None,
        help="Path to .ystar_cieu.db (auto-detected if omitted)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw JSON instead of formatted text"
    )
    args = parser.parse_args()

    result = detect_knowledge_action_gaps(
        cieu_db_path=args.cieu_db,
        registry_path=args.registry,
        cieu_window_sec=args.window,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    # Formatted output
    print("=" * 60)
    print("Knowledge-Action Gap Scan (知行合一)")
    print("=" * 60)
    print(f"Rules checked:         {result['rules_checked']}")
    print(f"Trigger events found:  {result['total_triggers_found']}")
    print(f"Gaps detected:         {result['total_gaps']}")
    print(f"Obligations registered:{result['obligations_registered']}")
    print()

    if result["gaps"]:
        print("DETECTED GAPS:")
        print("-" * 60)
        for i, gap in enumerate(result["gaps"], 1):
            print(f"  [{i}] {gap['knowledge_id']}")
            print(f"      Trigger:  {gap['trigger_event_type']}")
            print(f"      Required: {gap['required_action']}")
            print(f"      Window:   {gap['detection_window_sec']}s")
            print(f"      Severity: {gap['severity']}")
            if gap.get("description"):
                desc = gap["description"][:80]
                print(f"      Desc:     {desc}")
            print()
    else:
        print("No knowledge-action gaps detected in the scan window.")
        print("(This could mean: no matching trigger events, or all triggers")
        print(" had their required actions within the detection window.)")

    # Also show the enumerated gap tags
    tags = enumerate_open_knowledge_action_gaps(
        cieu_db_path=args.cieu_db,
        registry_path=args.registry,
        cieu_window_sec=args.window,
    )
    if tags:
        print("Gap tags:")
        for tag in tags:
            print(f"  - {tag}")


if __name__ == "__main__":
    main()

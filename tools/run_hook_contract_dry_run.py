#!/usr/bin/env python3
"""CLI dry-run entrypoint for hook contract envelopes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ystar.governance.hook_contract_adapter import run_hook_contract_dry_run


EXIT_CODES = {
    "allow": 0,
    "warn": 0,
    "require_revision": 2,
    "deny": 3,
    "escalate": 4,
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic hook contract dry-run against a JSON envelope."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSON hook-like envelope file.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Emit indented JSON.",
    )
    parser.add_argument(
        "--strict-exit-codes",
        action="store_true",
        help="Use decision-specific exit codes. This is the default v0 behavior.",
    )
    return parser.parse_args(argv)


def load_envelope(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object.")
    return data


def output_for_result(result) -> dict[str, Any]:
    envelope = result.hook_decision_envelope
    return {
        "tool": "hook_contract_dry_run",
        "dry_run_only": True,
        "non_execution_confirmation": True,
        "hook_event_id": envelope.get("hook_event_id"),
        "packet_id": envelope.get("packet_id"),
        "agent_id": envelope.get("agent_id"),
        "decision": envelope.get("decision"),
        "allow_execution": envelope.get("allow_execution"),
        "require_revision": envelope.get("require_revision"),
        "deny": envelope.get("deny"),
        "escalate": envelope.get("escalate"),
        "issues": envelope.get("issues", []),
        "safety_notes": envelope.get("safety_notes", []),
        "governance_result_summary": envelope.get("governance_result_summary", {}),
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        envelope = load_envelope(Path(args.input))
        result = run_hook_contract_dry_run(envelope)
        payload = output_for_result(result)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"hook_contract_dry_run error: {exc}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    print(json.dumps(payload, indent=indent, sort_keys=True))
    return EXIT_CODES.get(str(payload.get("decision")), 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

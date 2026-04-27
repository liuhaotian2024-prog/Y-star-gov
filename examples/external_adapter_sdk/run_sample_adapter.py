#!/usr/bin/env python3
"""Run the generic external adapter SDK sample through the hook dry-run CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SDK_DIR = Path(__file__).resolve().parent
ROOT = SDK_DIR.parents[1]
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from external_request_to_envelope import normalize_external_request_to_hook_envelope


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the generic external adapter SDK sample.")
    parser.add_argument("--request", default=str(SDK_DIR / "sample_external_request.json"))
    parser.add_argument("--config", default=str(SDK_DIR / "sample_adapter_config.json"))
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    request = load_json(Path(args.request))
    config = load_json(Path(args.config))
    envelope = normalize_external_request_to_hook_envelope(request, config)

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
        json.dump(envelope, handle)
        handle.flush()
        command = [
            "python3",
            str(ROOT / "tools" / "run_hook_contract_dry_run.py"),
            "--input",
            handle.name,
        ]
        if args.pretty:
            command.append("--pretty")
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            check=False,
        )

    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    print(result.stdout, end="")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""
ystar.czl.cli — `ystar czl ...` subcommand entry

Wires the loop, scenarios, and backends into the `ystar` CLI.

Subcommands:
    ystar czl run --scenario X --backend Y --workspace DIR
    ystar czl list-scenarios
    ystar czl list-backends
    ystar czl undo
    ystar czl benchmark --scenario X --arms A,B,C --trials N

Toast UI uses a 5-second non-blocking countdown on stdin via `select`.
Falls back to "always-yes" if stdin is not a terminal (CI environments).
"""
from __future__ import annotations

import argparse
import os
import select
import sys
import time
from typing import Optional

from ystar.czl import (
    list_scenarios as _list_scenarios,
    list_backends as _list_backends,
    get_scenario,
    get_backend,
)
from ystar.czl.loop import CZLRun, run_scenario
from ystar.czl.backends.base import BackendRegistry


def _terminal_toast(prompt: str, timeout: float, default_yes: bool) -> bool:
    """5-second informational toast. Default yes after timeout.

    Returns True if user accepted (Enter or timeout-default-yes),
    False if user rejected (any other key).
    """
    if not sys.stdin.isatty():
        # non-interactive (CI etc.) — auto-accept
        return default_yes

    sys.stdout.write("\n" + prompt + "\n")
    sys.stdout.flush()
    end = time.time() + timeout
    while time.time() < end:
        remaining = end - time.time()
        sys.stdout.write(f"\r[czl] auto-accepting in {remaining:.1f}s (press Enter to accept now, Esc/N to reject)... ")
        sys.stdout.flush()
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if ready:
            ch = sys.stdin.readline().strip().lower()
            sys.stdout.write("\n")
            if ch in ("", "y", "yes"):
                return True
            if ch in ("n", "no", "esc"):
                return False
    sys.stdout.write("\n")
    return default_yes


def cmd_run(args: argparse.Namespace) -> int:
    # Import scenarios + backends to trigger registry population
    import ystar.czl.scenarios  # noqa: F401  (registers built-ins)
    import ystar.czl.backends   # noqa: F401  (registers built-ins)

    scenario = get_scenario(args.scenario)
    if args.backend:
        backend = get_backend(args.backend)
    else:
        backend = BackendRegistry.auto_select()

    task_desc = args.task or input("Describe your task (one line): ")

    request = CZLRun(
        task_description=task_desc,
        scenario=scenario,
        backend=backend,
        workspace_dir=os.path.abspath(args.workspace),
        max_iterations=args.max_iterations,
        strict=args.strict,
        auto_undo_on_failure=not args.no_undo,
    )

    print(f"[czl] scenario={scenario.name} backend={backend.name} ({backend.tier}) workspace={request.workspace_dir}")
    result = run_scenario(request, toast_fn=_terminal_toast)

    # Print cost summary line — this is the marketing payload
    print(result.cost_summary_line)
    if not result.converged:
        print(f"[czl] failure_reason: {result.failure_reason}")
        return 1
    return 0


def cmd_list_scenarios(args: argparse.Namespace) -> int:
    import ystar.czl.scenarios  # noqa: F401
    names = _list_scenarios()
    if not names:
        print("(no scenarios registered)")
        return 0
    for n in names:
        s = get_scenario(n)
        print(f"  {n:20s}  {s.description}")
    return 0


def cmd_list_backends(args: argparse.Namespace) -> int:
    import ystar.czl.backends  # noqa: F401
    names = _list_backends()
    if not names:
        print("(no backends registered)")
        return 0
    for n in names:
        b = get_backend(n)
        avail = "AVAILABLE" if b.is_available() else "not configured"
        print(f"  {n:12s}  tier={b.tier:8s}  default_model={b.default_model:30s}  [{avail}]")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    """Pop the latest czl-pre-run stash."""
    import subprocess
    ws = os.path.abspath(args.workspace)
    proc = subprocess.run(
        ["git", "-C", ws, "stash", "list"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"[czl] not a git repo or git failed: {proc.stderr}")
        return 1
    # find latest czl-pre-run-* entry
    for i, line in enumerate(proc.stdout.splitlines()):
        if "czl-pre-run-" in line:
            stash_id = f"stash@{{{i}}}"
            proc2 = subprocess.run(
                ["git", "-C", ws, "stash", "pop", stash_id],
                capture_output=True, text=True,
            )
            if proc2.returncode == 0:
                print(f"[czl] reverted: {line}")
                return 0
            else:
                print(f"[czl] could not pop {stash_id}: {proc2.stderr}")
                return 1
    print("[czl] no czl-pre-run stash found")
    return 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Three-arm benchmark — see docs/CZL_PRODUCT_DESIGN.md §4."""
    print("[czl] benchmark is intentionally minimal in MVP; use `run` repeatedly")
    print("[czl] full three-arm orchestrator: benchmarks/czl_arbitrage/run_three_arm.py")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ystar czl", description="CZL — cheap-API + closure-loop arbitrage")
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run one CZL task")
    run_p.add_argument("--scenario", "-s", required=True, help="scenario name (see list-scenarios)")
    run_p.add_argument("--backend", "-b", default=None, help="backend name (default: auto-select cheapest available)")
    run_p.add_argument("--workspace", "-w", default=".", help="workspace directory (default: cwd)")
    run_p.add_argument("--task", "-t", default=None, help="task description (default: prompt)")
    run_p.add_argument("--max-iterations", type=int, default=10)
    run_p.add_argument("--strict", action="store_true", help="strict mode — always block on ambiguity")
    run_p.add_argument("--no-undo", action="store_true", help="don't auto-stash before run")
    run_p.set_defaults(func=cmd_run)

    sub.add_parser("list-scenarios", help="List registered scenarios").set_defaults(func=cmd_list_scenarios)
    sub.add_parser("list-backends", help="List registered backends and availability").set_defaults(func=cmd_list_backends)

    undo_p = sub.add_parser("undo", help="Revert last CZL run")
    undo_p.add_argument("--workspace", "-w", default=".")
    undo_p.set_defaults(func=cmd_undo)

    bench_p = sub.add_parser("benchmark", help="Three-arm comparison benchmark (A/B/C)")
    bench_p.add_argument("--scenario", "-s", required=True)
    bench_p.add_argument("--workspace", "-w", default=".")
    bench_p.add_argument("--arms", default="A,B,C")
    bench_p.add_argument("--trials", type=int, default=10)
    bench_p.set_defaults(func=cmd_benchmark)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

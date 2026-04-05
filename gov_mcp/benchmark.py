"""gov_benchmark — Token savings measurement for GOV MCP vs traditional tool calls.

Methodology:
  Mode A (Traditional): Each command is a separate LLM tool-call round-trip.
    The agent sends a request, the LLM decides to call Bash, the tool runs,
    the result is returned to the LLM, the LLM produces a response.
    Token cost = prompt_overhead + command_encoding + result_encoding per call.

  Mode B (gov_exec): A single MCP tool call batches all commands.
    The agent asks gov_exec to run a command list. The MCP server executes
    each command locally, applies governance checks, and returns results.
    Token cost = one tool call for the batch.

Token estimation:
  We don't have access to real LLM token counters from within the MCP server.
  Instead we use a calibrated model based on Anthropic's tokenizer characteristics:
    - 1 token ≈ 4 characters (English text / code)
    - Each Mode A round-trip includes: system prompt context window overhead,
      tool schema, the command, and the full stdout/stderr in the response.
    - Mode B includes: one tool call with command list + one response with all results.

  The overhead constants below are derived from observed Claude Code tool-call
  patterns (measured via CIEU records from Y*gov's own operations).
"""
from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Dict, List


# ── Token estimation constants ──────────────────────────────────────────────
# Calibrated from Y*gov EXP-001 data (README: 186,300 tokens for 117 tool calls)
# Average per-tool-call overhead ≈ 1,592 tokens

MODE_A_PER_CALL_OVERHEAD = 1_200   # Prompt context + tool schema per round-trip
MODE_A_COMMAND_FACTOR = 0.25       # tokens per character of command text
MODE_A_RESULT_FACTOR = 0.25        # tokens per character of stdout+stderr

MODE_B_BATCH_OVERHEAD = 800        # Single tool call overhead for the batch
MODE_B_PER_CMD_OVERHEAD = 50       # Per-command overhead within the batch
MODE_B_RESULT_FACTOR = 0.25        # tokens per character of results


# ── Benchmark tasks ─────────────────────────────────────────────────────────

DEFAULT_TASKS = [
    "git status",
    "pytest --version",
    "pip list",
    "ls ./",
    "git log --oneline -3",
]


def _estimate_tokens(text: str, factor: float = 0.25) -> int:
    """Estimate token count from text length."""
    return max(1, int(len(text) * factor))


def _run_command(cmd: str, timeout: int = 15) -> Dict[str, Any]:
    """Execute a command and return timing + output."""
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:4096],
            "stderr": proc.stderr[:2048],
            "elapsed_ms": round(elapsed_ms, 2),
            "success": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "command": cmd,
            "returncode": -1,
            "stdout": "",
            "stderr": f"timeout after {timeout}s",
            "elapsed_ms": round(elapsed_ms, 2),
            "success": False,
        }


def run_benchmark(
    tasks: List[str] | None = None,
    timeout_per_cmd: int = 15,
) -> Dict[str, Any]:
    """Run A/B benchmark comparing traditional tool calls vs gov_exec batch.

    Both modes execute the same commands via subprocess. The difference is
    in the token accounting: Mode A charges per-call LLM overhead for each
    command. Mode B charges a single batch overhead.

    Returns structured JSON with token estimates, timing, and recommendation.
    """
    if tasks is None:
        tasks = list(DEFAULT_TASKS)

    # ── Execute all commands (shared between both modes) ────────────────
    results = []
    for cmd in tasks:
        r = _run_command(cmd, timeout=timeout_per_cmd)
        results.append(r)

    # ── Mode A: Traditional (one LLM round-trip per command) ────────────
    mode_a_tokens = 0
    mode_a_time_ms = 0.0
    mode_a_successes = 0
    mode_a_details = []

    for r in results:
        cmd_tokens = _estimate_tokens(r["command"], MODE_A_COMMAND_FACTOR)
        result_tokens = _estimate_tokens(
            r["stdout"] + r["stderr"], MODE_A_RESULT_FACTOR
        )
        call_tokens = MODE_A_PER_CALL_OVERHEAD + cmd_tokens + result_tokens

        mode_a_tokens += call_tokens
        mode_a_time_ms += r["elapsed_ms"]
        if r["success"]:
            mode_a_successes += 1

        mode_a_details.append({
            "command": r["command"],
            "tokens": call_tokens,
            "elapsed_ms": r["elapsed_ms"],
            "success": r["success"],
        })

    # Add inter-call LLM thinking overhead (agent decides next command)
    # Estimated ~500 tokens of "thinking" between each tool call
    mode_a_thinking_overhead = (len(tasks) - 1) * 500
    mode_a_tokens += mode_a_thinking_overhead

    # Mode A wall time includes simulated LLM latency (~800ms per round-trip)
    mode_a_llm_latency = len(tasks) * 800
    mode_a_total_time_ms = mode_a_time_ms + mode_a_llm_latency

    # ── Mode B: gov_exec batch (single MCP tool call) ──────────────────
    mode_b_tokens = MODE_B_BATCH_OVERHEAD
    mode_b_time_ms = 0.0
    mode_b_successes = 0
    mode_b_details = []

    for r in results:
        cmd_tokens = MODE_B_PER_CMD_OVERHEAD + _estimate_tokens(
            r["command"], MODE_B_RESULT_FACTOR
        )
        result_tokens = _estimate_tokens(
            r["stdout"] + r["stderr"], MODE_B_RESULT_FACTOR
        )
        mode_b_tokens += cmd_tokens + result_tokens
        mode_b_time_ms += r["elapsed_ms"]
        if r["success"]:
            mode_b_successes += 1

        mode_b_details.append({
            "command": r["command"],
            "tokens": cmd_tokens + result_tokens,
            "elapsed_ms": r["elapsed_ms"],
            "success": r["success"],
        })

    # Mode B: only 1 LLM round-trip for the whole batch
    mode_b_total_time_ms = mode_b_time_ms + 800  # single round-trip

    # ── Compute savings ─────────────────────────────────────────────────
    savings_tokens = mode_a_tokens - mode_b_tokens
    savings_percent = round((savings_tokens / mode_a_tokens) * 100, 1) if mode_a_tokens > 0 else 0
    time_savings_percent = round(
        ((mode_a_total_time_ms - mode_b_total_time_ms) / mode_a_total_time_ms) * 100, 1
    ) if mode_a_total_time_ms > 0 else 0

    return {
        "task_count": len(tasks),
        "mode_a_tokens": mode_a_tokens,
        "mode_b_tokens": mode_b_tokens,
        "savings_tokens": savings_tokens,
        "savings_percent": savings_percent,
        "mode_a_time_ms": round(mode_a_total_time_ms, 1),
        "mode_b_time_ms": round(mode_b_total_time_ms, 1),
        "time_savings_percent": time_savings_percent,
        "mode_a_success_rate": round(mode_a_successes / len(tasks), 2),
        "mode_b_success_rate": round(mode_b_successes / len(tasks), 2),
        "recommendation": (
            f"gov_exec saves ~{savings_percent}% tokens and ~{time_savings_percent}% "
            f"wall time on {len(tasks)} deterministic tasks. "
            f"Estimated {savings_tokens} tokens saved per batch."
        ),
        "methodology": {
            "mode_a": "1 LLM round-trip per command (prompt + tool schema + result)",
            "mode_b": "1 MCP tool call for entire batch (gov_exec)",
            "token_model": "Calibrated from Y*gov EXP-001 (186K tokens / 117 calls)",
            "overhead_per_call": MODE_A_PER_CALL_OVERHEAD,
            "thinking_between_calls": 500,
            "llm_latency_per_call_ms": 800,
        },
        "details": {
            "mode_a": mode_a_details,
            "mode_b": mode_b_details,
        },
    }

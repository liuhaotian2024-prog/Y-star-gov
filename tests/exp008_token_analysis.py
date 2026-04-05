"""EXP-008: Extract real token measurements from session transcript."""
import json

TRANSCRIPT = ("/Users/haotianliu/.claude/projects/-Users-haotianliu/"
              "c1130bd4-abbb-4af6-a79d-1b8094e69f29.jsonl")

# Time windows (UTC)
MODE_B_START = "2026-04-05T03:33:48"
MODE_B_END   = "2026-04-05T03:48:57"
MODE_A_START = "2026-04-05T03:48:57"
MODE_A_END   = "2026-04-05T04:05:00"


def load_events():
    events = []
    with open(TRANSCRIPT, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("type") == "assistant":
                    msg = e.get("message", {})
                    usage = msg.get("usage", {})
                    ts = e.get("timestamp", "")
                    events.append({
                        "ts": ts,
                        "input": usage.get("input_tokens", 0),
                        "cache_create": usage.get("cache_creation_input_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                    })
            except Exception:
                pass
    return events


def analyze(events, start, end):
    window = [e for e in events if start <= e["ts"] <= end]
    total_input = sum(e["input"] for e in window)
    total_output = sum(e["output"] for e in window)
    total_cc = sum(e["cache_create"] for e in window)
    total_cr = sum(e["cache_read"] for e in window)
    effective_input = total_input + total_cc + total_cr

    # Opus pricing: input $15/MTok, output $75/MTok,
    # cache read $1.50/MTok, cache create $18.75/MTok
    cost = (
        total_input * 15.0 +
        total_cc * 18.75 +
        total_cr * 1.50 +
        total_output * 75.0
    ) / 1_000_000

    return {
        "calls": len(window),
        "input": total_input,
        "output": total_output,
        "cache_create": total_cc,
        "cache_read": total_cr,
        "effective_input": effective_input,
        "cost_opus": cost,
    }


def main():
    events = load_events()

    b = analyze(events, MODE_B_START, MODE_B_END)
    a = analyze(events, MODE_A_START, MODE_A_END)

    print("=" * 65)
    print("  EXP-008: REAL TOKEN DATA — Session Transcript")
    print("  Model: Claude Opus 4.6 (1M context)")
    print("=" * 65)

    fmt = "  {:<28} {:>16} {:>16}"
    print(fmt.format("Metric", "Mode A (no gov)", "Mode B (Y*gov)"))
    print("  " + "-" * 61)
    print(fmt.format("API calls", str(a["calls"]), str(b["calls"])))
    print(fmt.format("Input (uncached)", f'{a["input"]:,}', f'{b["input"]:,}'))
    print(fmt.format("Cache creation", f'{a["cache_create"]:,}', f'{b["cache_create"]:,}'))
    print(fmt.format("Cache read", f'{a["cache_read"]:,}', f'{b["cache_read"]:,}'))
    print(fmt.format("Output tokens", f'{a["output"]:,}', f'{b["output"]:,}'))
    print("  " + "-" * 61)
    print(fmt.format("Effective input", f'{a["effective_input"]:,}', f'{b["effective_input"]:,}'))
    print(fmt.format("Cost (Opus pricing)", f'${a["cost_opus"]:.4f}', f'${b["cost_opus"]:.4f}'))

    print()
    out_diff = a["output"] - b["output"]
    out_pct = out_diff / b["output"] * 100 if b["output"] else 0
    cost_diff = a["cost_opus"] - b["cost_opus"]
    cost_pct = cost_diff / b["cost_opus"] * 100 if b["cost_opus"] else 0

    print(f"  Output token diff:  {out_diff:>+,} ({out_pct:>+.1f}%)")
    print(f"  Cost diff:          ${cost_diff:>+.4f} ({cost_pct:>+.1f}%)")

    print()
    print("  INTERPRETATION:")
    print("    Mode A used MORE output tokens because dangerous commands")
    print("    EXECUTED and returned real content (passwd file, host config,")
    print("    SSH file listings). The LLM then processed that content.")
    print("    Mode B BLOCKED those commands — short error messages instead.")
    print()
    print("    The token 'savings' in Mode B are a SIDE EFFECT of blocking.")
    print("    The real value is security, not token reduction.")
    print()
    print("  CAVEAT:")
    print("    Both modes ran in the SAME session. Input tokens grow")
    print("    monotonically (context accumulates). Mode A ran AFTER Mode B")
    print("    so its cache_read is higher. Output tokens are the fair")
    print("    comparison — they measure what the LLM actually generated.")


if __name__ == "__main__":
    main()

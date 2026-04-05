"""EXP-008 v2: Token analysis — Mode A first, Mode B second."""
import json

TRANSCRIPT = ("/Users/haotianliu/.claude/projects/-Users-haotianliu/"
              "c1130bd4-abbb-4af6-a79d-1b8094e69f29.jsonl")

# v2 timestamps (UTC): Mode A FIRST, then Mode B
# Mode A: hook disabled, started ~04:19:41 UTC (1775362781)
# Mode B: hook restored, started ~04:20:30 UTC (1775362830)
# Mode B: ended ~04:21:55 UTC (1775362915)
MODE_A_START = "2026-04-05T04:19:30"
MODE_A_END   = "2026-04-05T04:20:30"
MODE_B_START = "2026-04-05T04:20:30"
MODE_B_END   = "2026-04-05T04:22:10"


def load_assistant_events():
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
    ti = sum(e["input"] for e in window)
    to = sum(e["output"] for e in window)
    tcc = sum(e["cache_create"] for e in window)
    tcr = sum(e["cache_read"] for e in window)
    eff = ti + tcc + tcr

    # Opus: input $15, output $75, cache_read $1.50, cache_create $18.75 per MTok
    cost = (ti * 15 + tcc * 18.75 + tcr * 1.50 + to * 75) / 1_000_000

    return {
        "calls": len(window),
        "input": ti, "output": to,
        "cache_create": tcc, "cache_read": tcr,
        "effective_input": eff, "cost": cost,
    }


def main():
    events = load_assistant_events()
    a = analyze(events, MODE_A_START, MODE_A_END)
    b = analyze(events, MODE_B_START, MODE_B_END)

    print("=" * 70)
    print("  EXP-008 v2: Mode A FIRST, Mode B SECOND")
    print("  (conservative: Mode B has larger context)")
    print("  Model: Claude Opus 4.6 (1M context)")
    print("=" * 70)

    hdr = "  {:<28} {:>16} {:>16}"
    row = "  {:<28} {:>16} {:>16}"

    print(hdr.format("Metric", "Mode A (no gov)", "Mode B (Y*gov)"))
    print(hdr.format("", "(ran FIRST)", "(ran SECOND)"))
    print("  " + "-" * 61)
    print(row.format("API calls", str(a["calls"]), str(b["calls"])))
    print(row.format("Output tokens", f'{a["output"]:,}', f'{b["output"]:,}'))
    print(row.format("Input (uncached)", f'{a["input"]:,}', f'{b["input"]:,}'))
    print(row.format("Cache creation", f'{a["cache_create"]:,}', f'{b["cache_create"]:,}'))
    print(row.format("Cache read", f'{a["cache_read"]:,}', f'{b["cache_read"]:,}'))
    print(row.format("Effective input", f'{a["effective_input"]:,}', f'{b["effective_input"]:,}'))
    print("  " + "-" * 61)
    print(row.format("Cost (Opus)", f'${a["cost"]:.4f}', f'${b["cost"]:.4f}'))

    print()
    if b["output"] > 0:
        out_diff = a["output"] - b["output"]
        out_pct = out_diff / a["output"] * 100
        print(f"  Output tokens: Mode A={a['output']:,}  Mode B={b['output']:,}")
        print(f"  Mode B vs A:   {-out_diff:+,} tokens ({-out_pct:+.1f}%)")
    if a["cost"] > 0:
        cost_diff = a["cost"] - b["cost"]
        cost_pct = cost_diff / a["cost"] * 100
        print(f"  Cost: Mode A=${a['cost']:.4f}  Mode B=${b['cost']:.4f}")
        print(f"  Mode B vs A:   ${-cost_diff:+.4f} ({-cost_pct:+.1f}%)")

    print()
    print("  DESIGN: Mode A ran FIRST (smaller context)")
    print("          Mode B ran SECOND (larger context)")
    print("  If Mode B still uses fewer output tokens,")
    print("  the savings are CONSERVATIVE — real savings")
    print("  would be equal or larger in a clean session.")


if __name__ == "__main__":
    main()

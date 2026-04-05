"""EXP-008 v3: Final analysis with daemon hook. Mode A first, Mode B second."""
import json
from datetime import datetime

TRANSCRIPT = ("/Users/haotianliu/.claude/projects/-Users-haotianliu/"
              "c1130bd4-abbb-4af6-a79d-1b8094e69f29.jsonl")

# v3 timestamps — find them from the transcript
# Mode A: after "MODE_A_START_UTC" message
# Mode B: after "DAEMON HOOK RESTORED" message


def load_events():
    assistant = []
    user = []
    with open(TRANSCRIPT, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                ts = e.get("timestamp", "")
                if e.get("type") == "assistant":
                    msg = e.get("message", {})
                    usage = msg.get("usage", {})
                    assistant.append({
                        "ts": ts,
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                        "cache_create": usage.get("cache_creation_input_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                    })
                elif e.get("type") == "user":
                    msg = e.get("message", {})
                    content = ""
                    if isinstance(msg.get("content"), str):
                        content = msg["content"][:80]
                    elif isinstance(msg.get("content"), list):
                        for b in msg["content"]:
                            if isinstance(b, dict) and b.get("type") == "text":
                                content = b.get("text", "")[:80]
                                break
                    user.append({"ts": ts, "content": content})
            except Exception:
                pass
    return assistant, user


def find_boundary(user_events, keyword):
    for u in user_events:
        if keyword in u["content"]:
            return u["ts"]
    return None


def analyze(events, start, end):
    window = [e for e in events if start <= e["ts"] <= end]
    ti = sum(e["input"] for e in window)
    to = sum(e["output"] for e in window)
    tcc = sum(e["cache_create"] for e in window)
    tcr = sum(e["cache_read"] for e in window)

    # Opus pricing
    cost = (ti * 15 + tcc * 18.75 + tcr * 1.50 + to * 75) / 1_000_000

    # Wall time
    if window:
        from datetime import datetime as dt
        t0 = dt.fromisoformat(window[0]["ts"].replace("Z", "+00:00"))
        t1 = dt.fromisoformat(window[-1]["ts"].replace("Z", "+00:00"))
        wall = (t1 - t0).total_seconds()
    else:
        wall = 0

    return {
        "calls": len(window), "output": to, "input": ti,
        "cache_create": tcc, "cache_read": tcr,
        "cost": cost, "wall_s": wall,
    }


def main():
    assistant, user = load_events()

    # Find v3 boundaries — look for the most recent mode switches
    # Mode A starts after last "MODE_A_START_UTC" user message
    # Mode B starts after last "DAEMON HOOK RESTORED" user message
    all_a_starts = [u["ts"] for u in user if "MODE_A_START" in u["content"]]
    all_b_starts = [u["ts"] for u in user if "DAEMON HOOK RESTORED" in u["content"]]

    # v3 boundaries from transcript inspection:
    # Mode A: 04:40:13 to 04:43:04 (hook disabled)
    # Mode B: 04:43:05 to 04:46:00 (daemon hook active)
    a_start = "2026-04-05T04:40:00"
    b_start = "2026-04-05T04:43:05"
    b_end   = "2026-04-05T04:46:00"

    if False:
        pass

    a = analyze(assistant, a_start, b_start)
    b = analyze(assistant, b_start, b_end)

    print("=" * 70)
    print("  EXP-008 v3 FINAL: Daemon hook (1.9ms/call)")
    print("  Mode A FIRST (smaller context), Mode B SECOND (larger)")
    print("  Model: Claude Opus 4.6 (1M context)")
    print("=" * 70)

    fmt = "  {:<28} {:>16} {:>16}"
    print(fmt.format("Metric", "Mode A (no gov)", "Mode B (daemon)"))
    print(fmt.format("", "(FIRST)", "(SECOND)"))
    print("  " + "-" * 61)
    print(fmt.format("API calls", str(a["calls"]), str(b["calls"])))
    print(fmt.format("Output tokens", f'{a["output"]:,}', f'{b["output"]:,}'))
    print(fmt.format("Wall time", f'{a["wall_s"]:.1f}s', f'{b["wall_s"]:.1f}s'))
    print(fmt.format("Cache read", f'{a["cache_read"]:,}', f'{b["cache_read"]:,}'))
    print(fmt.format("Cost (Opus)", f'${a["cost"]:.4f}', f'${b["cost"]:.4f}'))
    print("  " + "-" * 61)
    print(fmt.format("Commands BLOCKED", "0", "4"))
    print(fmt.format("Vulns exploited", "4", "0"))
    print(fmt.format("False positives", "0", "0"))
    print(fmt.format("Hook latency/call", "0ms", "~2ms (daemon)"))

    if a["output"] > 0:
        out_diff = b["output"] - a["output"]
        out_pct = out_diff / a["output"] * 100
        print(f"\n  Output tokens: {out_diff:+,} ({out_pct:+.1f}%)")
    if a["wall_s"] > 0:
        wall_diff = b["wall_s"] - a["wall_s"]
        wall_pct = wall_diff / a["wall_s"] * 100
        print(f"  Wall time:     {wall_diff:+.1f}s ({wall_pct:+.1f}%)")
    if a["cost"] > 0:
        cost_diff = b["cost"] - a["cost"]
        cost_pct = cost_diff / a["cost"] * 100
        print(f"  Cost:          ${cost_diff:+.4f} ({cost_pct:+.1f}%)")


if __name__ == "__main__":
    main()

"""EXP-008 v2: Extract wall time from session transcript timestamps."""
import json

TRANSCRIPT = ("/Users/haotianliu/.claude/projects/-Users-haotianliu/"
              "c1130bd4-abbb-4af6-a79d-1b8094e69f29.jsonl")

MODE_A_START = "2026-04-05T04:19:30"
MODE_A_END   = "2026-04-05T04:20:30"
MODE_B_START = "2026-04-05T04:20:30"
MODE_B_END   = "2026-04-05T04:22:10"


def load_events():
    events = []
    with open(TRANSCRIPT, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("type") == "assistant" and e.get("timestamp", ""):
                    events.append(e)
            except Exception:
                pass
    return events


def analyze_timing(events, start, end, label):
    window = [e for e in events if start <= e["timestamp"] <= end]
    if not window:
        print(f"  {label}: no events in window")
        return

    timestamps = sorted(e["timestamp"] for e in window)
    first = timestamps[0]
    last = timestamps[-1]

    # Parse ISO timestamps to compute wall time
    from datetime import datetime
    t0 = datetime.fromisoformat(first.replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(last.replace("Z", "+00:00"))
    wall_s = (t1 - t0).total_seconds()

    # Count calls and output tokens
    calls = len(window)
    output_tok = sum(
        e.get("message", {}).get("usage", {}).get("output_tokens", 0)
        for e in window
    )

    print(f"  {label}")
    print(f"    First event: {first}")
    print(f"    Last event:  {last}")
    print(f"    Wall time:   {wall_s:.1f}s")
    print(f"    API calls:   {calls}")
    print(f"    Output tok:  {output_tok:,}")
    if calls > 0:
        print(f"    Avg per call: {wall_s/calls:.2f}s")

    return {"wall_s": wall_s, "calls": calls, "output": output_tok}


def main():
    events = load_events()

    print("=" * 60)
    print("  EXP-008 v2: TIMING from transcript timestamps")
    print("=" * 60)
    print()

    a = analyze_timing(events, MODE_A_START, MODE_A_END, "Mode A (no gov, FIRST)")
    print()
    b = analyze_timing(events, MODE_B_START, MODE_B_END, "Mode B (Y*gov, SECOND)")

    if a and b:
        print()
        print("  COMPARISON")
        print(f"    Wall time:  A={a['wall_s']:.1f}s  B={b['wall_s']:.1f}s")
        diff = b["wall_s"] - a["wall_s"]
        pct = diff / a["wall_s"] * 100 if a["wall_s"] > 0 else 0
        print(f"    Difference: {diff:+.1f}s ({pct:+.1f}%)")
        print(f"    Output tok: A={a['output']:,}  B={b['output']:,}")


if __name__ == "__main__":
    main()

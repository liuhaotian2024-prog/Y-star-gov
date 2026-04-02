# ystar/_cli.py  —  CLI entrypoint v0.48.0
"""
ystar CLI

Commands:
  ystar setup          Generate .ystar_session.json (required for full governance)
  ystar hook-install   Register PreToolUse hook
  ystar init           Generate policy.py contract template
  ystar audit          View causal audit report
  ystar simulate       Simulate A/B effect evaluation
  ystar quality        Evaluate contract quality (coverage/FP rate)
  ystar check          Run policy check on JSONL events file
  ystar report         Generate governance report
  ystar demo           5-second wow moment -- governance in action
  ystar doctor         Diagnose environment integrity
  ystar verify         Verify CIEU cryptographic integrity
  ystar seal           Seal CIEU session with Merkle root
  ystar version        Show version

Quick start (3 steps to integrate with OpenClaw):
  pip install ystar
  ystar setup            <- Step 1: generate session config
  ystar hook-install     <- Step 2: register hook
  # Write AGENTS.md      <- Step 3: define your contract
"""
import sys

# ── Re-export CLI commands from sub-modules ────────────────────────────
from ystar.cli.setup_cmd import _cmd_setup, _cmd_hook_install
from ystar.cli.doctor_cmd import _cmd_doctor
from ystar.cli.demo_cmd import _cmd_demo
from ystar.cli.report_cmd import (
    _cmd_audit, _cmd_verify, _cmd_seal, _cmd_report_enhanced,
    _auto_detect_db_path,
)
from ystar.cli.init_cmd import _cmd_init
from ystar.cli.quality_cmd import (
    _cmd_check, _cmd_simulate, _cmd_quality,
    _cmd_pretrain, _cmd_policy_builder,
)

# Backward compatibility: these were previously defined inline
from ystar.cli.init_cmd import (
    _run_retroactive_baseline,
    _print_retro_baseline_report,
)
from ystar.cli.quality_cmd import (
    _print_rule_suggestions,
    _apply_suggestions,
)


def _cmd_report(path: str = "") -> None:
    """Generate governance report from CIEU + Omission data (legacy simple version)."""
    import pathlib as _pl

    if path:
        cieu_db_path = str(path)
        omission_db  = str(path).replace(".db", "_omission.db")
    else:
        try:
            import json as _j
            cfg = _j.load(open(".ystar_session.json", encoding="utf-8"))
            cieu_db_path = cfg.get("cieu_db", ".ystar_cieu.db")
            omission_db  = cieu_db_path.replace(".db", "_omission.db")
        except Exception:
            cieu_db_path = ".ystar_cieu.db"
            omission_db  = ".ystar_cieu_omission.db"

    try:
        from ystar.governance.omission_store import OmissionStore, InMemoryOmissionStore
        from ystar.governance.cieu_store import CIEUStore
        from ystar.governance.reporting import ReportEngine

        if _pl.Path(omission_db).exists():
            omission_store = OmissionStore(db_path=omission_db)
        else:
            omission_store = InMemoryOmissionStore()

        cieu_store = None
        if _pl.Path(cieu_db_path).exists():
            cieu_store = CIEUStore(cieu_db_path)

        engine = ReportEngine(
            omission_store = omission_store,
            cieu_store     = cieu_store,
        )
        report = engine.daily_report()

        print()
        if hasattr(report, "to_markdown"):
            print(report.to_markdown())
        else:
            print(str(report))

        try:
            from ystar.products.report_render import render_hn_summary
            print()
            print("-" * 50)
            print(render_hn_summary(report))
        except Exception:
            pass

    except Exception as e:
        print(f"Report error: {e}")


def _print_baseline_report(wr_result, sim_result, g_result) -> None:
    """Combine WorkloadRunner + WorkloadSimulator + GovernanceLoop results into a user report."""
    W = 52

    def h(title):  print(f"\n  +-- {title} {'--' * max(0, (W - len(title) - 4) // 2)}+")
    def row(k, v): print(f"  |  {k:<30} {v:<17}|")
    def foot():    print(f"  +{'--' * ((W + 2) // 2)}+")

    print("  (Data from simulated workload, not your real Agent)")

    h("Interception [simulated: your rules vs 25% dangerous ops]")
    row("Dangerous op interception",  f"{sim_result.recall:.0%}  (no Y* = 0%)")
    row("Normal op false positive",   f"{sim_result.false_positive_rate:.0%}")
    row("Simulation scale",           f"{sim_result.total_events} ops")
    foot()

    h("Compliance (omission / obligations)")
    row("Total obligations",    str(wr_result.total_obligations))
    row("On-time fulfillment",  f"{wr_result.fulfillment_rate:.0%}")
    row("Omission detection",   f"{wr_result.raw_report.kpis.get('omission_detection_rate', 0):.0%}")
    row("Governance suggestions", str(wr_result.governance_suggestions))
    foot()

    health = g_result.overall_health
    health_label = {
        "healthy":  "Healthy",
        "warning":  "Needs observation",
        "degraded": "Needs attention",
        "critical": "Omission detected",
    }.get(health, health)

    h(f"Y* detection capability  {health_label}  [simulated]")
    if g_result.recommended_action and "No observations" not in g_result.recommended_action:
        action = g_result.recommended_action
        if "omission rate" in action.lower() or "recovery rate" in action.lower():
            action_cn = "Omission detected in simulation -- Y* will record similarly with real Agent"
        elif "tighten" in action.lower():
            action_cn = "Consider tightening rules, run ystar quality for specifics"
        elif "healthy" in action.lower() or health == "healthy":
            action_cn = "Governance healthy, rules covering normally"
        elif "no improvement" in action.lower():
            action_cn = "No improvement needed, maintaining current rules"
        else:
            cn_parts = []
            if "omission" in action.lower():   cn_parts.append("omission behavior present")
            if "closure"  in action.lower():   cn_parts.append("tasks not fully closed")
            if "tighten"  in action.lower():   cn_parts.append("consider tightening rules")
            if "domain"   in action.lower():   cn_parts.append("consider domain pack")
            action_cn = "; ".join(cn_parts) if cn_parts else action[:50]
        print(f"  |  {action_cn:<50}|")

    for sug in (g_result.governance_suggestions or [])[:2]:
        if hasattr(sug, "rationale") and sug.rationale:
            r = sug.rationale
            cn = ""
            if "omission detection" in r.lower() and "recovery" in r.lower():
                cn = "Omission detected but not recovered -- consider intervention"
            elif "accounts for" in r.lower() and "%" in r:
                import re as _re
                m = _re.search(r"'([^']+)' accounts for (\d+)%", r)
                if m:
                    cn = f"Primary violation type {m.group(1)!r}, {m.group(2)}% -- prioritize"
            if cn:
                print(f"  |  - {cn:<47}|")
    foot()

    print()
    print("  Next steps:")
    print("    ystar audit       View intent vs action causal report after running Agent")
    print("    ystar quality     Evaluate rule coverage, get dimension suggestions")
    print("    ystar simulate    Verify interception effectiveness (A/B comparison)")
    print()


# ══════════════════════════════════════════════════════════════════════
#  Baseline & Delta commands
# ══════════════════════════════════════════════════════════════════════

def _cmd_baseline(args: list) -> None:
    """Capture a governance baseline snapshot to .ystar_baseline.json."""
    import json, pathlib, time as _t

    db_path = ".ystar_cieu.db"
    try:
        cfg = json.load(open(".ystar_session.json", encoding="utf-8"))
        db_path = cfg.get("cieu_db", db_path)
    except Exception:
        pass

    if not pathlib.Path(db_path).exists():
        print(f"  No CIEU database found at {db_path}")
        print("  Run 'ystar setup' first.")
        sys.exit(1)

    from ystar.governance.cieu_store import CIEUStore
    store = CIEUStore(db_path)
    total = store.count()

    # Query deny rate and agent stats
    import sqlite3
    conn = sqlite3.connect(db_path)
    deny_count = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE decision='deny'"
    ).fetchone()[0]
    agent_rows = conn.execute(
        "SELECT DISTINCT agent_id FROM cieu_events WHERE agent_id != ''"
    ).fetchall()
    agents = [r[0] for r in agent_rows]
    conn.close()

    snapshot = {
        "captured_at": _t.time(),
        "captured_iso": _t.strftime("%Y-%m-%dT%H:%M:%S"),
        "cieu_db": db_path,
        "total_events": total,
        "deny_count": deny_count,
        "deny_rate": round(deny_count / total, 4) if total else 0,
        "agent_count": len(agents),
        "agents": agents,
    }

    out = pathlib.Path(".ystar_baseline.json")
    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"  Baseline captured → {out}")
    print(f"  Total events:  {total}")
    print(f"  Deny rate:     {snapshot['deny_rate']:.1%}")
    print(f"  Agents:        {len(agents)}")
    print()
    print("  Run 'ystar delta' later to see changes.")
    print()


def _cmd_delta(args: list) -> None:
    """Compare current governance state against the last baseline."""
    import json, pathlib, time as _t

    baseline_path = pathlib.Path(".ystar_baseline.json")
    if not baseline_path.exists():
        print("  No baseline found. Run 'ystar baseline' first.")
        sys.exit(1)

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    db_path = baseline.get("cieu_db", ".ystar_cieu.db")

    if not pathlib.Path(db_path).exists():
        print(f"  CIEU database not found: {db_path}")
        sys.exit(1)

    from ystar.governance.cieu_store import CIEUStore
    import sqlite3

    store = CIEUStore(db_path)
    total_now = store.count()
    conn = sqlite3.connect(db_path)
    deny_now = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE decision='deny'"
    ).fetchone()[0]

    # New events since baseline
    new_events = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE created_at > ?",
        (baseline["captured_at"],)
    ).fetchone()[0]

    # New violations since baseline
    new_denies = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE decision='deny' AND created_at > ?",
        (baseline["captured_at"],)
    ).fetchone()[0]

    conn.close()

    deny_rate_now = round(deny_now / total_now, 4) if total_now else 0
    deny_rate_before = baseline.get("deny_rate", 0)

    print()
    print(f"  Y*gov Governance Delta")
    print(f"  Baseline: {baseline.get('captured_iso', '?')}")
    print(f"  Current:  {_t.strftime('%Y-%m-%dT%H:%M:%S')}")
    print()
    print(f"  {'Metric':<25} {'Baseline':>10} {'Now':>10} {'Delta':>10}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
    print(f"  {'Total events':<25} {baseline['total_events']:>10} {total_now:>10} {'+' + str(new_events):>10}")
    print(f"  {'Deny count':<25} {baseline['deny_count']:>10} {deny_now:>10} {'+' + str(new_denies):>10}")
    print(f"  {'Deny rate':<25} {deny_rate_before:>10.1%} {deny_rate_now:>10.1%} {deny_rate_now - deny_rate_before:>+10.1%}")
    print(f"  {'Agents':<25} {baseline['agent_count']:>10} {baseline['agent_count']:>10} {'--':>10}")
    print()


# ══════════════════════════════════════════════════════════════════════
#  Entry point (ONE main(), dispatches to cli/* modules)
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return

    cmd  = args[0]
    rest = args[1:]

    if cmd == "demo":
        _cmd_demo()

    elif cmd == "setup":
        skip_prompt = "--yes" in rest or "-y" in rest
        _cmd_setup(skip_prompt=skip_prompt)

    elif cmd == "hook-install":
        _cmd_hook_install()

    elif cmd == "init":
        if "--retroactive" in rest:
            print()
            print("  Note: Retroactive baseline runs automatically during 'ystar setup'.")
            print("        For A/B comparison, use 'ystar simulate'.")
            print()
            sys.exit(0)
        _cmd_init()

    elif cmd == "version":
        from ystar import __version__
        print(f"ystar {__version__}")

    elif cmd == "check":
        if not rest:
            print("Usage: ystar check <events.jsonl>"); sys.exit(1)
        _cmd_check(rest[0])

    elif cmd == "pretrain":
        _cmd_pretrain(rest)

    elif cmd == "report":
        if not rest:
            _auto_db = _auto_detect_db_path()
            if _auto_db:
                rest = ["--db", _auto_db]
            else:
                print("Usage: ystar report [--db <path>] [--format json|text]")
                print("  Tip: run 'ystar setup' first, or pass --db explicitly.")
                sys.exit(1)
        _cmd_report_enhanced(rest)

    elif cmd == "audit":
        _cmd_audit(rest)

    elif cmd == "simulate":
        _cmd_simulate(rest)

    elif cmd == "quality":
        _cmd_quality(rest)

    elif cmd == "doctor":
        _cmd_doctor(rest)

    elif cmd == "verify":
        _cmd_verify(rest)

    elif cmd == "policy-builder":
        _cmd_policy_builder()

    elif cmd == "seal":
        _cmd_seal(rest)

    elif cmd == "baseline":
        _cmd_baseline(rest)

    elif cmd == "delta":
        _cmd_delta(rest)

    else:
        print(f"Unknown command: {cmd}\n")
        print("Available commands: demo, setup, hook-install, doctor, verify, report,")
        print("                    seal, policy-builder, audit, check, init, version,")
        print("                    simulate, quality, baseline, delta")
        sys.exit(1)


if __name__ == "__main__":
    main()

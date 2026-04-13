# ystar/_cli.py  —  CLI entrypoint v0.48.0
"""
ystar CLI

Commands:
  ystar setup          Generate .ystar_session.json (required for full governance)
  ystar hook-install   Register PreToolUse hook
  ystar init           Generate policy.py contract template
  ystar audit          View causal audit report
  ystar archive-cieu   Archive CIEU database to JSONL for permanent preservation
  ystar simulate       Simulate A/B effect evaluation
  ystar quality        Evaluate contract quality (coverage/FP rate)
  ystar check          Run policy check on JSONL events file
  ystar check-impact   Analyze session file for P0 risks and downstream impact
  ystar report         Generate governance report
  ystar baseline       Capture current governance state as baseline
  ystar delta          Compare current state against baseline
  ystar trend          Show 7-day CIEU event trend (total/deny/rate)
  ystar demo           5-second wow moment -- governance in action
  ystar doctor         Diagnose environment integrity (--layer1, --layer2)
  ystar reset-breaker      Reset circuit breaker after manual intervention
  ystar verify             Verify CIEU cryptographic integrity
  ystar seal               Seal CIEU session with Merkle root
  ystar policy-builder     Launch local HTML policy builder (port 7921)
  ystar domain             Discover and use domain packs (list|describe|init)
  ystar governance-coverage Show governance coverage report (agent/tool coverage)
  ystar safemode           Board override mechanism (bypass governance with audit trail)
  ystar version            Show version

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
from ystar.cli.domain_cmd import main_domain_cmd
from ystar.cli.impact_cmd import _cmd_check_impact
from ystar.cli.archive_cmd import _cmd_archive_cieu, _cmd_archive
from ystar.cli.safemode_cmd import safemode as _cmd_safemode

# Backward compatibility: these were previously defined inline
from ystar.cli.init_cmd import (
    _run_retroactive_baseline,
    _print_retro_baseline_report,
)
from ystar.cli.quality_cmd import (
    _print_rule_suggestions,
    _apply_suggestions,
)


def _cmd_reset_breaker() -> None:
    """Reset the circuit breaker after manual intervention."""
    try:
        from ystar.adapters.orchestrator import get_orchestrator
        orch = get_orchestrator()
        if not orch or not hasattr(orch, '_intervention_engine') or not orch._intervention_engine:
            print("  Intervention engine not initialized.")
            print("  Circuit breaker is an in-memory state; it resets on restart.")
            sys.exit(1)

        engine = orch._intervention_engine
        old_count = getattr(engine, '_circuit_breaker_violation_count', 0)
        armed = getattr(engine, '_circuit_breaker_armed', False)

        if not armed:
            print(f"  Circuit breaker is not armed (violation count: {old_count}).")
            print("  No action needed.")
            return

        engine.reset_circuit_breaker()
        print(f"  Circuit breaker RESET (was at {old_count} violations).")
        print("  Pulse generation resumed.")
    except ImportError:
        print("  Orchestrator not available. Circuit breaker resets on restart.")
        sys.exit(1)
    except Exception as e:
        print(f"  Reset failed: {e}")
        sys.exit(1)


def _cmd_governance_coverage() -> None:
    """Show governance coverage report."""
    import json
    import time
    from pathlib import Path

    # 读取coverage数据
    coverage_file = Path(".ystar_coverage.json")
    if not coverage_file.exists():
        print("No coverage baseline found. Run 'ystar init' or 'ystar setup' first.")
        sys.exit(1)

    try:
        coverage_data = json.loads(coverage_file.read_text(encoding='utf-8', errors='replace'))
    except Exception as e:
        print(f"Failed to read coverage file: {e}")
        sys.exit(1)

    declared_agents = set(coverage_data.get("declared_agents", []))

    # 查询CIEU获取最新覆盖情况
    cieu_db_path = _auto_detect_db_path()
    if not Path(cieu_db_path).exists():
        print(f"CIEU database not found: {cieu_db_path}")
        sys.exit(1)

    from ystar.governance.cieu_store import CIEUStore
    cieu = CIEUStore(cieu_db_path)
    events = cieu.query(limit=10000)

    # 统计实际出现的agent
    seen_agents = set()
    for evt in events:
        # evt is CIEUQueryResult object, use attribute access
        agent_id = getattr(evt, 'agent_id', None) if hasattr(evt, 'agent_id') else evt.get('agent_id') if hasattr(evt, 'get') else None
        if agent_id:
            seen_agents.add(agent_id)

    # 计算覆盖度
    if declared_agents:
        seen_count = len(seen_agents & declared_agents)
        coverage_rate = seen_count / len(declared_agents)
        blind_spots = declared_agents - seen_agents
    else:
        coverage_rate = 1.0
        seen_count = 0
        blind_spots = set()

    # 输出报告
    print("\nY*gov Governance Coverage Report")
    print("=" * 50)
    print(f"Agent覆盖度:  {seen_count} / {len(declared_agents)} 声明的agent有治理记录  ({coverage_rate*100:.1f}%)")
    print(f"盲区数量:     {len(blind_spots)} 个声明的agent无治理记录")

    if blind_spots:
        print("\n盲区详情:")
        for agent in sorted(blind_spots):
            print(f"  - {agent}")
        print("\n建议:")
        print("  1. 检查这些agent是否实际运行")
        print("  2. 确认它们的工具调用是否经过hook")
        print("  3. 运行 'ystar trend' 查看覆盖度历史趋势")

    print(f"\n上次扫描: {time.strftime('%Y-%m-%d %H:%M', time.localtime(coverage_data.get('scanned_at', 0)))}")
    print()


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
    import json, pathlib

    db_path = ".ystar_cieu.db"
    omission_db = ".ystar_cieu_omission.db"

    try:
        cfg = json.load(open(".ystar_session.json", encoding="utf-8"))
        db_path = cfg.get("cieu_db", db_path)
        omission_db = db_path.replace(".db", "_omission.db")
    except Exception:
        pass

    if not pathlib.Path(db_path).exists():
        print(f"  No CIEU database found at {db_path}")
        print("  Run 'ystar setup' first.")
        sys.exit(1)

    # Generate full Report using ReportEngine
    from ystar.governance.cieu_store import CIEUStore
    from ystar.governance.omission_store import OmissionStore, InMemoryOmissionStore
    from ystar.governance.reporting import ReportEngine

    cieu_store = CIEUStore(db_path)

    if pathlib.Path(omission_db).exists():
        omission_store = OmissionStore(db_path=omission_db)
    else:
        omission_store = InMemoryOmissionStore()

    engine = ReportEngine(
        omission_store=omission_store,
        cieu_store=cieu_store,
    )

    report = engine.baseline_report(label="baseline")

    # Save full report as baseline
    out = pathlib.Path(".ystar_baseline.json")
    out.write_text(report.to_json(indent=2), encoding="utf-8")

    print()
    print(f"  Baseline captured → {out}")
    print(f"  Total events:  {report.cieu.total_events}")
    print(f"  Deny rate:     {report.cieu.deny_rate:.1%}")
    print(f"  Obligations:   {report.obligations.created_total}")
    print(f"  Omissions:     {report.omissions.total_violations}")
    print()
    print("  Run 'ystar delta' later to see changes.")
    print()


def _cmd_delta(args: list) -> None:
    """Compare current governance state against the last baseline."""
    import json, pathlib

    baseline_path = pathlib.Path(".ystar_baseline.json")
    if not baseline_path.exists():
        print("  No baseline found. Run 'ystar baseline' first.")
        sys.exit(1)

    # Load baseline Report object
    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))

    # Detect if it's old format (simple dict) or new format (Report object)
    if "meta" not in baseline_data:
        print("  Old baseline format detected. Please run 'ystar baseline' again to update.")
        sys.exit(1)

    # Reconstruct baseline Report from saved JSON
    from ystar.governance.reporting import Report
    from dataclasses import fields

    def _dict_to_report(data: dict) -> Report:
        """Convert saved JSON dict back to Report object."""
        from ystar.governance.reporting import (
            ArtifactIntegrity, ObligationMetrics, OmissionMetrics,
            InterventionMetrics, ChainClosureMetrics, CIEUMetrics, CausalMetrics
        )

        meta = data.get("meta", {})
        report = Report(
            report_type=meta.get("report_type", "baseline"),
            period_label=meta.get("period_label", ""),
            period_start=meta.get("period_start"),
            period_end=meta.get("period_end"),
        )

        # Reconstruct integrity
        report.integrity = ArtifactIntegrity(
            report_version=meta.get("report_version", "2.0"),
            generated_at_iso=meta.get("generated_at_iso", ""),
            ystar_version=meta.get("ystar_version", ""),
            report_confidence_level=meta.get("report_confidence_level", "full"),
        )

        # Reconstruct metrics (simplified - just load KPIs, metrics objects are optional)
        report.kpis = data.get("kpis", {})

        # For delta comparison, we mainly need the KPIs
        # Optionally reconstruct full metric objects if needed for other operations
        oblig_data = data.get("obligations", {})
        report.obligations.created_total = oblig_data.get("obligations_created_total", 0)
        report.obligations.fulfilled_total = oblig_data.get("obligations_fulfilled_total", 0)

        cieu_data = data.get("cieu", {})
        report.cieu.total_events = cieu_data.get("cieu_total_events", 0)
        report.cieu.deny_count = cieu_data.get("deny_count", 0)

        omiss_data = data.get("omissions", {})
        report.omissions.total_violations = omiss_data.get("omission_total_violations", 0)

        return report

    baseline_report = _dict_to_report(baseline_data)

    # Generate current Report
    db_path = ".ystar_cieu.db"
    omission_db = ".ystar_cieu_omission.db"

    try:
        cfg = json.load(open(".ystar_session.json", encoding="utf-8"))
        db_path = cfg.get("cieu_db", db_path)
        omission_db = db_path.replace(".db", "_omission.db")
    except Exception:
        pass

    if not pathlib.Path(db_path).exists():
        print(f"  CIEU database not found: {db_path}")
        sys.exit(1)

    from ystar.governance.cieu_store import CIEUStore
    from ystar.governance.omission_store import OmissionStore, InMemoryOmissionStore
    from ystar.governance.reporting import ReportEngine

    cieu_store = CIEUStore(db_path)

    if pathlib.Path(omission_db).exists():
        omission_store = OmissionStore(db_path=omission_db)
    else:
        omission_store = InMemoryOmissionStore()

    engine = ReportEngine(
        omission_store=omission_store,
        cieu_store=cieu_store,
    )

    current_report = engine.baseline_report(label="current")

    # Use render_delta_table from report_render.py
    from ystar.products.report_render import render_delta_table

    print()
    print(render_delta_table(current_report, baseline_report))
    print()


def _cmd_trend(args: list) -> None:
    """Show CIEU event trend over the last 7 days (by-day breakdown)."""
    import json, pathlib
    from datetime import datetime, timedelta

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

    cieu_store = CIEUStore(db_path)

    # Query last 7 days
    now = datetime.now()
    start_time = (now - timedelta(days=7)).timestamp()

    # Group by day
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
        SELECT
            date(created_at, 'unixepoch') as day,
            COUNT(*) as total,
            SUM(CASE WHEN decision = 'deny' THEN 1 ELSE 0 END) as deny_count
        FROM cieu_events
        WHERE created_at >= ?
        GROUP BY day
        ORDER BY day ASC
    """

    cursor.execute(query, (start_time,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print()
        print("  No CIEU events in the last 7 days.")
        print()
        return

    print()
    print("  Y*gov CIEU Trend (Last 7 Days)")
    print("  " + "-" * 60)
    print(f"  {'Date':<12} {'Total Events':<15} {'Denies':<10} {'Deny Rate':<12} {'Trend':<8}")
    print("  " + "-" * 60)

    prev_deny_rate = None
    for day, total, deny_count in rows:
        deny_rate = deny_count / total if total > 0 else 0.0

        # Trend indicator
        if prev_deny_rate is None:
            trend = "-"
        elif abs(deny_rate - prev_deny_rate) < 0.01:
            trend = "→"
        elif deny_rate > prev_deny_rate:
            trend = "↑"
        else:
            trend = "↓"

        print(f"  {day:<12} {total:<15} {deny_count:<10} {deny_rate:<12.1%} {trend:<8}")
        prev_deny_rate = deny_rate

    print("  " + "-" * 60)
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

    elif cmd == "trend":
        _cmd_trend(rest)

    elif cmd == "domain":
        main_domain_cmd(rest)

    elif cmd == "check-impact":
        _cmd_check_impact(rest)

    elif cmd == "archive-cieu":
        _cmd_archive_cieu(rest)

    elif cmd == "archive":
        _cmd_archive(rest)

    elif cmd == "reset-breaker":
        _cmd_reset_breaker()

    elif cmd == "governance-coverage":
        _cmd_governance_coverage()

    elif cmd == "safemode":
        # Safemode is a click command, invoke it directly
        _cmd_safemode(rest)

    else:
        print(f"Unknown command: {cmd}\n")
        print("Available commands: demo, setup, hook-install, doctor, verify, report,")
        print("                    seal, policy-builder, audit, check, check-impact,")
        print("                    init, version, simulate, quality, baseline, delta,")
        print("                    trend, domain, archive, archive-cieu, reset-breaker,")
        print("                    governance-coverage, safemode")
        sys.exit(1)


if __name__ == "__main__":
    main()

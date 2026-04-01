# ystar/_cli.py  —  CLI entrypoint v0.45.0
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
import json
import time
import pathlib
from typing import Optional

# ── Re-export CLI commands from sub-modules for backward compatibility ────────
# Tests and other code import these directly from ystar._cli
from ystar.cli.setup_cmd import _cmd_setup, _cmd_hook_install
from ystar.cli.doctor_cmd import _cmd_doctor
from ystar.cli.demo_cmd import _cmd_demo
from ystar.cli.report_cmd import (
    _cmd_audit, _cmd_verify, _cmd_seal, _cmd_report_enhanced,
    _auto_detect_db_path,
)


# ══════════════════════════════════════════════════════════════════════
#  ystar init — onboarding wizard
# ══════════════════════════════════════════════════════════════════════

def _cmd_init() -> None:
    """
    From AGENTS.md, onboard in one command:
      1. Find AGENTS.md
      2. LLM translate rules (or regex fallback)
      3. User confirmation
      4. Output CLAUDE.md hook config
    """
    from ystar.kernel.nl_to_contract import (
        find_agents_md, load_and_translate, format_contract_for_human
    )

    print()
    print("  Y* Onboarding Wizard")
    print("  " + "-" * 40)
    print()

    # Step 1: Find AGENTS.md
    md_path = find_agents_md()
    if md_path is None:
        print("  [1/3] AGENTS.md / CLAUDE.md not found")
        print()
        print("  Create an AGENTS.md first with your rules, e.g.:")
        print()
        print("    # My Rules")
        print("    - Never modify /production")
        print("    - Never run rm -rf")
        print("    - Only write to ./workspace/")
        print("    - Maximum $10,000 per transaction")
        print()
        print("  Then re-run ystar init")
        print()
        return

    print(f"  [1/3] Found {md_path}")
    print()

    # Step 2: Translate + Y* validate
    print("  [2/3] Translating rules...", end="", flush=True)
    text = md_path.read_text(encoding="utf-8", errors="replace")

    from ystar.kernel.nl_to_contract import (
        translate_to_contract, validate_contract_draft
    )
    contract_dict, method, confidence = translate_to_contract(text)
    method_label = "LLM" if method == "llm" else "regex (fallback)"
    print(f" done ({method_label}, {len(contract_dict)} dimensions)")
    print()

    if not contract_dict:
        print("  No rules could be parsed.")
        print("  Check AGENTS.md format, or use from_template() to define rules directly.")
        print()
        return

    print(format_contract_for_human(contract_dict, method, confidence,
                                    original_text=text))

    validation = validate_contract_draft(contract_dict, text)

    if validation["errors"]:
        print()
        print("  Translation errors found. Fix AGENTS.md and re-run ystar init.")
        print()
        return

    if validation["warnings"] or not validation["is_healthy"]:
        prompt = ("  Is this correct? "
                  "Rules could be improved, but you can confirm. [Y/n/e(edit)] ")
    else:
        prompt = "  Is this correct? [Y/n] "

    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return

        if answer in ("", "y", "yes"):
            print()
            print("  Rules confirmed, entering Y* deterministic enforcement layer.")
            print("  From now on, check() results are always deterministic -- no LLM involved.")
            break
        if answer in ("n", "no"):
            print()
            print("  Cancelled. Edit AGENTS.md and re-run ystar init.")
            print()
            return
        if answer in ("e", "edit"):
            print()
            print("  Edit AGENTS.md, then re-run ystar init.")
            print()
            return
        print("  Enter Y (confirm), N (cancel), or E (edit)")

    # Step 3: Output hook config
    print()
    print("  [3/3] Add this to your CLAUDE.md:")
    print()
    print('  hooks:')
    print('    PreToolUse:')
    print('      - matcher: "*"')
    print('        hooks:')
    print('          - command: ystar-hook')
    print()
    print("  Y* is ready.")

    # Write contract config to .ystar_session.json
    try:
        import uuid, time as _t
        session_cfg = {
            "session_id":      str(uuid.uuid4())[:12],
            "created_at":      _t.time(),
            "contract":        contract_dict,
            "source":          str(md_path) if md_path else "AGENTS.md",
            "cieu_db":         ".ystar_cieu.db",
            "governance_config": {
                "auto_activate_threshold": 0.9,
            },
        }
        with open(".ystar_session.json", "w", encoding="utf-8") as _f:
            json.dump(session_cfg, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Retroactive baseline scan
    print()
    _run_retroactive_baseline(contract_dict)
    print()


def _run_retroactive_baseline(contract_dict: dict, skip_prompt: bool = False) -> None:
    """
    Scan existing history, run retroactive baseline analysis.
    """
    import warnings as _w
    _w.filterwarnings("ignore")

    from ystar.kernel.history_scanner import scan_history, available_sources
    from ystar.kernel.retroactive import assess_batch, summarize
    from ystar.governance.retro_store import RetroBaselineStore
    from ystar.kernel.dimensions import IntentContract, normalize_aliases

    sources = available_sources()
    any_available = any(s["available"] for s in sources)

    cd = dict(contract_dict or {})
    cd.pop("temporal", None)
    try:
        contract = normalize_aliases(**cd)
    except Exception:
        contract = IntentContract()

    if not any_available:
        print("  --- Initial Baseline ---")
        print("  No historical behavior records found.")
        print()
        for s in sources:
            if not s["available"]:
                print(f"  - {s['label']}: {s.get('reason', 'unavailable')}")
        print()
        store = RetroBaselineStore()
        baseline_id = store.begin_baseline(
            contract_hash=contract.hash,
            notes="ystar setup, 0 historical records (no history sources)",
        )
        print(f"  Baseline file created: .ystar_retro_baseline.db")
        print(f"     Baseline ID: {baseline_id}")
        print(f"     Historical records: 0 (this is normal)")
        print()
        print("  After running an Agent, Y* will begin recording the CIEU causal chain.")
        print("  After running an Agent:")
        print("    ystar audit          view intent vs action causal report")
        print("    ystar quality        evaluate rule coverage")
        return

    print("  Scanning history...", end="", flush=True)
    records, source_id, source_desc = scan_history(days_back=30, max_records=5000)

    if not records:
        print(" no records found")
        print()
        store = RetroBaselineStore()
        baseline_id = store.begin_baseline(
            contract_hash=contract.hash,
            notes=f"ystar setup, source={source_id}, 0 records in last 30 days",
        )
        print(f"  Baseline file created: .ystar_retro_baseline.db")
        print(f"     Baseline ID: {baseline_id}")
        print(f"     Historical records: 0 (no records in last 30 days)")
        print()
        print("  Run ystar audit after running an Agent to build the first causal report.")
        return

    from ystar.adapters.claude_code_scanner import scan_summary
    summary_info = scan_summary(records)
    print(f" found {summary_info['total']} records (source: {source_desc})")

    if not skip_prompt:
        print()
        print(f"  {summary_info['sessions']} sessions, "
              f"date range: {summary_info['date_range']}")
        print(f"  Tool calls: "
              + ", ".join(f"{n}x{c}" for n, c in summary_info["top_tools"][:4]))
        print()
        print("  Y* will replay these historical records against your current rules,")
        print("  showing 'what Y* would have seen if it had been running'.")
        print()
        print("  Results go to .ystar_retro_baseline.db (separate file, no live CIEU impact).")
        print()
        try:
            answer = input("  Generate initial baseline report now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            store = RetroBaselineStore()
            baseline_id = store.begin_baseline(
                contract_hash=contract.hash,
                notes=f"ystar setup, source={source_id}, user cancelled",
            )
            print(f"  Baseline file created: .ystar_retro_baseline.db (empty)")
            print(f"     Baseline ID: {baseline_id}")
            return
        if answer in ("n", "no"):
            print()
            store = RetroBaselineStore()
            baseline_id = store.begin_baseline(
                contract_hash=contract.hash,
                notes=f"ystar setup, source={source_id}, user skipped",
            )
            print(f"  Baseline file created: .ystar_retro_baseline.db (empty)")
            print(f"     Baseline ID: {baseline_id}")
            print()
            print("  Skipped. Run ystar baseline later to generate the retroactive report.")
            return

    # Retroactive check (core layer)
    print()
    print("  Replaying history...", end="", flush=True)
    assessments   = assess_batch(records, contract)
    retro_summary = summarize(assessments)
    print(f" done ({len(assessments)} records)")

    store       = RetroBaselineStore()
    baseline_id = store.begin_baseline(
        contract_hash=contract.hash,
        notes=f"ystar init, source={source_id}, {len(assessments)} records",
    )
    store.write_assessments(assessments, baseline_id)

    quality_score = None
    dim_hints     = []
    try:
        from ystar.governance.metalearning import ContractQuality, DimensionDiscovery
        call_records = store.as_call_records(baseline_id, limit=300)
        if call_records:
            q             = ContractQuality.evaluate(contract, call_records)
            quality_score = q.quality_score
            dim_hints     = DimensionDiscovery.analyze(call_records)[:3]
    except Exception:
        pass

    _print_retro_baseline_report(retro_summary, quality_score, dim_hints, baseline_id)


def _print_retro_baseline_report(retro_summary, quality_score, dim_hints, baseline_id):
    """Print retroactive baseline report."""
    total = retro_summary.total
    deny  = retro_summary.deny_count
    allow = retro_summary.allow_count

    print()
    print(f"  Retroactive Baseline Report [based on real history]")
    print(f"  Records:  {total}")
    print(f"  Range:    {retro_summary.date_range}")
    print(f"  Sessions: {retro_summary.sessions}")
    print(f"  Allowed:  {allow} ({allow/max(total,1):.0%})")
    print(f"  Denied:   {deny} ({deny/max(total,1):.0%})")
    print()

    if retro_summary.top_violations:
        print("  Historical violation dimensions:")
        for dim, cnt in retro_summary.top_violations[:5]:
            bar = "=" * min(cnt * 2, 18)
            print(f"    {dim:<22} {bar} {cnt}")
        print()

    if quality_score is not None:
        print(f"  Contract quality score: {quality_score:.2f} / 1.00")
        print()

    if dim_hints:
        print("  DimensionDiscovery found uncovered patterns:")
        for hint in dim_hints:
            short = hint[:50] + "..." if len(hint) > 50 else hint
            print(f"    -> {short}")
        print()

    print(f"  Baseline anchored (ID: {baseline_id}).")
    print("  Data captured after running an Agent will be compared against this baseline.")


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
#  ystar check — policy check on JSONL events
# ══════════════════════════════════════════════════════════════════════

def _cmd_check(path: str) -> None:
    from ystar import IntentContract, check as ystar_check
    events_path = pathlib.Path(path)
    if not events_path.exists():
        print(f"File not found: {path}"); sys.exit(1)

    violations = 0
    total = 0
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        params = rec.get("params", rec)
        contract_def = rec.get("contract", {})
        c = IntentContract(**{k: v for k, v in contract_def.items()
                              if k in ("deny", "only_paths", "deny_commands",
                                       "only_domains", "invariant")})
        r = ystar_check(params, {}, c)
        total += 1
        if not r.passed:
            violations += 1
            for v in r.violations:
                print(f"VIOLATION  {v.dimension}: {v.message}")

    print(f"\nTotal: {total}  Violations: {violations}  "
          f"Pass rate: {(total-violations)/max(total,1)*100:.1f}%")


# ══════════════════════════════════════════════════════════════════════
#  ystar report (legacy simple version)
# ══════════════════════════════════════════════════════════════════════

def _cmd_report(path: str = "") -> None:
    """Generate governance report from CIEU + Omission data."""
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


# ══════════════════════════════════════════════════════════════════════
#  ystar simulate
# ══════════════════════════════════════════════════════════════════════

def _cmd_simulate(args: list) -> None:
    """Simulate A/B effect evaluation with built-in workload."""
    sessions = 50
    agents_md_path = None

    i = 0
    while i < len(args):
        if args[i] == "--sessions" and i + 1 < len(args):
            sessions = int(args[i + 1]); i += 2
        elif args[i] == "--agents-md" and i + 1 < len(args):
            agents_md_path = args[i + 1]; i += 2
        else:
            i += 1

    print()
    print("  Y* Effect Evaluation (built-in workload simulation)")
    print("  " + "-" * 40)
    print(f"  Simulating {sessions} sessions x 20 events (25% dangerous ops)")
    print("  Running...", end="", flush=True)

    try:
        import warnings
        warnings.filterwarnings("ignore")
        from ystar.integrations.simulation import WorkloadSimulator

        sim = WorkloadSimulator(sessions=sessions, seed=42)
        report = sim.run()

        print(" done")
        print()
        print("              No Y*     With Y*")
        print("  " + "-" * 32)
        print(f"  Dangerous op intercept  0%      {report.recall:.1%}")
        print(f"  Normal op FP rate       --      {report.false_positive_rate:.1%}")
        print(f"  Risk reduction          --      {report.risk_reduction:.1%}")
        print(f"  Runtime                 --      {report.run_time_sec:.2f}s")
        print()

        if report.recall > 0.9:
            print(f"  Conclusion: Y* intercepted {report.recall:.0%} of dangerous ops, "
                  f"FP rate {report.false_positive_rate:.1%}")
        else:
            print(f"  Conclusion: Intercept rate {report.recall:.0%}, "
                  "review rules for missing dangerous op coverage")
        print()
        print("  -- Recommended Integration Path (EnforcementMode) --")
        print("  Step 1: SIMULATE_ONLY  -> No blocking, only log hypothetical violations")
        print("  Step 2: OBSERVE_ONLY   -> Log real violations, no blocking, observe 1 week")
        print("  Step 3: FAIL_OPEN      -> Log + allow (degraded protection)")
        print("  Step 4: FAIL_CLOSED    -> Block on violation (strict compliance)")
        print()
        print("  Test with your own rules:")
        print("    ystar simulate --agents-md AGENTS.md")

    except Exception as e:
        print(f"\n  Simulation failed: {e}")
        print()


# ══════════════════════════════════════════════════════════════════════
#  ystar quality
# ══════════════════════════════════════════════════════════════════════

def _cmd_quality(args: list) -> None:
    """Evaluate contract quality against CIEU history."""
    db_path        = ".ystar_cieu.db"
    agents_md_path = None
    do_suggest     = False
    do_apply       = False

    i = 0
    while i < len(args):
        if args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]; i += 2
        elif args[i] == "--agents-md" and i + 1 < len(args):
            agents_md_path = args[i + 1]; i += 2
        elif args[i] == "--suggest":
            do_suggest = True; i += 1
        elif args[i] == "--apply":
            do_suggest = True
            do_apply   = True; i += 1
        else:
            i += 1

    print()
    print("  Y* Contract Quality Evaluation")
    print("  " + "-" * 50)

    from ystar.kernel.nl_to_contract import load_and_translate
    from ystar.kernel.dimensions import IntentContract, normalize_aliases

    contract_dict, src = load_and_translate(path=agents_md_path, confirm=False)
    if not contract_dict:
        print("  AGENTS.md not found, cannot evaluate contract quality.")
        print("  Tip: run ystar init first.")
        print()
        return

    cd = dict(contract_dict)
    cd.pop("temporal", None)
    try:
        contract = normalize_aliases(**cd)
    except Exception:
        contract = IntentContract()

    print(f"  Contract source: {src or '(unknown)'}")

    from ystar.governance.cieu_store import CIEUStore
    from ystar import check as ystar_check
    from ystar.governance.metalearning import CallRecord

    try:
        store = CIEUStore(db_path)
        total = store.count()
    except Exception as e:
        print(f"  Cannot read database {db_path}: {e}")
        print()
        return

    if total == 0:
        print("  CIEU database empty, run an Agent first.")
        print()
        return

    print(f"  Historical records: {total} (using most recent 500)")

    records_raw = store.query(limit=500)
    history     = []
    for r in records_raw:
        try:
            params = json.loads(r.params_json or "{}")
            chk    = ystar_check(params, {}, contract)
            history.append(CallRecord(
                seq=len(history),
                func_name=r.event_type or "unknown",
                params=params,
                result=json.loads(r.result_json or "{}"),
                violations=chk.violations,
                intent_contract=contract,
            ))
        except Exception:
            pass

    if not history:
        print("  Cannot parse historical records.")
        print()
        return

    from ystar.governance.metalearning import (
        learn, ContractQuality, DimensionDiscovery, derive_objective
    )

    print()
    print("  Running full-pipeline quality analysis...", end="", flush=True)
    result    = learn(history, base_contract=contract)
    objective = derive_objective(history)
    print(" done")
    print()

    quality = result.quality or ContractQuality.evaluate(contract, history)
    n_viol  = sum(1 for r in history if r.violations)
    n_safe  = len(history) - n_viol

    print("  Quality Results")
    print("  " + "-" * 50)
    print(f"  History sample: {len(history)} records (violations {n_viol} / safe {n_safe})")
    print()

    cov_label = "PASS" if quality.coverage_rate >= 0.9 else ("WARN" if quality.coverage_rate >= 0.6 else "FAIL")
    fp_label  = "PASS" if quality.false_positive_rate <= 0.05 else ("WARN" if quality.false_positive_rate <= 0.15 else "FAIL")
    qs_label  = "PASS" if quality.quality_score >= 0.8 else ("WARN" if quality.quality_score >= 0.6 else "FAIL")

    print(f"  [{cov_label}] Violation coverage:    {quality.coverage_rate:.0%}"
          f"  -- what % of historical violations current rules would prevent")
    print(f"  [{fp_label}] Normal op FP rate:      {quality.false_positive_rate:.0%}"
          f"  -- lower is better")
    print(f"  [{qs_label}] Overall quality score:  {quality.quality_score:.2f} / 1.00")
    print()
    print(f"  Recommended FP tolerance: {objective.fp_tolerance:.3f}"
          f"  -- derived from historical data (Pearl Rung-3)")
    print()

    diag = result.diagnosis or {}
    if any(v > 0 for v in diag.values()):
        print("  Runtime State Diagnosis (ABCD classification):")
        labels = {
            "A_ideal_deficient": "A Ideal-deficient (rules cover but did not trigger)",
            "B_execution_drift": "B Execution-drift (behavior deviates from intent)",
            "C_over_tightened":  "C Over-tightened (normal ops blocked)",
            "D_normal":          "D Normal operation",
        }
        for k, label in labels.items():
            v = diag.get(k, 0)
            if v > 0:
                print(f"    {label}: {v}")
        print()

    hints = result.dimension_hints or DimensionDiscovery.analyze(history)
    if hints:
        print("  DimensionDiscovery found uncovered violation patterns:")
        for h in hints[:3]:
            print(f"     -> {h}")
        print()
    else:
        print("  DimensionDiscovery: current dimensions cover all violation patterns")
        print()

    if not do_suggest:
        print("  Tip: run ystar quality --suggest to see rule optimization suggestions")
        print("       run ystar quality --apply  to interactively accept and write to AGENTS.md")
        print()
        return

    from ystar.governance.rule_advisor import generate_advice
    print("  Generating rule optimization suggestions...", end="", flush=True)
    advice = generate_advice(contract, history)
    print(f" done ({len(advice.suggestions)} suggestions)")
    print()

    if not advice.has_suggestions():
        print("  Current rules are optimal, no suggestions.")
        print()
        return

    _print_rule_suggestions(advice)

    if not do_apply:
        print()
        print("  Run ystar quality --apply to confirm and write to AGENTS.md")
        print()
        return

    print()
    _apply_suggestions(advice, agents_md_path or src)


def _print_rule_suggestions(advice) -> None:
    """Format and display rule suggestions grouped by type."""
    categories = [
        ("add",       "Suggested additions",     "  [+]"),
        ("tighten",   "Suggested tightening",    "  [^]"),
        ("relax",     "Suggested relaxation",    "  [v]"),
        ("dimension", "Suggested new dimensions", "  [~]"),
    ]

    has_any = False
    for kind, title, prefix in categories:
        group = [s for s in advice.suggestions if s.kind == kind]
        if not group:
            continue
        has_any = True
        print(f"  {title} ({len(group)})")
        print("  " + "-" * 50)
        for idx, s in enumerate(group, 1):
            conf_label = "HIGH" if s.confidence >= 0.8 else ("MED" if s.confidence >= 0.6 else "LOW")
            verified  = " (mathematically verified)" if s.verified else ""
            print(f"  {idx}. [{conf_label}] {s.description}{verified}")
            print(f"     Evidence: {s.evidence}")
            if s.rule_value is not None:
                print(f"     Suggested value: {s.rule_value}")
            if s.coverage > 0:
                print(f"     If accepted: coverage +{s.coverage:.0%}, FP rate {s.fp_rate:.0%}")
            print(f"     Confidence: {s.confidence:.0%}  Source: {s.source}")
            print()

    if not has_any:
        print("  No suggestions")


def _apply_suggestions(advice, agents_md_path: str) -> None:
    """Interactive per-suggestion confirmation, write accepted to AGENTS.md."""
    from ystar.governance.rule_advisor import (
        append_suggestions_to_agents_md, RuleSuggestion
    )
    from ystar.governance.metalearning import ConstraintRegistry, ManagedConstraint

    actionable = [s for s in advice.suggestions
                  if s.kind in ("add", "tighten") and s.rule_value is not None]

    if not actionable:
        print("  No directly applicable suggestions (no concrete rule values).")
        print()
        return

    print("  Per-suggestion confirmation")
    print("  " + "-" * 50)
    print("  [Y] Accept  [N] Skip  [?] Stash (write to ConstraintRegistry for review)")
    print()

    registry = ConstraintRegistry()
    accepted = []

    for idx, s in enumerate(actionable, 1):
        conf_label = "HIGH" if s.confidence >= 0.8 else "WARN"
        print(f"  [{idx}/{len(actionable)}] [{conf_label}] {s.description}")
        print(f"  Suggested: {s.rule_value}  Confidence: {s.confidence:.0%}")

        while True:
            try:
                ans = input("  Choice [Y/n/?] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if ans in ("", "y", "yes"):
                s.accepted = True
                accepted.append(s)
                print("  Accepted")
                break
            elif ans in ("n", "no"):
                s.accepted = False
                print("  Skipped")
                break
            elif ans in ("?", "p"):
                mc = ManagedConstraint(
                    id          = f"suggest-{idx}-{int(time.time())}",
                    dimension   = s.dimension,
                    rule        = str(s.rule_value),
                    status      = "DRAFT",
                    source      = f"ystar quality --apply ({s.source})",
                    confidence  = s.confidence,
                    created_at  = time.time(),
                    updated_at  = time.time(),
                    notes       = s.evidence,
                )
                try:
                    registry.add(mc)
                    print("  Stashed to ConstraintRegistry (DRAFT)")
                except Exception as e:
                    print(f"  Stash failed: {e}")
                break
            print("  Enter Y, N, or ?")
        print()

    if accepted:
        print(f"  Writing {len(accepted)} rules to AGENTS.md...", end="", flush=True)
        ok = append_suggestions_to_agents_md(
            agents_md_path, accepted, advice.history_size
        )
        if ok:
            print(" done")
            print()
            print("  AGENTS.md updated. Run ystar init to activate new rules:")
            print("     ystar init")
        else:
            print(" failed")
            print(f"  Cannot write to {agents_md_path}")
    else:
        print("  No suggestions accepted, AGENTS.md unchanged.")

    drafts = registry.by_status("DRAFT")
    if drafts:
        print()
        print(f"  {len(drafts)} suggestions stashed to ConstraintRegistry.")
        print("  Manage stashed suggestions:")
        print("    from ystar.governance.metalearning import ConstraintRegistry")
        print("    reg = ConstraintRegistry()")
        print("    reg.summary()")
    print()


# ══════════════════════════════════════════════════════════════════════
#  ystar pretrain
# ══════════════════════════════════════════════════════════════════════

def _cmd_pretrain(args: list) -> None:
    """ystar pretrain -- run full pretrain pipeline."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl",  default=None, help="JSONL data path")
    parser.add_argument("--days",   type=int, default=30)
    parser.add_argument("--quiet",  action="store_true")
    parsed = parser.parse_args(args)

    try:
        import subprocess, os
        pipeline = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "pretrain", "run_full_pretrain_pipeline.py"
        )
        if not os.path.exists(pipeline):
            print("pretrain/run_full_pretrain_pipeline.py not found")
            print("   Ensure full ystar is installed (including pretrain/ directory)")
            return
        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, pipeline],
            env=env,
            capture_output=parsed.quiet
        )
        if result.returncode != 0 and parsed.quiet:
            print("Pretrain failed, run ystar pretrain for details")
        elif result.returncode == 0 and parsed.quiet:
            from ystar.pretrain import pretrain_summary
            print(f"{pretrain_summary()}")
    except Exception as e:
        print(f"Pretrain error: {e}")


# ══════════════════════════════════════════════════════════════════════
#  ystar policy-builder
# ══════════════════════════════════════════════════════════════════════

def _cmd_policy_builder() -> None:
    """Launch Policy Builder UI (single-file HTML, no external deps)."""
    import webbrowser, http.server, threading, os

    candidates = [
        pathlib.Path(__file__).parent / "policy-builder.html",
        pathlib.Path(__file__).parent.parent / "policy-builder.html",
    ]
    html_path = None
    for c in candidates:
        if c.exists():
            html_path = c
            break

    if not html_path:
        print("policy-builder.html not found in ystar package.")
        print("   Find it at: https://github.com/liuhaotian2024-prog/Y-star-gov")
        return

    PORT = 7921
    os.chdir(html_path.parent)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass

    def serve():
        with http.server.HTTPServer(("", PORT), Handler) as httpd:
            httpd.serve_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    url = f"http://localhost:{PORT}/{html_path.name}"
    print()
    print(f"  Y*gov Policy Builder -- http://localhost:{PORT}/{html_path.name}")
    print("  " + "-" * 41)
    print("  Build your IntentContract visually, then copy the generated")
    print("  Python code into your AGENTS.md or session config.")
    print()
    print("  Press Ctrl+C to stop the server.")
    print()

    webbrowser.open(url)
    try:
        t.join()
    except KeyboardInterrupt:
        print("\n  Server stopped.")


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
        print()
        print("  Note: Baseline is captured automatically during 'ystar setup'.")
        print("        To re-run baseline, use 'ystar setup --yes'.")
        print("        For A/B simulation, use 'ystar simulate'.")
        print()
        sys.exit(0)

    else:
        print(f"Unknown command: {cmd}\n")
        print("Available commands: demo, setup, hook-install, doctor, verify, report,")
        print("                    seal, policy-builder, audit, check, init, version,")
        print("                    simulate, quality, baseline")
        sys.exit(1)


if __name__ == "__main__":
    main()

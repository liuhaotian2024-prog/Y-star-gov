# Layer: CLI
"""ystar CLI — quality, simulate, check, pretrain, policy-builder commands."""
from __future__ import annotations

import json
import sys
import time
import pathlib
from typing import Optional


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


def _cmd_pretrain(args: list) -> None:
    """ystar pretrain -- run full pretrain pipeline."""
    import argparse, subprocess, os
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl",  default=None, help="JSONL data path")
    parser.add_argument("--days",   type=int, default=30)
    parser.add_argument("--quiet",  action="store_true")
    parsed = parser.parse_args(args)

    try:
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


def _cmd_policy_builder() -> None:
    """Launch Policy Builder UI (single-file HTML, no external deps)."""
    import webbrowser, http.server, threading, os

    candidates = [
        pathlib.Path(__file__).parent.parent / "policy-builder.html",
        pathlib.Path(__file__).parent.parent.parent / "policy-builder.html",
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

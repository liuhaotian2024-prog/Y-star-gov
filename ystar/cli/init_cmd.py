# Layer: CLI
"""ystar CLI — init command and retroactive baseline."""
from __future__ import annotations

import json
import sys
from typing import Optional


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

    print()
    _run_retroactive_baseline(contract_dict)
    print()


def _run_retroactive_baseline(contract_dict: dict, skip_prompt: bool = False) -> None:
    """Scan existing history, run retroactive baseline analysis."""
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

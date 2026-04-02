"""ystar.dev_cli — 完全内聚版 v0.40.0 (see full docstring in module)"""
# This module is the canonical entry point for ystar-dev CLI
# Full implementation — no wrapper to external scripts

from __future__ import annotations
import json, logging, os, re, subprocess, sys, time
from pathlib import Path
from typing import List, Optional

RESET="\033[0m"; RED="\033[91m"; GREEN="\033[92m"
YELLOW="\033[93m"; BLUE="\033[94m"; BOLD="\033[1m"

def c(color, text): return f"{color}{text}{RESET}"

_THIS_DIR = Path(__file__).parent
_ROOT     = _THIS_DIR.parent
_AGENTS_MD = _ROOT / "AGENTS.md"

def _get_version():
    try:
        from ystar import __version__; return __version__
    except Exception: return "unknown"

def _get_all_versions():
    versions = {}
    for p in [_ROOT/"pyproject.toml", (_THIS_DIR/"..").resolve()/"pyproject.toml"]:
        if p.exists():
            m = re.search(r'^version\s*=\s*"([^"]+)"', p.read_text(), re.M)
            if m: versions[p.name] = m.group(1)
    init = _THIS_DIR/"__init__.py"
    if init.exists():
        m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text())
        if m: versions["__init__.py"] = m.group(1)
    return versions

def _check_changelog(version):
    for ch in [_ROOT/"CHANGELOG.md", _ROOT.parent/"ystar_pkg"/"CHANGELOG.md"]:
        if ch.exists():
            text = ch.read_text()
            if version not in text: return False
            m = re.search(r"^## \[?(\d+\.\d+\.\d+)", text, re.M)
            return bool(m and m.group(1) == version)
    return False

def _run_tests():
    try:
        r = subprocess.run(
            [sys.executable,"-m","pytest","ystar/tests/","ystar/scenarios/","-q","--tb=no"],
            capture_output=True, text=True, cwd=str(_ROOT), timeout=120)
        passed = int(re.search(r'(\d+) passed', r.stdout).group(1)) if 'passed' in r.stdout else 0
        failed = int(re.search(r'(\d+) failed', r.stdout).group(1)) if 'failed' in r.stdout else 0
        return (failed==0), passed, failed
    except Exception as e:
        logging.getLogger("ystar.dev_cli").warning("_run_tests failed: %s", e)
        return False, 0, -1

def _count_tests():
    try:
        r = subprocess.run(
            [sys.executable,"-m","pytest","ystar/tests/","ystar/scenarios/",
             "--collect-only","-q","--tb=no"],
            capture_output=True, text=True, cwd=str(_ROOT), timeout=30)
        m = re.search(r'(\d+) tests? collected', r.stdout)
        return int(m.group(1)) if m else 0
    except Exception as e:
        logging.getLogger("ystar.dev_cli").warning("_count_tests failed: %s", e)
        return 0

# ── check ─────────────────────────────────────────────────────────────
def cmd_check(args):
    if not args: print("usage: ystar-dev check <file> [--summary <text>]"); return 1
    file_path=args[0]; summary=""; agent="coder_agent"
    i=1
    while i<len(args):
        if args[i]=="--summary" and i+1<len(args): summary=args[i+1]; i+=2
        elif args[i]=="--agent" and i+1<len(args): agent=args[i+1]; i+=2
        else: i+=1

    print(f"\n{c(BOLD,'─'*60)}\n{c(BOLD,'ystar-dev check')}  {c(BLUE,file_path)}")
    if summary: print(f"  summary: {c(BLUE,summary)}")
    print(c(BOLD,'─'*60))

    try:
        from ystar.domains.ystar_dev import make_ystar_dev_session
        from ystar.domains.openclaw.adapter import OpenClawEvent, EventType, enforce, EnforceDecision
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1

    state = make_ystar_dev_session(f"dev_{int(time.time())}", test_count_before=_count_tests())
    ev = OpenClawEvent(event_type=EventType.FILE_WRITE, agent_id=agent,
                       session_id=state.session_id, task_ticket_id="AGENTS.md",
                       file_path=file_path, patch_summary=summary)
    decision, records = enforce(ev, state)
    rec = records[0] if records else None
    violations = [v for v in (rec.call_record.violations if rec else [])
                  if v.dimension != "phantom_variable"]

    if decision == EnforceDecision.ALLOW:
        print(f"\n  {c(GREEN,'✓ ALLOW')}  修改符合 Y* 开发约束")
        return 0
    elif decision == EnforceDecision.ESCALATE:
        print(f"\n  {c(YELLOW,'⚠ ESCALATE')}  需要人工审批")
        for v in violations: print(f"    {c(YELLOW,v.dimension)}: {v.message}")
        return 2
    else:
        print(f"\n  {c(RED,'✗ DENY')}  修改被 Y* 开发约束拦截")
        for v in violations: print(f"    {c(RED,v.dimension)}: {v.message}")
        if rec and rec.drift_details: print(f"    {c(RED,'drift')}: {rec.drift_details}")
        return 1

# ── release ───────────────────────────────────────────────────────────
def cmd_release():
    print(f"\n{c(BOLD,'═'*60)}\n{c(BOLD,'ystar-dev release')}  发布前合规检查\n{c(BOLD,'═'*60)}\n")
    ver=_get_version(); versions=_get_all_versions(); unique=set(versions.values())
    ok_ver = len(unique)==1 and list(unique)[0]==ver
    print(f"  {c(GREEN,'✓') if ok_ver else c(RED,'✗')} 版本号一致: {ver}")
    if not ok_ver:
        for f,v in versions.items(): print(f"      {f}: {v}")
    ok_cl = _check_changelog(ver)
    print(f"  {c(GREEN,'✓') if ok_cl else c(RED,'✗')} CHANGELOG 包含 v{ver}: {'是' if ok_cl else '否'}")
    ok_test, passed, failed = _run_tests()
    print(f"  {c(GREEN,'✓') if ok_test else c(RED,'✗')} 测试: {passed} passed, {failed} failed")
    ok_agents = _AGENTS_MD.exists()
    print(f"  {c(GREEN,'✓') if ok_agents else c(YELLOW,'⚠')} AGENTS.md: {'存在' if ok_agents else '缺失'}")
    all_ok = ok_ver and ok_cl and ok_test
    print(f"\n{c(BOLD,'─'*60)}")
    if all_ok:
        print(f"  {c(GREEN,BOLD+'✓ RELEASE READY')}  v{ver} 可以发布")
        entry={"type":"release","version":ver,"timestamp":time.time(),"test_count":passed,"decision":"ALLOW"}
        try:
            with open(_ROOT/".ystar_release_log.jsonl","a") as f: f.write(json.dumps(entry)+"\n")
            print(f"\n  {c(BLUE,'CIEU')} release record written → .ystar_release_log.jsonl")
        except Exception as e:
            print(f"  Warning: Could not write release log: {e}")
        return 0
    else:
        print(f"  {c(RED,BOLD+'✗ RELEASE BLOCKED')}  修复上述问题后重试")
        return 1

# ── agents ─────────────────────────────────────────────────────────────
def cmd_agents(regenerate=False):
    try: from ystar.domains.ystar_dev import YSTAR_CONSTITUTION
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    const=YSTAR_CONSTITUTION
    print(f"\n{c(BOLD,'Y* Development Constraints')}  [hash={const.hash[:16]}...]\n")
    def show(label, items, col=BLUE):
        if items:
            print(f"  {c(BOLD,label)}")
            for item in items[:5]: print(f"    {c(col,'•')} {item[:72]}")
            if len(items)>5: print(f"    ... +{len(items)-5} 条")
            print()
    show("铁律 deny", const.deny, RED)
    show("deny_commands", const.deny_commands, RED)
    show("invariant", const.invariant, GREEN)
    show("optional_invariant", const.optional_invariant, YELLOW)
    if const.field_deny:
        print(f"  {c(BOLD,'field_deny')}")
        for fn,bl in const.field_deny.items(): print(f"    {c(BLUE,'•')} [{fn}]: {bl[:2]}...")
        print()
    print(f"  {c(BLUE,'Hash')}: {const.hash[:32]}...")
    print(f"  {c(BLUE,'Source')}: ystar/domains/ystar_dev/__init__.py → YSTAR_CONSTITUTION")
    print(f"  {c(BLUE,'Derived')}: AGENTS.md (generated, not source of truth)")
    if regenerate or not _AGENTS_MD.exists():
        const.to_agents_md(str(_AGENTS_MD))
        print(f"\n  {c(GREEN,'✓')} AGENTS.md regenerated → {_AGENTS_MD}")
    else:
        print(f"\n  {c(YELLOW,'tip')}: 'ystar-dev agents --regenerate' to sync AGENTS.md")
    return 0

# ── status ─────────────────────────────────────────────────────────────
def cmd_status():
    print(f"\n{c(BOLD,'Y* Development Status')}\n")
    ver=_get_version(); versions=_get_all_versions()
    print(f"  {c(BOLD,'Version')}")
    for f,v in versions.items():
        print(f"    {c(GREEN,'✓') if v==ver else c(RED,'✗')} {f}: {v}")
    ok_test, passed, failed = _run_tests()
    print(f"\n  {c(BOLD,'Tests')}")
    print(f"    {c(GREEN,'✓') if ok_test else c(RED,'✗')} {passed} passed, {failed} failed")
    try:
        from ystar.domains.openclaw.adapter import get_cieu_log, EnforceDecision
        log=get_cieu_log(); deny_n=sum(1 for r in log if r.decision==EnforceDecision.DENY)
        print(f"\n  {c(BOLD,'CIEU Log (session)')}")
        print(f"    {len(log)} records  ({deny_n} DENY)")
    except Exception as e:
        print(f"  Warning: Could not load CIEU log: {e}")
    domains_dir = _THIS_DIR/"domains"
    if domains_dir.exists():
        domains=[d.name for d in domains_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
        print(f"\n  {c(BOLD,'Domain Packs')}")
        print(f"    {', '.join(sorted(domains))}")
    return 0

# ── add-rule ───────────────────────────────────────────────────────────
def cmd_add_rule(nl_text):
    try:
        from ystar.domains.ystar_dev import (YSTAR_CONSTITUTION, nl_to_contract_delta,
            propose_constitution_update, _record_constitution_change)
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    print(f"\n{c(BOLD,'─'*60)}\n{c(BOLD,'ystar-dev add-rule')}  NL → YSTAR_CONSTITUTION\n{c(BOLD,'─'*60)}")
    print(f"  Input: {c(BLUE,nl_text)}\n")
    delta = nl_to_contract_delta(nl_text)
    if not delta or not any(k in delta for k in ("deny","deny_commands","only_paths","invariant","value_range","field_deny")):
        print(f"  {c(YELLOW,'⚠')} No parseable constraints found."); return 1
    print(f"{c(BOLD,propose_constitution_update(delta, nl_text))}")
    print(f"\n  {c(YELLOW,'! HUMAN APPROVAL REQUIRED')}\n")
    try: answer=input("  Apply? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt): answer="n"
    if answer!="y": print(f"  {c(YELLOW,'○ Cancelled.')}"); return 0
    _record_constitution_change(YSTAR_CONSTITUTION.hash, YSTAR_CONSTITUTION.hash, delta, "add_rule", nl_text)
    YSTAR_CONSTITUTION.to_agents_md(str(_AGENTS_MD))
    print(f"  {c(GREEN,'✓')} AGENTS.md regenerated")
    with open(_ROOT/".ystar_pending_rules.jsonl","a") as f:
        f.write(json.dumps({"timestamp":time.time(),"nl_text":nl_text,"delta":delta,"approved":True})+"\n")
    print(f"  {c(GREEN,'✓')} Rule saved to .ystar_pending_rules.jsonl")
    return 0

# ── violations ─────────────────────────────────────────────────────────
def cmd_violations():
    try:
        from ystar.domains.ystar_dev import violations_summary, load_constitution_history
        from ystar.domains.openclaw.adapter import get_cieu_log, EnforceDecision
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    print(f"\n{c(BOLD,'Y* CIEU Violation Analysis')}\n{c(BOLD,'─'*60)}\n")
    log=get_cieu_log(); denied=[r for r in log if r.decision.value in ("deny","escalate")]
    if log:
        print(f"  {c(BOLD,'Session')}: {len(log)} records, {len(denied)} denied")
        for rec in denied[:5]:
            viols=[v for v in rec.call_record.violations if v.dimension!="phantom_variable"]
            if viols: print(f"    {c(RED,'✗')} [{viols[0].dimension}] {rec.event.agent_id}: {viols[0].message[:52]}")
    else: print(f"  {c(BLUE,'Session')}: no records")
    for p in violations_summary():
        print(f"    {c(YELLOW, str(p['count'])+'x')} [{p['type']}] {p['pattern'][:52]}")
    history=load_constitution_history()
    if history:
        print(f"\n  {c(BOLD,'History')}: {len(history)} changes")
        for h in history[-3:]:
            ts=time.strftime("%Y-%m-%d %H:%M", time.localtime(h["timestamp"]))
            print(f"    {ts}  [{h['source']}]")
    return 0

# ── diff ───────────────────────────────────────────────────────────────
def cmd_diff():
    try: from ystar.domains.ystar_dev import YSTAR_CONSTITUTION, load_constitution_history
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    history=load_constitution_history()
    print(f"\n{c(BOLD,'YSTAR_CONSTITUTION diff')}\n")
    print(f"  Current: {YSTAR_CONSTITUTION.hash[:32]}...")
    if not history: print(f"  {c(BLUE,'No history.')}"); return 0
    last=history[-1]
    if last["delta"]:
        for key,changes in last["delta"].items():
            if key.startswith("_") or not isinstance(changes,dict): continue
            for direction,items in changes.items():
                if isinstance(items,list):
                    col=GREEN if direction=="added" else RED
                    for item in items: print(f"    {c(col,'+' if direction=='added' else '-')} {key}: {item[:60]}")
    return 0

# ── history ────────────────────────────────────────────────────────────
def cmd_history():
    try: from ystar.domains.ystar_dev import load_constitution_history
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    history=load_constitution_history()
    print(f"\n{c(BOLD,'YSTAR_CONSTITUTION Evolution History')}\n")
    if not history: print(f"  {c(BLUE,'No history yet.')}"); return 0
    for i,h in enumerate(history):
        ts=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(h["timestamp"]))
        print(f"  {c(BLUE,f'#{i+1:02d}')}  {ts}  [{c(YELLOW,h.get('source','unknown'))}]")
        dk=[k for k in h["delta"].keys() if not k.startswith("_")]
        if dk: print(f"       changed: {', '.join(dk[:4])}")
        if h.get("rule_text"): print(f"       rule: \"{h['rule_text'][:40]}\"")
        print()
    return 0

# ── cieu ───────────────────────────────────────────────────────────────
def cmd_cieu(args):
    try: from ystar.domains.openclaw.adapter import get_cieu_log, replay_cieu, persist_cieu_log
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    subcmd=args[0] if args else "summary"
    if subcmd=="persist":
        n=persist_cieu_log()
        print(f"\n  {c(GREEN,'✓')} {n} CIEU records persisted to .ystar_cieu.jsonl"); return 0
    analysis=replay_cieu()
    print(f"\n{c(BOLD,'CIEU Session Analysis')}\n{c(BOLD,'─'*60)}\n")
    print(f"  Total: {c(BLUE,str(analysis['total']))}")
    for dec,cnt in sorted(analysis.get("by_decision",{}).items()):
        col=GREEN if dec=="allow" else (RED if dec=="deny" else YELLOW)
        print(f"    {c(col,dec):20} {cnt}")
    for v in analysis.get("violations",[])[:5]:
        print(f"    {c(RED,v['dimension']):20} ×{v['count']}  {v['examples'][0][:45] if v['examples'] else ''}")
    if subcmd=="replay":
        for t in analysis.get("timeline",[])[:20]:
            col=GREEN if t["decision"]=="allow" else RED
            print(f"    #{t['seq']:02d} {c(col,t['decision']):10} {t['agent']:15} {(t.get('file') or t['event'])[:35]}")
    print(f"\n  {c(BLUE,'Tip')}: ystar-dev cieu persist")
    return 0

# ── serve ──────────────────────────────────────────────────────────────
def cmd_serve(args):
    try: from ystar.adapters.connector import create_connector
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    port=7777; strict=False; paths=["./src","./tests"]; domains=[]; webhook=None
    i=0
    while i<len(args):
        if args[i]=="--port" and i+1<len(args): port=int(args[i+1]); i+=2
        elif args[i]=="--strict": strict=True; i+=1
        elif args[i]=="--paths" and i+1<len(args): paths=[p.strip() for p in args[i+1].split(",")]; i+=2
        elif args[i]=="--domains" and i+1<len(args): domains=[d.strip() for d in args[i+1].split(",")]; i+=2
        elif args[i]=="--webhook" and i+1<len(args): webhook=args[i+1]; i+=2
        else: i+=1
    print(f"\n{c(BOLD,'Y* OpenClaw Connector')} port={port} strict={strict}")
    create_connector(port=port, allowed_paths=paths,
                     allowed_domains=domains or None, strict=strict, webhook_url=webhook).run()
    return 0

# ── approve ────────────────────────────────────────────────────────────
def cmd_approve(args):
    try: from ystar.adapters.connector import get_approval_queue
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    queue=get_approval_queue(); subcmd=args[0] if args else "list"
    if subcmd=="list" or not args:
        pending=queue.list_pending()
        print(f"\n{c(BOLD,'Pending Approvals')}\n")
        if not pending: print(f"  {c(GREEN,'✓')} No pending approvals"); return 0
        for p in pending:
            exp=int(p.expires_at-time.time())
            print(f"  {c(YELLOW,p.approval_id)}  [{p.event_type}]  {p.event_detail}")
            print(f"    Risk: {c(RED,p.risk_reason[:60])}")
            print(f"    Expires in: {c(YELLOW,f'{exp}s')}\n")
        print("  Run: ystar-dev approve <id>  |  ystar-dev approve deny <id>")
        return 0
    elif subcmd=="deny" and len(args)>=2:
        ok=queue.deny(args[1],operator="cli"); print(f"  {c(RED,'✗') if ok else c(YELLOW,'⚠')} {'Denied' if ok else 'Not found'}: {args[1]}"); return 0 if ok else 1
    else:
        ok=queue.approve(subcmd,operator="cli"); print(f"  {c(GREEN,'✓') if ok else c(YELLOW,'⚠')} {'Approved' if ok else 'Not found'}: {subcmd}"); return 0 if ok else 1

# ── query (v0.30新機能) ────────────────────────────────────────────────

# ── simulate ────────────────────────────────────────────────────────────
def cmd_simulate(args):
    """A/B workload evidence simulation."""
    sessions=50; events=20; seed=None; output=None; verbose=False
    i=0
    while i<len(args):
        if args[i]=="--sessions" and i+1<len(args): sessions=int(args[i+1]); i+=2
        elif args[i]=="--events" and i+1<len(args): events=int(args[i+1]); i+=2
        elif args[i]=="--seed" and i+1<len(args): seed=int(args[i+1]); i+=2
        elif args[i]=="--output" and i+1<len(args): output=args[i+1]; i+=2
        elif args[i]=="--verbose": verbose=True; i+=1
        else: i+=1
    try:
        from ystar.integrations.simulation import WorkloadSimulator
    except ImportError as e: print(f"  {c(RED,'Error')}: {e}"); return 1
    print(f"\n{c(BOLD,'Y* Workload Evidence Simulation')}")
    print(f"  {sessions} sessions x {events} events/session")
    report = WorkloadSimulator(sessions=sessions, events_per_session=events, seed=seed).run(verbose=verbose)
    report.print_summary()
    if output: report.save(output)
    return 0

def cmd_query(args):
    """CIEU永続ログ検索・統計。v0.30新機能。"""
    if not args: print("usage: ystar-dev query <keyword> [--decision D] [--agent A]\n       ystar-dev query --stats"); return 1
    keyword=args[0] if not args[0].startswith("--") else None
    decision=None; agent_filter=None; stats_mode="--stats" in args
    i=0
    while i<len(args):
        if args[i]=="--decision" and i+1<len(args): decision=args[i+1]; i+=2
        elif args[i]=="--agent" and i+1<len(args): agent_filter=args[i+1]; i+=2
        else: i+=1
    log_path=_ROOT/".ystar_cieu.jsonl"
    if not log_path.exists():
        print(f"  {c(YELLOW,'⚠')} No persistent CIEU log. Run: ystar-dev cieu persist"); return 0
    records=[]
    for line in log_path.read_text().splitlines():
        try: records.append(json.loads(line))
        except Exception as e:
            print(f"  Warning: Could not parse CIEU record: {e}")
    if stats_mode:
        from collections import Counter
        by_dec=Counter(r.get("decision") for r in records)
        by_ev=Counter(r.get("event_type") for r in records)
        viols=Counter(v.get("dimension","") for r in records for v in r.get("violations",[]))
        print(f"\n{c(BOLD,'CIEU Stats')}  total={len(records)}\n")
        print(f"  {c(BOLD,'By Decision')}")
        for dec,cnt in by_dec.most_common():
            col=GREEN if dec=="allow" else (RED if dec=="deny" else YELLOW)
            print(f"    {c(col,dec):12} {cnt:4}  ({cnt*100//len(records) if records else 0}%)")
        print(f"\n  {c(BOLD,'By Event')}")
        for et,cnt in by_ev.most_common(5): print(f"    {et or 'unknown':20} {cnt}")
        if viols:
            print(f"\n  {c(BOLD,'Top Violations')}")
            for dim,cnt in viols.most_common(5): print(f"    {c(RED,dim):22} ×{cnt}")
        return 0
    results=[r for r in records
             if (not keyword or keyword.lower() in json.dumps(r).lower())
             and (not decision or r.get("decision")==decision)
             and (not agent_filter or r.get("agent_id")==agent_filter)]
    print(f"\n{c(BOLD,'CIEU Query')}  keyword={c(BLUE,keyword or '*')}  found={c(BLUE,str(len(results)))}/{len(records)}\n")
    for rec in results[:20]:
        ts=time.strftime("%m-%d %H:%M", time.localtime(rec.get("timestamp",0)))
        dec=rec.get("decision","?")
        col=GREEN if dec=="allow" else (RED if dec=="deny" else YELLOW)
        viols=rec.get("violations",[])
        viol_str=f"  [{viols[0]['dimension']}]" if viols else ""
        print(f"  {ts}  {c(col,dec):10} {rec.get('agent_id','?')[:15]:16} {rec.get('event_type','?')[:12]:14} {rec.get('file','')[:28]}{viol_str}")
    if len(results)>20: print(f"  ... and {len(results)-20} more")
    return 0

# ── main entry point ───────────────────────────────────────────────────

# ── omission (v0.31新機能) ─────────────────────────────────────────────
def cmd_omission(args):
    """
    Omission Governance Layer CLI  (v0.31+)

    サブコマンド:
      summary               全体サマリー（違反数・アクター別・タイプ別）
      replay [entity_id]    違反リプレイ（誰が・何を・何秒サボったか）
      timeline <entity_id>  単一エンティティの義務タイムライン
      rules                 有効ルール一覧と時限設定
      status <entity_id>    単一エンティティの義務ステータス
    """
    from ystar.governance.omission_store import OmissionStore
    from ystar.governance.omission_summary import (
        omission_summary, entity_timeline, replay,
        print_summary, print_replay,
    )
    from ystar.governance.omission_engine import OmissionEngine
    from ystar.governance.omission_rules import get_registry

    db_path = ".ystar_omission.db"
    subcmd  = args[0] if args else "summary"
    rest    = args[1:]

    # 数据库存在性检查
    import os
    if not os.path.exists(db_path):
        print(f"\n  {c(YELLOW,'⚠')}  No omission database found at {c(BLUE, db_path)}")
        print(f"  Omission tracking starts automatically when the OpenClaw adapter ingests events.")
        print(f"  To use in-session: from ystar import create_adapter; adapter = create_adapter()")
        return 0

    store = OmissionStore(db_path=db_path)

    if subcmd == "summary":
        s = omission_summary(store)
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  Y* OMISSION GOVERNANCE  ')}v{_get_version()}")
        print(f"{c(BOLD,'─'*60)}")
        total   = s["total_obligations"]
        viol    = s["total_violations"]
        open_   = s["open_obligations"]
        fulfill = s["fulfilled_obligations"]
        rate    = s["violation_rate"]
        rate_col = RED if rate > 0.3 else (YELLOW if rate > 0.1 else GREEN)
        print(f"  Obligations  : {c(BLUE,str(total))}  "
              f"({c(GREEN,str(fulfill))} fulfilled  "
              f"{c(YELLOW,str(open_))} open  "
              f"{c(RED,str(s['expired_obligations']))} expired)")
        print(f"  Violations   : {c(RED if viol else GREEN, str(viol))}")
        print(f"  Escalated    : {c(RED if s['escalated_violations'] else GREEN, str(s['escalated_violations']))}")
        print(f"  Violation rate: {c(rate_col, f'{rate:.1%}')}")
        if s["by_omission_type"]:
            print(f"\n{c(BOLD,'  By Omission Type:')}")
            for t, cnt in list(s["by_omission_type"].items())[:7]:
                bar = "█" * min(cnt, 30)
                short = t.replace("required_","").replace("_omission","")
                print(f"    {short:<35} {c(RED, bar)} {cnt}")
        if s["by_actor"]:
            print(f"\n{c(BOLD,'  Top Actors (most violations):')}")
            for actor, cnt in list(s["by_actor"].items())[:5]:
                print(f"    {actor:<30} {c(YELLOW, str(cnt))}")
        print(f"\n  {c(BLUE,'Tips')}:")
        print(f"    ystar-dev omission replay            # 全违规详情")
        print(f"    ystar-dev omission replay <entity>   # 单 entity 追责")
        print(f"    ystar-dev omission rules             # 查看规则配置")
        print()

    elif subcmd == "replay":
        entity_id = rest[0] if rest else None
        r = replay(store, entity_id=entity_id)
        scope_str = entity_id or "global"
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  OMISSION REPLAY')}  [{c(BLUE, scope_str)}]")
        print(f"{c(BOLD,'─'*60)}")
        print(f"  Total violations: {c(RED if r['total_violations'] else GREEN, str(r['total_violations']))}")
        if not r["violations"]:
            print(f"  {c(GREEN,'✓')} No omission violations found.")
        for v in r["violations"]:
            sev_col = RED if v["severity"] in ("high","critical") else YELLOW
            print(f"\n  {c(sev_col,'▶')} {c(BOLD, v['omission_type'])}")
            print(f"    entity   : {c(BLUE, v['entity_id'])} ({v['entity_type']})")
            print(f"    actor    : {c(YELLOW, v['actor_id'])}")
            if v["lineage"]:
                print(f"    lineage  : {' → '.join(v['lineage'])}")
            missing = [e for e in v["required_events"] if e not in v["actually_occurred_events"]]
            if missing:
                print(f"    missing  : {c(RED, ', '.join(missing))}")
            print(f"    overdue  : {c(RED, f"{v['overdue_secs']:.1f}s")}")
            print(f"    severity : {c(sev_col, v['severity'])}")
            if v["escalated"]:
                print(f"    escalated→ {c(RED, str(v['escalated_to']))}")
            if v["cieu_ref"]:
                print(f"    cieu_ref : {c(BLUE, v['cieu_ref'][:16])}...")
        print()

    elif subcmd == "timeline":
        if not rest:
            print(f"  usage: ystar-dev omission timeline <entity_id>"); return 1
        entity_id = rest[0]
        tl = entity_timeline(store, entity_id)
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  TIMELINE')}  [{c(BLUE, entity_id)}]  status={c(YELLOW, tl['entity_status'])}")
        print(f"{c(BOLD,'─'*60)}")
        s = tl["summary"]
        print(f"  events={s['events']}  obligations={s['obligations']}  "
              f"fulfilled={c(GREEN,str(s['fulfilled']))}  "
              f"open={c(YELLOW,str(s['open']))}  "
              f"violations={c(RED,str(s.get('violations',0)))}")
        print()
        for entry in tl["timeline"]:
            import time as _time
            ts_str = _time.strftime("%H:%M:%S", _time.localtime(entry["ts"]))
            kind = entry["kind"]
            if kind == "event":
                print(f"  {c(BLUE, ts_str)}  {c(GREEN,'EVENT')}      {entry['type']:40} actor={entry['actor']}")
            elif kind == "obligation_created":
                due = entry.get("due_at")
                due_str = _time.strftime("%H:%M:%S", _time.localtime(due)) if due else "?"
                status_col = GREEN if entry["status"] == "fulfilled" else (RED if entry["status"] == "expired" else YELLOW)
                print(f"  {c(BLUE, ts_str)}  {c(YELLOW,'OBLIGATION')}  {entry['type']:40} due={due_str} [{c(status_col, entry['status'])}]")
            elif kind == "obligation_fulfilled":
                print(f"  {c(BLUE, ts_str)}  {c(GREEN,'FULFILLED')}   {entry['type']}")
            elif kind == "violation":
                sev_col = RED if entry["severity"] in ("high","critical") else YELLOW
                print(f"  {c(BLUE, ts_str)}  {c(RED,'VIOLATION')}   {entry['omission']:40} +{entry['overdue_secs']:.0f}s [{c(sev_col, entry['severity'])}]")
        print()

    elif subcmd == "rules":
        registry = get_registry()
        rules = registry.summary()
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  OMISSION RULES')}  ({len(rules)} registered)")
        print(f"{c(BOLD,'─'*60)}")
        for r in rules:
            enabled_str = c(GREEN,"✓ enabled") if r["enabled"] else c(RED,"✗ disabled")
            sev_col = RED if r["severity"] == "high" else (YELLOW if r["severity"] == "medium" else BLUE)
            due = r["due_within_secs"]
            due_str = f"{int(due)}s" if due < 60 else f"{due/60:.0f}m"
            print(f"  {c(BOLD, r['rule_id']):<40} {enabled_str}")
            print(f"    obligation : {r['obligation_type']}")
            print(f"    triggers   : {', '.join(r['trigger_events'])}")
            print(f"    due within : {c(YELLOW, due_str)}   severity: {c(sev_col, r['severity'])}")
            print()

    elif subcmd == "status":
        if not rest:
            print(f"  usage: ystar-dev omission status <entity_id>"); return 1
        entity_id = rest[0]
        registry = get_registry()
        engine   = OmissionEngine(store=store, registry=registry)
        report   = engine.obligation_status_report(entity_id)
        can_close = report["can_close"]
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  OBLIGATION STATUS')}  [{c(BLUE, entity_id)}]")
        print(f"{c(BOLD,'─'*60)}")
        close_str = c(GREEN,"✓ may close") if can_close else c(RED,"✗ BLOCKED")
        print(f"  Closure gate : {close_str}")
        for status, obs in report["obligations"].items():
            col = GREEN if status=="fulfilled" else (RED if status in ("expired","escalated") else YELLOW)
            print(f"  {c(col, status.upper())} ({len(obs)}):")
            for ob in obs[:3]:
                print(f"    · {ob['obligation_type']:45} actor={ob['actor_id']}")
        if report["violations"]:
            print(f"  {c(RED,'VIOLATIONS')} ({len(report['violations'])}):")
            for v in report["violations"][:3]:
                print(f"    · {v['omission_type']:45} +{v['overdue_secs']:.0f}s overdue")
        print()

    elif subcmd == "heatmap":
        from ystar.governance.omission_summary import obligation_heatmap, actor_reliability_report
        hm = obligation_heatmap(store)
        ar = actor_reliability_report(store)
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  OBLIGATION HEATMAP')}  (entity_type × obligation_type failure rate)")
        print(f"{c(BOLD,'─'*60)}")
        for etype, otypes in sorted(hm["heatmap"].items()):
            print(f"  {c(BLUE, etype)}")
            for otype, counts in sorted(otypes.items(), key=lambda x: -x[1]["rate"]):
                short = otype.replace("required_","").replace("_omission","")
                rate  = counts["rate"]
                col   = RED if rate > 0.5 else (YELLOW if rate > 0.2 else GREEN)
                bar   = "█" * int(rate * 20)
                print(f"    {short:<38} {c(col,bar)} {rate:.0%} ({counts['violated']}/{counts['total']})")
        if hm["worst_combo"]["entity_type"]:
            worst = hm["worst_combo"]
            print(f"\n  {c(RED,'⚠ Worst')} : {worst['entity_type']} × "
                  f"{worst['obligation_type'].replace('required_','').replace('_omission','')} "
                  f"({worst['rate']:.0%})")
        if ar["actors"]:
            print(f"\n{c(BOLD,'  ACTOR RELIABILITY')} (worst first):")
            for a in ar["actors"][:5]:
                rate_col = RED if a["reliability_rate"] < 0.5 else (YELLOW if a["reliability_rate"] < 0.8 else GREEN)
                print(f"    {a['actor_id']:<30} {c(rate_col, f"{a['reliability_rate']:.0%}")} "
                      f"({a['fulfilled']}/{a['total_obligations']}) "
                      f"avg_overdue={a['avg_overdue_secs']:.0f}s")
        print()

    elif subcmd == "chain":
        from ystar.governance.omission_summary import chain_breakpoint_analysis
        ca = chain_breakpoint_analysis(store)
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  CHAIN BREAKPOINT ANALYSIS')}")
        print(f"{c(BOLD,'─'*60)}")
        print(f"  Total chains   : {ca['total_chains']}")
        print(f"  Broken chains  : {c(RED if ca['broken_chains'] else GREEN, str(ca['broken_chains']))}")
        print(f"  Max depth      : {ca['deepest_chain_length']}")
        if ca['most_common_break']:
            print(f"  Most common break: {c(RED, ca['most_common_break'])}")
        if ca['breakpoints']:
            print(f"\n{c(BOLD,'  Breakpoints by position:')}")
            for bp in ca['breakpoints']:
                bar = "█" * min(bp['count'], 30)
                print(f"    {bp['position']:<35} {c(RED, bar)} {bp['count']} "
                      f"(actors: {', '.join(bp['actors'][:3])}{'...' if len(bp['actors'])>3 else ''})")
        if ca['orphan_entities']:
            print(f"\n  {c(YELLOW,'⚠ Orphan entities')}: {ca['orphan_entities'][:5]}")
        print()

    elif subcmd == "intervention":
        from ystar.domains.openclaw.adapter import get_intervention_engine
        eng = get_intervention_engine()
        if eng is None:
            print(f"\n  {c(YELLOW,'⚠')}  Intervention engine not configured.")
            print(f"  Call configure_intervention_engine() to enable active intervention.")
            return 0
        entity_id = rest[0] if rest else None
        report = eng.intervention_report(actor_id=entity_id)
        print(f"\n{c(BOLD,'─'*60)}")
        print(f"{c(BOLD,'  ACTIVE INTERVENTIONS')}"
              f"  [{c(BLUE, report['scope'])}]")
        print(f"{c(BOLD,'─'*60)}")
        print(f"  Active pulses  : {c(RED if report['active_pulses'] else GREEN, str(report['active_pulses']))}")
        print(f"  Restricted     : {c(RED if report['restricted'] else GREEN, str(report['restricted']))}")
        if report['by_level']:
            print(f"\n{c(BOLD,'  By level:')}")
            level_cols = {
                'soft_pulse': YELLOW, 'interrupt_gate': RED, 'reroute_escalate': RED
            }
            for lvl, cnt in report['by_level'].items():
                col = level_cols.get(lvl, YELLOW)
                print(f"    {c(col, lvl):<30} {cnt}")
        if report['pulses']:
            print(f"\n{c(BOLD,'  Active pulses:')}")
            for p in report['pulses'][:5]:
                lvl_col = RED if p['level'] != 'soft_pulse' else YELLOW
                print(f"    {c(lvl_col,'▶')} [{c(lvl_col, p['level'])}] "
                      f"entity={p['entity_id']} actor={c(YELLOW,p['actor_id'])}")
                print(f"      omission: {p['omission_type']}")
                if p.get('escalate_to'):
                    print(f"      escalated→ {c(RED, p['escalate_to'])}")
        print()

    elif subcmd == "operator":
        # C3: Operator/principal summary view
        from ystar.governance.omission_summary import (
            omission_summary, chain_breakpoint_analysis, actor_reliability_report
        )
        s  = omission_summary(store)
        ca = chain_breakpoint_analysis(store)
        ar = actor_reliability_report(store)
        print(f"\n{'='*60}")
        print(f"  Y* OPERATOR SUMMARY  v{_get_version()}")
        print(f"{'='*60}")
        health = "🔴 CRITICAL" if s['violation_rate'] > 0.3 else ("🟡 DEGRADED" if s['violation_rate'] > 0.1 else "🟢 HEALTHY")
        print(f"\n  System health : {health}")
        print(f"  Violation rate: {c(RED if s['violation_rate']>0.3 else YELLOW, f"{s['violation_rate']:.1%}")}")
        print(f"  Broken chains : {c(RED if ca['broken_chains'] else GREEN, str(ca['broken_chains']))}")
        print(f"  Open obligations: {c(YELLOW, str(s['open_obligations']))}")
        print(f"  Escalated     : {c(RED if s['escalated_violations'] else GREEN, str(s['escalated_violations']))}")
        if ca['most_common_break']:
            print(f"\n  {c(BOLD,'Most common failure')}: {c(RED, ca['most_common_break'])}")
        if ar['actors']:
            worst = ar['actors'][0]
            if worst['reliability_rate'] < 0.8:
                print(f"  {c(BOLD,'Least reliable actor')}: {c(YELLOW, worst['actor_id'])} "
                      f"({worst['reliability_rate']:.0%})")
        print(f"\n  {c(BLUE,'Quick actions:')}")
        for cmd in ["omission summary", "omission chain", "omission heatmap",
                    "omission replay", "omission intervention"]:
            print(f"    ystar-dev {cmd}")
        print(f"{'='*60}\n")

    else:
        print(f"  Unknown subcommand: {subcmd}")
        print(f"  Options: summary | replay [entity] | timeline <entity> | "
              f"rules | status <entity> | heatmap | chain | intervention | operator")
        return 1

    return 0


# ── experiment (v0.34新機能) ───────────────────────────────────────────────
def cmd_experiment(args):
    """
    A/B 実験でomission + intervention の有効性を証明する。

    使用方法：
        ystar-dev experiment                        # 全シナリオ実行
        ystar-dev experiment <scenario>             # 単一シナリオ
        ystar-dev experiment <scenario> --trials N  # 試行回数指定
        ystar-dev experiment list                   # シナリオ一覧

    シナリオ：
        manager_no_dispatch   worker_no_ack
        active_then_silent    false_completion   healthy_closure
    """
    from ystar.products.omission_experiment import (
        run_ab_experiment, run_full_battery,
        print_ab_report, print_battery_report,
        _SCENARIO_FNS,
    )

    subcmd  = args[0] if args else "all"
    n_trials= 20
    seed    = 42
    i = 1
    while i < len(args):
        if args[i] == "--trials" and i + 1 < len(args):
            n_trials = int(args[i + 1]); i += 2
        elif args[i] == "--seed" and i + 1 < len(args):
            seed = int(args[i + 1]); i += 2
        else:
            i += 1

    if subcmd == "list":
        print(f"\n{c(BOLD,'Available scenarios:')}")
        for s in _SCENARIO_FNS:
            print(f"  {c(BLUE, s)}")
        print()
        return 0

    if subcmd == "all":
        print(f"\n{c(BOLD,'Running full A/B battery...')} ({n_trials} trials × 5 scenarios)")
        battery = run_full_battery(n_trials=n_trials, seed=seed)
        print_battery_report(battery)
        print(f"  {c(BLUE,'Tip')}: ystar-dev experiment <scenario> for detailed view")
        return 0

    scenario = subcmd
    if scenario not in _SCENARIO_FNS:
        print(f"  {c(RED,'Unknown scenario:')} {scenario}")
        print(f"  Run 'ystar-dev experiment list' to see available scenarios.")
        return 1

    print(f"\n{c(BOLD,'Running A/B experiment:')} {c(BLUE, scenario)}")
    print(f"  {n_trials} trials per group  |  seed={seed}")
    report = run_ab_experiment(scenario=scenario, n_trials=n_trials, random_seed=seed)
    print_ab_report(report)
    return 0


# ── report (v0.35新機能) ────────────────────────────────────────────────────
def cmd_report(args):
    """
    Y* ベースライン & 日次レポート生成。

    使用方法：
        ystar-dev report baseline              # 全量スナップショット
        ystar-dev report daily                 # 過去24時間
        ystar-dev report daily --since DATE    # 指定日以降
        ystar-dev report export --output FILE  # JSON出力
        ystar-dev report compare BASE CURRENT  # 2報告書を比較

    対応フォーマット：
        --format markdown (デフォルト) / json
    """
    from ystar.governance.reporting import ReportEngine, Report
    from ystar.governance.omission_store import OmissionStore
    import os

    subcmd = args[0] if args else "baseline"
    fmt    = "markdown"
    output = None
    since  = None

    i = 1
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output = args[i + 1]; i += 2
        elif args[i] == "--since" and i + 1 < len(args):
            # Parse DATE as Unix timestamp or ISO date
            try:
                import datetime
                d = datetime.datetime.strptime(args[i + 1], "%Y-%m-%d")
                since = d.timestamp()
            except Exception:
                since = float(args[i + 1])
            i += 2
        else:
            i += 1

    # Connect to stores
    omission_db = ".ystar_omission.db"
    cieu_db     = ".ystar_cieu.db"

    if not os.path.exists(omission_db):
        print(f"\n  {c(YELLOW,'⚠')}  No omission store found at {c(BLUE, omission_db)}")
        print(f"  Run workloads first to collect governance data.")
        return 0

    store = OmissionStore(db_path=omission_db)

    cieu = None
    if os.path.exists(cieu_db):
        try:
            from ystar.governance.cieu_store import CIEUStore
            cieu = CIEUStore(db_path=cieu_db)
        except Exception:
            pass

    # Intervention engine (in-memory, read from pulse_store only)
    engine = ReportEngine(
        omission_store   = store,
        cieu_store       = cieu,
        report_confidence = "full" if cieu else "partial",
    )

    if subcmd in ("baseline", "base"):
        report = engine.baseline_report()
    elif subcmd == "daily":
        report = engine.daily_report(since=since)
    elif subcmd == "export":
        report = engine.baseline_report()
        out_path = output or "ystar_report.json"
        with open(out_path, "w") as f:
            f.write(report.to_json())
        print(f"\n  {c(GREEN,'✓')} Report exported to {c(BLUE, out_path)}")
        return 0
    elif subcmd == "compare":
        print(f"  usage: ystar-dev report compare <base_json> <current_json>"); return 1
    else:
        print(f"  Unknown subcommand: {subcmd}"); return 1

    # Output
    if fmt == "json" or output and output.endswith(".json"):
        text = report.to_json()
    else:
        text = report.to_markdown()

    if output:
        with open(output, "w") as f:
            f.write(text)
        print(f"\n  {c(GREEN,'✓')} Report written to {c(BLUE, output)}")
    else:
        # Print to terminal
        lines = text.split("\n")
        for line in lines:
            if line.startswith("# "):
                print(f"\n{c(BOLD, line)}")
            elif line.startswith("## "):
                print(f"\n{c(BLUE, line)}")
            elif line.startswith("| ") and "|----" not in line:
                print(f"  {line}")
            elif "**" in line:
                # Bold highlights
                import re
                cleaned = re.sub(r"\*\*(.*?)\*\*", lambda m: c(BOLD, m.group(1)), line)
                print(f"  {cleaned}")
            elif line.strip() == "---":
                print(f"  {c(BOLD,'─'*56)}")
            else:
                print(f"  {line}" if line.strip() else "")

    return 0


# ── layers (v0.36.3) ────────────────────────────────────────────────────────
def cmd_layers(args):
    """
    現在のレイヤー構造を表示する。

    使用方法：
        ystar-dev layers          # 5層構造とファイル数を表示
        ystar-dev layers --check  # 境界違反をスキャン
        ystar-dev layers --canonical  # 正規インポートパスを表示
    """
    import pathlib, subprocess, sys

    subcmd = args[0] if args else "show"

    LAYERS = {
        "Kernel":     ("kernel/",    "#2196F3", "engine dimensions prefill"),
        "Governance": ("governance/","#4CAF50", "omission_* intervention_* governance_loop cieu_store metalearning"),
        "Adapters":   ("adapters/",  "#FF9800", "omission_adapter connector report_delivery"),
        "Products":   ("products/",  "#9C27B0", "reporting omission_experiment simulation check_service dev_cli"),
        "Domains":    ("domains/",   "#607D8B", "openclaw/ finance/ healthcare/ devops/"),
    }

    YSTAR = pathlib.Path("ystar")

    if subcmd in ("show", "--show"):
        print(f"\n{c(BOLD,'Y* Layer Structure v0.36.3')}")
        print(f"{'='*56}")
        for layer_name, (subdir, color, desc) in LAYERS.items():
            layer_path = YSTAR / subdir.rstrip('/')
            if layer_path.exists():
                files = [f for f in layer_path.glob("*.py") if f.name != "__init__.py"]
                n = len(files)
                names = " ".join(f.name.replace('.py','') for f in files[:4])
                if len(files) > 4: names += f" +{len(files)-4}"
            else:
                n, names = 0, "(not yet)"
            print(f"  {c(BOLD, f'{layer_name:<16}')} ystar/{subdir:<16} {n:>3} files")
            print(f"  {'':16} {c(BLUE, names[:50])}")
        print(f"\n  Root dir: {len(list(YSTAR.glob('*.py')))} files (legacy + backward compat)")
        print()

    elif subcmd in ("--check", "check"):
        print(f"\n{c(BOLD,'Running boundary check...')}")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_layer_boundaries.py", "-v", "--tb=short"],
            capture_output=True, text=True
        )
        # Print concise summary
        lines = r.stdout.split("\n")
        for line in lines:
            if "PASSED" in line:
                print(f"  {c(GREEN,'✓')} {line.split('::')[-1].split(' PASSED')[0].strip()}")
            elif "FAILED" in line:
                print(f"  {c(RED,'✗')} {line.split('::')[-1].split(' FAILED')[0].strip()}")
        summary = next((l for l in reversed(lines) if "passed" in l or "failed" in l), "")
        print(f"\n  {c(BOLD, summary.strip())}")

    elif subcmd in ("--canonical", "canonical"):
        print(f"\n{c(BOLD,'Canonical Import Paths (v0.36.3):')}")
        print()
        paths = [
            ("Kernel",     "from ystar.kernel import check, IntentContract, enforce"),
            ("Governance", "from ystar.governance import OmissionEngine, InterventionEngine"),
            ("Governance", "from ystar.governance.adaptive import ConstraintRegistry, GovernanceLoop"),
            ("Governance", "from ystar.governance.auto_configure import run_governance_auto_configure"),
            ("Governance", "from ystar.governance.report_metrics import ObligationMetrics"),
            ("Adapters",   "from ystar.adapters import OmissionAdapter, DeliveryManager"),
            ("Products",   "from ystar.products import run_ab_experiment"),
            ("Domains",    "from ystar.domains.openclaw.accountability_pack import apply_openclaw_accountability_pack"),
        ]
        layer_colors = {"Kernel":"#2196F3","Governance":"#4CAF50",
                        "Adapters":"#FF9800","Products":"#9C27B0","Domains":"#607D8B"}
        for layer, path in paths:
            print(f"  {c(BLUE, f'[{layer}]')}")
            print(f"    {c(BOLD, path)}")
        print()
    else:
        print(f"  Options: show | --check | --canonical")
    return 0

def main():
    args=sys.argv[1:]
    if not args or args[0] in ("-h","--help"):
        print(f"\n{c(BOLD,'ystar-dev')} v{_get_version()}  Y* Development CLI\n")
        for cmd,desc in [
            ("check <file>","pre-check before modifying"),
            ("release","full release compliance check"),
            ("agents","show constraints / regenerate AGENTS.md"),
            ("status","development status snapshot"),
            ("add-rule <NL>","propose a new rule"),
            ("violations","CIEU violation analysis"),
            ("diff","YSTAR_CONSTITUTION diff"),
            ("history","constitution evolution history"),
            ("cieu [persist|replay]","session CIEU analysis"),
            ("serve","start OpenClaw HTTP connector"),
            ("approve [list|<id>]","manage ESCALATE queue"),
            ("query <kw> [--stats]","search persistent CIEU log  [v0.30]"),
            ("omission [summary|replay|rules|heatmap|chain|intervention|operator]","omission governance  [v0.33]"),
            ("experiment [scenario|all|list]","A/B effectiveness experiment  [v0.34]"),
            ("report [baseline|daily|export]","baseline & daily report generator [v0.35]"),
            ("layers [--check|--canonical]","show 5-layer architecture status    [v0.36]"),
        ]: print(f"  {c(BLUE,'ystar-dev '+cmd):45} {desc}")
        print(); return 0

    cmd=args[0]
    if cmd=="check": return cmd_check(args[1:])
    elif cmd=="release": return cmd_release()
    elif cmd=="agents": return cmd_agents("--regenerate" in args or "--regen" in args)
    elif cmd=="status": return cmd_status()
    elif cmd=="add-rule": nl=" ".join(args[1:]); return cmd_add_rule(nl) if nl else (print("usage: ystar-dev add-rule <text>") or 1)
    elif cmd=="violations": return cmd_violations()
    elif cmd=="diff": return cmd_diff()
    elif cmd=="history": return cmd_history()
    elif cmd=="cieu": return cmd_cieu(args[1:])
    elif cmd=="serve": return cmd_serve(args[1:])
    elif cmd=="approve": return cmd_approve(args[1:])
    elif cmd=="query": return cmd_query(args[1:])
    elif cmd=="simulate": return cmd_simulate(args[1:])
    elif cmd=="omission": return cmd_omission(args[1:])
    elif cmd=="experiment": return cmd_experiment(args[1:])
    elif cmd=="report":     return cmd_report(args[1:])
    elif cmd=="layers":     return cmd_layers(args[1:])
    else: print(f"Unknown: {cmd}. Run 'ystar-dev --help'"); return 1

if __name__=="__main__":
    sys.exit(main())

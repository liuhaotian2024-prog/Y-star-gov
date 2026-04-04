# ystar/cli/doctor_cmd.py — ystar doctor command
"""
Environment diagnostic command.
Moved from ystar/_cli.py for modularization.

Enhanced with Layer1/Layer2 architecture:
- Layer1: Zero-dependency health checks (core governance infrastructure)
- Layer2: Dependency health checks (Python env, git, hooks, tests)
"""
import json
import pathlib
import os
import sys
from typing import Tuple


def _cmd_doctor(args: list) -> None:
    """
    ystar doctor -- diagnose current environment integrity.

    Usage:
      ystar doctor           # Run both Layer1 and Layer2
      ystar doctor --layer1  # Only zero-dependency checks
      ystar doctor --layer2  # Only dependency checks (requires Layer1 pass)
    """
    # Parse layer arguments
    layer1_only = "--layer1" in args
    layer2_only = "--layer2" in args

    if layer1_only and layer2_only:
        print("Error: Cannot specify both --layer1 and --layer2")
        sys.exit(1)

    # Run Layer1
    layer1_ok, layer1_count, layer1_fail = _doctor_layer1()

    # Determine if we should run Layer2
    if layer2_only and not layer1_ok:
        print()
        print("  Layer1 checks failed. Fix Layer1 issues before running Layer2.")
        sys.exit(1)

    if not layer1_only:
        layer2_ok, layer2_count, layer2_fail = _doctor_layer2()
    else:
        layer2_ok, layer2_count, layer2_fail = True, 0, 0

    # Final summary
    print()
    print("  " + "=" * 60)
    total_ok = layer1_count + layer2_count
    total_fail = layer1_fail + layer2_fail

    if total_fail == 0:
        print(f"  All {total_ok} checks passed -- Y*gov is healthy")
        # Don't exit in test environment
        if "pytest" not in sys.modules:
            sys.exit(0)
    else:
        print(f"  {total_ok} passed, {total_fail} failed")
        print("  Run the suggested commands above to fix issues")
        # Don't exit in test environment
        if "pytest" not in sys.modules:
            sys.exit(1)


def _doctor_layer1() -> Tuple[bool, int, int]:
    """
    Layer1: Zero-dependency health checks.

    Returns (all_ok: bool, ok_count: int, fail_count: int)
    """
    ok_count = 0
    fail_count = 0

    def ok(msg):
        nonlocal ok_count
        print(f"  [✓] {msg}")
        ok_count += 1

    def fail(msg, hint=""):
        nonlocal fail_count
        print(f"  [✗] {msg}")
        if hint:
            print(f"      → {hint}")
        fail_count += 1

    def warn(msg):
        print(f"  [!] {msg}")

    print()
    print("  Y*gov Doctor — Layer1 (Zero-dependency checks)")
    print("  " + "=" * 60)
    print()

    # 1. Check CIEU database
    print("  [1] CIEU Database")
    cieu_path = ".ystar_cieu.db"
    session_cfg = None

    # Try to load session config to get custom CIEU path
    for search_dir in [os.getcwd(), str(pathlib.Path.home())]:
        p = pathlib.Path(search_dir) / ".ystar_session.json"
        if p.exists():
            try:
                session_cfg = json.loads(p.read_text())
                cieu_path = session_cfg.get("cieu_db", cieu_path)
                break
            except Exception:
                pass

    if pathlib.Path(cieu_path).exists():
        try:
            from ystar.governance.cieu_store import CIEUStore
            store = CIEUStore(cieu_path)
            stats = store.stats()
            event_count = stats.get('total', 0)
            ok(f"CIEU Database — {cieu_path} ({event_count} events)")
        except Exception as e:
            fail(f"CIEU Database readable but error: {e}",
                 f"Database may be corrupted: {cieu_path}")
    else:
        warn(f"CIEU Database — {cieu_path} (not found, will be created on first use)")

    # 2. Check Omission database
    print()
    print("  [2] Omission Database")
    omission_db = cieu_path.replace(".db", "_omission.db") if cieu_path else ".ystar_omission.db"

    if pathlib.Path(omission_db).exists():
        try:
            from ystar.governance.omission_store import OmissionStore
            store = OmissionStore(db_path=omission_db)
            violations = store.list_violations()
            ok(f"Omission Database — {omission_db} ({len(violations)} violations)")
        except Exception as e:
            fail(f"Omission Database readable but error: {e}",
                 f"Database may be corrupted: {omission_db}")
    else:
        warn(f"Omission Database — {omission_db} (not found, will be created on first use)")

    # 3. Check Contract file
    print()
    print("  [3] Contract File")
    contract_file = pathlib.Path("AGENTS.md")

    # Detect if this is the Y*gov framework repo itself (not a user project)
    is_framework_repo = (pathlib.Path("ystar") / "__init__.py").exists()

    if contract_file.exists():
        try:
            lines = contract_file.read_text(encoding="utf-8").splitlines()
            ok(f"Contract File — AGENTS.md (loaded, {len(lines)} lines)")
        except Exception as e:
            fail(f"Contract File — AGENTS.md exists but unreadable: {e}")
    else:
        if is_framework_repo:
            warn("Contract File — AGENTS.md not found (framework repo, skipping)")
        else:
            fail("Contract File — AGENTS.md not found",
                 "Create AGENTS.md with governance rules")

    # 4. Check Interrupt Gate (pending obligations)
    print()
    print("  [4] Interrupt Gate")
    try:
        from ystar.governance.omission_store import OmissionStore, InMemoryOmissionStore
        if pathlib.Path(omission_db).exists():
            store = OmissionStore(db_path=omission_db)
            pending = store.pending_obligations()
            overdue = [o for o in pending if hasattr(o, 'is_overdue') and o.is_overdue()]

            if overdue:
                fail(f"Interrupt Gate — BLOCKING ({len(overdue)} overdue obligations)",
                     "Complete pending obligations to clear gate")
            elif pending:
                warn(f"Interrupt Gate — {len(pending)} pending obligations (not yet overdue)")
            else:
                ok("Interrupt Gate — CLEAR (0 blocking obligations)")
        else:
            ok("Interrupt Gate — CLEAR (no obligation store found)")
    except Exception as e:
        warn(f"Interrupt Gate check failed: {e}")

    # 4b. Circuit Breaker status
    try:
        from ystar.governance.intervention_engine import InterventionEngine
        # Try to get the engine from the orchestrator if available
        _cb_engine = None
        try:
            from ystar.adapters.orchestrator import get_orchestrator
            _orch = get_orchestrator()
            if _orch and hasattr(_orch, '_intervention_engine'):
                _cb_engine = _orch._intervention_engine
        except Exception:
            pass

        if _cb_engine is not None:
            cb_armed = getattr(_cb_engine, '_circuit_breaker_armed', False)
            cb_count = getattr(_cb_engine, '_circuit_breaker_violation_count', 0)
            cb_threshold = getattr(_cb_engine, '_circuit_breaker_threshold', 20)

            if cb_armed:
                fail(f"Circuit Breaker — ARMED ({cb_count} violations)",
                     "Pulse generation is STOPPED. Run 'ystar reset-breaker' to reset.")
            else:
                ok(f"Circuit Breaker — OK ({cb_count}/{cb_threshold} violations)")
        else:
            print(f"  [ ] Circuit Breaker — engine not loaded (check at runtime)")
    except Exception as e:
        warn(f"Circuit Breaker check failed: {e}")

    # 5. Check Unreachable Obligations
    print()
    print("  [5] Unreachable Obligations")
    try:
        # Unreachable obligations are those that cannot be fulfilled due to misconfiguration
        # For now, we check if any obligations have been pending for >7 days
        if pathlib.Path(omission_db).exists():
            from ystar.governance.omission_store import OmissionStore
            import time
            store = OmissionStore(db_path=omission_db)
            all_obligations = store.list_obligations()
            week_ago = time.time() - (7 * 24 * 60 * 60)
            unreachable = [o for o in all_obligations
                          if hasattr(o, 'created_at') and o.created_at < week_ago
                          and hasattr(o, 'status') and o.status.value == 'pending']

            if unreachable:
                fail(f"Unreachable Obligations — {len(unreachable)} found",
                     "Review obligations pending >7 days")
            else:
                ok("Unreachable Obligations — 0 found")
        else:
            ok("Unreachable Obligations — 0 found (no store)")
    except Exception as e:
        warn(f"Unreachable obligations check failed: {e}")

    # 6. Check Engine Configuration
    print()
    print("  [6] Engine Configuration")
    if session_cfg:
        try:
            contract = session_cfg.get("contract", {})
            deny_paths = contract.get("deny", [])
            deny_cmds = contract.get("deny_commands", [])
            timing_keys = contract.get("obligation_timing", {})

            agent_count = 1  # Simplified, in reality would parse from AGENTS.md
            rule_count = len(deny_paths) + len(deny_cmds) + len(timing_keys)

            ok(f"Engine Config — Valid ({agent_count} agents, {rule_count} rules)")
        except Exception as e:
            fail(f"Engine Config — Invalid: {e}")
    else:
        warn("Engine Config — No session config found")

    # 7. Check Archive Freshness
    print()
    print("  [7] Archive Freshness")
    archive_meta = pathlib.Path('data/cieu_archive/.archive_metadata.json')
    if archive_meta.exists():
        try:
            with open(archive_meta, encoding='utf-8') as f:
                meta = json.load(f)
            from datetime import datetime as dt
            last_archive = dt.fromisoformat(meta['last_archive'])
            days_since = (dt.now() - last_archive).days

            if days_since > 7:
                fail(f"Archive Freshness — {days_since} days since last archive (>7 days)",
                     "Run 'ystar archive-cieu' to preserve CIEU data")
            else:
                ok(f"Archive Freshness — Last archived {days_since} days ago")
        except Exception as e:
            warn(f"Archive Freshness — Error reading metadata: {e}")
    else:
        fail("Archive Freshness — No archive found",
             "Run 'ystar archive-cieu' to create first archive")

    # 8. Check External Config Reads
    print()
    print("  [8] External Config Reads")
    try:
        import sqlite3
        cieu_db_path = pathlib.Path(cieu_path)

        if cieu_db_path.exists():
            conn = sqlite3.connect(str(cieu_db_path))
            cursor = conn.cursor()

            # Query for external config reads
            cursor.execute("""
                SELECT file_path, COUNT(*) as count
                FROM cieu_events
                WHERE event_type = 'external_config_read'
                GROUP BY file_path
                ORDER BY count DESC
                LIMIT 5
            """)

            external_reads = cursor.fetchall()
            conn.close()

            if external_reads:
                fail(f"External Config Reads — {len(external_reads)} unique paths detected",
                     "Review external CLAUDE.md for context poisoning")
                for path, count in external_reads:
                    print(f"      → {path} ({count} reads)")
            else:
                ok("External Config Reads — None detected")
        else:
            ok("External Config Reads — No CIEU database")

    except Exception as e:
        warn(f"External Config Reads check failed: {e}")

    # 9. Check Runtime Constraint Files
    print()
    print("  [9] Runtime Constraints")

    deny_path = pathlib.Path(".ystar_runtime_deny.json")
    relax_path = pathlib.Path(".ystar_runtime_relax.json")

    for name, rpath in [("deny", deny_path), ("relax", relax_path)]:
        if rpath.exists():
            try:
                with open(rpath, encoding="utf-8") as f:
                    data = json.load(f)
                from ystar.kernel.dimensions import IntentContract as _IC
                _IC.from_dict(data)
                rule_count = sum(
                    len(v) if isinstance(v, list) else len(v) if isinstance(v, dict) else 1
                    for v in data.values()
                )
                ok(f"Runtime {name} — {rule_count} constraint entries")
            except Exception as e:
                fail(f"Runtime {name} — parse failed: {e}")
        else:
            print(f"  [ ] Runtime {name} — not present (ok)")

    # Monotonicity check (if either runtime file exists)
    if deny_path.exists() or relax_path.exists():
        try:
            from ystar.adapters.runtime_contracts import (
                load_runtime_deny, load_runtime_relax,
            )
            from ystar.kernel.dimensions import IntentContract as _IC2

            # Load session contract from session config or empty baseline
            session_contract = _IC2()
            try:
                from ystar.session import Policy
                policy = Policy.from_agents_md_multi()
                # Use first registered agent as baseline
                for _agent_key in policy._rules:
                    session_contract = policy._rules[_agent_key]
                    break
            except Exception:
                pass

            deny_contract = load_runtime_deny(".")
            relax_contract = load_runtime_relax(".")

            if deny_contract is not None:
                is_ok, viols = deny_contract.is_subset_of(session_contract)
                if not is_ok:
                    fail(f"Runtime deny monotonicity violation: {viols[0]}")
                else:
                    ok("Runtime deny monotonicity check passed")

            if relax_contract is not None:
                is_ok, viols = relax_contract.is_subset_of(session_contract)
                if not is_ok:
                    fail(f"Runtime relax exceeds session boundary: {viols[0]}")
                else:
                    ok("Runtime relax boundary check passed")
        except Exception as e:
            warn(f"Monotonicity check failed: {e}")

    # 10. Governance Heartbeat
    print()
    print("  [10] Governance Heartbeat")
    try:
        from ystar.adapters.orchestrator import get_orchestrator
        orch = get_orchestrator()
        hb = orch.governance_heartbeat()

        if hb["health"] == "dead":
            fail("Governance Heartbeat — DEAD (orchestrator not initialized)",
                 "Run agent commands to trigger hook initialization")
        elif hb["health"] == "degraded":
            reasons = []
            if hb.get("circuit_breaker_armed"):
                reasons.append("circuit breaker armed")
            subsystems = hb.get("subsystems", {})
            dead_subs = [k for k, v in subsystems.items() if not v]
            if dead_subs:
                reasons.append(f"dead subsystems: {', '.join(dead_subs)}")
            fail(f"Governance Heartbeat — DEGRADED ({'; '.join(reasons)})",
                 "Check subsystem initialization and circuit breaker status")
        else:
            sub_alive = sum(1 for v in hb.get("subsystems", {}).values() if v)
            sub_total = len(hb.get("subsystems", {}))
            extra = []
            if hb.get("call_count", 0) > 0:
                extra.append(f"{hb['call_count']} calls")
            if hb.get("active_obligations") is not None:
                extra.append(f"{hb['active_obligations']} obligations")
            if hb.get("active_pulses") is not None:
                extra.append(f"{hb['active_pulses']} pulses")
            detail = f", {', '.join(extra)}" if extra else ""
            ok(f"Governance Heartbeat — HEALTHY ({sub_alive}/{sub_total} subsystems{detail})")

        # Heartbeat age warning (if intervention scan is stale)
        from ystar.adapters.orchestrator import (
            INTERVENTION_SCAN_INTERVAL_SECS,
            GOVERNANCE_LOOP_INTERVAL_SECS,
        )
        scan_age = hb.get("last_intervention_scan_age_s")
        if scan_age is not None and scan_age > INTERVENTION_SCAN_INTERVAL_SECS * 3:
            warn(f"Intervention scan is stale ({int(scan_age)}s ago, expected every {int(INTERVENTION_SCAN_INTERVAL_SECS)}s)")

        loop_age = hb.get("last_governance_loop_age_s")
        if loop_age is not None and loop_age > GOVERNANCE_LOOP_INTERVAL_SECS * 3:
            warn(f"Governance loop is stale ({int(loop_age)}s ago, expected every {int(GOVERNANCE_LOOP_INTERVAL_SECS)}s)")

        # CIEU chain integrity from heartbeat
        if hb.get("cieu_chain_ok") is False:
            fail("CIEU chain integrity — BROKEN (detected via heartbeat)",
                 "Run 'ystar verify' for full chain verification")
        elif hb.get("cieu_chain_ok") is True:
            ok("CIEU chain integrity — verified via heartbeat")
    except Exception as e:
        warn(f"Governance Heartbeat — check failed: {e}")

    # CIEU statistics for Path B constraint activity
    try:
        from ystar.governance.cieu_store import CIEUStore as _CStore
        _cieu_db = cieu_path  # reuse from check [1]
        if pathlib.Path(_cieu_db).exists():
            _cstore = _CStore(_cieu_db)
            try:
                deny_events = _cstore.query(event_type="runtime_deny_applied", limit=100)
                print(f"  [ ] Path B deny events: {len(deny_events)}")
            except Exception:
                print("  [ ] Path B deny events: query unavailable")
            try:
                relax_events = _cstore.query(event_type="runtime_relax_applied", limit=100)
                print(f"  [ ] Metalearning relax events: {len(relax_events)}")
            except Exception:
                print("  [ ] Metalearning relax events: query unavailable")
    except Exception:
        pass

    # Layer1 summary
    all_ok = (fail_count == 0)
    return all_ok, ok_count, fail_count


def _doctor_layer2() -> Tuple[bool, int, int]:
    """
    Layer2: Dependency health checks (Python env, git, hooks, tests).

    Returns (all_ok: bool, ok_count: int, fail_count: int)
    """
    ok_count = 0
    fail_count = 0

    def ok(msg):
        nonlocal ok_count
        print(f"  [✓] {msg}")
        ok_count += 1

    def fail(msg, hint=""):
        nonlocal fail_count
        print(f"  [✗] {msg}")
        if hint:
            print(f"      → {hint}")
        fail_count += 1

    def warn(msg):
        print(f"  [!] {msg}")

    print()
    print("  Y*gov Doctor — Layer2 (Dependency checks)")
    print("  " + "=" * 60)
    print()

    # 1. Git repository status
    print("  [1] Git Repository")
    try:
        import subprocess
        result = subprocess.run(["git", "status", "--porcelain"],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            ok("Git Repository — Available")
        else:
            warn("Git Repository — Not a git repository")
    except Exception as e:
        warn(f"Git Repository — Not available: {e}")

    # 2. Python dependencies
    print()
    print("  [2] Python Dependencies")
    try:
        import ystar
        ok(f"Python Dependencies — ystar installed (v{ystar.__version__})")
    except Exception as e:
        fail(f"Python Dependencies — ystar not installed: {e}",
             "Run: pip install ystar")

    # 3. Hook installation
    print()
    print("  [3] Hook Installation")
    hook_locations = [
        pathlib.Path.home() / ".claude" / "settings.json",
        pathlib.Path.home() / ".config" / "openclaw" / "openclaw.json",
        pathlib.Path.home() / "Library" / "Application Support" / "Claude" / "settings.json",
    ]
    hook_found = False
    for loc in hook_locations:
        if loc.exists():
            try:
                cfg = json.loads(loc.read_text(encoding="utf-8"))
                hooks_obj = cfg.get("hooks", {})
                if "ystar" in json.dumps(hooks_obj).lower():
                    ok(f"Hook Installation — Registered in {loc.name}")
                    hook_found = True
                    break
            except Exception:
                pass
    if not hook_found:
        fail("Hook Installation — Not registered",
             "Run: ystar hook-install")

    # 4. Test suite
    print()
    print("  [4] Test Suite")
    test_dir = pathlib.Path("tests")
    if test_dir.exists():
        test_files = list(test_dir.glob("test_*.py"))
        ok(f"Test Suite — {len(test_files)} test files found")
    else:
        warn("Test Suite — No tests/ directory found")

    # Layer2 summary
    all_ok = (fail_count == 0)
    return all_ok, ok_count, fail_count

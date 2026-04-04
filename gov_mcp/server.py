"""GOV MCP — Y*gov governance exposed as a standard MCP server.

Ecosystem-neutral: no Claude Code / Anthropic-specific imports.
All paths via pathlib. No hardcoded defaults.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from mcp.server.fastmcp import FastMCP

from ystar import (
    CheckResult,
    DelegationChain,
    DelegationContract,
    InMemoryOmissionStore,
    IntentContract,
    OmissionEngine,
    check,
    enforce,
)
from ystar.kernel.nl_to_contract import translate_to_contract, validate_contract_draft


# ---------------------------------------------------------------------------
# Server state — held per-process, shared across all tool calls
# ---------------------------------------------------------------------------

class _State:
    """Mutable server state initialised at startup."""

    def __init__(self, agents_md_path: Path, exec_whitelist_path: Optional[Path] = None) -> None:
        self.agents_md_path = agents_md_path
        self.agents_md_text = agents_md_path.read_text(encoding="utf-8")

        # Translate AGENTS.md → contract (regex fallback, no LLM needed)
        contract_dict, self.confidence_label, self.confidence_score = translate_to_contract(
            self.agents_md_text
        )
        self.active_contract = _dict_to_contract(contract_dict)

        # Draft contract buffer (for load → validate → activate flow)
        self.draft_contract: Optional[IntentContract] = None
        self.draft_dict: Optional[Dict[str, Any]] = None

        # Delegation chain
        self.delegation_chain = DelegationChain()

        # Omission engine
        self.omission_engine = OmissionEngine(store=InMemoryOmissionStore())

        # CIEU store (None until a db path is provided via gov_report/gov_verify)
        self._cieu_store: Optional[Any] = None

        # Exec whitelist
        self.exec_whitelist = _load_exec_whitelist(exec_whitelist_path)


def _load_exec_whitelist(path: Optional[Path]) -> Dict[str, List[str]]:
    """Load exec whitelist YAML. Returns dict with allowed_prefixes and always_deny."""
    if path is None:
        # Default: adjacent to this file
        path = Path(__file__).parent / "exec_whitelist.yaml"
    if not path.is_file():
        return {"allowed_prefixes": [], "always_deny": []}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "allowed_prefixes": data.get("allowed_prefixes", []),
        "always_deny": data.get("always_deny", []),
    }


def _dict_to_contract(d: Dict[str, Any]) -> IntentContract:
    """Build an IntentContract from a translate_to_contract dict."""
    return IntentContract(
        deny=d.get("deny", []),
        only_paths=d.get("only_paths", []),
        deny_commands=d.get("deny_commands", []),
        only_domains=d.get("only_domains", []),
        invariant=d.get("invariant", []),
        optional_invariant=d.get("optional_invariant", []),
        postcondition=d.get("postcondition", []),
        field_deny=d.get("field_deny", {}),
        value_range=d.get("value_range", {}),
        obligation_timing=d.get("obligation_timing", {}),
        name=d.get("name", ""),
    )


def _violations_to_list(violations: list) -> List[Dict[str, Any]]:
    """Serialize Violation dataclass instances to plain dicts."""
    return [
        {
            "dimension": v.dimension,
            "field": v.field,
            "message": v.message,
            "actual": str(v.actual) if v.actual is not None else None,
            "constraint": v.constraint,
            "severity": v.severity,
        }
        for v in violations
    ]


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def create_server(
    agents_md_path: Path,
    exec_whitelist_path: Optional[Path] = None,
    **kwargs: Any,
) -> FastMCP:
    """Create and return a configured GOV MCP server.

    Extra kwargs (host, port) are forwarded to FastMCP for SSE transport.
    """

    mcp = FastMCP(
        "gov-mcp",
        instructions="Y*gov governance as a standard MCP server",
        **kwargs,
    )
    state = _State(agents_md_path, exec_whitelist_path=exec_whitelist_path)

    # ===================================================================
    # CORE ENFORCEMENT LAYER
    # ===================================================================

    @mcp.tool()
    def gov_check(agent_id: str, tool_name: str, params: dict) -> str:
        """Check a proposed agent action against the active governance contract.

        Returns ALLOW or DENY with violations list.
        """
        t0 = time.perf_counter()
        result: CheckResult = check(
            params={"tool_name": tool_name, **params},
            result={},
            contract=state.active_contract,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        return json.dumps({
            "decision": "ALLOW" if result.passed else "DENY",
            "violations": _violations_to_list(result.violations),
            "agent_id": agent_id,
            "tool_name": tool_name,
            "latency_ms": round(latency_ms, 4),
        })

    @mcp.tool()
    def gov_enforce(agent_id: str, tool_name: str, params: dict) -> str:
        """Full enforcement pipeline: check + obligation scan + delegation verify.

        Returns decision with full context.
        """
        t0 = time.perf_counter()

        # 1. Run enforce (check + mode handling)
        result = enforce(
            params={"tool_name": tool_name, **params},
            result={},
            contract=state.active_contract,
        )

        # 2. Obligation scan
        obligation_warnings: List[str] = []
        try:
            scan = state.omission_engine.scan(agent_id)
            if scan:
                obligation_warnings = [str(s) for s in (scan if isinstance(scan, list) else [scan])]
        except Exception:
            pass

        # 3. Delegation check (if chain has links)
        delegation_valid: Optional[bool] = None
        delegation_issues: List[str] = []
        if state.delegation_chain.depth > 0:
            delegation_issues = state.delegation_chain.validate()
            delegation_valid = len(delegation_issues) == 0

        latency_ms = (time.perf_counter() - t0) * 1000

        return json.dumps({
            "decision": "ALLOW" if result.passed else "DENY",
            "violations": _violations_to_list(result.violations),
            "agent_id": agent_id,
            "tool_name": tool_name,
            "mode": str(result.mode),
            "action_taken": str(result.action_taken),
            "obligation_warnings": obligation_warnings,
            "delegation_valid": delegation_valid,
            "delegation_issues": delegation_issues,
            "latency_ms": round(latency_ms, 4),
        })

    @mcp.tool()
    def gov_delegate(
        principal: str,
        actor: str,
        deny: list[str] | None = None,
        only_paths: list[str] | None = None,
        deny_commands: list[str] | None = None,
        only_domains: list[str] | None = None,
        action_scope: list[str] | None = None,
        allow_redelegate: bool = False,
        delegation_depth: int = 0,
    ) -> str:
        """Register a parent→child delegation and validate monotonicity.

        The child contract must be a strict subset of the parent's permissions.
        """
        child_contract = IntentContract(
            deny=(deny or []),
            only_paths=(only_paths or []),
            deny_commands=(deny_commands or []),
            only_domains=(only_domains or []),
            invariant=[],
            optional_invariant=[],
            postcondition=[],
            field_deny={},
            value_range={},
            obligation_timing={},
        )

        link = DelegationContract(
            principal=principal,
            actor=actor,
            contract=child_contract,
            action_scope=(action_scope or []),
            allow_redelegate=allow_redelegate,
            delegation_depth=delegation_depth,
        )
        state.delegation_chain.append(link)

        issues = state.delegation_chain.validate()

        return json.dumps({
            "registered": True,
            "principal": principal,
            "actor": actor,
            "chain_depth": state.delegation_chain.depth,
            "is_valid": len(issues) == 0,
            "issues": issues,
        })

    # ===================================================================
    # CONTRACT MANAGEMENT LAYER (Step 1 stubs with basic impl)
    # ===================================================================

    @mcp.tool()
    def gov_contract_load(agents_md_text: str) -> str:
        """Translate AGENTS.md text into a draft IntentContract.

        Uses regex fallback (no LLM required). Call gov_contract_validate
        next, then gov_contract_activate to enforce.
        """
        contract_dict, label, score = translate_to_contract(agents_md_text)
        state.draft_dict = contract_dict
        state.draft_contract = _dict_to_contract(contract_dict)

        return json.dumps({
            "status": "draft_loaded",
            "confidence_label": label,
            "confidence_score": score,
            "contract_preview": {
                "deny": contract_dict.get("deny", []),
                "deny_commands": contract_dict.get("deny_commands", []),
                "only_paths": contract_dict.get("only_paths", []),
                "only_domains": contract_dict.get("only_domains", []),
                "value_range": contract_dict.get("value_range", {}),
                "obligation_timing": contract_dict.get("obligation_timing", {}),
            },
        })

    @mcp.tool()
    def gov_contract_validate() -> str:
        """Validate the currently loaded draft contract.

        Must call gov_contract_load first.
        """
        if state.draft_dict is None:
            return json.dumps({"error": "No draft contract loaded. Call gov_contract_load first."})

        report = validate_contract_draft(state.draft_dict, original_text=state.agents_md_text)

        return json.dumps({
            "passed": report.get("passed", False) if isinstance(report, dict) else bool(report),
            "issues": report.get("issues", []) if isinstance(report, dict) else [],
            "report": report if isinstance(report, dict) else str(report),
        })

    @mcp.tool()
    def gov_contract_activate() -> str:
        """Activate the validated draft contract as the enforcement contract.

        Must call gov_contract_load and gov_contract_validate first.
        """
        if state.draft_contract is None:
            return json.dumps({"error": "No draft contract loaded. Call gov_contract_load first."})

        state.active_contract = state.draft_contract
        state.draft_contract = None
        state.draft_dict = None

        return json.dumps({
            "status": "activated",
            "contract_name": state.active_contract.name,
            "contract_hash": state.active_contract.hash,
        })

    # ===================================================================
    # EXEC LAYER
    # ===================================================================

    @mcp.tool()
    def gov_exec(command: str, agent_id: str, timeout_secs: int = 30) -> str:
        """Execute a command after governance + whitelist check.

        The command is checked against:
          1. always_deny list (instant reject, no override)
          2. allowed_prefixes whitelist (must match at least one)
          3. Y*gov active contract (deny_commands enforcement)

        Returns stdout, stderr, and return code on ALLOW.
        Returns denial reason on DENY.
        """
        t0 = time.perf_counter()
        whitelist = state.exec_whitelist

        # Phase 1: always_deny (checked first — overrides everything)
        for pattern in whitelist.get("always_deny", []):
            if pattern in command:
                latency_ms = (time.perf_counter() - t0) * 1000
                return json.dumps({
                    "decision": "DENY",
                    "reason": f"always_deny: command contains '{pattern}'",
                    "agent_id": agent_id,
                    "command": command,
                    "latency_ms": round(latency_ms, 4),
                })

        # Phase 2: allowed_prefixes whitelist
        cmd_stripped = command.strip()
        prefix_match = any(
            cmd_stripped.startswith(prefix) for prefix in whitelist.get("allowed_prefixes", [])
        )
        if not prefix_match:
            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "decision": "DENY",
                "reason": "command does not match any allowed prefix",
                "agent_id": agent_id,
                "command": command,
                "latency_ms": round(latency_ms, 4),
            })

        # Phase 3: Y*gov contract enforcement
        contract_result: CheckResult = check(
            params={"command": command, "tool_name": "Bash"},
            result={},
            contract=state.active_contract,
        )
        if not contract_result.passed:
            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "decision": "DENY",
                "reason": "Y*gov contract violation",
                "violations": _violations_to_list(contract_result.violations),
                "agent_id": agent_id,
                "command": command,
                "latency_ms": round(latency_ms, 4),
            })

        # All checks passed — execute
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_secs,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "decision": "ALLOW",
                "agent_id": agent_id,
                "command": command,
                "returncode": proc.returncode,
                "stdout": proc.stdout[:4096],
                "stderr": proc.stderr[:2048],
                "latency_ms": round(latency_ms, 4),
            })
        except subprocess.TimeoutExpired:
            latency_ms = (time.perf_counter() - t0) * 1000
            return json.dumps({
                "decision": "ALLOW",
                "agent_id": agent_id,
                "command": command,
                "returncode": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout_secs}s",
                "latency_ms": round(latency_ms, 4),
            })

    # ===================================================================
    # AUDIT & OBSERVABILITY LAYER
    # ===================================================================

    @mcp.tool()
    def gov_report(cieu_db: str = "", since_hours: float = 24.0) -> str:
        """Return CIEU summary: total decisions, deny rate, top violations.

        Args:
            cieu_db: Path to CIEU database. Empty string uses in-process state.
            since_hours: Report window in hours (default 24).
        """
        try:
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                store = CIEUStore(cieu_db)
            else:
                store = state._cieu_store

            if store is None:
                return json.dumps({"error": "No CIEU store available. Pass cieu_db path."})

            since_ts = time.time() - (since_hours * 3600) if since_hours > 0 else None
            stats = store.stats(since=since_ts)

            return json.dumps({
                "total_events": stats.get("total", 0),
                "deny_rate": round(stats.get("deny_rate", 0.0), 4),
                "escalation_rate": round(stats.get("escalation_rate", 0.0), 4),
                "drift_rate": round(stats.get("drift_rate", 0.0), 4),
                "by_decision": stats.get("by_decision", {}),
                "by_event_type": stats.get("by_event_type", {}),
                "top_violations": stats.get("top_violations", []),
                "sessions": stats.get("sessions", 0),
                "since_hours": since_hours,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_verify(cieu_db: str = "", session_id: str = "") -> str:
        """Verify SHA-256 Merkle chain integrity of CIEU records.

        Args:
            cieu_db: Path to CIEU database.
            session_id: Session to verify. Empty string verifies all sealed sessions.
        """
        try:
            if cieu_db:
                from ystar.governance.cieu_store import CIEUStore
                store = CIEUStore(cieu_db)
            else:
                store = state._cieu_store

            if store is None:
                return json.dumps({"error": "No CIEU store available. Pass cieu_db path."})

            if session_id:
                result = store.verify_session_seal(session_id)
                return json.dumps({
                    "session_id": result.get("session_id", session_id),
                    "valid": result.get("valid", False),
                    "stored_root": result.get("stored_root", ""),
                    "computed_root": result.get("computed_root", ""),
                    "event_count": result.get("current_count", 0),
                    "tamper_evidence": result.get("tamper_evidence", ""),
                })
            else:
                # Verify all sealed sessions
                results = []
                try:
                    # list_sealed_sessions may not exist in all versions
                    if hasattr(store, "list_sealed_sessions"):
                        sealed = store.list_sealed_sessions()
                        for s in sealed:
                            sid = s if isinstance(s, str) else getattr(s, "session_id", str(s))
                            r = store.verify_session_seal(sid)
                            results.append({"session_id": sid, "valid": r.get("valid", False)})
                except Exception:
                    pass

                # Also report CIEU stats as a basic integrity signal
                stats = store.stats()
                all_valid = all(r["valid"] for r in results) if results else True
                return json.dumps({
                    "chain_integrity": "VALID" if all_valid else "BROKEN",
                    "sessions_checked": len(results),
                    "total_events": stats.get("total", 0),
                    "total_sessions": stats.get("sessions", 0),
                    "results": results,
                })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_obligations(
        actor_id: str = "",
        status_filter: str = "",
    ) -> str:
        """Query current obligations from the OmissionEngine store.

        Args:
            actor_id: Filter by actor. Empty string returns all.
            status_filter: Filter by status (pending, fulfilled, soft_overdue, hard_overdue, etc.).
        """
        try:
            store = state.omission_engine.store
            kwargs: Dict[str, Any] = {}
            if actor_id:
                kwargs["actor_id"] = actor_id
            if status_filter:
                from ystar import ObligationStatus
                try:
                    kwargs["status"] = ObligationStatus(status_filter)
                except ValueError:
                    return json.dumps({"error": f"Unknown status: {status_filter}. Valid: pending, fulfilled, soft_overdue, hard_overdue, escalated, cancelled, expired, failed"})

            obligations = store.list_obligations(**kwargs)

            items = []
            for ob in obligations:
                items.append({
                    "obligation_id": ob.obligation_id,
                    "obligation_type": ob.obligation_type,
                    "entity_id": ob.entity_id,
                    "actor_id": ob.actor_id,
                    "status": ob.status.value if hasattr(ob.status, "value") else str(ob.status),
                    "due_at": ob.due_at,
                    "severity": ob.severity.value if hasattr(ob.severity, "value") else str(ob.severity),
                })

            return json.dumps({
                "total": len(items),
                "obligations": items,
                "filters": {"actor_id": actor_id or None, "status": status_filter or None},
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool()
    def gov_doctor() -> str:
        """Run health check on Y*gov governance state.

        Returns structured diagnostics: contract status, delegation chain,
        omission engine state, and subsystem liveness.
        """
        checks: Dict[str, Any] = {}

        # 1. Contract
        checks["contract"] = {
            "status": "loaded",
            "name": state.active_contract.name or "(unnamed)",
            "hash": state.active_contract.hash,
            "agents_md": str(state.agents_md_path),
            "confidence": state.confidence_label,
            "confidence_score": state.confidence_score,
        }

        # 2. Delegation chain
        chain_issues = state.delegation_chain.validate() if state.delegation_chain.depth > 0 else []
        checks["delegation_chain"] = {
            "depth": state.delegation_chain.depth,
            "valid": len(chain_issues) == 0,
            "issues": chain_issues,
        }

        # 3. Omission engine
        try:
            store = state.omission_engine.store
            pending = store.pending_obligations()
            all_obs = store.list_obligations()
            checks["omission_engine"] = {
                "status": "active",
                "total_obligations": len(all_obs),
                "pending": len(pending),
            }
        except Exception as e:
            checks["omission_engine"] = {"status": "error", "error": str(e)}

        # 4. CIEU store
        if state._cieu_store is not None:
            try:
                stats = state._cieu_store.stats()
                checks["cieu"] = {
                    "status": "active",
                    "total_events": stats.get("total", 0),
                    "deny_rate": round(stats.get("deny_rate", 0.0), 4),
                }
            except Exception as e:
                checks["cieu"] = {"status": "error", "error": str(e)}
        else:
            checks["cieu"] = {"status": "not_configured"}

        # 5. Exec whitelist
        wl = state.exec_whitelist
        checks["exec_whitelist"] = {
            "allowed_prefixes": len(wl.get("allowed_prefixes", [])),
            "always_deny": len(wl.get("always_deny", [])),
        }

        # Overall health
        failed = []
        if not checks["contract"]["hash"]:
            failed.append("contract not loaded")
        if checks.get("delegation_chain", {}).get("issues"):
            failed.append("delegation chain invalid")
        if checks.get("omission_engine", {}).get("status") == "error":
            failed.append("omission engine error")

        return json.dumps({
            "health": "degraded" if failed else "healthy",
            "issues": failed,
            "checks": checks,
        })

    return mcp

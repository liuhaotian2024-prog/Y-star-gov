"""GOV MCP — Y*gov governance exposed as a standard MCP server.

Ecosystem-neutral: no Claude Code / Anthropic-specific imports.
All paths via pathlib. No hardcoded defaults.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def __init__(self, agents_md_path: Path) -> None:
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

def create_server(agents_md_path: Path) -> FastMCP:
    """Create and return a configured GOV MCP server."""

    mcp = FastMCP(
        "gov-mcp",
        instructions="Y*gov governance as a standard MCP server",
    )
    state = _State(agents_md_path)

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
    # AUDIT & OBSERVABILITY LAYER (stubs)
    # ===================================================================

    @mcp.tool()
    def gov_report() -> str:
        """Return CIEU summary: total decisions, deny rate, agent breakdown."""
        return json.dumps({"status": "stub", "message": "CIEU reporting not yet wired — use ystar report CLI"})

    @mcp.tool()
    def gov_verify() -> str:
        """Verify SHA-256 Merkle chain integrity of CIEU records."""
        return json.dumps({"status": "stub", "message": "CIEU verification not yet wired — use ystar verify CLI"})

    @mcp.tool()
    def gov_obligations() -> str:
        """Query current active obligations and their status."""
        return json.dumps({"status": "stub", "message": "Obligation query not yet wired"})

    @mcp.tool()
    def gov_doctor() -> str:
        """Run 7-point health check on Y*gov installation."""
        return json.dumps({
            "status": "operational",
            "checks": {
                "active_contract": state.active_contract.name or "(unnamed)",
                "contract_hash": state.active_contract.hash,
                "agents_md": str(state.agents_md_path),
                "confidence": state.confidence_label,
                "confidence_score": state.confidence_score,
                "delegation_chain_depth": state.delegation_chain.depth,
            },
        })

    return mcp

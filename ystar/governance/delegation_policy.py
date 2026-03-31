# Layer: Foundation
"""
ystar.governance.delegation_policy — Delegation Chain Construction
==================================================================

Path A/B don't hand-assemble contracts. This module provides
policy-driven construction of handoff registration data and
validated delegation chains from compiled bundles.

Usage:
    from ystar.governance.delegation_policy import build_path_a_handoff

    handoff_data = build_path_a_handoff(constitution_bundle, path_a_policy)
    chain = build_delegation_chain(parent_bundle, child_bundle)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ystar.kernel.dimensions import IntentContract


@dataclass
class DelegationChainResult:
    """Result of building a delegation chain."""
    parent_contract: IntentContract
    child_contract: IntentContract
    parent_scope: List[str]
    child_scope: List[str]
    delegation_depth: int = 1
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)


def build_path_a_handoff(
    constitution_bundle,
    path_a_policy,
) -> dict:
    """
    Build handoff registration data from compiled bundles.

    Instead of Path A's _do_handoff_registration() assembling contracts inline,
    this function constructs the handoff data from the compiled constitution
    bundle and PathAPolicy.

    Args:
        constitution_bundle: CompiledContractBundle from ConstitutionProvider
        path_a_policy: PathAPolicy instance with safety constraints

    Returns:
        dict with parent_contract, child_contract, parent_scope, child_scope
    """
    # Parent contract: GovernanceLoop layer (top-level governance)
    parent_contract = IntentContract(
        name="governance_loop:meta_governance",
        deny=["/etc", "/root"],
        deny_commands=["rm -rf", "sudo"],
    )

    # Child contract: Path A (derived from constitution bundle + policy)
    child_deny = list(path_a_policy.default_forbidden_paths)
    child_deny_commands = list(path_a_policy.default_forbidden_commands)

    constitution_hash = ""
    if constitution_bundle is not None:
        constitution_hash = getattr(constitution_bundle, "source_hash", "")
        if constitution_hash:
            constitution_hash = f"sha256:{constitution_hash[:16]}"

    child_contract = IntentContract(
        name=f"path_a:agent:{constitution_hash}",
        deny=child_deny,
        deny_commands=child_deny_commands,
        hash=constitution_hash or "sha256:unavailable",
    )

    # Scope: child is STRICT SUBSET of parent
    parent_scope = [
        "module_graph.wire", "cieu.write",
        "obligation.create", "governance_loop.observe",
    ]
    child_scope = [
        "module_graph.wire", "cieu.write",
        "obligation.create",
    ]  # no governance_loop.observe

    return {
        "parent_contract": parent_contract,
        "child_contract": child_contract,
        "parent_scope": parent_scope,
        "child_scope": child_scope,
        "constitution_hash": constitution_hash,
    }


def build_delegation_chain(
    parent_bundle,
    child_bundle,
) -> DelegationChainResult:
    """
    Build a validated delegation chain from compiled bundles.

    Validates that the child's contract is a subset of the parent's
    (monotonicity constraint).

    Args:
        parent_bundle: CompiledContractBundle for the parent (e.g., GovernanceLoop)
        child_bundle:  CompiledContractBundle for the child (e.g., Path A)

    Returns:
        DelegationChainResult with validation status
    """
    parent_contract = parent_bundle.contract if parent_bundle else IntentContract()
    child_contract = child_bundle.contract if child_bundle else IntentContract()

    # Validate monotonicity: child deny must be superset of parent deny
    validation_errors: List[str] = []

    parent_deny = set(parent_contract.deny or [])
    child_deny = set(child_contract.deny or [])
    if not parent_deny.issubset(child_deny):
        missing = parent_deny - child_deny
        validation_errors.append(
            f"Child deny is not a superset of parent deny. Missing: {missing}"
        )

    parent_deny_cmds = set(parent_contract.deny_commands or [])
    child_deny_cmds = set(child_contract.deny_commands or [])
    if not parent_deny_cmds.issubset(child_deny_cmds):
        missing = parent_deny_cmds - child_deny_cmds
        validation_errors.append(
            f"Child deny_commands not superset of parent. Missing: {missing}"
        )

    parent_scope = [
        "module_graph.wire", "cieu.write",
        "obligation.create", "governance_loop.observe",
    ]
    child_scope = [
        "module_graph.wire", "cieu.write",
        "obligation.create",
    ]

    return DelegationChainResult(
        parent_contract=parent_contract,
        child_contract=child_contract,
        parent_scope=parent_scope,
        child_scope=child_scope,
        is_valid=len(validation_errors) == 0,
        validation_errors=validation_errors,
    )

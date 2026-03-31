# Layer: Foundation
"""
ystar.kernel.scope_encoding — Scope Constraint Encoding/Decoding
================================================================

Scope constraint encoding/decoding for module, external, and domain scopes.

Centralizes the encoding of scope constraints that were previously
done inline with f-strings. This ensures consistent encoding across
Path A, Path B, and the kernel.

Encoding scheme:
    module:mod_id          — module scope constraint
    external:agent_id      — external agent scope
    external_domain:domain — external domain scope
"""
from __future__ import annotations

from typing import List


def encode_module_scope(module_ids: List[str]) -> List[str]:
    """Encode module IDs into scope constraint strings.

    >>> encode_module_scope(["causal_engine", "omission_engine"])
    ['module:causal_engine', 'module:omission_engine']
    """
    return [f"module:{mid}" for mid in module_ids]


def decode_module_scope(only_paths: List[str]) -> List[str]:
    """Decode module scope constraints back to module IDs.

    >>> decode_module_scope(["module:causal_engine", "/etc"])
    ['causal_engine']
    """
    return [p[7:] for p in only_paths if p.startswith("module:")]


def encode_external_scope(agent_id: str) -> str:
    """Encode an external agent ID into a scope constraint string.

    >>> encode_external_scope("agent_42")
    'external:agent_42'
    """
    return f"external:{agent_id}"


def encode_external_domain(domain: str) -> str:
    """Encode an external domain into a scope constraint string.

    >>> encode_external_domain("finance")
    'external_domain:finance'
    """
    return f"external_domain:{domain}"

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


# ── Prefixes (single source of truth) ─────────────────────────────────
MODULE_PREFIX = "module:"
EXTERNAL_PREFIX = "external:"
EXTERNAL_DOMAIN_PREFIX = "external_domain:"

_ALL_PREFIXES = (MODULE_PREFIX, EXTERNAL_PREFIX, EXTERNAL_DOMAIN_PREFIX)


def decode_external_scope(only_paths: List[str]) -> List[str]:
    """Decode external scope constraints back to agent IDs.

    >>> decode_external_scope(["external:agent_42", "module:x"])
    ['agent_42']
    """
    n = len(EXTERNAL_PREFIX)
    return [
        p[n:] for p in only_paths
        if p.startswith(EXTERNAL_PREFIX) and not p.startswith(EXTERNAL_DOMAIN_PREFIX)
    ]


def decode_external_domain(only_paths: List[str]) -> List[str]:
    """Decode external domain constraints back to domain names.

    >>> decode_external_domain(["external_domain:finance", "module:x"])
    ['finance']
    """
    n = len(EXTERNAL_DOMAIN_PREFIX)
    return [p[n:] for p in only_paths if p.startswith(EXTERNAL_DOMAIN_PREFIX)]


def classify_scope(scope_str: str) -> str:
    """Return the scope type of a constraint string.

    >>> classify_scope("module:causal_engine")
    'module'
    >>> classify_scope("external:agent_42")
    'external'
    >>> classify_scope("external_domain:finance")
    'external_domain'
    >>> classify_scope("/etc/hosts")
    'path'
    """
    if scope_str.startswith(EXTERNAL_DOMAIN_PREFIX):
        return "external_domain"
    if scope_str.startswith(EXTERNAL_PREFIX):
        return "external"
    if scope_str.startswith(MODULE_PREFIX):
        return "module"
    return "path"


def split_scopes(only_paths: List[str]):
    """Split a mixed only_paths list into typed buckets.

    Returns (module_ids, external_ids, domain_names, filesystem_paths).

    >>> split_scopes(["module:x", "external:a", "external_domain:d", "/tmp"])
    (['x'], ['a'], ['d'], ['/tmp'])
    """
    modules = decode_module_scope(only_paths)
    externals = decode_external_scope(only_paths)
    domains = decode_external_domain(only_paths)
    paths = [p for p in only_paths if classify_scope(p) == "path"]
    return modules, externals, domains, paths


def validate_scope(scope_str: str) -> bool:
    """Check whether a scope constraint string is well-formed.

    >>> validate_scope("module:causal_engine")
    True
    >>> validate_scope("module:")
    False
    >>> validate_scope("")
    False
    """
    if not scope_str:
        return False
    scope_type = classify_scope(scope_str)
    if scope_type == "path":
        return len(scope_str) > 0
    # For typed scopes, the value after the prefix must be non-empty
    prefix_map = {
        "module": MODULE_PREFIX,
        "external": EXTERNAL_PREFIX,
        "external_domain": EXTERNAL_DOMAIN_PREFIX,
    }
    prefix = prefix_map[scope_type]
    return len(scope_str) > len(prefix)

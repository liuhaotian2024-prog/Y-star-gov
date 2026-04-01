# Layer: Intent Compilation
"""
ystar.kernel.contract_provider — Constitution Bundle Provider
=============================================================

The ONLY way Path A/B get their constitution.

Instead of reading files directly and computing hashes inline,
all constitution access goes through ConstitutionProvider.resolve().

This centralizes:
  - File I/O and hash computation
  - Caching (avoid re-reading on every cycle)
  - Cache invalidation (after amendment)
  - Compilation via the unified compiler
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ystar.kernel.compiler import CompiledContractBundle, compile_constitution


class ConstitutionProvider:
    """
    Constitution bundle provider — the ONLY way Path A/B get their constitution.

    Usage:
        provider = ConstitutionProvider()
        bundle = provider.resolve("ystar/path_a/PATH_A_AGENTS.md")
        print(bundle.source_hash)

        # After amendment:
        provider.invalidate_cache("ystar/path_a/PATH_A_AGENTS.md")
        bundle = provider.resolve("ystar/path_a/PATH_A_AGENTS.md")  # re-reads
    """

    def __init__(self, compiler=None) -> None:
        self._cache: Dict[str, CompiledContractBundle] = {}
        self._compiler = compiler  # reserved for future custom compiler injection
        self._version_counter: Dict[str, int] = {}
        self._hash_history: Dict[str, List[str]] = {}

    def resolve(self, source_ref: str) -> CompiledContractBundle:
        """
        Resolve a constitution by reference (file path or identifier).

        Returns cached bundle if available, otherwise compiles fresh.
        """
        if source_ref in self._cache:
            return self._cache[source_ref]

        bundle = compile_constitution(source_ref)
        # Track version and hash history
        prev_hash = self._hash_history.get(source_ref, [""])[-1] if source_ref in self._hash_history else ""
        self._version_counter[source_ref] = self._version_counter.get(source_ref, 0) + 1
        bundle.version = self._version_counter[source_ref]
        bundle.previous_hash = prev_hash
        self._hash_history.setdefault(source_ref, []).append(bundle.source_hash)

        self._cache[source_ref] = bundle
        return bundle

    def resolve_latest(self, source_ref: str) -> CompiledContractBundle:
        """
        Force re-read and return the latest constitution, bypassing cache.
        """
        self._cache.pop(source_ref, None)
        return self.resolve(source_ref)

    def get_hash(self, source_ref: str) -> str:
        """
        Get current constitution hash.

        Returns the SHA-256 hash of the constitution file,
        or empty string if the file is not available.
        """
        bundle = self.resolve(source_ref)
        return bundle.source_hash

    def verify_hash(self, source_ref: str, expected_hash: str) -> bool:
        """
        Verify that the current constitution hash matches an expected value.

        Useful for detecting tampering or drift between cached and on-disk state.
        """
        current = self.get_hash(source_ref)
        return current != "" and current == expected_hash

    def get_version(self, source_ref: str) -> int:
        """Return the current version number for a constitution reference."""
        return self._version_counter.get(source_ref, 0)

    def resolve_by_hash(self, expected_hash: str) -> Optional[CompiledContractBundle]:
        """
        Find a cached bundle whose source_hash matches expected_hash.

        Searches all cached constitutions. Returns None if no match found.
        Useful for auditing: given a hash, retrieve the constitution that produced it.
        """
        for bundle in self._cache.values():
            if bundle.source_hash == expected_hash:
                return bundle
        return None

    def invalidate_cache(self, source_ref: Optional[str] = None) -> None:
        """
        Invalidate cached constitution (after amendment).

        Args:
            source_ref: specific file to invalidate.
                        If None, invalidates ALL cached constitutions.
        """
        if source_ref is None:
            self._cache.clear()
        else:
            self._cache.pop(source_ref, None)

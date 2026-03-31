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

from typing import Dict, Optional

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

    def resolve(self, source_ref: str) -> CompiledContractBundle:
        """
        Resolve a constitution by reference (file path or identifier).

        Returns cached bundle if available, otherwise compiles fresh.
        """
        if source_ref in self._cache:
            return self._cache[source_ref]

        bundle = compile_constitution(source_ref)
        self._cache[source_ref] = bundle
        return bundle

    def get_hash(self, source_ref: str) -> str:
        """
        Get current constitution hash.

        Returns the SHA-256 hash of the constitution file,
        or empty string if the file is not available.
        """
        bundle = self.resolve(source_ref)
        return bundle.source_hash

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

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
  - Amendment audit chain tracking
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from ystar.kernel.compiler import CompiledContractBundle, compile_constitution
from ystar.governance.amendment import AmendmentLog, AmendmentRecord


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

    def __init__(self, compiler=None, amendment_log: Optional[AmendmentLog] = None) -> None:
        self._cache: Dict[str, CompiledContractBundle] = {}
        self._compiler = compiler  # reserved for future custom compiler injection
        self._version_counter: Dict[str, int] = {}
        self._hash_history: Dict[str, List[str]] = {}
        self._amendment_log = amendment_log or AmendmentLog()
        self._amendment_counter = 0  # for generating unique amendment IDs

    def resolve(self, source_ref: str) -> CompiledContractBundle:
        """
        Resolve a constitution by reference (file path or identifier).

        Returns cached bundle if available, otherwise compiles fresh.
        Verifies source hash against history on subsequent loads.
        """
        if source_ref in self._cache:
            return self._cache[source_ref]

        bundle = compile_constitution(source_ref)
        # Track version and hash history
        prev_hash = self._hash_history.get(source_ref, [""])[-1] if source_ref in self._hash_history else ""
        self._version_counter[source_ref] = self._version_counter.get(source_ref, 0) + 1
        bundle.version = self._version_counter[source_ref]
        bundle.previous_hash = prev_hash

        # Verify hash if we have history (Task #4: Source Legitimacy Check)
        # Compare directly instead of calling verify_hash() to avoid recursion
        if prev_hash and prev_hash != "" and prev_hash != bundle.source_hash:
            import logging
            logging.warning(
                f"Source legitimacy warning: constitution '{source_ref}' "
                f"hash changed from {prev_hash[:12]}... to {bundle.source_hash[:12]}... "
                f"— possible tampering or unrecorded amendment"
            )

            # Create amendment record when hash changes
            self._amendment_counter += 1
            amendment_record = AmendmentRecord(
                amendment_id=f"amend_{self._amendment_counter}_{int(time.time())}",
                timestamp=time.time(),
                author_agent_id="system",  # default, should be overridden by caller
                source_ref=source_ref,
                old_hash=prev_hash,
                new_hash=bundle.source_hash,
                change_description=f"Hash changed from {prev_hash[:12]}... to {bundle.source_hash[:12]}..."
            )
            self._amendment_log.append(amendment_record)

        self._hash_history.setdefault(source_ref, []).append(bundle.source_hash)

        self._cache[source_ref] = bundle
        return bundle

    def resolve_latest(self, source_ref: str) -> CompiledContractBundle:
        """
        Force re-read and return the latest constitution, bypassing cache.
        Verifies source hash against history.
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

    def resolve_for_agent(
        self,
        agent_id: str,
        delegation_chain=None,
        fallback_source_ref: Optional[str] = None,
    ) -> CompiledContractBundle:
        """
        Resolve constitution for a specific agent, optionally using delegation chain routing.

        This method enables per-agent constitution routing in multi-agent systems:
        - If delegation_chain is provided, finds the agent's link and extracts its constitution source_ref
        - If the agent is not in the chain or no chain provided, falls back to fallback_source_ref
        - If no fallback provided, raises ValueError

        Args:
            agent_id: The agent identifier (e.g., "agent_a", "ceo", "cto")
            delegation_chain: Optional DelegationChain containing agent-specific constitutions
            fallback_source_ref: Default constitution path if agent not found in chain

        Returns:
            CompiledContractBundle for the resolved constitution

        Raises:
            ValueError: If agent not found in chain and no fallback provided

        Example:
            provider = ConstitutionProvider()
            chain = DelegationChain()
            chain.append(make_link("org", "ceo", contract, constitution_source="ceo/CONSTITUTION.md"))
            bundle = provider.resolve_for_agent("ceo", delegation_chain=chain)
        """
        source_ref = None

        # Try to find agent in delegation chain
        if delegation_chain is not None:
            for link in delegation_chain.links:
                # Check if this link's actor matches the agent_id
                if link.actor == agent_id:
                    # Try to extract constitution_source_ref from the link
                    # DelegationContract may have a constitution_source_ref attribute
                    ref = getattr(link, "constitution_source_ref", "")
                    # Only use if non-empty
                    if ref and ref.strip():
                        source_ref = ref
                        break

                # Also check if agent is the principal (could be delegating)
                if link.principal == agent_id:
                    ref = getattr(link, "constitution_source_ref", "")
                    if ref and ref.strip():
                        source_ref = ref
                        break

        # Fallback if not found in chain
        if source_ref is None or not source_ref.strip():
            if fallback_source_ref is not None:
                source_ref = fallback_source_ref
            else:
                raise ValueError(
                    f"Agent '{agent_id}' not found in delegation chain and no fallback provided"
                )

        # Use existing resolve() to get the bundle
        return self.resolve(source_ref)

    def invalidate_cache(
        self,
        source_ref: Optional[str] = None,
        author_agent_id: str = "system",
        change_description: str = ""
    ) -> None:
        """
        Invalidate cached constitution (after amendment).

        When source_ref is specified and we have a cached bundle with a different
        hash, creates an AmendmentRecord automatically on next resolve().

        Args:
            source_ref: specific file to invalidate.
                        If None, invalidates ALL cached constitutions.
            author_agent_id: agent who triggered the invalidation (for audit)
            change_description: human-readable description of the change
        """
        if source_ref is None:
            self._cache.clear()
        else:
            self._cache.pop(source_ref, None)

    def get_amendment_history(self, source_ref: str) -> List[AmendmentRecord]:
        """Get chronological amendment history for a specific constitution."""
        return self._amendment_log.history(source_ref)

    def get_all_amendments(self) -> List[AmendmentRecord]:
        """Get all amendment records across all constitutions."""
        return self._amendment_log.all_records()

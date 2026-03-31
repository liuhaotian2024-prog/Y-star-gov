# Layer: Intent Compilation
"""
ystar.kernel.compiler — Unified Contract Compilation Entry Point
================================================================

All contract creation in Y*gov goes through this module.
nl_to_contract.py is a provider implementation, not the direct entry.

Pipeline:
    source_text / file_path
        → compile_source() / compile_constitution()
        → CompiledContractBundle
            .contract       IntentContract
            .source_hash    SHA-256 of source document
            .source_ref     path or identifier of source
            .version        monotonically increasing
            .confidence     0-1, how confident the translation is
            .diagnostics    optional metadata from the compilation
            .compile_method "llm", "regex", "manual", "policy"
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ystar.kernel.dimensions import IntentContract


@dataclass
class CompiledContractBundle:
    """Result of compiling a source document into an IntentContract."""
    contract: IntentContract
    source_hash: str          # SHA-256 of source document
    source_ref: str           # path or identifier of source
    version: int = 1
    confidence: float = 1.0
    diagnostics: Optional[dict] = None
    compile_method: str = ""  # "llm", "regex", "manual", "policy"

    def is_valid(self) -> bool:
        """Check if compilation produced a usable contract."""
        return self.contract is not None and self.source_hash != ""


def _compute_hash(text: str) -> str:
    """Compute SHA-256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compile_source(
    source_text: str,
    source_ref: str = "",
    api_call_fn: Optional[Callable] = None,
) -> CompiledContractBundle:
    """
    Compile natural language rules into a contract bundle.

    Uses nl_to_contract internally when an LLM is available,
    falls back to prefill (regex-based) otherwise.

    Args:
        source_text: natural language rules to compile
        source_ref:  path or identifier of the source document
        api_call_fn: optional LLM API call function

    Returns:
        CompiledContractBundle with the compiled contract
    """
    source_hash = _compute_hash(source_text)
    diagnostics: Dict[str, Any] = {}
    compile_method = "regex"
    confidence = 0.5

    # Try LLM-based translation first
    contract = None
    try:
        from ystar.kernel.nl_to_contract import translate_nl
        result = translate_nl(source_text, api_call_fn=api_call_fn)
        if result is not None:
            contract = result
            compile_method = "llm"
            confidence = 0.85
            diagnostics["llm_used"] = True
    except Exception as e:
        diagnostics["llm_error"] = str(e)

    # Fall back to regex-based prefill
    if contract is None:
        try:
            from ystar.kernel.prefill import prefill
            prefill_result = prefill(policy_text=source_text)
            contract = prefill_result.contract
            compile_method = "regex"
            confidence = 0.5
            diagnostics["prefill_warnings"] = prefill_result.warnings
        except Exception as e:
            diagnostics["prefill_error"] = str(e)

    # Last resort: empty contract
    if contract is None:
        contract = IntentContract(name=f"compiled:{source_ref or 'unknown'}")
        compile_method = "manual"
        confidence = 0.1
        diagnostics["fallback"] = "empty_contract"

    return CompiledContractBundle(
        contract=contract,
        source_hash=source_hash,
        source_ref=source_ref,
        confidence=confidence,
        diagnostics=diagnostics,
        compile_method=compile_method,
    )


def compile_constitution(file_path: str) -> CompiledContractBundle:
    """
    Compile a constitution file (AGENTS.md, PATH_A_AGENTS.md, etc.).

    Reads the file, computes its hash, and compiles the content
    into a CompiledContractBundle.

    Args:
        file_path: path to the constitution file

    Returns:
        CompiledContractBundle with source_ref set to file_path
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, IOError) as e:
        # File unreadable — return a bundle with empty contract
        return CompiledContractBundle(
            contract=IntentContract(name=f"constitution:{file_path}"),
            source_hash="",
            source_ref=file_path,
            confidence=0.0,
            diagnostics={"file_error": str(e)},
            compile_method="manual",
        )

    bundle = compile_source(content, source_ref=file_path)
    # Override source_hash with binary hash for constitution integrity
    try:
        with open(file_path, "rb") as f:
            bundle.source_hash = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        pass

    return bundle

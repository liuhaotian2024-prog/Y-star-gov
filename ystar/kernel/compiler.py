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
import time
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
    source_type: str = ""     # "constitution", "policy", "nl", "manual"
    compiled_at: float = 0.0  # epoch timestamp of compilation
    previous_hash: str = ""   # hash of the previous version (audit trail)
    amendment_version: int = 0  # which amendment produced this bundle (0 = original)

    def __post_init__(self):
        if self.compiled_at == 0.0:
            self.compiled_at = time.time()

    def is_valid(self) -> bool:
        """Check if compilation produced a usable contract."""
        return self.contract is not None and self.source_hash != ""


def _compute_hash(text: str) -> str:
    """Compute SHA-256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _try_structured_parse(text: str) -> Optional[Dict]:
    """
    Try to parse structured YAML/markdown constitution format.

    Looks for patterns like:
        ## Intent Contracts
        - function: func_name
          deny: ["/path", "keyword"]
          only_paths: ["/allowed"]

    Returns contract_dict if successful, None otherwise.
    """
    import re

    # Look for "## Intent Contracts" section
    intent_section_match = re.search(
        r'##\s+Intent\s+Contracts?\s*\n(.*?)(?=\n##|\Z)',
        text,
        re.DOTALL | re.IGNORECASE
    )

    if not intent_section_match:
        return None

    section = intent_section_match.group(1)

    # Try to extract YAML-like list items
    contract_dict: Dict[str, Any] = {}

    # Extract deny list
    deny_match = re.search(r'deny:\s*\[(.*?)\]', section, re.DOTALL)
    if deny_match:
        deny_items = [
            item.strip().strip('"\'')
            for item in deny_match.group(1).split(',')
            if item.strip()
        ]
        contract_dict['deny'] = deny_items

    # Extract only_paths list
    only_paths_match = re.search(r'only_paths:\s*\[(.*?)\]', section, re.DOTALL)
    if only_paths_match:
        paths = [
            item.strip().strip('"\'')
            for item in only_paths_match.group(1).split(',')
            if item.strip()
        ]
        contract_dict['only_paths'] = paths

    # Extract deny_commands list
    deny_commands_match = re.search(r'deny_commands:\s*\[(.*?)\]', section, re.DOTALL)
    if deny_commands_match:
        cmds = [
            item.strip().strip('"\'')
            for item in deny_commands_match.group(1).split(',')
            if item.strip()
        ]
        contract_dict['deny_commands'] = cmds

    # Extract only_domains list
    only_domains_match = re.search(r'only_domains:\s*\[(.*?)\]', section, re.DOTALL)
    if only_domains_match:
        domains = [
            item.strip().strip('"\'')
            for item in only_domains_match.group(1).split(',')
            if item.strip()
        ]
        contract_dict['only_domains'] = domains

    # Extract invariant list
    invariant_match = re.search(r'invariant:\s*\[(.*?)\]', section, re.DOTALL)
    if invariant_match:
        invs = [
            item.strip().strip('"\'')
            for item in invariant_match.group(1).split(',')
            if item.strip()
        ]
        contract_dict['invariant'] = invs

    return contract_dict if contract_dict else None


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
        from ystar.kernel.nl_to_contract import translate_to_contract
        contract_dict, method, conf = translate_to_contract(source_text, api_call_fn=api_call_fn)
        if contract_dict:
            contract = IntentContract(**contract_dict)
            compile_method = method
            confidence = conf
            diagnostics["translation_used"] = True
    except Exception as e:
        diagnostics["llm_error"] = str(e)

    # Try structured YAML/markdown parsing (for test constitutions and structured docs)
    if contract is None:
        try:
            contract_dict = _try_structured_parse(source_text)
            if contract_dict:
                contract = IntentContract(**contract_dict)
                compile_method = "structured"
                confidence = 0.7
                diagnostics["structured_parse"] = True
        except Exception as e:
            diagnostics["structured_error"] = str(e)

    # Fall back to regex-based extraction if structured parsing failed
    if contract is None:
        try:
            from ystar.kernel.nl_to_contract import _try_regex_translation
            contract_dict = _try_regex_translation(source_text)
            if contract_dict:
                contract = IntentContract(**contract_dict)
                compile_method = "regex"
                confidence = 0.5
                diagnostics["regex_fallback"] = True
        except Exception as e:
            diagnostics["regex_error"] = str(e)

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
        source_type="nl",
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
    bundle.source_type = "constitution"
    # Override source_hash with binary hash for constitution integrity
    try:
        with open(file_path, "rb") as f:
            bundle.source_hash = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        pass

    return bundle

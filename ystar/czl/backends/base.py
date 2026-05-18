"""
ystar.czl.backends.base — multi-provider LLM backend abstraction

This is the arbitrage layer. ONE interface, MANY providers:

  - DeepSeek    (cheap; main commercial arm C target)
  - MiniMax     (cheap; alternative arm C)
  - Qwen        (cheap)
  - Kimi        (cheap, long context)
  - Ollama      (local; zero-cost arm B)
  - Anthropic   (expensive; arm A baseline)
  - OpenAI      (expensive; alternative arm A)
  - <third-party via entry_points>

Built on LiteLLM (`pip install litellm`) — it normalizes ~100 providers behind
a single `completion()` call. We do NOT roll our own HTTP clients for each
provider. That would violate the don't-reinvent rule.

LiteLLM also gives us:
  - Per-provider rate-limit handling
  - Cost tracking (token counts + estimated USD)
  - Retry-with-backoff (HTTP 529 from Anthropic, etc.)
  - Streaming
  - Structured output (function-calling normalized)

If a user wants to add a provider LiteLLM doesn't support, they implement
the Backend ABC directly and register via entry_points.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_log = logging.getLogger("ystar.czl.backends")


@dataclass
class BackendAction:
    """One proposed action emitted by the backend (e.g. one tool call)."""
    type: str                                 # "edit_file" | "run_command" | "create_file" | ...
    payload: Dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, k: str) -> Any:
        if k == "type":
            return self.type
        return self.payload.get(k, "")

    def get(self, k: str, default: Any = "") -> Any:
        if k == "type":
            return self.type
        return self.payload.get(k, default)


@dataclass
class BackendResponse:
    """One round-trip result from a backend invocation."""
    actions: List[BackendAction] = field(default_factory=list)
    raw_text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    provider_metadata: Dict[str, Any] = field(default_factory=dict)


class Backend(ABC):
    """
    Abstract LLM backend. Subclasses wrap one provider (or a LiteLLM router).
    """

    # === class metadata (override) ==========================================
    name: str = ""              # "deepseek" | "minimax" | "ollama" | ...
    tier: str = "cheap"         # "cheap" | "frontier" | "local"
    default_model: str = ""

    # === core interface =====================================================
    @abstractmethod
    def invoke(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        workspace_dir: str,
        contract: Dict[str, Any],
    ) -> BackendResponse:
        """
        Send one completion request. Parse the response into structured
        BackendAction list. Return token counts and cost.

        Implementations should:
          - Use LiteLLM's `completion()` for actual HTTP
          - Use the provider's preferred edit format (some prefer JSON
            tool-calling; smaller models prefer Aider-style "whole file" diffs)
          - Honor the contract — e.g. include the `deny` list in the system
            prompt as a soft hint, even though boundary_enforcer enforces it
            again at the action layer (defense in depth)
        """
        ...

    # === optional helpers ===================================================
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Compute USD cost from per-million-token rates declared in
        subclasses. Default 0 (override in concrete classes)."""
        return 0.0

    def is_available(self) -> bool:
        """Quick health check — e.g. is the API key set? Is Ollama up?
        Default True; override for network/auth checks."""
        return True

    def __repr__(self) -> str:
        return f"<Backend {self.name} tier={self.tier}>"


# === registry ================================================================

class BackendRegistry:
    """Class-level registry, mirroring ScenarioRegistry."""
    _registry: Dict[str, Backend] = {}
    _entry_points_loaded: bool = False

    @classmethod
    def register(cls, backend: Backend) -> None:
        if not backend.name:
            raise ValueError(f"Backend {backend!r} must define `name`")
        if backend.name in cls._registry:
            _log.warning("Overwriting existing backend '%s'", backend.name)
        cls._registry[backend.name] = backend

    @classmethod
    def get(cls, name: str) -> Backend:
        cls._lazy_load_entry_points()
        if name not in cls._registry:
            raise KeyError(
                f"No backend named '{name}'. Available: {sorted(cls._registry.keys())}"
            )
        return cls._registry[name]

    @classmethod
    def list(cls) -> List[str]:
        cls._lazy_load_entry_points()
        return sorted(cls._registry.keys())

    @classmethod
    def auto_select(cls) -> Backend:
        """
        Probe environment for the cheapest available backend, in this order:
            1. Local Ollama (if reachable and has a coder model)
            2. DeepSeek (if DEEPSEEK_API_KEY set)
            3. MiniMax (if MINIMAX_API_KEY set)
            4. Qwen (if DASHSCOPE_API_KEY or QWEN_API_KEY set)
            5. Kimi (if MOONSHOT_API_KEY set)
            6. Anthropic (last resort — defeats arbitrage)
            7. OpenAI (last resort)

        See docs/CZL_PRODUCT_DESIGN.md §6.4.
        """
        cls._lazy_load_entry_points()
        ordered_names = ["ollama", "deepseek", "minimax", "qwen", "kimi", "anthropic", "openai"]
        for n in ordered_names:
            if n in cls._registry:
                be = cls._registry[n]
                if be.is_available():
                    _log.info("Auto-selected backend: %s", n)
                    return be
        raise RuntimeError(
            "No backend available. Set one of DEEPSEEK_API_KEY / MINIMAX_API_KEY / "
            "DASHSCOPE_API_KEY / MOONSHOT_API_KEY / OLLAMA_HOST / ANTHROPIC_API_KEY / "
            "OPENAI_API_KEY in your environment."
        )

    @classmethod
    def _lazy_load_entry_points(cls) -> None:
        if cls._entry_points_loaded:
            return
        cls._entry_points_loaded = True
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="ystar.czl.backends")
            for ep in eps:
                try:
                    be_cls = ep.load()
                    instance = be_cls() if isinstance(be_cls, type) else be_cls
                    cls.register(instance)
                except Exception as e:
                    _log.warning("Failed to load third-party backend %s: %s", ep.name, e)
        except Exception:
            pass


# === built-in LiteLLM-based concrete class ===================================
# Most providers can use this single implementation, varying only by `model`
# string. Specific providers that need custom edit-format handling
# (e.g. Ollama small models that prefer whole-file mode) subclass and override.

class LiteLLMBackend(Backend):
    """
    Generic backend powered by LiteLLM. Concrete subclasses set:
        name, tier, default_model, env_var_for_key, input_price_per_M,
        output_price_per_M
    """
    env_var_for_key: str = ""           # e.g. "DEEPSEEK_API_KEY"
    input_price_per_M: float = 0.0
    output_price_per_M: float = 0.0
    litellm_model_prefix: str = ""      # e.g. "deepseek/" or "openai/" or "ollama/"
    # Custom api_base for OpenAI-compatible providers that don't have a
    # dedicated LiteLLM connector (e.g. MiniMax via api.minimaxi.chat).
    # When set, the env_var_for_key value is passed explicitly as api_key
    # since the openai/ connector would otherwise look for OPENAI_API_KEY.
    api_base: Optional[str] = None
    # Newer Claude (Opus 4.7+) deprecates `temperature`. Backends targeting
    # such models should set this False so the loop omits temperature
    # rather than 400'ing.
    supports_temperature: bool = True

    def __init__(self, model: Optional[str] = None):
        self.model = model or self.default_model
        self.full_model_id = f"{self.litellm_model_prefix}{self.model}"

    def is_available(self) -> bool:
        if not self.env_var_for_key:
            return True   # local or no-key backends
        return bool(os.environ.get(self.env_var_for_key))

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self.input_price_per_M
            + output_tokens / 1_000_000 * self.output_price_per_M
        )

    def invoke(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        workspace_dir: str,
        contract: Dict[str, Any],
    ) -> BackendResponse:
        try:
            import litellm
        except ImportError as e:
            raise RuntimeError(
                "ystar-czl backends require litellm. Install via `pip install litellm`."
            ) from e

        # Compose messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Call LiteLLM (which handles auth, retry, rate-limit per provider).
        # temperature=0 is deliberate for backends that accept it: small
        # models drift toward "creative rewrites" at higher temperatures,
        # which destroys convergence under external verification. Newer
        # frontier models (Claude Opus 4.7+) deprecate temperature entirely,
        # so we omit it when supports_temperature is False.
        kwargs: Dict[str, Any] = {
            "model": self.full_model_id,
            "messages": messages,
        }
        if self.supports_temperature:
            kwargs["temperature"] = 0.0
        if self.api_base:
            kwargs["api_base"] = self.api_base
            if self.env_var_for_key:
                key_val = os.environ.get(self.env_var_for_key)
                if key_val:
                    kwargs["api_key"] = key_val
        response = litellm.completion(**kwargs)

        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        in_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        out_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return BackendResponse(
            actions=_parse_actions_from_text(text),
            raw_text=text,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=self.estimate_cost(in_tokens, out_tokens),
            provider_metadata={"model_id": self.full_model_id},
        )


# === simple text-format action parser ========================================
# Smaller models work better with text-block format than JSON tool-calling.
# This parses Aider-style markdown blocks like:
#
#   ```edit src/foo.py
#   <new file content>
#   ```
#
# or:
#
#   ```run
#   pytest tests/test_foo.py
#   ```

import re

_EDIT_BLOCK_RE = re.compile(
    r"```(?P<kind>edit|create|run|delete|add_tests|append)\s+(?P<path>[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)
_RUN_BLOCK_RE = re.compile(r"```run\n(?P<body>.*?)```", re.DOTALL)
# v4.0 T3: probe blocks. No path — the command IS the body. Distinct from
# `run` because `run` is the legacy single-command-no-path action; probe
# semantically requests a READ-ONLY observation that does NOT modify
# workspace state (loop captures stdout/stderr and feeds to next iter).
_PROBE_BLOCK_RE = re.compile(r"```probe\n(?P<body>.*?)```", re.DOTALL)
# v5.0.4: gemma 4B's natural markdown style is ```python (no path) for test
# code, not ```add_tests test_data_pipeline.py. v5.0.3 sanity showed gemma
# derailed at iter 2 by switching to ```python format and emitting 0 actions
# for 50 iters. Accept ```python as a SOFT-TYPED add_tests action — emits
# action type "python_block" with NO path; the scenario decides its default
# target test file. Containing scenario-specific knowledge in the scenario,
# not the parser.
_PYTHON_BLOCK_RE = re.compile(r"```python\s*\n(?P<body>.*?)```", re.DOTALL)


def _parse_actions_from_text(text: str) -> List[BackendAction]:
    actions: List[BackendAction] = []

    # First pass: edit/create/delete/add_tests/append with explicit path
    for m in _EDIT_BLOCK_RE.finditer(text):
        kind = m.group("kind")
        if kind == "run":
            continue  # handled below
        # v3.4 T1: both `add_tests` and `append` normalize to the add_tests_file
        # action type, dispatched to scenario.apply_action's merge-by-name path.
        action_type = "add_tests_file" if kind in ("add_tests", "append") else f"{kind}_file"
        actions.append(BackendAction(
            type=action_type,
            payload={
                "path": m.group("path").strip(),
                "content": m.group("body"),
            },
        ))

    # Second pass: bare run blocks (no path)
    for m in _RUN_BLOCK_RE.finditer(text):
        actions.append(BackendAction(
            type="run_command",
            payload={"command": m.group("body").strip()},
        ))

    # v4.0 T3: probe blocks (no path, read-only observation)
    for m in _PROBE_BLOCK_RE.finditer(text):
        actions.append(BackendAction(
            type="probe_command",
            payload={"command": m.group("body").strip()},
        ))

    # v5.0.4: bare ```python blocks → "python_block" action (scenario decides target).
    # Only emit when no ```add_tests / ```edit block with python content was
    # already extracted from the same text (avoid double-applying the same
    # body that's nested inside an add_tests wrapper).
    if not any(a.type in ("add_tests_file", "edit_file") for a in actions):
        for m in _PYTHON_BLOCK_RE.finditer(text):
            body = m.group("body")
            # Only treat as test code if body contains `def test_` — else it's
            # probably a description / docstring snippet.
            if "def test_" in body:
                actions.append(BackendAction(
                    type="python_block",
                    payload={"content": body},
                ))

    return actions

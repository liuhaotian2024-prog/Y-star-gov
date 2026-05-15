"""
ystar.czl.backends — concrete LLM provider registrations

Each provider here is a one-paragraph subclass of LiteLLMBackend. Prices
sourced from each provider's pricing page as of 2026-05.

ARM ROLES:
  - frontier (arm A baseline):  anthropic, openai
  - cheap (arm C primary):      deepseek, minimax, qwen, kimi
  - local (arm B):              ollama
"""
from __future__ import annotations

import os
from typing import Any, Dict

from ystar.czl.backends.base import (
    Backend,
    BackendRegistry,
    BackendResponse,
    LiteLLMBackend,
    _parse_actions_from_text,
)


# === ARM A: frontier (baseline only — never the production target) ==========

class AnthropicBackend(LiteLLMBackend):
    name = "anthropic"
    tier = "frontier"
    default_model = "claude-opus-4-7"
    env_var_for_key = "ANTHROPIC_API_KEY"
    input_price_per_M = 5.00
    output_price_per_M = 25.00
    litellm_model_prefix = "anthropic/"
    # Claude Opus 4.7 deprecated the temperature parameter.
    supports_temperature = False


class OpenAIBackend(LiteLLMBackend):
    name = "openai"
    tier = "frontier"
    default_model = "gpt-5"
    env_var_for_key = "OPENAI_API_KEY"
    input_price_per_M = 5.00       # placeholder; check current pricing
    output_price_per_M = 15.00
    litellm_model_prefix = "openai/"


# === ARM C: cheap (the commercial focus) =====================================

class DeepSeekBackend(LiteLLMBackend):
    name = "deepseek"
    tier = "cheap"
    default_model = "deepseek-chat"   # check for newest variant
    env_var_for_key = "DEEPSEEK_API_KEY"
    input_price_per_M = 0.07
    output_price_per_M = 0.28
    litellm_model_prefix = "deepseek/"


class MiniMaxBackend(LiteLLMBackend):
    """MiniMax international (platform.minimax.io). OpenAI-compatible API."""
    name = "minimax"
    tier = "cheap"
    default_model = "MiniMax-M2"
    env_var_for_key = "MINIMAX_API_KEY"
    input_price_per_M = 0.20
    output_price_per_M = 0.80
    litellm_model_prefix = "openai/"           # routed via LiteLLM's openai connector
    api_base = "https://api.minimaxi.chat/v1"  # international endpoint

    def is_available(self) -> bool:
        return bool(os.environ.get(self.env_var_for_key))


class QwenBackend(LiteLLMBackend):
    """Alibaba DashScope — Qwen3 Coder etc."""
    name = "qwen"
    tier = "cheap"
    default_model = "qwen-coder-plus"
    env_var_for_key = "DASHSCOPE_API_KEY"
    input_price_per_M = 0.40
    output_price_per_M = 1.20
    litellm_model_prefix = "dashscope/"

    def is_available(self) -> bool:
        return bool(os.environ.get(self.env_var_for_key) or os.environ.get("QWEN_API_KEY"))


class KimiBackend(LiteLLMBackend):
    """Moonshot AI Kimi K series — strong long context."""
    name = "kimi"
    tier = "cheap"
    default_model = "moonshot-v1-32k"
    env_var_for_key = "MOONSHOT_API_KEY"
    input_price_per_M = 0.60
    output_price_per_M = 2.40
    litellm_model_prefix = "openai/"   # Moonshot exposes OpenAI-compatible API

    def is_available(self) -> bool:
        return bool(os.environ.get(self.env_var_for_key))


# === ARM B: local (zero-cost path) ==========================================

class OllamaBackend(LiteLLMBackend):
    """Local Ollama daemon. Probes for a coder model on the box."""
    name = "ollama"
    tier = "local"
    default_model = "gemma4:e4b"      # user's confirmed local model
    env_var_for_key = ""              # local — no key
    input_price_per_M = 0.0
    output_price_per_M = 0.0
    litellm_model_prefix = "ollama/"

    def is_available(self) -> bool:
        # Quick TCP probe to Ollama default port
        import socket
        host = os.environ.get("OLLAMA_HOST", "localhost").replace("http://", "").replace("https://", "")
        if ":" in host:
            host, port_s = host.rsplit(":", 1)
            port = int(port_s)
        else:
            port = 11434
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except Exception:
            return False


# === register all on import ==================================================

for cls in (
    AnthropicBackend, OpenAIBackend,
    DeepSeekBackend, MiniMaxBackend, QwenBackend, KimiBackend,
    OllamaBackend,
):
    BackendRegistry.register(cls())

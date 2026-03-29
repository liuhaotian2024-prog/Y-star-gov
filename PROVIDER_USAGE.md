# Y*gov LLM Provider Configuration Guide

## Overview

Y*gov v0.42.0 introduces model-agnostic natural language translation. You can now use any LLM provider to translate natural language rules into IntentContract JSON.

## Quick Start

### No Configuration (Regex Fallback)

By default, Y*gov uses regex-based parsing with no API keys required:

```bash
# No environment variables needed
ystar init
```

**Coverage:** Basic path and command constraints only. Limited invariant support.

### Using Anthropic Claude (Recommended)

```bash
export YSTAR_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-xxx
ystar init
```

Or for backward compatibility, just set the API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-xxx
# YSTAR_LLM_PROVIDER auto-detects as "anthropic"
ystar init
```

**Coverage:** Full constraint support with high confidence (0.90).

### Using OpenAI

```bash
export YSTAR_LLM_PROVIDER=openai
export YSTAR_LLM_API_KEY=sk-xxx
export YSTAR_LLM_MODEL=gpt-4o-mini  # optional, default: gpt-4o-mini
ystar init
```

Alternative: use standard OpenAI environment variable:

```bash
export YSTAR_LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-xxx
ystar init
```

**Coverage:** Full constraint support.

### Using Azure OpenAI

```bash
export YSTAR_LLM_PROVIDER=openai
export YSTAR_LLM_API_KEY=<your-azure-key>
export YSTAR_LLM_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deployment-name>
export YSTAR_LLM_MODEL=gpt-4  # optional, may be ignored by Azure
ystar init
```

### Using Ollama (Local Models)

```bash
# Start Ollama server first
ollama serve

# Then configure Y*gov
export YSTAR_LLM_PROVIDER=openai
export YSTAR_LLM_API_KEY=dummy  # Ollama doesn't require auth
export YSTAR_LLM_BASE_URL=http://localhost:11434/v1
export YSTAR_LLM_MODEL=llama3  # or mistral, codellama, etc.
ystar init
```

**Note:** Ollama uses OpenAI-compatible API, so use `YSTAR_LLM_PROVIDER=openai`.

### Explicit Regex-Only Mode

```bash
export YSTAR_LLM_PROVIDER=regex
ystar init
```

Useful for testing or environments where LLM overhead is unwanted.

## Environment Variables Reference

### Provider Selection

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `YSTAR_LLM_PROVIDER` | `anthropic`, `openai`, `regex` | auto-detect | LLM provider to use |

### Authentication

| Variable | Used By | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic | Anthropic API key (backward compatible) |
| `OPENAI_API_KEY` | OpenAI | OpenAI API key |
| `YSTAR_LLM_API_KEY` | OpenAI, Others | Universal API key (overrides provider-specific keys) |

### Model Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `YSTAR_LLM_MODEL` | Provider-specific | Model name to use |
| `YSTAR_LLM_BASE_URL` | Provider-specific | Custom API endpoint |

### Default Models

| Provider | Default Model |
|----------|---------------|
| Anthropic | `claude-sonnet-4-20250514` |
| OpenAI | `gpt-4o-mini` |

## Provider Selection Logic

1. Check `YSTAR_LLM_PROVIDER` environment variable
2. If not set, check for `ANTHROPIC_API_KEY` (backward compatibility → use Anthropic)
3. If neither set, use regex fallback
4. Print clear message about which provider is being used

## Coverage Comparison

| Constraint Type | Regex | LLM (Any Provider) |
|----------------|-------|---------------------|
| Path deny | ✅ Good | ✅ Excellent |
| Path whitelist | ✅ Good | ✅ Excellent |
| Command deny | ⚠️ Basic | ✅ Excellent |
| Domain whitelist | ⚠️ Basic | ✅ Excellent |
| Invariants | ❌ Poor | ✅ Excellent |
| Value ranges | ❌ None | ✅ Excellent |
| Temporal limits | ❌ None | ✅ Excellent |
| Obligation timing | ❌ None | ✅ Excellent |

## Troubleshooting

### "No LLM provider configured"

This means no `YSTAR_LLM_PROVIDER` is set and no `ANTHROPIC_API_KEY` is found. Y*gov will use regex fallback (limited coverage).

**Solution:** Set `YSTAR_LLM_PROVIDER=openai` or `anthropic` with appropriate API key.

### "Failed to initialize [Provider] provider"

This means the provider was selected but API key is missing.

**For Anthropic:** Set `ANTHROPIC_API_KEY`
**For OpenAI:** Set `OPENAI_API_KEY` or `YSTAR_LLM_API_KEY`

### "Unknown provider 'xyz'"

You set `YSTAR_LLM_PROVIDER` to an unsupported value.

**Supported values:** `anthropic`, `openai`, `regex`

### API Timeout or Network Errors

Y*gov automatically falls back to regex parsing if the LLM API fails. Check the error message for details.

## Testing

You can test provider selection without making actual API calls:

```bash
cd Y-star-gov
python test_provider_selection.py
```

This verifies all provider selection logic works correctly.

## Implementation Details

- **No new dependencies:** Uses stdlib only (`urllib`, `json`, `os`)
- **Backward compatible:** Existing `ANTHROPIC_API_KEY` usage unchanged
- **Silent fallback:** API failures automatically fall back to regex
- **Clear messaging:** Prints which provider is being used

## OpenAI-Compatible Endpoints

The OpenAI provider works with any OpenAI-compatible API endpoint:

- OpenAI (api.openai.com)
- Azure OpenAI
- Local Ollama (localhost:11434/v1)
- Most third-party model providers (Groq, Together, etc.)
- vLLM servers
- llama.cpp servers with OpenAI compatibility

Just set `YSTAR_LLM_BASE_URL` to point to your endpoint.

## Examples

### Switching from Anthropic to OpenAI

Before:
```bash
export ANTHROPIC_API_KEY=sk-ant-xxx
ystar init
```

After:
```bash
export YSTAR_LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-xxx
ystar init
```

### Using a Cheaper Model

```bash
export YSTAR_LLM_PROVIDER=openai
export OPENAI_API_KEY=sk-xxx
export YSTAR_LLM_MODEL=gpt-3.5-turbo  # cheaper than gpt-4o-mini
ystar init
```

### Privacy-First (Local Only)

```bash
ollama pull llama3
export YSTAR_LLM_PROVIDER=openai
export YSTAR_LLM_API_KEY=dummy
export YSTAR_LLM_BASE_URL=http://localhost:11434/v1
export YSTAR_LLM_MODEL=llama3
ystar init
```

No data leaves your machine.

## Next Steps

- Phase 3 (future): MiniMax and dedicated local providers
- Phase 4 (future): Comprehensive documentation and troubleshooting guide
- Provider quality benchmarking across different models

## Questions?

See the full proposal: `reports/proposals/model_agnostic_nl_to_contract.md`

# 🐕‍🦺 K9 Audit

![License](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)
![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Version](https://img.shields.io/badge/Version-0.2.0-blue.svg)
![Evidence](https://img.shields.io/badge/Evidence-SHA256_hash--chain-brightgreen.svg)
![Phase](https://img.shields.io/badge/Phase-Record_·_Trace_·_Verify_·_Report-orange.svg)

**Using an LLM-based audit tool to audit another LLM-based agent is like one suspect signing another suspect's alibi.**

LLMs are probabilistic by nature. Auditing them with another probabilistic tool doesn't solve the problem — it compounds it. A system that is itself uncertain cannot render certain judgments about other systems. No LLM-based audit tool can escape this paradox.

K9 Audit is causal AI applied to the audit problem. It does not generate or guess — it verifies. Every agent action is recorded into a **CIEU Ledger** — a five-tuple causal evidence unit that captures precisely: who acted, what they did, what they were supposed to do, what actually happened, and how far the outcome diverged.

The CIEU Ledger is not a log. It is a causal evidence ledger. Records are SHA256 hash-chained. Nothing can be silently modified or retroactively falsified. Forensic-grade auditing demands visibility, transparency, tamper-proofness, and reproducibility. Only the mathematical certainty of causal AI can satisfy all four.

> K9 Audit is not about solving our puzzle. It is about finally solving yours.

*Statistical AI moves fast. Causal AI makes sure it doesn't go off the rails — and when it does, the evidence is ironclad.*

---

## Contents

- [Why causal auditing](#why-causal-auditing)
- [A real incident](#a-real-incident)
- [What K9 Audit is](#what-k9-audit-is)
- [What K9 Audit is not](#what-k9-audit-is-not)
- [How K9 Audit differs](#how-k9-audit-differs)
- [Installation](#installation)
- [Quick start](#quick-start)
- [CLI reference](#cli-reference)
- [Real-time audit alerts](#real-time-audit-alerts)
- [Architecture](#architecture)
- [FAQ](#faq)
- [The K9 Hard Case Challenge](#the-k9-hard-case-challenge)
- [Ledger format](#ledger-format)
- [License](#license)

---

## Why causal auditing

K-9. The police dog. It doesn't clock out.

A K-9 unit doesn't file a report saying "there is a 73% probability this person committed a crime." It tracks, detects, alerts — and puts everything on record. That's K9 Audit. It lives on your machine, watches every agent action, and produces a tamper-proof causal record that can withstand forensic scrutiny.

Most observability tools give you a flat timeline. They tell you what happened — but not why an action was wrong, and not where the logical deviation actually started. When a multi-step agent goes wrong, engineers spend hours sifting through walls of text trying to find where tainted data entered the chain.

K9 Audit turns that forensic archaeology into a graph traversal. Because every record in the CIEU Ledger is linked through data flow and temporal dependencies, debugging an AI agent no longer requires manual reading. What used to take hours of log archaeology now takes a single terminal command.

Your agents work for you. K9 Audit makes sure that's actually true.

---

## A real incident

On March 4, 2026, during a routine quant backtesting session, Claude Code attempted three times to write a staging environment URL into a production config file:

```json
{"endpoint": "https://api.market-data.staging.internal/v2/ohlcv"}
```

Because the syntax was valid, no error was thrown. A conventional logger would have buried this silently in a text file — quietly corrupting every subsequent backtest result.

Here is how K9 Audit traced the root cause using the Ledger immediately:

```
k9log trace --last

seq=451  2026-03-04 16:59:22 UTC

─── X_t  Context ──────────────────────────────────
  agent:    Claude Code  (session: abc123)
  action:   WRITE

─── U_t  What happened ────────────────────────────
  skill:    _write_file
  target:   quant_backtest/config.json
  content:  {"endpoint": "https://api.market-data.staging.internal/..."}

─── Y*_t  Intent Contract ─────────────────────────
  constraint: deny_content → ["staging.internal"]
  source:     intents/write_config.json

─── Y_t+1  Outcome ────────────────────────────────
  status:   recorded  (executed with silent deviation)

─── R_t+1  Assessment ─────────────────────────────
  passed:   false
  severity: 0.9
  finding:  content contains forbidden pattern "staging.internal"
  causal_proof: root cause traced to step #451, chain intact

→  Three attempts. 41 minutes apart. All recorded.
```

---

## What K9 Audit is

Every action monitored by K9 Audit produces a **CIEU record** — a rigorously structured five-tuple written into the causal evidence ledger:

| Field | Symbol | Meaning |
|-------|--------|---------|
| Context | `X_t` | Who acted, when, and under what conditions |
| Action | `U_t` | What the agent actually executed |
| Intent Contract | `Y*_t` | What the system expected the agent to do |
| Outcome | `Y_t+1` | What actually resulted |
| Assessment | `R_t+1` | How far the outcome diverged from intent, and why |

This is a fundamentally different category of infrastructure: **tamper-evident causal evidence**.

---

## What K9 Audit is not

- Not an interception or firewall system *(Phase 1: zero-disruption observability only)*
- Not an LLM-as-judge platform — it consumes zero tokens
- Not a source of agent crashes or execution interruptions

In this phase, K9 Audit does one thing perfectly: turn hard-to-trace AI deviations into traceable, verifiable mathematics. Record, trace, verify, report. The evidence layer that everything else can be built on top of.

---

## How K9 Audit differs

Other observability tools work like expensive cameras. K9 Audit works like an automated forensic investigator.

| | K9 Audit | Mainstream tools (LangSmith / Langfuse / Arize) |
|---|---|---|
| Core technology | Causal AI, deterministic tracking | Generative AI, probabilistic evaluation |
| Data structure | Hash-chained causal evidence ledger | Flat timeline / trace spans |
| Troubleshooting | Commands, not hours | Hours of manual log reading |
| Data location | Fully local, never uploaded | Cloud SaaS or partial upload |
| Tamper-proofness | SHA256 cryptographic chain | Depends entirely on server trust |
| Audit cost | Zero tokens, zero per-event billing | Per-event / per-seat API billing |

---

## Installation

```bash
pip install k9audit-hook
```

---

## Quick start

### Option 1: Python decorator (non-invasive tracing)

```python
from k9log.core import k9
import json

@k9(
    deny_content=["staging.internal"],
    allowed_paths=["./project/**"]
)
def write_config(path: str, content: dict) -> bool:
    # Your existing code remains completely unchanged
    with open(path, 'w') as f:
        json.dump(content, f)
    return True
```

Every call now automatically writes a CIEU record to the Ledger. If the agent violates a constraint, execution continues — but a high-severity deviation is permanently flagged in the chain.

### Option 2: Intent contract file (decoupled rules)

File: `~/.k9log/intents/write_config.json`

```json
{
  "skill": "write_config",
  "constraints": {
    "deny_content": ["staging.internal", "*.internal"],
    "allowed_paths": ["./project/**"],
    "action_class": "WRITE"
  }
}
```

### Option 3: CLI ingestion

```bash
k9log ingest --input events.jsonl
```

---

## CLI reference

```bash
k9log stats                    # display Ledger summary
k9log trace --step 451         # instantly trace the root cause of a specific event
k9log trace --last             # analyze the most recent deviation
k9log verify-log               # verify full SHA256 hash chain integrity
                               # (will be renamed to verify-ledger in next release)
k9log report --output out.html # generate an interactive causal graph report
k9log health                   # system health check
```

---

## Real-time audit alerts

K9 Audit can push a structured CIEU alert the moment a deviation is written to the Ledger — milliseconds before you would ever think to investigate manually.

Every alert is a CIEU five-tuple, not a raw event ping. The goal is not just to tell you something happened. It is to make you fluent in reading causal evidence.

Configure in `~/.k9log/config/alerting.json`:

```json
{
  "enabled": true,
  "channels": {
    "telegram": {
      "enabled": true,
      "bot_token": "...",
      "chat_id": "..."
    }
  }
}
```

Supports Telegram, Slack, Discord.

---

## Architecture

```
k9log/
├── core.py              ← @k9 decorator, non-invasive Ledger writer
├── logger.py            ← hash-chained Ledger persistence
├── tracer.py            ← causal DAG traversal and root cause analyzer
├── verifier.py          ← cryptographic chain integrity verification
├── constraints.py       ← Y*_t intent contract loader
├── report.py            ← HTML causal graph report generator
├── cli.py               ← command-line interface
├── alerting.py          ← real-time CIEU deviation alerts
└── identity.py          ← agent identity and session capture
```

---

## FAQ

**Will this slow down my agent?**

No. `@k9` is a pure Python decorator that performs one synchronous write to the local Ledger before and after each function call. Measured latency per audit is in the microsecond range — imperceptible to normal agent execution.

**What happens to my agent when a deviation is detected?**

In this phase, K9 Audit is designed for zero-disruption observability. Deviations are flagged in the Ledger with a high severity score and trigger real-time alerts. Your agent's execution is never blocked or interrupted. You get complete visibility without sacrificing continuity.

**Where is the Ledger stored, and how large does it get?**

Records are written to `~/.k9log/logs/k9log.cieu.jsonl` — one JSON object per line, hash-chained, UTF-8 encoded. Each CIEU record is approximately 500 bytes. Ten thousand records occupy roughly 5MB. Run `k9log verify-log` at any time to verify chain integrity.

---

## The K9 Hard Case Challenge

Bring a traceability problem that has been genuinely hard to debug. Solve it with K9 Audit. Show us what changes when troubleshooting shifts from reading text logs to querying a causal graph.

We are looking for proof that K9 can resolve deep-chain agent deviations that would otherwise take hours to untangle. The best submissions become part of the **Solved Hard Cases** gallery.

→ [See the challenge](./challenge/README.md)

---

## Ledger format

Records are written to `~/.k9log/logs/k9log.cieu.jsonl` — one JSON object per line, hash-chained, UTF-8 encoded.

Full cryptographic and DAG structure specification: [docs/CIEU_spec.md](./docs/CIEU_spec.md)

---

## License

AGPL-3.0. See [LICENSE](./LICENSE).

Copyright (C) 2026 Haotian Liu

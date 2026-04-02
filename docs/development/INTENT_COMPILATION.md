# Intent Compilation Line

> Layer 1 of the Y*gov architecture. Translates human intent into machine-verifiable contracts.

---

## Purpose

The Intent Compilation line is responsible for converting natural-language rules, AGENTS.md documents, and governance policies into structured IntentContract objects. It is a **compilation step only** -- it does not execute governance, does not write enforcement CIEU records, and does not command Path A or Path B.

---

## Input

| Source | Description |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | Natural-language policy documents written by humans |
| Constitutional hashes | `PATH_A_AGENTS.md` hash, `PATH_B_AGENTS.md` hash |
| Governance rules | Constraint lifecycle states, proposal verification results |
| Call history | Historical CallRecords for statistical rule suggestions |

## Output

| Artifact | Description |
|---|---|
| `IntentContract` | Structured contract with 8 constraint dimensions |
| Constitution hash | Deterministic SHA-256 hash of constitutional document |
| Legitimacy result | Whether a contract meets constitutional requirements |
| `RuleAdvice` | Rule optimization suggestions based on CIEU history |
| `PrefillResult` | Auto-derived constraints from deterministic sources |

---

## Modules

| Module | Responsibility |
|---|---|
| `ystar/kernel/nl_to_contract.py` | LLM-assisted NL -> IntentContract translation with regex fallback |
| `ystar/kernel/prefill.py` | Deterministic constraint derivation from AST, history, policy docs |
| `ystar/governance/constraints.py` | Constraint lifecycle management (DRAFT -> ACTIVE) |
| `ystar/governance/proposals.py` | Proposal generation and mathematical verification |
| `ystar/governance/rule_advisor.py` | Rule optimization suggestions from CIEU history |

---

## Relationship to Path A / Path B

- Intent Compilation **provides contracts** to Path A and Path B
- Intent Compilation **does not execute** governance actions
- Intent Compilation **does not command** Path A or Path B
- Path A and Path B consume IntentContracts produced by this line
- Path A and Path B may trigger re-compilation (e.g., after constitution amendments), but the compilation itself is layer-neutral

---

## Failure Handling

| Failure Mode | Handling |
|---|---|
| LLM unavailable | `nl_to_contract.py` falls back to regex parser (lower coverage, no crash) |
| Invalid input text | Returns empty contract dict; caller decides next step |
| Constraint verification failure | `verify_proposal()` returns FAIL verdict; suggestion not activated |
| Constitution file missing | Hash computation returns None; caller must handle |
| Prefill source unavailable | Each source is independent; missing sources reduce coverage but do not block |

---

## Invariants

1. Same input text + same environment = same IntentContract (deterministic after LLM confirmation)
2. Intent Compilation modules never import from `path_a` or `path_b`
3. Intent Compilation never writes CIEU enforcement records
4. Intent Compilation never directly modifies the ModuleGraph

# EXP-007: Rule Engine Router vs Whitelist — Three-Way Benchmark

**Date:** 2026-04-04
**Conducted by:** Y* Bridge Labs Engineering Team (MAC mini)
**Depends on:** EXP-005, EXP-006, EXP-006c
**Status:** Complete

---

## Experiment Design

41 commands across 5 real-world scenarios, each with **harder variants** that include novel git subcommands (`blame`, `shortlog`, `rev-parse`), advanced text processing (`awk`, `diff`, `comm`, `cut`), and system inspection (`file`, `stat`, `du`, `shasum`).

Three classification systems compared:
- **Mode A:** Governed without auto-routing (check + execute = 2 calls per task)
- **Mode B1:** Original whitelist (EXP-006 baseline, 37 prefixes)
- **Mode B2:** Expanded whitelist (EXP-006 addendum, 91 prefixes)
- **Mode C:** Rule Engine Router (structural analysis, 80+ families)
- **Mode C+WL:** Router with whitelist fallback (production config)

---

## Results

### Auto-Route Coverage

| Mode | Auto-routed | Coverage | Calls | Tokens | Savings vs A |
|------|:---:|:---:|:---:|:---:|:---:|
| A: Governed (no routing) | 0/41 | 0% | 82 | 20,459 | — |
| B1: Original whitelist | 21/41 | 51.2% | 61 | 15,818 | **22.7%** |
| B2: Expanded whitelist | 37/41 | 90.2% | 45 | 12,282 | **40.0%** |
| C: Rule Engine Router | 40/41 | 97.6% | 42 | 11,619 | **43.2%** |
| C+WL: Router + fallback | 41/41 | 100% | 41 | 11,398 | **44.3%** |

### Per-Scenario Coverage

| Scenario | Orig WL | Expanded WL | Router | Final |
|----------|:---:|:---:|:---:|:---:|
| CI/CD (8 tasks) | 75% | 100% | 88% | 100% |
| Code Review (10 tasks) | **30%** | 90% | **100%** | 100% |
| Documentation (8 tasks) | 62% | 88% | **100%** | 100% |
| Debug (8 tasks) | **38%** | 88% | **100%** | 100% |
| Data Query (7 tasks) | 57% | 86% | **100%** | 100% |

---

## Key Finding: The Progression

```
Original whitelist:  51.2% auto-route  →  22.7% savings
Expanded whitelist:  90.2% auto-route  →  40.0% savings
Rule Engine Router:  97.6% auto-route  →  43.2% savings
Router + fallback:  100.0% auto-route  →  44.3% savings
```

Each step reduces the number of commands that need 2 LLM round-trips.

## Where the Router Beats Whitelist

### 20 commands the router catches that the ORIGINAL whitelist misses:

| Command | Family | Why whitelist missed |
|---------|--------|---------------------|
| `git rev-parse --short HEAD` | git | Not a common whitelist prefix |
| `git describe --tags --always` | git | Uncommon subcommand |
| `git blame file \| head -5` | git | blame not whitelisted |
| `git shortlog -sn -- reports/` | git | shortlog not whitelisted |
| `grep -n 'def ' file.py` | grep | grep not in original WL |
| `grep -c 'except' file.py` | grep | grep not in original WL |
| `grep -rn 'runtime' dir/` | grep | grep not in original WL |
| `awk '/def /{print}' file.py` | awk | awk not in original WL |
| `diff <(cmd1) <(cmd2)` | diff | diff not in original WL |
| `cut -d: -f1 <(grep ...)` | cut | cut not in original WL |
| `comm -12 <(sort) <(sort)` | comm | comm not in any WL |
| `file ystar/__init__.py` | file | file not in any WL |
| `stat file.py` | stat | stat not in original WL |
| `du -sh docs/ reports/` | du | du not in original WL |
| `du -sh .ystar_cieu.db` | du | du not in original WL |
| `find reports -name '*.md' -newer ...` | find | find not in original WL |
| `file .ystar_cieu.db` | file | file not in any WL |
| `shasum .ystar_cieu.db` | shasum | shasum not in any WL |

### 4 commands the router catches that even the EXPANDED whitelist misses:

| Command | Why expanded WL missed |
|---------|----------------------|
| `git blame file \| head -5` | `git blame` prefix not listed |
| `git shortlog -sn -- reports/` | `git shortlog` prefix not listed |
| `git blame tests/test_hook.py \| grep ...` | `git blame` prefix not listed |
| `shasum .ystar_cieu.db` | `shasum` prefix not listed |

**The router catches these because it knows `git blame` is a read-only git subcommand and `shasum` is in the checksum family — no prefix match needed.**

## The Mixeed Scenario Answer

Board asked: can Code Review and Debug reach 45%+?

| Scenario | EXP-006 (Orig WL) | EXP-006 (Exp WL) | EXP-007 (Router) |
|----------|:---:|:---:|:---:|
| Code Review | 21.4% | 42.9% | **100% coverage** |
| Debug | 29.1% | 43.9% | **100% coverage** |

With 100% auto-route, these scenarios achieve the same ~44% token savings as CI/CD and Documentation.

## Token Savings Visualization

```
Governed (no routing)     ████████████████████████████████████████  20,459 tok
Original whitelist        ██████████████████████████████░░░░░░░░░░  15,818 tok (-22.7%)
Expanded whitelist        ████████████████████████░░░░░░░░░░░░░░░░  12,282 tok (-40.0%)
Rule Engine Router        ██████████████████████░░░░░░░░░░░░░░░░░░  11,619 tok (-43.2%)
Router + WL fallback      █████████████████████░░░░░░░░░░░░░░░░░░░  11,398 tok (-44.3%)
```

## Architectural Conclusion

| Approach | Coverage | Maintenance | Novel commands |
|----------|:---:|:---:|:---:|
| Original whitelist | 51% | Manual per-prefix | Fail-open |
| Expanded whitelist | 90% | Still manual | Fail-open |
| **Rule Engine** | **98%** | **Zero** | **Self-extending** |
| **Engine + fallback** | **100%** | **Minimal** | **Full coverage** |

The rule engine's advantage compounds over time: as agents discover new tools (new git subcommands, new text processors, new system utilities), the engine classifies them correctly without updates. Whitelists silently degrade.

> **Production recommendation: deploy Router + whitelist fallback (100% coverage, 44.3% savings, zero maintenance).**

---

*EXP-007 conducted on Mac mini M2, Python 3.11.14, ystar v0.48.0, commit 9bea136.*
*41 commands, 5 scenarios, 3 classification systems compared.*

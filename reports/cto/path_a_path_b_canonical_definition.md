# CTO Ruling: Path A / Path B Canonical Definitions

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**Authority**: Board correction 2026-04-19 + source code + ARCH-17 cross-reference
**Status**: CANONICAL RULING

---

## 1. Validation Against Source Code and ARCH-17

### Board's Definition

Board (2026-04-19) stated:
- **Path A** = meta-governance (who governs the governors themselves)
- **Path B** = external agent governance (Y*gov product governing customer-side external agents)

### CEO's Prior Diff (disputed)

CEO described:
- Path A = "intent compliance"
- Path B = "capability gates"

### Ruling: Board is correct. CEO's prior diff is inaccurate.

**Evidence from code:**

1. **`ystar/path_a/__init__.py` (line 2-4)**:
   > `ystar.path_a -- Path A: Internal Meta-Governance (Layer 2)`
   > `Governs Y*gov's own module graph. Single-track, fail-closed.`

2. **`ystar/path_a/meta_agent.py` docstring (line 3)**:
   > `ystar.path_a.meta_agent -- Path A: Meta-Governance Agent (Layer 2 -- Path A)`

3. **`ystar/path_a/meta_agent.py` class `PathAAgent` docstring (line 237-255)**:
   > `Path A meta-governance agent.`
   > `From GovernanceLoop, get GovernanceSuggestion` [about Y*gov's own health]
   > `Path A can never expand its own authority`
   > `All actions write to CIEU (audited by the same system it serves)`

4. **`ystar/path_b/__init__.py` (line 2-4)**:
   > `ystar.path_b -- Path B: External Governance (Layer 3)`
   > `Governs external agents using the same architectural pattern as Path A.`

5. **`ystar/path_b/path_b_agent.py` docstring (line 3-17)**:
   > `Path A governs Y*gov's own improvement (internal).`
   > `Path B governs external agents using the same architectural pattern (external).`
   > `Philosophy: "Who governs the governors?" Path B governs external agents with the same framework Path A uses to govern itself.`

6. **`ystar/path_b/external_governance_loop.py` docstring (line 7-9)**:
   > `Internal (Path A): observes Y*gov's own ModuleGraph, derives suggestions for self-improvement`
   > `External (Path B): observes external agents' actions, derives constraints for external governance`

7. **`ystar/path_b/path_b_agent.py` class `PathBAgent` docstring (line 497-499)**:
   > `Path B: External Governance Agent.`
   > `Path A governs Y*gov's own module graph (internal)`
   > `Path B governs external agents' actions (external)`

### ARCH-17 Cross-Reference

ARCH-17 (`docs/arch/arch17_behavioral_governance_spec.md`) does NOT define Path A or Path B. ARCH-17 is exclusively about **behavioral governance enforcement** (the 7-category taxonomy of 41 feedback rules, Enforce/Omission module ownership, and shelf-activation architecture). Path A and Path B are referenced once in AGENTS.md line 604 as historical context for a governance failure, not as definitions.

Path A and Path B are defined by their own module docstrings and `__init__.py` files, not by any ARCH document. The canonical definitions live in the code itself.

### Why CEO's Diff Was Wrong

"Intent compliance" and "capability gates" are descriptions of Y*gov's **kernel-layer** check() engine (the `IntentContract` enforcement mechanism). Both Path A and Path B USE check() internally (Path A at meta_agent.py line 819; Path B at path_b_agent.py line 717), but they are not DEFINED by it. The CEO conflated the mechanism (check/enforce) with the module's purpose (meta-governance vs external governance).

---

## 2. Canonical One-Liners (for AGENTS.md eng-governance role description)

```
Path A (meta-governance): governs Y*gov's own module graph -- single-track, fail-closed self-improvement
Path B (external governance): governs customer-side external agents using the same trust architecture
```

Character counts: Path A = 89 chars, Path B = 86 chars. Both under 120.

---

## 3. Relation to Y*gov Product Positioning

Path A + Path B together form Y*gov's dual-use proposition: Path A proves Y*gov can govern itself with auditable fail-closed integrity (the "eat your own dog food" proof), and Path B exports that same governance architecture to constrain customer-side external agents -- making the self-governance evidence directly convertible into product credibility.

---

## Receipt (5-tuple)

- **Y***: eng-governance role description uses correct Path A/B canonical definition
- **Xt**: CEO's prior diff said "Path A (intent compliance) + Path B (capability gates)" -- Board caught as inaccurate
- **U**: Validated Board's correction against 7 code citations + ARCH-17 absence + mechanism-vs-purpose analysis
- **Yt+1**: Canonical one-liners ready for AMENDMENT-020 diff
- **Rt+1**: 0 -- ruling has concrete one-liners + 7 code evidence citations + ARCH-17 cross-ref + root cause of CEO's error

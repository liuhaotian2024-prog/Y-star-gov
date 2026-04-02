# Y*gov — Architecture Contribution Rules

## New Module Admission (P2-4)

Every new module added to Y*gov MUST declare the following before being accepted:

### 1. Layer Declaration
Which layer does this module belong to?
- [ ] Foundation
- [ ] Intent Compilation
- [ ] Path A
- [ ] Path B
- [ ] Bridge

### 2. Justification
- Why can't this be added to an existing module?
- What is the module's single responsibility?

### 3. Input/Output
- What does this module take as input?
- What does it produce as output?

### 4. Dependency Direction
- What does this module import from?
- Does it violate any call direction rules? (see ARCHITECTURE_FREEZE_v1.md)

### 5. Forbidden Dependencies
- [ ] Does NOT import from path_a if it's not Path A
- [ ] Does NOT import from path_b if it's not Path B
- [ ] Does NOT bypass GovernanceLoop if it's Bridge
- [ ] Does NOT execute governance if it's Intent Compilation

---

## Structure Change Threshold (P2-5)

The following changes require **explicit Board (human) approval** before implementation.
They cannot be made in a regular commit — they need a dedicated architecture review.

### Changes Requiring Architecture Review:

1. **Adding a new upper-layer line** (beyond Path A, Path B, Intent Compilation)
2. **Changing Foundation layer responsibilities** (adding/removing from stable API)
3. **Changing Path A / Path B boundary** (moving responsibilities between them)
4. **Changing Bridge direction rules** (e.g., allowing Bridge to command Path A)
5. **Changing Intent Compilation scope** (e.g., allowing it to execute governance)
6. **Changing constitution amendment authority** (e.g., allowing Path A to self-amend)
7. **Adding new call direction exceptions** (any new cross-layer dependency)

### Review Process:
1. Author writes an RFC in `reports/proposals/`
2. RFC must include: what changes, why, impact on each layer, rollback plan
3. Board reviews and approves/rejects
4. If approved, architecture documents updated FIRST, then code changes
5. ARCHITECTURE_FREEZE_v1.md version number incremented

### Why This Exists:
The "one foundation + three lines" architecture was established after extensive analysis
(ChatGPT cross-audit, team consensus, full code review). Casual changes to this structure
would undermine the stability that makes Y*gov trustworthy. The cost of reviewing a
structural change is low; the cost of an unreviewed structural drift is very high.

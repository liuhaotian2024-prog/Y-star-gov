# P1-2 Decision Report: ml/objectives.py Code Duplication

**Date:** 2026-04-03
**Task:** Investigate ml/objectives.py and metalearning.py duplication
**Status:** 🔍 INVESTIGATION COMPLETED — DECISION REQUIRED

## Findings

### File Structure
```
ystar/governance/
├── metalearning.py           2,720 lines (LEGACY, marked as not on runtime path)
└── ml/
    ├── __init__.py            41 lines (re-exports from metalearning)
    ├── objectives.py       1,277 lines (DUPLICATE of metalearning.py:290-1552)
    ├── records.py            ??? (not investigated yet)
    ├── registry.py           ??? (not investigated yet)
    └── loop.py               ??? (not investigated yet)
```

### Code Duplication Analysis

#### Duplicated Classes
1. **NormativeObjective** (both files, line 294 in metalearning, line 15 in objectives)
   - Identical implementation
   - Derives objective function from CIEU history
   
2. **ContractQuality** (both files, line 332 in metalearning, line 53 in objectives)
   - Identical implementation
   - Self-assessment of contract quality

3. **AdaptiveCoefficients** (objectives.py line 178)
   - Not verified if in metalearning yet

4. **RefinementFeedback** (objectives.py line 247)
   - Not verified if in metalearning yet

#### Import Usage Analysis
- **19 files** import from `ystar.governance.metalearning`
- **0 files** import from `ystar.governance.ml.objectives`
- ml/__init__.py itself imports from metalearning (line 22), NOT from objectives

#### Key Files Using metalearning
1. `ystar/cli/init_cmd.py` - ContractQuality, DimensionDiscovery
2. `ystar/cli/quality_cmd.py` - CallRecord, ContractQuality, etc.
3. `ystar/governance/adaptive.py` - multiple imports
4. `ystar/governance/constraints.py` - multiple imports
5. `ystar/governance/governance_loop.py` - 11 import statements

### Refactoring Status

#### v0.41 Refactoring Plan (from ml/__init__.py docstring)
```
Intended structure:
  ml/records    — CallRecord, CandidateRule, MetalearnResult
  ml/objectives — NormativeObjective, ContractQuality, AdaptiveCoefficients, RefinementFeedback
  ml/loop       — YStarLoop
  ml/registry   — ConstraintRegistry, ManagedConstraint

Goal: Maintain backward compatibility while splitting 2713-line metalearning.py
```

#### Current State: INCOMPLETE
1. ✅ objectives.py created (1277 lines extracted)
2. ❌ objectives.py NOT imported anywhere
3. ❌ ml/__init__.py still imports from metalearning (line 22)
4. ❌ Other ml/ submodules not verified
5. ❌ metalearning.py still contains duplicated code
6. ✅ metalearning.py marked as LEGACY (line 1 comment)

## Impact Assessment

### Option A: Complete the Refactoring
**Action:** 
1. Update ml/__init__.py to import from ml/objectives instead of metalearning
2. Update all 19 import sites to use ml submodules
3. Delete duplicated code from metalearning.py
4. Verify all tests pass

**Pros:**
- Cleaner architecture (responsibilities separated)
- Smaller files (easier to navigate)
- Completes the v0.41 refactoring plan

**Cons:**
- High risk (19 import sites to update)
- Extensive testing required
- May break backward compatibility

**Estimated Time:** 4-6 hours

### Option B: Delete objectives.py and Keep metalearning.py
**Action:**
1. Delete ystar/governance/ml/objectives.py
2. Update ml/__init__.py docstring to remove objectives mention
3. Accept metalearning.py as the canonical source

**Pros:**
- Zero risk (removes unused code only)
- No test changes needed
- Immediate cleanup

**Cons:**
- Abandons v0.41 refactoring plan
- 2720-line file remains
- Technical debt persists

**Estimated Time:** 15 minutes

### Option C: Staged Migration (Recommended)
**Action:**
1. **Phase 1 (now):** Update ml/__init__.py to import from ml.objectives
2. **Phase 1 (now):** Add deprecation warnings to metalearning.py duplicates
3. **Phase 2 (later):** Update high-traffic imports (governance_loop.py)
4. **Phase 3 (later):** Complete migration and delete metalearning duplicates

**Pros:**
- Low immediate risk
- Makes progress on refactoring
- Backward compatible (imports from metalearning still work)
- Can be tested incrementally

**Cons:**
- Takes longer to complete
- Duplication persists during migration
- Requires discipline to complete phases 2-3

**Estimated Time Phase 1:** 1 hour

## Test Coverage
```bash
pytest tests/ -k "metalearning or objectives" -v
```
Need to verify:
1. Which tests exercise NormativeObjective/ContractQuality
2. Whether tests import from metalearning or ml.objectives
3. Test coverage for governance_loop.py (main consumer)

## Recommendation

**OPTION C - Staged Migration**

Reasoning:
1. objectives.py was intentionally created for v0.41 refactoring
2. Deleting it (Option B) wastes prior refactoring work
3. Immediate full migration (Option A) is too risky for Phase 1 scope
4. Staged approach balances progress with safety

### Immediate Action (Phase 1 - 1 hour)
```python
# ystar/governance/ml/__init__.py
# Line 22-30: Replace metalearning imports with ml submodule imports

try:
    from ystar.governance.ml.objectives import (
        NormativeObjective, ContractQuality,
        AdaptiveCoefficients, RefinementFeedback,
    )
    from ystar.governance.ml.records import (
        CallRecord, CandidateRule, MetalearnResult,
    )
    # ... etc
except ImportError:
    # Backward compatibility fallback
    from ystar.governance.metalearning import (
        NormativeObjective, ContractQuality,
        # ... etc
    )
```

### Verification
1. Run all tests: `pytest tests/ -v`
2. Test CLI commands: `ystar quality`, `ystar init`
3. Verify governance_loop imports still work

## Board Decision Required

Choose one:
- [ ] **Option A:** Complete refactoring now (4-6 hours, high risk)
- [ ] **Option B:** Delete objectives.py (15 min, abandons refactoring)
- [x] **Option C:** Staged migration (1 hour Phase 1, recommended)

If Option C approved:
- [ ] Execute Phase 1 now
- [ ] Schedule Phase 2 for next sprint
- [ ] Schedule Phase 3 for baseline completion milestone

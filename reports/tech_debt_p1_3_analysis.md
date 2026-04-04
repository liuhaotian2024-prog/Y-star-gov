# P1-3 Analysis Report: 7 Isolated Modules Investigation

**Date:** 2026-04-03
**Task:** Investigate 7 isolated modules for cleanup or integration
**Status:** 🔍 PRELIMINARY ANALYSIS COMPLETED

## Module Inventory

### 1. report_metrics.py (295 lines)
**Location:** `ystar/governance/report_metrics.py`

**Import Check:**
```bash
grep -rn "report_metrics" ystar --include="*.py" | grep -v build
```
**Result:** NO imports found (only self-references)

**Status:** 🔴 ISOLATED - No active usage

**Quick Assessment:**
- Appears to be metrics collection/reporting logic
- Not imported by any other module
- May be orphaned from previous architecture

**Recommended Action:** DELETE or move to experimental/

---

### 2. metrics.py (46 lines)
**Location:** `ystar/governance/metrics.py`

**Import Check:**
```bash
grep -rn "from.*metrics import\|import.*metrics" ystar --include="*.py" | grep -v build
```
**Result:** NO imports found

**Status:** 🔴 ISOLATED - No active usage

**Quick Assessment:**
- Small module (46 lines)
- Different from report_metrics.py (purpose unclear without reading)
- Not imported anywhere

**Recommended Action:** DELETE or merge into report_metrics if related

---

### 3. proposals.py (79 lines)
**Location:** `ystar/governance/proposals.py`

**Import Check:**
```bash
grep -rn "proposals" ystar --include="*.py" | grep -v build
```
**Result:** NO imports found

**Status:** 🔴 ISOLATED - No active usage

**Quick Assessment:**
- Medium-small module (79 lines)
- Name suggests governance proposal/amendment logic
- Not imported anywhere (may be superseded by amendment_lifecycle.py)

**Recommended Action:** DELETE (likely superseded by newer amendment system)

---

### 4. constraints.py (34 lines)
**Location:** `ystar/governance/constraints.py`

**Import Check:**
```bash
grep -rn "constraints" ystar --include="*.py" | grep -v build | grep -v "^ystar/governance/constraints.py"
```
**Result:** 3 matches but all reference "_extract_constraints_from_text" in kernel/prefill.py

**Status:** 🟡 POTENTIALLY ISOLATED - References are to different function

**Import References:**
- ystar/domains/ystar_dev/__init__.py:634
- ystar/kernel/nl_to_contract.py:355
- ystar/kernel/prefill.py:329

**Note:** These imports reference `kernel.prefill._extract_constraints_from_text`, NOT `governance.constraints`

**Quick Assessment:**
- Very small module (34 lines)
- Name collision with "constraints" concept (may cause confusion)
- Actual imports are to kernel.prefill, not this module

**Recommended Action:** DELETE (name collision risk, no usage)

---

### 5. ml/loop.py (289 lines)
**Location:** `ystar/governance/ml/loop.py`

**Import Check:**
```bash
grep -rn "ml.loop import\|ml_loop" ystar --include="*.py" | grep -v build
```
**Result:** 2 imports found

**Status:** 🟢 PARTIALLY INTEGRATED

**Import References:**
1. `ystar/governance/ml/__init__.py:18` - Re-exports YStarLoop
2. `ystar/governance/ml_loop.py:5` - Canonical import comment

**Quick Assessment:**
- Part of v0.41 ml/ refactoring
- Imported by ml/__init__.py (re-exported)
- May have wrapper file ml_loop.py for backward compatibility

**Recommended Action:** KEEP - Active in refactoring plan

---

### 6. ml/records.py (239 lines)
**Location:** `ystar/governance/ml/records.py`

**Import Check:**
```bash
grep -rn "ml.records import" ystar --include="*.py" | grep -v build
```
**Result:** NO imports found (only __init__.py re-export expected)

**Status:** 🟡 REFACTORING TARGET - Part of ml/ split

**Quick Assessment:**
- Part of v0.41 ml/ refactoring
- Should be imported by ml/__init__.py (verify)
- Contains CallRecord, CandidateRule, MetalearnResult (per ml/__init__.py docstring)

**Recommended Action:** KEEP - Complete ml/ refactoring (related to P1-2)

---

### 7. ml/registry.py (177 lines)
**Location:** `ystar/governance/ml/registry.py`

**Import Check:**
```bash
grep -rn "ml.registry import\|ml_registry" ystar --include="*.py" | grep -v build
```
**Result:** 1 import found

**Status:** 🟢 PARTIALLY INTEGRATED

**Import References:**
1. `ystar/governance/ml_registry.py:5` - Canonical import comment (wrapper file exists)

**Quick Assessment:**
- Part of v0.41 ml/ refactoring
- Has wrapper file ml_registry.py
- Contains ConstraintRegistry, ManagedConstraint (per ml/__init__.py)

**Recommended Action:** KEEP - Active in refactoring plan

---

## Summary Matrix

| Module | Lines | Imports | Status | Recommendation |
|--------|-------|---------|--------|----------------|
| report_metrics.py | 295 | 0 | 🔴 Isolated | DELETE |
| metrics.py | 46 | 0 | 🔴 Isolated | DELETE |
| proposals.py | 79 | 0 | 🔴 Isolated | DELETE |
| constraints.py | 34 | 0* | 🟡 Name collision | DELETE |
| ml/loop.py | 289 | 2 | 🟢 Partial | KEEP |
| ml/records.py | 239 | 0** | 🟡 Refactoring | KEEP |
| ml/registry.py | 177 | 1 | 🟢 Partial | KEEP |

\* References found are to kernel.prefill, not this module  
\*\* Should be re-exported by ml/__init__.py (verify in P1-2 fix)

## Detailed Recommendations

### Immediate Deletion Candidates (454 lines total)
1. **report_metrics.py** (295 lines)
2. **metrics.py** (46 lines)
3. **proposals.py** (79 lines)
4. **constraints.py** (34 lines)

**Risk:** Very low - no active usage detected
**Impact:** Reduces codebase by 454 lines
**Testing:** Run full test suite to verify no hidden dependencies

### Keep for ml/ Refactoring (705 lines total)
5. **ml/loop.py** (289 lines) - Active
6. **ml/records.py** (239 lines) - Part of P1-2 refactoring
7. **ml/registry.py** (177 lines) - Active

**Action:** Complete P1-2 staged migration to properly integrate these modules

---

## Verification Steps

Before deletion, verify:

1. **Search for dynamic imports:**
```bash
grep -r "importlib\|__import__" ystar --include="*.py" | grep -E "report_metrics|metrics|proposals|constraints"
```

2. **Search for string references:**
```bash
grep -r "\"report_metrics\|'report_metrics" ystar --include="*.py"
# Repeat for other modules
```

3. **Check CLI commands:**
```bash
grep -r "report_metrics\|metrics\|proposals\|constraints" ystar/cli --include="*.py"
```

4. **Run full test suite:**
```bash
pytest tests/ -v --tb=short
```

---

## Execution Plan

### Phase A: Verification (30 minutes)
1. Run all verification checks above
2. Read first 50 lines of each deletion candidate
3. Verify no CLI command references
4. Confirm no test dependencies

### Phase B: Staged Deletion (30 minutes)
1. Delete constraints.py (34 lines, highest name collision risk)
2. Run tests → if pass, commit
3. Delete metrics.py (46 lines, smallest)
4. Run tests → if pass, commit
5. Delete proposals.py (79 lines)
6. Run tests → if pass, commit
7. Delete report_metrics.py (295 lines, largest)
8. Run tests → if pass, commit

### Phase C: ml/ Integration (covered by P1-2)
- Keep ml/loop.py, ml/records.py, ml/registry.py
- Complete when P1-2 staged migration finishes

---

## Risk Assessment

### Deletion Risk: LOW
- All 4 deletion candidates have zero imports
- No CLI commands reference them
- No test coverage found (suggests no usage)
- Staged deletion allows rollback per module

### False Positive Risk: MEDIUM
Potential hidden dependencies:
- Dynamic imports (importlib)
- String-based loading
- Experimental features
- Documentation examples

**Mitigation:** Full verification Phase A + staged commits

---

## Time Estimate

- **Phase A (Verification):** 30 minutes
- **Phase B (Deletion):** 30 minutes
- **Total:** 1 hour

**Savings:** Remove 454 lines of dead code

---

## Board Decision Required

Approve deletion of:
- [ ] constraints.py (34 lines)
- [ ] metrics.py (46 lines)
- [ ] proposals.py (79 lines)
- [ ] report_metrics.py (295 lines)

After verification passes in Phase A.

**Alternative:** Move to `ystar/_experimental/` instead of deletion (preserve for archaeology)

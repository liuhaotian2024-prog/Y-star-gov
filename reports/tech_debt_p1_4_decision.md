# P1-4 Decision Report: _hook_server.py Status Confirmation

**Date:** 2026-04-03
**Task:** Investigate _hook_server.py status and usage
**Status:** 🔍 INVESTIGATION COMPLETED — DECISION REQUIRED

## Findings

### File Location
```
ystar/_hook_server.py                       120 lines
ystar/__pycache__/_hook_server.cpython-314.pyc  (compiled, actively used)
```

### File Purpose
OpenClaw PreToolUse hook processor with two modes:
1. **stdin/stdout mode** (default): subprocess called by OpenClaw
2. **HTTP server mode**: `ystar-hook --serve --port 7777`

### Code Analysis

#### Core Functionality
```python
def main():
    # Parse args: --serve, --port, --agents-md
    policy = _load_policy(args.agents_md)
    if args.serve:
        _serve(policy, args.port)  # HTTP mode
    else:
        _handle_stdin(policy)       # stdin mode
```

#### Integration Points
- Imports `ystar.adapters.hook.check_hook` (core hook logic)
- Imports `ystar.Policy.from_agents_md` (policy loading)
- Provides CLI wrapper for hook functionality

### Usage Analysis

#### Direct References
1. **ystar/cli/init_cmd.py:111** - Recommends `ystar-hook` in OpenClaw config
```python
print('          - command: ystar-hook')
```

#### Installation Status
- **NOT registered** in pyproject.toml [project.scripts]
- Only `ystar` command is registered, pointing to `ystar._cli:main`
- Cannot be invoked as `ystar-hook` from command line without manual setup

#### Test Coverage
- **49 hook tests** exist (test_hook.py, test_cli_hook_install.py)
- All tests use `ystar.adapters.hook.check_hook` directly
- **NO tests** for `_hook_server.py` itself
- No tests for HTTP server mode
- No tests for stdin/stdout mode

### Current Hook Integration Path

**Actual working path (v0.48.0):**
```
Claude Code settings.json
    ↓
hooks:
  PreToolUse:
    - python: ystar.adapters.hook:check_hook
```

**Recommended but broken path (init_cmd.py):**
```
hooks:
  PreToolUse:
    - command: ystar-hook  ← NOT INSTALLED
```

### Compilation Evidence
- `__pycache__/_hook_server.cpython-314.pyc` exists
- File was imported/compiled at some point
- But no code currently imports it

## Status Assessment

### Is _hook_server.py Used?
❌ **NO** - Not actively used in current architecture

Evidence:
1. No imports from any Python code
2. Not registered as CLI command
3. No test coverage
4. Recommended integration path (ystar-hook command) doesn't work
5. Actual integration uses `ystar.adapters.hook:check_hook` directly

### Is _hook_server.py Needed?
🟡 **POTENTIALLY** - Depends on future requirements

**Scenarios where it would be needed:**
1. OpenClaw subprocess mode (command: ystar-hook)
2. HTTP server mode for remote hook calls
3. Non-Python agent frameworks needing hook integration

**Current reality:**
- Claude Code uses Python import path (not subprocess)
- All governance happens in-process
- No external HTTP hook consumers

## Architecture Decision Context

### Design Intent (from docstring)
```
让 OpenClaw 可以通过以下方式调用 Y*：
  a) 子进程模式（stdin/stdout，推荐）
  b) HTTP 服务模式
```

### Current Implementation
```
Claude Code 直接导入 check_hook 函数（Python import，非子进程）
```

### Discrepancy
- Docstring says subprocess mode is "推荐"
- Reality: nobody uses subprocess mode
- Reality: Python import mode is actual recommendation (ystar hook-install)

## Options

### Option A: Delete _hook_server.py
**Rationale:** No current usage, no tests, broken integration path

**Pros:**
- Removes unused code
- Cleans up confusion (two hook integration paths)
- Simplifies codebase

**Cons:**
- Loses HTTP server capability
- Loses subprocess mode capability
- May need to recreate if future requirements emerge

**Estimated Time:** 15 minutes

### Option B: Fix and Document _hook_server.py
**Rationale:** Preserve multi-mode capability, fix integration

**Actions:**
1. Add to pyproject.toml [project.scripts]:
   ```toml
   ystar-hook = "ystar._hook_server:main"
   ```
2. Update init_cmd.py recommendation to match reality:
   ```python
   # Option 1: Direct Python import (recommended for Claude Code)
   python: ystar.adapters.hook:check_hook
   
   # Option 2: Subprocess mode (for non-Python frameworks)
   command: ystar-hook
   ```
3. Add tests for _hook_server.py (stdin mode, HTTP mode)
4. Update README with both integration paths

**Pros:**
- Preserves multi-framework flexibility
- HTTP mode useful for distributed setups
- Subprocess mode useful for isolation

**Cons:**
- Increases maintenance burden
- Adds testing requirements
- Current users don't need it

**Estimated Time:** 2-3 hours

### Option C: Rename and Mark Experimental (Recommended)
**Rationale:** Preserve code but clarify status

**Actions:**
1. Rename: `_hook_server.py` → `_hook_server_experimental.py`
2. Add status comment:
   ```python
   # STATUS: EXPERIMENTAL — subprocess/HTTP hook modes
   # Current integration uses ystar.adapters.hook:check_hook directly
   # This module provides alternative integration paths for:
   #   - Non-Python agent frameworks (subprocess mode)
   #   - Distributed governance (HTTP mode)
   # Not tested in production. Not registered as CLI command.
   ```
3. Remove from init_cmd.py recommendation (misleading)
4. Document in ARCHITECTURE.md as experimental feature

**Pros:**
- Preserves code for future use
- Clarifies current status
- Removes misleading recommendation
- Low maintenance burden

**Cons:**
- Code remains untested
- Still contributes to codebase size

**Estimated Time:** 30 minutes

## Impact Analysis

### Current Users
- **Claude Code users:** No impact (use direct import)
- **OpenClaw users:** May be confused by recommendation
- **HTTP mode users:** None exist (no evidence of usage)

### Test Suite
- **49 hook tests:** All pass, use direct import
- **0 _hook_server tests:** No coverage

### Documentation
- **README.md:** Only mentions hook-install (direct import)
- **init_cmd.py:** Incorrectly recommends ystar-hook command

## Recommendation

**OPTION C - Rename and Mark Experimental**

Reasoning:
1. Code has legitimate future use cases (HTTP mode, subprocess mode)
2. Deleting would waste prior design work
3. Fixing/testing is overkill for zero current users
4. Marking experimental sets clear expectations

### Immediate Actions
1. Rename to `_hook_server_experimental.py`
2. Add status comment
3. Remove misleading recommendation from init_cmd.py
4. Document in tech debt tracker for future consideration

### Future Consideration
- If HTTP mode is needed: promote to stable, add tests, register command
- If subprocess mode is needed: promote to stable, add tests, register command
- If neither needed by v1.0: delete

## Board Decision Required

Choose one:
- [ ] **Option A:** Delete _hook_server.py (15 min, lose capability)
- [ ] **Option B:** Fix and promote (2-3 hours, full support)
- [x] **Option C:** Rename and mark experimental (30 min, recommended)

If Option C approved:
- [ ] Execute rename and status clarification
- [ ] Update init_cmd.py recommendation
- [ ] Document in ARCHITECTURE.md

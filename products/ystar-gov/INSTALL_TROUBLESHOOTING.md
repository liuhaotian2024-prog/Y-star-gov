# Y*gov Installation Troubleshooting Guide

## Quick Start (One Command)

```bash
pip install ystar
ystar doctor
```

## Common Issues and Solutions

### Issue 1: "No module named ystar.__main__"

**Symptom:**
```bash
python -m ystar version
# Error: No module named ystar.__main__
```

**Root Cause:** You're using an old version of Y*gov (< 0.41.1) that didn't include `__main__.py`.

**Solution:**
```bash
# Update to latest version
pip install --upgrade ystar

# Or use the script entrypoint instead
ystar version  # This works on all versions
```

### Issue 2: "ystar: command not found"

**Symptom:**
```bash
ystar version
# bash: ystar: command not found
```

**Root Cause:** The package was installed in a location not in your PATH.

**Solution:**
```bash
# Option 1: Use python -m ystar instead
python -m ystar version

# Option 2: Find where pip installed it
pip show ystar
# Look at the "Location" field, the script is in ../Scripts/ystar (Windows) or ../bin/ystar (Unix)

# Option 3: Reinstall with --user flag
pip install --user ystar
# Then add ~/.local/bin to PATH (Unix) or %APPDATA%\Python\Scripts (Windows)
```

### Issue 3: Import errors for core modules

**Symptom:**
```python
from ystar import Policy
# ImportError: cannot import name 'Policy' from 'ystar'
```

**Root Cause:** Package installation is incomplete or corrupted.

**Solution:**
```bash
# Uninstall and reinstall
pip uninstall ystar -y
pip install ystar

# Verify installation
python -c "from ystar import Policy, check, IntentContract; print('OK')"
```

### Issue 4: Version mismatch

**Symptom:**
```bash
ystar version
# ystar 0.40.0
```

**Root Cause:** Multiple versions installed or pip cache issue.

**Solution:**
```bash
# Force reinstall
pip install --force-reinstall --no-cache-dir ystar

# Verify version
ystar version
python -c "import ystar; print(ystar.__version__)"
```

### Issue 5: Windows path issues with hooks

**Symptom:**
Hook installation fails or hook doesn't run on Windows Git Bash.

**Root Cause:** Backslash path separator conflicts with Git Bash.

**Solution:**
The v0.41.1 release fixes this automatically by converting backslashes to forward slashes. Update to latest:
```bash
pip install --upgrade ystar
ystar hook-install
```

## Verification Checklist

Run these commands to verify your installation:

```bash
# 1. Check version
ystar version

# 2. Test module execution
python -m ystar version

# 3. Test imports
python -c "from ystar import Policy, check, IntentContract, enforce, OmissionEngine; print('OK')"

# 4. Run doctor
ystar doctor

# 5. Test hook (if installed)
# Should show Y* hook status
ystar doctor | grep -A 2 "Hook Registration"
```

All commands should complete without errors.

## Running the Official Test Suite

If you cloned the repository, you can run the full test suite:

```bash
cd /path/to/Y-star-gov
pip install pytest
pytest tests/ -v

# Expected output: 141 passed
```

## Automated Installation Test

We provide an automated test script that verifies installation in a clean virtual environment:

```bash
cd /path/to/Y-star-gov
bash products/ystar-gov/install_test.sh
```

This script:
- Creates a fresh venv
- Installs the wheel
- Tests all imports
- Tests both CLI invocation methods (script and module)
- Cleans up

## Manual Installation from Wheel

If pip install fails, you can manually install from the wheel file:

```bash
# Download or build the wheel
python -m build  # If building from source

# Install the wheel
pip install dist/ystar-0.41.1-py3-none-any.whl
```

## Installation from Source

```bash
# Clone the repository
git clone https://github.com/liuhaotian2024-prog/Y-star-gov.git
cd Y-star-gov

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .

# Or build and install wheel
python -m build
pip install dist/ystar-0.41.1-py3-none-any.whl
```

## Minimum Requirements

- Python >= 3.11
- pip >= 20.0
- No external dependencies (Y*gov is zero-dependency)

## Platform-Specific Notes

### Windows
- Use Git Bash or PowerShell (not CMD)
- Hook installation automatically handles path conversion

### macOS
- Settings path: `~/Library/Application Support/Claude/settings.json`
- Python path: Check `which python3`

### Linux
- Settings path: `~/.config/openclaw/openclaw.json` or `~/.claude/settings.json`
- Ensure `~/.local/bin` is in PATH for script entrypoints

## Getting Help

If you've tried all solutions above and still have issues:

1. Run `ystar doctor` and save the output
2. Check Python version: `python --version`
3. Check pip version: `pip --version`
4. Open an issue at: https://github.com/liuhaotian2024-prog/Y-star-gov/issues

Include:
- OS and version
- Python version
- Output of `ystar doctor`
- Full error message

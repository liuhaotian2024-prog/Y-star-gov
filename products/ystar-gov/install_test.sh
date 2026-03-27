#!/bin/bash
# Y*gov Installation Verification Test
# Tests that the wheel installs cleanly in a fresh Python virtual environment

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo "=== Y*gov Installation Test ==="
echo ""

# Check if wheel exists
WHEEL_PATH="dist/ystar-0.41.1-py3-none-any.whl"
if [ ! -f "$WHEEL_PATH" ]; then
    echo "ERROR: Wheel not found at $WHEEL_PATH"
    echo "Run: python -m build"
    exit 1
fi

# Create fresh venv
echo "[1/5] Creating fresh virtual environment..."
rm -rf test_install_venv
python -m venv test_install_venv

# Activate (cross-platform)
if [ -f test_install_venv/Scripts/activate ]; then
    # Windows Git Bash
    source test_install_venv/Scripts/activate
    PYTHON="test_install_venv/Scripts/python"
    YSTAR="test_install_venv/Scripts/ystar"
else
    # Unix
    source test_install_venv/bin/activate
    PYTHON="test_install_venv/bin/python"
    YSTAR="test_install_venv/bin/ystar"
fi

# Install wheel
echo "[2/5] Installing wheel..."
pip install -q "$WHEEL_PATH"

# Test imports
echo "[3/5] Testing imports..."
$PYTHON -c "from ystar import Policy; print('  OK: Policy import')"
$PYTHON -c "from ystar import check, IntentContract; print('  OK: check, IntentContract import')"
$PYTHON -c "from ystar import enforce, OmissionEngine; print('  OK: enforce, OmissionEngine import')"

# Test CLI via script entrypoint
echo "[4/5] Testing CLI via script entrypoint (ystar)..."
VERSION=$($YSTAR version 2>&1)
echo "  $VERSION"
if [[ ! "$VERSION" =~ "ystar 0.41" ]]; then
    echo "ERROR: CLI script entrypoint failed"
    exit 1
fi

# Test CLI via module execution
echo "[5/5] Testing CLI via module execution (python -m ystar)..."
VERSION_M=$($PYTHON -m ystar version 2>&1)
echo "  $VERSION_M"
if [[ ! "$VERSION_M" =~ "ystar 0.41" ]]; then
    echo "ERROR: CLI module execution failed"
    exit 1
fi

# Cleanup
rm -rf test_install_venv

echo ""
echo "SUCCESS: All installation tests passed"
echo ""
echo "Verified:"
echo "  - Wheel installs without errors"
echo "  - Core imports work (Policy, check, IntentContract, enforce, OmissionEngine)"
echo "  - CLI works via 'ystar' script"
echo "  - CLI works via 'python -m ystar'"
echo ""

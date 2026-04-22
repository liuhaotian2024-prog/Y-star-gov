#!/usr/bin/env bash
# test_clean_install_repro.sh — Phase C2: Clean-machine install reproduction
# Purpose: Verify that a fresh git clone + pip install + ystar doctor succeeds.
# NOTE: This runs in the local dev env as "clean-enough" approximation.
#       True clean-machine would require Docker or a fresh VM.
set -euo pipefail

CLONE_DIR="/tmp/ystar-clean-install-test-$$"
VENV_DIR="$CLONE_DIR/.venv"
REPO_URL="https://github.com/liuhaotian2024-prog/Y-star-gov.git"
TRANSCRIPT="/tmp/ystar-install-transcript-$$.log"
touch "$TRANSCRIPT"

cleanup() {
    echo "[CLEANUP] Removing $CLONE_DIR"
    rm -rf "$CLONE_DIR"
}
trap cleanup EXIT

echo "=========================================="
echo "Y*gov Clean Install Reproduction Test"
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=========================================="
echo ""

# Step 1: Clone
echo "[STEP 1/5] git clone $REPO_URL -> $CLONE_DIR"
git clone --depth 1 "$REPO_URL" "$CLONE_DIR" 2>&1 | tee -a "$TRANSCRIPT"
echo "RESULT: clone $([ -d "$CLONE_DIR/ystar" ] && echo 'OK' || echo 'FAIL')"
echo ""

# Step 2: Create venv + install
echo "[STEP 2/5] Creating virtualenv + pip install ."
python3 -m venv "$VENV_DIR" 2>&1 | tee -a "$TRANSCRIPT"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip 2>&1 | tail -1 | tee -a "$TRANSCRIPT"
echo "Installing Y*gov from source..."
pip install "$CLONE_DIR" 2>&1 | tee -a "$TRANSCRIPT"
INSTALL_RC=$?
echo "RESULT: pip install exit code $INSTALL_RC"
echo ""

# Step 3: Verify ystar CLI is importable
echo "[STEP 3/5] Verify ystar package is importable"
python3 -c "import ystar; print('ystar version:', getattr(ystar, '__version__', 'unknown'))" 2>&1 | tee -a "$TRANSCRIPT"
IMPORT_RC=$?
echo "RESULT: import exit code $IMPORT_RC"
echo ""

# Step 4: ystar doctor
echo "[STEP 4/5] Running ystar doctor"
if command -v ystar &>/dev/null; then
    ystar doctor 2>&1 | tee -a "$TRANSCRIPT"
    DOCTOR_RC=$?
else
    echo "ystar CLI not found in PATH after install"
    # Try module invocation
    python3 -m ystar doctor 2>&1 | tee -a "$TRANSCRIPT" || true
    DOCTOR_RC=1
fi
echo "RESULT: doctor exit code ${DOCTOR_RC:-N/A}"
echo ""

# Step 5: Minimal smoke test — import core modules
echo "[STEP 5/5] Smoke test: import core governance modules"
python3 -c "
from ystar.kernel.cieu_store import CIEUStore
from ystar.governance.boundary_enforcer import BoundaryEnforcer
from ystar.governance.omission_engine import OmissionEngine
print('Core modules import: OK')
print('CIEUStore:', CIEUStore)
print('BoundaryEnforcer:', BoundaryEnforcer)
print('OmissionEngine:', OmissionEngine)
" 2>&1 | tee -a "$TRANSCRIPT"
SMOKE_RC=$?
echo "RESULT: smoke test exit code $SMOKE_RC"
echo ""

# Summary
echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo "  Clone:        $([ -d "$CLONE_DIR/ystar" ] && echo 'PASS' || echo 'FAIL')"
echo "  pip install:  $([ ${INSTALL_RC:-1} -eq 0 ] && echo 'PASS' || echo 'FAIL')"
echo "  import ystar: $([ ${IMPORT_RC:-1} -eq 0 ] && echo 'PASS' || echo 'FAIL')"
echo "  ystar doctor: $([ ${DOCTOR_RC:-1} -eq 0 ] && echo 'PASS' || echo 'FAIL')"
echo "  smoke test:   $([ ${SMOKE_RC:-1} -eq 0 ] && echo 'PASS' || echo 'FAIL')"
echo ""
echo "Transcript saved to: $TRANSCRIPT"
echo "=========================================="

deactivate 2>/dev/null || true

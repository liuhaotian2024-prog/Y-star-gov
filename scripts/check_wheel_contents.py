#!/usr/bin/env python3
"""Pre-publish packaging check - prevents Claude Code style leaks."""
import sys
import zipfile
import glob
from pathlib import Path

def check_wheel_contents():
    wheels = glob.glob('dist/*.whl')
    if not wheels:
        print("ERROR: No wheel found in dist/")
        return 1

    wheel_path = wheels[0]
    print(f"Checking wheel: {wheel_path}")

    with zipfile.ZipFile(wheel_path) as z:
        files = z.namelist()

        # Forbidden patterns (debug, test, cache files)
        forbidden_patterns = [
            '.map',           # Source maps
            'test_',          # Test files
            '__pycache__',    # Python cache
            '.pyc',           # Compiled Python
            'scripts/',       # Internal scripts
            '.git',           # Git metadata
            'debug',          # Debug files
            '.log',           # Log files
        ]

        bad_files = []
        for f in files:
            for pattern in forbidden_patterns:
                if pattern in f.lower():
                    bad_files.append(f)
                    break

        if bad_files:
            print("\n❌ PACKAGING ERROR - Forbidden files in wheel:")
            for f in bad_files:
                print(f"  - {f}")
            return 1

        # Verify expected files are present
        expected_patterns = ['ystar/', '__init__.py']
        found = {p: any(p in f for f in files) for p in expected_patterns}

        if not all(found.values()):
            print(f"\n⚠️  WARNING - Expected files missing:")
            for p, present in found.items():
                if not present:
                    print(f"  - {p}")

        print(f"\n✅ Package clean: {len(files)} files")
        print(f"   Main package files: {len([f for f in files if 'ystar/' in f])}")
        return 0

if __name__ == "__main__":
    sys.exit(check_wheel_contents())

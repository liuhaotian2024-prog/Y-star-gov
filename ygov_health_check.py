#!/usr/bin/env python3
"""
Y*gov Health Check - Comprehensive Bug Audit
Based on K9Audit patterns and security best practices
"""

import ast
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

class HealthCheckReport:
    def __init__(self):
        self.critical = []
        self.medium = []
        self.low = []
        self.info = []

    def add(self, severity: str, category: str, message: str, file_path: str = "", line_no: int = 0):
        entry = {
            "category": category,
            "message": message,
            "file": file_path,
            "line": line_no
        }
        if severity == "CRITICAL":
            self.critical.append(entry)
        elif severity == "MEDIUM":
            self.medium.append(entry)
        elif severity == "LOW":
            self.low.append(entry)
        else:
            self.info.append(entry)

    def print_report(self):
        print("\n" + "="*80)
        print("Y*GOV HEALTH CHECK REPORT")
        print("="*80)

        if self.critical:
            print(f"\n[CRITICAL] {len(self.critical)} issues found:")
            for i, issue in enumerate(self.critical, 1):
                print(f"\n{i}. [{issue['category']}]")
                print(f"   {issue['message']}")
                if issue['file']:
                    print(f"   File: {issue['file']}")
                if issue['line']:
                    print(f"   Line: {issue['line']}")

        if self.medium:
            print(f"\n[MEDIUM] {len(self.medium)} issues found:")
            for i, issue in enumerate(self.medium, 1):
                print(f"\n{i}. [{issue['category']}]")
                print(f"   {issue['message']}")
                if issue['file']:
                    print(f"   File: {issue['file']}")
                if issue['line']:
                    print(f"   Line: {issue['line']}")

        if self.low:
            print(f"\n[LOW] {len(self.low)} issues found:")
            for i, issue in enumerate(self.low, 1):
                print(f"\n{i}. [{issue['category']}]")
                print(f"   {issue['message']}")
                if issue['file']:
                    print(f"   File: {issue['file']}")

        print("\n" + "="*80)
        print(f"SUMMARY: {len(self.critical)} critical, {len(self.medium)} medium, {len(self.low)} low")
        print("="*80)

def find_python_files(root_dir: Path) -> List[Path]:
    """Find all Python files in the source directory, excluding build/"""
    files = []
    for path in root_dir.rglob("*.py"):
        if "build" not in path.parts and "__pycache__" not in path.parts:
            files.append(path)
    return files

def check_dead_code(root_dir: Path, report: HealthCheckReport):
    """Check for dead code and orphaned files"""
    print("\n[1/7] Checking for dead code and orphaned files...")

    ystar_dir = root_dir / "ystar"
    files = find_python_files(ystar_dir)

    # Build import graph
    imports = defaultdict(set)
    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports[file_path].add(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports[file_path].add(node.module)
        except Exception as e:
            report.add("MEDIUM", "PARSE_ERROR", f"Cannot parse file: {e}", str(file_path))

    # Check for duplicate modules (root vs subdirectory)
    module_locations = defaultdict(list)
    for file_path in files:
        module_name = file_path.stem
        if module_name != "__init__":
            module_locations[module_name].append(file_path)

    for module, locations in module_locations.items():
        if len(locations) > 1:
            # Check if one is at root and one in subdirectory
            root_file = None
            subdir_file = None
            for loc in locations:
                if loc.parent == ystar_dir:
                    root_file = loc
                else:
                    subdir_file = loc

            if root_file and subdir_file:
                report.add("MEDIUM", "DUPLICATE_MODULE",
                          f"Module '{module}' exists in both root and subdirectory (likely shim remnant)",
                          f"Root: {root_file.relative_to(root_dir)}, Subdir: {subdir_file.relative_to(root_dir)}")

def check_broken_imports(root_dir: Path, report: HealthCheckReport):
    """Check for broken imports and missing references"""
    print("\n[2/7] Checking for broken imports...")

    ystar_dir = root_dir / "ystar"
    files = find_python_files(ystar_dir)

    for file_path in files:
        try:
            # Get the module path relative to the package root
            rel_path = file_path.relative_to(root_dir)
            module_parts = list(rel_path.parts[:-1]) + [rel_path.stem]
            if module_parts[-1] == "__init__":
                module_parts = module_parts[:-1]
            module_name = ".".join(module_parts)

            # Try to import
            result = subprocess.run(
                [sys.executable, "-c", f"import {module_name}"],
                cwd=str(root_dir),
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip().split('\n')[-1] if result.stderr else "Unknown error"
                if "ModuleNotFoundError" in error_msg or "ImportError" in error_msg:
                    report.add("CRITICAL", "BROKEN_IMPORT",
                              f"Cannot import module: {error_msg}",
                              str(file_path.relative_to(root_dir)))
                elif "NameError" in error_msg or "AttributeError" in error_msg:
                    report.add("CRITICAL", "BROKEN_REFERENCE",
                              f"Broken reference in module: {error_msg}",
                              str(file_path.relative_to(root_dir)))
        except subprocess.TimeoutExpired:
            report.add("MEDIUM", "IMPORT_TIMEOUT",
                      "Import took too long (possible circular dependency)",
                      str(file_path.relative_to(root_dir)))
        except Exception as e:
            report.add("LOW", "IMPORT_CHECK_ERROR",
                      f"Could not check import: {e}",
                      str(file_path.relative_to(root_dir)))

def check_api_signatures(root_dir: Path, report: HealthCheckReport):
    """Check for API signature mismatches"""
    print("\n[3/7] Checking API signatures...")

    ystar_dir = root_dir / "ystar"
    files = find_python_files(ystar_dir)

    # Known signature issues from previous audits
    known_issues = {
        "OmissionEngine.__init__": ["store"],
        "ConstraintBudget.__init__": ["agent_id"],
    }

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(file_path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        class_name = node.name

                        # Find __init__ method
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                                args = [arg.arg for arg in item.args.args if arg.arg != "self"]

                                # Check against known issues
                                full_name = f"{class_name}.__init__"
                                if full_name in known_issues:
                                    required_params = known_issues[full_name]
                                    missing_params = [p for p in required_params if p not in args]
                                    if missing_params:
                                        report.add("CRITICAL", "SIGNATURE_MISMATCH",
                                                  f"{full_name} missing required parameters: {missing_params}",
                                                  str(file_path.relative_to(root_dir)),
                                                  item.lineno)
        except Exception as e:
            report.add("LOW", "SIGNATURE_CHECK_ERROR",
                      f"Could not check signatures: {e}",
                      str(file_path.relative_to(root_dir)))

def check_silent_exceptions(root_dir: Path, report: HealthCheckReport):
    """Check for silent exception swallowing"""
    print("\n[4/7] Checking for silent exception swallowing...")

    ystar_dir = root_dir / "ystar"
    files = find_python_files(ystar_dir)

    patterns = [
        (r"except\s+Exception\s*:\s*pass", "except Exception: pass"),
        (r"except\s*:\s*pass", "except: pass"),
        (r"except\s+\w+\s*:\s*pass", "except SomeError: pass (too broad)"),
    ]

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line_no, line in enumerate(lines, 1):
                for pattern, description in patterns:
                    if re.search(pattern, line):
                        report.add("MEDIUM", "SILENT_EXCEPTION",
                                  f"Silent exception swallowing: {description}",
                                  str(file_path.relative_to(root_dir)),
                                  line_no)
        except Exception as e:
            report.add("LOW", "EXCEPTION_CHECK_ERROR",
                      f"Could not check exceptions: {e}",
                      str(file_path.relative_to(root_dir)))

def check_hardcoded_paths(root_dir: Path, report: HealthCheckReport):
    """Check for hardcoded paths and credentials"""
    print("\n[5/7] Checking for hardcoded paths and credentials...")

    ystar_dir = root_dir / "ystar"
    files = find_python_files(ystar_dir)

    patterns = [
        (r"(?:password|secret|api_key|token)\s*=\s*['\"][^'\"]+['\"]", "HARDCODED_CREDENTIAL"),
        (r"/home/\w+", "HARDCODED_HOME_PATH"),
        (r"C:\\Users\\", "HARDCODED_WINDOWS_PATH"),
        (r"localhost:\d+", "HARDCODED_LOCALHOST"),
        (r"http://(?!example\.com)", "HARDCODED_HTTP_URL"),
    ]

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            for line_no, line in enumerate(lines, 1):
                # Skip comments
                if line.strip().startswith("#"):
                    continue

                for pattern, issue_type in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        report.add("MEDIUM", issue_type,
                                  f"Found: {line.strip()[:80]}",
                                  str(file_path.relative_to(root_dir)),
                                  line_no)
        except Exception as e:
            report.add("LOW", "HARDCODE_CHECK_ERROR",
                      f"Could not check for hardcoded values: {e}",
                      str(file_path.relative_to(root_dir)))

def check_test_consistency(root_dir: Path, report: HealthCheckReport):
    """Check test file consistency"""
    print("\n[6/7] Checking test consistency...")

    # Check if tests can be collected
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=str(root_dir),
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        errors = result.stdout + result.stderr
        report.add("CRITICAL", "TEST_COLLECTION_FAILED",
                  f"pytest collection failed: {errors[:500]}",
                  "tests/")

    # Check for common test issues
    test_dir = root_dir / "tests"
    if test_dir.exists():
        test_files = list(test_dir.glob("test_*.py"))

        for test_file in test_files:
            try:
                with open(test_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Check for proper imports
                if "import pytest" not in content and "@pytest" in content:
                    report.add("MEDIUM", "MISSING_PYTEST_IMPORT",
                              "File uses pytest decorators but doesn't import pytest",
                              str(test_file.relative_to(root_dir)))

                # Check for test functions
                if not re.search(r"def test_\w+", content):
                    report.add("LOW", "NO_TEST_FUNCTIONS",
                              "Test file contains no test functions",
                              str(test_file.relative_to(root_dir)))
            except Exception as e:
                report.add("LOW", "TEST_CHECK_ERROR",
                          f"Could not check test file: {e}",
                          str(test_file.relative_to(root_dir)))

def check_readme_commands(root_dir: Path, report: HealthCheckReport):
    """Check if README commands are valid"""
    print("\n[7/7] Checking README commands...")

    readme_files = list(root_dir.glob("README*.md")) + list(root_dir.glob("readme*.md"))

    for readme in readme_files:
        try:
            with open(readme, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract code blocks
            code_blocks = re.findall(r"```(?:bash|shell|sh)?\n(.*?)```", content, re.DOTALL)

            for block in code_blocks:
                lines = block.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith("ystar "):
                        command = line.split()[1] if len(line.split()) > 1 else ""
                        # We'll check if the command exists in CLI
                        report.add("INFO", "README_COMMAND",
                                  f"Found ystar command: {line}",
                                  str(readme.relative_to(root_dir)))
        except Exception as e:
            report.add("LOW", "README_CHECK_ERROR",
                      f"Could not check README: {e}",
                      str(readme.relative_to(root_dir)))

def main():
    root_dir = Path(__file__).parent
    print(f"Running health check on: {root_dir}")

    report = HealthCheckReport()

    try:
        check_dead_code(root_dir, report)
        check_broken_imports(root_dir, report)
        check_api_signatures(root_dir, report)
        check_silent_exceptions(root_dir, report)
        check_hardcoded_paths(root_dir, report)
        check_test_consistency(root_dir, report)
        check_readme_commands(root_dir, report)
    except KeyboardInterrupt:
        print("\n\nHealth check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFATAL ERROR during health check: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    report.print_report()

    # Return exit code based on severity
    if report.critical:
        return 2
    elif report.medium:
        return 1
    else:
        return 0

if __name__ == "__main__":
    sys.exit(main())

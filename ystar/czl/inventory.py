"""
ystar.czl.inventory — v4.0 T1 workspace + system inventory scanner.

Pure-scan subsystem. Reports facts the model can act on:
  - files in the workspace (filtered: .py / .toml / .json / .ini / .md / .txt)
  - interpreters available on the host system (via shutil.which)
  - source code interfaces extracted from Python AST (functions + classes
    with docstring first-line)

No recommendations, no scenario-specific bias. Caller decides how the
model uses this. Used by render_environment_inventory in scenarios/base.

Founder principle compliance:
  - No Trampoline-preset tool: interpreter list is shutil.which() over a
    well-known interpreter set; absence is a fact, not a default.
  - No magic business constants: only physical-resource limits (file
    count cap 200 per dir traversal, AST parse on .py only).
"""
from __future__ import annotations

import ast
import os
import shutil
from typing import Any, Dict, List, Optional


# Interpreters / build tools the inventory probes for. Absence is recorded
# as absence — there's no "default interpreter" Trampoline insists on.
_KNOWN_INTERPRETERS: List[str] = [
    # Python
    "python3", "python3.11", "python3.12", "python3.10", "python3.9", "python",
    # JS / TS
    "node", "deno", "bun", "npm", "yarn", "pnpm",
    # System languages
    "rustc", "cargo", "go", "java", "gcc", "g++", "clang", "make",
    # Other interpreters
    "ruby", "perl", "lua", "bash", "sh", "zsh",
    # Test runners (often on PATH separately from python interpreter)
    "pytest", "mypy", "ruff", "coverage", "node_modules/.bin/jest",
    # Containers / orchestration (model may use to inspect environment)
    "docker", "podman", "git",
]


# File extensions we report. Other files are skipped to keep the listing
# focused and the prompt size bounded.
_REPORTED_EXTENSIONS = (".py", ".toml", ".json", ".yaml", ".yml", ".ini", ".cfg",
                        ".md", ".txt", ".sh")


# Caps (physical resource bounds, not business logic constants)
_MAX_FILES_PER_SCAN = 200
_MAX_SOURCE_FILES_AST = 50  # only parse first N .py files


class WorkspaceInventory:
    """Read-only scanner. Caller invokes scan() once at iter 0 (or per
    iter for refresh) and feeds the result into render_environment_inventory.
    """

    @staticmethod
    def scan(workspace_dir: str) -> Dict[str, Any]:
        return {
            "files": WorkspaceInventory._scan_files(workspace_dir),
            "interpreters": WorkspaceInventory._scan_interpreters(),
            "source_interfaces": WorkspaceInventory._scan_source_interfaces(workspace_dir),
        }

    # ---------------------------------------------------------------- files

    @staticmethod
    def _scan_files(workspace_dir: str) -> List[str]:
        if not os.path.isdir(workspace_dir):
            return []
        out: List[str] = []
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for f in files:
                if f.startswith("."):
                    continue
                _, ext = os.path.splitext(f)
                if ext.lower() not in _REPORTED_EXTENSIONS:
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, workspace_dir)
                out.append(rel)
                if len(out) >= _MAX_FILES_PER_SCAN:
                    return out
        return sorted(out)

    # ---------------------------------------------------------- interpreters

    @staticmethod
    def _scan_interpreters() -> Dict[str, str]:
        out: Dict[str, str] = {}
        for cmd in _KNOWN_INTERPRETERS:
            path = shutil.which(cmd)
            if path:
                out[cmd] = path
        return out

    # ----------------------------------------------------- source interfaces

    @staticmethod
    def _scan_source_interfaces(workspace_dir: str) -> Dict[str, Any]:
        """AST-parse first _MAX_SOURCE_FILES_AST .py files in workspace.
        For each: list of {name, signature, docstring_first_line} per
        function, and {name} per class.
        """
        out: Dict[str, Any] = {}
        parsed = 0
        if not os.path.isdir(workspace_dir):
            return out
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for f in sorted(files):
                if not f.endswith(".py"):
                    continue
                # Skip test_*.py from interface index — they're not the
                # surface the model is testing against.
                if f.startswith("test_"):
                    continue
                if parsed >= _MAX_SOURCE_FILES_AST:
                    return out
                full = os.path.join(root, f)
                rel = os.path.relpath(full, workspace_dir)
                try:
                    src = open(full, "r", encoding="utf-8").read()
                    tree = ast.parse(src, filename=full)
                except (OSError, SyntaxError) as e:
                    out[rel] = {"error": str(e)}
                    parsed += 1
                    continue
                functions: List[Dict[str, str]] = []
                classes: List[Dict[str, str]] = []
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions.append(_describe_func(node))
                    elif isinstance(node, ast.ClassDef):
                        classes.append({"name": node.name})
                out[rel] = {"functions": functions, "classes": classes}
                parsed += 1
        return out


def _describe_func(node: ast.FunctionDef) -> Dict[str, str]:
    """Render a function's signature + docstring first line, no body."""
    try:
        # Build parameter list from AST args directly
        params: List[str] = []
        # positional
        for a in node.args.args:
            annot = ast.unparse(a.annotation) if a.annotation else None
            if annot:
                params.append(f"{a.arg}: {annot}")
            else:
                params.append(a.arg)
        if node.args.vararg:
            params.append(f"*{node.args.vararg.arg}")
        for a in node.args.kwonlyargs:
            annot = ast.unparse(a.annotation) if a.annotation else None
            params.append(f"{a.arg}: {annot}" if annot else a.arg)
        if node.args.kwarg:
            params.append(f"**{node.args.kwarg.arg}")
        ret = ast.unparse(node.returns) if node.returns else None
        sig = f"({', '.join(params)})" + (f" -> {ret}" if ret else "")
    except Exception:
        sig = "(?)"
    doc = ast.get_docstring(node)
    doc_first = doc.split("\n", 1)[0].strip() if doc else ""
    return {"name": node.name, "signature": sig, "docstring_first_line": doc_first}

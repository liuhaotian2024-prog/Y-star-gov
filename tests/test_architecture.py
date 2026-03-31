"""
tests.test_architecture -- Structural and Layer Boundary Tests

Items 10, 13, 14: Verify architectural invariants.

Tests:
- Item 10: Layer dependency checks (import boundaries)
- Item 13: Structure existence tests
- Item 14: Role boundary tests (method-level)
"""
import ast
import os
import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_YSTAR_ROOT = os.path.join(_PROJECT_ROOT, "ystar")


def _get_imports(filepath: str) -> list:
    """Extract all import module names from a Python file using AST."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _get_class_methods(filepath: str, class_name: str) -> list:
    """Extract method names from a class in a Python file."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# Item 10: Layer Dependency Checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestLayerDependencies:
    """Verify that layer import boundaries are respected."""

    def test_path_a_does_not_import_path_b(self):
        """path_a/meta_agent.py must not import from path_b."""
        imports = _get_imports(os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py"))
        for imp in imports:
            assert "path_b" not in imp, f"Path A imports from Path B: {imp}"

    def test_path_b_does_not_import_path_a(self):
        """path_b/path_b_agent.py must not import from path_a."""
        imports = _get_imports(os.path.join(_YSTAR_ROOT, "path_b", "path_b_agent.py"))
        for imp in imports:
            assert "path_a" not in imp, f"Path B imports from Path A: {imp}"

    def test_path_b_external_loop_does_not_import_path_a(self):
        """path_b/external_governance_loop.py must not import from path_a."""
        imports = _get_imports(
            os.path.join(_YSTAR_ROOT, "path_b", "external_governance_loop.py")
        )
        for imp in imports:
            assert "path_a" not in imp, f"Path B external loop imports from Path A: {imp}"

    def test_experience_bridge_does_not_import_path_a(self):
        """experience_bridge.py (Bridge layer) must not import from path_a."""
        imports = _get_imports(
            os.path.join(_YSTAR_ROOT, "governance", "experience_bridge.py")
        )
        for imp in imports:
            assert "path_a" not in imp, f"Bridge imports from Path A: {imp}"

    def test_intent_compilation_does_not_import_path_a(self):
        """Intent Compilation modules must not import from path_a."""
        ic_modules = [
            os.path.join(_YSTAR_ROOT, "kernel", "nl_to_contract.py"),
            os.path.join(_YSTAR_ROOT, "kernel", "prefill.py"),
            os.path.join(_YSTAR_ROOT, "governance", "constraints.py"),
            os.path.join(_YSTAR_ROOT, "governance", "proposals.py"),
            os.path.join(_YSTAR_ROOT, "governance", "rule_advisor.py"),
        ]
        for mod_path in ic_modules:
            imports = _get_imports(mod_path)
            for imp in imports:
                assert "path_a" not in imp, (
                    f"Intent Compilation module {mod_path} imports from path_a: {imp}"
                )

    def test_intent_compilation_does_not_import_path_b(self):
        """Intent Compilation modules must not import from path_b."""
        ic_modules = [
            os.path.join(_YSTAR_ROOT, "kernel", "nl_to_contract.py"),
            os.path.join(_YSTAR_ROOT, "kernel", "prefill.py"),
            os.path.join(_YSTAR_ROOT, "governance", "constraints.py"),
            os.path.join(_YSTAR_ROOT, "governance", "proposals.py"),
            os.path.join(_YSTAR_ROOT, "governance", "rule_advisor.py"),
        ]
        for mod_path in ic_modules:
            imports = _get_imports(mod_path)
            for imp in imports:
                assert "path_b" not in imp, (
                    f"Intent Compilation module {mod_path} imports from path_b: {imp}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Item 13: Structure Existence Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructureExistence:
    """Verify that key structural files and directories exist."""

    def test_architecture_freeze_exists(self):
        """ARCHITECTURE_FREEZE_v1.md must exist."""
        assert os.path.exists(os.path.join(_PROJECT_ROOT, "ARCHITECTURE_FREEZE_v1.md"))

    def test_path_a_directory_exists(self):
        """path_a/ directory must exist with meta_agent.py."""
        assert os.path.isdir(os.path.join(_YSTAR_ROOT, "path_a"))
        assert os.path.exists(os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py"))

    def test_path_b_directory_exists(self):
        """path_b/ directory must exist with path_b_agent.py."""
        assert os.path.isdir(os.path.join(_YSTAR_ROOT, "path_b"))
        assert os.path.exists(os.path.join(_YSTAR_ROOT, "path_b", "path_b_agent.py"))

    def test_experience_bridge_exists(self):
        """governance/experience_bridge.py must exist."""
        assert os.path.exists(
            os.path.join(_YSTAR_ROOT, "governance", "experience_bridge.py")
        )

    def test_causal_engine_exists_in_governance(self):
        """causal_engine.py must be in governance/, not module_graph/."""
        assert os.path.exists(
            os.path.join(_YSTAR_ROOT, "governance", "causal_engine.py")
        )
        # Must NOT exist in module_graph/
        assert not os.path.exists(
            os.path.join(_YSTAR_ROOT, "module_graph", "causal_engine.py")
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Item 14: Role Boundary Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleBoundaries:
    """Verify that agents respect their role boundaries at the method level."""

    def test_path_a_has_no_external_governance_methods(self):
        """PathAAgent should not have methods for external agent governance."""
        methods = _get_class_methods(
            os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py"),
            "PathAAgent",
        )
        external_keywords = [
            "observe_external", "govern_external", "disconnect_agent",
            "external_constraint", "external_observation",
        ]
        for method in methods:
            for kw in external_keywords:
                assert kw not in method, (
                    f"PathAAgent has external governance method: {method}"
                )

    def test_path_b_has_no_internal_wiring_methods(self):
        """PathBAgent should not have methods for internal module wiring."""
        methods = _get_class_methods(
            os.path.join(_YSTAR_ROOT, "path_b", "path_b_agent.py"),
            "PathBAgent",
        )
        internal_keywords = [
            "wire_module", "activate_module", "run_graph",
            "module_graph", "composition_plan",
        ]
        for method in methods:
            for kw in internal_keywords:
                assert kw not in method, (
                    f"PathBAgent has internal wiring method: {method}"
                )

    def test_experience_bridge_does_not_import_path_a_agent(self):
        """ExperienceBridge must not directly import PathAAgent."""
        filepath = os.path.join(_YSTAR_ROOT, "governance", "experience_bridge.py")
        if not os.path.exists(filepath):
            pytest.skip("experience_bridge.py not found")
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "PathAAgent" not in source, (
            "ExperienceBridge directly references PathAAgent"
        )

    # ── T11: Bridge-Only Routing Enforcement ─────────────────────────────────

    def test_governance_loop_does_not_import_path_b_agent(self):
        """GovernanceLoop must not directly import PathBAgent or ExternalGovernanceLoop."""
        filepath = os.path.join(_YSTAR_ROOT, "governance", "governance_loop.py")
        if not os.path.exists(filepath):
            pytest.skip("governance_loop.py not found")
        imports = _get_imports(filepath)
        for imp in imports:
            assert "path_b" not in imp, (
                f"GovernanceLoop imports from path_b: {imp}"
            )
        # Also check for direct class references
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "PathBAgent" not in source, (
            "GovernanceLoop directly references PathBAgent"
        )
        assert "ExternalGovernanceLoop" not in source, (
            "GovernanceLoop directly references ExternalGovernanceLoop"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# N10: Architecture Regression Tests — Provider & Scope Encoding
# ═══════════════════════════════════════════════════════════════════════════════

class TestProviderAndScopeEncoding:
    """Verify that Path A/B use ConstitutionProvider and scope_encoding module."""

    def test_path_a_uses_provider_not_direct_file(self):
        """meta_agent.py must import ConstitutionProvider."""
        imports = _get_imports(os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py"))
        assert any("contract_provider" in imp for imp in imports), (
            "Path A meta_agent.py does not import from contract_provider"
        )
        # Verify it also imports ConstitutionProvider specifically
        filepath = os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py")
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "ConstitutionProvider" in source, (
            "Path A meta_agent.py does not reference ConstitutionProvider"
        )

    def test_path_b_uses_provider_not_direct_file(self):
        """path_b_agent.py must import ConstitutionProvider."""
        imports = _get_imports(os.path.join(_YSTAR_ROOT, "path_b", "path_b_agent.py"))
        assert any("contract_provider" in imp for imp in imports), (
            "Path B path_b_agent.py does not import from contract_provider"
        )
        filepath = os.path.join(_YSTAR_ROOT, "path_b", "path_b_agent.py")
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "ConstitutionProvider" in source, (
            "Path B path_b_agent.py does not reference ConstitutionProvider"
        )

    def test_scope_encoding_used(self):
        """Path A must use scope_encoding module instead of inline f-strings."""
        imports = _get_imports(os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py"))
        assert any("scope_encoding" in imp for imp in imports), (
            "Path A meta_agent.py does not import from scope_encoding"
        )
        filepath = os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py")
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "encode_module_scope" in source, (
            "Path A meta_agent.py does not use encode_module_scope()"
        )
        # Verify no inline module: f-string encoding remains
        # (the old pattern was: f"module:{mod_id}" for mod_id in ...)
        # We check that suggestion_to_contract doesn't use the inline pattern
        assert 'f"module:{mod_id}"' not in source, (
            "Path A still uses inline f-string for module scope encoding"
        )

    def test_compiler_module_exists(self):
        """kernel/compiler.py must exist with compile_source and compile_constitution."""
        filepath = os.path.join(_YSTAR_ROOT, "kernel", "compiler.py")
        assert os.path.exists(filepath), "kernel/compiler.py not found"
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "compile_source" in source
        assert "compile_constitution" in source
        assert "CompiledContractBundle" in source

    def test_contract_provider_module_exists(self):
        """kernel/contract_provider.py must exist with ConstitutionProvider."""
        filepath = os.path.join(_YSTAR_ROOT, "kernel", "contract_provider.py")
        assert os.path.exists(filepath), "kernel/contract_provider.py not found"
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "ConstitutionProvider" in source
        assert "resolve" in source
        assert "invalidate_cache" in source

    def test_delegation_policy_module_exists(self):
        """governance/delegation_policy.py must exist with build_path_a_handoff."""
        filepath = os.path.join(_YSTAR_ROOT, "governance", "delegation_policy.py")
        assert os.path.exists(filepath), "governance/delegation_policy.py not found"
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        assert "build_path_a_handoff" in source
        assert "build_delegation_chain" in source

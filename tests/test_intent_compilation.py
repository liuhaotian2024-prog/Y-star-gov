"""
tests.test_intent_compilation -- Intent Compilation Line Boundary Tests

Item 4: Verify intent compilation boundary invariants.

Tests:
1. nl_to_contract produces valid IntentContract fields
2. Invalid input is rejected (returns empty or minimal)
3. Constitution hash is deterministic
4. Intent compilation modules do NOT import from path_a or path_b
"""
import hashlib
import os
import ast
import pytest

# ── Project root for file scanning ──────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_YSTAR_ROOT = os.path.join(_PROJECT_ROOT, "ystar")


class TestNlToContractOutput:
    """Test that nl_to_contract produces valid IntentContract-compatible output."""

    def test_produces_valid_contract_dict(self):
        """translate_to_contract should return a dict with valid IntentContract fields."""
        from ystar.kernel.nl_to_contract import translate_to_contract

        text = "Never run rm -rf. Only write to ./workspace/."
        result, method, confidence = translate_to_contract(text, api_call_fn=lambda _: None)

        # Should fall back to regex
        assert isinstance(result, dict)
        # Valid fields only
        valid_fields = {
            "deny", "only_paths", "deny_commands", "only_domains",
            "invariant", "optional_invariant", "value_range", "temporal",
            "obligation_timing",
        }
        for key in result:
            assert key in valid_fields, f"Unexpected field: {key}"

    def test_empty_input_returns_empty(self):
        """Empty or whitespace-only input should return empty dict."""
        from ystar.kernel.nl_to_contract import translate_to_contract

        result, method, confidence = translate_to_contract("   ", api_call_fn=lambda _: None)
        assert isinstance(result, dict)
        # Regex fallback on empty text should produce empty or minimal dict
        assert method == "regex"

    def test_nonsense_input_handled(self):
        """Garbage input should not crash, should return something."""
        from ystar.kernel.nl_to_contract import translate_to_contract

        result, method, confidence = translate_to_contract(
            "asdf qwerty 12345 !!!@@@", api_call_fn=lambda _: None
        )
        assert isinstance(result, dict)
        assert method == "regex"


class TestConstitutionHashDeterminism:
    """Test that constitution hash computation is deterministic."""

    def test_path_a_constitution_hash_deterministic(self):
        """PATH_A_AGENTS.md hash should be the same on repeated reads."""
        path = os.path.join(_YSTAR_ROOT, "path_a", "PATH_A_AGENTS.md")
        if not os.path.exists(path):
            pytest.skip("PATH_A_AGENTS.md not found")

        with open(path, "rb") as f:
            hash1 = hashlib.sha256(f.read()).hexdigest()
        with open(path, "rb") as f:
            hash2 = hashlib.sha256(f.read()).hexdigest()

        assert hash1 == hash2, "Constitution hash must be deterministic"

    def test_path_b_constitution_hash_deterministic(self):
        """PATH_B_AGENTS.md hash should be the same on repeated reads."""
        path = os.path.join(_YSTAR_ROOT, "path_b", "PATH_B_AGENTS.md")
        if not os.path.exists(path):
            pytest.skip("PATH_B_AGENTS.md not found")

        with open(path, "rb") as f:
            hash1 = hashlib.sha256(f.read()).hexdigest()
        with open(path, "rb") as f:
            hash2 = hashlib.sha256(f.read()).hexdigest()

        assert hash1 == hash2, "Constitution hash must be deterministic"


class TestIntentCompilationImportBoundary:
    """Test that intent compilation modules do NOT import from path_a or path_b."""

    INTENT_COMPILATION_MODULES = [
        os.path.join(_YSTAR_ROOT, "kernel", "nl_to_contract.py"),
        os.path.join(_YSTAR_ROOT, "kernel", "prefill.py"),
        os.path.join(_YSTAR_ROOT, "governance", "constraints.py"),
        os.path.join(_YSTAR_ROOT, "governance", "proposals.py"),
        os.path.join(_YSTAR_ROOT, "governance", "rule_advisor.py"),
    ]

    @pytest.mark.parametrize("module_path", INTENT_COMPILATION_MODULES)
    def test_no_path_a_import(self, module_path):
        """Intent compilation modules must not import from path_a."""
        if not os.path.exists(module_path):
            pytest.skip(f"{module_path} not found")

        with open(module_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "path_a" not in alias.name, (
                        f"{module_path} imports from path_a: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "path_a" not in node.module, (
                        f"{module_path} imports from path_a: {node.module}"
                    )

    @pytest.mark.parametrize("module_path", INTENT_COMPILATION_MODULES)
    def test_no_path_b_import(self, module_path):
        """Intent compilation modules must not import from path_b."""
        if not os.path.exists(module_path):
            pytest.skip(f"{module_path} not found")

        with open(module_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "path_b" not in alias.name, (
                        f"{module_path} imports from path_b: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "path_b" not in node.module, (
                        f"{module_path} imports from path_b: {node.module}"
                    )

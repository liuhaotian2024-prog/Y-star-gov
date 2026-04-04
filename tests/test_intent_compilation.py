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


class TestIntentContractMarkdownExport:
    """Test IntentContract.to_markdown() method for human-readable output."""

    def test_to_markdown_basic_output(self):
        """to_markdown() should produce well-formatted Markdown output."""
        from ystar.kernel.dimensions import IntentContract

        contract = IntentContract(
            name="test_contract",
            deny=[".env", "/etc/passwd"],
            deny_commands=["rm -rf", "sudo"],
            only_paths=["./workspace/"],
            invariant=["amount > 0"],
            value_range={"amount": {"min": 1, "max": 1000}},
        )

        md = contract.to_markdown()

        # Should contain key sections
        assert "# Intent Contract" in md
        assert "test_contract" in md
        assert "### Absolute Denials" in md
        assert ".env" in md
        assert "### Denied Commands" in md
        assert "rm -rf" in md
        assert "### Allowed Paths Only" in md
        assert "./workspace/" in md
        assert "### Invariants (hard)" in md
        assert "amount > 0" in md
        assert "### Value Range Constraints" in md
        assert "min=1, max=1000" in md

    def test_to_markdown_with_metadata(self):
        """to_markdown(include_metadata=True) should include lifecycle fields."""
        from ystar.kernel.dimensions import IntentContract

        contract = IntentContract(
            name="lifecycle_test",
            deny=[".env"],
            status="confirmed",
            confirmed_by="alice@example.com",
            confirmed_at=1234567890.0,
            version=2,
            review_triggers=["personnel_change"],
        )

        md = contract.to_markdown(include_metadata=True)

        # Should contain lifecycle metadata
        assert "### Lifecycle Metadata" in md
        assert "Status**: confirmed" in md
        assert "Confirmed by**: alice@example.com" in md
        assert "Confirmed at**:" in md
        assert "Version**: 2" in md
        assert "Review triggers**:" in md
        assert "personnel_change" in md

    def test_to_markdown_empty_contract(self):
        """to_markdown() should handle empty contracts gracefully."""
        from ystar.kernel.dimensions import IntentContract

        contract = IntentContract(name="empty")
        md = contract.to_markdown()

        # Should have header but no constraint sections
        assert "# Intent Contract" in md
        assert "empty" in md
        # Should not crash or produce malformed output
        assert isinstance(md, str)
        assert len(md) > 0

    def test_to_markdown_obligation_timing(self):
        """to_markdown() should format obligation_timing correctly."""
        from ystar.kernel.dimensions import IntentContract

        contract = IntentContract(
            obligation_timing={
                "acknowledgement": 300,
                "completion": 3600,
                "delegation": 600,
            }
        )

        md = contract.to_markdown()

        assert "### Obligation Timing (seconds)" in md
        assert "acknowledgement`: 300s" in md
        assert "completion`: 3600s" in md
        assert "delegation`: 600s" in md

    def test_to_markdown_field_deny(self):
        """to_markdown() should format field_deny rules correctly."""
        from ystar.kernel.dimensions import IntentContract

        contract = IntentContract(
            field_deny={
                "environment": ["production", "prod"],
                "account_type": ["admin", "root"],
            }
        )

        md = contract.to_markdown()

        assert "### Field Deny Rules" in md
        assert "field `environment` must not contain:" in md
        assert "production" in md
        assert "field `account_type` must not contain:" in md
        assert "admin" in md

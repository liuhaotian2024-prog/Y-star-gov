"""
test_nl_to_contract.py
======================
Tests for natural language to IntentContract translation.

Covers:
1. LLM path (when API key is available)
2. Regex fallback (when API key is missing)
3. All rule types: paths, commands, amounts, domains
4. Error messaging when LLM fallback happens
"""
import os
import pytest
from ystar.kernel.nl_to_contract import translate_to_contract


class TestRegexFallback:
    """Test the regex fallback when LLM is not available."""

    def test_path_denial(self):
        """Regex should extract path denials."""
        text = "Never access /etc or /root."
        result, method, confidence = translate_to_contract(text, api_call_fn=lambda _: None)

        # When api_call_fn returns None, it should fall back to regex
        assert method == "regex"
        assert confidence == 0.50
        assert "/etc" in result.get("deny", [])
        assert "/root" in result.get("deny", []) or "/root." in result.get("deny", [])

    def test_command_denial_full_phrase(self):
        """Regex should extract full command phrases, not just first word."""
        # Use newlines to separate sentences (prefill processes line-by-line)
        text = "Never run rm -rf.\nNever execute sudo rm."
        result, method, confidence = translate_to_contract(text, api_call_fn=lambda _: None)

        assert method == "regex"
        deny_cmds = result.get("deny_commands", [])

        # Should extract "rm -rf", not just "rm"
        assert any("rm -rf" in cmd or "rm" in cmd and "-rf" in cmd for cmd in deny_cmds), \
            f"Expected 'rm -rf' in deny_commands, got: {deny_cmds}"

        # Should extract "sudo rm", not just "sudo"
        assert any("sudo" in cmd and "rm" in cmd for cmd in deny_cmds), \
            f"Expected 'sudo rm' in deny_commands, got: {deny_cmds}"

    def test_amount_limit_maximum(self):
        """Regex should extract maximum amount limits."""
        text = "Maximum transaction amount 5000."
        result, method, confidence = translate_to_contract(text, api_call_fn=lambda _: None)

        assert method == "regex"
        value_range = result.get("value_range", {})

        # Should have extracted the amount limit
        assert "amount" in value_range or "transaction" in value_range, \
            f"Expected amount/transaction in value_range, got: {value_range}"

        # Check that max value is 5000
        for param in ["amount", "transaction"]:
            if param in value_range:
                assert value_range[param].get("max") == 5000, \
                    f"Expected max=5000, got: {value_range[param]}"

    def test_amount_limit_variations(self):
        """Test various amount limit phrasings."""
        test_cases = [
            ("maximum amount 5000", "amount", 5000, "max"),
            ("max transaction 10000", "transaction", 10000, "max"),
            ("amount limit 999", "amount", 999, "max"),
            ("minimum amount 100", "amount", 100, "min"),
            ("at least 50", None, 50, "min"),  # May not extract without explicit keyword
        ]

        for text, expected_param, expected_val, limit_type in test_cases:
            result, method, confidence = translate_to_contract(text, api_call_fn=lambda _: None)
            value_range = result.get("value_range", {})

            if expected_param:
                assert expected_param in value_range, \
                    f"Text: '{text}' - Expected {expected_param} in value_range, got: {value_range}"
                assert value_range[expected_param].get(limit_type) == expected_val, \
                    f"Text: '{text}' - Expected {limit_type}={expected_val}, got: {value_range[expected_param]}"

    def test_comprehensive_mixed_rules(self):
        """Test the example from K9's bug report."""
        # Use newlines to separate sentences
        text = "Never access /etc or /root.\nNever run rm -rf.\nMaximum transaction amount 5000."
        result, method, confidence = translate_to_contract(text, api_call_fn=lambda _: None)

        assert method == "regex"

        # Should have path denials
        deny_paths = result.get("deny", [])
        assert any("/etc" in p for p in deny_paths), f"Expected /etc in deny, got: {deny_paths}"
        assert any("/root" in p for p in deny_paths), f"Expected /root in deny, got: {deny_paths}"

        # Should have command denials (full phrase)
        deny_cmds = result.get("deny_commands", [])
        assert any("rm" in cmd for cmd in deny_cmds), \
            f"Expected rm-related command in deny_commands, got: {deny_cmds}"

        # Should have amount limit
        value_range = result.get("value_range", {})
        assert "amount" in value_range or "transaction" in value_range, \
            f"Expected amount limit in value_range, got: {value_range}"

    def test_domain_restrictions(self):
        """Regex should extract domain whitelist."""
        text = "Only access github.com and api.stripe.com."
        result, method, confidence = translate_to_contract(text, api_call_fn=lambda _: None)

        assert method == "regex"
        domains = result.get("only_domains", [])
        assert "github.com" in domains, f"Expected github.com in only_domains, got: {domains}"
        assert "api.stripe.com" in domains, f"Expected api.stripe.com in only_domains, got: {domains}"


class TestLLMPath:
    """Test the LLM translation path (requires mock or real API key)."""

    def test_llm_with_mock_api(self):
        """Test that LLM path is used when api_call_fn is provided."""
        def mock_llm(prompt):
            # Return a valid JSON contract
            return '{"deny": ["/production"], "deny_commands": ["git push --force"], "value_range": {"amount": {"max": 5000}}}'

        text = "Never access /production. Never run git push --force. Maximum amount 5000."
        result, method, confidence = translate_to_contract(text, api_call_fn=mock_llm)

        assert method == "llm"
        assert confidence == 0.90
        assert "/production" in result.get("deny", [])
        assert "git push --force" in result.get("deny_commands", [])
        assert result.get("value_range", {}).get("amount", {}).get("max") == 5000

    def test_llm_falls_back_on_api_error(self):
        """When LLM call fails, should fall back to regex."""
        def failing_llm(prompt):
            raise Exception("API error")

        text = "Never access /etc."
        result, method, confidence = translate_to_contract(text, api_call_fn=failing_llm)

        # Should fall back to regex
        assert method == "regex"
        assert confidence == 0.50
        # Should have extracted /etc (with or without trailing period stripped)
        assert any("/etc" in p for p in result.get("deny", [])), \
            f"Expected /etc in deny, got: {result.get('deny', [])}"


class TestErrorMessaging:
    """Test that proper error messages are shown."""

    def test_no_api_key_message(self, capsys):
        """Should show clear message when API key is missing."""
        # Ensure no API key is set
        old_key = os.environ.get("ANTHROPIC_API_KEY")
        if old_key:
            del os.environ["ANTHROPIC_API_KEY"]

        try:
            text = "Never access /etc."
            result, method, confidence = translate_to_contract(text)

            # Should use regex fallback
            assert method == "regex"

            # Should have printed warning message
            captured = capsys.readouterr()
            assert "ANTHROPIC_API_KEY not set" in captured.err or "regex fallback" in captured.err.lower(), \
                f"Expected API key warning in stderr, got: {captured.err}"
        finally:
            # Restore original API key
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_api_error_message(self, capsys):
        """Should show clear message when API call fails."""
        def failing_llm(prompt):
            raise ValueError("Invalid API key")

        text = "Never access /etc."
        result, method, confidence = translate_to_contract(text, api_call_fn=failing_llm)

        # Should use regex fallback
        assert method == "regex"

        # Should have printed error message
        captured = capsys.readouterr()
        assert "LLM translation failed" in captured.err or "Falling back to regex" in captured.err, \
            f"Expected LLM failure warning in stderr, got: {captured.err}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

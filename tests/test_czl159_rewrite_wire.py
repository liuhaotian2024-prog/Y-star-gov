"""
CZL-166: Test that CZL-159 deny messages include actionable header template.

Unit-tests the CZL-159 logic extracted from hook_wrapper.py, verifying
the deny reason contains fill-in-the-blank header fields.
"""
import re
import pytest


def _czl159_evaluate(file_path: str, content: str):
    """Extract CZL-159 logic from hook_wrapper.py for isolated testing.

    Returns (should_block: bool, block_msg: str | None).
    """
    _enforced_prefixes = ("reports/", "content/", "knowledge/ceo/strategy/")
    _is_enforced = any(pfx in file_path for pfx in _enforced_prefixes)
    if not _is_enforced:
        return False, None

    _research = bool(re.search(
        r"(source[s]?[:\s]|cite[ds]?[\s:]|per\s+\w|according\s+to|"
        r"search|found\s+that|reference[ds]?|evidence|data\s+show|"
        r"based\s+on|research|study|paper|article|empirical)",
        content, re.IGNORECASE))
    _synthesis = bool(re.search(
        r"(therefore|because|analysis|conclude[ds]?|lesson[s]?|"
        r"insight[s]?|implication|root\s+cause|pattern|takeaway|"
        r"diagnosis|framework|principle|synthesis|assessment)",
        content, re.IGNORECASE))
    _audience = bool(re.search(
        r"(audience|purpose|for\s+board|stakeholder|reader[s]?|"
        r"\u76ee\u6807\u53d7\u4f17|\u76ee\u7684|\u9762\u5411|intended\s+for|context\s+for|"
        r"decision\s+maker|consumer|recipient)",
        content, re.IGNORECASE))

    _missing = []
    if not _research:
        _missing.append("research")
    if not _synthesis:
        _missing.append("synthesis")
    if not _audience:
        _missing.append("audience")

    if not _missing:
        return False, None

    # -- CZL-166: header template logic (mirrors hook_wrapper.py) --
    try:
        from ystar.rules.auto_rewrite import czl159_header_autoinject_template
        _header_template = czl159_header_autoinject_template()
    except Exception:
        _header_template = (
            "\n\n--- Copy this template into your document header before writing ---\n"
            "Audience: [who is the intended reader?]\n"
            "Research basis: [cite sources, data, or evidence]\n"
            "Synthesis: [what is the core insight / conclusion?]\n"
            "Purpose: [what decision or action should this enable?]\n"
            "---\n"
            "Fill in each bracket, then re-attempt the Write."
        )

    _block_msg = (
        f"[CZL-159 CEO PRE-OUTPUT BLOCK] Write to {file_path} missing "
        f"U-workflow signals: {', '.join(_missing)}. "
        f"Do research/synthesis/audience framing before writing."
        f"{_header_template}"
    )
    return True, _block_msg


class TestCZL159DenyIncludesHeaderTemplate:
    """CZL-166: deny reason must contain actionable fill-in-the-blank template."""

    def test_missing_signals_deny_includes_header_template(self):
        """Write to content/ with zero U-workflow signals -> deny with template."""
        blocked, reason = _czl159_evaluate(
            "content/blog_post.md",
            "Hello world. This is a bare post with no signals.",
        )
        assert blocked is True
        assert "CZL-159" in reason
        assert "Audience:" in reason, "Template must include Audience field"
        assert "Research basis:" in reason, "Template must include Research basis field"
        assert "Synthesis:" in reason, "Template must include Synthesis field"
        assert "Purpose:" in reason, "Template must include Purpose field"
        assert "Fill in each bracket" in reason, "Template must include actionable instruction"

    def test_missing_one_signal_still_includes_template(self):
        """Write with research+synthesis but no audience -> deny includes template."""
        blocked, reason = _czl159_evaluate(
            "content/quarterly.md",
            (
                "Based on research data showing growth patterns, "
                "the analysis concludes upward trend."
            ),
        )
        assert blocked is True
        assert "audience" in reason.lower()
        assert "Audience:" in reason, "Template present even for single missing signal"

    def test_all_signals_present_no_block(self):
        """Write with all 3 signals -> no CZL-159 block."""
        blocked, reason = _czl159_evaluate(
            "content/analysis.md",
            (
                "For the intended audience of decision makers: "
                "Based on research and evidence from multiple sources, "
                "the analysis concludes that the framework is sound. "
                "Therefore the insight is clear."
            ),
        )
        assert blocked is False
        assert reason is None

    def test_non_enforced_path_no_block(self):
        """Write to non-enforced path -> no CZL-159 block regardless of content."""
        blocked, reason = _czl159_evaluate(
            "scripts/some_script.py",
            "bare content no signals",
        )
        assert blocked is False

    def test_template_has_copy_instruction(self):
        """Template must tell user to copy and fill in."""
        blocked, reason = _czl159_evaluate(
            "knowledge/ceo/strategy/plan.md",
            "just a bare plan",
        )
        assert blocked is True
        assert "Copy this template" in reason or "Fill in each bracket" in reason

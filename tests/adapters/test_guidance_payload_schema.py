"""
CZL-ARCH-11d: GuidancePayload schema tests.

Validates the GuidancePayload dataclass is correctly defined with
sane defaults and correct field types.
"""

from dataclasses import fields as dc_fields
from typing import Dict, Any, Optional

from ystar.domains.openclaw.adapter import GuidancePayload


class TestGuidancePayloadSchema:
    """Three minimum-viable tests for the GuidancePayload dataclass."""

    def test_instantiation_defaults(self):
        """GuidancePayload can be instantiated with zero arguments (all defaults)."""
        gp = GuidancePayload()
        assert gp is not None
        assert isinstance(gp, GuidancePayload)

    def test_default_values_sane(self):
        """Default values are safe no-ops: no command, empty args, no retry, no refs."""
        gp = GuidancePayload()
        assert gp.invoke_cmd is None
        assert gp.fix_command_args == {}
        assert gp.then_retry_original is False
        assert gp.rule_ref is None
        assert gp.docs_ref is None

    def test_field_types_correct(self):
        """All 5 fields exist with the expected type annotations."""
        gp = GuidancePayload(
            invoke_cmd="ystar doctor",
            fix_command_args={"--verbose": True},
            then_retry_original=True,
            rule_ref="labs.path_alias_normalizer",
            docs_ref="https://docs.ystar.dev/rules/path-alias",
        )
        assert isinstance(gp.invoke_cmd, str)
        assert isinstance(gp.fix_command_args, dict)
        assert isinstance(gp.then_retry_original, bool)
        assert isinstance(gp.rule_ref, str)
        assert isinstance(gp.docs_ref, str)

        # Verify exactly 5 fields on the dataclass
        field_names = {f.name for f in dc_fields(GuidancePayload)}
        assert field_names == {
            "invoke_cmd",
            "fix_command_args",
            "then_retry_original",
            "rule_ref",
            "docs_ref",
        }

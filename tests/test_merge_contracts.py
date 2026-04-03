"""
Tests for three-layer contract merge with monotonicity guarantee.

Covers:
  - All None inputs
  - Session-only (identity merge)
  - Session + deny (tightening)
  - Session + deny + relax (relaxation within bounds)
  - Relax attempts to exceed session boundary (rejected)
  - All 8 dimensions + obligation_timing

Architecture:
  Layer 1 (session)       -- immutable upper bound
  Layer 2 (runtime_deny)  -- can only tighten
  Layer 3 (runtime_relax) -- can loosen deny, but never exceed session
"""
import pytest

from ystar.kernel.dimensions import IntentContract
from ystar.kernel.merge import merge_contracts


# ============================================================================
# 1. Base cases
# ============================================================================

class TestBaseCases:
    """All-None, session-only, and trivial merge cases."""

    def test_all_none_returns_empty(self):
        """When session is None, return empty IntentContract."""
        result = merge_contracts(None, None, None)
        assert result.is_empty()

    def test_session_none_with_deny_returns_empty(self):
        """Even if deny is provided, None session means empty result."""
        deny = IntentContract(deny=["secret"])
        result = merge_contracts(None, deny, None)
        assert result.is_empty()

    def test_session_only_returns_clone(self):
        """With only session, result equals session."""
        session = IntentContract(
            deny=["a"],
            only_paths=["./src"],
            deny_commands=["rm -rf"],
            only_domains=["api.example.com"],
            invariant=["x > 0"],
            postcondition=["result != None"],
            field_deny={"env": ["production"]},
            value_range={"amount": {"min": 0, "max": 1000}},
        )
        result = merge_contracts(session)
        assert result.deny == ["a"]
        assert result.only_paths == ["./src"]
        assert result.deny_commands == ["rm -rf"]
        assert result.only_domains == ["api.example.com"]
        assert result.invariant == ["x > 0"]
        assert result.postcondition == ["result != None"]
        assert result.field_deny == {"env": ["production"]}
        assert result.value_range == {"amount": {"min": 0, "max": 1000}}

    def test_session_only_is_independent_copy(self):
        """Mutating the result must not affect the original session."""
        session = IntentContract(deny=["a"])
        result = merge_contracts(session)
        result.deny.append("b")
        assert session.deny == ["a"]

    def test_empty_deny_and_relax(self):
        """Empty deny/relax contracts produce session-equivalent result."""
        session = IntentContract(deny=["a"], invariant=["x > 0"])
        result = merge_contracts(session, IntentContract(), IntentContract())
        assert result.deny == ["a"]
        assert result.invariant == ["x > 0"]


# ============================================================================
# 2. Blacklist dimensions: deny, deny_commands
# ============================================================================

class TestBlacklistMerge:
    """deny and deny_commands follow blacklist merge rules."""

    def test_deny_adds_items(self):
        """deny layer adds new deny items to session baseline."""
        session = IntentContract(deny=["a"])
        deny = IntentContract(deny=["b"])
        result = merge_contracts(session, deny)
        assert "a" in result.deny
        assert "b" in result.deny

    def test_deny_duplicate_is_deduplicated(self):
        """deny adding an item already in session does not duplicate."""
        session = IntentContract(deny=["a", "b"])
        deny = IntentContract(deny=["a"])
        result = merge_contracts(session, deny)
        assert result.deny.count("a") == 1

    def test_relax_removes_deny_added_items(self):
        """relax can remove items that deny added."""
        session = IntentContract(deny=["a"])
        deny = IntentContract(deny=["b"])
        relax = IntentContract(deny=["b"])
        result = merge_contracts(session, deny, relax)
        assert "a" in result.deny
        assert "b" not in result.deny

    def test_relax_cannot_remove_session_items(self):
        """relax CANNOT remove items from the session baseline."""
        session = IntentContract(deny=["a", "b"])
        deny = IntentContract(deny=["c"])
        relax = IntentContract(deny=["a"])  # tries to remove session item
        result = merge_contracts(session, deny, relax)
        assert "a" in result.deny  # session item preserved
        assert "b" in result.deny
        assert "c" in result.deny  # deny item not targeted by relax

    def test_deny_commands_same_pattern(self):
        """deny_commands follows the same blacklist merge rules."""
        session = IntentContract(deny_commands=["rm -rf"])
        deny = IntentContract(deny_commands=["sudo"])
        relax = IntentContract(deny_commands=["sudo"])
        result = merge_contracts(session, deny, relax)
        assert "rm -rf" in result.deny_commands
        assert "sudo" not in result.deny_commands


# ============================================================================
# 3. Whitelist dimensions: only_paths
# ============================================================================

class TestWhitelistPaths:
    """only_paths whitelist merge rules."""

    def test_deny_narrows_paths(self):
        """deny restricts paths to a subset of session."""
        session = IntentContract(only_paths=["./src"])
        deny = IntentContract(only_paths=["./src/core"])
        result = merge_contracts(session, deny)
        assert result.only_paths == ["./src/core"]

    def test_deny_path_outside_session_ignored(self):
        """deny paths not within session paths are rejected."""
        session = IntentContract(only_paths=["./src"])
        deny = IntentContract(only_paths=["./other"])  # not within ./src
        result = merge_contracts(session, deny)
        # Invalid deny paths fall back to session
        assert result.only_paths == ["./src"]

    def test_relax_widens_within_session(self):
        """relax can add paths back, but only within session boundary."""
        session = IntentContract(only_paths=["./src"])
        deny = IntentContract(only_paths=["./src/core"])
        relax = IntentContract(only_paths=["./src/lib"])
        result = merge_contracts(session, deny, relax)
        assert "./src/core" in result.only_paths
        assert "./src/lib" in result.only_paths

    def test_relax_path_outside_session_rejected(self):
        """relax cannot add paths outside session boundary."""
        session = IntentContract(only_paths=["./src"])
        deny = IntentContract(only_paths=["./src/core"])
        relax = IntentContract(only_paths=["./other"])  # outside session
        result = merge_contracts(session, deny, relax)
        assert "./src/core" in result.only_paths
        assert "./other" not in result.only_paths

    def test_empty_session_paths_means_no_restriction(self):
        """Empty session paths = no path restriction."""
        session = IntentContract(only_paths=[])
        deny = IntentContract(only_paths=["./src"])
        result = merge_contracts(session, deny)
        assert result.only_paths == []


# ============================================================================
# 4. Whitelist dimensions: only_domains
# ============================================================================

class TestWhitelistDomains:
    """only_domains whitelist merge rules."""

    def test_deny_narrows_domains(self):
        """deny restricts domains to a subset of session."""
        session = IntentContract(
            only_domains=["api.example.com", "cdn.example.com", "auth.example.com"]
        )
        deny = IntentContract(only_domains=["api.example.com"])
        result = merge_contracts(session, deny)
        assert result.only_domains == ["api.example.com"]

    def test_deny_domain_outside_session_ignored(self):
        """deny domains not in session set are rejected."""
        session = IntentContract(only_domains=["api.example.com"])
        deny = IntentContract(only_domains=["evil.com"])
        result = merge_contracts(session, deny)
        assert result.only_domains == ["api.example.com"]

    def test_relax_widens_within_session(self):
        """relax can add domains back, but only from session set."""
        session = IntentContract(
            only_domains=["api.example.com", "cdn.example.com"]
        )
        deny = IntentContract(only_domains=["api.example.com"])
        relax = IntentContract(only_domains=["cdn.example.com"])
        result = merge_contracts(session, deny, relax)
        assert "api.example.com" in result.only_domains
        assert "cdn.example.com" in result.only_domains

    def test_relax_domain_outside_session_rejected(self):
        """relax cannot add domains outside session set."""
        session = IntentContract(only_domains=["api.example.com"])
        deny = IntentContract(only_domains=["api.example.com"])
        relax = IntentContract(only_domains=["evil.com"])
        result = merge_contracts(session, deny, relax)
        assert "evil.com" not in result.only_domains


# ============================================================================
# 5. Predicate dimensions: invariant, postcondition, optional_invariant
# ============================================================================

class TestPredicateMerge:
    """invariant, postcondition, and optional_invariant merge rules."""

    def test_deny_adds_invariants(self):
        """deny adds new invariant predicates."""
        session = IntentContract(invariant=["x > 0"])
        deny = IntentContract(invariant=["x < 100"])
        result = merge_contracts(session, deny)
        assert "x > 0" in result.invariant
        assert "x < 100" in result.invariant

    def test_relax_removes_deny_invariants(self):
        """relax can remove deny-added invariants."""
        session = IntentContract(invariant=["x > 0"])
        deny = IntentContract(invariant=["x < 100"])
        relax = IntentContract(invariant=["x < 100"])
        result = merge_contracts(session, deny, relax)
        assert "x > 0" in result.invariant
        assert "x < 100" not in result.invariant

    def test_relax_cannot_remove_session_invariants(self):
        """relax cannot remove session baseline invariants."""
        session = IntentContract(invariant=["x > 0", "y > 0"])
        deny = IntentContract(invariant=["z > 0"])
        relax = IntentContract(invariant=["x > 0"])  # tries to remove session
        result = merge_contracts(session, deny, relax)
        assert "x > 0" in result.invariant
        assert "y > 0" in result.invariant
        assert "z > 0" in result.invariant

    def test_postcondition_same_pattern(self):
        """postcondition follows the same predicate merge rules."""
        session = IntentContract(postcondition=["result != None"])
        deny = IntentContract(postcondition=["result.get('status') == 'ok'"])
        relax = IntentContract(postcondition=["result.get('status') == 'ok'"])
        result = merge_contracts(session, deny, relax)
        assert "result != None" in result.postcondition
        assert "result.get('status') == 'ok'" not in result.postcondition

    def test_optional_invariant_same_pattern(self):
        """optional_invariant follows the same predicate merge rules."""
        session = IntentContract(optional_invariant=["confidence > 0.5"])
        deny = IntentContract(optional_invariant=["confidence > 0.8"])
        result = merge_contracts(session, deny)
        assert "confidence > 0.5" in result.optional_invariant
        assert "confidence > 0.8" in result.optional_invariant


# ============================================================================
# 6. Numeric range dimension: value_range
# ============================================================================

class TestValueRangeMerge:
    """value_range numeric bounds merge rules."""

    def test_deny_tightens_range(self):
        """deny raises min and lowers max."""
        session = IntentContract(
            value_range={"amount": {"min": 0, "max": 1000}}
        )
        deny = IntentContract(
            value_range={"amount": {"min": 10, "max": 500}}
        )
        result = merge_contracts(session, deny)
        assert result.value_range["amount"]["min"] == 10
        assert result.value_range["amount"]["max"] == 500

    def test_deny_cannot_loosen_range(self):
        """deny trying to loosen is ignored (clamped to session)."""
        session = IntentContract(
            value_range={"amount": {"min": 10, "max": 500}}
        )
        deny = IntentContract(
            value_range={"amount": {"min": 0, "max": 1000}}  # looser
        )
        result = merge_contracts(session, deny)
        assert result.value_range["amount"]["min"] == 10  # session min preserved
        assert result.value_range["amount"]["max"] == 500  # session max preserved

    def test_relax_loosens_within_session(self):
        """relax loosens deny's tightening but stays within session bounds."""
        session = IntentContract(
            value_range={"amount": {"min": 0, "max": 1000}}
        )
        deny = IntentContract(
            value_range={"amount": {"min": 10, "max": 500}}
        )
        relax = IntentContract(
            value_range={"amount": {"min": 5, "max": 700}}
        )
        result = merge_contracts(session, deny, relax)
        assert result.value_range["amount"]["min"] == 5  # loosened from deny's 10
        assert result.value_range["amount"]["max"] == 700  # loosened from deny's 500

    def test_relax_cannot_exceed_session_bounds(self):
        """relax trying to exceed session boundary is clamped."""
        session = IntentContract(
            value_range={"amount": {"min": 0, "max": 1000}}
        )
        deny = IntentContract(
            value_range={"amount": {"min": 10, "max": 500}}
        )
        relax = IntentContract(
            value_range={"amount": {"min": -5, "max": 2000}}  # exceeds session
        )
        result = merge_contracts(session, deny, relax)
        assert result.value_range["amount"]["min"] == 0  # clamped to session min
        assert result.value_range["amount"]["max"] == 1000  # clamped to session max

    def test_deny_adds_new_param_range(self):
        """deny can add value_range for a param not in session."""
        session = IntentContract(
            value_range={"amount": {"min": 0, "max": 1000}}
        )
        deny = IntentContract(
            value_range={"count": {"min": 1, "max": 100}}
        )
        result = merge_contracts(session, deny)
        assert result.value_range["amount"] == {"min": 0, "max": 1000}
        assert result.value_range["count"] == {"min": 1, "max": 100}

    def test_relax_loosens_deny_only_param(self):
        """relax can loosen a param that only deny defined (no session limit)."""
        session = IntentContract(value_range={})
        deny = IntentContract(
            value_range={"count": {"min": 10, "max": 50}}
        )
        relax = IntentContract(
            value_range={"count": {"min": 5, "max": 80}}
        )
        result = merge_contracts(session, deny, relax)
        # No session boundary, so relax goes to its requested values
        assert result.value_range["count"]["min"] == 5
        assert result.value_range["count"]["max"] == 80


# ============================================================================
# 7. Field deny dimension
# ============================================================================

class TestFieldDenyMerge:
    """field_deny per-field blacklist merge rules."""

    def test_deny_adds_field_deny_items(self):
        """deny adds new blocked values to a field."""
        session = IntentContract(field_deny={"env": ["production"]})
        deny = IntentContract(field_deny={"env": ["staging"]})
        result = merge_contracts(session, deny)
        assert "production" in result.field_deny["env"]
        assert "staging" in result.field_deny["env"]

    def test_relax_removes_deny_field_items(self):
        """relax removes deny-added field items but keeps session items."""
        session = IntentContract(field_deny={"env": ["production"]})
        deny = IntentContract(field_deny={"env": ["staging"]})
        relax = IntentContract(field_deny={"env": ["staging"]})
        result = merge_contracts(session, deny, relax)
        assert "production" in result.field_deny["env"]
        assert "staging" not in result.field_deny["env"]

    def test_deny_adds_new_field(self):
        """deny can add a completely new field to field_deny."""
        session = IntentContract(field_deny={"env": ["production"]})
        deny = IntentContract(field_deny={"region": ["us-gov"]})
        result = merge_contracts(session, deny)
        assert result.field_deny["env"] == ["production"]
        assert result.field_deny["region"] == ["us-gov"]

    def test_relax_cannot_remove_session_field_items(self):
        """relax cannot remove session baseline field_deny items."""
        session = IntentContract(field_deny={"env": ["production"]})
        deny = IntentContract(field_deny={})
        relax = IntentContract(field_deny={"env": ["production"]})
        result = merge_contracts(session, deny, relax)
        assert "production" in result.field_deny["env"]


# ============================================================================
# 8. Obligation timing dimension
# ============================================================================

class TestObligationTimingMerge:
    """obligation_timing merge rules (shorter = stricter)."""

    def test_deny_tightens_timing(self):
        """deny imposes shorter deadlines."""
        session = IntentContract(
            obligation_timing={"completion": 3600, "acknowledgement": 300}
        )
        deny = IntentContract(
            obligation_timing={"completion": 1800}  # tighter
        )
        result = merge_contracts(session, deny)
        assert result.obligation_timing["completion"] == 1800
        assert result.obligation_timing["acknowledgement"] == 300

    def test_deny_cannot_loosen_timing(self):
        """deny trying to lengthen deadline is clamped to session."""
        session = IntentContract(
            obligation_timing={"completion": 1800}
        )
        deny = IntentContract(
            obligation_timing={"completion": 3600}  # looser, rejected
        )
        result = merge_contracts(session, deny)
        assert result.obligation_timing["completion"] == 1800

    def test_relax_loosens_within_session(self):
        """relax can extend deadline back toward session limit."""
        session = IntentContract(
            obligation_timing={"completion": 3600}
        )
        deny = IntentContract(
            obligation_timing={"completion": 1800}
        )
        relax = IntentContract(
            obligation_timing={"completion": 2700}
        )
        result = merge_contracts(session, deny, relax)
        assert result.obligation_timing["completion"] == 2700

    def test_relax_cannot_exceed_session_timing(self):
        """relax cannot extend deadline beyond session limit."""
        session = IntentContract(
            obligation_timing={"completion": 3600}
        )
        deny = IntentContract(
            obligation_timing={"completion": 1800}
        )
        relax = IntentContract(
            obligation_timing={"completion": 7200}  # exceeds session
        )
        result = merge_contracts(session, deny, relax)
        assert result.obligation_timing["completion"] == 3600  # clamped to session


# ============================================================================
# 9. Monotonicity guarantee (cross-dimension)
# ============================================================================

class TestMonotonicity:
    """The merged contract must never be more permissive than session."""

    def test_merged_is_subset_of_session(self):
        """Merged result must satisfy is_subset_of(session)."""
        session = IntentContract(
            deny=["secret"],
            deny_commands=["rm -rf"],
            invariant=["x > 0"],
            value_range={"amount": {"min": 0, "max": 1000}},
        )
        deny = IntentContract(
            deny=["password"],
            deny_commands=["sudo"],
            invariant=["x < 100"],
            value_range={"amount": {"min": 10, "max": 500}},
        )
        relax = IntentContract(
            deny=["password"],  # undo deny's addition
            value_range={"amount": {"min": 5, "max": 700}},
        )
        result = merge_contracts(session, deny, relax)

        # The result should be at least as strict as session
        is_sub, violations = result.is_subset_of(session)
        assert is_sub, f"Monotonicity violated: {violations}"

    def test_adversarial_relax_all_dimensions(self):
        """Adversarial relax tries to loosen every dimension -- all clamped."""
        session = IntentContract(
            deny=["a"],
            deny_commands=["rm"],
            only_paths=["./src"],
            only_domains=["api.example.com"],
            invariant=["x > 0"],
            postcondition=["result != None"],
            field_deny={"env": ["prod"]},
            value_range={"amount": {"min": 0, "max": 1000}},
            obligation_timing={"completion": 3600},
        )
        deny = IntentContract()  # no deny
        relax = IntentContract(
            deny=["a"],  # tries to remove session deny
            deny_commands=["rm"],  # tries to remove session deny_commands
            only_paths=["./other"],  # outside session
            only_domains=["evil.com"],  # outside session
            invariant=["x > 0"],  # tries to remove session invariant
            postcondition=["result != None"],  # tries to remove session postcondition
            field_deny={"env": ["prod"]},  # tries to remove session field_deny
            value_range={"amount": {"min": -100, "max": 5000}},  # exceeds session
            obligation_timing={"completion": 7200},  # exceeds session
        )
        result = merge_contracts(session, deny, relax)

        # All session baselines should be preserved
        assert "a" in result.deny
        assert "rm" in result.deny_commands
        assert "x > 0" in result.invariant
        assert "result != None" in result.postcondition
        assert "prod" in result.field_deny.get("env", [])
        assert result.value_range["amount"]["min"] == 0
        assert result.value_range["amount"]["max"] == 1000
        assert result.obligation_timing["completion"] == 3600

        # Paths and domains should not include adversarial additions
        assert "./other" not in result.only_paths
        assert "evil.com" not in result.only_domains

    def test_name_preserved_from_session(self):
        """The merged contract should preserve session's name."""
        session = IntentContract(deny=["a"], name="my_contract")
        deny = IntentContract(deny=["b"], name="deny_contract")
        result = merge_contracts(session, deny)
        assert result.name == "my_contract"


# ============================================================================
# 10. Edge cases
# ============================================================================

class TestEdgeCases:
    """Edge cases and unusual inputs."""

    def test_relax_without_deny(self):
        """relax without deny has no effect (nothing to relax)."""
        session = IntentContract(deny=["a"])
        relax = IntentContract(deny=["a"])  # nothing was deny-added
        result = merge_contracts(session, None, relax)
        assert result.deny == ["a"]

    def test_multiple_deny_and_relax_items(self):
        """Multiple items in deny and selective relax."""
        session = IntentContract(deny=["a"])
        deny = IntentContract(deny=["b", "c", "d"])
        relax = IntentContract(deny=["c"])  # only remove "c"
        result = merge_contracts(session, deny, relax)
        assert "a" in result.deny
        assert "b" in result.deny
        assert "c" not in result.deny
        assert "d" in result.deny

    def test_value_range_partial_bounds(self):
        """value_range with only min or only max."""
        session = IntentContract(
            value_range={"x": {"min": 0}}  # no max
        )
        deny = IntentContract(
            value_range={"x": {"min": 5}}
        )
        result = merge_contracts(session, deny)
        assert result.value_range["x"]["min"] == 5
        assert "max" not in result.value_range["x"]

    def test_empty_session_paths_deny_does_not_restrict(self):
        """If session has no path whitelist, deny cannot create one."""
        session = IntentContract()
        deny = IntentContract(only_paths=["./src"])
        result = merge_contracts(session, deny)
        assert result.only_paths == []

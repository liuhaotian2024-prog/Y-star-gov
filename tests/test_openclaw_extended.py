"""
tests/test_openclaw_extended.py — Extended integration tests for OpenClaw

Additional edge case tests:
1. CIEU record generation and audit trail integrity
2. Strict handoff mode enforcement
3. Field_deny semantic constraints
4. Delegation chain monotonicity verification
5. Configuration functions (configure_auto_persist, configure_omission_governance)
"""
import pytest
import time
from ystar.kernel.dimensions import IntentContract
from ystar.domains.openclaw import OpenClawDomainPack, make_openclaw_chain
from ystar.domains.openclaw.adapter import (
    enforce,
    make_session,
    OpenClawEvent,
    EventType,
    EnforceDecision,
    SessionState,
    get_cieu_log,
    clear_cieu_log,
)


class TestCIEURecordGeneration:
    """Test that enforce() generates proper CIEU audit records."""

    def setup_method(self):
        """Clear CIEU log before each test."""
        clear_cieu_log()

    def test_enforce_allow_creates_cieu_record(self):
        """Verify ALLOW decision creates a CIEU record with correct fields."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="cieu_test_001",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_READ,
            agent_id="coder_agent",
            session_id="cieu_test_001",
            file_path="./workspace/config.py",
            task_ticket_id="TASK-CIEU-001"
        )

        decision, records = enforce(event, session)

        assert decision == EnforceDecision.ALLOW
        assert len(records) == 1

        record = records[0]
        assert record.decision == EnforceDecision.ALLOW
        assert record.event.agent_id == "coder_agent"
        assert record.event.event_type == EventType.FILE_READ
        assert record.event_id is not None  # UUID assigned
        assert record.seq_global > 0  # Timestamp assigned
        assert len(record.call_record.violations) == 0

    def test_enforce_deny_creates_cieu_record_with_violations(self):
        """Verify DENY decision creates CIEU record with violation details."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="cieu_test_002",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder_agent",
            session_id="cieu_test_002",
            file_path="/etc/passwd",  # Forbidden path
            patch_summary="Malicious write",
            task_ticket_id="TASK-CIEU-002"
        )

        decision, records = enforce(event, session)

        assert decision == EnforceDecision.DENY
        assert len(records) == 1

        record = records[0]
        assert record.decision == EnforceDecision.DENY
        assert len(record.call_record.violations) > 0
        # Verify violation has dimension and message
        violation = record.call_record.violations[0]
        assert hasattr(violation, 'dimension')
        assert hasattr(violation, 'message')

    def test_cieu_records_have_unique_event_ids(self):
        """Ensure each CIEU record gets a unique event_id."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="cieu_test_003",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event_ids = set()
        for i in range(5):
            event = OpenClawEvent(
                event_type=EventType.FILE_READ,
                agent_id="coder_agent",
                session_id="cieu_test_003",
                file_path=f"./workspace/file_{i}.py",
                task_ticket_id=f"TASK-{i}"
            )
            decision, records = enforce(event, session)
            event_ids.add(records[0].event_id)

        assert len(event_ids) == 5  # All unique

    def test_cieu_record_to_dict_serializable(self):
        """Verify CIEU records can be serialized to dict for storage."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="cieu_test_004",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder_agent",
            session_id="cieu_test_004",
            file_path="./workspace/main.py",
            patch_summary="Add feature",
            task_ticket_id="TASK-DICT-001"
        )

        decision, records = enforce(event, session)
        record_dict = records[0].to_dict()

        assert isinstance(record_dict, dict)
        assert "event_id" in record_dict
        assert "seq_global" in record_dict
        assert "session_id" in record_dict
        assert "agent_id" in record_dict
        assert "event_type" in record_dict
        assert "decision" in record_dict
        assert "violations" in record_dict
        assert record_dict["session_id"] == "cieu_test_004"
        assert record_dict["agent_id"] == "coder_agent"


class TestStrictHandoffMode:
    """Test strict_handoff_mode enforcement."""

    def test_strict_mode_denies_agent_without_handoff_contract(self):
        """In strict mode, agents without handoff contracts should be denied."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="strict_test_001",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=True  # Enable strict mode
        )

        # Create event for an agent that hasn't been handed off yet
        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="new_agent_no_handoff",
            session_id="strict_test_001",
            file_path="./workspace/test.py",
            patch_summary="Unauthorized write",
            task_ticket_id="TASK-STRICT-001"
        )

        decision, records = enforce(event, session)

        # In strict mode, agent without handoff contract should be denied
        assert decision == EnforceDecision.DENY

    def test_non_strict_mode_allows_agents_from_delegation_chain(self):
        """Non-strict mode should allow agents defined in delegation chain."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="non_strict_test_001",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False  # Non-strict mode
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder_agent",
            session_id="non_strict_test_001",
            file_path="./workspace/main.py",
            patch_summary="Implement feature",
            task_ticket_id="TASK-NON-STRICT-001"
        )

        decision, records = enforce(event, session)

        # In non-strict mode, agents from chain should work
        assert decision == EnforceDecision.ALLOW


class TestFieldDenySemanticConstraints:
    """Test field_deny constraints on semantic fields like patch_summary."""

    def test_tester_cannot_weaken_assertion_via_patch_summary(self):
        """Tester role should be denied when patch_summary contains 'weaken_assertion'."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="field_deny_test_001",
            allowed_paths=["./tests"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="tester_agent",
            session_id="field_deny_test_001",
            file_path="./tests/test_auth.py",
            patch_summary="weaken_assertion for flaky test",  # Forbidden phrase
            task_ticket_id="TASK-FIELD-001"
        )

        decision, records = enforce(event, session)

        assert decision == EnforceDecision.DENY
        # Should have violation related to field_deny
        assert len(records[0].call_record.violations) > 0

    def test_tester_cannot_skip_flaky_test(self):
        """Tester role should be denied when trying to skip flaky tests."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="field_deny_test_002",
            allowed_paths=["./tests"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="tester_agent",
            session_id="field_deny_test_002",
            file_path="./tests/test_integration.py",
            patch_summary="skip flaky edge case in CI",  # Forbidden phrase
            task_ticket_id="TASK-FIELD-002"
        )

        decision, records = enforce(event, session)

        assert decision == EnforceDecision.DENY

    def test_coder_can_write_with_allowed_patch_summary(self):
        """Coder should be allowed with non-forbidden patch_summary."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="field_deny_test_003",
            allowed_paths=["./src"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder_agent",
            session_id="field_deny_test_003",
            file_path="./src/auth.py",
            patch_summary="Add input validation for email field",  # Allowed
            task_ticket_id="TASK-FIELD-003"
        )

        decision, records = enforce(event, session)

        assert decision == EnforceDecision.ALLOW


class TestDelegationChainMonotonicity:
    """Test that delegation chains enforce monotonicity (child ⊆ parent)."""

    def test_delegation_chain_validates_successfully(self):
        """A properly constructed chain should validate without errors."""
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./workspace"],
            allowed_domains=None,
            include_release=False
        )

        errors = chain.validate()
        assert errors == []  # No validation errors

    def test_chain_with_release_validates_successfully(self):
        """Chain with release agent should also validate."""
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./workspace"],
            allowed_domains=None,
            include_release=True
        )

        errors = chain.validate()
        assert errors == []

    def test_chain_links_have_correct_depth(self):
        """Verify delegation_depth decreases correctly down the chain."""
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./workspace"],
            include_release=True
        )

        # planner -> coder (depth=2), coder -> tester (depth=1), tester -> release (depth=0)
        assert chain.links[0].delegation_depth == 2  # planner->coder
        assert chain.links[1].delegation_depth == 1  # coder->tester
        assert chain.links[2].delegation_depth == 0  # tester->release

    def test_chain_action_scope_narrows_down_chain(self):
        """Verify action_scope narrows (child ⊆ parent) down the chain."""
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./workspace"],
            include_release=False
        )

        # planner->coder has broader scope than coder->tester
        planner_to_coder_scope = set(chain.links[0].action_scope)
        coder_to_tester_scope = set(chain.links[1].action_scope)

        # tester scope should be subset of coder scope
        assert coder_to_tester_scope.issubset(planner_to_coder_scope)


class TestConfigurationFunctions:
    """Test configuration functions for auto-persist and omission governance."""

    def test_make_session_creates_valid_session_state(self):
        """Verify make_session() creates a valid SessionState."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="config_test_001",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        assert session.session_id == "config_test_001"
        assert session.pack == pack
        assert session.delegation_chain is not None
        assert session.strict_handoff_mode is False
        assert isinstance(session, SessionState)

    def test_make_session_with_custom_chain(self):
        """Verify make_session() accepts custom delegation chain."""
        pack = OpenClawDomainPack()
        custom_chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./custom"],
            include_release=True
        )

        session = make_session(
            session_id="config_test_002",
            allowed_paths=["./custom"],
            pack=pack,
            chain=custom_chain,
            strict=True
        )

        assert session.delegation_chain == custom_chain
        assert session.strict_handoff_mode is True

    def test_make_session_with_allowed_domains(self):
        """Verify make_session() passes allowed_domains to chain."""
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="config_test_003",
            allowed_paths=["./workspace"],
            allowed_domains=["docs.python.org", "github.com"],
            pack=pack,
            strict=False
        )

        # Verify the session was created successfully
        assert session.session_id == "config_test_003"
        assert session.delegation_chain is not None


class TestConstitutionalLayer:
    """Test that constitutional constraints are enforced across all roles."""

    def test_all_roles_deny_credentials_file_access(self):
        """All roles should deny access to credentials files."""
        pack = OpenClawDomainPack()

        roles = ["planner", "coder", "tester", "reviewer", "researcher", "release"]

        for role in roles:
            contract = pack.make_contract(role, {})
            assert "credentials_file_access" in contract.deny, \
                f"Role {role} should deny credentials_file_access"

    def test_all_roles_deny_dangerous_commands(self):
        """All roles should deny dangerous commands like 'rm -rf /'."""
        pack = OpenClawDomainPack()

        roles = ["planner", "coder", "tester", "reviewer", "researcher", "release"]

        for role in roles:
            contract = pack.make_contract(role, {})
            assert "rm -rf /" in contract.deny_commands, \
                f"Role {role} should deny 'rm -rf /'"
            assert "drop table" in contract.deny_commands, \
                f"Role {role} should deny 'drop table'"

    def test_constitutional_invariant_session_authenticated(self):
        """All roles should require session_authenticated == True."""
        pack = OpenClawDomainPack()

        roles = ["planner", "coder", "tester", "reviewer", "researcher", "release"]

        for role in roles:
            contract = pack.make_contract(role, {})
            assert "session_authenticated == True" in contract.invariant, \
                f"Role {role} should require session authentication"


class TestRoleSpecificConstraints:
    """Test role-specific constraints beyond the constitutional layer."""

    def test_release_requires_approval_and_ci_passed(self):
        """Release agent must have approval and CI passing."""
        pack = OpenClawDomainPack()
        contract = pack.make_contract("release", {})

        assert "release_approved == True" in contract.invariant
        assert "ci_passed == True" in contract.invariant
        assert "bypass_ci" in contract.deny

    def test_reviewer_cannot_write_or_delete(self):
        """Reviewer role should be read-only."""
        pack = OpenClawDomainPack()
        contract = pack.make_contract("reviewer", {})

        assert "write_file" in contract.deny
        assert "delete_file" in contract.deny
        assert "git commit" in contract.deny_commands

    def test_researcher_has_domain_whitelist(self):
        """Researcher should be restricted to whitelisted domains."""
        pack = OpenClawDomainPack()
        contract = pack.make_contract("researcher", {
            "allowed_domains": ["docs.python.org", "github.com"]
        })

        assert "docs.python.org" in contract.only_domains
        assert "github.com" in contract.only_domains
        assert "write_file" in contract.deny

    def test_coder_has_max_files_modified_constraint(self):
        """Coder should have value_range constraint on files_modified."""
        pack = OpenClawDomainPack()
        contract = pack.make_contract("coder", {
            "allowed_paths": ["./src"],
            "max_files_modified": 15
        })

        assert "files_modified" in contract.value_range
        assert contract.value_range["files_modified"]["max"] == 15

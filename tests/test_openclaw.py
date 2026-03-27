"""
tests/test_openclaw.py — Integration tests for OpenClaw domain pack

Tests cover:
1. OpenClawDomainPack: all 6 role contracts load correctly
2. enforce(): ALLOW on permitted actions
3. enforce(): DENY on forbidden paths
4. extract_params(): all 10 event types produce correct parameters
"""
import pytest
from ystar.kernel.dimensions import IntentContract
from ystar.domains.openclaw import OpenClawDomainPack, make_openclaw_chain
from ystar.domains.openclaw.adapter import (
    enforce,
    extract_params,
    make_session,
    OpenClawEvent,
    EventType,
    EnforceDecision,
    SessionState,
)


class TestOpenClawDomainPack:
    """Test that all 6 role contracts in OpenClawDomainPack are valid IntentContracts."""

    def test_pack_initialization(self):
        pack = OpenClawDomainPack(
            workspace_root="./workspace",
            doc_domains=["docs.python.org", "github.com"]
        )
        assert pack.domain_name == "openclaw"
        assert pack.workspace_root == "./workspace"
        assert "docs.python.org" in pack.doc_domains

    def test_planner_contract_is_valid(self):
        pack = OpenClawDomainPack()
        contract = pack.make_contract("planner", {"allowed_paths": ["./src"]})
        assert isinstance(contract, IntentContract)
        assert contract.name == "planner"
        assert "./src" in contract.only_paths
        assert "write_outside_scope" in contract.deny

    def test_coder_contract_is_valid(self):
        pack = OpenClawDomainPack()
        contract = pack.make_contract("coder", {"allowed_paths": ["./src"]})
        assert isinstance(contract, IntentContract)
        assert contract.name == "coder"
        assert "write_outside_scope" in contract.deny
        assert "git push" in contract.deny_commands

    def test_tester_contract_is_valid(self):
        pack = OpenClawDomainPack()
        contract = pack.make_contract("tester", {
            "allowed_paths": ["./src"],
            "test_paths": ["./tests"]
        })
        assert isinstance(contract, IntentContract)
        assert contract.name == "tester"
        assert "modify_src_without_approval" in contract.deny
        # Check field_deny for semantic constraints
        assert "patch_summary" in contract.field_deny
        assert "weaken_assertion" in contract.field_deny["patch_summary"]

    def test_reviewer_contract_is_valid(self):
        pack = OpenClawDomainPack()
        contract = pack.make_contract("reviewer", {"allowed_paths": ["./src"]})
        assert isinstance(contract, IntentContract)
        assert contract.name == "reviewer"
        assert "write_file" in contract.deny
        assert "approve_own_pr" in contract.deny

    def test_researcher_contract_is_valid(self):
        pack = OpenClawDomainPack()
        contract = pack.make_contract("researcher", {
            "allowed_domains": ["docs.python.org"]
        })
        assert isinstance(contract, IntentContract)
        assert contract.name == "researcher"
        assert "docs.python.org" in contract.only_domains
        assert "write_file" in contract.deny

    def test_release_contract_is_valid(self):
        pack = OpenClawDomainPack()
        contract = pack.make_contract("release", {})
        assert isinstance(contract, IntentContract)
        assert contract.name == "release"
        assert "bypass_ci" in contract.deny
        assert "release_approved == True" in contract.invariant
        assert "ci_passed == True" in contract.invariant

    def test_all_contracts_inherit_constitutional_layer(self):
        """All role contracts should inherit constitutional constraints."""
        pack = OpenClawDomainPack()
        for role in ["planner", "coder", "tester", "reviewer", "researcher", "release"]:
            contract = pack.make_contract(role, {})
            # Constitutional constraints from _openclaw_constitution()
            assert "production_bypass" in contract.deny
            assert "credentials_file_access" in contract.deny
            assert "rm -rf /" in contract.deny_commands
            assert "drop table" in contract.deny_commands


class TestEnforceAllow:
    """Test enforce() returns ALLOW on permitted actions."""

    def test_coder_can_write_to_allowed_workspace(self):
        pack = OpenClawDomainPack(workspace_root="./workspace")
        session = make_session(
            session_id="test_session",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder_agent",
            session_id="test_session",
            file_path="./workspace/main.py",
            patch_summary="Add logging",
            task_ticket_id="TASK-001"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.ALLOW
        assert len(records) == 1
        assert records[0].decision == EnforceDecision.ALLOW

    def test_researcher_can_fetch_allowed_domain(self):
        pack = OpenClawDomainPack(doc_domains=["docs.python.org"])
        chain = make_openclaw_chain(pack, allowed_paths=["./src"])
        session = make_session(
            session_id="test_session",
            pack=pack,
            chain=chain,
            strict=False
        )
        # Manually register researcher contract
        researcher_contract = pack.make_contract("researcher", {
            "allowed_domains": ["docs.python.org"]
        })
        session.agent_contracts["researcher_agent"] = researcher_contract

        event = OpenClawEvent(
            event_type=EventType.WEB_FETCH,
            agent_id="researcher_agent",
            session_id="test_session",
            url="https://docs.python.org/3/library/os.html",
            task_ticket_id="TASK-002"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.ALLOW

    def test_tester_can_run_tests(self):
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="test_session",
            allowed_paths=["./tests"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.CMD_EXEC,
            agent_id="tester_agent",
            session_id="test_session",
            command="pytest tests/test_main.py -v",
            task_ticket_id="TASK-003"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.ALLOW


class TestEnforceDeny:
    """Test enforce() returns DENY on forbidden paths and actions."""

    def test_coder_cannot_write_to_etc_passwd(self):
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="test_session",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder_agent",
            session_id="test_session",
            file_path="/etc/passwd",
            patch_summary="Malicious write",
            task_ticket_id="TASK-004"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.DENY
        assert len(records) == 1
        assert records[0].decision == EnforceDecision.DENY

    def test_coder_cannot_run_rm_rf_command(self):
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="test_session",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.CMD_EXEC,
            agent_id="coder_agent",
            session_id="test_session",
            command="rm -rf /important",
            task_ticket_id="TASK-005"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.DENY

    def test_coder_cannot_write_outside_workspace(self):
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="test_session",
            allowed_paths=["./workspace"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder_agent",
            session_id="test_session",
            file_path="/production/database.sql",
            patch_summary="Forbidden write",
            task_ticket_id="TASK-006"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.DENY

    def test_researcher_cannot_fetch_forbidden_domain(self):
        pack = OpenClawDomainPack(doc_domains=["docs.python.org"])
        session = make_session(
            session_id="test_session",
            allowed_paths=["./src"],
            pack=pack,
            strict=False
        )
        researcher_contract = pack.make_contract("researcher", {
            "allowed_domains": ["docs.python.org"]
        })
        session.agent_contracts["researcher_agent"] = researcher_contract

        event = OpenClawEvent(
            event_type=EventType.WEB_FETCH,
            agent_id="researcher_agent",
            session_id="test_session",
            url="https://evil.com/exfiltrate",
            task_ticket_id="TASK-007"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.DENY

    def test_reviewer_cannot_write_files(self):
        pack = OpenClawDomainPack()
        session = make_session(
            session_id="test_session",
            allowed_paths=["./src"],
            pack=pack,
            strict=False
        )

        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="reviewer_agent",
            session_id="test_session",
            file_path="./src/main.py",
            patch_summary="Reviewer should not write",
            task_ticket_id="TASK-008"
        )

        decision, records = enforce(event, session)
        assert decision == EnforceDecision.DENY


class TestExtractParams:
    """Test extract_params() for all 10 event types."""

    def test_file_write_extracts_path_and_patch_summary(self):
        event = OpenClawEvent(
            event_type=EventType.FILE_WRITE,
            agent_id="coder",
            session_id="s1",
            file_path="./src/main.py",
            patch_summary="Fix bug",
            task_ticket_id="T-001"
        )
        params = extract_params(event)
        assert params["file_path"] == "./src/main.py"
        assert params["patch_summary"] == "Fix bug"
        assert params["action"] == "file_write"
        assert params["task_ticket_exists"] is True

    def test_file_read_extracts_path(self):
        event = OpenClawEvent(
            event_type=EventType.FILE_READ,
            agent_id="reviewer",
            session_id="s1",
            file_path="./src/config.py",
            task_ticket_id="T-002"
        )
        params = extract_params(event)
        assert params["file_path"] == "./src/config.py"
        assert params["action"] == "file_read"

    def test_cmd_exec_extracts_command(self):
        event = OpenClawEvent(
            event_type=EventType.CMD_EXEC,
            agent_id="tester",
            session_id="s1",
            command="pytest tests/ -v",
            task_ticket_id="T-003"
        )
        params = extract_params(event)
        assert params["command"] == "pytest tests/ -v"
        assert params["action"] == "cmd_exec"

    def test_web_fetch_extracts_url(self):
        event = OpenClawEvent(
            event_type=EventType.WEB_FETCH,
            agent_id="researcher",
            session_id="s1",
            url="https://docs.python.org",
            task_ticket_id="T-004"
        )
        params = extract_params(event)
        assert params["url"] == "https://docs.python.org"
        assert params["action"] == "web_fetch"

    def test_code_exec_extracts_code_length(self):
        event = OpenClawEvent(
            event_type=EventType.CODE_EXEC,
            agent_id="coder",
            session_id="s1",
            code="print('hello')",
            task_ticket_id="T-005"
        )
        params = extract_params(event)
        assert params["code_length"] == len("print('hello')")
        assert params["action"] == "code_exec"

    def test_subagent_spawn_extracts_parent_child_and_task(self):
        event = OpenClawEvent(
            event_type=EventType.SUBAGENT_SPAWN,
            agent_id="planner",
            session_id="s1",
            parent_agent_id="orchestrator",
            child_agent_id="coder_agent",
            task_description="Write unit tests",
            action_scope=["write_test", "run_test"],
            task_ticket_id="T-006"
        )
        params = extract_params(event)
        assert params["parent_agent_id"] == "orchestrator"
        assert params["child_agent_id"] == "coder_agent"
        assert params["task_description"] == "Write unit tests"
        assert params["action_scope"] == ["write_test", "run_test"]
        assert params["action"] == "subagent_spawn"

    def test_handoff_extracts_from_to_agents(self):
        event = OpenClawEvent(
            event_type=EventType.HANDOFF,
            agent_id="tester",
            session_id="s1",
            parent_agent_id="coder",
            task_description="Validate test coverage",
            action_scope=["run_test"],
            task_ticket_id="T-007"
        )
        params = extract_params(event)
        assert params["from_agent"] == "coder"
        assert params["to_agent"] == "tester"
        assert params["task_description"] == "Validate test coverage"
        assert params["action"] == "handoff"

    def test_session_start_extracts_base_params(self):
        event = OpenClawEvent(
            event_type=EventType.SESSION_START,
            agent_id="orchestrator",
            session_id="s1",
            task_ticket_id="T-008"
        )
        params = extract_params(event)
        assert params["action"] == "session_start"
        assert params["agent_id"] == "orchestrator"
        assert params["session_authenticated"] is True

    def test_skill_invoke_extracts_skill_and_tool_name(self):
        event = OpenClawEvent(
            event_type=EventType.SKILL_INVOKE,
            agent_id="coder",
            session_id="s1",
            skill_name="python-linter",
            tool_name="pylint",
            task_ticket_id="T-009"
        )
        params = extract_params(event)
        assert params["skill_name"] == "python-linter"
        assert params["tool_name"] == "pylint"
        assert params["action"] == "skill_invoke"

    def test_mcp_tool_call_extracts_tool_and_url(self):
        event = OpenClawEvent(
            event_type=EventType.MCP_TOOL_CALL,
            agent_id="researcher",
            session_id="s1",
            tool_name="http_fetch",
            tool_args={"url": "https://api.example.com/data"},
            task_ticket_id="T-010"
        )
        params = extract_params(event)
        assert params["tool_name"] == "http_fetch"
        assert params["url"] == "https://api.example.com/data"
        assert params["action"] == "mcp_tool_call"

    def test_task_ticket_exists_is_false_when_no_ticket(self):
        event = OpenClawEvent(
            event_type=EventType.FILE_READ,
            agent_id="reviewer",
            session_id="s1",
            file_path="./src/main.py"
            # No task_ticket_id
        )
        params = extract_params(event)
        assert params["task_ticket_exists"] is False


class TestMakeOpenClawChain:
    """Test make_openclaw_chain() creates valid delegation chains."""

    def test_chain_creates_planner_to_coder_to_tester(self):
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./src", "./tests"]
        )
        assert chain is not None
        assert len(chain.links) == 2  # planner->coder, coder->tester
        assert chain.links[0].principal == "planner"
        assert chain.links[0].actor == "coder_agent"
        assert chain.links[1].principal == "coder_agent"
        assert chain.links[1].actor == "tester_agent"

    def test_chain_with_release_adds_third_link(self):
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./src"],
            include_release=True
        )
        assert len(chain.links) == 3  # planner->coder->tester->release
        assert chain.links[2].principal == "tester_agent"
        assert chain.links[2].actor == "release_agent"

    def test_chain_validates_successfully(self):
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(
            pack=pack,
            allowed_paths=["./src"]
        )
        errors = chain.validate()
        assert errors == []  # No validation errors


class TestSessionState:
    """Test SessionState contract resolution."""

    def test_get_contract_for_returns_coder_contract(self):
        pack = OpenClawDomainPack()
        chain = make_openclaw_chain(pack, allowed_paths=["./src"])
        state = SessionState(
            session_id="s1",
            pack=pack,
            delegation_chain=chain
        )
        contract = state.get_contract_for("coder_agent")
        assert contract is not None
        assert "coder" in contract.name.lower()

    def test_get_contract_for_returns_none_for_unknown_agent(self):
        pack = OpenClawDomainPack()
        state = SessionState(
            session_id="s1",
            pack=pack
        )
        contract = state.get_contract_for("unknown_agent_xyz")
        assert contract is None

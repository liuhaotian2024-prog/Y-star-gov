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
        assert os.path.exists(os.path.join(_PROJECT_ROOT, "docs/development/ARCHITECTURE_FREEZE_v1.md"))

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


# ═══════════════════════════════════════════════════════════════════════════════
# R9: Forbid Direct Constitution Loading & Hardcoded Self-Governance
# ═══════════════════════════════════════════════════════════════════════════════

def _read_source(filepath: str) -> str:
    """Read file source, stripping comment lines."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def _non_comment_lines(source: str) -> list:
    """Return lines that are not pure comments."""
    return [
        line for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


class TestForbidDirectConstitutionLoading:
    """R9: Architecture tests that forbid legacy constitution access patterns."""

    def test_path_a_no_direct_open_constitution(self):
        """meta_agent.py must not use open(_PATH_A_AGENTS_MD...) in non-comment lines.

        All constitution access must go through ConstitutionProvider.
        """
        filepath = os.path.join(_YSTAR_ROOT, "path_a", "meta_agent.py")
        lines = _non_comment_lines(_read_source(filepath))
        matches = [
            line for line in lines
            if "open(_PATH_A_AGENTS_MD" in line
            or "open(self._constitution_path" in line
        ]
        assert len(matches) == 0, (
            f"Path A meta_agent.py still has direct constitution file opens: {matches}"
        )

    def test_path_b_no_static_constitution_hash(self):
        """path_b_agent.py must not have _CONSTITUTION_HASH = ... at module level.

        Hash must be computed at runtime in __init__, not at import time.
        """
        filepath = os.path.join(_YSTAR_ROOT, "path_b", "path_b_agent.py")
        source = _read_source(filepath)
        lines = _non_comment_lines(source)
        matches = [
            line for line in lines
            if "_CONSTITUTION_HASH" in line
            and "=" in line
            and "self." not in line
            # Exclude lines inside class bodies (they start with whitespace)
            and not line.startswith(" ") and not line.startswith("\t")
        ]
        assert len(matches) == 0, (
            f"Path B still has module-level _CONSTITUTION_HASH assignment: {matches}"
        )

    def test_path_b_self_gov_uses_policy(self):
        """run_one_cycle must not have inline deny=['/etc'...] for self-governance.

        Self-governance contract must come from self.policy fields.
        """
        filepath = os.path.join(_YSTAR_ROOT, "path_b", "path_b_agent.py")
        source = _read_source(filepath)

        # Find the run_one_cycle method body
        in_run_one_cycle = False
        inline_deny_found = False
        for line in source.splitlines():
            if "def run_one_cycle" in line:
                in_run_one_cycle = True
                continue
            if in_run_one_cycle and line.strip().startswith("def "):
                in_run_one_cycle = False
            if in_run_one_cycle and 'deny=["/etc"' in line:
                inline_deny_found = True
                break

        assert not inline_deny_found, (
            "run_one_cycle still has hardcoded deny=[\"/etc\"...] — "
            "should use self.policy.self_governance_deny"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# R10: Foundation Sovereignty — Scope, Compiler, Provider Authority Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestScopeProtocolSovereignty:
    """Scope encoding is the single authority for prefix logic."""

    def test_engine_uses_split_scopes(self):
        """engine.py must import split_scopes, not decode inline."""
        filepath = os.path.join(_YSTAR_ROOT, "kernel", "engine.py")
        source = _read_source(filepath)
        assert "split_scopes" in source, (
            "engine.py must use split_scopes() from scope_encoding"
        )
        # Must NOT have the old inline pattern
        for old_pattern in ['p[7:]', 'p[9:]', 'p[16:]']:
            assert old_pattern not in source, (
                f"engine.py still has inline '{old_pattern}' — use scope_encoding decode functions"
            )

    def test_scope_decode_roundtrip(self):
        """Encode → decode roundtrip must be lossless."""
        from ystar.kernel.scope_encoding import (
            encode_module_scope, decode_module_scope,
            encode_external_scope, decode_external_scope,
            encode_external_domain, decode_external_domain,
        )
        modules = ["causal_engine", "omission_engine"]
        encoded = encode_module_scope(modules)
        assert decode_module_scope(encoded) == modules

        ext_encoded = [encode_external_scope("agent_42")]
        assert decode_external_scope(ext_encoded) == ["agent_42"]

        dom_encoded = [encode_external_domain("finance")]
        assert decode_external_domain(dom_encoded) == ["finance"]

    def test_split_scopes_mixed(self):
        """split_scopes correctly separates a mixed list."""
        from ystar.kernel.scope_encoding import split_scopes
        mixed = ["module:x", "external:a", "external_domain:d", "/tmp"]
        m, e, d, p = split_scopes(mixed)
        assert m == ["x"]
        assert e == ["a"]
        assert d == ["d"]
        assert p == ["/tmp"]

    def test_validate_scope(self):
        """validate_scope rejects empty and malformed scopes."""
        from ystar.kernel.scope_encoding import validate_scope
        assert validate_scope("module:causal_engine") is True
        assert validate_scope("external:agent_42") is True
        assert validate_scope("external_domain:finance") is True
        assert validate_scope("/etc/hosts") is True
        assert validate_scope("module:") is False
        assert validate_scope("") is False


class TestCompilerSovereignty:
    """CompiledContractBundle has full audit fields."""

    def test_bundle_has_timestamp(self):
        """CompiledContractBundle must include compiled_at timestamp."""
        from ystar.kernel.compiler import CompiledContractBundle
        from ystar.kernel.dimensions import IntentContract
        bundle = CompiledContractBundle(
            contract=IntentContract(name="test"),
            source_hash="abc",
            source_ref="test.md",
        )
        assert bundle.compiled_at > 0, "compiled_at must auto-populate"

    def test_bundle_has_amendment_fields(self):
        """CompiledContractBundle must track amendment_version and previous_hash."""
        from ystar.kernel.compiler import CompiledContractBundle
        from ystar.kernel.dimensions import IntentContract
        bundle = CompiledContractBundle(
            contract=IntentContract(name="test"),
            source_hash="abc",
            source_ref="test.md",
            previous_hash="old_hash",
            amendment_version=2,
        )
        assert bundle.previous_hash == "old_hash"
        assert bundle.amendment_version == 2


class TestProviderSovereignty:
    """ConstitutionProvider has version tracking and hash verification."""

    def test_provider_has_resolve_latest(self):
        """ConstitutionProvider must expose resolve_latest()."""
        from ystar.kernel.contract_provider import ConstitutionProvider
        provider = ConstitutionProvider()
        assert hasattr(provider, "resolve_latest")

    def test_provider_has_verify_hash(self):
        """ConstitutionProvider must expose verify_hash()."""
        from ystar.kernel.contract_provider import ConstitutionProvider
        provider = ConstitutionProvider()
        assert hasattr(provider, "verify_hash")

    def test_provider_has_get_version(self):
        """ConstitutionProvider must expose get_version()."""
        from ystar.kernel.contract_provider import ConstitutionProvider
        provider = ConstitutionProvider()
        assert hasattr(provider, "get_version")

    def test_provider_version_increments(self):
        """Each resolve after invalidation must increment version."""
        import tempfile, os
        from ystar.kernel.contract_provider import ConstitutionProvider
        provider = ConstitutionProvider()
        # Create a temp constitution file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Test Constitution\n- rule: be good\n")
            tmp_path = f.name
        try:
            bundle1 = provider.resolve(tmp_path)
            assert bundle1.version == 1
            provider.invalidate_cache(tmp_path)
            bundle2 = provider.resolve(tmp_path)
            assert bundle2.version == 2
            assert bundle2.previous_hash == bundle1.source_hash
        finally:
            os.unlink(tmp_path)


class TestCausalFoundationGeneralized:
    """CausalEngine must be domain-agnostic (configurable DAG)."""

    def test_default_dag_is_swoh(self):
        """Default DAG uses S/W/O/H governance variables."""
        from ystar.governance.causal_engine import CausalEngine
        engine = CausalEngine()
        assert 'S' in engine._equations
        assert 'H' in engine._equations

    def test_custom_dag_accepted(self):
        """CausalEngine accepts a custom DAG for non-governance domains."""
        from ystar.governance.causal_engine import CausalEngine
        custom_dag = {'A': ['B'], 'B': ['C']}
        engine = CausalEngine(dag_edges=custom_dag)
        assert 'A' in engine._equations
        assert 'B' in engine._equations
        assert 'C' in engine._equations
        assert engine._equations['B'].parents == ['A']

    def test_governance_loop_extractions_exist(self):
        """GovernanceLoop must delegate to extracted causal_feedback and proposal_submission."""
        source_path = os.path.join(_YSTAR_ROOT, "governance", "governance_loop.py")
        source = _read_source(source_path)
        assert "causal_feedback" in source, "GovernanceLoop must import from causal_feedback"


def test_governance_pipeline_e2e():
    """
    End-to-end integration test for governance pipeline.

    Verifies data flow from session config through to GovernanceLoop suggestions:
    1. Session config with obligation_timing
    2. OmissionStore contains registered obligations
    3. ReportEngine produces non-zero KPIs
    4. GovernanceLoop produces suggestions when health is degraded

    This test prevents the "wired but not flowing" failure mode where
    interfaces exist but data never propagates through the pipeline.
    """
    import tempfile
    import os
    import json
    from ystar.session import Policy
    from ystar.kernel.dimensions import IntentContract

    # Create a minimal session config with obligation_timing
    session_cfg = {
        "session_id": "test_e2e",
        "cieu_db": tempfile.mktemp(suffix=".db"),
        "contract": {
            "dimensions": [
                {
                    "name": "delegation",
                    "rules": [
                        {
                            "id": "rule_test_delegation",
                            "kind": "obligation",
                            "condition": "action == 'test_action'",
                            "message": "Test obligation",
                        }
                    ]
                }
            ],
            "obligation_timing": {
                "rule_test_delegation": {
                    "postcondition_timeout_secs": 60.0,
                    "soft_deadline_secs": 30.0,
                }
            }
        }
    }

    try:
        # Step 1: Verify contract parses correctly
        contract_dict = session_cfg["contract"]
        contract = IntentContract.from_dict(contract_dict)
        assert contract is not None, "Contract should parse"

        # Step 2: Setup omission system with timing
        from ystar.governance.omission_store import OmissionStore
        from ystar.governance.omission_rules import reset_registry
        from ystar.governance.omission_engine import OmissionEngine
        from ystar.governance.omission_models import TrackedEntity, GovernanceEvent, GEventType, EntityStatus
        from ystar.governance.cieu_store import CIEUStore
        from ystar.domains.openclaw.accountability_pack import apply_openclaw_accountability_pack

        omission_db = tempfile.mktemp(suffix="_omission.db")
        cieu_db = session_cfg["cieu_db"]

        store = OmissionStore(db_path=omission_db)
        registry = reset_registry()
        # Use simple timing config instead of custom rules
        simple_contract_dict = {
            "name": "test_policy",
            "obligation_timing": {
                "delegation": 300.0,
                "acknowledgement": 120.0,
            }
        }
        simple_contract = IntentContract.from_dict(simple_contract_dict)
        apply_openclaw_accountability_pack(registry, contract=simple_contract)

        cieu_store = CIEUStore(cieu_db)
        engine = OmissionEngine(store=store, registry=registry, cieu_store=cieu_store)

        # Step 3: Create entity and trigger obligation via ENTITY_CREATED event
        import time
        now = time.time()

        entity = TrackedEntity(
            entity_id="task_001",
            entity_type="task",
            current_owner_id="agent_a",
            initiator_id="agent_system",
            status=EntityStatus.ACTIVE,
        )
        engine.register_entity(entity)

        event = GovernanceEvent(
            event_type=GEventType.ENTITY_CREATED,
            entity_id="task_001",
            actor_id="agent_a",
            ts=now,
        )
        engine.ingest_event(event)

        # Verify obligation was created
        obligations = store.list_obligations()
        assert len(obligations) > 0, f"Obligation should be created in store from delegation event. Got {len(obligations)} obligations."

        # Step 4: Create ReportEngine and verify it reads from store
        from ystar.governance.reporting import ReportEngine
        report_engine = ReportEngine(omission_store=store)
        report = report_engine.baseline_report()

        assert report.obligations is not None, "Report should have obligation data"
        total_obs = (report.obligations.created_total + report.obligations.pending_total +
                     report.obligations.fulfilled_total + report.obligations.expired_total)
        assert total_obs > 0, f"Report should show registered obligations. Got: created={report.obligations.created_total}, pending={report.obligations.pending_total}"

        # Step 5: Create GovernanceLoop and verify observation
        from ystar.governance.governance_loop import GovernanceLoop
        gloop = GovernanceLoop(report_engine=report_engine)

        obs = gloop.observe_from_report_engine()
        assert obs is not None, "Observation should be created"

        # Step 6: Simulate time passing to make obligation overdue
        # Update obligations to be overdue (account for grace_period_secs)
        for ob in store.list_obligations():
            # Set due_at far enough in the past to exceed effective_due_at = due_at + grace_period_secs
            ob.due_at = time.time() - 1000  # 1000 seconds overdue (exceeds any grace period)
            ob.grace_period_secs = 0  # Disable grace period for test clarity
            store.update_obligation(ob)
        # Run scan to detect violations
        scan_result = engine.scan()

        # Debug: check what scan produced
        violations_after_scan = store.list_violations()
        obligations_after_scan = store.list_obligations()

        # Verify scan detected violations
        assert len(violations_after_scan) > 0, (
            f"Scan should detect violations. Scan result: {scan_result.summary()}, "
            f"Violations: {len(violations_after_scan)}, "
            f"Obligations: {[(ob.obligation_id, ob.status, ob.due_at, ob.effective_due_at) for ob in obligations_after_scan]}"
        )

        # Step 7: Re-observe and verify non-zero KPIs
        report2 = report_engine.baseline_report()
        obs2 = gloop.observe_from_report_engine()

        # At least ONE KPI should be non-zero (we have overdue obligations)
        has_nonzero = any([
            obs2.hard_overdue_rate > 0,
            obs2.omission_detection_rate > 0,
            obs2.obligation_expiry_rate > 0,
        ])
        assert has_nonzero, (
            f"At least one KPI should be non-zero. "
            f"Violations detected: {len(violations_after_scan)}, "
            f"Report obligations: created={report2.obligations.created_total}, "
            f"hard_overdue={report2.obligations.hard_overdue}, "
            f"soft_overdue={report2.obligations.soft_overdue}, "
            f"KPIs: {obs2.raw_kpis}"
        )

        # Step 8: Run tighten() and verify suggestions are generated
        result = gloop.tighten()

        # With degraded health and non-zero KPIs, we should get SOME output
        # (suggestions OR recommended action OR health != "unknown")
        assert result.overall_health != "unknown", "Health should be assessed"

        # If health is degraded and we have omission data, suggestion policy
        # should produce at least one suggestion OR a recommended action
        if result.overall_health in ("degraded", "critical"):
            has_output = (
                len(result.governance_suggestions) > 0 or
                result.recommended_action != ""
            )
            assert has_output, (
                f"Degraded health with omission data should produce suggestions or action. "
                f"Health: {result.overall_health}, Suggestions: {len(result.governance_suggestions)}, "
                f"Action: {result.recommended_action}"
            )

        # Cleanup
        if os.path.exists(session_cfg["cieu_db"]):
            os.unlink(session_cfg["cieu_db"])
        if os.path.exists(omission_db):
            os.unlink(omission_db)

    except Exception as e:
        # Cleanup on error
        if os.path.exists(session_cfg["cieu_db"]):
            os.unlink(session_cfg["cieu_db"])
        if 'omission_db' in locals() and os.path.exists(omission_db):
            os.unlink(omission_db)
        raise
        assert "proposal_submission" in source, "GovernanceLoop must import from proposal_submission"

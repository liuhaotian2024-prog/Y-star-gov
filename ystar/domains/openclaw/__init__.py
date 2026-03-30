"""
OpenClaw Domain Pack  v1.0.0  —  Reference Connector Implementation
====================================================================

This is Y*'s FIRST and REFERENCE connector implementation.
It demonstrates how to integrate any multi-agent framework with Y*.

Other frameworks can follow this same pattern:
  1. Inherit EventStreamConnector from ystar.integrations.base
  2. Implement connect() / stream_events() / send_decision()
  3. Translate framework events → WorkloadEvent
  4. Run WorkloadRunner.run(YourConnector(config)) for governance evaluation

See: ystar/integrations/openclaw.py for the connector implementation.
============================
Y* constraint domain pack for multi-agent coding environments
modelled on the OpenClaw / Claude Code architecture.

Agents modelled:
  planner          — decomposes tasks, defines scope
  coder            — writes / modifies source files
  tester           — runs tests, may modify test files
  reviewer         — read-only code review
  researcher       — fetches external documentation
  release          — packages and publishes artefacts

Constitutional layer (applies to ALL agents):
  - No production deployments without approval token
  - No shell commands that destroy data irreversibly
  - No access to credentials files
  - No exfiltration of source to external hosts

Iron law:  delegation monotonicity — every child contract must be a
           strict subset of its parent.  Enforced by DelegationChain.validate()
           via IntentContract.is_subset_of() (added in Y* v0.24.0).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ystar.kernel.dimensions import (
    IntentContract,
    ConstitutionalContract,
    DelegationContract,
    DelegationChain,
)


# ── Constitutional layer ──────────────────────────────────────────────────────

def _openclaw_constitution() -> ConstitutionalContract:
    """
    Constraints that bind every agent in an OpenClaw session,
    regardless of which role they hold.
    """
    return ConstitutionalContract(
        deny=[
            "production_bypass",          # skip CI/CD approval
            "credentials_file_access",    # .env, secrets.yaml, key files
            "exfiltrate_source",          # push source to external host without approval
            "overwrite_audit_log",        # tamper with CIEU records
        ],
        deny_commands=[
            "rm -rf /",
            "drop table",
            "kubectl delete namespace",
            "terraform destroy",
            "git push --force origin main",
        ],
        # ── 外部アクセスはデフォルト禁止 ──────────────────────────
        # only_domains=[] は engine.py では「制限なし」として動作するため、
        # 非 researcher ロールには明示的に空文字列のセンチネルを使う代わりに、
        # field_deny で URL パターンを拒否する方法で外部アクセスを防ぐ。
        only_domains=[],        # researcher ロールで上書きされる
        invariant=[
            "session_authenticated == True",
        ],
        # 外部への情報送信をdenyで防ぐ
        # exfiltrate_source は deny リストに含まれているが、
        # URL パラメータ経由の送信は only_domains で防ぐ必要がある
        field_deny={
            "url": [
                "evil",        # よく使われる攻撃ドメイン
                "ngrok.io",    # トンネリング
                "requestbin",  # データ収集
                "webhook.site",# データ収集
                "burpcollaborator", # セキュリティテスト悪用
            ],
        },
    )


# ── Role definitions ──────────────────────────────────────────────────────────

@dataclass
class OpenClawDomainPack:
    """
    Domain pack for OpenClaw-style multi-agent coding pipelines.

    Each role's make_contract() returns an IntentContract that:
      1. Enforces constitutional constraints (always applied)
      2. Adds role-specific constraints on top
      3. Is guaranteed to be ⊆ of any parent contract when used
         with make_delegation_chain()
    """

    domain_name: str = "openclaw"

    # configurable workspace root — all file ops must stay within
    workspace_root: str = field(default="./workspace")

    # allowed external documentation domains (researcher role)
    doc_domains: List[str] = field(default_factory=lambda: [
        "docs.python.org",
        "github.com",
        "docs.github.com",
        "pypi.org",
        "docs.anthropic.com",
        "claude.ai",
    ])

    def constitutional_contract(self) -> ConstitutionalContract:
        return _openclaw_constitution()

    def vocabulary(self) -> Dict[str, Any]:
        return {
            "domain": self.domain_name,
            "role_names": [
                "planner", "coder", "tester",
                "reviewer", "researcher", "release",
            ],
            "version": "1.0.0",
        }

    # ── per-role contracts ────────────────────────────────────────────────

    def make_contract(self, role: str, ctx: Optional[Dict[str, Any]] = None) -> IntentContract:
        ctx = ctx or {}
        constitution = self.constitutional_contract()

        makers = {
            "planner":    self._planner_contract,
            "coder":      self._coder_contract,
            "tester":     self._tester_contract,
            "reviewer":   self._reviewer_contract,
            "researcher": self._researcher_contract,
            "release":    self._release_contract,
        }
        if role not in makers:
            raise ValueError(
                f"Unknown OpenClaw role '{role}'. "
                f"Valid roles: {sorted(makers)}"
            )
        base = makers[role](ctx)
        return base.merge(constitution)

    def _planner_contract(self, ctx: Dict) -> IntentContract:
        """
        Planner: defines task scope and allowed paths.
        - May read any file in workspace
        - May NOT write files directly (delegates to coder)
        - Sets the only_paths scope for downstream agents
        """
        allowed_paths   = ctx.get("allowed_paths", [self.workspace_root])
        allowed_domains = ctx.get("allowed_domains", [])   # [] = 外部アクセス制限なし
        return IntentContract(
            deny=[
                "write_outside_scope",
                "skip_test_requirement",
                "bypass_review",
            ],
            deny_commands=["git push", "kubectl apply", "terraform apply"],
            only_paths=allowed_paths,
            only_domains=allowed_domains,   # 指定された場合のみ外部アクセスを制限
            invariant=["task_ticket_exists == True"],
            name="planner",
        )

    def _coder_contract(self, ctx: Dict) -> IntentContract:
        """
        Coder: implements changes within planner-approved scope.
        - File writes restricted to only_paths
        - Cannot weaken tests
        - Cannot deploy
        """
        allowed_paths = ctx.get("allowed_paths", [self.workspace_root])
        return IntentContract(
            deny=[
                "write_outside_scope",
                "delete_test_file",
                "skip_test_requirement",
                "bypass_review",
            ],
            field_deny={
                "patch_summary": ["weaken_assertion", "skip_flaky_test",
                                  "relax assertion",  "skip flaky"],
                "action":        ["weaken_assertion", "skip_flaky_test"],
            },
            deny_commands=[
                "git push", "kubectl apply",
                "terraform apply", "npm publish",
            ],
            only_paths=allowed_paths,
            invariant=["task_ticket_exists == True"],
            value_range={
                "files_modified": {"max": ctx.get("max_files_modified", 20)},
            },
            name="coder",
        )

    def _tester_contract(self, ctx: Dict) -> IntentContract:
        """
        Tester: runs tests and may add/fix test files.
        - CANNOT modify src/ files outside test scope
        - CANNOT relax assertions or skip flaky tests
        - Only paths: test directories + planner-approved src paths
        """
        test_paths = ctx.get("test_paths", ["./tests", "./test"])
        src_paths  = ctx.get("allowed_paths", [])
        allowed    = list(dict.fromkeys(test_paths + src_paths))
        return IntentContract(
            deny=[
                "modify_src_without_approval",
                "delete_test_file",
                "bypass_review",
            ],
            # Semantic speculation guard: substring match on patch_summary field
            # Catches: "Relax assertion ...", "skip flaky edge case", etc.
            field_deny={
                "patch_summary": ["weaken_assertion", "skip_flaky_test",
                                  "relax assertion",  "skip flaky",
                                  "remove strict",    "bypass failure"],
                "action":        ["weaken_assertion", "skip_flaky_test"],
            },
            deny_commands=["git push", "kubectl apply", "npm publish"],
            only_paths=allowed,
            invariant=["task_ticket_exists == True"],
            name="tester",
        )

    def _reviewer_contract(self, ctx: Dict) -> IntentContract:
        """
        Reviewer: read-only; can comment but not modify files.
        """
        allowed_paths = ctx.get("allowed_paths", [self.workspace_root])
        return IntentContract(
            deny=[
                "write_file",
                "delete_file",
                "bypass_review",
                "approve_own_pr",
            ],
            deny_commands=["git push", "git commit", "kubectl apply"],
            only_paths=allowed_paths,
            invariant=["task_ticket_exists == True"],
            name="reviewer",
        )

    def _researcher_contract(self, ctx: Dict) -> IntentContract:
        """
        Researcher: fetches external docs from whitelisted domains only.
        No file writes. No code execution.
        """
        domains = ctx.get("allowed_domains", self.doc_domains)
        return IntentContract(
            deny=[
                "write_file",
                "execute_code",
                "access_non_whitelisted_domain",
                "bypass_review",
            ],
            deny_commands=["git push", "kubectl apply", "npm publish", "pip install"],
            only_domains=domains,
            invariant=["task_ticket_exists == True"],
            name="researcher",
        )

    def _release_contract(self, ctx: Dict) -> IntentContract:
        """
        Release: packages artefacts. Deployment commands require
        explicit approval token — enforced via invariant.
        HIGH-RISK: deny_commands list is extensive.
        """
        return IntentContract(
            deny=[
                "bypass_ci",
                "skip_approval",
                "deploy_without_token",
                "overwrite_release",
            ],
            deny_commands=[
                "git push",                    # release agent uses git tag, not push
                "git push --force",
                "kubectl apply",
                "kubectl delete",
                "terraform apply",
                "terraform destroy",
                "npm publish",
            ],
            invariant=[
                "release_approved == True",
                "ci_passed == True",
                "task_ticket_exists == True",
            ],
            name="release",
        )


# ── Standard delegation chain ─────────────────────────────────────────────────

def make_openclaw_chain(
    pack: OpenClawDomainPack = None,
    allowed_paths: Optional[List[str]] = None,
    allowed_domains: Optional[List[str]] = None,
    include_release: bool = False,
) -> DelegationChain:
    """
    Build the standard OpenClaw delegation chain:

        planner → coder → tester [→ release]

    Monotonicity guarantee (v0.24.0+):
      - Each child contract is a strict subset of its parent
      - action_scope narrows at every hop
      - DelegationChain.validate() will catch any drift

    Args:
        pack:             OpenClawDomainPack instance (created if None)
        allowed_paths:    filesystem scope set by planner
        allowed_domains:  external domain whitelist for ALL agents.
                          When specified, any WEB_FETCH to a domain not
                          in this list will be DENIED — this is the primary
                          defense against sleeper attacks that exfiltrate
                          data to external URLs.
                          When empty/None, only researcher role has domain
                          restrictions (via its own only_domains setting).
        include_release:  extend chain to include release agent
    """
    import time

    if pack is None:
        pack = OpenClawDomainPack()

    # Planner defines the COMPLETE scope for the entire session.
    # Test paths are included from the start — tester must be ⊆ coder ⊆ planner.
    src_paths  = allowed_paths or ["./src"]
    test_paths = ["./tests", "./test"]
    all_paths  = list(dict.fromkeys(src_paths + test_paths))

    # allowed_domains が指定された場合、全ロールに域名ホワイトリストを適用
    # → 潜伏炸弹が外部 URL に送信できなくなる（あなたの指摘を実装）
    domain_ctx = {"allowed_domains": allowed_domains} if allowed_domains else {}

    ctx_planner  = {"allowed_paths": all_paths, **domain_ctx}
    ctx_coder    = {"allowed_paths": all_paths, "max_files_modified": 10, **domain_ctx}
    ctx_tester   = {"allowed_paths": all_paths, "test_paths": test_paths, **domain_ctx}

    planner_c = pack.make_contract("planner",  ctx_planner)
    coder_c   = pack.make_contract("coder",    ctx_coder)
    tester_c  = pack.make_contract("tester",   ctx_tester)

    # coder_c must inherit planner_c constraints (monotonicity)
    def _merge_field_deny(a: dict, b: dict) -> dict:
        """Merge two field_deny dicts: union of blocked values per field."""
        merged = dict(a)
        for field, vals in b.items():
            if field in merged:
                merged[field] = list(dict.fromkeys(merged[field] + vals))
            else:
                merged[field] = vals
        return merged

    coder_inherited = IntentContract(
        deny          = list(dict.fromkeys(coder_c.deny + planner_c.deny)),
        deny_commands = list(dict.fromkeys(coder_c.deny_commands + planner_c.deny_commands)),
        only_paths    = coder_c.only_paths or planner_c.only_paths,
        only_domains  = coder_c.only_domains or planner_c.only_domains,
        invariant     = list(dict.fromkeys(coder_c.invariant + planner_c.invariant)),
        optional_invariant = list(dict.fromkeys(
            coder_c.optional_invariant + planner_c.optional_invariant)),
        field_deny    = _merge_field_deny(coder_c.field_deny, planner_c.field_deny),
        value_range   = {**planner_c.value_range, **coder_c.value_range},
        name          = "coder_inherited",
    )

    # tester_c must inherit coder_inherited constraints
    tester_inherited = IntentContract(
        deny          = list(dict.fromkeys(tester_c.deny + coder_inherited.deny)),
        deny_commands = list(dict.fromkeys(tester_c.deny_commands + coder_inherited.deny_commands)),
        only_paths    = tester_c.only_paths or coder_inherited.only_paths,
        only_domains  = tester_c.only_domains or coder_inherited.only_domains,
        invariant     = list(dict.fromkeys(tester_c.invariant + coder_inherited.invariant)),
        optional_invariant = list(dict.fromkeys(
            tester_c.optional_invariant + coder_inherited.optional_invariant)),
        field_deny    = _merge_field_deny(tester_c.field_deny, coder_inherited.field_deny),
        value_range   = {**coder_inherited.value_range, **tester_c.value_range},
        name          = "tester_inherited",
    )

    # Parent scope must always be superset of child scope
    planner_to_coder = DelegationContract(
        principal        = "planner",
        actor            = "coder_agent",
        contract         = coder_inherited,
        action_scope     = ["write_file", "read_file", "run_linter",
                            "run_tests", "modify_test", "read_doc"],
        delegation_depth = 2 if include_release else 1,
        allow_redelegate = True,
        valid_until      = time.time() + 7_200,   # 2-hour session
        grant_id         = "GRANT-PLANNER-CODER",
    )

    coder_to_tester = DelegationContract(
        principal        = "coder_agent",
        actor            = "tester_agent",
        contract         = tester_inherited,
        action_scope     = ["run_tests", "modify_test", "read_doc"],  # ⊆ planner_to_coder
        delegation_depth = 1 if include_release else 0,
        allow_redelegate = include_release,
        valid_until      = time.time() + 7_200,
        grant_id         = "GRANT-CODER-TESTER",
    )

    links = [planner_to_coder, coder_to_tester]

    if include_release:
        release_c = pack.make_contract("release", {})
        release_inherited = IntentContract(
            deny          = list(dict.fromkeys(release_c.deny + tester_inherited.deny)),
            deny_commands = list(dict.fromkeys(release_c.deny_commands + tester_inherited.deny_commands)),
            only_paths    = release_c.only_paths or tester_inherited.only_paths,
            only_domains  = release_c.only_domains or tester_inherited.only_domains,
            invariant     = list(dict.fromkeys(release_c.invariant + tester_inherited.invariant)),
            optional_invariant = list(dict.fromkeys(
                release_c.optional_invariant + tester_inherited.optional_invariant)),
            value_range   = {**tester_inherited.value_range, **release_c.value_range},
            name          = "release_inherited",
        )
        tester_to_release = DelegationContract(
            principal        = "tester_agent",
            actor            = "release_agent",
            contract         = release_inherited,
            action_scope     = ["read_doc"],   # ⊆ coder_to_tester scope; release uses own auth
            delegation_depth = 0,
            allow_redelegate = False,
            valid_until      = time.time() + 7_200,
            grant_id         = "GRANT-TESTER-RELEASE",
        )
        links.append(tester_to_release)

    return DelegationChain(links)


# ── Policy bridge (zero-friction entry point) ────────────────────────────────

def make_policy(agents: dict, allowed_paths: list = None) -> "Policy":  # noqa: F821
    """
    Create a Policy (or Company) backed by a full OpenClaw session.

    This is the recommended entry point for OpenClaw users who want
    near-zero friction. Use it instead of make_session() + state.agent_contracts.

    Example::

        from ystar.domains.openclaw import make_policy
        from ystar import from_template

        policy = make_policy(agents={
            "rd":    from_template({"can_write_to": ["./workspace/dev/"]}),
            "sales": from_template({"can_call": ["api.hubspot.com"]}),
        }, allowed_paths=["./workspace/"])

        # Simple path (framework-agnostic):
        result = policy.check("rd", "write", path="./workspace/dev/main.py")

        # OpenClaw path (full event enforcement):
        result = policy.check_event(some_openclaw_event)
    """
    from ystar.session import Policy as _Policy
    from ystar.kernel.dimensions import IntentContract as _IC

    class OpenClawPolicy(_Policy):
        """Policy with an OpenClaw session underneath for full enforcement."""

        def __init__(self, agents, allowed_paths):
            from ystar.domains.openclaw.adapter import (
                make_session as _make_session, enforce as _enforce,
                EnforceDecision as _ED,
            )
            super().__init__(rules=agents)
            _ap = allowed_paths or ["./"]
            self._oc_chain = make_openclaw_chain(allowed_paths=_ap)
            self._oc_state = _make_session(
                session_id=_generate_session_id(),
                allowed_paths=_ap,
                chain=self._oc_chain,
            )
            self._enforce = _enforce
            self._ED = _ED
            # bind contracts to the underlying session as well
            for name, contract in agents.items():
                self._oc_state.agent_contracts[name] = contract

        def check_event(self, event: "OpenClawEvent") -> "PolicyResult":
            """
            Full OpenClaw enforcement: passes the raw event through
            enforce() and returns a PolicyResult.
            """
            from ystar.session import PolicyResult as _PR
            decision, records = self._enforce(event, self._oc_state)
            allowed = (decision == self._ED.ALLOW)
            reason = "ok" if allowed else _format_enforce_reason(records)
            return _PR(
                allowed=allowed, reason=reason,
                who=event.agent_id, what=event.event_type.value,
                violations=[],
            )

    return OpenClawPolicy(agents, allowed_paths)


def _generate_session_id() -> str:
    import uuid
    return f"ystar_{uuid.uuid4().hex[:8]}"


def _format_enforce_reason(records) -> str:
    """Extract a human-readable denial reason from CIEU records."""
    for rec in records:
        viols = getattr(rec, "violations", []) or []
        for v in viols:
            msg = getattr(v, "message", str(v))
            if msg:
                return msg
    return "denied by policy"

"""
Y* DevOps Domain Pack

DevOps / production control domain pack, applicable to:
  - Deployment permission control in CI/CD pipelines
  - Constraint propagation for production environment changes
  - Change approval chains in multi-agent collaboration
  - Intent specification for command execution

This pack demonstrates that the Y* kernel is finance-agnostic —
the same DomainPack interface, an entirely different domain.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ystar.domains import DomainPack
from ystar import IntentContract, ConstitutionalContract, DelegationContract


class DevOpsDomainPack(DomainPack):
    """
    DevOps domain pack.

    Encapsulates:
    - Production environment protection vocabulary
    - DevOps constitutional contract (dangerous command denial, environment constraints)
    - Role contract templates (developer / reviewer / deployer / sre / oncall)
    - Change approval chain builder
    """

    @property
    def domain_name(self) -> str:
        return "devops"

    @property
    def version(self) -> str:
        return "1.0.0"

    def vocabulary(self) -> dict:
        return {
            "deny_keywords": [
                "production_bypass",
                "skip_review",
                "force_deploy",
                "unapproved_service",
            ],
            "role_names": [
                "developer", "code_reviewer", "deployer",
                "sre", "oncall", "release_manager",
            ],
            "param_names": [
                "blast_radius", "rollback_available", "canary_pct",
                "change_ticket", "affected_services", "deploy_window",
            ],
            "env_keywords": ["personal_dev", "sandbox", "experiment"],
            # DevOps专用的命令禁止patterns
            "dangerous_command_patterns": [
                r"禁止(?:在生产|线上)(?:运行|执行)\s*([a-z][a-z0-9_\-]*"
                r"(?:[、,，]\s*[a-z][a-z0-9_\-]*)+)",
                r"(?:never|do\s*not)\s+run\s+([a-z][a-z0-9_\-]*"
                r"(?:\s+or\s+[a-z][a-z0-9_\-]*)+)\s+in\s+production",
            ],
        }

    def constitutional_contract(self) -> ConstitutionalContract:
        """
        DevOps宪法层：生产环境不可放宽的约束
        """
        return ConstitutionalContract(
            deny=[
                "production_bypass",   # 不允许绕过生产审批
                "skip_review",         # 不允许跳过代码审查
                "unapproved_service",  # 未批准的服务
            ],
            deny_commands=[
                "rm -rf /",
                "kubectl delete namespace production",
                "DROP TABLE ",
                "TRUNCATE ",
                "force_deploy ",
            ],
            optional_invariant=[
                "rollback_available == True",  # 有回滚方案
                "blast_radius < 0.3",          # 影响面控制
            ],
            value_range={
                "canary_pct":    {"min": 0, "max": 0.1},   # 灰度不超过10%
                "affected_pods": {"min": 0, "max": 100},
            },
        )

    def make_contract(self, role: str, context: dict = None) -> IntentContract:
        """
        根据角色生成DevOps合约。

        Args:
            role: 'developer' | 'code_reviewer' | 'deployer' |
                  'sre' | 'oncall' | 'release_manager'
            context: {"env": "staging", "max_canary_pct": 0.05}
        """
        ctx = context or {}
        constitution = self.constitutional_contract()

        role_contracts = {
            "developer": IntentContract(
                deny=["production_deploy_direct"],
                invariant=["change_ticket_exists == True"],
                value_range={"canary_pct": {"max": 0}},  # dev不能直接部署
                obligation_timing={
                    "acknowledgement": 1800,      # 30 min to ack code review request
                    "status_update": 14400,       # 4 hours status update
                    "result_publication": 28800,  # 8 hours to complete feature
                    "escalation": 3600,           # 1 hour to escalate blocker
                },
            ),
            "code_reviewer": IntentContract(
                invariant=["review_approved == True"],
                deny=["skip_review"],
                obligation_timing={
                    "acknowledgement": 3600,      # 1 hour to ack review request
                    "status_update": 14400,       # 4 hours status update
                    "result_publication": 28800,  # 8 hours to complete review
                    "escalation": 7200,           # 2 hours to escalate review issue
                },
            ),
            "deployer": IntentContract(
                invariant=["review_approved == True",
                           "change_ticket_approved == True"],
                optional_invariant=["rollback_available == True"],
                value_range={
                    "canary_pct":    {"max": ctx.get("max_canary_pct", 0.05)},
                    "affected_pods": {"max": ctx.get("max_pods", 50)},
                },
                obligation_timing={
                    "acknowledgement": 600,       # 10 min to ack deploy request
                    "status_update": 1800,        # 30 min status update
                    "result_publication": 3600,   # 1 hour to complete deployment
                    "escalation": 300,            # 5 min to escalate deploy failure
                },
            ),
            "sre": IntentContract(
                invariant=["oncall_notified == True"],
                optional_invariant=["blast_radius < 0.3"],
                value_range={"canary_pct": {"max": 0.10}},
                obligation_timing={
                    "acknowledgement": 300,       # 5 min to ack incident
                    "status_update": 900,         # 15 min status update
                    "result_publication": 3600,   # 1 hour to resolve incident
                    "escalation": 600,            # 10 min to escalate to senior SRE
                },
            ),
            "oncall": IntentContract(
                invariant=["incident_acknowledged == True"],
                deny=["production_bypass"],
                obligation_timing={
                    "acknowledgement": 300,       # 5 min to ack page
                    "status_update": 900,         # 15 min status update
                    "result_publication": 1800,   # 30 min to triage incident
                    "escalation": 600,            # 10 min to escalate critical incident
                },
            ),
            "release_manager": IntentContract(
                invariant=["release_window_open == True"],
                value_range={"canary_pct": {"max": 0.10}},
                obligation_timing={
                    "acknowledgement": 3600,      # 1 hour to ack release request
                    "status_update": 7200,        # 2 hours status update
                    "result_publication": 14400,  # 4 hours to complete release
                    "escalation": 1800,           # 30 min to escalate release blocker
                },
            ),
        }

        base = role_contracts.get(role, IntentContract())
        return base.merge(constitution)


def make_deploy_chain(
    pack: DevOpsDomainPack = None,
) -> "DelegationChain":
    """
    Build standard deployment approval chain:
    Developer → Code Reviewer → Release Manager → Deployer

    v0.24.0: monotonicity enforced — each link's contract inherits parent
    constraints; action_scope only narrows at each step.
    """
    from ystar import DelegationChain, IntentContract

    if pack is None:
        pack = DevOpsDomainPack()

    reviewer_c = pack.make_contract("code_reviewer")
    rm_c       = pack.make_contract("release_manager")
    deployer_c = pack.make_contract("deployer")

    # rm_c must inherit reviewer_c invariants
    rm_c_inherited = IntentContract(
        deny          = list(dict.fromkeys(rm_c.deny + reviewer_c.deny)),
        deny_commands = list(dict.fromkeys(rm_c.deny_commands + reviewer_c.deny_commands)),
        only_paths    = rm_c.only_paths or reviewer_c.only_paths,
        only_domains  = rm_c.only_domains or reviewer_c.only_domains,
        invariant     = list(dict.fromkeys(rm_c.invariant + reviewer_c.invariant)),
        optional_invariant = list(dict.fromkeys(
            rm_c.optional_invariant + reviewer_c.optional_invariant)),
        value_range   = {**reviewer_c.value_range, **rm_c.value_range},
        name          = "release_manager_inherited",
    )
    # deployer_c must inherit rm_c_inherited constraints
    deployer_c_inherited = IntentContract(
        deny          = list(dict.fromkeys(deployer_c.deny + rm_c_inherited.deny)),
        deny_commands = list(dict.fromkeys(deployer_c.deny_commands + rm_c_inherited.deny_commands)),
        only_paths    = deployer_c.only_paths or rm_c_inherited.only_paths,
        only_domains  = deployer_c.only_domains or rm_c_inherited.only_domains,
        invariant     = list(dict.fromkeys(deployer_c.invariant + rm_c_inherited.invariant)),
        optional_invariant = list(dict.fromkeys(
            deployer_c.optional_invariant + rm_c_inherited.optional_invariant)),
        value_range   = {**rm_c_inherited.value_range, **deployer_c.value_range},
        name          = "deployer_inherited",
    )

    chain = DelegationChain([
        DelegationContract(
            principal="developer", actor="code_reviewer",
            contract=reviewer_c,
            action_scope=["review_code", "approve_pr",
                          "approve_release", "schedule_deploy",
                          "deploy_canary", "rollout", "rollback"],
            prerequisites=["change_ticket_exists == True"],
            allow_redelegate=True,
            delegation_depth=2,
            grant_id="GRANT-DEV-REVIEWER",
        ),
        DelegationContract(
            principal="code_reviewer", actor="release_manager",
            contract=rm_c_inherited,
            action_scope=["approve_release", "schedule_deploy",
                          "deploy_canary", "rollout", "rollback"],   # ⊆ parent
            prerequisites=["review_approved == True"],
            allow_redelegate=True,
            delegation_depth=1,
            grant_id="GRANT-REVIEWER-RM",
        ),
        DelegationContract(
            principal="release_manager", actor="deployer",
            contract=deployer_c_inherited,
            action_scope=["deploy_canary", "rollout", "rollback"],   # ⊆ parent
            prerequisites=["change_ticket_approved == True"],
            delegation_depth=0,
            grant_id="GRANT-RM-DEPLOYER",
        ),
    ])
    return chain

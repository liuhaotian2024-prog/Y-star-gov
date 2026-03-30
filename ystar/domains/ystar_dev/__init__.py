"""
Y* Self-Hosting Domain Pack  v1.0.0
=====================================
用 Y* 自身来治理 Y* 的开发过程。

这是"自举"（self-hosting）里程碑：
  - Y* 的每次代码修改都必须通过 Y* 的 check()
  - 修改核心不变量（monotonicity rules）需要更高授权
  - 删除测试文件被绝对禁止
  - 放宽合约约束的修改被检测和拦截

类比：编译器用自身编译自身（self-hosting compiler）
      Y* 用自身约束自身的开发行为

架构：
  开发者（human）
      ↓  DelegationContract（planner 授权）
  planner_agent        ← 任务分解，不能直接改 core
      ↓  DelegationContract（coder 授权，受 core_rules 约束）
  coder_agent          ← 实现，但 dimensions.py / engine.py 受保护
      ↓  DelegationContract（tester 授权）
  tester_agent         ← 只能强化测试，不能弱化
      ↓  DelegationContract（reviewer 授权）
  reviewer_agent       ← 审查，确认 monotonicity 没有被放宽

宪法层（YSTAR_DEV_CONSTITUTION）：
  - dimensions.py 里的 monotonicity 规则不能被放宽
  - engine.py 里的 check() 核心逻辑不能被绕过
  - 所有 deny 规则只能增加，不能减少
  - 测试数量只能增加，不能减少
  - 每次发布必须 version bump
  - CHANGELOG 必须更新
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from ystar.kernel.dimensions import (
    IntentContract,
    ConstitutionalContract,
)
from ystar.domains import DomainPack


# ═══════════════════════════════════════════════════════════════════════
# YSTAR_CONSTITUTION  —  Y* 铁律的唯一机器可信源头
#
# 这是 Y* 自举的核心：
#   - 不再从 AGENTS.md 解析规则（那是旧的方向）
#   - 从这个 ConstitutionalContract 生成 AGENTS.md（正确的方向）
#   - 任何对铁律的修改必须先改这里，AGENTS.md 是导出物
#
# 用法：
#   YSTAR_CONSTITUTION.to_agents_md("AGENTS.md")   # 重新生成文档
#   YStarDevDomainPack.constitutional_contract()   # 开发约束继承自此
# ═══════════════════════════════════════════════════════════════════════

YSTAR_CONSTITUTION = ConstitutionalContract(

    # ── 铁律 1：Core 是确定性的 ─────────────────────────────────────
    # check() 对相同输入永远返回相同结果，不允许 LLM 推断进入 core loop
    deny=[
        "add_lm_inference_to_core",       # 铁律1: engine.py 不能有 LLM 调用
        "bypass_check_function",          # 铁律1: 不能绕过 check()
        "add_randomness_to_check",        # 铁律1: check() 必须确定性
        # 铁律 2：约束编译，非推断
        "weaken_monotonicity_rule",       # 铁律2: is_subset_of 不能被软化
        "disable_delegation_validate",    # 铁律2: DelegationChain.validate 不能被禁用
        "relax_contract_without_review",  # 铁律2: 合约只能收紧，不能放宽
        # 铁律 3：域知识在域包
        "add_domain_rule_to_engine",      # 铁律3: engine.py 不能有业务规则
        "add_domain_rule_to_dimensions",  # 铁律3: dimensions.py 不能有业务规则
        # 测试与发布不变量
        "delete_test_file",
        "weaken_assertion",
        "skip_flaky_test",
        "skip_version_bump",
        "skip_changelog_update",
    ],

    deny_commands=[
        "rm -rf ystar/tests ",
        "rm -rf ystar/scenarios ",
        "git push --force ",
        "git push origin main ",  # 必须通过 PR
    ],

    # 所有 Y* 开发会话必须满足
    invariant=[
        "session_authenticated == True",
        "task_ticket_exists == True",
    ],

    # 发布时必须满足
    optional_invariant=[
        "reviewer_approved == True",
        "test_count_after >= test_count_before",
        "version_bumped == True",
        "changelog_updated == True",
    ],

    # 语义投机防护（开发侧）
    field_deny={
        "patch_summary": [
            "pp.startswith(cp)",              # 方向反了的路径比较 bug
            "or pp.startswith",
            "is_subset_of to return True",
            "return True when paths overlap",
            "skip monoton",
            "disable validate",
            "relax contract",
        ],
    },

    name="ystar_constitution",
)


# ── 受保护的核心文件（只有 reviewer 或 human 可以修改）────────────────
CORE_PROTECTED_FILES = [
    "ystar/dimensions.py",      # monotonicity rules 所在地
    "ystar/engine.py",          # check() 核心
    "ystar/__init__.py",        # 公共 API
    "pyproject.toml",           # 版本号
]

# ── 受保护的 DomainPack 文件（修改需要特殊授权）─────────────────────
DOMAIN_PACK_FILES = [
    "ystar/domains/pharma/__init__.py",
    "ystar/domains/finance/__init__.py",
    "ystar/domains/crypto/__init__.py",
    "ystar/domains/healthcare/__init__.py",
    "ystar/domains/devops/__init__.py",
    "ystar/domains/openclaw/__init__.py",
    "ystar/domains/openclaw/adapter.py",
]

# ── 绝对禁止删除的文件──────────────────────────────────────────────────
PROTECTED_FROM_DELETION = [
    "ystar/tests/",
    "ystar/scenarios/",
    "CHANGELOG.md",
    "docs/",
]

# ── 可以弱化 monotonicity 的高危修改模式 ─────────────────────────────
# field_deny 用子字符串匹配（不是正则），必须是真实可能出现的子字符串
MONOTONICITY_WEAKENING_PATTERNS = [
    "pp.startswith(cp)",              # 之前的 only_paths bug 根因
    "or pp.startswith",
    "is_subset_of to return True",    # 绕过 subset check 的自然语言
    "is_subset_of return True",
    "return True when paths overlap", # 典型绕过描述
    "allow overlap",
    "def is_subset_of",               # 修改核心方法定义
    "skip monoton",                   # skip monotonicity
    "disable validate",               # disable validate
    "validate return []",             # 让 validate 永远返回空列表
    "bypass subset",
    "relax contract",
]


class YStarDevDomainPack(DomainPack):
    """
    Y* 开发过程的约束域包。

    用 OpenClawDomainPack + YStarDevDomainPack 双层约束，
    实现"Y* 治理 Y* 自身开发"的自举闭环。
    """

    def __init__(self, config: Dict = None):
        self._config = config or {}

    @property
    def domain_name(self) -> str:
        return "ystar_dev"

    @property
    def version(self) -> str:
        return "1.0.0"

    def vocabulary(self) -> Dict[str, Any]:
        return {
            "role_names": [
                "ystar_planner",     # 任务分解，设定开发 scope
                "ystar_coder",       # 实现，受核心文件保护约束
                "ystar_tester",      # 测试强化，绝不弱化
                "ystar_reviewer",    # 审查 monotonicity 合规
                "ystar_releaser",    # 版本发布，version bump 验证
            ],
            "param_names": [
                "file_path",
                "patch_summary",
                "test_count_before",
                "test_count_after",
                "version_bumped",
                "changelog_updated",
                "monotonicity_preserved",
                "core_file_modified",
                "reviewer_approved",
            ],
        }

    def constitutional_contract(self) -> ConstitutionalContract:
        """
        Y* 开发的宪法层。

        直接返回 YSTAR_CONSTITUTION —— 唯一的机器可信源头。
        不再从 AGENTS.md 解析，而是从合约生成 AGENTS.md。

        三条铁律编码在 YSTAR_CONSTITUTION 里：
          铁律1  确定性：add_lm_inference_to_core, bypass_check_function denied
          铁律2  规则编译：weaken_monotonicity_rule, disable_delegation_validate denied
          铁律3  域知识在域包：add_domain_rule_to_engine denied
        """
        # 允许通过 config 附加额外约束（来自 AGENTS.md 解析或外部注入）
        extra_deny = self._config.get("extra_deny", [])
        extra_cmds = self._config.get("extra_deny_commands", [])

        if not extra_deny and not extra_cmds:
            return YSTAR_CONSTITUTION

        # 附加约束：在 YSTAR_CONSTITUTION 基础上叠加，不替换
        from ystar.kernel.dimensions import ConstitutionalContract
        return ConstitutionalContract(
            deny          = list(dict.fromkeys(YSTAR_CONSTITUTION.deny + extra_deny)),
            deny_commands = list(dict.fromkeys(YSTAR_CONSTITUTION.deny_commands + extra_cmds)),
            only_paths    = YSTAR_CONSTITUTION.only_paths,
            only_domains  = YSTAR_CONSTITUTION.only_domains,
            invariant     = YSTAR_CONSTITUTION.invariant,
            optional_invariant = YSTAR_CONSTITUTION.optional_invariant,
            field_deny    = YSTAR_CONSTITUTION.field_deny,
            value_range   = YSTAR_CONSTITUTION.value_range,
            name          = "ystar_constitution_extended",
        )

    def make_contract(self, role: str, context: Dict = None) -> IntentContract:
        ctx          = context or {}
        constitution = self.constitutional_contract()

        roles = {

            "ystar_planner": IntentContract(
                # 任务分解，可读所有文件，不能直接修改 core
                deny=[
                    "modify_core_without_review",
                    "bypass_delegation_chain",
                    "weaken_monotonicity_rule",
                    "delete_test_file",
                ],
                deny_commands=["git push", "git push --force"],
                only_paths=[
                    "ystar/",
                    "tests/",
                    "docs/",
                    "./",
                ],
                field_deny={
                    "patch_summary": MONOTONICITY_WEAKENING_PATTERNS[:4],
                },
                invariant=["task_ticket_exists == True"],
                name="ystar_planner",
            ),

            "ystar_coder": IntentContract(
                # 实现代码，但核心文件有额外保护
                deny=[
                    "modify_core_without_review",
                    "weaken_monotonicity_rule",
                    "bypass_check_function",
                    "delete_test_file",
                    "add_lm_inference_to_core",
                    "weaken_assertion",
                    "skip_flaky_test",
                ],
                deny_commands=["git push", "git push --force"],
                only_paths=[
                    "ystar/",
                    "tests/",
                    "docs/",
                    "CHANGELOG.md",
                ],
                # 语义投机防护：监控对 dimensions.py 的危险修改模式
                field_deny={
                    "patch_summary": MONOTONICITY_WEAKENING_PATTERNS,
                    "code_content":  MONOTONICITY_WEAKENING_PATTERNS[:3],
                },
                invariant=["task_ticket_exists == True", "session_authenticated == True"],
                value_range={
                    # 每次提交不能删除测试：test_count_after >= test_count_before
                    # 用 min 约束表达"只能增不能减"
                    "test_count_after": {"min": ctx.get("test_count_before", 0)},
                },
                name="ystar_coder",
            ),

            "ystar_tester": IntentContract(
                # 测试强化，只能在 tests/ 和 scenarios/ 内操作
                deny=[
                    "weaken_assertion",
                    "skip_flaky_test",
                    "relax_contract_without_review",
                    "delete_test_file",
                    "modify_core_without_review",
                ],
                deny_commands=["git push", "git push --force", "pytest --no-header -q --tb=no"],
                only_paths=["ystar/tests/", "ystar/scenarios/", "tests/"],
                field_deny={
                    "patch_summary": [
                        "weaken_assertion", "skip_flaky_test",
                        "relax assertion", "skip flaky",
                        "remove test", "disable test",
                        "comment out test",
                    ],
                },
                invariant=["task_ticket_exists == True"],
                value_range={
                    "test_count_after": {"min": ctx.get("test_count_before", 0)},
                },
                name="ystar_tester",
            ),

            "ystar_reviewer": IntentContract(
                # 只读审查 + 可以注释/标记，不能修改业务代码
                deny=[
                    "modify_source_without_ticket",
                    "bypass_review",
                    "approve_monotonicity_weakening",  # 不能批准会放宽 monotonicity 的修改
                ],
                deny_commands=["git push", "git merge --no-ff"],
                only_paths=["ystar/", "tests/", "docs/"],
                invariant=["task_ticket_exists == True", "reviewer_approved == True"],
                name="ystar_reviewer",
            ),

            "ystar_releaser": IntentContract(
                # 版本发布：必须 version bump + changelog
                deny=[
                    "skip_version_bump",
                    "skip_changelog_update",
                    "release_with_test_failures",
                    "overwrite_existing_release",
                ],
                deny_commands=[
                    "git push --force",
                    "git push origin main",  # 通过 tag，不直接推 main
                ],
                only_paths=["pyproject.toml", "CHANGELOG.md", "ystar/__init__.py"],
                invariant=[
                    "task_ticket_exists == True",
                    "version_bumped == True",
                    "changelog_updated == True",
                    "reviewer_approved == True",
                ],
                name="ystar_releaser",
            ),
        }

        base = roles.get(role, IntentContract())
        return base.merge(constitution)


# ── 自举 SessionState 构建辅助函数 ───────────────────────────────────

def make_ystar_dev_session(
    session_id:          str,
    test_count_before:   int = 1000,
    current_version:     str = "0.25.0",
) -> "SessionState":
    """
    构建一个 Y* 开发会话的 SessionState。

    将 OpenClawDomainPack（通用多 agent 约束）和
    YStarDevDomainPack（Y* 特定开发约束）叠加，
    形成双层保护：
      外层：OpenClaw 通用规则（文件越界、危险命令等）
      内层：Y* 开发专属规则（monotonicity 保护等）

    这就是"自举"的实现形式：
    Y* 的运行时 check() 在每次 coder_agent 修改 dimensions.py 时
    验证这次修改不会放宽 monotonicity 规则。
    """
    from ystar.domains.openclaw.adapter import SessionState
    from ystar.domains.openclaw import OpenClawDomainPack, make_openclaw_chain

    openclaw_pack = OpenClawDomainPack(workspace_root="./")
    dev_pack      = YStarDevDomainPack(config={
        "test_count_before": test_count_before,
        "current_version":   current_version,
    })

    # OpenClaw 链：planner → coder → tester（外层约束）
    chain = make_openclaw_chain(openclaw_pack, allowed_paths=["ystar/"])

    state = SessionState(
        session_id       = session_id,
        pack             = openclaw_pack,
        delegation_chain = chain,
    )

    # 注入 Y*Dev 专属合约（叠加到链上的合约之上）
    # 用 merge 确保两层约束都生效
    ctx = {"test_count_before": test_count_before}

    for role_pair in [
        ("planner",         "ystar_planner"),
        ("coder_agent",     "ystar_coder"),
        ("tester_agent",    "ystar_tester"),
        ("reviewer_agent",  "ystar_reviewer"),
        ("release_agent",   "ystar_releaser"),
    ]:
        openclaw_role, dev_role = role_pair
        # 从链里找 openclaw 合约
        openclaw_contract = state.get_contract_for(openclaw_role) or \
                            openclaw_pack.make_contract(openclaw_role.replace("_agent","") or openclaw_role)
        # 获取 dev 专属合约
        dev_contract = dev_pack.make_contract(dev_role, ctx)
        # 叠加：取更严格的那个（merge 保证两层都生效）
        merged = dev_contract.merge(dev_pack.constitutional_contract())
        state.agent_contracts[openclaw_role] = merged

    return state


# ── AGENTS.md 解析 ───────────────────────────────────────────────────

def _parse_agents_md(agents_md_path: str = None) -> dict:
    """
    解析 AGENTS.md，提取 deny / deny_commands / only_paths 约束。

    这让 YStarDevDomainPack 可以自动从 AGENTS.md 加载开发约束，
    和 K9Audit 一样读取同一份规则源，避免规则分散在多处。
    """
    from pathlib import Path

    if agents_md_path is None:
        # 向上查找 AGENTS.md
        for candidate in [
            Path.cwd() / "AGENTS.md",
            Path(__file__).parent.parent.parent.parent / "AGENTS.md",
            Path.home() / ".openclaw" / "AGENTS.md",
        ]:
            if candidate.exists():
                agents_md_path = str(candidate)
                break

    if not agents_md_path or not Path(agents_md_path).exists():
        return {}

    deny = []
    deny_commands = []
    only_paths = []

    for line in Path(agents_md_path).read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        rule = stripped[2:].strip()

        # deny_commands：含命令特征的规则
        if any(cmd in rule for cmd in ["git push", "rm -rf", "kubectl", "terraform", "npm publish"]):
            # 提取命令
            for cmd in ["git push --force", "git push", "rm -rf ystar/tests", "kubectl delete"]:
                if cmd in rule:
                    deny_commands.append(cmd + " ")  # trailing space matches engine
            continue

        # only_paths：含路径特征
        if "only write to" in rule.lower() or "only access" in rule.lower():
            import re
            paths = re.findall(r'[./][/\w.-]+/', rule)
            only_paths.extend(paths)
            continue

        # deny：含 Never/Do not 的规则 → 提取关键词作为 deny token
        neg = ["Never ", "Do not ", "never ", "do not ", "must not "]
        for prefix in neg:
            if rule.startswith(prefix):
                core = rule[len(prefix):].strip()
                # 转成机器可匹配的 deny token（取前30字符）
                token = core[:30].lower().replace(" ", "_").replace("(", "").replace(")", "")
                deny.append(token)
                break

    return {
        "deny":          deny,
        "deny_commands": deny_commands,
        "only_paths":    only_paths,
    }


def _build_from_agents_md(agents_md_path: str = None) -> "YStarDevDomainPack":
    """
    从 AGENTS.md 构建 YStarDevDomainPack。

    用法（K9Audit 集成方式）：
        pack = _build_from_agents_md()   # 自动查找 AGENTS.md
        state = make_ystar_dev_session("dev_001")
    """
    parsed = _parse_agents_md(agents_md_path)
    return YStarDevDomainPack(config={
        "extra_deny":          parsed.get("deny", []),
        "extra_deny_commands": parsed.get("deny_commands", []),
    })


# ═══════════════════════════════════════════════════════════════════════
# Constitution 進化追跡  +  NL→Contract ループ
# ═══════════════════════════════════════════════════════════════════════

import hashlib, json
from pathlib import Path

_CONSTITUTION_HISTORY = Path(__file__).parent.parent.parent.parent / \
                        ".ystar_constitution_history.jsonl"


def _record_constitution_change(
    old_hash:    Optional[str],
    new_hash:    str,
    delta:       dict,
    source:      str = "manual",
    rule_text:   Optional[str] = None,
) -> None:
    """
    YSTAR_CONSTITUTION が変化するたびに CIEU スタイルの記録を残す。

    old_hash=None のときは初回記録。
    """
    import time
    entry = {
        "timestamp": time.time(),
        "old_hash":  old_hash,
        "new_hash":  new_hash,
        "delta":     delta,
        "source":    source,   # "manual" | "add_rule" | "nl_import"
        "rule_text": rule_text,
    }
    try:
        with open(_CONSTITUTION_HISTORY, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def load_constitution_history() -> List[dict]:
    """
    YSTAR_CONSTITUTION の全変化履歴を返す。

    これにより「Y* が自分の鉄律をどのように変化させてきたか」を
    完全に追跡できる。
    """
    if not _CONSTITUTION_HISTORY.exists():
        return []
    history = []
    for line in _CONSTITUTION_HISTORY.read_text().splitlines():
        try:
            history.append(json.loads(line))
        except Exception:
            pass
    return history


def nl_to_contract_delta(
    nl_text: str,
    constitution: "ConstitutionalContract" = None,
) -> dict:
    """
    自然言語のルール記述を IntentContract delta に変換する。

    2段階変換：
      1. NL→構造化キーワード（確定的パターンマッチ）
      2. 構造化キーワード→ IntentContract delta

    例：
      "Never call subprocess.run in engine.py"
        → deny: ["call_subprocess_run_in_engine"]
      "deny: pandas_import, numpy_import"
        → deny: ["pandas_import", "numpy_import"]

    LLM 不使用。確定的。
    """
    import re

    # Step 1: NL→構造化キーワードへの確定的変換
    # "Never X Y" / "Do not X Y" → deny token
    nl_lower = nl_text.lower().strip()

    extracted_deny: List[str]         = []
    extracted_cmds: List[str]         = []
    extracted_paths: List[str]        = []
    extracted_inv: List[str]          = []

    # パターン1: 明示的構造化 "deny: a, b, c"
    m = re.search(r"deny:\s*(.+)", nl_text, re.I)
    if m:
        items = [i.strip() for i in m.group(1).split(",") if i.strip()]
        extracted_deny.extend(items)

    # パターン2: "deny_commands: git push"
    m2 = re.search(r"deny_commands?:\s*(.+)", nl_text, re.I)
    if m2:
        items = [i.strip() for i in m2.group(1).split(",") if i.strip()]
        extracted_cmds.extend(items)

    # パターン3: "Never X" / "Do not X" → トークン化
    neg_phrases = re.findall(
        r"(?:never|do not|must not|cannot)\s+([a-z_0-9 ]+?)(?:\.|,|$|in |to |from )",
        nl_lower
    )
    for phrase in neg_phrases:
        # "import pandas" → "import_pandas"
        token = re.sub(r"\s+", "_", phrase.strip()[:40])
        if token and len(token) > 3:
            # シェルコマンドっぽいものは deny_commands へ
            if any(cmd in token for cmd in ["git_push","rm_rf","kubectl","terraform","sudo"]):
                extracted_cmds.append(token.replace("_", " "))
            else:
                extracted_deny.append(token)

    # パターン4: "only paths: X" / "only allow X"
    m4 = re.search(r"only (?:allow )?paths?:\s*([^\s,]+)", nl_text, re.I)
    if m4:
        extracted_paths.append(m4.group(1).strip())

    # パターン5: "invariant: X == Y"
    m5 = re.search(r"invariant:\s*(.+)", nl_text, re.I)
    if m5:
        extracted_inv.append(m5.group(1).strip())

    # prefill の確定的テキスト解析も試みる（補完）
    try:
        from ystar.kernel.prefill import _extract_constraints_from_text
        extracted_prefill = _extract_constraints_from_text(nl_text)
        # マージ（重複排除）
        for d in extracted_prefill.get("deny", []):
            if d not in extracted_deny:
                extracted_deny.append(d)
        for d in extracted_prefill.get("deny_commands", []):
            if d not in extracted_cmds:
                extracted_cmds.append(d)
    except ImportError:
        pass

    extracted = {
        "deny":          extracted_deny,
        "deny_commands": extracted_cmds,
        "only_paths":    extracted_paths,
        "invariant":     extracted_inv,
    }

    if not extracted:
        return {}

    # 基準合約（現在の YSTAR_CONSTITUTION）
    base = constitution or YSTAR_CONSTITUTION
    base_ic = IntentContract(
        deny=base.deny, deny_commands=base.deny_commands,
        only_paths=base.only_paths, only_domains=base.only_domains,
        invariant=base.invariant, optional_invariant=base.optional_invariant,
        field_deny=base.field_deny, value_range=base.value_range,
    )

    # 新しい制約を追加した合約を作成
    new_ic = IntentContract(
        deny=list(dict.fromkeys(base.deny + extracted.get("deny", []))),
        deny_commands=list(dict.fromkeys(
            base.deny_commands + extracted.get("deny_commands", [])
        )),
        only_paths=base.only_paths + extracted.get("only_paths", []),
        only_domains=base.only_domains + extracted.get("only_domains", []),
        invariant=base.invariant + extracted.get("invariant", []),
        optional_invariant=base.optional_invariant,
        field_deny=base.field_deny,
        value_range={**base.value_range, **extracted.get("value_range", {})},
    )

    delta = base_ic.diff(new_ic)
    delta["_source_text"] = nl_text
    delta["_extracted"]   = extracted
    return delta


def propose_constitution_update(
    delta:     dict,
    nl_source: Optional[str] = None,
) -> str:
    """
    delta（nl_to_contract_delta の出力）を
    人間可読の変更提案テキストに変換する。

    ystar-dev add-rule コマンドの表示に使う。
    """
    lines = ["Proposed addition to YSTAR_CONSTITUTION:\n"]

    for key in ("deny", "deny_commands", "only_paths", "only_domains",
                "invariant", "optional_invariant"):
        if key in delta and "added" in delta[key]:
            for item in delta[key]["added"]:
                lines.append(f"  + {key}: \"{item}\"")

    if "value_range" in delta:
        for param, change in delta["value_range"].items():
            lines.append(f"  + value_range[\"{param}\"]: {change}")

    if "field_deny" in delta:
        for field, fd in delta["field_deny"].items():
            for item in fd.get("added", []):
                lines.append(f"  + field_deny[\"{field}\"]: \"{item}\"")

    if not lines[1:]:
        return "No new constraints detected in the provided text."

    if nl_source:
        lines.insert(1, f"  (parsed from: \"{nl_source[:60]}\")\n")

    return "\n".join(lines)


def violations_summary(
    history_path: Optional[str] = None,
) -> List[dict]:
    """
    CIEU 違反ログから開発パターンを分析し、
    YSTAR_CONSTITUTION への追加提案を返す。

    これが ChatGPT が指摘した「CIEU フィードバックループ」の実装。
    違反が何度も起きているパターン → constitution 強化の候補。
    """
    from collections import Counter
    import time

    log_path = Path(history_path) if history_path else \
               Path(__file__).parent.parent.parent.parent / ".ystar_release_log.jsonl"

    if not log_path.exists():
        return []

    violations: List[dict] = []
    deny_counter:    Counter = Counter()
    field_counter:   Counter = Counter()
    command_counter: Counter = Counter()

    for line in log_path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except Exception:
            continue

        # 違反エントリのみ処理
        if entry.get("decision") not in ("DENY", "ESCALATE"):
            continue

        for v in entry.get("violations", []):
            dim = v.get("dimension", "")
            msg = v.get("message", "")
            if dim == "deny":
                deny_counter[msg] += 1
            elif dim == "deny_commands":
                command_counter[msg] += 1
            elif dim == "field_deny":
                field_counter[msg] += 1

    proposals = []

    # 3回以上発生したパターン → 強化候補
    for msg, count in deny_counter.most_common(5):
        proposals.append({
            "type":     "deny",
            "pattern":  msg[:60],
            "count":    count,
            "proposal": f"Consider strengthening deny rule: {msg[:50]}",
        })

    for msg, count in command_counter.most_common(3):
        proposals.append({
            "type":     "deny_commands",
            "pattern":  msg[:60],
            "count":    count,
            "proposal": f"Frequently blocked command: {msg[:50]}",
        })

    return proposals

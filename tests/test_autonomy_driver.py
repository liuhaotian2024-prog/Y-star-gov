"""
tests.test_autonomy_driver  —  AutonomyEngine (prescriptive queue) 单元测试
==========================================================================

AMENDMENT-014: AutonomyDriver merged into AutonomyEngine.

测试覆盖：
  1. pull_next_action 返回非空
  2. recompute_action_queue 后 queue 非空
  3. detect_off_target 检测正确
  4. claim_orphan_obligations 认领孤儿义务
  5. action_queue 优先级排序正确
  6. priority_brief 解析正确
  7. empty queue 自动 recompute
  8. get_action_queue_summary 返回有效摘要
"""
import tempfile
from pathlib import Path
import pytest

from ystar.governance.autonomy_engine import (
    AutonomyEngine, Action, PriorityBrief
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, Severity
)


@pytest.fixture
def omission_store():
    """创建测试用 OmissionStore。"""
    store = InMemoryOmissionStore()
    # 添加一些 pending obligations (use actor_id, notes, not owner/description)
    store.add_obligation(ObligationRecord(
        obligation_id="obl_001",
        entity_id="task_001",
        actor_id="cto",
        obligation_type="p0_bug_fix",
        notes="Fix CIEU persistence",
        status=ObligationStatus.PENDING,
        severity=Severity.HIGH
    ))
    store.add_obligation(ObligationRecord(
        obligation_id="obl_002",
        entity_id="task_002",
        actor_id="cmo",
        obligation_type="blog_first_draft",
        notes="Write launch blog",
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM
    ))
    # Orphan obligation (actor_id="")
    store.add_obligation(ObligationRecord(
        obligation_id="obl_003",
        entity_id="task_003",
        actor_id="",  # orphan
        obligation_type="code_review",
        notes="Review PR #123",
        status=ObligationStatus.PENDING,
        severity=Severity.LOW
    ))
    return store


@pytest.fixture
def priority_brief_file():
    """创建测试用 priority_brief.md。"""
    content = """---
campaign: Y*Defuse Launch
day: 3
---

## Today's Targets
today_targets:
  - Fix CIEU persistence bug
  - Write launch blog draft
  - Review pending PRs

## This Week
this_week_targets:
  - PyPI 0.49.0 release
  - Show HN submission
  - 3 customer calls

## This Month
this_month_targets:
  - 10K users
  - 20K GitHub stars
  - arXiv paper submission
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        return Path(f.name)


@pytest.fixture
def driver(omission_store, priority_brief_file):
    """创建测试用 AutonomyEngine (prescriptive mode)。"""
    from ystar.governance.omission_engine import OmissionEngine
    role_capabilities = {
        "ceo": ["delegation", "coordination"],
        "cto": ["code", "test", "debug"],
        "cmo": ["content", "blog"],
    }
    oe = OmissionEngine(store=omission_store)
    return AutonomyEngine(
        mode="desire-driven",
        omission_engine=oe,
        role_capabilities=role_capabilities,
        priority_brief_path=str(priority_brief_file)
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_pull_next_action_returns_action(driver):
    """测试 pull_next_action 返回非空。"""
    action = driver.pull_next_action("cto")
    assert action is not None
    assert isinstance(action, Action)
    assert action.description != ""


def test_recompute_action_queue_non_empty(driver):
    """测试 recompute 后 queue 非空。"""
    driver.recompute_action_queue("cto")
    queue = driver.action_queues.get("cto", [])
    assert len(queue) > 0


def test_detect_off_target_true(driver):
    """测试 detect_off_target 返回 True (偏离)。"""
    off_target = driver.detect_off_target("ceo", "meta-governance tuning")
    assert off_target is True


def test_detect_off_target_false(driver):
    """测试 detect_off_target 返回 False (未偏离)。"""
    off_target = driver.detect_off_target("ceo", "Fix CIEU persistence bug")
    assert off_target is False


def test_claim_orphan_obligations(driver):
    """测试 claim_orphan_obligations 认领孤儿义务。"""
    # 初始状态：obl_003 是 orphan
    orphan = driver.omission_engine.store.get_obligation("obl_003")
    assert orphan.actor_id == ""

    # 认领
    driver.claim_orphan_obligations()

    # 验证：orphan 已被认领
    orphan_after = driver.omission_engine.store.get_obligation("obl_003")
    assert orphan_after.actor_id != ""
    assert orphan_after.actor_id == "cto"  # code_review → cto


def test_action_queue_priority_ordering(driver):
    """测试 action_queue 优先级排序。"""
    driver.recompute_action_queue("cto")
    queue = driver.action_queues.get("cto", [])

    # priority=0 (daily_target) 应该在最前面
    assert queue[0].priority == 0
    assert "daily_target" in queue[0].tags


def test_priority_brief_parsing(driver):
    """测试 priority_brief 解析正确。"""
    brief = driver._load_priority_brief()
    assert isinstance(brief, PriorityBrief)
    assert len(brief.today_targets) == 3
    assert "Fix CIEU persistence bug" in brief.today_targets
    assert len(brief.this_week_targets) == 3
    assert brief.campaign == "Y*Defuse Launch"
    assert brief.day == 3


def test_empty_queue_auto_recompute(driver):
    """测试空 queue 自动 recompute。"""
    # 清空 queue
    driver.action_queues["ceo"] = []

    # pull 应该触发 recompute
    action = driver.pull_next_action("ceo")
    assert action is not None


def test_get_action_queue_summary(driver):
    """测试 get_action_queue_summary 返回有效摘要。"""
    summary = driver.get_action_queue_summary("cto")
    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "[1]" in summary  # 至少有一个 action


def test_create_autonomy_driver_factory():
    """测试 AutonomyEngine 工厂构造（AMENDMENT-014: no separate factory)。"""
    driver = AutonomyEngine(mode="desire-driven")
    assert isinstance(driver, AutonomyEngine)
    assert driver.omission_engine.store is not None
    assert len(driver.role_capabilities) > 0


def test_pending_obligations_for_agent(driver):
    """测试 _get_pending_obligations 过滤正确。"""
    pending_cto = driver._get_pending_obligations("cto")
    assert len(pending_cto) == 1
    assert pending_cto[0].obligation_id == "obl_001"

    pending_cmo = driver._get_pending_obligations("cmo")
    assert len(pending_cmo) == 1
    assert pending_cmo[0].obligation_id == "obl_002"


def test_infer_owner_heuristics(driver):
    """测试 _infer_owner 启发式推断。"""
    assert driver._infer_owner("p0_bug_fix") == "cto"
    assert driver._infer_owner("blog_first_draft") == "cmo"
    assert driver._infer_owner("delegation") == "ceo"
    assert driver._infer_owner("governance_check") == "eng-governance"
    assert driver._infer_owner("unknown_type") is None


def test_action_queue_deduplication(driver):
    """测试 action_queue 不重复添加相同 obligation。"""
    driver.recompute_action_queue("cto")
    queue_len_1 = len(driver.action_queues["cto"])

    # 再次 recompute
    driver.recompute_action_queue("cto")
    queue_len_2 = len(driver.action_queues["cto"])

    # 长度应该相同（因为 obligation 没变）
    assert queue_len_1 == queue_len_2


def test_pull_next_action_decrements_queue(driver):
    """测试 pull_next_action 减少 queue 长度。"""
    driver.recompute_action_queue("cto")
    initial_len = len(driver.action_queues["cto"])

    driver.pull_next_action("cto")
    after_len = len(driver.action_queues["cto"])

    assert after_len == initial_len - 1

"""
tests.test_autonomy_driver_integration  —  AutonomyEngine 集成测试
====================================================================

AMENDMENT-014: AutonomyDriver merged into AutonomyEngine.

模拟真实场景：
  1. CEO idle 5 min → ADE 自动 pull → CEO context 收到下一活
  2. priority_brief 驱动 action_queue 生成
  3. orphan obligations 自动派发
  4. OFF_TARGET 检测触发 recompute
"""
import tempfile
import time
from pathlib import Path
import pytest

from ystar.governance.autonomy_engine import AutonomyEngine
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, Severity
)


def test_ceo_idle_5min_auto_pull():
    """模拟 CEO idle 5 min → ADE 自动 pull 下一活。"""
    # 创建 priority_brief
    brief_content = """---
campaign: Y*Defuse Launch
day: 3
---

## Today's Targets
today_targets:
  - Fix CIEU persistence bug
  - Build ADE MVP
  - Update priority_brief schema

## This Week
this_week_targets:
  - PyPI 0.49.0 release
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(brief_content)
        brief_path = f.name

    # 创建 store + engine
    store = InMemoryOmissionStore()
    oe = OmissionEngine(store=store)
    driver = AutonomyEngine(
        mode="desire-driven",
        omission_engine=oe,
        priority_brief_path=brief_path
    )

    # 模拟 CEO idle → pull next
    action = driver.pull_next_action("ceo")
    assert action is not None
    assert "CIEU persistence" in action.description
    assert action.priority == 0  # daily_target 最优先

    Path(brief_path).unlink()  # cleanup


def test_priority_brief_drives_action_queue():
    """测试 priority_brief 驱动 action_queue 生成。"""
    brief_content = """---
campaign: Internal Consolidation
day: 1
---

## Today's Targets
today_targets:
  - Governance infrastructure 3 roots
  - AMENDMENT-009 implementation
  - CIEU persistence fix

## This Week
this_week_targets:
  - Amendment voting
  - Continuity Guardian v2
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(brief_content)
        brief_path = f.name

    driver = create_autonomy_driver(priority_brief_path=brief_path)
    driver.recompute_action_queue("ceo")

    queue = driver.action_queues["ceo"]
    assert len(queue) >= 5  # 3 daily + 2 weekly

    # 验证优先级排序
    daily_actions = [a for a in queue if "daily_target" in a.tags]
    assert len(daily_actions) == 3
    assert all(a.priority == 0 for a in daily_actions)

    Path(brief_path).unlink()


def test_orphan_obligations_auto_dispatch():
    """测试 orphan obligations 自动派发。"""
    store = InMemoryOmissionStore()

    # 添加多个 orphan obligations
    store.add_obligation(ObligationRecord(
        obligation_id="orphan_001",
        entity_id="task_001",
        actor_id="",  # orphan
        obligation_type="p0_bug_fix",
        notes="Fix critical bug",
        status=ObligationStatus.PENDING
    ))
    store.add_obligation(ObligationRecord(
        obligation_id="orphan_002",
        entity_id="task_002",
        actor_id="",  # orphan
        obligation_type="blog_first_draft",
        notes="Write blog",
        status=ObligationStatus.PENDING
    ))
    store.add_obligation(ObligationRecord(
        obligation_id="orphan_003",
        entity_id="task_003",
        actor_id="",  # orphan
        obligation_type="governance_check",
        notes="Run governance audit",
        status=ObligationStatus.PENDING
    ))

    driver = create_autonomy_driver(omission_store=store)
    driver.claim_orphan_obligations()

    # 验证所有 orphan 已被认领
    obl_001 = store.get_obligation("orphan_001")
    obl_002 = store.get_obligation("orphan_002")
    obl_003 = store.get_obligation("orphan_003")

    assert obl_001.actor_id == "cto"
    assert obl_002.actor_id == "cmo"
    assert obl_003.actor_id == "eng-governance"


def test_off_target_detection_triggers_warning():
    """测试 OFF_TARGET 检测触发警告。"""
    brief_content = """---
today_targets:
  - Fix CIEU persistence
  - Build autonomy driver
  - Write integration tests
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(brief_content)
        brief_path = f.name

    driver = create_autonomy_driver(priority_brief_path=brief_path)

    # ON_TARGET case
    on_target = driver.detect_off_target("ceo", "Fix CIEU persistence bug in store.py")
    assert on_target is False

    # OFF_TARGET case (doing meta-governance instead of daily targets)
    off_target = driver.detect_off_target("ceo", "refactor governance loop architecture")
    assert off_target is True

    Path(brief_path).unlink()


def test_action_queue_summary_for_boot_packages():
    """测试 get_action_queue_summary 输出格式（用于 boot_packages.category_11）。"""
    brief_content = """---
today_targets:
  - Fix CIEU persistence bug
  - Build ADE MVP
  - Write tests
this_week_targets:
  - PyPI release
  - Show HN
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(brief_content)
        brief_path = f.name

    driver = create_autonomy_driver(priority_brief_path=brief_path)
    summary = driver.get_action_queue_summary("ceo")

    assert isinstance(summary, str)
    assert "[1]" in summary
    assert "why:" in summary
    assert "verify:" in summary

    Path(brief_path).unlink()


def test_pull_next_action_with_mixed_sources():
    """测试混合来源（daily_target + obligation + weekly_target）的 action_queue。"""
    brief_content = """---
today_targets:
  - Fix bug A
this_week_targets:
  - Feature B
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(brief_content)
        brief_path = f.name

    store = InMemoryOmissionStore()
    store.add_obligation(ObligationRecord(
        obligation_id="obl_001",
        entity_id="task_001",
        actor_id="ceo",
        obligation_type="directive_decomposition",
        notes="Decompose AMENDMENT-009",
        status=ObligationStatus.PENDING
    ))

    driver = create_autonomy_driver(
        omission_store=store,
        priority_brief_path=brief_path
    )

    # Pull 应该先返回 daily_target (priority=0)
    action1 = driver.pull_next_action("ceo")
    assert action1.source == "priority_brief"
    assert action1.priority == 0

    # 然后是 obligation (priority=1)
    action2 = driver.pull_next_action("ceo")
    assert action2.source == "obligation_backlog"
    assert action2.priority == 1

    # 最后是 weekly_target (priority=2)
    action3 = driver.pull_next_action("ceo")
    assert action3.source == "priority_brief"
    assert action3.priority == 2

    Path(brief_path).unlink()


def test_recompute_is_idempotent():
    """测试 recompute 幂等性（重复调用不会重复添加）。"""
    brief_content = """---
today_targets:
  - Task A
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(brief_content)
        brief_path = f.name

    driver = create_autonomy_driver(priority_brief_path=brief_path)

    driver.recompute_action_queue("ceo")
    len1 = len(driver.action_queues["ceo"])

    driver.recompute_action_queue("ceo")
    len2 = len(driver.action_queues["ceo"])

    assert len1 == len2  # 幂等性

    Path(brief_path).unlink()

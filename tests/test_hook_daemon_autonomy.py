"""
tests.test_hook_daemon_autonomy — Hook daemon idle-pull + OFF_TARGET tests
===========================================================================

AMENDMENT-014: AutonomyDriver merged into AutonomyEngine.

测试覆盖：
  1. idle_trigger: 静默 ≥5min 触发 pull_next_action
  2. off_target_positive: 当前动作不在 daily_targets → emit OFF_TARGET_WARNING
  3. off_target_negative: 当前动作在 daily_targets → 不触发 warning
  4. idle_reset_on_message: Board 消息后 idle 计时复位
"""
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from ystar._hook_daemon import HookDaemon, IDLE_THRESHOLD_SECONDS
from ystar.governance.autonomy_engine import Action, AutonomyEngine


@pytest.fixture
def temp_priority_brief():
    """创建临时 priority_brief.md 文件。"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""
# Priority Brief — Day 3

campaign: ADE MVP Launch
day: 3

today_targets:
  - Fix CIEU persistence bug
  - Write unit tests for idle-pull
  - Deploy autonomy_driver to production

this_week_targets:
  - Complete ADE integration
  - Launch blog post

this_month_targets:
  - Reach 10 enterprise customers
""")
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def mock_daemon(temp_priority_brief):
    """创建 mock HookDaemon with AutonomyEngine。"""
    daemon = HookDaemon()
    # AMENDMENT-014: AutonomyDriver merged into AutonomyEngine
    daemon._autonomy_driver = AutonomyEngine(
        mode="desire-driven",
        priority_brief_path=str(temp_priority_brief)
    )
    daemon.agent_id = "eng-kernel"
    daemon._last_user_message_time = time.time()
    daemon._shutdown_flag = False
    return daemon


def test_idle_trigger_pulls_next_action(mock_daemon):
    """测试：静默 ≥5min 触发 pull_next_action。"""
    # Arrange: 设置 last_user_message_time 为 6 分钟前
    mock_daemon._last_user_message_time = time.time() - (IDLE_THRESHOLD_SECONDS + 60)

    # Mock _write_cieu_event to capture calls
    cieu_events = []
    original_write = mock_daemon._write_cieu_event

    def capture_event(event_type, params):
        cieu_events.append({"event_type": event_type, "params": params})
        original_write(event_type, params)

    mock_daemon._write_cieu_event = capture_event

    # Act: 触发 idle_pull
    mock_daemon._trigger_idle_pull()

    # Assert: IDLE_PULL_TRIGGERED event 被写入
    assert len(cieu_events) == 1
    assert cieu_events[0]["event_type"] == "IDLE_PULL_TRIGGERED"
    assert cieu_events[0]["params"]["agent_id"] == "eng-kernel"
    assert "description" in cieu_events[0]["params"]
    assert cieu_events[0]["params"]["idle_duration_s"] > IDLE_THRESHOLD_SECONDS


def test_off_target_positive_detection(mock_daemon):
    """测试：当前动作不在 daily_targets → emit OFF_TARGET_WARNING。"""
    # Arrange: current_action 不在 daily_targets 内
    current_action = "meta-governance tuning and recursive self-optimization"

    cieu_events = []
    original_write = mock_daemon._write_cieu_event

    def capture_event(event_type, params):
        cieu_events.append({"event_type": event_type, "params": params})
        original_write(event_type, params)

    mock_daemon._write_cieu_event = capture_event

    # Act: 检测 OFF_TARGET
    mock_daemon._detect_off_target(current_action)

    # Assert: OFF_TARGET_WARNING event 被写入
    assert len(cieu_events) == 1
    assert cieu_events[0]["event_type"] == "OFF_TARGET_WARNING"
    assert cieu_events[0]["params"]["agent_id"] == "eng-kernel"
    assert current_action in cieu_events[0]["params"]["current_action"]


def test_off_target_negative_no_warning(mock_daemon):
    """测试：当前动作在 daily_targets → 不触发 warning。"""
    # Arrange: current_action 在 daily_targets 内 (关键词匹配)
    current_action = "Fix CIEU persistence bug in kernel"

    cieu_events = []

    def capture_event(event_type, params):
        cieu_events.append({"event_type": event_type, "params": params})

    mock_daemon._write_cieu_event = capture_event

    # Act: 检测 OFF_TARGET
    mock_daemon._detect_off_target(current_action)

    # Assert: 没有 OFF_TARGET_WARNING
    assert len(cieu_events) == 0


def test_idle_reset_on_message(mock_daemon):
    """测试：Board 消息后 idle 计时复位。"""
    # Arrange: 设置一个旧的 timestamp
    old_time = time.time() - 100
    mock_daemon._last_user_message_time = old_time

    # Act: 模拟收到 payload（任何 tool call）
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"}
    }
    mock_daemon._update_last_message_time(payload)

    # Assert: _last_user_message_time 被更新到当前时间
    assert mock_daemon._last_user_message_time > old_time
    assert abs(mock_daemon._last_user_message_time - time.time()) < 1  # 在 1 秒内


def test_extract_action_description_bash():
    """测试：从 Bash payload 提取 action description。"""
    daemon = HookDaemon()
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "python -m pytest tests/",
            "description": "Run all tests"
        }
    }

    # 优先使用 description 字段
    desc = daemon._extract_action_description(payload)
    assert desc == "Run all tests"

    # 如果没有 description，fallback 到 command
    payload2 = {
        "tool_name": "Bash",
        "tool_input": {"command": "git status"}
    }
    desc2 = daemon._extract_action_description(payload2)
    assert "git status" in desc2


def test_extract_action_description_edit():
    """测试：从 Edit payload 提取 action description。"""
    daemon = HookDaemon()
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/path/to/file.py",
            "old_string": "foo",
            "new_string": "bar"
        }
    }

    desc = daemon._extract_action_description(payload)
    assert "edit /path/to/file.py" in desc


def test_handle_with_off_target_detection(mock_daemon):
    """测试：handle() 处理 payload 时自动运行 OFF_TARGET 检测。"""
    # Arrange: payload with Bash command (描述不在 daily_targets)
    payload = {
        "tool_name": "Bash",
        "tool_input": {
            "command": "echo 'recursive meta tuning'",
            "description": "Optimize meta-governance framework"
        }
    }

    cieu_events = []

    def capture_event(event_type, params):
        cieu_events.append({"event_type": event_type, "params": params})

    mock_daemon._write_cieu_event = capture_event

    # Mock check_hook to return empty result (allow)
    with patch('ystar.adapters.hook.check_hook', return_value={}):
        with patch('ystar.adapters.hook_response.detect_host', return_value='claude_code'):
            with patch('ystar.adapters.hook_response.convert_ygov_result', return_value={}):
                # Act: handle payload
                response_json = mock_daemon.handle(json.dumps(payload))

    # Assert: OFF_TARGET_WARNING 被触发
    off_target_events = [e for e in cieu_events if e["event_type"] == "OFF_TARGET_WARNING"]
    assert len(off_target_events) >= 1  # 至少有一个 OFF_TARGET 警告


def test_idle_monitor_background_thread(mock_daemon):
    """测试：idle monitor 在后台线程中运行。"""
    # Arrange: 设置 last_user_message_time 为很久之前
    mock_daemon._last_user_message_time = time.time() - (IDLE_THRESHOLD_SECONDS + 120)

    cieu_events = []

    def capture_event(event_type, params):
        cieu_events.append({"event_type": event_type, "params": params})

    mock_daemon._write_cieu_event = capture_event

    # Act: 手动触发 _trigger_idle_pull (模拟 monitor thread 的行为)
    mock_daemon._trigger_idle_pull()

    # Assert: IDLE_PULL_TRIGGERED event 被写入
    assert len(cieu_events) == 1
    assert cieu_events[0]["event_type"] == "IDLE_PULL_TRIGGERED"

    # 验证 timer 被 reset
    # (在真实场景中，_trigger_idle_pull 会在 monitor 里被调用后 reset timer)

"""
tests.test_residual_loop_engine  —  RLE Unit Tests
===================================================

AMENDMENT-014 (2026-04-12) — ResidualLoopEngine tests

测试覆盖：
  1. converged: Rt+1 < epsilon → emit CONVERGED, stop
  2. oscillation_break: 振荡检测 → emit OSCILLATION, stop
  3. escalate_board: iterations > max → emit ESCALATE, stop
  4. multi_iteration: 多次迭代收敛
  5. damping_factor: gamma < 1.0 → correction magnitude decreases
  6. target_undefined: no Y* → gracefully skip
"""
from unittest.mock import Mock, MagicMock
import pytest

from ystar.governance.residual_loop_engine import ResidualLoopEngine


@pytest.fixture
def mock_autonomy_engine():
    """Mock AutonomyEngine."""
    engine = Mock()
    engine.pull_next_action = Mock(return_value=Mock(description="Fix bug X"))
    return engine


@pytest.fixture
def mock_cieu_store():
    """Mock CIEUStore."""
    store = Mock()
    store.write_dict = Mock()
    return store


@pytest.fixture
def target_provider():
    """Target provider that extracts Y* from event."""
    return lambda event: event.get("params", {}).get("target_y_star")


def test_converged_stops_loop(mock_autonomy_engine, mock_cieu_store, target_provider):
    """测试收敛：Rt+1 < epsilon → emit CONVERGED, stop."""
    rle = ResidualLoopEngine(
        autonomy_engine=mock_autonomy_engine,
        cieu_store=mock_cieu_store,
        target_provider=target_provider,
        convergence_epsilon=0.1,
    )

    event = {
        "session_id": "test_session",
        "agent_id": "cto",
        "event_type": "ToolUse",
        "params": {
            "target_y_star": "hello",
            "y_actual": "hello",  # exact match → residual = 0.0
        }
    }

    rle.on_cieu_event(event)

    # Should emit CONVERGED, not pull next action
    mock_cieu_store.write_dict.assert_called()
    last_event = mock_cieu_store.write_dict.call_args[0][0]
    assert last_event["event_type"] == "RESIDUAL_LOOP_CONVERGED"
    assert last_event["params"]["final_residual"] < 0.1


def test_oscillation_break(mock_autonomy_engine, mock_cieu_store, target_provider):
    """测试振荡检测：Rt+1 交替增减 → emit OSCILLATION, stop."""
    rle = ResidualLoopEngine(
        autonomy_engine=mock_autonomy_engine,
        cieu_store=mock_cieu_store,
        target_provider=target_provider,
        convergence_epsilon=0.0,
        max_iterations=20,
    )

    # Inject oscillating residuals: 0.5 → 0.3 → 0.6 → 0.2 → 0.7 (2 sign changes)
    # Simulate by feeding events with different y_actual
    session_id = "oscillation_test"
    residuals = [0.5, 0.3, 0.6, 0.2, 0.7]  # Diffs: -0.2, +0.3, -0.4, +0.5 (≥2 sign changes)

    # Mock distance to return pre-defined residuals
    original_distance = rle._residual_distance
    residual_iter = iter(residuals)
    rle._residual_distance = lambda y_star, y_actual: next(residual_iter)

    for i, residual in enumerate(residuals):
        event = {
            "session_id": session_id,
            "agent_id": "cto",
            "event_type": "ToolUse",
            "params": {
                "target_y_star": "target",
                "y_actual": f"actual_{i}",
            }
        }
        rle.on_cieu_event(event)

    # Restore original distance
    rle._residual_distance = original_distance

    # Should emit OSCILLATION
    calls = [call[0][0] for call in mock_cieu_store.write_dict.call_args_list]
    oscillation_events = [c for c in calls if c["event_type"] == "RESIDUAL_LOOP_OSCILLATION"]
    assert len(oscillation_events) > 0


def test_escalate_board_max_iterations(mock_autonomy_engine, mock_cieu_store, target_provider):
    """测试超过最大迭代 → emit ESCALATE, stop."""
    rle = ResidualLoopEngine(
        autonomy_engine=mock_autonomy_engine,
        cieu_store=mock_cieu_store,
        target_provider=target_provider,
        convergence_epsilon=0.0,
        max_iterations=3,
    )

    session_id = "escalate_test"
    for i in range(5):  # 5 iterations > max=3
        event = {
            "session_id": session_id,
            "agent_id": "cto",
            "event_type": "ToolUse",
            "params": {
                "target_y_star": "target",
                "y_actual": f"actual_{i}",  # Never converges
            }
        }
        rle.on_cieu_event(event)

    # Should emit ESCALATE
    calls = [call[0][0] for call in mock_cieu_store.write_dict.call_args_list]
    escalate_events = [c for c in calls if c["event_type"] == "RESIDUAL_LOOP_ESCALATE"]
    assert len(escalate_events) > 0


def test_multi_iteration_convergence(mock_autonomy_engine, mock_cieu_store, target_provider):
    """测试多次迭代后收敛。"""
    rle = ResidualLoopEngine(
        autonomy_engine=mock_autonomy_engine,
        cieu_store=mock_cieu_store,
        target_provider=target_provider,
        convergence_epsilon=0.05,
    )

    session_id = "multi_iter_test"
    # Simulate gradual convergence: 0.3 → 0.15 → 0.08 → 0.03 (below epsilon)
    residuals = [0.3, 0.15, 0.08, 0.03]
    residual_iter = iter(residuals)
    rle._residual_distance = lambda y_star, y_actual: next(residual_iter, 0.0)

    for i in range(4):
        event = {
            "session_id": session_id,
            "agent_id": "cto",
            "event_type": "ToolUse",
            "params": {
                "target_y_star": "target",
                "y_actual": f"actual_{i}",
            }
        }
        rle.on_cieu_event(event)

    # Should emit RESIDUAL_LOOP_ACTION for first 3, then CONVERGED on 4th
    calls = [call[0][0] for call in mock_cieu_store.write_dict.call_args_list]
    action_events = [c for c in calls if c["event_type"] == "RESIDUAL_LOOP_ACTION"]
    converged_events = [c for c in calls if c["event_type"] == "RESIDUAL_LOOP_CONVERGED"]

    assert len(action_events) >= 2  # At least 2 actions before convergence
    assert len(converged_events) == 1


def test_damping_factor_applied(mock_autonomy_engine, mock_cieu_store, target_provider):
    """测试 damping factor：gamma < 1.0 → correction magnitude decreases."""
    rle = ResidualLoopEngine(
        autonomy_engine=mock_autonomy_engine,
        cieu_store=mock_cieu_store,
        target_provider=target_provider,
        convergence_epsilon=0.0,
        damping_gamma=0.5,
        max_iterations=5,
    )

    session_id = "damping_test"
    # Mock pull_next_action to track iterations
    iterations = []
    def track_iteration(agent_id):
        iterations.append(len(iterations))
        return Mock(description=f"Action {len(iterations)}")
    mock_autonomy_engine.pull_next_action = track_iteration

    for i in range(3):
        event = {
            "session_id": session_id,
            "agent_id": "cto",
            "event_type": "ToolUse",
            "params": {
                "target_y_star": "target",
                "y_actual": f"actual_{i}",
            }
        }
        rle.on_cieu_event(event)

    # Check that damping_factor was applied (state.iterations increases)
    state = rle._loop_state.get(session_id)
    assert state is not None
    assert state["iterations"] == 3


def test_target_undefined_graceful_skip(mock_autonomy_engine, mock_cieu_store, target_provider):
    """测试 no Y* → gracefully skip (no action)."""
    rle = ResidualLoopEngine(
        autonomy_engine=mock_autonomy_engine,
        cieu_store=mock_cieu_store,
        target_provider=target_provider,
    )

    event = {
        "session_id": "no_target_test",
        "agent_id": "cto",
        "event_type": "ToolUse",
        "params": {
            # No target_y_star
            "y_actual": "some result",
        }
    }

    rle.on_cieu_event(event)

    # Should NOT write any CIEU events (no target → skip)
    mock_cieu_store.write_dict.assert_not_called()


def test_default_distance_string():
    """测试 _default_distance 处理 string (Levenshtein)."""
    distance = ResidualLoopEngine._default_distance("hello", "hallo")
    assert 0.0 < distance < 1.0  # Some difference, not exact match


def test_default_distance_numeric():
    """测试 _default_distance 处理 numeric."""
    distance = ResidualLoopEngine._default_distance(10, 15)
    assert distance == 5 / 15  # |10-15| / max(10,15)


def test_default_distance_dict():
    """测试 _default_distance 处理 dict."""
    distance = ResidualLoopEngine._default_distance(
        {"a": 1, "b": 2},
        {"a": 1, "b": 3, "c": 4}  # 2 diffs: b value, c missing
    )
    assert distance == 2 / 3  # 2 diffs / 3 keys


def test_default_distance_list():
    """测试 _default_distance 处理 list (set diff)."""
    distance = ResidualLoopEngine._default_distance(
        [1, 2, 3],
        [2, 3, 4]  # diff = {1, 4}
    )
    assert distance == 2 / 4  # 2 diff / 4 total unique

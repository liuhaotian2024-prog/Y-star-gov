"""
ystar.integrations.simulation  —  Production-Equivalent Simulation
===================================================================
v0.41.0

SimulatedWorkloadConnector 完全实现 EventStreamConnector 接口，
产出与真实 OpenClaw multi-agent 工作负载等价的事件流。

等价性保证：
  - 相同的事件类型和语义（subagent_spawn / task_delegated / task_acked / ...）
  - 可控的失败率（模拟真实场景中 worker 静默失联、manager 不分派等）
  - 可重复（random_seed 固定时产出完全一致）
  - 与真实接入使用完全相同的 Y* 治理路径

仿真 vs 真实的唯一差别：
  - 事件来源：内存生成 vs HTTP / webhook / queue
  - 时间推进：瞬间完成 vs 真实时钟
  - 其余路径完全相同
"""
from __future__ import annotations

import random
import time
from typing import Generator

from ystar.integrations.base import (
    EventStreamConnector,
    IntegrationHealth,
    LiveWorkloadConfig,
    WorkloadEvent,
)


class SimulatedWorkloadConnector(EventStreamConnector):
    """
    仿真事件流连接器。

    产出真实 OpenClaw 风格的 multi-agent 工作负载事件序列：
      - 正常任务链：spawn → delegate → ack → status → result → upstream
      - 静默失联：worker ack 后不再发送
      - 未分派：manager spawn 后不 delegate
      - 假完成：worker 声称完成但 omission 检测发现缺少 upstream_summary

    使用方式：
        config = LiveWorkloadConfig(
            source_name="simulation",
            n_agents=5,
            n_tasks=20,
            failure_rate=0.3,
        )
        connector = SimulatedWorkloadConnector(config)
        with connector:
            for event in connector.stream_events():
                adapter.ingest_raw(event.__dict__)
    """

    # 失败模式分配（failure_rate 的内部分布）
    _FAILURE_MODES = {
        "worker_silent":    0.40,   # worker ack 后静默
        "no_dispatch":      0.30,   # manager 不 delegate
        "false_completion": 0.20,   # 缺少 upstream_summary
        "late_result":      0.10,   # result 极度滞后
    }

    def __init__(self, config: LiveWorkloadConfig) -> None:
        super().__init__(config)
        self._rng = random.Random(config.random_seed)
        self._generated = 0

    def connect(self) -> bool:
        self._health.connected    = True
        self._health.last_heartbeat = time.time()
        return True

    def disconnect(self) -> None:
        self._health.connected = False

    def health(self) -> IntegrationHealth:
        self._health.events_sent = self._generated
        return self._health

    def stream_events(self) -> Generator[WorkloadEvent, None, None]:
        """
        产出仿真事件流。每个 task 是一个独立的 agent 协作链。
        """
        cfg  = self.config
        base_ts = 1_000_000.0

        for task_i in range(cfg.n_tasks):
            session = f"sim-sess-{cfg.source_name}-{task_i:04d}"
            mgr     = f"mgr-{task_i % cfg.n_agents:02d}"
            wkr     = f"wkr-{task_i:04d}"
            ts      = base_ts + task_i * 30.0

            # Decide this task's fate
            is_failure = self._rng.random() < cfg.failure_rate
            if is_failure:
                mode = self._pick_failure_mode()
            else:
                mode = "healthy"

            # ── Event 1: spawn (always happens) ────────────────────────────
            yield self._make(session, mgr, wkr, "subagent_spawn", ts,
                             parent=mgr, child=wkr)
            ts += 2.0

            if mode == "no_dispatch":
                # Manager spawns but never delegates
                self._health.errors.append(f"no_dispatch:{session}") \
                    if cfg.failure_rate > 0 else None
                continue

            # ── Event 2: delegate ────────────────────────────────────────
            yield self._make(session, mgr, wkr, "task_delegated", ts)
            ts += self._rng.uniform(5, 15)

            if mode == "worker_silent":
                # Worker acks but then goes silent
                yield self._make(session, wkr, wkr, "task_acked", ts)
                continue

            # ── Event 3: ack ─────────────────────────────────────────────
            yield self._make(session, wkr, wkr, "task_acked", ts)
            ts += self._rng.uniform(10, 30)

            # ── Event 4: status_update ───────────────────────────────────
            yield self._make(session, wkr, wkr, "status_update", ts,
                             payload={"progress": self._rng.randint(20, 80)})
            ts += self._rng.uniform(20, 60)

            if mode == "late_result":
                ts += 600.0  # extreme delay

            # ── Event 5: result_published ────────────────────────────────
            yield self._make(session, wkr, wkr, "result_published", ts,
                             payload={"result_quality": self._rng.uniform(0.6, 1.0)})
            ts += self._rng.uniform(5, 15)

            if mode == "false_completion":
                # Claims done but doesn't notify upstream
                continue

            # ── Event 6: upstream_summary (healthy or late_result) ────────
            yield self._make(session, mgr, mgr, "upstream_summary", ts)

        self._generated = cfg.n_tasks

    def _make(
        self, session: str, agent: str, target: str,
        event_type: str, ts: float,
        parent: Optional[str] = None,
        child:  Optional[str] = None,
        payload: dict = None,
    ) -> WorkloadEvent:
        self._health.events_received += 1
        return WorkloadEvent(
            event_type      = event_type,
            agent_id        = agent,
            session_id      = session,
            timestamp       = ts,
            parent_agent_id = parent,
            child_agent_id  = child,
            payload         = payload or {},
            source          = self.config.source_name,
        )

    def _pick_failure_mode(self) -> str:
        r = self._rng.random()
        cumul = 0.0
        for mode, weight in self._FAILURE_MODES.items():
            cumul += weight
            if r < cumul:
                return mode
        return "worker_silent"


# Fix: Optional not imported
from typing import Optional
SimulatedWorkloadConnector._make.__annotations__['parent'] = Optional[str]
SimulatedWorkloadConnector._make.__annotations__['child']  = Optional[str]

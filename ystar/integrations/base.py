"""
ystar.integrations.base  —  Universal Connector Interface Specification  v0.41.0
=======================================================================

This is the ONLY interface Y* imposes on external frameworks.
Any multi-agent framework (OpenClaw, LangChain, CrewAI, AutoGen,
custom runtimes) can integrate with Y* by implementing this interface.

Design principle:
  Y* does not know or care which framework you use.
  It only requires that you translate your framework's events into
  WorkloadEvent objects and implement the three abstract methods below.

Reference implementations:
  - OpenClaw: ystar/integrations/openclaw.py  (SSE + webhook)
  - Simulation: ystar/integrations/simulation.py  (for testing)

To add a new framework::

    from ystar.integrations.base import EventStreamConnector, WorkloadEvent

    class MyFrameworkConnector(EventStreamConnector):
        def connect(self) -> bool: ...
        def stream_events(self) -> Generator[WorkloadEvent, None, None]: ...
        def disconnect(self) -> None: ...

    # Run governance evaluation:
    from ystar.integrations.runner import WorkloadRunner
    result = WorkloadRunner.run(MyFrameworkConnector(config))
==========================================================
v0.37.0

所有真实接入必须实现此模块定义的接口。
接口即合约——这是 Y* 对外部生态的唯一约束面。

接入新生态的步骤：
  1. 继承 EventStreamConnector
  2. 实现 connect() / stream_events() / send_decision() / disconnect()
  3. 用 WorkloadRunner 运行，结果自动进入 ReportEngine + GovernanceLoop
  4. 对比 simulation 的 baseline，计算 delta
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional


# ── 数据类型 ───────────────────────────────────────────────────────────────────

@dataclass
class WorkloadEvent:
    """
    从外部生态流入 Y* 的单个事件。
    所有接入层必须把原始事件规范化为此格式。
    """
    event_type:       str            # "subagent_spawn" / "task_acked" / ...
    agent_id:         str
    session_id:       str
    timestamp:        float = field(default_factory=time.time)
    parent_agent_id:  Optional[str] = None
    child_agent_id:   Optional[str] = None
    task_ticket_id:   Optional[str] = None
    payload:          Dict[str, Any] = field(default_factory=dict)
    source:           str = "unknown"   # "openclaw" / "simulation" / "webhook"


@dataclass
class WorkloadResult:
    """
    Y* 对一次工作负载运行的完整评估结果。
    可直接对比：simulation vs production，before vs after governance。
    """
    run_id:            str = ""
    source:            str = ""        # "simulation" / "openclaw" / ...
    duration_secs:     float = 0.0

    # 核心 KPIs（来自 ReportEngine）
    total_events:      int = 0
    total_obligations: int = 0
    violations:        int = 0
    fulfillment_rate:  float = 0.0
    recovery_rate:     float = 0.0
    false_positive_rate: float = 0.0
    chain_closure_rate:  float = 0.0

    # 治理闭环
    governance_suggestions: int = 0
    constraints_activated:  int = 0
    actors_restored:        int = 0

    # 原始报告
    raw_report:        Optional[Any] = None   # Report object

    def to_dict(self) -> dict:
        return {
            "run_id":             self.run_id,
            "source":             self.source,
            "duration_secs":      round(self.duration_secs, 2),
            "total_events":       self.total_events,
            "total_obligations":  self.total_obligations,
            "violations":         self.violations,
            "fulfillment_rate":   round(self.fulfillment_rate, 3),
            "recovery_rate":      round(self.recovery_rate, 3),
            "false_positive_rate": round(self.false_positive_rate, 3),
            "chain_closure_rate": round(self.chain_closure_rate, 3),
            "governance_suggestions": self.governance_suggestions,
            "constraints_activated":  self.constraints_activated,
            "actors_restored":        self.actors_restored,
        }

    def delta_from(self, baseline: "WorkloadResult") -> Dict[str, float]:
        """对比 baseline 的 delta，正值=改善，负值=退化。"""
        return {
            "fulfillment_rate":   self.fulfillment_rate   - baseline.fulfillment_rate,
            "recovery_rate":      self.recovery_rate      - baseline.recovery_rate,
            "false_positive_rate":-(self.false_positive_rate - baseline.false_positive_rate),
            "chain_closure_rate": self.chain_closure_rate - baseline.chain_closure_rate,
            "violations_delta":   baseline.violations - self.violations,
        }


@dataclass
class LiveWorkloadConfig:
    """连接器配置，由调用方提供。"""
    source_name:      str
    n_agents:         int   = 10
    n_tasks:          int   = 50
    failure_rate:     float = 0.3     # 0=全部成功, 1=全部失败
    governance_on:    bool  = True
    strict_timing:    bool  = False
    random_seed:      int   = 42

    # 真实接入专用字段（仿真不使用）
    endpoint_url:     Optional[str] = None
    auth_token:       Optional[str] = None
    timeout_secs:     float = 30.0
    extra:            Dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrationHealth:
    """连接器健康状态快照。"""
    connected:        bool  = False
    events_received:  int   = 0
    events_sent:      int   = 0
    last_heartbeat:   float = 0.0
    errors:           List[str] = field(default_factory=list)
    latency_ms:       float = 0.0

    @property
    def healthy(self) -> bool:
        return self.connected and not self.errors


# ── 抽象接口 ───────────────────────────────────────────────────────────────────

class EventStreamConnector(ABC):
    """
    外部生态 → Y* 的事件流连接器抽象基类。

    任何真实接入（OpenClaw、webhook、Kafka、等）都必须实现此接口。
    仿真实现（SimulatedWorkloadConnector）完整实现此接口用于测试。

    实现要求：
      - connect() / disconnect() 管理连接生命周期
      - stream_events() 以 generator 形式产出 WorkloadEvent
      - send_decision() 把 Y* 的裁决发送回外部系统（可选）
      - health() 返回当前健康状态
    """

    def __init__(self, config: LiveWorkloadConfig) -> None:
        self.config  = config
        self._health = IntegrationHealth()

    @abstractmethod
    def connect(self) -> bool:
        """
        建立与外部系统的连接。
        返回 True = 连接成功，False = 失败。

        真实实现示例（OpenClaw）：
            response = requests.post(self.config.endpoint_url + "/auth",
                                     headers={"Authorization": self.config.auth_token})
            return response.status_code == 200
        """

    @abstractmethod
    def stream_events(self) -> Generator[WorkloadEvent, None, None]:
        """
        以 generator 形式产出工作负载事件流。
        调用方负责把每个事件注入 OmissionAdapter.ingest_raw()。

        真实实现示例（OpenClaw webhook）：
            for event in self._http_long_poll():
                yield WorkloadEvent(
                    event_type = event["type"],
                    agent_id   = event["agent_id"],
                    session_id = event["session_id"],
                    ...
                )
        """

    @abstractmethod
    def disconnect(self) -> None:
        """关闭连接，释放资源。"""

    def send_decision(
        self,
        event: WorkloadEvent,
        decision: str,          # "allow" / "deny" / "escalate"
        rationale: str = "",
    ) -> bool:
        """
        把 Y* 的裁决发送回外部系统。
        默认实现：no-op（仅记录）。
        真实实现应调用外部 API 把裁决注入 agent 的执行流。

        返回 True = 成功送达，False = 送达失败。
        """
        return True

    def health(self) -> IntegrationHealth:
        """返回当前连接健康状态。"""
        return self._health

    def __enter__(self) -> "EventStreamConnector":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

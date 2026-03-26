"""
ystar.integrations  —  仿真与测试基础设施
==========================================
v0.40.0  (3-B 定位调整)

【重要】这一层的定位：仿真 + 测试工具，不是生产接入路径。

正确的生产接入路径（v0.40.0 起）：
  from ystar import Policy
  from ystar.adapters.hook import check_hook

  policy = Policy.from_agents_md()         # 读 AGENTS.md，LLM 翻译
  response = check_hook(hook_payload, policy)  # 处理 OpenClaw PreToolUse hook

本层用途：
  ┌─────────────────────────────────────────────────────┐
  │  simulation.py   ← 生成仿真工作负载（ystar simulate 的基础）  │
  │  runner.py       ← A/B 对比运行器（治理 vs 无治理）             │
  │  base.py         ← 抽象接口（实现新 connector 时参考）          │
  │  openclaw.py     ← SSE/轮询 connector 骨架（待真实连接测试）    │
  └─────────────────────────────────────────────────────┘

为什么流式总线不作为主路径：
  OpenClaw 的 hook 协议是同步一问一答（PreToolUse → 决策），
  而 EventStreamConnector 是异步流式模型，两者架构不匹配。
  流式总线适合：长期监控、批量回放、A/B 实验数据生成。
  实时决策用：adapters/hook.py 的 check_hook()。
"""
from ystar.integrations.base import (
    EventStreamConnector,
    LiveWorkloadConfig,
    WorkloadEvent,
    WorkloadResult,
    IntegrationHealth,
)
from ystar.integrations.simulation import SimulatedWorkloadConnector
from ystar.integrations.runner import WorkloadRunner, run_integration_trial

__all__ = [
    "EventStreamConnector",
    "LiveWorkloadConfig",
    "WorkloadEvent",
    "WorkloadResult",
    "IntegrationHealth",
    "SimulatedWorkloadConnector",
    "WorkloadRunner",
    "run_integration_trial",
]

from ystar.integrations.base import (
    EventStreamConnector,
    LiveWorkloadConfig,
    WorkloadEvent,
    WorkloadResult,
    IntegrationHealth,
)
from ystar.integrations.simulation import SimulatedWorkloadConnector
from ystar.integrations.runner import WorkloadRunner, run_integration_trial

__all__ = [
    "EventStreamConnector",
    "LiveWorkloadConfig",
    "WorkloadEvent",
    "WorkloadResult",
    "IntegrationHealth",
    "SimulatedWorkloadConnector",
    "WorkloadRunner",
    "run_integration_trial",
]

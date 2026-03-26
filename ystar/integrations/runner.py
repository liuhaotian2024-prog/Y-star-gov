"""
ystar.integrations.runner  —  Universal Workload Runner
========================================================
v0.41.0

WorkloadRunner 接受任何实现了 EventStreamConnector 的连接器，
运行完整的治理评估周期，产出 WorkloadResult。

这是仿真 → 真实接入的关键桥梁：
  相同的 Runner，相同的评估逻辑，只有 Connector 不同。
  结果直接可比。
"""
from __future__ import annotations

import time
import uuid
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass

from ystar.integrations.base import (
    EventStreamConnector,
    LiveWorkloadConfig,
    WorkloadResult,
)


class WorkloadRunner:
    """
    通用工作负载运行器。

    工作流：
      1. 创建 Y* 治理栈（store + engine + adapter + report_engine）
      2. 可选：创建 GovernanceLoop（如果 governance_on=True）
      3. 运行 connector.stream_events()，把每个事件注入 adapter
      4. 推进时间，触发 omission scan
      5. 生成 WorkloadResult（含 KPIs 和原始 report）

    使用方式：
        # 仿真
        sim_result = WorkloadRunner.run(
            SimulatedWorkloadConnector(config),
            governance_on=True,
        )

        # 真实接入（未来）
        real_result = WorkloadRunner.run(
            OpenClawConnector(config),
            governance_on=True,
        )

        # 对比
        delta = real_result.delta_from(sim_result)
    """

    @classmethod
    def run(
        cls,
        connector: EventStreamConnector,
        governance_on: bool  = True,
        strict_timing: bool  = False,
        scan_interval_events: int = 10,  # scan every N events
    ) -> WorkloadResult:
        """
        运行完整的治理评估周期。

        Args:
            connector:            已连接的 EventStreamConnector
            governance_on:        是否启用 omission 治理
            strict_timing:        是否使用严格时限
            scan_interval_events: 每几个事件触发一次 scan

        Returns:
            WorkloadResult 含完整 KPIs
        """
        from ystar.governance.omission_store import InMemoryOmissionStore
        from ystar.governance.omission_engine import OmissionEngine
        from ystar.adapters.omission_adapter import OmissionAdapter
        from ystar.governance.omission_rules import reset_registry
        from ystar.governance.reporting import ReportEngine
        from ystar.governance.intervention_engine import InterventionEngine
        from ystar.domains.openclaw.accountability_pack import (
            apply_openclaw_accountability_pack
        )

        run_id    = str(uuid.uuid4())[:8]
        start     = time.time()
        now_val   = [1_000_000.0]
        now_fn    = lambda: now_val[0]

        store    = InMemoryOmissionStore()
        registry = reset_registry()
        if governance_on:
            apply_openclaw_accountability_pack(
                registry, strict=strict_timing
            )
        engine   = OmissionEngine(store=store, registry=registry, now_fn=now_fn)
        adapter  = OmissionAdapter(engine=engine)
        inter    = InterventionEngine(store, now_fn=now_fn)

        event_count = 0
        conn_health = connector.health()

        with connector:
            for event in connector.stream_events():
                # Normalize WorkloadEvent → raw dict for adapter
                raw = {
                    "event_type":      event.event_type,
                    "agent_id":        event.agent_id,
                    "session_id":      event.session_id,
                    "timestamp":       event.timestamp,
                    "parent_agent_id": event.parent_agent_id,
                    "child_agent_id":  event.child_agent_id,
                    "task_ticket_id":  event.task_ticket_id,
                    **event.payload,
                }
                adapter.ingest_raw(raw)

                # Advance simulated time to event's timestamp + buffer
                now_val[0] = event.timestamp + 0.1
                event_count += 1

                # Periodic scan
                if governance_on and event_count % scan_interval_events == 0:
                    engine.scan(now=now_fn())

        # Final time advance + scan (past all deadlines)
        now_val[0] += 1200.0
        if governance_on:
            scan_result = engine.scan(now=now_fn())
            inter.process_violations(scan_result.violations)

        # Generate report
        rpt_eng = ReportEngine(omission_store=store, intervention_eng=inter)
        report  = rpt_eng.baseline_report()

        # Optional: governance loop suggestions
        suggestions = 0
        if governance_on:
            try:
                from ystar.governance.governance_loop import GovernanceLoop
                from ystar.governance.metalearning import ConstraintRegistry
                cr   = ConstraintRegistry()
                loop = GovernanceLoop(
                    report_engine       = rpt_eng,
                    intervention_engine = inter,
                    constraint_registry = cr,
                )
                loop.observe_from_report(report)
                g_result    = loop.tighten()
                submitted   = loop.submit_suggestions_to_registry(g_result)
                suggestions = submitted
            except Exception:
                pass

        elapsed = time.time() - start
        kpis    = report.kpis or {}

        return WorkloadResult(
            run_id               = run_id,
            source               = connector.config.source_name,
            duration_secs        = elapsed,
            total_events         = event_count,
            total_obligations    = report.obligations.created_total,
            violations           = report.omissions.total_violations,
            fulfillment_rate     = kpis.get("obligation_fulfillment_rate", 0.0),
            recovery_rate        = kpis.get("omission_recovery_rate", 0.0),
            false_positive_rate  = kpis.get("false_positive_rate", 0.0),
            chain_closure_rate   = kpis.get("chain_closure_rate", 0.0),
            governance_suggestions = suggestions,
            constraints_activated  = 0,
            actors_restored        = 0,
            raw_report             = report,
        )

    @classmethod
    def compare(
        cls,
        baseline_connector: EventStreamConnector,
        treatment_connector: EventStreamConnector,
        label_baseline: str  = "baseline",
        label_treatment: str = "treatment",
    ) -> dict:
        """
        运行两个 connector，对比结果，返回 delta 报告。
        用于：simulation vs production，no-governance vs governance。
        """
        baseline  = cls.run(baseline_connector,  governance_on=False)
        treatment = cls.run(treatment_connector, governance_on=True)
        delta     = treatment.delta_from(baseline)

        return {
            label_baseline:  baseline.to_dict(),
            label_treatment: treatment.to_dict(),
            "delta":         {k: round(v, 3) for k, v in delta.items()},
            "verdict": (
                "✅ governance improves outcomes"
                if delta.get("fulfillment_rate", 0) > 0
                else "⚠ no improvement detected"
            ),
        }


def run_integration_trial(
    config: LiveWorkloadConfig,
    connector_class=None,
) -> WorkloadResult:
    """
    快速入口：用给定配置运行一次完整治理评估。
    默认使用 SimulatedWorkloadConnector。

    Args:
        config:          工作负载配置
        connector_class: 连接器类（默认 SimulatedWorkloadConnector）

    Returns:
        WorkloadResult
    """
    from ystar.integrations.simulation import SimulatedWorkloadConnector
    if connector_class is None:
        connector_class = SimulatedWorkloadConnector
    connector = connector_class(config)
    return WorkloadRunner.run(connector, governance_on=config.governance_on)

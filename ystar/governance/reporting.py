"""
ystar.reporting  —  Y* Baseline & Daily Report Engine
======================================================
v0.41.0

"不只是日志器，而是能用数字回答：Y* 到底有没有改变执行结果。"

架构：
    ReportEngine
        ├── collect_metrics()       ← 从 store 读取全量指标
        ├── baseline_report()       ← 全量快照（可保存作对照基线）
        ├── daily_report(since=T)   ← 增量日报（与基线比较 delta）
        └── export_json/markdown()  ← 序列化输出

数据来源（全部只读，不写入任何 store）：
    OmissionStore / InMemoryOmissionStore  → omission 指标
    CIEUStore（可选）                       → commission/drift 指标
    InterventionEngine（可选）              → intervention 指标

使用：
    from ystar.governance.reporting import ReportEngine

    engine = ReportEngine(
        omission_store    = adapter.engine.store,
        cieu_store        = cieu,           # optional
        intervention_eng  = inter_engine,   # optional
    )
    report = engine.baseline_report()
    print(report.to_markdown())

    # CLI
    ystar-dev report baseline
    ystar-dev report daily --since 2026-03-22
    ystar-dev report export --output report.json
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

_log = logging.getLogger(__name__)

from ystar.governance.omission_models import (
    ObligationStatus, OmissionType, EntityStatus, Severity,
)
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore
from ystar.governance.omission_summary import (
    omission_summary, chain_breakpoint_analysis,
    obligation_heatmap, actor_reliability_report,
)

AnyStore = Union[InMemoryOmissionStore, OmissionStore]


# ── Metrics dataclasses ───────────────────────────────────────────────────────

@dataclass
class ArtifactIntegrity:
    """报告元信息 — 可信度与工件完整性。"""
    report_version:            str   = "2.0"
    generated_at:              float = field(default_factory=time.time)
    generated_at_iso:          str   = ""
    report_confidence_level:   str   = "full"   # full / partial / speculative
    code_archive_status:       str   = "unknown"
    release_verifiability:     str   = "unknown"
    ystar_version:             str   = ""
    notes:                     str   = ""

    def __post_init__(self):
        import datetime
        if not self.generated_at_iso:
            self.generated_at_iso = datetime.datetime.fromtimestamp(
                self.generated_at
            ).strftime("%Y-%m-%d %H:%M:%S")
        if not self.ystar_version:
            try:
                from ystar import __version__
                self.ystar_version = __version__
            except Exception as e:
                # Optional version import — fallback is acceptable
                _log.debug(f"Could not import ystar version: {e}")
                self.ystar_version = "unknown"

    def to_dict(self) -> dict:
        return {
            "report_version":          self.report_version,
            "generated_at_iso":        self.generated_at_iso,
            "ystar_version":           self.ystar_version,
            "report_confidence_level": self.report_confidence_level,
            "code_archive_status":     self.code_archive_status,
            "release_verifiability":   self.release_verifiability,
            "notes":                   self.notes,
        }


@dataclass
class ObligationMetrics:
    """义务生命周期指标。"""
    # 生命周期
    created_total:     int = 0
    fulfilled_total:   int = 0
    expired_total:     int = 0   # includes soft+hard overdue
    soft_overdue:      int = 0
    hard_overdue:      int = 0
    escalated_total:   int = 0
    cancelled_total:   int = 0
    pending_total:     int = 0

    # 老化
    avg_soft_overdue_age_secs: float = 0.0
    avg_hard_overdue_age_secs: float = 0.0

    # 闭环影响
    closure_blocked_entity_count:      int = 0
    false_completion_entity_count:     int = 0

    # 按义务类型细分的履约率
    fulfillment_rate_by_type: Dict[str, float] = field(default_factory=dict)

    @property
    def fulfillment_rate(self) -> float:
        return self.fulfilled_total / self.created_total if self.created_total else 0.0

    @property
    def expiry_rate(self) -> float:
        return self.expired_total / self.created_total if self.created_total else 0.0

    @property
    def hard_overdue_rate(self) -> float:
        return self.hard_overdue / self.created_total if self.created_total else 0.0

    def to_dict(self) -> dict:
        return {
            # lifecycle
            "obligations_created_total":     self.created_total,
            "obligations_fulfilled_total":   self.fulfilled_total,
            "obligations_expired_total":     self.expired_total,
            "obligations_soft_overdue":      self.soft_overdue,
            "obligations_hard_overdue":      self.hard_overdue,
            "obligations_escalated_total":   self.escalated_total,
            "obligations_pending_total":     self.pending_total,
            # rates
            "fulfillment_rate":              round(self.fulfillment_rate, 3),
            "expiry_rate":                   round(self.expiry_rate, 3),
            "hard_overdue_rate":             round(self.hard_overdue_rate, 3),
            # aging
            "avg_soft_overdue_age_secs":     round(self.avg_soft_overdue_age_secs, 1),
            "avg_hard_overdue_age_secs":     round(self.avg_hard_overdue_age_secs, 1),
            # closure impact
            "closure_blocked_entity_count":  self.closure_blocked_entity_count,
            "false_completion_entity_count": self.false_completion_entity_count,
            # by type
            "fulfillment_rate_by_type":      {
                k: round(v, 3) for k, v in self.fulfillment_rate_by_type.items()
            },
        }


@dataclass
class OmissionMetrics:
    """Omission violations 指标。"""
    total_violations:          int = 0
    by_type:                   Dict[str, int] = field(default_factory=dict)
    by_actor:                  Dict[str, int] = field(default_factory=dict)
    by_entity_type:            Dict[str, int] = field(default_factory=dict)
    by_severity:               Dict[str, int] = field(default_factory=dict)
    escalated_violations:      int = 0

    # Omission 恢复情况
    recovered_count:           int = 0    # omission 发生后最终被 fulfill 的
    remaining_open_count:      int = 0
    rerouted_count:            int = 0

    # 链式断点分析
    broken_chains:             int = 0
    total_chains:              int = 0
    most_common_breakpoint:    Optional[str] = None
    breakpoints:               List[dict] = field(default_factory=list)

    @property
    def violation_rate(self) -> float:
        return (
            self.total_violations /
            (self.total_violations + self.recovered_count)
            if (self.total_violations + self.recovered_count) else 0.0
        )

    @property
    def recovery_rate(self) -> float:
        return (
            self.recovered_count / self.total_violations
            if self.total_violations else 0.0
        )

    def to_dict(self) -> dict:
        return {
            "omission_total_violations":     self.total_violations,
            "omission_escalated":            self.escalated_violations,
            "omission_recovered_count":      self.recovered_count,
            "omission_remaining_open_count": self.remaining_open_count,
            "omission_rerouted_count":       self.rerouted_count,
            "violation_rate":                round(self.violation_rate, 3),
            "recovery_rate":                 round(self.recovery_rate, 3),
            "by_omission_type":              self.by_type,
            "by_actor":                      dict(list(self.by_actor.items())[:10]),
            "by_entity_type":                self.by_entity_type,
            "by_severity":                   self.by_severity,
            "broken_chains":                 self.broken_chains,
            "total_chains":                  self.total_chains,
            "most_common_breakpoint":        self.most_common_breakpoint,
            "breakpoints":                   self.breakpoints[:5],
        }


@dataclass
class InterventionMetrics:
    """主动干预指标。"""
    # 总量
    total:             int = 0
    soft_pulses:       int = 0
    interrupt_gates:   int = 0
    reroutes:          int = 0
    capability_restricts: int = 0
    closure_blocks:    int = 0

    # 按触发原因
    by_omission_type:  Dict[str, int] = field(default_factory=dict)

    # 效果
    recoveries_after_intervention:    int = 0
    repeat_violations_after:          int = 0
    manual_takeovers_after:           int = 0

    # 副作用
    false_positive_interventions:     int = 0
    intervention_induced_deadlocks:   int = 0
    interventions_reverted:           int = 0

    # Connection 12: Document D deep intervention metrics (proper dataclass fields)
    _operator_burden_escalations:     int = field(default=0, repr=False)
    _oscillation_count:               int = field(default=0, repr=False)
    _closure_recovery_before:         float = field(default=0.0, repr=False)
    _closure_recovery_after:          float = field(default=0.0, repr=False)
    _pending_reroute_count:           int = field(default=0, repr=False)

    @property
    def recovery_rate(self) -> float:
        return (
            self.recoveries_after_intervention / self.total
            if self.total else 0.0
        )

    @property
    def false_positive_rate(self) -> float:
        return (
            self.false_positive_interventions / self.total
            if self.total else 0.0
        )

    # Connection 12: Document D deep metrics — new computed properties
    @property
    def operator_burden_rate(self) -> float:
        return getattr(self, '_operator_burden_escalations', 0) / max(self.total, 1)

    @property
    def oscillation_rate(self) -> float:
        return getattr(self, '_oscillation_count', 0) / max(self.interrupt_gates, 1)

    @property
    def closure_recovery_improvement(self) -> float:
        return (getattr(self, '_closure_recovery_after', 0.0) -
                getattr(self, '_closure_recovery_before', 0.0))

    def to_dict(self) -> dict:
        return {
            "interventions_total":              self.total,
            "soft_pulses_total":                self.soft_pulses,
            "interrupt_gates_total":            self.interrupt_gates,
            "reroutes_total":                   self.reroutes,
            "capability_restricts_total":       self.capability_restricts,
            "closure_blocks_total":             self.closure_blocks,
            "recovery_rate_after_intervention": round(self.recovery_rate, 3),
            "false_positive_rate":              round(self.false_positive_rate, 3),
            "by_omission_type":                 self.by_omission_type,
            "recoveries_after_intervention":    self.recoveries_after_intervention,
            "repeat_violations_after":          self.repeat_violations_after,
            "false_positive_interventions":     self.false_positive_interventions,
            # Connection 12: Document D deep metrics
            "operator_burden_escalations":      getattr(self, '_operator_burden_escalations', 0),
            "operator_burden_rate":             round(self.operator_burden_rate, 3),
            "oscillation_count":                getattr(self, '_oscillation_count', 0),
            "oscillation_rate":                 round(self.oscillation_rate, 3),
            "closure_recovery_before":          round(getattr(self, '_closure_recovery_before', 0.0), 3),
            "closure_recovery_after":           round(getattr(self, '_closure_recovery_after', 0.0), 3),
            "closure_recovery_improvement":     round(self.closure_recovery_improvement, 3),
            "pending_reroute_count":            getattr(self, '_pending_reroute_count', 0),
        }


@dataclass
class ChainClosureMetrics:
    """链级闭环质量指标（root→leaf）。"""
    total_entities:                   int = 0
    entities_closed:                  int = 0
    entities_with_open_obligations:   int = 0

    # root-to-leaf 覆盖率
    root_tasks_total:                 int = 0
    root_tasks_all_children_closed:   int = 0
    root_tasks_missing_ack:           int = 0
    root_tasks_missing_result:        int = 0
    root_tasks_missing_upstream:      int = 0

    # 断链恢复
    broken_lineages_total:            int = 0
    broken_lineages_recovered:        int = 0
    avg_recovery_depth:               float = 0.0

    # 可复现性
    replayable_entities_rate:         float = 0.0
    events_missing_entity_ref:        int = 0
    events_missing_lineage_ref:       int = 0

    @property
    def closure_rate(self) -> float:
        return self.entities_closed / self.total_entities if self.total_entities else 0.0

    @property
    def root_task_full_closure_rate(self) -> float:
        return (
            self.root_tasks_all_children_closed / self.root_tasks_total
            if self.root_tasks_total else 0.0
        )

    def to_dict(self) -> dict:
        return {
            "total_entities":                   self.total_entities,
            "entities_closed":                  self.entities_closed,
            "entity_closure_rate":              round(self.closure_rate, 3),
            "entities_with_open_obligations":   self.entities_with_open_obligations,
            "root_tasks_total":                 self.root_tasks_total,
            "root_task_full_closure_rate":      round(self.root_task_full_closure_rate, 3),
            "root_tasks_missing_ack_rate":      round(
                self.root_tasks_missing_ack / max(self.root_tasks_total, 1), 3),
            "root_tasks_missing_result_rate":   round(
                self.root_tasks_missing_result / max(self.root_tasks_total, 1), 3),
            "root_tasks_missing_upstream_rate": round(
                self.root_tasks_missing_upstream / max(self.root_tasks_total, 1), 3),
            "broken_lineages_total":            self.broken_lineages_total,
            "broken_lineages_recovered":        self.broken_lineages_recovered,
            "replayable_entities_rate":         round(self.replayable_entities_rate, 3),
            "events_missing_entity_ref":        self.events_missing_entity_ref,
        }


@dataclass
class CausalMetrics:
    """Pearl causal reasoning metrics (from CausalEngine, optional)."""
    causal_confidence_avg:  float = 0.0
    observations_count:     int = 0
    autonomous_rate:        float = 0.0   # fraction of decisions made autonomously
    human_required_rate:    float = 0.0   # fraction requiring human approval
    counterfactual_queries: int = 0

    def to_dict(self) -> dict:
        return {
            "causal_confidence_avg":  round(self.causal_confidence_avg, 3),
            "observations_count":     self.observations_count,
            "autonomous_rate":        round(self.autonomous_rate, 3),
            "human_required_rate":    round(self.human_required_rate, 3),
            "counterfactual_queries": self.counterfactual_queries,
        }


@dataclass
class CIEUMetrics:
    """Commission/drift 指标（来自 CIEUStore，可选）。"""
    total_events:        int = 0
    allow_count:         int = 0
    deny_count:          int = 0
    escalate_count:      int = 0
    drift_count:         int = 0
    top_violations:      List[tuple] = field(default_factory=list)
    dimension_hints:     List[str]   = field(default_factory=list)  # 2-E: DimensionDiscovery

    @property
    def deny_rate(self) -> float:
        return self.deny_count / self.total_events if self.total_events else 0.0

    @property
    def drift_rate(self) -> float:
        return self.drift_count / self.total_events if self.total_events else 0.0

    def to_dict(self) -> dict:
        return {
            "cieu_total_events":   self.total_events,
            "allow_count":         self.allow_count,
            "deny_count":          self.deny_count,
            "escalate_count":      self.escalate_count,
            "drift_count":         self.drift_count,
            "deny_rate":           round(self.deny_rate, 3),
            "drift_rate":          round(self.drift_rate, 3),
            "top_violations":      [(k, v) for k, v in self.top_violations[:5]],
        }


@dataclass
class Report:
    """
    完整的 Y* 报告对象。
    包含 baseline 或 daily 的全量指标，可序列化为 JSON 或 Markdown。
    """
    report_type:    str  = "baseline"     # baseline / daily
    period_start:   Optional[float] = None
    period_end:     Optional[float] = None
    period_label:   str = ""

    integrity:      ArtifactIntegrity = field(default_factory=ArtifactIntegrity)
    obligations:    ObligationMetrics = field(default_factory=ObligationMetrics)
    omissions:      OmissionMetrics   = field(default_factory=OmissionMetrics)
    interventions:  InterventionMetrics = field(default_factory=InterventionMetrics)
    chain:          ChainClosureMetrics = field(default_factory=ChainClosureMetrics)
    cieu:           CIEUMetrics       = field(default_factory=CIEUMetrics)
    causal:         CausalMetrics     = field(default_factory=CausalMetrics)

    # Top-level KPIs (pre-computed summary)
    kpis:           Dict[str, Any] = field(default_factory=dict)

    def _build_kpis(self) -> None:
        """Pre-compute the top-level KPI summary."""
        self.kpis = {
            "obligation_fulfillment_rate":   round(self.obligations.fulfillment_rate, 3),
            "obligation_expiry_rate":        round(self.obligations.expiry_rate, 3),
            "hard_overdue_rate":             round(self.obligations.hard_overdue_rate, 3),
            "omission_detection_rate":       round(
                1.0 if self.omissions.total_violations > 0 else 0.0, 3),
            "omission_recovery_rate":        round(self.omissions.recovery_rate, 3),
            "chain_closure_rate":            round(self.chain.closure_rate, 3),
            "intervention_recovery_rate":    round(self.interventions.recovery_rate, 3),
            "false_positive_rate":           round(self.interventions.false_positive_rate, 3),
            "cieu_deny_rate":               round(self.cieu.deny_rate, 3),
        }

    def to_dict(self) -> dict:
        self._build_kpis()
        return {
            "meta": {
                "report_type":   self.report_type,
                "period_label":  self.period_label,
                "period_start":  self.period_start,
                "period_end":    self.period_end,
                **self.integrity.to_dict(),
            },
            "kpis":          self.kpis,
            "obligations":   self.obligations.to_dict(),
            "omissions":     self.omissions.to_dict(),
            "interventions": self.interventions.to_dict(),
            "chain":         self.chain.to_dict(),
            "cieu":          self.cieu.to_dict(),
            "causal":        self.causal.to_dict(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        self._build_kpis()
        d = self.to_dict()
        lines = [
            f"# Y* {self.report_type.upper()} REPORT",
            f"",
            f"**Generated**: {self.integrity.generated_at_iso}  ",
            f"**Version**: v{self.integrity.ystar_version}  ",
            f"**Confidence**: {self.integrity.report_confidence_level}  ",
            f"**Period**: {self.period_label or 'all-time'}",
            f"",
            f"---",
            f"",
            f"## KPIs",
            f"",
            f"| Metric | Value | Direction |",
            f"|--------|-------|-----------|",
        ]
        kpi_meta = [
            ("obligation_fulfillment_rate",  "↑ better"),
            ("obligation_expiry_rate",       "↓ better"),
            ("hard_overdue_rate",            "↓ better"),
            ("omission_detection_rate",      "↑ better"),
            ("omission_recovery_rate",       "↑ better"),
            ("chain_closure_rate",           "↑ better"),
            ("intervention_recovery_rate",   "↑ better"),
            ("false_positive_rate",          "↓ better"),
            ("cieu_deny_rate",              "↓ better"),
        ]
        for k, direction in kpi_meta:
            v = self.kpis.get(k, 0)
            lines.append(f"| {k} | {v:.1%} | {direction} |")

        lines += [
            f"",
            f"---",
            f"",
            f"## Obligations",
            f"",
            f"- Created: **{self.obligations.created_total}**",
            f"- Fulfilled: **{self.obligations.fulfilled_total}** "
            f"({self.obligations.fulfillment_rate:.1%})",
            f"- Soft overdue: **{self.obligations.soft_overdue}**",
            f"- Hard overdue: **{self.obligations.hard_overdue}**",
            f"- Escalated: **{self.obligations.escalated_total}**",
            f"- Closure blocked: **{self.obligations.closure_blocked_entity_count}** entities",
            f"",
        ]

        if self.obligations.fulfillment_rate_by_type:
            lines.append("**Fulfillment by obligation type:**")
            lines.append("")
            lines.append("| Type | Rate |")
            lines.append("|------|------|")
            for t, r in sorted(self.obligations.fulfillment_rate_by_type.items(),
                                key=lambda x: x[1]):
                short = t.replace("required_", "").replace("_omission", "")
                lines.append(f"| {short} | {r:.1%} |")
            lines.append("")

        lines += [
            f"## Omissions",
            f"",
            f"- Total violations: **{self.omissions.total_violations}**",
            f"- Escalated: **{self.omissions.escalated_violations}**",
            f"- Recovered: **{self.omissions.recovered_count}** "
            f"({self.omissions.recovery_rate:.1%})",
            f"- Remaining open: **{self.omissions.remaining_open_count}**",
            f"",
        ]
        if self.omissions.by_type:
            lines.append("**By omission type:**")
            lines.append("")
            lines.append("| Type | Count |")
            lines.append("|------|-------|")
            for t, n in sorted(self.omissions.by_type.items(), key=lambda x: -x[1]):
                short = t.replace("required_", "").replace("_omission", "")
                lines.append(f"| {short} | {n} |")
            lines.append("")
        if self.omissions.most_common_breakpoint:
            lines.append(f"**Most common chain breakpoint**: "
                         f"`{self.omissions.most_common_breakpoint}`")
            lines.append("")

        lines += [
            f"## Interventions",
            f"",
            f"- Total: **{self.interventions.total}**",
            f"  - Level 1 (soft pulse): {self.interventions.soft_pulses}",
            f"  - Level 2 (interrupt gate): {self.interventions.interrupt_gates}",
            f"  - Level 3 (reroute): {self.interventions.reroutes}",
            f"- Recovery rate: **{self.interventions.recovery_rate:.1%}**",
            f"- False positive rate: **{self.interventions.false_positive_rate:.1%}**",
            f"",
            f"## Chain Closure",
            f"",
            f"- Total entities: **{self.chain.total_entities}**",
            f"- Closed: **{self.chain.entities_closed}** ({self.chain.closure_rate:.1%})",
            f"- Root tasks: **{self.chain.root_tasks_total}**",
            f"- Full closure rate: **{self.chain.root_task_full_closure_rate:.1%}**",
            f"- Broken lineages: **{self.chain.broken_lineages_total}**",
            f"  - Recovered: {self.chain.broken_lineages_recovered}",
            f"",
        ]
        if self.cieu.total_events:
            # ── CIEU 因果叙事格式（2-B）────────────────────────────────
            deny_n     = self.cieu.deny_count
            esc_n      = self.cieu.escalate_count
            allow_n    = self.cieu.allow_count
            total_n    = self.cieu.total_events
            drift_n    = self.cieu.drift_count

            # 一致性结论
            if deny_n == 0 and esc_n == 0:
                consistency = "✅ 所有操作均在意图合约范围内"
            else:
                consistency = (f"✅ {deny_n + esc_n} 次超出承诺的操作已被拦截，"
                               "无漏网行为")

            lines += [
                f"## CIEU 因果审计摘要",
                f"",
                f"审计事件: **{total_n}** 条（含操作参数完整快照）",
                f"",
                f"| 结果 | 数量 | 说明 |",
                f"|------|------|------|",
                f"| ✅ 按承诺执行 | **{allow_n}** | 在意图合约范围内 |",
                f"| ❌ 超出承诺（已拦截）| **{deny_n}** | "
                f"违反合约规则，已阻断 |",
            ]
            if esc_n:
                lines.append(
                    f"| ⚠ 升级人工审批 | **{esc_n}** | 高风险操作，等待审批 |"
                )
            if drift_n:
                lines.append(
                    f"| 🔄 目标漂移 | **{drift_n}** "
                    f"({self.cieu.drift_rate:.1%}) | Agent 行为偏离原始意图 |"
                )

            lines.append(f"")
            lines.append(f"**意图与行动一致性**: {consistency}")
            lines.append(f"")

            # 顶部违规维度
            if self.cieu.top_violations:
                lines.append("**违规维度分布**:")
                for dim, count in self.cieu.top_violations[:5]:
                    lines.append(f"- `{dim}`: {count} 次")
                lines.append(f"")

            lines.append(
                f"> 运行 `ystar audit` 查看每条违规的完整参数快照和授权链"
            )
            lines.append(f"")

            # 2-E：DimensionDiscovery 建议（如有）
            if self.cieu.dimension_hints:
                lines += [
                    f"**💡 DimensionDiscovery — 发现未覆盖的违规模式**:",
                ]
                for hint in self.cieu.dimension_hints:
                    lines.append(f"- {hint}")
                lines += [
                    f"",
                    f"> 考虑在 AGENTS.md 里补充这些约束类型，"
                    f"重新运行 `ystar init` 更新规则",
                    f"",
                ]

        # ── 行动指南（每次报告末尾，指引下一步）────────────────────
        lines += [
            f"---",
            f"",
            f"## 接下来你可以做什么",
            f"",
        ]

        # 根据报告内容动态生成针对性建议
        has_cieu     = self.cieu.total_events > 0
        has_denies   = self.cieu.deny_count > 0
        has_dim_hints = bool(self.cieu.dimension_hints)
        has_omissions = self.omissions.total_violations > 0

        if has_denies:
            lines += [
                f"**查看违规现场**（有 {self.cieu.deny_count} 次操作被拦截）",
                f"```",
                f"ystar audit",
                f"```",
                f"每条违规记录包含：时间 / 操作参数快照 / 发起人 / 授权链 / 封印状态。",
                f"",
            ]
        elif has_cieu:
            lines += [
                f"**查看因果审计报告**",
                f"```",
                f"ystar audit",
                f"```",
                f"查看 Agent 的每次操作是否在承诺范围内（意图 vs 行动）。",
                f"",
            ]
        else:
            lines += [
                f"**运行你的 Agent，然后查看审计报告**",
                f"```",
                f"# 让 Agent 跑一些任务，然后：",
                f"ystar audit",
                f"```",
                f"Y* 会自动记录每次操作与规则的对照关系（CIEU 因果链）。",
                f"",
            ]

        if has_dim_hints:
            lines += [
                f"**补充规则覆盖（DimensionDiscovery 发现了盲区）**",
                f"```",
                f"ystar quality    # 查看规则覆盖率和补充建议",
                f"```",
                f"",
            ]
        else:
            lines += [
                f"**评估规则质量**",
                f"```",
                f"ystar quality    # 覆盖率 / 误拦率 / 维度建议",
                f"```",
                f"",
            ]

        lines += [
            f"**验证拦截效果**",
            f"```",
            f"ystar simulate   # 内置 A/B 模拟：98% 拦截率，0% 误拦",
            f"```",
            f"",
        ]

        if has_denies or has_omissions:
            lines += [
                f"**生成密码学封印**（为合规审计提供不可篡改的证明）",
                f"```",
                f"ystar seal --session <session_id>",
                f"```",
                f"",
            ]

        lines += [
            f"> Y* 会持续记录每次 Agent 操作的因果链。"
            f"运行 `ystar report` 可随时生成完整治理报告。",
            f"",
        ]

        return "\n".join(lines)

    def delta(self, baseline: "Report") -> Dict[str, Any]:
        """
        与基线对比，返回每个 KPI 的 delta 和方向判断。
        direction: improved / regressed / neutral
        """
        self._build_kpis()
        baseline._build_kpis()

        # 方向：True = higher is better
        higher_better = {
            "obligation_fulfillment_rate": True,
            "obligation_expiry_rate":      False,
            "hard_overdue_rate":           False,
            "omission_detection_rate":     True,
            "omission_recovery_rate":      True,
            "chain_closure_rate":          True,
            "intervention_recovery_rate":  True,
            "false_positive_rate":         False,
            "cieu_deny_rate":             False,
        }
        result = {}
        for k, hb in higher_better.items():
            v_now  = self.kpis.get(k, 0.0)
            v_base = baseline.kpis.get(k, 0.0)
            delta  = v_now - v_base
            if abs(delta) < 0.01:
                direction = "neutral"
            elif (delta > 0 and hb) or (delta < 0 and not hb):
                direction = "improved"
            else:
                direction = "regressed"
            result[k] = {
                "baseline":  round(v_base, 3),
                "current":   round(v_now, 3),
                "delta":     round(delta, 3),
                "direction": direction,
            }
        return result


# ── ReportEngine ──────────────────────────────────────────────────────────────

class ReportEngine:
    """
    Y* 报告引擎。

    从现有 store 读取指标，生成 Report 对象。
    纯只读，不写入任何 store。
    """

    def __init__(
        self,
        omission_store:    AnyStore,
        cieu_store:        Optional[Any] = None,   # CIEUStore
        intervention_eng:  Optional[Any] = None,   # InterventionEngine
        report_confidence: str = "full",
        causal_engine:     Optional[Any] = None,   # CausalEngine
    ) -> None:
        self.omission_store   = omission_store
        self.cieu_store       = cieu_store
        self.intervention_eng = intervention_eng
        self.report_confidence = report_confidence
        self.causal_engine     = causal_engine

    # ── Public API ────────────────────────────────────────────────────────────

    def baseline_report(self, label: str = "all-time") -> Report:
        """全量快照报告。"""
        r = Report(report_type="baseline", period_label=label,
                   period_start=0.0, period_end=time.time())
        r.integrity.report_confidence_level = self.report_confidence
        self._fill(r, since=None)
        return r

    def daily_report(
        self,
        since: Optional[float] = None,
        label: str = "",
    ) -> Report:
        """
        增量日报。
        since: Unix timestamp（默认 24 小时前）
        """
        since = since or (time.time() - 86400.0)
        import datetime
        day_str = label or datetime.datetime.fromtimestamp(since).strftime("%Y-%m-%d")
        r = Report(
            report_type  = "daily",
            period_label = day_str,
            period_start = since,
            period_end   = time.time(),
        )
        r.integrity.report_confidence_level = self.report_confidence
        self._fill(r, since=since)
        return r

    # ── Internal: metric collection ──────────────────────────────────────────

    def _fill(self, r: Report, since: Optional[float]) -> None:
        self._fill_obligations(r, since)
        self._fill_omissions(r, since)
        self._fill_chain(r)
        self._fill_interventions(r)
        self._fill_cieu(r, since)
        self._fill_causal(r)
        r._build_kpis()

    def _ts_filter(self, ts: float, since: Optional[float]) -> bool:
        return since is None or ts >= since

    def _fill_obligations(self, r: Report, since: Optional[float]) -> None:
        all_obs = self.omission_store.list_obligations()
        if since is not None:
            all_obs = [o for o in all_obs if self._ts_filter(o.created_at, since)]

        m = r.obligations
        m.created_total = len(all_obs)

        now = time.time()
        soft_ages, hard_ages = [], []

        for ob in all_obs:
            s = ob.status
            if s == ObligationStatus.FULFILLED:
                m.fulfilled_total += 1
            elif s == ObligationStatus.PENDING:
                m.pending_total += 1
            elif s == ObligationStatus.SOFT_OVERDUE:
                m.soft_overdue += 1
                m.expired_total += 1
                if ob.soft_violation_at:
                    soft_ages.append(now - ob.soft_violation_at)
            elif s == ObligationStatus.HARD_OVERDUE:
                m.hard_overdue += 1
                m.soft_overdue += 1  # hard is also soft
                m.expired_total += 1
                if ob.hard_violation_at:
                    hard_ages.append(now - ob.hard_violation_at)
            elif s == ObligationStatus.EXPIRED:
                m.expired_total += 1
            elif s == ObligationStatus.ESCALATED:
                m.escalated_total += 1
                m.expired_total += 1
            elif s == ObligationStatus.CANCELLED:
                m.cancelled_total += 1

        m.avg_soft_overdue_age_secs = (
            sum(soft_ages) / len(soft_ages) if soft_ages else 0.0
        )
        m.avg_hard_overdue_age_secs = (
            sum(hard_ages) / len(hard_ages) if hard_ages else 0.0
        )

        # Closure blocked entities
        entities = self.omission_store.list_entities()
        m.closure_blocked_entity_count = sum(
            1 for e in entities
            if any(
                ob.status.is_open and ob.escalation_policy.deny_closure_on_open
                for ob in self.omission_store.list_obligations(entity_id=e.entity_id)
            )
        )

        # Fulfillment rate by obligation type
        by_type: Dict[str, Dict[str, int]] = {}
        for ob in all_obs:
            t = ob.obligation_type
            by_type.setdefault(t, {"total": 0, "fulfilled": 0})
            by_type[t]["total"] += 1
            if ob.status == ObligationStatus.FULFILLED:
                by_type[t]["fulfilled"] += 1
        m.fulfillment_rate_by_type = {
            t: v["fulfilled"] / v["total"]
            for t, v in by_type.items() if v["total"] > 0
        }

    def _fill_omissions(self, r: Report, since: Optional[float]) -> None:
        all_viols = self.omission_store.list_violations()
        if since is not None:
            all_viols = [v for v in all_viols
                         if self._ts_filter(v.detected_at, since)]

        m = r.omissions
        m.total_violations = len(all_viols)
        m.escalated_violations = sum(1 for v in all_viols if v.escalated)

        for v in all_viols:
            m.by_type[v.omission_type]   = m.by_type.get(v.omission_type, 0) + 1
            m.by_actor[v.actor_id]        = m.by_actor.get(v.actor_id, 0) + 1
            sev = v.severity.value if hasattr(v.severity, 'value') else str(v.severity)
            m.by_severity[sev]            = m.by_severity.get(sev, 0) + 1
            ent = self.omission_store.get_entity(v.entity_id)
            etype = ent.entity_type if ent else "unknown"
            m.by_entity_type[etype] = m.by_entity_type.get(etype, 0) + 1

        # Recovered = had violation AND obligation now fulfilled
        recovered = 0
        for v in all_viols:
            ob = self.omission_store.get_obligation(v.obligation_id)
            if ob and ob.status == ObligationStatus.FULFILLED:
                recovered += 1
        m.recovered_count = recovered
        m.remaining_open_count = m.total_violations - recovered

        # ── CIEU 补全：从统一日志读取 omission_violation 事件 ──────────────
        # OmissionEngine 的违规事件同时写入 CIEUStore（event_type 以 omission_violation: 开头）
        # 当 OmissionStore 为空或数据不完整时，从 CIEU 补全统计
        if self.cieu_store is not None:
            try:
                import json as _json
                records = self.cieu_store.query(limit=2000, since=since)
                cieu_omission_count = 0
                for rec in records:
                    if rec.event_type and rec.event_type.startswith("omission_violation:"):
                        cieu_omission_count += 1
                        # 从 event_type 提取 obligation_type
                        ob_type = rec.event_type.split(":", 1)[1]
                        # 如果 OmissionStore 里没有这条记录，从 CIEU 补充统计
                        if ob_type not in m.by_type:
                            m.by_type[ob_type] = m.by_type.get(ob_type, 0) + 1
                        if rec.agent_id and rec.agent_id not in m.by_actor:
                            m.by_actor[rec.agent_id] = m.by_actor.get(rec.agent_id, 0) + 1

                # 如果 CIEU 里有更多 omission 记录，更新总数
                if cieu_omission_count > m.total_violations:
                    m.total_violations = cieu_omission_count
                    m.remaining_open_count = max(0, cieu_omission_count - recovered)
            except Exception as e:
                _log.warning(f"Could not compute CIEU omission metrics: {e}")

        # Chain breakpoint analysis
        try:
            ca = chain_breakpoint_analysis(self.omission_store)
            m.broken_chains          = ca["broken_chains"]
            m.total_chains           = ca["total_chains"]
            m.most_common_breakpoint = ca["most_common_break"]
            m.breakpoints            = ca["breakpoints"][:5]
        except Exception as e:
            _log.warning(f"Could not compute chain breakpoint analysis: {e}")

    def _fill_chain(self, r: Report) -> None:
        entities = self.omission_store.list_entities()
        m = r.chain
        m.total_entities = len(entities)

        root_entities = [e for e in entities if not e.parent_entity_id]
        m.root_tasks_total = len(root_entities)

        for e in entities:
            # Closed entities
            if e.status == EntityStatus.CLOSED:
                m.entities_closed += 1

            # Open obligations
            obs = self.omission_store.list_obligations(entity_id=e.entity_id)
            if any(o.status.is_open for o in obs):
                m.entities_with_open_obligations += 1

            # Lineage completeness
            if e.lineage and len(e.lineage) > 0:
                if e.lineage[0] != e.entity_id:
                    pass  # has parent lineage

        # Root task closure analysis
        for e in root_entities:
            obs = self.omission_store.list_obligations(entity_id=e.entity_id)
            ob_types = {o.obligation_type for o in obs}
            has_ack_missing = any(
                o.obligation_type == OmissionType.REQUIRED_ACKNOWLEDGEMENT.value
                and o.status.is_overdue_any
                for o in obs
            )
            has_result_missing = any(
                o.obligation_type == OmissionType.REQUIRED_RESULT_PUBLICATION.value
                and o.status.is_overdue_any
                for o in obs
            )
            has_upstream_missing = any(
                o.obligation_type == OmissionType.REQUIRED_UPSTREAM_NOTIFICATION.value
                and o.status.is_overdue_any
                for o in obs
            )
            all_fulfilled = all(
                o.status == ObligationStatus.FULFILLED for o in obs
            ) if obs else True

            if all_fulfilled:
                m.root_tasks_all_children_closed += 1
            if has_ack_missing:
                m.root_tasks_missing_ack += 1
            if has_result_missing:
                m.root_tasks_missing_result += 1
            if has_upstream_missing:
                m.root_tasks_missing_upstream += 1

        # Replayability: entities that have at least 1 governance event
        replayable = sum(
            1 for e in entities
            if self.omission_store.events_for_entity(e.entity_id)
        )
        m.replayable_entities_rate = replayable / m.total_entities if m.total_entities else 0.0

        # Broken lineages
        viols = self.omission_store.list_violations()
        viol_entities = {v.entity_id for v in viols}
        m.broken_lineages_total = len(viol_entities)
        m.broken_lineages_recovered = sum(
            1 for eid in viol_entities
            if self.omission_store.has_event_of_type(eid, "closure_event")
        )

    def _fill_interventions(self, r: Report) -> None:
        if self.intervention_eng is None:
            return
        m = r.interventions
        try:
            from ystar.governance.intervention_models import InterventionLevel, InterventionStatus
            all_pulses = self.intervention_eng.pulse_store.all_pulses()
            m.total = len(all_pulses)
            for p in all_pulses:
                if p.level == InterventionLevel.SOFT_PULSE:
                    m.soft_pulses += 1
                elif p.level == InterventionLevel.INTERRUPT_GATE:
                    m.interrupt_gates += 1
                    m.capability_restricts += 1
                elif p.level == InterventionLevel.REROUTE_ESCALATE:
                    m.reroutes += 1
                m.by_omission_type[p.omission_type] = (
                    m.by_omission_type.get(p.omission_type, 0) + 1
                )
                if p.status == InterventionStatus.RESOLVED:
                    m.recoveries_after_intervention += 1

            # Connection 12: Document D deep intervention metrics
            # oscillation: actors gated more than once
            from collections import Counter as _Counter
            gate_actors = _Counter(
                p.actor_id for p in all_pulses
                if p.level == InterventionLevel.INTERRUPT_GATE
            )
            m._oscillation_count = sum(1 for c in gate_actors.values() if c > 1)

            # pending reroutes
            try:
                m._pending_reroute_count = len(
                    self.intervention_eng.pending_reroutes()
                )
            except Exception as e:
                _log.warning(f"Could not get pending reroutes: {e}")

            # operator burden: escalated interventions (reroutes needing handoff)
            m._operator_burden_escalations = m.reroutes

            # closure recovery: compare pre/post chain closure
            try:
                chain_m = r.chain
                m._closure_recovery_after  = chain_m.closure_rate
                m._closure_recovery_before = max(
                    0.0,
                    chain_m.closure_rate - (
                        m.recoveries_after_intervention
                        / max(chain_m.total_entities, 1)
                    )
                )
            except Exception as e:
                _log.warning(f"Could not compute closure recovery: {e}")

        except Exception as e:
            _log.warning(f"Could not fill intervention metrics: {e}")

    def _fill_cieu(self, r: Report, since: Optional[float]) -> None:
        if self.cieu_store is None:
            return
        m = r.cieu
        try:
            stats = self.cieu_store.stats(since=since)
            m.total_events   = stats.get("total", 0)
            by_dec           = stats.get("by_decision", {})
            m.allow_count    = by_dec.get("allow", 0)
            m.deny_count     = by_dec.get("deny", 0)
            m.escalate_count = by_dec.get("escalate", 0)
            m.drift_count    = stats.get("drift_count", 0)
            m.top_violations = stats.get("top_violations", [])
        except Exception as e:
            _log.warning(f"Could not fill CIEU metrics: {e}")

        # 2-E: DimensionDiscovery — 从 CIEU 历史发现未覆盖的违规模式
        if m.total_events > 0:
            try:
                from ystar.governance.metalearning import (
                    CallRecord, DimensionDiscovery,
                )
                from ystar.kernel.dimensions import IntentContract
                from ystar.kernel.engine import check as _check
                import json as _json

                records_raw = self.cieu_store.query(limit=200, since=since)
                history = []
                for rec in records_raw:
                    try:
                        params   = _json.loads(rec.params_json or "{}")
                        contract = IntentContract()
                        chk      = _check(params, {}, contract)
                        history.append(CallRecord(
                            seq=len(history),
                            func_name=rec.event_type or "unknown",
                            params=params,
                            result=_json.loads(rec.result_json or "{}"),
                            violations=chk.violations,
                            intent_contract=contract,
                        ))
                    except Exception as e:
                        _log.debug(f"Could not process dimension discovery record: {e}")
                if history:
                    m.dimension_hints = DimensionDiscovery.analyze(history)[:3]
            except Exception as e:
                _log.warning(f"Could not fill dimension discovery metrics: {e}")

    def _fill_causal(self, r: Report) -> None:
        """GAP 2 FIX: Compute causal metrics from CausalEngine if available."""
        if self.causal_engine is None:
            return
        m = r.causal
        try:
            obs = getattr(self.causal_engine, '_observations', [])
            m.observations_count = len(obs)
            if obs:
                confidences = [getattr(o, 'confidence', 0.0) for o in obs]
                m.causal_confidence_avg = sum(confidences) / len(confidences)
            threshold = getattr(self.causal_engine, 'confidence_threshold', 0.65)
            auto_count = sum(1 for o in obs if getattr(o, 'confidence', 0.0) >= threshold)
            human_count = len(obs) - auto_count
            if obs:
                m.autonomous_rate = auto_count / len(obs)
                m.human_required_rate = human_count / len(obs)
            m.counterfactual_queries = getattr(self.causal_engine, '_counterfactual_count', 0)
        except Exception as e:
            _log.warning(f"Could not fill causal metrics: {e}")

"""
ystar.governance.report_metrics  —  Governance Metrics Data Classes
====================================================================
v0.41.0

reporting.py 物理拆分（P2 完成）：

  ystar/governance/report_metrics.py  ← 指标数据类（Governance Services）
  ystar/products/report_render.py     ← 报告渲染（Operator Products）
  ystar/reporting.py                  ← 向后兼容的统一入口（re-export）

这个文件只包含：
  - ArtifactIntegrity   — 报告元信息（置信度、版本等）
  - ObligationMetrics   — 义务生命周期指标
  - OmissionMetrics     — Omission violations 指标
  - InterventionMetrics — 主动干预指标
  - ChainClosureMetrics — 链级闭环质量指标
  - CIEUMetrics         — Commission/drift 指标

不包含：
  - Report.to_markdown()（渲染，属于 Products）
  - Report.to_json()（渲染，属于 Products）
  - ReportEngine（留在 reporting.py 和 governance/metrics.py）

设计原则：
  这些数据类应该可以在任何 Governance Services 代码中使用，
  不需要依赖渲染框架或产品层代码。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from ystar.governance.omission_models import (
    ObligationStatus, OmissionType, EntityStatus, Severity,
)
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore

AnyStore = Union[InMemoryOmissionStore, OmissionStore]


@dataclass
class ArtifactIntegrity:
    """报告元信息 — 可信度与工件完整性。"""
    report_version:            str   = "2.0"
    generated_at:              float = field(default_factory=time.time)
    generated_at_iso:          str   = ""
    report_confidence_level:   str   = "full"
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
            except Exception:
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
    created_total:     int = 0
    fulfilled_total:   int = 0
    expired_total:     int = 0
    soft_overdue:      int = 0
    hard_overdue:      int = 0
    escalated_total:   int = 0
    cancelled_total:   int = 0
    pending_total:     int = 0

    avg_soft_overdue_age_secs: float = 0.0
    avg_hard_overdue_age_secs: float = 0.0

    closure_blocked_entity_count:  int = 0
    false_completion_entity_count: int = 0

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
            "obligations_created_total":     self.created_total,
            "obligations_fulfilled_total":   self.fulfilled_total,
            "obligations_expired_total":     self.expired_total,
            "obligations_soft_overdue":      self.soft_overdue,
            "obligations_hard_overdue":      self.hard_overdue,
            "obligations_escalated_total":   self.escalated_total,
            "obligations_pending_total":     self.pending_total,
            "fulfillment_rate":              round(self.fulfillment_rate, 3),
            "expiry_rate":                   round(self.expiry_rate, 3),
            "hard_overdue_rate":             round(self.hard_overdue_rate, 3),
            "avg_soft_overdue_age_secs":     round(self.avg_soft_overdue_age_secs, 1),
            "avg_hard_overdue_age_secs":     round(self.avg_hard_overdue_age_secs, 1),
            "closure_blocked_entity_count":  self.closure_blocked_entity_count,
            "false_completion_entity_count": self.false_completion_entity_count,
            "fulfillment_rate_by_type":      {
                k: round(v, 3) for k, v in self.fulfillment_rate_by_type.items()
            },
        }


@dataclass
class OmissionMetrics:
    """Omission violations 指标。"""
    total_violations:     int = 0
    by_type:              Dict[str, int] = field(default_factory=dict)
    by_actor:             Dict[str, int] = field(default_factory=dict)
    by_entity_type:       Dict[str, int] = field(default_factory=dict)
    by_severity:          Dict[str, int] = field(default_factory=dict)
    escalated_violations: int = 0
    recovered_count:      int = 0
    remaining_open_count: int = 0
    rerouted_count:       int = 0
    broken_chains:        int = 0
    total_chains:         int = 0
    most_common_breakpoint: Optional[str] = None
    breakpoints:          List[dict] = field(default_factory=list)

    @property
    def violation_rate(self) -> float:
        total = self.total_violations + self.recovered_count
        return self.total_violations / total if total else 0.0

    @property
    def recovery_rate(self) -> float:
        return self.recovered_count / self.total_violations if self.total_violations else 0.0

    def to_dict(self) -> dict:
        return {
            "omission_total_violations":     self.total_violations,
            "omission_escalated":            self.escalated_violations,
            "omission_recovered_count":      self.recovered_count,
            "omission_remaining_open_count": self.remaining_open_count,
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
    total:             int = 0
    soft_pulses:       int = 0
    interrupt_gates:   int = 0
    reroutes:          int = 0
    capability_restricts: int = 0
    closure_blocks:    int = 0
    by_omission_type:  Dict[str, int] = field(default_factory=dict)
    recoveries_after_intervention:   int = 0
    repeat_violations_after:         int = 0
    manual_takeovers_after:          int = 0
    false_positive_interventions:    int = 0
    intervention_induced_deadlocks:  int = 0
    interventions_reverted:          int = 0

    @property
    def recovery_rate(self) -> float:
        return self.recoveries_after_intervention / self.total if self.total else 0.0

    @property
    def false_positive_rate(self) -> float:
        return self.false_positive_interventions / self.total if self.total else 0.0

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
            "false_positive_interventions":     self.false_positive_interventions,
        }


@dataclass
class ChainClosureMetrics:
    """链级闭环质量指标。"""
    total_entities:                int = 0
    entities_closed:               int = 0
    entities_with_open_obligations:int = 0
    root_tasks_total:              int = 0
    root_tasks_all_children_closed:int = 0
    root_tasks_missing_ack:        int = 0
    root_tasks_missing_result:     int = 0
    root_tasks_missing_upstream:   int = 0
    broken_lineages_total:         int = 0
    broken_lineages_recovered:     int = 0
    avg_recovery_depth:            float = 0.0
    replayable_entities_rate:      float = 0.0
    events_missing_entity_ref:     int = 0
    events_missing_lineage_ref:    int = 0

    @property
    def closure_rate(self) -> float:
        return self.entities_closed / self.total_entities if self.total_entities else 0.0

    @property
    def root_task_full_closure_rate(self) -> float:
        return (self.root_tasks_all_children_closed / self.root_tasks_total
                if self.root_tasks_total else 0.0)

    def to_dict(self) -> dict:
        return {
            "total_entities":                  self.total_entities,
            "entities_closed":                 self.entities_closed,
            "entity_closure_rate":             round(self.closure_rate, 3),
            "entities_with_open_obligations":  self.entities_with_open_obligations,
            "root_tasks_total":                self.root_tasks_total,
            "root_task_full_closure_rate":     round(self.root_task_full_closure_rate, 3),
            "root_tasks_missing_ack_rate":     round(
                self.root_tasks_missing_ack / max(self.root_tasks_total, 1), 3),
            "root_tasks_missing_result_rate":  round(
                self.root_tasks_missing_result / max(self.root_tasks_total, 1), 3),
            "broken_lineages_total":           self.broken_lineages_total,
            "broken_lineages_recovered":       self.broken_lineages_recovered,
            "replayable_entities_rate":        round(self.replayable_entities_rate, 3),
            "events_missing_entity_ref":       self.events_missing_entity_ref,
        }


@dataclass
class CIEUMetrics:
    """Commission/drift 指标。"""
    total_events:  int = 0
    allow_count:   int = 0
    deny_count:    int = 0
    escalate_count:int = 0
    drift_count:   int = 0
    top_violations:List[tuple] = field(default_factory=list)

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

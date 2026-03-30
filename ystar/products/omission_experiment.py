"""
ystar.omission_experiment  —  D1 A/B Experimental Comparison Framework
=======================================================================
v0.41.0

证明 "omission + intervention > omission only > baseline"
通过可重复、可量化的 A/B 实验，而不只是场景演示。

三个 treatment group：
  Group 0 — Baseline    : 无任何治理
  Group 1 — Omission    : omission detection only (no intervention)
  Group 2 — Full        : omission + active intervention (v0.33+)

八个核心指标：
  1. unclosed_task_rate      未闭环任务比例     ← 越低越好
  2. avg_silence_secs        平均沉默时长       ← 越低越好
  3. false_completion_rate   假完成率           ← 越低越好（检测能力指标）
  4. detection_rate          检测率             ← 越高越好（omission/intervention专属）
  5. escalation_rate         升级率             ← 越低越好
  6. recovery_rate           恢复闭环率         ← 越高越好
  7. gate_denial_rate        门控拒绝率         ← intervention 专属
  8. false_positive_rate     误伤率             ← 越低越好

使用方式：
    from ystar.products.omission_experiment import run_ab_experiment, print_ab_report

    results = run_ab_experiment(
        scenario="manager_no_dispatch",
        n_trials=50,
        random_seed=42,
    )
    print_ab_report(results)
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ystar.governance.omission_models import (
    ObligationStatus, EntityStatus,
    TrackedEntity, GovernanceEvent, GEventType,
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_rules import reset_registry
from ystar.adapters.omission_adapter import OmissionAdapter
from ystar.governance.intervention_engine import InterventionEngine
from ystar.governance.intervention_models import InterventionLevel


# ── Metric definitions ────────────────────────────────────────────────────────

@dataclass
class TrialResult:
    """Result of one trial (one task execution)."""
    group:              str
    scenario:           str
    trial_id:           int

    closed:             bool  = False
    silence_secs:       float = 0.0
    false_completion:   bool  = False
    violation_detected: bool  = False
    intervention_fired: bool  = False
    gate_denied:        bool  = False
    recovered:          bool  = False
    escalated:          bool  = False
    clean_actor:        bool  = True    # no false positive on normal actors


@dataclass
class GroupMetrics:
    """Aggregated metrics for one treatment group across N trials."""
    group:              str
    scenario:           str
    n_trials:           int = 0

    unclosed:           int = 0
    silence_total:      float = 0.0
    false_completions:  int = 0
    detections:         int = 0
    interventions:      int = 0
    gate_denials:       int = 0
    recoveries:         int = 0
    escalations:        int = 0
    false_positives:    int = 0      # legitimate actors blocked

    @property
    def unclosed_rate(self) -> float:
        return self.unclosed / self.n_trials if self.n_trials else 0.0

    @property
    def avg_silence_secs(self) -> float:
        return self.silence_total / self.n_trials if self.n_trials else 0.0

    @property
    def false_completion_rate(self) -> float:
        return self.false_completions / self.n_trials if self.n_trials else 0.0

    @property
    def detection_rate(self) -> float:
        return self.detections / self.n_trials if self.n_trials else 0.0

    @property
    def recovery_rate(self) -> float:
        return self.recoveries / self.detections if self.detections else 0.0

    @property
    def gate_denial_rate(self) -> float:
        return self.gate_denials / self.n_trials if self.n_trials else 0.0

    @property
    def false_positive_rate(self) -> float:
        return self.false_positives / self.n_trials if self.n_trials else 0.0

    def add_trial(self, t: TrialResult) -> None:
        self.n_trials     += 1
        if not t.closed:
            self.unclosed += 1
        self.silence_total += t.silence_secs
        if t.false_completion:
            self.false_completions += 1
        if t.violation_detected:
            self.detections += 1
        if t.intervention_fired:
            self.interventions += 1
        if t.gate_denied:
            self.gate_denials += 1
        if t.recovered:
            self.recoveries += 1
        if t.escalated:
            self.escalations += 1
        if not t.clean_actor:
            self.false_positives += 1

    def to_dict(self) -> dict:
        return {
            "group":               self.group,
            "n_trials":            self.n_trials,
            "unclosed_rate":       round(self.unclosed_rate, 3),
            "avg_silence_secs":    round(self.avg_silence_secs, 1),
            "false_completion_rate":round(self.false_completion_rate, 3),
            "detection_rate":      round(self.detection_rate, 3),
            "recovery_rate":       round(self.recovery_rate, 3),
            "gate_denial_rate":    round(self.gate_denial_rate, 3),
            "false_positive_rate": round(self.false_positive_rate, 3),
        }


@dataclass
class ABReport:
    """Full A/B experiment report across all three groups."""
    scenario:   str
    n_trials:   int
    seed:       Optional[int]
    groups:     Dict[str, GroupMetrics] = field(default_factory=dict)

    def improvement(self, metric: str, from_group: str, to_group: str) -> float:
        """
        Returns the relative improvement of `metric` going from one group to another.
        Positive = improvement (lower is better for rates like unclosed_rate).
        """
        g0 = self.groups.get(from_group)
        g1 = self.groups.get(to_group)
        if g0 is None or g1 is None:
            return 0.0
        v0 = getattr(g0, metric.replace(".", "_"), None)
        v1 = getattr(g1, metric.replace(".", "_"), None)
        if v0 is None or v1 is None or not callable(
            getattr(type(g0), metric.replace(".", "_"), None)
        ):
            # Try property
            v0 = getattr(g0, metric, None)
            v1 = getattr(g1, metric, None)
        if v0 is None or v1 is None:
            return 0.0
        if isinstance(v0, property):
            return 0.0
        if abs(v0) < 1e-9:
            return 0.0
        return (v0 - v1) / v0  # positive = improvement


# ── Scenario definitions ──────────────────────────────────────────────────────

ScenarioFn = Callable[
    [Optional[OmissionEngine], Optional[OmissionAdapter],
     Optional[InterventionEngine], List, Any],
    TrialResult,
]


def _make_stack(
    with_omission: bool,
    with_intervention: bool,
    group: str,
    scenario: str,
    trial_id: int,
    due_secs: float = 30.0,
) -> Tuple[
    Optional[OmissionEngine],
    Optional[OmissionAdapter],
    Optional[InterventionEngine],
    List,
    Any,
]:
    now_val = [float(trial_id * 500)]
    def fake_now(v=now_val): return v[0]

    if not with_omission:
        return None, None, None, now_val, fake_now

    store    = InMemoryOmissionStore()
    registry = reset_registry()
    for rule_id in (
        "rule_a_delegation", "rule_b_acknowledgement",
        "rule_c_status_update", "rule_e_upstream_notification",
    ):
        registry.override_timing(rule_id, due_within_secs=due_secs)

    engine  = OmissionEngine(store=store, registry=registry, now_fn=fake_now)
    adapter = OmissionAdapter(engine=engine)
    inter   = InterventionEngine(store, now_fn=fake_now,
                                  default_escalate_to="supervisor",
                                  default_fallback_owner="backup") \
              if with_intervention else None
    return engine, adapter, inter, now_val, fake_now


# ── Built-in scenario functions ───────────────────────────────────────────────

def scenario_manager_no_dispatch(
    engine, adapter, inter, now_val, fake_now,
    group: str = "", scenario: str = "", trial_id: int = 0,
) -> TrialResult:
    """Manager receives root task but never dispatches."""
    t = TrialResult(group=group, scenario=scenario, trial_id=trial_id)
    sess = f"sess-{uuid.uuid4().hex[:8]}"

    if adapter:
        adapter.ingest_raw({
            "event_type": "session_start",
            "agent_id": "manager", "session_id": sess,
            "timestamp": fake_now(),
        })

    t.silence_secs = 65.0
    now_val[0] += 65.0

    if engine:
        scan = engine.scan(now=fake_now())
        t.violation_detected = len(scan.violations) > 0
        if inter and scan.violations:
            ir = inter.process_violations(scan.violations)
            t.intervention_fired = len(ir.pulses_fired) > 0
            t.gate_denied = ir.gates_denied > 0

    t.closed = False
    return t


def scenario_worker_no_ack(
    engine, adapter, inter, now_val, fake_now,
    group: str = "", scenario: str = "", trial_id: int = 0,
) -> TrialResult:
    """Manager dispatches correctly, worker never acks."""
    t = TrialResult(group=group, scenario=scenario, trial_id=trial_id)
    sess   = f"sess-{uuid.uuid4().hex[:8]}"
    worker = f"wkr-{uuid.uuid4().hex[:6]}"
    base   = fake_now()

    if adapter:
        adapter.ingest_raw({
            "event_type": "subagent_spawn",
            "agent_id": "manager", "session_id": sess,
            "timestamp": base,
            "parent_agent_id": "manager", "child_agent_id": worker,
        })
        adapter.ingest_raw({
            "event_type": "task_delegated",
            "agent_id": "manager", "session_id": sess,
            "timestamp": base + 3,
        })
    # Worker goes completely silent
    t.silence_secs = 65.0
    now_val[0] = base + 65.0

    if engine:
        scan = engine.scan(now=fake_now())
        t.violation_detected = len(scan.violations) > 0
        if inter and scan.violations:
            ir = inter.process_violations(scan.violations)
            t.intervention_fired = len(ir.pulses_fired) > 0

    t.closed = False
    return t


def scenario_active_then_silent(
    engine, adapter, inter, now_val, fake_now,
    group: str = "", scenario: str = "", trial_id: int = 0,
) -> TrialResult:
    """Worker acks then vanishes — no status update."""
    t = TrialResult(group=group, scenario=scenario, trial_id=trial_id)
    sess   = f"sess-{uuid.uuid4().hex[:8]}"
    worker = f"wkr-{uuid.uuid4().hex[:6]}"
    base   = fake_now()

    if adapter:
        adapter.ingest_raw({
            "event_type": "subagent_spawn",
            "agent_id": "manager", "session_id": sess,
            "timestamp": base,
            "parent_agent_id": "manager", "child_agent_id": worker,
        })
        adapter.ingest_raw({
            "event_type": "task_delegated",
            "agent_id": "manager", "session_id": sess,
            "timestamp": base + 3,
        })
        adapter.ingest_raw({
            "event_type": "task_acked",
            "agent_id": worker, "session_id": sess,
            "timestamp": base + 8,
        })
    # Worker acked but never updates
    t.silence_secs = 120.0
    now_val[0] = base + 120.0

    if engine:
        scan = engine.scan(now=fake_now())
        t.violation_detected = len(scan.violations) > 0
        if inter and scan.violations:
            ir = inter.process_violations(scan.violations)
            t.intervention_fired = len(ir.pulses_fired) > 0

    t.closed = False
    return t


def scenario_false_completion(
    engine, adapter, inter, now_val, fake_now,
    group: str = "", scenario: str = "", trial_id: int = 0,
) -> TrialResult:
    """Worker publishes result but manager falsely claims closure without upstream notify."""
    t = TrialResult(group=group, scenario=scenario, trial_id=trial_id)
    sess   = f"sess-{uuid.uuid4().hex[:8]}"
    worker = f"wkr-{uuid.uuid4().hex[:6]}"
    base   = fake_now()

    if adapter:
        adapter.ingest_raw({
            "event_type": "subagent_spawn",
            "agent_id": "manager", "session_id": sess,
            "timestamp": base, "parent_agent_id": "manager", "child_agent_id": worker,
        })
        adapter.ingest_raw({
            "event_type": "task_acked",
            "agent_id": worker, "session_id": sess, "timestamp": base + 5,
        })
        adapter.ingest_raw({
            "event_type": "result_published",
            "agent_id": worker, "session_id": sess, "timestamp": base + 20,
        })
    # Manager claims done without upstream_summary
    t.false_completion = True
    t.silence_secs = 70.0
    now_val[0] = base + 70.0

    if engine:
        scan = engine.scan(now=fake_now())
        t.violation_detected = len(scan.violations) > 0
        if inter and scan.violations:
            ir = inter.process_violations(scan.violations)
            t.intervention_fired = len(ir.pulses_fired) > 0

    t.closed = False  # false completion exposed by omission
    return t


def scenario_healthy_closure(
    engine, adapter, inter, now_val, fake_now,
    group: str = "", scenario: str = "", trial_id: int = 0,
) -> TrialResult:
    """Full healthy cycle — used to measure false positive rate."""
    t = TrialResult(group=group, scenario=scenario, trial_id=trial_id)
    sess   = f"sess-{uuid.uuid4().hex[:8]}"
    worker = f"wkr-{uuid.uuid4().hex[:6]}"
    base   = fake_now()

    if adapter:
        for ev in [
            {"event_type": "subagent_spawn", "agent_id": "manager",
             "session_id": sess, "timestamp": base,
             "parent_agent_id": "manager", "child_agent_id": worker},
            {"event_type": "task_delegated", "agent_id": "manager",
             "session_id": sess, "timestamp": base + 3},
            {"event_type": "task_acked", "agent_id": worker,
             "session_id": sess, "timestamp": base + 8},
            {"event_type": "status_update", "agent_id": worker,
             "session_id": sess, "timestamp": base + 15},
            {"event_type": "result_published", "agent_id": worker,
             "session_id": sess, "timestamp": base + 25},
            {"event_type": "upstream_summary", "agent_id": "manager",
             "session_id": sess, "timestamp": base + 35},
        ]:
            adapter.ingest_raw(ev)

    now_val[0] = base + 60.0
    if engine:
        scan = engine.scan(now=fake_now())
        t.violation_detected = len(scan.violations) > 0
        t.clean_actor = not t.violation_detected   # false positive if violation on healthy task
        if inter and scan.violations:
            ir = inter.process_violations(scan.violations)
            t.intervention_fired = len(ir.pulses_fired) > 0

    t.closed = True
    return t


_SCENARIO_FNS: Dict[str, ScenarioFn] = {
    "manager_no_dispatch":   scenario_manager_no_dispatch,
    "worker_no_ack":         scenario_worker_no_ack,
    "active_then_silent":    scenario_active_then_silent,
    "false_completion":      scenario_false_completion,
    "healthy_closure":       scenario_healthy_closure,
}


# ── Main experiment runner ────────────────────────────────────────────────────

def run_ab_experiment(
    scenario:     str = "worker_no_ack",
    n_trials:     int = 20,
    random_seed:  Optional[int] = None,
    due_secs:     float = 30.0,
) -> ABReport:
    """
    Run a 3-group A/B experiment for the given scenario.

    Returns ABReport with metrics for all three groups.
    """
    if random_seed is not None:
        random.seed(random_seed)

    fn = _SCENARIO_FNS.get(scenario)
    if fn is None:
        raise ValueError(f"Unknown scenario: {scenario!r}. Available: {list(_SCENARIO_FNS)}")

    report = ABReport(scenario=scenario, n_trials=n_trials, seed=random_seed)

    group_configs = [
        ("baseline",             False, False),
        ("omission_only",        True,  False),
        ("omission+intervention",True,  True),
    ]

    for group_name, with_omission, with_intervention in group_configs:
        gm = GroupMetrics(group=group_name, scenario=scenario)
        for trial_id in range(n_trials):
            engine, adapter, inter, now_val, fake_now = _make_stack(
                with_omission, with_intervention,
                group_name, scenario, trial_id, due_secs,
            )
            trial = fn(engine, adapter, inter, now_val, fake_now,
                       group=group_name, scenario=scenario, trial_id=trial_id)
            gm.add_trial(trial)
        report.groups[group_name] = gm

    return report


def run_full_battery(n_trials: int = 20, seed: int = 42) -> Dict[str, ABReport]:
    """Run all built-in scenarios and return a dict of ABReports."""
    return {
        scenario: run_ab_experiment(scenario, n_trials, seed)
        for scenario in _SCENARIO_FNS
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_ab_report(report: ABReport, compact: bool = False) -> None:
    """Print a formatted A/B comparison table."""
    METRICS = [
        ("unclosed_rate",       "Unclosed rate",       "↓"),
        ("avg_silence_secs",    "Avg silence (s)",     "↓"),
        ("false_completion_rate","False completion",   "↓"),
        ("detection_rate",      "Detection rate",      "↑"),
        ("recovery_rate",       "Recovery rate",       "↑"),
        ("gate_denial_rate",    "Gate denial rate",    "↑"),
        ("false_positive_rate", "False positive rate", "↓"),
    ]

    groups = ["baseline", "omission_only", "omission+intervention"]
    print(f"\n{'='*72}")
    print(f"  A/B EXPERIMENT: {report.scenario.upper()}")
    print(f"  Trials per group: {report.n_trials}  |  Seed: {report.seed}")
    print(f"{'='*72}")
    print(f"  {'Metric':<28} {'Baseline':>12} {'Omission':>12} {'Full':>12}  {'Δ(0→2)':>8}")
    print(f"  {'-'*68}")

    for attr, label, direction in METRICS:
        vals = []
        for g in groups:
            gm = report.groups.get(g)
            v = getattr(gm, attr, 0.0) if gm else 0.0
            vals.append(v)

        # Delta: baseline → full
        v0, v2 = vals[0], vals[2]
        if abs(v0) > 1e-9:
            delta = (v2 - v0) / abs(v0) * 100
        else:
            delta = 0.0

        better = (direction == "↓" and delta < -5) or (direction == "↑" and delta > 5)
        worse  = (direction == "↓" and delta > 5)  or (direction == "↑" and delta < -5)

        # Format values
        fmts = []
        for v in vals:
            if attr.endswith("_secs"):
                fmts.append(f"{v:.1f}s")
            else:
                fmts.append(f"{v:.1%}")

        delta_str = f"{delta:+.0f}%" if abs(delta) > 0.5 else "—"
        marker = "✅" if better else ("⚠️" if worse else "  ")

        print(f"  {direction} {label:<27} {fmts[0]:>12} {fmts[1]:>12} {fmts[2]:>12}  {delta_str:>6} {marker}")

    print(f"{'='*72}\n")


def print_battery_report(battery: Dict[str, ABReport]) -> None:
    """Print summary for all scenarios."""
    print(f"\n{'='*72}")
    print(f"  FULL BATTERY RESULTS  ({len(battery)} scenarios)")
    print(f"{'='*72}")
    print(f"  {'Scenario':<30} {'Detection':>10} {'Recovery':>10} {'FP rate':>10}")
    print(f"  {'-'*62}")
    for scenario, report in battery.items():
        full = report.groups.get("omission+intervention")
        base = report.groups.get("baseline")
        if full and base:
            det = full.detection_rate
            rec = full.recovery_rate
            fp  = full.false_positive_rate
            det_col = "✅" if det > 0.8 else ("⚠️" if det > 0.3 else "❌")
            print(f"  {scenario:<30} {det:.0%} {det_col:>2}  {rec:.0%}      {fp:.0%}")
    print(f"{'='*72}\n")

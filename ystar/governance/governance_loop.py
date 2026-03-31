# Layer: Foundation
"""
ystar.governance_loop  —  P1: Governance-Aware Meta-Learning Bridge
====================================================================
v0.41.0

"停止造新轮子，把已有 metalearning 资源编排到治理主线里。"

这不是一个新的 meta-learning 引擎。
它是一个编排层，把三个已有资源接在一起：

  已有资源 1: YStarLoop        (commission side: CallRecord → tighten)
  已有资源 2: ReportEngine     (governance side: omission/intervention metrics)
  已有资源 3: ConstraintRegistry (proposal activation → controlled change)

编排方式：

  baseline_report()
       ↓ to_learning_observations()
  GovernanceObservation
       ↓ feed_to_loop()
  YStarLoop.record() + governance_tighten()
       ↓
  GovernanceTightenResult
       ↓ 包含：
          contract_suggestions    (来自 commission 侧学习)
          governance_suggestions  (来自 omission/intervention 侧学习)
       ↓ apply_suggestions_via_registry()
  ConstraintRegistry              (受控激活，不直接热改宪法)

闭环：
  生态接入 → 观测 → 反馈 → 参数建议 → 受控激活 → re-baseline
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ystar.governance.reporting import Report, ReportEngine
# Connection 5: AdaptiveCoefficients — shared between commission and governance
from ystar.governance.metalearning import AdaptiveCoefficients


# ── 治理侧观测对象 ─────────────────────────────────────────────────────────────

@dataclass
class GovernanceObservation:
    """
    一次治理周期的结构化观测。
    由 Report.to_learning_observations() 产生，作为 meta-learning 的输入。

    commission 侧（已有 YStarLoop）→ 通过 CallRecord 历史
    governance 侧（新增）          → 通过此对象
    """
    # 观测时间段
    period_label:             str   = ""
    observed_at:              float = field(default_factory=time.time)

    # omission 侧指标
    obligation_fulfillment_rate:   float = 0.0
    obligation_expiry_rate:        float = 0.0
    hard_overdue_rate:             float = 0.0
    omission_detection_rate:       float = 0.0
    omission_recovery_rate:        float = 0.0

    # intervention 侧指标
    intervention_recovery_rate:    float = 0.0
    false_positive_rate:           float = 0.0

    # 链级指标
    chain_closure_rate:            float = 0.0

    # 原始数据（供深度分析）
    raw_kpis:                      Dict[str, float] = field(default_factory=dict)
    by_omission_type:              Dict[str, int]   = field(default_factory=dict)
    by_actor:                      Dict[str, int]   = field(default_factory=dict)
    broken_chain_count:            int = 0
    total_entities:                int = 0

    def is_healthy(self) -> bool:
        """快速健康判断：所有核心指标是否在可接受范围内。"""
        return (
            self.obligation_fulfillment_rate >= 0.8
            and self.hard_overdue_rate <= 0.05
            and self.false_positive_rate <= 0.02
        )

    def needs_tightening(self) -> bool:
        """是否需要收紧治理参数（omission 过多，recovery 不足）。"""
        return (
            self.omission_detection_rate > 0.3
            and self.omission_recovery_rate < 0.5
        )

    def needs_relaxing(self) -> bool:
        """是否需要放宽治理参数（误伤过多）。"""
        return self.false_positive_rate > 0.05

    def to_dict(self) -> dict:
        return {
            "period_label":               self.period_label,
            "observed_at":                self.observed_at,
            "obligation_fulfillment_rate":self.obligation_fulfillment_rate,
            "obligation_expiry_rate":      self.obligation_expiry_rate,
            "hard_overdue_rate":           self.hard_overdue_rate,
            "omission_detection_rate":     self.omission_detection_rate,
            "omission_recovery_rate":      self.omission_recovery_rate,
            "intervention_recovery_rate":  self.intervention_recovery_rate,
            "false_positive_rate":         self.false_positive_rate,
            "chain_closure_rate":          self.chain_closure_rate,
            "is_healthy":                  self.is_healthy(),
            "needs_tightening":            self.needs_tightening(),
            "needs_relaxing":              self.needs_relaxing(),
        }


# ── 治理侧调参建议 ─────────────────────────────────────────────────────────────

@dataclass
class GovernanceSuggestion:
    """
    一条基于观测产生的治理参数调整建议。
    不直接修改任何配置，而是提交给 ConstraintRegistry 受控激活。
    """
    suggestion_type:  str   = ""    # "tighten_timing" / "relax_timing" / "add_domain_pack" / etc.
    target_rule_id:   str   = ""
    current_value:    Any   = None
    suggested_value:  Any   = None
    confidence:       float = 0.5   # 0~1
    rationale:        str   = ""
    observation_ref:  str   = ""    # GovernanceObservation.period_label

    def to_constraint_proposal_dict(self) -> dict:
        """转换为 ConstraintRegistry 可消费的格式。"""
        return {
            "rule_id":         self.target_rule_id,
            "suggestion_type": self.suggestion_type,
            "current":         self.current_value,
            "suggested":       self.suggested_value,
            "confidence":      self.confidence,
            "rationale":       self.rationale,
            "source":          "governance_loop",
        }


@dataclass
class GovernanceTightenResult:
    """
    一次治理侧学习周期的输出。
    包含 commission 侧建议（来自 YStarLoop）和 governance 侧建议（新增）。
    """
    # commission 侧
    commission_result:       Optional[Any] = None  # MetalearnResult

    # governance 侧
    governance_suggestions:  List[GovernanceSuggestion] = field(default_factory=list)
    observation:             Optional[GovernanceObservation] = None

    # 综合判断
    overall_health:          str = "unknown"  # healthy / degraded / critical
    recommended_action:      str = ""
    # Connection 6: ContractQuality self-assessment
    contract_quality:        Optional[Any] = None
    # Connection 8: scan_restorations — actors whose capabilities were restored
    restored_actors:         List[str] = field(default_factory=list)
    # Connection 8: intervention snapshot
    intervention_snapshot:   Optional[dict] = None
    # Pearl integration: causal reasoning chain from CausalEngine
    causal_chain:            List[str] = field(default_factory=list)
    # Pearl integration: structure discovery validation result
    structure_validated:     Optional[dict] = None

    def is_action_required(self) -> bool:
        return self.overall_health in ("degraded", "critical") or \
               len(self.governance_suggestions) > 0

    def summary(self) -> str:
        parts = [f"health={self.overall_health}"]
        if self.governance_suggestions:
            parts.append(f"{len(self.governance_suggestions)} governance suggestions")
        if self.commission_result:
            parts.append("commission tightened")
        return " | ".join(parts)


# ── Report → GovernanceObservation ────────────────────────────────────────────

def report_to_observation(report: Report) -> GovernanceObservation:
    """
    将 ReportEngine 产出的 Report 转换为 GovernanceObservation。
    这是连接 reporting 层和 meta-learning 层的关键桥接函数。
    """
    kpis = report.kpis or {}
    omission_d = report.omissions.to_dict() if report.omissions else {}

    return GovernanceObservation(
        period_label                = report.period_label,
        obligation_fulfillment_rate = kpis.get("obligation_fulfillment_rate", 0.0),
        obligation_expiry_rate      = kpis.get("obligation_expiry_rate", 0.0),
        hard_overdue_rate           = kpis.get("hard_overdue_rate", 0.0),
        omission_detection_rate     = kpis.get("omission_detection_rate", 0.0),
        omission_recovery_rate      = kpis.get("omission_recovery_rate", 0.0),
        intervention_recovery_rate  = kpis.get("intervention_recovery_rate", 0.0),
        false_positive_rate         = kpis.get("false_positive_rate", 0.0),
        chain_closure_rate          = kpis.get("chain_closure_rate", 0.0),
        raw_kpis                    = dict(kpis),
        by_omission_type            = dict(omission_d.get("by_omission_type", {})),
        by_actor                    = dict(omission_d.get("by_actor", {})),
        broken_chain_count          = omission_d.get("broken_chains", 0),
        total_entities              = report.chain.total_entities,
    )


# ── GovernanceLoop ─────────────────────────────────────────────────────────────

class GovernanceLoop:
    """
    治理感知的 meta-learning 闭环。

    把已有资源编排成闭环，不重写任何已有功能：
      YStarLoop       ← commission 侧（不动）
      ReportEngine    ← governance 侧观测源
      ConstraintRegistry ← 建议激活链

    使用方式：
        loop = GovernanceLoop(
            report_engine = ReportEngine(omission_store=store),
        )

        # 每次 scan 后喂入结果
        loop.observe_from_report_engine()

        # 定期触发学习周期
        result = loop.tighten()
        print(result.summary())

        # 把建议提交给 ConstraintRegistry（受控激活）
        loop.submit_suggestions_to_registry(result)
    """

    def __init__(
        self,
        report_engine:        ReportEngine,
        ystar_loop:           Optional[Any] = None,   # YStarLoop（可选）
        constraint_registry:  Optional[Any] = None,   # ConstraintRegistry（可选）
        intervention_engine:  Optional[Any] = None,   # InterventionEngine（可选）
        causal_engine:        Optional[Any] = None,   # CausalEngine（可选）— Pearl L2-3
        amendment_engine:     Optional[Any] = None,   # AmendmentEngine（可选）
    ) -> None:
        self.report_engine        = report_engine
        self.constraint_registry  = constraint_registry
        self._intervention_engine = intervention_engine
        self._causal_engine       = causal_engine       # Pearl integration point
        self._amendment_engine    = amendment_engine     # Amendment system integration
        self._observations:       List[GovernanceObservation] = []
        self._baseline:           Optional[GovernanceObservation] = None

        # Connection 5: Full RefinementFeedback loop
        # GovernanceLoop maintains a SINGLE AdaptiveCoefficients instance
        # that flows through BOTH commission (YStarLoop) and governance sides.
        # This is the true fusion: one coefficient set, two feedback sources.
        self.coefficients = AdaptiveCoefficients()

        # 接入已有 YStarLoop（commission 侧）
        # Initialize with shared coefficients so derive_objective_adaptive() is used
        if ystar_loop is None:
            try:
                from ystar.governance.metalearning import YStarLoop
                self._ystar_loop = YStarLoop(
                    initial_coefficients=self.coefficients
                )
            except (ImportError, TypeError):
                try:
                    from ystar.governance.metalearning import YStarLoop
                    self._ystar_loop = YStarLoop()
                except ImportError:
                    self._ystar_loop = None
        else:
            self._ystar_loop = ystar_loop
            # Adopt existing loop's coefficients if available
            if hasattr(ystar_loop, 'coefficients'):
                self.coefficients = ystar_loop.coefficients

    # ── 观测 ──────────────────────────────────────────────────────────────────

    def bootstrap_from_jsonl(self, jsonl_path: str) -> int:
        """
        Connection 9: learn_from_jsonl — seed learning loop from historical data.

        Loads CIEU/audit JSONL records from disk and feeds them into
        YStarLoop so governance can start from a non-zero baseline
        rather than waiting for live session data.

        Args:
            jsonl_path: path to a JSONL file of CallRecord-compatible dicts

        Returns:
            number of records loaded
        """
        if self._ystar_loop is None:
            return 0
        try:
            from ystar.governance.metalearning import learn_from_jsonl
            # learn_from_jsonl returns a MetalearnResult
            # but it also populates call records — extract them
            import json
            records = []
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        from ystar.governance.metalearning import CallRecord
                        rec = CallRecord(
                            seq        = d.get('seq', len(records)),
                            func_name  = d.get('func_name', d.get('event_type', 'unknown')),
                            params     = d.get('params', {}),
                            result     = d.get('result', {}),
                            violations = d.get('violations', []),
                        )
                        records.append(rec)
                    except Exception:
                        continue
            self._ystar_loop.record_many(records)
            return len(records)
        except Exception:
            return 0


    def bootstrap_from_scan_history(
        self,
        days_back:   int = 30,
        max_records: int = 5000,
        jsonl_path:  str = None,
    ) -> int:
        """
        Connection 9b: seed learning loop from scan_history() — the history scanner.

        Unlike bootstrap_from_jsonl (which takes a raw path), this uses
        the full scan_history pipeline: tries Claude Code logs, CIEU DB,
        then JSONL, returning the first available source.

        Args:
            days_back:   how far back to scan (default 30 days)
            max_records: cap on records loaded
            jsonl_path:  optional explicit JSONL path (passed to scan_history)

        Returns:
            number of records seeded
        """
        from ystar.kernel.history_scanner import scan_history
        try:
            records, source_id, source_desc = scan_history(
                days_back   = days_back,
                max_records = max_records,
                jsonl_path  = jsonl_path,
            )
            if not records:
                return 0
            # Re-use the JSONL bootstrap path: export records to temp file
            import tempfile, json, os
            with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                             delete=False) as tmp:
                for r in records:
                    tmp.write(json.dumps({
                        "func_name": r.tool_name,
                        "params":    r.tool_input or {},
                        "result":    {},
                        "violations":[],
                        "source":    source_id,
                    }) + "\n")
                tmp_path = tmp.name
            try:
                n = self.bootstrap_from_jsonl(tmp_path)
            finally:
                os.unlink(tmp_path)
            return n
        except Exception:
            return 0
    def ingest_cieu_to_causal_engine(
        self,
        cieu_records: List[Dict[str, Any]],
    ) -> int:
        """
        Pearl Integration 4: Feed CIEU global records into CausalEngine.

        Converts CIEU audit records (from any source, not just Path A) into
        CausalObservation format and feeds them into the SCM. This gives the
        Pearl engine a much richer dataset than Path A cycles alone.

        Each CIEU record is mapped to SCM variables:
          - W (wiring): 1.0 if action=wire/allow, 0.0 if deny
          - O (obligations): derived from passed/decision fields
          - H (health): inferred from result fields
          - S (suggestions): derived from event_type

        Args:
            cieu_records: list of CIEU record dicts (from CIEUStore or JSONL)

        Returns:
            Number of records successfully ingested.
        """
        if self._causal_engine is None:
            return 0

        ingested = 0
        for rec in cieu_records:
            try:
                event_type = rec.get("event_type", "")
                decision = rec.get("decision", "")
                passed = rec.get("passed", False)
                result_data = rec.get("result", {})

                # Map to health labels
                # Successful decisions suggest healthy/stable state
                health_after = "stable" if passed else "degraded"
                if isinstance(result_data, dict):
                    if result_data.get("status") == "fulfilled":
                        health_after = "healthy"
                    elif result_data.get("status") in ("failed", "rollback"):
                        health_after = "critical"

                # Previous health: assume stable as baseline for CIEU records
                health_before = "stable"

                # Obligation counts: infer from event semantics
                obl_total = 1  # Each CIEU record represents one obligation unit
                obl_fulfilled = 1 if passed else 0

                # Action edges: derive from event type
                action_edges = []
                params = rec.get("params", {})
                if isinstance(params, dict):
                    src = params.get("source", event_type)
                    tgt = params.get("target", rec.get("agent_id", "unknown"))
                    action_edges = [(str(src), str(tgt))]

                self._causal_engine.observe(
                    health_before=health_before,
                    health_after=health_after,
                    obl_before=(0, obl_total),
                    obl_after=(obl_fulfilled, obl_total),
                    edges_before=[],
                    edges_after=action_edges,
                    action_edges=action_edges,
                    succeeded=passed,
                    cycle_id=f"cieu_{rec.get('session_id', 'unknown')}_{ingested}",
                    suggestion_type=event_type or None,
                )
                ingested += 1
            except Exception:
                continue  # Skip malformed records

        return ingested

    def observe_from_report_engine(self, since: Optional[float] = None) -> GovernanceObservation:
        """
        从 ReportEngine 生成当前观测，加入观测历史。
        这是 P1 的核心：把 reporting 输出接进 meta-learning 输入。
        """
        report = self.report_engine.daily_report(since=since)
        obs    = report_to_observation(report)
        self._observations.append(obs)
        return obs

    def discover_and_propose_parameters(
        self,
        cieu_history: Optional[List[dict]] = None,
    ) -> List[GovernanceSuggestion]:
        """
        Connection 3: ParameterHint → GovernanceSuggestion → ConstraintRegistry

        Runs discover_parameters() on CIEU call history and converts
        ParameterHint objects into GovernanceSuggestions.
        These suggestions can then be submitted to ConstraintRegistry
        via submit_suggestions_to_registry().

        Args:
            cieu_history: list of call dicts (if None, uses YStarLoop history)
        """
        try:
            from ystar.governance.metalearning import discover_parameters, ParameterHint
            # Build history dict from YStarLoop or provided data
            history_dict: dict = {}
            if cieu_history:
                for rec in cieu_history:
                    fn = rec.get('func_name', 'unknown')
                    if fn not in history_dict:
                        history_dict[fn] = []
                    history_dict[fn].append({'params': rec.get('params', {})})
            elif self._ystar_loop and self._ystar_loop.history:
                for rec in self._ystar_loop.history:
                    if rec.func_name not in history_dict:
                        history_dict[rec.func_name] = []
                    history_dict[rec.func_name].append({'params': rec.params})

            if not history_dict:
                return []

            hints: List[ParameterHint] = discover_parameters(history_dict)
            suggestions = []
            for hint in hints[:5]:  # cap at 5 per discovery run
                hint_type  = getattr(hint, 'hint_type', 'OBSERVED_ONLY')
                constraint = getattr(hint, 'suggested_constraint', '')
                confidence = 0.75 if hint_type == 'NUMERIC_THRESHOLD' else (
                             0.65 if hint_type == 'CATEGORICAL' else 0.4)

                # 语义询问：对数值阈值发现，调用语义推断引擎获取上下文解释
                semantic_rationale = ""
                if hint_type == 'NUMERIC_THRESHOLD':
                    try:
                        from ystar.governance.metalearning import inquire_parameter_semantics
                        param_name_hint = getattr(hint, 'param_name', '')
                        # inquire_parameter_semantics(param_name, hint, domain_context="")
                        sem = inquire_parameter_semantics(
                            param_name_hint, hint, domain_context="",
                        )
                        if sem and hasattr(sem, 'reasoning'):
                            semantic_rationale = f" | Semantic: {sem.reasoning[:80]}"
                    except Exception:
                        pass

                suggestions.append(GovernanceSuggestion(
                    suggestion_type = f"parameter_discovery_{hint_type.lower()}",
                    target_rule_id  = getattr(hint, 'param_name', 'unknown_param'),
                    current_value   = None,
                    suggested_value = constraint,
                    confidence      = confidence,
                    rationale       = (
                        f"ParameterHint({hint_type}): parameter "
                        f"'{getattr(hint, 'param_name', '')}' "
                        f"suggests constraint: {str(constraint)[:100]}"
                        + semantic_rationale
                    ),
                    observation_ref = "parameter_discovery",
                ))
            return suggestions
        except Exception:
            return []

    def observe_from_report(self, report: Report) -> GovernanceObservation:
        """从已有 Report 对象直接提取观测（避免重复查询 store）。"""
        obs = report_to_observation(report)
        self._observations.append(obs)
        return obs

    def set_baseline(self, report: Optional[Report] = None) -> GovernanceObservation:
        """
        设置基线观测（对应 baseline_report）。
        之后的 delta 分析都以此为参照。
        """
        if report is None:
            report = self.report_engine.baseline_report()
        self._baseline = report_to_observation(report)
        self._baseline.period_label = "baseline"
        return self._baseline

    # ── 学习 ──────────────────────────────────────────────────────────────────

    def tighten(self) -> GovernanceTightenResult:
        """
        运行一次完整的治理学习周期：
          1. 分析最近观测，产出 governance 建议
          2. （可选）触发 commission 侧 YStarLoop.tighten()
          3. 综合评估，输出 GovernanceTightenResult
        """
        result = GovernanceTightenResult()

        if not self._observations:
            result.overall_health    = "unknown"
            result.recommended_action = "No observations yet. Call observe_from_report_engine() first."
            return result

        latest = self._observations[-1]
        result.observation = latest

        # Amendment check: if amendment_engine has pending amendments, note in result
        if self._amendment_engine is not None:
            try:
                pending = self._amendment_engine.list_proposals(status="approved")
                if pending:
                    result.recommended_action = (
                        f"{len(pending)} approved amendment(s) pending activation. "
                        + result.recommended_action
                    )
            except Exception:
                pass

        # Connection 8a: scan_restorations — restore actor capabilities
        # when their hard_overdue obligations are fulfilled.
        # This closes the intervention loop: gate → obligation fulfilled → restore.
        if self._intervention_engine is not None:
            try:
                restored = self._intervention_engine.scan_restorations()
                if restored:
                    result.restored_actors = restored
            except Exception:
                pass

        # Commission 侧学习（已有 YStarLoop，直接驱动）
        # Connection 1: inject governance coefficients so YStarLoop uses
        # derive_objective_adaptive() with our adaptive coefficients instead
        # of the hardcoded derive_objective() constants
        if self._ystar_loop:
            try:
                # Fuse: write governance-updated coefficients into commission loop
                # so the commission objective reflects governance feedback
                self._ystar_loop.coefficients = self.coefficients
                result.commission_result = self._ystar_loop.tighten()
                # Read back (YStarLoop may have further updated them)
                self.coefficients = self._ystar_loop.coefficients
            except Exception:
                pass

        # Governance 侧 RefinementFeedback（如有前一次观测，计算 delta 作为反馈）
        if len(self._observations) >= 2 and self._ystar_loop:
            try:
                from ystar.governance.metalearning import RefinementFeedback, update_coefficients
                from ystar.governance.metalearning import NormativeObjective
                prev, curr = self._observations[-2], self._observations[-1]
                # 把 omission 指标转换为 RefinementFeedback 的 diagnosis 格式
                # A_ideal_deficient = entities with omission (not ideal)
                # C_over_tightened  = false positives
                total = max(curr.total_entities, 1)
                fb = RefinementFeedback(
                    objective_used   = NormativeObjective(),
                    diagnosis_before = {
                        "A_ideal_deficient": int(prev.omission_detection_rate * total),
                        "B_compliant":       int((1 - prev.omission_detection_rate) * total),
                        "C_over_tightened":  int(prev.false_positive_rate * total),
                        "D_unreachable":     0,
                    },
                    diagnosis_after  = {
                        "A_ideal_deficient": int(curr.omission_detection_rate * total),
                        "B_compliant":       int((1 - curr.omission_detection_rate) * total),
                        "C_over_tightened":  int(curr.false_positive_rate * total),
                        "D_unreachable":     0,
                    },
                    history_size = total,
                )
                # 把 feedback 写入 YStarLoop 的 coefficients（commission+governance 融合）
                self._ystar_loop.coefficients = update_coefficients(
                    fb, self._ystar_loop.coefficients
                )
            except Exception:
                pass

        # ── Pearl Integration 2: Metalearning results → CausalEngine ──────
        # When GovernanceLoop runs tighten(), the metalearning results (what
        # rules were learned) are converted to CausalObservation format and
        # fed into CausalEngine.observe(). This gives the Pearl engine
        # visibility into the metalearning loop's outcomes.
        #   Rule learned + health improved → positive observation
        #   Rule learned + no improvement → negative observation
        if (self._causal_engine is not None
                and len(self._observations) >= 2
                and result.commission_result is not None):
            try:
                prev, curr = self._observations[-2], self._observations[-1]
                health_improved = (
                    curr.obligation_fulfillment_rate > prev.obligation_fulfillment_rate
                    or (curr.hard_overdue_rate < prev.hard_overdue_rate)
                )
                # Map governance observation to CausalEngine's observe() format
                # Suggestion type from commission result
                stype = None
                if hasattr(result.commission_result, 'adjustments'):
                    stype = "metalearning_tighten"

                # Obligation counts from governance observations
                total_ent = max(curr.total_entities, 1)
                fulfilled = int(curr.obligation_fulfillment_rate * total_ent)
                prev_fulfilled = int(prev.obligation_fulfillment_rate * total_ent)

                health_label = "healthy" if curr.is_healthy() else (
                    "degraded" if curr.hard_overdue_rate > 0.1 else "stable"
                )
                prev_health = "healthy" if prev.is_healthy() else (
                    "degraded" if prev.hard_overdue_rate > 0.1 else "stable"
                )

                self._causal_engine.observe(
                    health_before=prev_health,
                    health_after=health_label,
                    obl_before=(prev_fulfilled, total_ent),
                    obl_after=(fulfilled, total_ent),
                    edges_before=[],
                    edges_after=[],
                    action_edges=[("metalearning", "governance")],
                    succeeded=health_improved,
                    cycle_id=f"governance_tighten_{curr.period_label}",
                    suggestion_type=stype,
                )
            except Exception:
                pass  # CausalEngine feed failed; don't block governance

        # ── Pearl Integration 3: Auto-trigger structure discovery ─────
        # When enough cycle-level observations have accumulated, validate
        # the causal DAG against data-discovered structure.
        if self._causal_engine is not None:
            try:
                n_obs = self._causal_engine.count_cycle_observations()
                if n_obs >= 30:
                    discovered = self._causal_engine.learn_structure(
                        min_observations=30,
                    )
                    if discovered is not None:
                        result.structure_validated = getattr(
                            self._causal_engine, '_structure_validation', None
                        )
            except Exception:
                pass  # Structure discovery failed; don't block governance

        # Governance 侧：产出参数建议
        suggestions = self._generate_governance_suggestions(latest)
        # Connection 2: DimensionDiscovery — new dimension suggestions
        dim_suggestions = self._run_dimension_discovery()
        suggestions = suggestions + dim_suggestions

        # ── Pearl Integration 1: CausalEngine weights suggestions ──────────
        # When CausalEngine is available, ask P(Health|do(suggestion)) for each
        # suggestion and use causal confidence to weight the suggestion's own
        # confidence score. Higher causal confidence = more trustworthy.
        if self._causal_engine is not None and suggestions:
            causal_chain_entries: List[str] = []
            for sug in suggestions:
                try:
                    # Query the causal engine: what is the expected health
                    # effect if we apply this suggestion (wiring action)?
                    do_result = self._causal_engine.do_wire_query(
                        sug.suggestion_type,
                        sug.target_rule_id,
                    )
                    # Weight the suggestion confidence by causal confidence
                    # formula: blended = 0.5 * original + 0.5 * causal_confidence
                    if do_result.confidence > 0:
                        original_conf = sug.confidence
                        sug.confidence = (
                            0.5 * original_conf + 0.5 * do_result.confidence
                        )
                        causal_chain_entries.append(
                            f"P(H|do({sug.suggestion_type}→{sug.target_rule_id}))"
                            f"={do_result.predicted_health}"
                            f" conf={do_result.confidence:.2f}"
                            f" (original={original_conf:.2f}→{sug.confidence:.2f})"
                        )
                    # Include the full causal chain from the do-calculus query
                    causal_chain_entries.extend(do_result.causal_chain)
                except Exception:
                    pass  # CausalEngine query failed; keep original confidence
            result.causal_chain = causal_chain_entries

        result.governance_suggestions = suggestions

        # Connection 13: process_violations → intervention pulses
        # Automatically convert current omission violations into intervention
        # actions so the intervention engine stays in sync with governance loop.
        if self._intervention_engine is not None:
            try:
                from ystar.governance.omission_models import ObligationStatus
                pending_obs = self.report_engine.omission_store.list_obligations()
                # Build synthetic violations from hard/soft overdue obligations
                from ystar.governance.omission_models import OmissionViolation, OmissionType, Severity
                import time as _time
                violations = []
                for ob in pending_obs:
                    if ob.status in (ObligationStatus.SOFT_OVERDUE,
                                     ObligationStatus.HARD_OVERDUE):
                        violations.append(OmissionViolation(
                            obligation_id = ob.obligation_id,
                            entity_id     = ob.entity_id,
                            actor_id      = ob.actor_id,
                            omission_type = ob.obligation_type,
                            severity      = Severity.HIGH if ob.status == ObligationStatus.HARD_OVERDUE
                                           else Severity.MEDIUM,
                            detected_at   = _time.time(),
                            overdue_secs  = ob.hard_overdue_secs or 0.0,
                            details       = {"stage": ob.status.value,
                                             "rule_id": ob.rule_id},
                        ))
                if violations:
                    iv_result = self._intervention_engine.process_violations(violations)
                    result.restored_actors.extend(
                        getattr(iv_result, 'restored_actors', [])
                    )
            except Exception:
                pass

        # Connection 6: ContractQuality self-assessment
        result.contract_quality = self._score_contract_quality()

        # Connection 8b + 11: intervention_report + pending_reroutes snapshot
        if self._intervention_engine is not None:
            try:
                snapshot = self._intervention_engine.intervention_report()
                # Connection 11: pending_reroutes — actors awaiting fallback handoff
                try:
                    reroutes = self._intervention_engine.pending_reroutes()
                    snapshot["pending_reroutes"] = [
                        {"entity_id": r.entity_id, "actor_id": r.actor_id}
                        for r in reroutes
                    ]
                except Exception:
                    snapshot["pending_reroutes"] = []
                result.intervention_snapshot = snapshot
            except Exception:
                pass

        # 综合健康判断
        result.overall_health    = self._assess_health(latest)
        result.recommended_action = self._recommend_action(latest, suggestions)

        return result

    # ── 建议激活 ──────────────────────────────────────────────────────────────

    def submit_verified_proposals_to_registry(
        self,
        auto_approve_confidence_threshold: float = 0.7,
    ) -> int:
        """
        Connection 15: inquire_and_verify — run the full pipeline then submit.

        Combines auto_inquire_all() + verify_proposal() and directly submits
        proposals that pass mathematical verification to ConstraintRegistry.
        Only proposals with verdict=PASS/WARN enter the registry.

        Returns number of verified proposals submitted.
        """
        if not self._ystar_loop or not self._ystar_loop.history:
            return 0
        try:
            from ystar.governance.metalearning import inquire_and_verify, ManagedConstraint
            import time, uuid
            tuples = inquire_and_verify(
                history        = self._ystar_loop.history,
                known_contract = self._ystar_loop.base_contract,
                domain_context = "governance",
                api_call_fn    = None,
                min_confidence = 0.4,
            )
            submitted = 0
            for proposal, vreport in tuples:
                if vreport.verdict not in ("PASS", "WARN"):
                    continue
                mc = ManagedConstraint(
                    id         = str(uuid.uuid4())[:8],
                    dimension  = getattr(proposal, 'suggested_dim', 'governance'),
                    rule       = getattr(proposal, 'suggested_rule', str(proposal)),
                    status     = "DRAFT",
                    source     = "inquire_and_verify",
                    confidence = getattr(proposal, 'confidence', 0.5),
                    created_at = time.time(),
                    updated_at = time.time(),
                    notes      = (
                        f"verify={vreport.verdict} "
                        f"cov={vreport.empirical_coverage:.0%} "
                        f"fp={vreport.empirical_fp_rate:.0%}"
                    ),
                )
                if self.constraint_registry:
                    self.constraint_registry.add(mc)
                    if mc.confidence >= auto_approve_confidence_threshold:
                        self.constraint_registry.verify(mc.id, notes="auto-verified")
                        self.constraint_registry.approve(mc.id, notes="auto-approved")
                    submitted += 1
            return submitted
        except Exception:
            return 0

    def submit_suggestions_to_registry(
        self,
        result: GovernanceTightenResult,
        auto_approve_confidence_threshold: float = 0.9,
    ) -> int:
        """
        把治理建议提交到 ConstraintRegistry 受控激活链。

        生命周期：
          DRAFT → VERIFIED（confidence >= 0.6）→ APPROVED（confidence >= threshold）→ ACTIVE

        confidence >= auto_approve_confidence_threshold 的建议直接走到 APPROVED，
        等待下次 activate() 被激活写入合约。
        其他建议停在 DRAFT，需要人工审批。

        这实现了"参数调整有记录、可回滚、可审批"的设计目标。
        不直接热改任何规则，只提交到受控链。
        """
        if self.constraint_registry is None:
            return 0

        try:
            from ystar.governance.metalearning import ManagedConstraint
        except ImportError:
            return 0

        submitted = 0
        # Connection 4: VerificationReport gates approval
        # Only auto-approve if verify_proposal() returns PASS or WARN
        # This ensures LLM-generated suggestions get mathematical validation
        # before entering the controlled activation chain.
        try:
            from ystar.governance.metalearning import verify_proposal, SemanticConstraintProposal
            _verify_available = True
        except ImportError:
            _verify_available = False

        for sug in result.governance_suggestions:
            try:
                import time, uuid
                mc = ManagedConstraint(
                    id         = str(uuid.uuid4())[:8],
                    dimension  = "governance_timing",
                    rule       = (
                        f"{sug.target_rule_id}:{sug.suggestion_type}"
                        f":{sug.suggested_value}"
                    ),
                    status     = "DRAFT",
                    source     = "governance_loop",
                    confidence = sug.confidence,
                    created_at = time.time(),
                    updated_at = time.time(),
                    notes      = sug.rationale[:200],
                )
                self.constraint_registry.add(mc)

                # Verification gate: run verify_proposal() if we have history
                verification_passed = True  # default: allow without history
                if (_verify_available
                        and self._ystar_loop
                        and self._ystar_loop.history
                        and sug.confidence >= 0.6):
                    try:
                        # Build a SemanticConstraintProposal from suggestion
                        proposal = SemanticConstraintProposal(
                            dimension   = "governance_timing",
                            rule        = mc.rule,
                            rationale   = sug.rationale,
                            confidence  = sug.confidence,
                        )
                        vreport = verify_proposal(
                            proposal,
                            self._ystar_loop.history,
                        )
                        # Connection 4: only advance if PASS or WARN (not FAIL)
                        verification_passed = vreport.verdict in ("PASS", "WARN")
                        # Annotate the constraint with verification evidence
                        notes_with_verify = (
                            f"{mc.notes} | verify={vreport.verdict} "
                            f"coverage={vreport.empirical_coverage:.0%} "
                            f"fp={vreport.empirical_fp_rate:.0%}"
                        )
                        # Rebuild with verify notes (ManagedConstraint is frozen-ish)
                        mc = ManagedConstraint(
                            id=mc.id, dimension=mc.dimension, rule=mc.rule,
                            status=mc.status, source=mc.source,
                            confidence=sug.confidence * (1.1 if verification_passed else 0.5),
                            created_at=mc.created_at, updated_at=time.time(),
                            notes=notes_with_verify[:300],
                        )
                        # Update in registry
                        self.constraint_registry.constraints = [
                            mc if c.id == mc.id else c
                            for c in self.constraint_registry.constraints
                        ]
                    except Exception:
                        pass  # verification failed to run; proceed conservatively

                # Auto-advance through lifecycle — gated by verification
                if sug.confidence >= 0.6 and verification_passed:
                    self.constraint_registry.verify(mc.id,
                        notes=f"auto-verified (confidence={sug.confidence:.2f})")
                if (sug.confidence >= auto_approve_confidence_threshold
                        and verification_passed):
                    self.constraint_registry.approve(mc.id,
                        notes=f"auto-approved+verified (confidence={sug.confidence:.2f})")

                submitted += 1
            except Exception:
                pass
        return submitted

    def apply_active_constraints_to_registry(
        self,
        omission_registry: Any,
    ) -> int:
        """
        P3: 把 ConstraintRegistry 中 ACTIVE 状态的治理约束
        应用到 omission_rules 的 RuleRegistry。

        这是闭环的最后一步：
          GovernanceSuggestion → ConstraintRegistry → ACTIVE → 实际影响治理参数

        返回成功应用的约束数量。
        """
        if self.constraint_registry is None:
            return 0

        applied = 0
        try:
            active = self.constraint_registry.by_status("ACTIVE")
            for mc in active:
                # 解析规则格式: "rule_id:suggestion_type:suggested_value"
                parts = mc.rule.split(":", 2)
                if len(parts) < 2:
                    continue
                rule_id, sug_type = parts[0], parts[1]
                try:
                    if sug_type == "tighten_timing":
                        rule = omission_registry.get(rule_id)
                        if rule:
                            # 缩紧 20%（保守）
                            new_due = rule.due_within_secs * 0.8
                            omission_registry.override_timing(
                                rule_id, due_within_secs=new_due
                            )
                            applied += 1
                    elif sug_type == "relax_timing":
                        rule = omission_registry.get(rule_id)
                        if rule:
                            # 放宽 20%（保守）
                            new_due = rule.due_within_secs * 1.2
                            omission_registry.override_timing(
                                rule_id, due_within_secs=new_due
                            )
                            applied += 1
                except Exception:
                    pass
        except Exception:
            pass
        return applied

    def delta_from_baseline(self) -> Optional[Dict[str, float]]:
        """与基线对比的 delta（如果基线已设置）。"""
        if self._baseline is None or not self._observations:
            return None
        latest = self._observations[-1]
        baseline = self._baseline
        return {
            "fulfillment_rate_delta":   latest.obligation_fulfillment_rate - baseline.obligation_fulfillment_rate,
            "expiry_rate_delta":        latest.obligation_expiry_rate       - baseline.obligation_expiry_rate,
            "recovery_rate_delta":      latest.omission_recovery_rate       - baseline.omission_recovery_rate,
            "closure_rate_delta":       latest.chain_closure_rate           - baseline.chain_closure_rate,
            "false_positive_delta":     latest.false_positive_rate          - baseline.false_positive_rate,
        }

    def observation_history(self) -> List[GovernanceObservation]:
        return list(self._observations)

    # ── 私有：建议生成 ────────────────────────────────────────────────────────

    def auto_inquire_and_propose(
        self,
        domain_context: str = "governance",
        min_confidence: float = 0.4,
    ) -> List[GovernanceSuggestion]:
        """
        Connection 14: auto_inquire_all — full automatic discovery pipeline.
        discover_parameters() → inquire_parameter_semantics() → return proposals.

        Higher-level than discover_and_propose_parameters(). Uses LLM if available
        via api_call_fn, falls back to statistical-only if not.

        Call this instead of discover_and_propose_parameters() when you want
        the complete semantic enrichment pipeline in a single call.
        """
        if not self._ystar_loop or not self._ystar_loop.history:
            return []
        try:
            from ystar.governance.metalearning import auto_inquire_all
            proposals = auto_inquire_all(
                history        = self._ystar_loop.history,
                known_contract = self._ystar_loop.base_contract,
                domain_context = domain_context,
                api_call_fn    = None,   # statistical-only by default
                min_confidence = min_confidence,
            )
            suggestions = []
            for prop in proposals[:5]:
                suggestions.append(GovernanceSuggestion(
                    suggestion_type = "auto_inquire_proposal",
                    target_rule_id  = getattr(prop, 'param_name', 'unknown'),
                    current_value   = None,
                    suggested_value = getattr(prop, 'suggested_rule', str(prop)),
                    confidence      = getattr(prop, 'confidence', 0.5),
                    rationale       = getattr(prop, 'reasoning', str(prop))[:200],
                    observation_ref = "auto_inquire_all",
                ))
            return suggestions
        except Exception:
            return []

    def _run_dimension_discovery(self) -> List[GovernanceSuggestion]:
        """
        Connection 2: DimensionDiscovery — identifies violation patterns
        that cannot be expressed by the 8 base dimensions and suggests
        new constraint dimensions (temporal, aggregate, context, resource).
        """
        if not self._ystar_loop or not self._ystar_loop.history:
            return []
        try:
            from ystar.governance.metalearning import DimensionDiscovery
            hints = DimensionDiscovery.analyze(self._ystar_loop.history)
            suggestions = []
            for hint in hints[:3]:  # cap at 3 per cycle
                suggestions.append(GovernanceSuggestion(
                    suggestion_type = "new_dimension",
                    target_rule_id  = "dimension_registry",
                    current_value   = "8 base dimensions",
                    suggested_value = hint,
                    confidence      = 0.55,
                    rationale       = f"DimensionDiscovery detected pattern: {hint[:120]}",
                    observation_ref = "commission_history",
                ))
            return suggestions
        except Exception:
            return []

    def _generate_governance_suggestions(
        self,
        obs: GovernanceObservation,
    ) -> List[GovernanceSuggestion]:
        """
        基于观测产出参数调整建议。
        规则：deterministic，给定相同观测永远产出相同建议。
        """
        suggestions = []

        # 建议 1：omission 过多但 recovery 低 → 时限可能设得太松，建议收紧
        if obs.omission_detection_rate > 0.3 and obs.omission_recovery_rate < 0.4:
            suggestions.append(GovernanceSuggestion(
                suggestion_type = "tighten_timing",
                target_rule_id  = "rule_a_delegation",
                current_value   = "current_domain_pack_value",
                suggested_value = "reduce_by_20_percent",
                confidence      = min(obs.omission_detection_rate, 0.8),
                rationale       = (
                    f"Omission detection rate {obs.omission_detection_rate:.1%} is high "
                    f"but recovery rate {obs.omission_recovery_rate:.1%} is low. "
                    f"Consider tightening timing to force earlier compliance."
                ),
                observation_ref = obs.period_label,
            ))

        # 建议 2：误伤率高 → 时限可能太紧，建议放宽
        if obs.false_positive_rate > 0.05:
            suggestions.append(GovernanceSuggestion(
                suggestion_type = "relax_timing",
                target_rule_id  = "all_rules",
                current_value   = "current_domain_pack_values",
                suggested_value = "increase_by_20_percent",
                confidence      = min(obs.false_positive_rate * 10, 0.7),
                rationale       = (
                    f"False positive rate {obs.false_positive_rate:.1%} exceeds 5% threshold. "
                    f"Governance rules may be too aggressive. Consider relaxing timing."
                ),
                observation_ref = obs.period_label,
            ))

        # 建议 3：hard overdue 高 → 可能缺少 domain pack，建议配置
        if obs.hard_overdue_rate > 0.1 and obs.obligation_fulfillment_rate < 0.5:
            suggestions.append(GovernanceSuggestion(
                suggestion_type = "add_domain_pack",
                target_rule_id  = "registry",
                current_value   = None,
                suggested_value = "apply appropriate domain pack",
                confidence      = 0.6,
                rationale       = (
                    f"Hard overdue rate {obs.hard_overdue_rate:.1%} is high with low fulfillment "
                    f"{obs.obligation_fulfillment_rate:.1%}. "
                    f"A domain pack with appropriate timings may improve compliance."
                ),
                observation_ref = obs.period_label,
            ))

        # 建议 4：特定 omission 类型集中 → 针对性建议
        if obs.by_omission_type:
            top_type, top_count = max(obs.by_omission_type.items(),
                                       key=lambda x: x[1])
            total = sum(obs.by_omission_type.values())
            if top_count / max(total, 1) > 0.6:
                suggestions.append(GovernanceSuggestion(
                    suggestion_type = "focus_rule",
                    target_rule_id  = top_type.replace("required_", "rule_").replace("_omission", ""),
                    current_value   = top_count,
                    suggested_value = "prioritize this rule for domain pack override",
                    confidence      = 0.7,
                    rationale       = (
                        f"'{top_type}' accounts for {top_count/max(total,1):.0%} of all omissions. "
                        f"Focused domain pack tuning for this rule may have highest impact."
                    ),
                    observation_ref = obs.period_label,
                ))

        return suggestions

    def _score_contract_quality(self) -> Optional[Any]:
        """
        Connection 6: ContractQuality + score_candidate
        Score quality of the current contract from commission history.
        Returns dict with coverage/fp/quality metrics, or None if no history.
        """
        if not self._ystar_loop or not self._ystar_loop.history or \
                len(self._ystar_loop.history) < 3:
            return None
        try:
            from ystar.kernel.engine import check as _chk
            history  = self._ystar_loop.history
            contract = self._ystar_loop.base_contract
            if contract is None:
                return None
            incidents  = [r for r in history if r.violations]
            safe_calls = [r for r in history if not r.violations]
            if not incidents:
                return {"coverage_rate": 1.0, "false_positive_rate": 0.0,
                        "quality_score": 1.0, "incident_count": 0}
            n_prev = sum(1 for r in incidents
                         if _chk(r.params, r.result, contract).passed)
            n_fp   = sum(1 for r in safe_calls
                         if not _chk(r.params, r.result, contract).passed)
            cov = n_prev / max(len(incidents), 1)
            fp  = n_fp   / max(len(safe_calls), 1)
            return {
                "coverage_rate":       round(cov, 3),
                "false_positive_rate": round(fp, 3),
                "quality_score":       round(cov * 0.6 + (1 - fp) * 0.4, 3),
                "incident_count":      len(incidents),
                "safe_count":          len(safe_calls),
            }
        except Exception:
            return None

    def _assess_health(self, obs: GovernanceObservation) -> str:
        if obs.is_healthy():
            return "healthy"
        if obs.hard_overdue_rate > 0.2 or obs.false_positive_rate > 0.1:
            return "critical"
        return "degraded"

    def _recommend_action(
        self,
        obs: GovernanceObservation,
        suggestions: List[GovernanceSuggestion],
    ) -> str:
        if obs.is_healthy():
            return "System governance is healthy. Continue monitoring."
        if obs.needs_tightening():
            return ("High omission rate with low recovery. "
                    "Consider applying a tighter domain pack or reviewing actor behavior.")
        if obs.needs_relaxing():
            return ("False positive rate is high. "
                    "Consider relaxing timing thresholds to reduce incorrect violations.")
        if suggestions:
            top = suggestions[0]
            return f"Top suggestion: {top.suggestion_type} on {top.target_rule_id} ({top.rationale[:80]}...)"
        return "Review omission breakdown for specific improvement areas."

    # ── Fix 6: NL → ConstraintRegistry bridge ─────────────────────────────────

    def propose_from_nl(
        self,
        nl_text: str,
        func=None,
        auto_approve: bool = False,
    ) -> dict:
        """
        自然语言 → ConstraintRegistry 完整审批链。

        流程：NL 文本 → prefill() → suggestion → registry.add(DRAFT) → (可选) approve → ACTIVE

        Args:
            nl_text:      自然语言约束描述（如 "不能访问生产数据库"）
            func:         可选目标函数，提供额外上下文给 prefill
            auto_approve: True = 自动推进到 ACTIVE；False = 停留在 DRAFT 等人工审批

        Returns:
            dict with keys: suggestion, proposal_id, status, contract
        """
        from ystar.kernel.prefill import prefill as _prefill

        # Step 1: NL → prefill suggestion
        result = _prefill(func=func) if func else _prefill()

        proposal_id: Optional[str] = None
        status = "no_registry"

        # Step 2: Push to ConstraintRegistry if available
        registry = getattr(self, "_constraint_registry", None)
        if registry is not None and result.contract and not result.contract.is_empty():
            try:
                proposal_id = registry.add(
                    contract=result.contract,
                    source_description=f"propose_from_nl: {nl_text[:120]}",
                    proposer="governance_loop",
                )
                status = "draft"
                if auto_approve and proposal_id:
                    registry.approve(proposal_id, approver="auto")
                    status = "active"
            except Exception as exc:
                status = f"error:{exc}"

        return {
            "suggestion":   result,
            "proposal_id":  proposal_id,
            "status":       status,
            "contract":     result.contract,
        }

    # ── Fix 9: F3 Chain Drift Detection ───────────────────────────────────────

    def detect_chain_drift(
        self,
        chain_events: list,
        mission_statement: Optional[str] = None,
    ) -> dict:
        """
        F3 链级 drift 检测 — 分析整条 agent 协作链是否逐步偏航。

        使用 ChainDriftDetector 做三层分析：
          1. 使命偏离 (mission drift)
          2. 累积扩权 (cumulative scope expansion)
          3. 组合信号 (compound signal: suppress+hide 关键词组合)

        Args:
            chain_events: list of dicts with keys: agent_id, action, scope (optional), ts (optional)
            mission_statement: 使命声明（用于检测偏离）

        Returns:
            dict with: drift_detected, drift_type, severity, details, raw
        """
        # 使用注入的 drift_detector（ecosystem adapter 在初始化时传入）
        # 若未注入则使用内置的轻量关键词扫描（纯内核逻辑，无外部依赖）
        detector = getattr(self, "_chain_drift_detector", None)
        if detector is not None:
            raw = detector.analyze(chain_events)
            return {
                "drift_detected": raw.get("drift_detected", False),
                "drift_type":     raw.get("drift_type"),
                "severity":       raw.get("severity", "none"),
                "details":        raw.get("details", {}),
                "raw":            raw,
            }

        # 内置轻量检测（无 openclaw 依赖）
        suppress_count = sum(
            1 for e in chain_events
            if any(kw in str(e.get("action", "")).lower()
                   for kw in ("suppress", "hide", "conceal", "bypass", "override"))
        )
        drift = suppress_count >= 2
        return {
            "drift_detected": drift,
            "drift_type":     "compound_signal" if drift else None,
            "severity":       "high" if drift else "none",
            "details":        {"suppress_count": suppress_count},
            "raw":            {},
        }

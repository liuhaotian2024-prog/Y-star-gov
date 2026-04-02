# Layer: Bridge
# Direction: Path B -> Bridge -> GovernanceLoop (one-way)
# CANNOT: command Path A, bypass GovernanceLoop, execute governance actions
"""
ystar.governance.experience_bridge — Path B Experience Bridge

Bridge between Path B's external governance experience and Path A's GovernanceLoop.

Design:
    Path B observes external agents and produces CIEU records.
    This bridge aggregates those records into governance-relevant metrics
    that feed into GovernanceLoop via GovernanceObservation.raw_kpis.

Pipeline:
    1. ingest_path_b_cieu(records)     — raw CIEU records from Path B
    2. aggregate_patterns()            — events -> ExternalGovernancePatterns
    3. attribute_gaps()                — patterns -> InternalGovernanceGaps
    4. generate_observation_metrics()  — gaps -> Dict[str, float] (3 KPIs)
    5. feed_governance_loop(gloop)     — inject metrics into GovernanceLoop

This is the formal feedback channel from external governance back to
internal governance. Without it, Path A has no visibility into what
Path B is learning about the outside world.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)


# ── Stage 1 output: aggregated patterns from CIEU records ────────────────────

@dataclass
class ExternalGovernancePattern:
    """
    A recurring pattern discovered in Path B's CIEU records.

    Produced by aggregate_patterns() from raw event data.
    Consumed by attribute_gaps() to infer internal governance weaknesses.
    """
    pattern_id:       str = ""
    pattern_type:     str = ""       # "repeated_violation" / "budget_exhaustion" / "disconnect"
    count:            int = 0        # how many times this pattern occurred
    severity_mean:    float = 0.0    # average severity across occurrences
    affected_agents:  List[str] = field(default_factory=list)
    evidence_refs:    List[str] = field(default_factory=list)  # CIEU record IDs
    confidence:       float = 0.0    # 0-1, higher = more certain this is a real pattern


# ── Stage 2 output: inferred internal governance gaps ────────────────────────

@dataclass
class InternalGovernanceGap:
    """
    An internal governance gap inferred from external governance patterns.

    If Path B keeps seeing the same violation type from multiple external agents,
    that might indicate the internal governance (Path A) failed to produce
    adequate constraints for that class of behavior.
    """
    gap_id:                str = ""
    inferred_module_targets: List[str] = field(default_factory=list)
    inferred_gap_type:     str = ""   # "constraint_missing" / "constraint_weak" / "scope_mismatch"
    supporting_patterns:   List[ExternalGovernancePattern] = field(default_factory=list)
    confidence:            float = 0.0
    rationale:             str = ""


# ── T9: Bridge I/O Schema ────────────────────────────────────────────────────

@dataclass
class BridgeInput:
    """
    Structured input to the ExperienceBridge.

    Collects all data sources that the bridge can ingest, so callers
    know exactly what to provide and the bridge can validate completeness.
    """
    cieu_records:       List[Dict[str, Any]] = field(default_factory=list)
    compliance_results: List[Dict[str, Any]] = field(default_factory=list)
    budget_snapshots:   List[Dict[str, Any]] = field(default_factory=list)
    causal_results:     List[Dict[str, Any]] = field(default_factory=list)
    disconnect_events:  List[Dict[str, Any]] = field(default_factory=list)

    def is_valid(self) -> bool:
        """Validate that at least one data source is populated."""
        return bool(
            self.cieu_records
            or self.compliance_results
            or self.budget_snapshots
            or self.causal_results
            or self.disconnect_events
        )


@dataclass
class BridgeSuggestionCandidate:
    """
    A typed suggestion candidate produced by the ExperienceBridge.

    Each candidate represents a concrete governance action that should be
    considered by GovernanceLoop, originating from Path B gap analysis.
    """
    suggestion_type: str      # "wire", "tighten", "add_domain_pack", "rewire", "review"
    target: str               # module or rule target
    confidence: float         # 0-1
    source_gap: str           # which InternalGovernanceGap produced this
    rationale: str


@dataclass
class BridgeOutput:
    """
    Structured output from the ExperienceBridge.

    Contains the processed metrics, gap candidates, and suggestion candidates
    that feed into GovernanceLoop.
    """
    metrics:              Dict[str, float] = field(default_factory=dict)
    gap_candidates:       List[InternalGovernanceGap] = field(default_factory=list)
    suggestion_candidates: List[BridgeSuggestionCandidate] = field(default_factory=list)


# ── Experience Bridge ────────────────────────────────────────────────────────

class ExperienceBridge:
    """
    Bridge between Path B's external governance experience and
    Path A's GovernanceLoop.

    Usage:
        bridge = ExperienceBridge()
        bridge.ingest_path_b_cieu(cieu_records)
        bridge.aggregate_patterns()
        bridge.attribute_gaps()
        metrics = bridge.generate_observation_metrics()
        bridge.feed_governance_loop(gloop)
    """

    def __init__(self) -> None:
        self._raw_records: List[Dict[str, Any]] = []
        self._patterns: List[ExternalGovernancePattern] = []
        self._gaps: List[InternalGovernanceGap] = []

    # ── T9: Structured ingest with validation ───────────────────────────────

    def ingest(self, bridge_input: "BridgeInput") -> None:
        """
        T9: Ingest structured BridgeInput with validation.

        Raises ValueError if input is not valid (no data sources populated).
        Merges all data sources into _raw_records for downstream processing.
        """
        if not isinstance(bridge_input, BridgeInput):
            raise TypeError(f"Expected BridgeInput, got {type(bridge_input).__name__}")
        if not bridge_input.is_valid():
            raise ValueError("BridgeInput has no data sources populated")

        # Ingest CIEU records (primary source)
        self.ingest_path_b_cieu(bridge_input.cieu_records)

        # Compliance results → synthetic CIEU records
        for cr in bridge_input.compliance_results:
            self._raw_records.append({
                "func_name": "path_b.compliance_result",
                "path_b_event": "COMPLIANCE_RESULT",
                "params": cr,
                "violations": [],
                "source": "path_b_agent",
            })

        # Budget snapshots
        for bs in bridge_input.budget_snapshots:
            self._raw_records.append({
                "func_name": "path_b.budget_snapshot",
                "path_b_event": "BUDGET_SNAPSHOT",
                "params": bs,
                "violations": [],
                "source": "path_b_agent",
            })

        # Disconnect events
        for de in bridge_input.disconnect_events:
            self._raw_records.append({
                "func_name": "path_b.disconnect",
                "path_b_event": "EXTERNAL_AGENT_DISCONNECTED",
                "params": de,
                "violations": [],
                "source": "path_b_agent",
            })

    def generate_output(self) -> "BridgeOutput":
        """T9: Produce a structured BridgeOutput from current state.

        N5: suggestion_candidates are now generated from InternalGovernanceGap
        objects. Each high-confidence gap produces at least one GovernanceSuggestion
        draft so that GovernanceLoop can act on bridge findings automatically.
        """
        return BridgeOutput(
            metrics=self.generate_observation_metrics(),
            gap_candidates=list(self._gaps),
            suggestion_candidates=self._generate_suggestion_candidates(),
        )

    def _generate_suggestion_candidates(self) -> "List[BridgeSuggestionCandidate]":
        """N5: Generate BridgeSuggestionCandidate objects from InternalGovernanceGap objects.

        At least 1 suggestion per high-confidence gap (confidence >= 0.5).
        Returns typed BridgeSuggestionCandidate objects instead of raw dicts.
        """
        suggestions: List[BridgeSuggestionCandidate] = []
        for gap in self._gaps:
            if gap.confidence < 0.3:
                continue  # Too uncertain to suggest anything

            # Map gap type to suggestion type and target
            if gap.inferred_gap_type == "constraint_missing":
                stype = "wire"
                target = gap.inferred_module_targets[0] if gap.inferred_module_targets else "constraint_derivation"
            elif gap.inferred_gap_type == "constraint_weak":
                stype = "tighten"
                target = "constraint_derivation"
            elif gap.inferred_gap_type == "scope_mismatch":
                stype = "rewire"
                target = "observation_schema"
            else:
                stype = "review"
                target = gap.gap_id

            suggestions.append(BridgeSuggestionCandidate(
                suggestion_type=stype,
                target=target,
                confidence=gap.confidence,
                source_gap=gap.gap_id,
                rationale=gap.rationale[:200] if gap.rationale else "",
            ))
        return suggestions

    # ── Stage 0: ingest raw CIEU records from Path B ─────────────────────────

    def ingest_path_b_cieu(self, cieu_records: List[Dict[str, Any]]) -> None:
        """
        Ingest Path B's CIEU records.

        Each record is a dict with at minimum:
            func_name:     str (e.g. "path_b.constraint_applied")
            path_b_event:  str (event type)
            params:        dict (cycle details)
            violations:    list
            source:        "path_b_agent"
        """
        for record in cieu_records:
            if not isinstance(record, dict):
                continue
            # Only accept records that came from Path B
            if record.get("source") == "path_b_agent" or "path_b" in record.get("func_name", ""):
                self._raw_records.append(record)

    # ── Stage 1: events -> patterns ──────────────────────────────────────────

    def aggregate_patterns(self) -> List[ExternalGovernancePattern]:
        """
        Aggregate raw CIEU records into ExternalGovernancePatterns.

        Groups by event type and agent, counting occurrences and
        computing mean severity.
        """
        self._patterns = []

        # Group by (event_type, agent_id)
        groups: Dict[str, Dict[str, Any]] = {}
        for record in self._raw_records:
            event = record.get("path_b_event", record.get("func_name", "unknown"))
            params = record.get("params", {})
            agent_id = params.get("agent_id", "unknown")
            key = f"{event}:{agent_id}"

            if key not in groups:
                groups[key] = {
                    "event": event,
                    "agents": set(),
                    "count": 0,
                    "severity_sum": 0.0,
                    "refs": [],
                }
            g = groups[key]
            g["agents"].add(agent_id)
            g["count"] += 1
            # Extract severity from violations list
            violations = record.get("violations", [])
            if violations:
                g["severity_sum"] += len(violations) * 0.7  # default severity per violation
            g["refs"].append(params.get("cycle_id", ""))

        # Convert groups to patterns
        for i, (key, g) in enumerate(groups.items()):
            count = g["count"]
            severity_mean = (g["severity_sum"] / count) if count > 0 else 0.0
            # Confidence increases with count, capped at 0.95
            confidence = min(0.95, 0.2 + (count * 0.1))

            pattern = ExternalGovernancePattern(
                pattern_id=f"pat_{i:04d}",
                pattern_type=self._classify_event(g["event"]),
                count=count,
                severity_mean=severity_mean,
                affected_agents=list(g["agents"]),
                evidence_refs=[r for r in g["refs"] if r],
                confidence=confidence,
            )
            self._patterns.append(pattern)

        # ── T10: Enhanced pattern detection ──────────────────────────────────

        # Repeated violation detection: flag agents with 3+ violations
        for pattern in self._patterns:
            if pattern.pattern_type == "repeated_violation" and pattern.count >= 3:
                pattern.confidence = min(0.98, pattern.confidence + 0.1)

        # Ineffective constraint detection: CONSTRAINT_APPLIED followed by
        # more violations from the same agent
        applied_agents: set = set()
        violation_after_constraint: Dict[str, int] = {}
        for record in self._raw_records:
            event = record.get("path_b_event", "")
            agent_id = record.get("params", {}).get("agent_id", "unknown")
            if "CONSTRAINT_APPLIED" in event:
                applied_agents.add(agent_id)
            elif agent_id in applied_agents and record.get("violations"):
                violation_after_constraint[agent_id] = (
                    violation_after_constraint.get(agent_id, 0) + 1
                )

        for agent_id, count in violation_after_constraint.items():
            if count >= 2:
                self._patterns.append(ExternalGovernancePattern(
                    pattern_id=f"pat_ineff_{agent_id[:6]}",
                    pattern_type="ineffective_constraint",
                    count=count,
                    severity_mean=0.7,
                    affected_agents=[agent_id],
                    evidence_refs=[],
                    confidence=min(0.95, 0.3 + count * 0.15),
                ))

        # Causal effectiveness summary: ratio of successful constraints
        total_applied = sum(
            1 for r in self._raw_records
            if "CONSTRAINT_APPLIED" in r.get("path_b_event", "")
        )
        total_compliant = sum(
            1 for r in self._raw_records
            if "COMPLIANCE_RESULT" in r.get("path_b_event", "")
        )
        if total_applied > 0:
            effectiveness = total_compliant / total_applied
            self._patterns.append(ExternalGovernancePattern(
                pattern_id="pat_causal_effectiveness",
                pattern_type="causal_effectiveness_summary",
                count=total_applied,
                severity_mean=1.0 - effectiveness,
                affected_agents=[],
                evidence_refs=[],
                confidence=min(0.95, 0.3 + total_applied * 0.1),
            ))

        return self._patterns

    @staticmethod
    def _classify_event(event: str) -> str:
        """Classify a Path B event into a pattern type."""
        event_lower = event.lower()
        if "disconnect" in event_lower:
            return "disconnect"
        if "no_constraint" in event_lower:
            return "constraint_gap"
        if "self_violation" in event_lower:
            return "path_b_self_violation"
        if "constraint_applied" in event_lower:
            return "repeated_violation"
        return "other"

    # ── Stage 2: patterns -> internal governance gaps ────────────────────────

    def attribute_gaps(self) -> List[InternalGovernanceGap]:
        """
        Attribute external governance patterns to internal governance gaps.

        Logic:
        - repeated_violation across multiple agents -> constraint_missing
        - disconnect events -> constraint_weak (applied but insufficient)
        - constraint_gap -> scope_mismatch (observation didn't map to constraint)
        """
        self._gaps = []

        for i, pattern in enumerate(self._patterns):
            if pattern.confidence < 0.3:
                continue  # Too uncertain

            gap_type = "constraint_missing"
            rationale = ""

            if pattern.pattern_type == "repeated_violation":
                gap_type = "constraint_missing"
                rationale = (
                    f"Pattern '{pattern.pattern_id}' shows {pattern.count} "
                    f"repeated violations across {len(pattern.affected_agents)} agent(s). "
                    f"Internal governance may be missing a constraint for this class."
                )
            elif pattern.pattern_type == "disconnect":
                gap_type = "constraint_weak"
                rationale = (
                    f"Pattern '{pattern.pattern_id}' shows {pattern.count} disconnects. "
                    f"Existing constraints were insufficient to prevent escalation."
                )
            elif pattern.pattern_type == "constraint_gap":
                gap_type = "scope_mismatch"
                rationale = (
                    f"Pattern '{pattern.pattern_id}' shows {pattern.count} cases where "
                    f"no constraint could be derived from observation. "
                    f"The observation schema may not cover this violation class."
                )
            else:
                rationale = (
                    f"Pattern '{pattern.pattern_id}' ({pattern.pattern_type}) "
                    f"occurred {pattern.count} times."
                )

            gap = InternalGovernanceGap(
                gap_id=f"gap_{i:04d}",
                inferred_module_targets=pattern.affected_agents,
                inferred_gap_type=gap_type,
                supporting_patterns=[pattern],
                confidence=pattern.confidence * 0.9,  # Slight discount for inference
                rationale=rationale,
            )
            self._gaps.append(gap)

        return self._gaps

    # ── Stage 3: gaps -> observation metrics ─────────────────────────────────

    def generate_observation_metrics(self) -> Dict[str, float]:
        """
        Convert internal governance gaps into 3 KPIs that GovernanceLoop understands.

        Returns:
            external_constraint_effectiveness_rate (0-1):
                How effective are Path B's constraints? Higher = better.
                1.0 = no gaps found, 0.0 = every pattern indicates a gap.

            external_budget_exhaustion_rate (0-1):
                How often does Path B run out of constraint budget?
                Higher = more budget pressure = Path B is over-constraining.

            external_disconnect_pressure (0-1):
                How often does Path B escalate to disconnect?
                Higher = more disconnects = constraints aren't working.
        """
        if not self._patterns:
            return {
                "external_constraint_effectiveness_rate": 1.0,
                "external_budget_exhaustion_rate": 0.0,
                "external_disconnect_pressure": 0.0,
            }

        total_patterns = len(self._patterns)
        total_events = sum(p.count for p in self._patterns)

        # Effectiveness: proportion of patterns that did NOT produce gaps
        gap_pattern_ids = set()
        for gap in self._gaps:
            for p in gap.supporting_patterns:
                gap_pattern_ids.add(p.pattern_id)
        patterns_without_gaps = total_patterns - len(gap_pattern_ids)
        effectiveness = patterns_without_gaps / total_patterns if total_patterns > 0 else 1.0

        # Budget exhaustion: proportion of events from constraint_gap patterns
        budget_events = sum(
            p.count for p in self._patterns
            if p.pattern_type == "constraint_gap"
        )
        budget_rate = budget_events / total_events if total_events > 0 else 0.0

        # Disconnect pressure: proportion of events from disconnect patterns
        disconnect_events = sum(
            p.count for p in self._patterns
            if p.pattern_type == "disconnect"
        )
        disconnect_rate = disconnect_events / total_events if total_events > 0 else 0.0

        return {
            "external_constraint_effectiveness_rate": max(0.0, min(1.0, effectiveness)),
            "external_budget_exhaustion_rate": max(0.0, min(1.0, budget_rate)),
            "external_disconnect_pressure": max(0.0, min(1.0, disconnect_rate)),
        }

    # ── Stage 4: inject metrics into GovernanceLoop ──────────────────────────

    def feed_governance_loop(self, gloop: Any) -> None:
        """
        Inject Path B experience metrics into GovernanceLoop.

        Reads the latest GovernanceObservation from the loop and
        merges our 3 KPIs into its raw_kpis dict.

        Args:
            gloop: GovernanceLoop instance (from ystar.governance.governance_loop)
        """
        metrics = self.generate_observation_metrics()

        # Access the loop's observation list and inject into raw_kpis
        observations = getattr(gloop, "_observations", [])
        if observations:
            latest = observations[-1]
            if hasattr(latest, "raw_kpis"):
                latest.raw_kpis.update(metrics)
        else:
            # No observations yet — create a minimal one with our metrics
            try:
                from ystar.governance.governance_loop import GovernanceObservation
                obs = GovernanceObservation(
                    period_label="experience_bridge_injection",
                    raw_kpis=dict(metrics),
                )
                observations.append(obs)
            except ImportError:
                # Optional import — CausalObservation not available
                pass

"""
Y*gov Causal Chain Analyzer
Inspired by K9Audit's causal_analyzer.py (AGPL-3.0) — logic rewritten for MIT license compliance.

Traces causal chains in Y*gov CIEU event logs using temporal and semantic correlation.
"""
import sqlite3
import json
from typing import Dict, List, Optional, Any
from pathlib import Path


class CausalChainAnalyzer:
    """
    Analyzes CIEU event logs to build causal chains.

    Uses:
    - Temporal edges: events in same session ordered by seq_global
    - Semantic edges: agent_id correlation + task_description similarity
    - Decision edges: DENY/VIOLATION events and their preceding/following context
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = ".ystar_cieu.db"
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"CIEU database not found: {self.db_path}")
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def trace_event(self, event_id: str, lookback: int = 10, lookahead: int = 10) -> Dict[str, Any]:
        """
        Trace causal chain for a given event.

        Args:
            event_id: Target event ID
            lookback: Max predecessors to fetch
            lookahead: Max successors to fetch

        Returns:
            {
                "event": {...},
                "predecessors": [...],
                "successors": [...],
                "metadata": {"chain_length": N, "violations_in_chain": N}
            }
        """
        # Get target event
        cursor = self.conn.execute(
            "SELECT * FROM cieu_events WHERE event_id = ?",
            (event_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"error": f"Event {event_id} not found"}

        target_event = dict(row)
        session_id = target_event["session_id"]
        agent_id = target_event["agent_id"]
        seq_global = target_event["seq_global"]

        # Find predecessors (same session, earlier seq_global)
        predecessors = self._find_predecessors(session_id, agent_id, seq_global, lookback)

        # Find successors (same session, later seq_global)
        successors = self._find_successors(session_id, agent_id, seq_global, lookahead)

        # Metadata
        all_events = predecessors + [target_event] + successors
        violations_count = sum(1 for e in all_events if e.get("passed") == 0)

        return {
            "event": target_event,
            "predecessors": predecessors,
            "successors": successors,
            "metadata": {
                "chain_length": len(all_events),
                "violations_in_chain": violations_count,
                "session_id": session_id,
                "agent_id": agent_id,
            }
        }

    def _find_predecessors(
        self,
        session_id: str,
        agent_id: str,
        seq_global: int,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Find preceding events in causal chain."""
        cursor = self.conn.execute(
            """
            SELECT * FROM cieu_events
            WHERE session_id = ?
              AND seq_global < ?
            ORDER BY seq_global DESC
            LIMIT ?
            """,
            (session_id, seq_global, limit)
        )
        events = [dict(row) for row in cursor.fetchall()]
        # Reverse to chronological order
        return list(reversed(events))

    def _find_successors(
        self,
        session_id: str,
        agent_id: str,
        seq_global: int,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Find succeeding events in causal chain."""
        cursor = self.conn.execute(
            """
            SELECT * FROM cieu_events
            WHERE session_id = ?
              AND seq_global > ?
            ORDER BY seq_global ASC
            LIMIT ?
            """,
            (session_id, seq_global, limit)
        )
        return [dict(row) for row in cursor.fetchall()]

    def find_root_causes(self, event_id: str) -> List[Dict[str, Any]]:
        """
        Find likely root causes of a violation/denial event.

        Returns list of candidate root causes ranked by confidence.
        """
        chain = self.trace_event(event_id, lookback=20, lookahead=5)
        if "error" in chain:
            return []

        target_event = chain["event"]
        predecessors = chain["predecessors"]

        # Target must be a violation/denial
        if target_event.get("passed") != 0:
            return [{"reasoning": "Target event is not a violation/denial", "confidence": 0.0}]

        root_causes = []

        # Strategy 1: Earliest violation in chain
        violations_in_chain = [
            e for e in predecessors
            if e.get("passed") == 0
        ]
        if violations_in_chain:
            earliest = violations_in_chain[0]  # Already chronological
            root_causes.append({
                "type": "earliest_violation",
                "event_id": earliest["event_id"],
                "seq_global": earliest["seq_global"],
                "event_type": earliest["event_type"],
                "agent_id": earliest["agent_id"],
                "decision": earliest["decision"],
                "confidence": 0.9,
                "reasoning": "First violation in causal chain"
            })

        # Strategy 2: High-severity violations (violations field has severity)
        high_severity = []
        for e in violations_in_chain:
            violations_json = e.get("violations", "[]")
            try:
                violations = json.loads(violations_json) if violations_json else []
                if any(v.get("severity", 0) >= 0.7 for v in violations):
                    high_severity.append(e)
            except json.JSONDecodeError:
                continue

        for hv in high_severity[:3]:
            root_causes.append({
                "type": "high_severity_violation",
                "event_id": hv["event_id"],
                "seq_global": hv["seq_global"],
                "event_type": hv["event_type"],
                "agent_id": hv["agent_id"],
                "decision": hv["decision"],
                "confidence": 0.85,
                "reasoning": "High-severity violation in chain"
            })

        # Strategy 3: Agent context switches (different agent_id before target)
        agent_switches = [
            e for e in predecessors
            if e["agent_id"] != target_event["agent_id"]
        ]
        if agent_switches and not root_causes:
            last_switch = agent_switches[-1]
            root_causes.append({
                "type": "agent_context_switch",
                "event_id": last_switch["event_id"],
                "seq_global": last_switch["seq_global"],
                "event_type": last_switch["event_type"],
                "agent_id": last_switch["agent_id"],
                "decision": last_switch.get("decision"),
                "confidence": 0.6,
                "reasoning": f"Last event from different agent ({last_switch['agent_id']}) before violation"
            })

        # Strategy 4: Chain origin (if no violations found)
        if not root_causes and predecessors:
            origin = predecessors[0]
            root_causes.append({
                "type": "chain_origin",
                "event_id": origin["event_id"],
                "seq_global": origin["seq_global"],
                "event_type": origin["event_type"],
                "agent_id": origin["agent_id"],
                "decision": origin.get("decision"),
                "confidence": 0.5,
                "reasoning": "Origin of causal chain (no violations detected)"
            })

        # Sort by confidence descending
        root_causes.sort(key=lambda rc: -rc["confidence"])
        return root_causes

    def visualize_chain(self, event_id: str) -> str:
        """
        Return human-readable visualization of causal chain.
        """
        chain = self.trace_event(event_id, lookback=10, lookahead=10)
        if "error" in chain:
            return f"Error: {chain['error']}"

        lines = []
        lines.append("=" * 80)
        lines.append("CAUSAL CHAIN ANALYSIS")
        lines.append("=" * 80)

        target = chain["event"]
        lines.append(f"\nTARGET EVENT: {target['event_id']}")
        lines.append(f"  Type: {target['event_type']}")
        lines.append(f"  Agent: {target['agent_id']}")
        lines.append(f"  Decision: {target['decision']}")
        lines.append(f"  Passed: {target['passed']}")
        lines.append(f"  Session: {target['session_id']}")

        lines.append(f"\nPREDECESSORS ({len(chain['predecessors'])} events):")
        for i, e in enumerate(chain["predecessors"], 1):
            status = "✓" if e.get("passed") == 1 else "✗"
            lines.append(
                f"  {i}. {status} [{e['event_type']}] {e['agent_id']} | {e['decision']} | seq={e['seq_global']}"
            )

        lines.append(f"\nSUCCESSORS ({len(chain['successors'])} events):")
        for i, e in enumerate(chain["successors"], 1):
            status = "✓" if e.get("passed") == 1 else "✗"
            lines.append(
                f"  {i}. {status} [{e['event_type']}] {e['agent_id']} | {e['decision']} | seq={e['seq_global']}"
            )

        lines.append(f"\nMETADATA:")
        lines.append(f"  Chain length: {chain['metadata']['chain_length']}")
        lines.append(f"  Violations in chain: {chain['metadata']['violations_in_chain']}")

        # Root causes
        root_causes = self.find_root_causes(event_id)
        if root_causes:
            lines.append(f"\nROOT CAUSES ({len(root_causes)}):")
            for i, rc in enumerate(root_causes, 1):
                lines.append(
                    f"  {i}. [{rc['type']}] {rc.get('event_id', 'N/A')} | "
                    f"confidence={rc['confidence']:.0%} | {rc['reasoning']}"
                )

        lines.append("=" * 80)
        return "\n".join(lines)

    def close(self):
        """Close database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

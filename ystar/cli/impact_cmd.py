# ystar/cli/impact_cmd.py — ystar check-impact command
"""
Impact analysis command for session JSON files.

Analyzes governance decisions and their downstream effects:
- P0 risks (blocking issues)
- Downstream impact (what's affected)
- CIEU violations
- Omission violations
"""
import json
import pathlib
import sys
from typing import Dict, List, Any, Tuple


def _cmd_check_impact(args: list) -> None:
    """
    ystar check-impact <session.json>

    Parse session.json and analyze governance impact:
    - P0 risks (blocking issues)
    - Downstream impact (affected agents/operations)
    - CIEU violations
    - Omission violations
    """
    if not args:
        print("Usage: ystar check-impact <session.json>")
        sys.exit(1)

    session_file = pathlib.Path(args[0])
    if not session_file.exists():
        print(f"Error: Session file not found: {session_file}")
        sys.exit(1)

    try:
        session_data = json.loads(session_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: Failed to parse session file: {e}")
        sys.exit(1)

    # Analyze impact
    analysis = _analyze_session_impact(session_data)

    # Render report
    _render_impact_report(session_file.name, analysis)


def _analyze_session_impact(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze session data for governance impact.

    Returns:
        {
            "p0_risks": [(type, description)],
            "downstream_impact": {
                "blocks": [operation],
                "affects": [agent_id]
            },
            "cieu_events": {
                "total": int,
                "allow": int,
                "deny": int,
                "escalate": int
            },
            "omissions": {
                "violations": int,
                "pending": int,
                "overdue": int
            }
        }
    """
    analysis = {
        "p0_risks": [],
        "downstream_impact": {
            "blocks": [],
            "affects": set()
        },
        "cieu_events": {
            "total": 0,
            "allow": 0,
            "deny": 0,
            "escalate": 0
        },
        "omissions": {
            "violations": 0,
            "pending": 0,
            "overdue": 0
        }
    }

    # Extract CIEU events from session
    cieu_events = session_data.get("cieu_events", [])
    analysis["cieu_events"]["total"] = len(cieu_events)

    for event in cieu_events:
        decision = event.get("decision", "allow")
        analysis["cieu_events"][decision] = analysis["cieu_events"].get(decision, 0) + 1

        # Check for P0 risks
        if decision == "deny":
            tool_name = event.get("tool_name", "Unknown")
            file_path = event.get("file_path", event.get("tool_input", {}).get("file_path", ""))
            analysis["p0_risks"].append(
                ("CIEU-DENY", f"Tool call blocked: {tool_name}({file_path})")
            )

        # Track affected agents
        agent_id = event.get("agent_id", "unknown")
        if agent_id:
            analysis["downstream_impact"]["affects"].add(agent_id)

    # Extract omission data
    obligations = session_data.get("obligations", [])
    for obl in obligations:
        status = obl.get("status", "pending")
        if status == "violated":
            analysis["omissions"]["violations"] += 1
            obl_type = obl.get("obligation_type", "unknown")
            analysis["p0_risks"].append(
                ("OMISSION", f"Obligation overdue: {obl_type}")
            )
        elif status == "pending":
            analysis["omissions"]["pending"] += 1

            # Check if it's blocking
            is_overdue = obl.get("is_overdue", False)
            if is_overdue:
                analysis["omissions"]["overdue"] += 1
                analysis["downstream_impact"]["blocks"].append(
                    f"Pending obligation: {obl.get('obligation_type', 'unknown')}"
                )

    # Convert set to list for JSON serialization
    analysis["downstream_impact"]["affects"] = list(analysis["downstream_impact"]["affects"])

    return analysis


def _render_impact_report(filename: str, analysis: Dict[str, Any]) -> None:
    """Render impact analysis report to console."""
    print()
    print(f"  Impact Analysis: {filename}")
    print("  " + "━" * 60)
    print()

    # P0 Risks
    p0_risks = analysis["p0_risks"]
    print(f"  P0 Risks: {len(p0_risks)} found")
    if p0_risks:
        for risk_type, description in p0_risks[:5]:  # Show max 5
            print(f"    - [{risk_type}] {description}")
        if len(p0_risks) > 5:
            print(f"    ... and {len(p0_risks) - 5} more")
    print()

    # Downstream Impact
    impact = analysis["downstream_impact"]
    print("  Downstream Impact:")
    if impact["blocks"]:
        print(f"    - Blocks: {len(impact['blocks'])} operations")
        for block in impact["blocks"][:3]:
            print(f"        • {block}")
    else:
        print("    - Blocks: None")

    affects = impact["affects"]
    if affects:
        print(f"    - Affects: {len(affects)} agents ({', '.join(affects[:5])})")
    else:
        print("    - Affects: No agents identified")
    print()

    # CIEU Events
    cieu = analysis["cieu_events"]
    print(f"  CIEU Events: {cieu['total']} total")
    if cieu['total'] > 0:
        print(f"    - Allow:    {cieu.get('allow', 0)}")
        print(f"    - Deny:     {cieu.get('deny', 0)}")
        print(f"    - Escalate: {cieu.get('escalate', 0)}")
        deny_rate = cieu.get('deny', 0) / cieu['total'] if cieu['total'] > 0 else 0
        print(f"    - Deny Rate: {deny_rate:.1%}")
    print()

    # Omissions
    omissions = analysis["omissions"]
    print(f"  Omissions:")
    print(f"    - Violations: {omissions['violations']}")
    print(f"    - Pending:    {omissions['pending']}")
    print(f"    - Overdue:    {omissions['overdue']}")
    print()

    # Overall assessment
    print("  " + "━" * 60)
    if len(p0_risks) > 0:
        print("  Status: CRITICAL — P0 risks detected, immediate attention required")
        sys.exit(1)
    elif omissions["overdue"] > 0:
        print("  Status: WARNING — Overdue obligations, review required")
        sys.exit(1)
    else:
        print("  Status: OK — No critical issues detected")
        sys.exit(0)

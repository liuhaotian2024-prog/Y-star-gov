import os
# Layer: Foundation
"""
ystar.governance.obligation_remediation — Obligation-specific Remediation Payloads
===================================================================================
v0.49.0 (AMENDMENT-012 extension)

When obligations become overdue, InterventionEngine/OmissionEngine returns structured
remediation that tells agents EXACTLY what to do — not generic "fulfill obligation".

Each of the 9 obligation types from contract.obligation_timing gets specific:
  - wrong_action: What the agent did that triggered overdue
  - correct_steps: Executable commands/code to fulfill the obligation
  - skill_ref: Pointer to knowledge/{role}/skills/*.md for full guidance
  - lesson_ref: Incident that motivated this obligation (if any)
  - rule_name: obligation_timing key
  - rule_context: Why this obligation exists (1-sentence)

Design Lesson:
  governance_self_deadlock_20260413.md revealed that deny-as-teaching for behavior
  rules shipped with 10 remediation entries, but the 9 obligation types had NONE.
  Result: when directive_acknowledgement went overdue, CEO got blocked with generic
  "overdue 187s" but no path to fix → 35-minute hard lock until Board manual emit.

This module closes that gap: every obligation type now has executable remediation.
"""
from typing import Dict, Optional

from ystar.session import Remediation


# ── 9 Obligation Type Remediations ─────────────────────────────────────────────

OBLIGATION_REMEDIATION_MAP: Dict[str, Remediation] = {
    # 1. directive_acknowledgement (120s SLA)
    "directive_acknowledgement": Remediation(
        wrong_action="Responded to Board message after 120s SLA expired",
        correct_steps=[
            "# If you just responded but hook blocked: wait 5-10s for heartbeat auto-ack to process",
            "# If urgent and heartbeat hasn't caught up:",
            'python3 -c "import sys; sys.path.insert(0, \\os.path.expanduser("~/.openclaw/workspace/ystar-company\\")); from tools.cieu.ygva.governor import emit_event; emit_event(\\"DIRECTIVE_ACKNOWLEDGED\\", {\\"source\\": \\"ceo\\", \\"directive_id\\": \\"<Board_message_id>\\"})"',
            "# If daemon still blocking after emit: pkill -f _hook_daemon.py (LaunchAgent will auto-restart with fresh state)",
        ],
        skill_ref="knowledge/ceo/skills/respond_within_sla.md",
        lesson_ref="knowledge/ceo/lessons/governance_self_deadlock_20260413.md",
        rule_name="directive_acknowledgement",
        rule_context="Board expects timely response; >120s silence triggers governance self-lock to prevent runaway autonomy.",
    ),

    # 2. intent_declaration (300s SLA)
    "intent_declaration": Remediation(
        wrong_action="Modified governance/protected paths without declaring intent first",
        correct_steps=[
            "# Run intent declaration before touching protected paths:",
            "python3 scripts/record_intent.py --file <protected_file> --intent '<1-sentence intent>' --duration 4",
            "# This creates 4-hour intent window; then retry your Edit/Write",
            "# Protected paths: governance/, agents/, README.md, scripts/record_intent.py, scripts/check_intents.py",
        ],
        skill_ref="knowledge/secretary/skills/intent_guard_workflow.md",
        lesson_ref=None,  # Constitutional constraint
        rule_name="intent_declaration",
        rule_context="Prevents accidental corruption of governance charter during refactoring; requires conscious declaration before modifying protected paths.",
    ),

    # 3. progress_update (1800s SLA — 30 min)
    "progress_update": Remediation(
        wrong_action="No progress update sent within 30 minutes of task acknowledgement",
        correct_steps=[
            "# Write a 1-3 sentence status update to appropriate channel:",
            "# For CEO tasks: update DIRECTIVE_TRACKER.md with task progress",
            "# For engineering tasks: add progress note to reports/autonomous/<agent>_<date>.md",
            "# For multi-agent tasks: post update in task handoff file (memory/session_handoff.md)",
            '# Emit progress_update event: emit_event("PROGRESS_UPDATE", {"task_id": "<id>", "status": "<status>", "blockers": []})',
        ],
        skill_ref="knowledge/ceo/skills/progress_tracking.md",
        lesson_ref=None,
        rule_name="progress_update",
        rule_context="Prevents silent failures; ensures Board and peer agents know task is moving forward or blocked.",
    ),

    # 4. task_completion_report (3600s SLA — 1 hour)
    "task_completion_report": Remediation(
        wrong_action="Task marked complete but no completion report written within 1 hour",
        correct_steps=[
            "# Write completion report with outcome + artifacts:",
            "# For CEO: update DIRECTIVE_TRACKER.md with completion status + link to deliverable",
            "# For CTO/engineers: write reports/autonomous/<agent>_<date>.md with PR/commit links",
            "# For CMO: write content/ artifact + add entry to marketing/content_calendar.md",
            "# For CSO: update sales/pipeline.md with outcome",
            '# Emit completion event: emit_event("TASK_COMPLETED", {"task_id": "<id>", "outcome": "<outcome>", "artifacts": ["<path1>", "<path2>"]})',
        ],
        skill_ref="knowledge/ceo/skills/task_closure_protocol.md",
        lesson_ref=None,
        rule_name="task_completion_report",
        rule_context="Ensures deliverables are documented and findable; prevents 'ghost work' where tasks finish but outcomes are lost.",
    ),

    # 5. knowledge_update (21600s SLA — 6 hours)
    "knowledge_update": Remediation(
        wrong_action="Research/learning occurred (WebSearch/WebFetch/Read external) but no knowledge/ update within 6 hours",
        correct_steps=[
            "# Write findings to knowledge/<role>/gaps/ or knowledge/<role>/role_definition/:",
            "# If filled a gap: update knowledge/<role>/gaps/<topic>.md with findings + sources",
            "# If learned new skill: create knowledge/<role>/skills/<skill_name>.md",
            "# If discovered pattern: create knowledge/<role>/lessons/<incident_name>.md",
            "# Always include: date, source URLs, key takeaways, implications for role",
        ],
        skill_ref="knowledge/ceo/skills/knowledge_hygiene.md",
        lesson_ref=None,
        rule_name="knowledge_update",
        rule_context="Research without documentation = wasted work; ensures team memory persists across sessions.",
    ),

    # 6. theory_library_daily (86400s SLA — 24 hours)
    "theory_library_daily": Remediation(
        wrong_action="Theory library (knowledge/theory/) not updated in 24 hours despite active research",
        correct_steps=[
            "# Review today's CIEU logs for new patterns/theories:",
            "grep THEORY_DISCOVERED .ystar_cieu.db -A 5 | tail -50",
            "# Write new theory entry to knowledge/theory/<domain>/<theory_name>.md:",
            "# Format: hypothesis, evidence, confidence, falsification criteria, related theories",
            "# If no new theories today: write knowledge/theory/daily_review_<date>.md with 'no new theories' note",
        ],
        skill_ref="knowledge/ceo/skills/theory_management.md",
        lesson_ref=None,
        rule_name="theory_library_daily",
        rule_context="Prevents theoretical drift; ensures agent reasoning models stay current with observed reality.",
    ),

    # 7. autonomous_daily_report (86400s SLA — 24 hours)
    "autonomous_daily_report": Remediation(
        wrong_action="Agent has not written daily autonomous report in 24 hours",
        correct_steps=[
            "# Write daily report to reports/autonomous/<agent>_<YYYY-MM-DD>.md:",
            "# Required sections:",
            "#   - Tasks completed (with outcome + artifacts)",
            "#   - Blockers encountered (with escalation status)",
            "#   - Knowledge gaps discovered (with follow-up plan)",
            "#   - Coordination with other agents (who + what)",
            "#   - CIEU audit summary (violations + remediations)",
            "# Report triggers nightly knowledge consolidation + next-day planning",
        ],
        skill_ref="knowledge/ceo/skills/autonomous_reporting.md",
        lesson_ref=None,
        rule_name="autonomous_daily_report",
        rule_context="Daily rhythm for autonomous agents; ensures accountability even when Board is offline.",
    ),

    # 8. gemma_session_daily (86400s SLA — 24 hours)
    "gemma_session_daily": Remediation(
        wrong_action="No Gemma learning session run in 24 hours despite new CIEU events",
        correct_steps=[
            "# Run daily Gemma learning session:",
            "python3 scripts/local_learn.py --mode extract-values --input .ystar_cieu.db --output knowledge/<role>/gaps/gemma_sessions.log",
            "# This extracts Board values, agent behavior patterns, governance gaps from CIEU logs",
            "# Review output in gemma_sessions.log, action any HIGH_PRIORITY gaps within 48h",
            "# If Gemma endpoint unreachable: write manual review to knowledge/<role>/gaps/manual_review_<date>.md",
        ],
        skill_ref="knowledge/ceo/skills/gemma_learning_protocol.md",
        lesson_ref=None,
        rule_name="gemma_session_daily",
        rule_context="Local learning loop; ensures agent mental models stay aligned with Board values without external LLM dependency.",
    ),

    # 9. weekly_roadmap_audit (604800s SLA — 7 days)
    "weekly_roadmap_audit": Remediation(
        wrong_action="No roadmap audit run in 7 days; OKRs may have drifted from reality",
        correct_steps=[
            "# Run weekly roadmap audit:",
            "python3 scripts/roadmap_audit.py --input OKR.md --cieu-db .ystar_cieu.db --output reports/roadmap_audit_<date>.md",
            "# Compare OKR targets vs actual CIEU-recorded progress",
            "# Update OKR.md with revised targets if >20% drift detected",
            "# Escalate to Board if strategic pivot needed (e.g., customer feedback invalidated hypothesis)",
            "# If roadmap_audit.py missing: manually review OKR.md vs reports/autonomous/ and write gap analysis",
        ],
        skill_ref="knowledge/ceo/skills/strategic_alignment_audit.md",
        lesson_ref=None,
        rule_name="weekly_roadmap_audit",
        rule_context="Prevents strategy drift; ensures execution stays aligned with declared objectives.",
    ),
}


# ── Helper: Get remediation by obligation type ─────────────────────────────────

def get_obligation_remediation(obligation_type: str) -> Remediation:
    """
    Get structured remediation for an obligation type.

    Args:
        obligation_type: Key from contract.obligation_timing (e.g., "directive_acknowledgement")

    Returns:
        Remediation object with executable guidance

    Raises:
        KeyError if obligation_type not in map (caller should handle gracefully)
    """
    return OBLIGATION_REMEDIATION_MAP[obligation_type]


def get_obligation_remediation_safe(obligation_type: str) -> Optional[Remediation]:
    """
    Get remediation or None if not found (safe version).

    Use this in enforcement paths where some obligation types may not have
    remediation yet (e.g., custom domain pack obligations).
    """
    return OBLIGATION_REMEDIATION_MAP.get(obligation_type)

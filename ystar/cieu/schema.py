"""
CIEU Database Schema Constants

This module defines the canonical schema for the CIEU audit database.
All scripts that interact with .ystar_cieu.db MUST import from here.

Governance: Board-mandated schema, do not modify without Board approval.
"""

# Column names (use these constants, never hardcode strings)
COL_ROWID = "rowid"
COL_EVENT_ID = "event_id"
COL_SEQ_GLOBAL = "seq_global"
COL_CREATED_AT = "created_at"
COL_SESSION_ID = "session_id"
COL_AGENT_ID = "agent_id"
COL_EVENT_TYPE = "event_type"
COL_DECISION = "decision"
COL_PASSED = "passed"
COL_VIOLATIONS = "violations"
COL_DRIFT_DETECTED = "drift_detected"
COL_DRIFT_DETAILS = "drift_details"
COL_DRIFT_CATEGORY = "drift_category"
COL_FILE_PATH = "file_path"
COL_COMMAND = "command"
COL_URL = "url"
COL_SKILL_NAME = "skill_name"
COL_SKILL_SOURCE = "skill_source"
COL_TASK_DESCRIPTION = "task_description"
COL_CONTRACT_HASH = "contract_hash"
COL_CHAIN_DEPTH = "chain_depth"
COL_PARAMS_JSON = "params_json"
COL_RESULT_JSON = "result_json"
COL_HUMAN_INITIATOR = "human_initiator"
COL_LINEAGE_PATH = "lineage_path"
COL_SEALED = "sealed"
COL_EVIDENCE_GRADE = "evidence_grade"

# Table name
TABLE_CIEU_EVENTS = "cieu_events"
TABLE_CIEU_FTS = "cieu_fts"

# Common query patterns
QUERY_INSERT_EVENT = f"""
INSERT INTO {TABLE_CIEU_EVENTS} (
    {COL_EVENT_ID}, {COL_SEQ_GLOBAL}, {COL_CREATED_AT},
    {COL_SESSION_ID}, {COL_AGENT_ID}, {COL_EVENT_TYPE},
    {COL_DECISION}, {COL_PASSED}, {COL_TASK_DESCRIPTION}, {COL_PARAMS_JSON}
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

QUERY_SELECT_BY_TYPE = f"""
SELECT {COL_EVENT_ID}, {COL_CREATED_AT}, {COL_AGENT_ID},
       {COL_TASK_DESCRIPTION}, {COL_PARAMS_JSON}
FROM {TABLE_CIEU_EVENTS}
WHERE {COL_EVENT_TYPE} = ?
ORDER BY {COL_CREATED_AT} ASC
"""

QUERY_SELECT_BY_SESSION = f"""
SELECT {COL_EVENT_ID}, {COL_CREATED_AT}, {COL_AGENT_ID},
       {COL_EVENT_TYPE}, {COL_TASK_DESCRIPTION}, {COL_PARAMS_JSON}
FROM {TABLE_CIEU_EVENTS}
WHERE {COL_SESSION_ID} = ?
ORDER BY {COL_CREATED_AT} ASC
"""

# Decision values
DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_ESCALATE = "escalate"

# Evidence grades
EVIDENCE_DECISION = "decision"
EVIDENCE_AUDIT = "audit"
EVIDENCE_SEALED = "sealed"

# Helper function for creating event_id
def generate_event_id() -> str:
    """Generate UUID for event_id."""
    import uuid
    return str(uuid.uuid4())

# Helper function for seq_global
def generate_seq_global() -> int:
    """Generate microsecond timestamp for seq_global."""
    import time
    return int(time.time() * 1_000_000)

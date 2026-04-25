import sqlite3
from pathlib import Path

from ystar.governance.observation_stack import ObservationStack, XtSnapshot


def test_observation_stack_builds_snapshot_without_dbs(tmp_path):
    (tmp_path / "ystar" / "governance").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    stack = ObservationStack(repo_root=tmp_path)
    snap = stack.build(
        role_id="ceo",
        agent_id="aiden",
        task_id="T1",
        goal_id="Y_001",
        prompt_context="ship gov-mcp",
    )

    assert isinstance(snap, XtSnapshot)
    assert snap.snapshot_id.startswith("xt_")
    assert snap.role_id == "ceo"
    assert snap.agent_id == "aiden"
    assert snap.local_context["prompt_context"] == "ship gov-mcp"
    assert snap.code_state["governance_package_exists"] is True
    assert "cieu_state" in snap.stale_fields
    assert snap.confidence["code_state"] == 0.9


def test_observation_stack_reads_cieu_and_goal_tables(tmp_path):
    db = tmp_path / ".ystar_cieu.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE cieu_events (event_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE sealed_sessions (session_id TEXT PRIMARY KEY)")
    conn.execute(
        """
        CREATE TABLE ystar_goal_tree (
            goal_id TEXT PRIMARY KEY,
            parent_goal_id TEXT,
            goal_text TEXT,
            y_star_definition TEXT,
            owner_role TEXT,
            status TEXT,
            weight REAL
        )
        """
    )
    conn.execute(
        "CREATE TABLE cieu_goal_contribution (event_id TEXT, goal_id TEXT)"
    )
    conn.execute("INSERT INTO cieu_events VALUES ('e1')")
    conn.execute(
        """
        INSERT INTO ystar_goal_tree
        VALUES ('Y_001', NULL, 'ship gov-mcp', 'pip-installable + first paid user', 'cto', 'active', 1.0)
        """
    )
    conn.commit()
    conn.close()

    stack = ObservationStack(repo_root=tmp_path, cieu_db=db)
    snap = stack.build(role_id="cto", agent_id="ethan", goal_id="Y_001")

    assert snap.cieu_state["db_exists"] is True
    assert snap.cieu_state["event_count"] == 1
    assert snap.goal_state["goal_table_exists"] is True
    assert snap.goal_state["goal_count"] == 1
    assert snap.goal_state["active_goal"]["goal_id"] == "Y_001"
    assert snap.goal_state["active_goal"]["y_star_definition"] == "pip-installable + first paid user"


def test_observation_stack_reads_memory_brain_and_omission_counts(tmp_path):
    memory_db = tmp_path / ".ystar_memory.db"
    conn = sqlite3.connect(memory_db)
    conn.execute("CREATE TABLE memories (memory_id TEXT)")
    conn.execute("CREATE TABLE agents (agent_id TEXT)")
    conn.execute("CREATE TABLE access_log (access_id TEXT)")
    conn.execute("INSERT INTO memories VALUES ('m1')")
    conn.commit()
    conn.close()

    brain_db = tmp_path / "aiden_brain.db"
    conn = sqlite3.connect(brain_db)
    conn.execute("CREATE TABLE nodes (id TEXT)")
    conn.execute("CREATE TABLE edges (src TEXT, dst TEXT)")
    conn.execute("CREATE TABLE activation_log (id INTEGER)")
    conn.execute("INSERT INTO activation_log VALUES (1)")
    conn.commit()
    conn.close()

    omission_db = tmp_path / ".ystar_omission.db"
    conn = sqlite3.connect(omission_db)
    conn.execute("CREATE TABLE entities (id TEXT)")
    conn.execute("CREATE TABLE obligations (id TEXT)")
    conn.execute("CREATE TABLE omission_violations (id TEXT)")
    conn.execute("INSERT INTO obligations VALUES ('o1')")
    conn.commit()
    conn.close()

    stack = ObservationStack(
        repo_root=tmp_path,
        memory_db=memory_db,
        brain_db=brain_db,
        omission_db=omission_db,
    )
    snap = stack.build(role_id="secretary", agent_id="samantha")

    assert snap.memory_state["memory_count"] == 1
    assert snap.brain_state["activation_count"] == 1
    assert snap.omission_state["obligation_count"] == 1
    assert "memory_state" not in snap.stale_fields
    assert "brain_state" not in snap.stale_fields
    assert "omission_state" not in snap.stale_fields


def test_xt_snapshot_to_dict_roundtrip_shape(tmp_path):
    stack = ObservationStack(repo_root=tmp_path)
    snap = stack.build(role_id="auditor", agent_id="maya")
    d = snap.to_dict()

    assert d["role_id"] == "auditor"
    assert d["agent_id"] == "maya"
    assert "code_state" in d
    assert "confidence" in d

# ystar/cli/safemode_cmd.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
Safemode CLI — Board Override Mechanism (AMENDMENT-015 Layer 4)

Allows Board (Haotian) to bypass governance checks for emergency actions.
All overrides are fully audited in CIEU.

Usage:
    ystar safemode "git push --force origin main" --justification "emergency hotfix"
    ystar safemode --shell --duration 60
    ystar safemode restore-agent ceo
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click


def _get_cieu_db() -> Optional[Path]:
    """Find CIEU database path."""
    candidates = [
        Path.cwd() / ".ystar_cieu.db",
        Path(os.path.expanduser("~/.openclaw/workspace/ystar-company/.ystar_cieu.db")),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _record_cieu_event(event_type: str, data: dict):
    """Record safemode event in CIEU database."""
    cieu_db = _get_cieu_db()
    if not cieu_db:
        click.echo(f"⚠️  CIEU database not found, safemode event not recorded", err=True)
        return

    try:
        import sqlite3
        conn = sqlite3.connect(str(cieu_db))
        cursor = conn.cursor()

        # Ensure table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cieu_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                data TEXT
            )
        """)

        cursor.execute(
            "INSERT INTO cieu_events (event_type, agent_id, timestamp, data) VALUES (?, ?, ?, ?)",
            (event_type, data.get("agent_id", "board"), time.time(), json.dumps(data))
        )

        conn.commit()
        conn.close()

    except Exception as e:
        click.echo(f"⚠️  Failed to record CIEU event: {e}", err=True)


@click.command("safemode")
@click.argument("command", required=False)
@click.option("--shell", is_flag=True, help="Open interactive shell with governance disabled")
@click.option("--duration", default=60, type=int, help="Safemode duration in seconds (for --shell)")
@click.option("--bypass", help="Specific check to bypass (e.g., restricted_write_paths)")
@click.option("--justification", prompt="Why is this override needed?", help="Justification for audit trail")
def safemode(command: Optional[str], shell: bool, duration: int, bypass: Optional[str], justification: str):
    """
    Execute command with governance checks bypassed (Board override).

    All safemode actions are recorded in CIEU audit trail.

    Examples:
        # Single command override
        ystar safemode "git push --force origin main" --justification "emergency hotfix"

        # Interactive shell mode
        ystar safemode --shell --duration 60 --justification "debugging governance issue"

        # Identity restore (special case)
        ystar safemode restore-agent ceo
    """
    if not command and not shell:
        click.echo("Error: Must provide either COMMAND or --shell", err=True)
        sys.exit(1)

    # Special case: restore-agent (Layer 1 identity recovery)
    if command and command.startswith("restore-agent "):
        target_agent = command.split()[1]
        _restore_agent_identity(target_agent, justification)
        return

    # Record override start
    override_data = {
        "agent_id": "board",
        "command": command or "shell",
        "bypass": bypass,
        "justification": justification,
        "duration": duration if shell else None
    }
    _record_cieu_event("governance_override_start", override_data)

    click.echo(f"🔓 SAFEMODE ACTIVE — Governance checks bypassed")
    click.echo(f"   Justification: {justification}")
    if bypass:
        click.echo(f"   Bypassing: {bypass}")

    # Prepare environment with safemode flags
    env = os.environ.copy()
    env["YSTAR_SAFEMODE"] = "1"
    if bypass:
        env["YSTAR_SAFEMODE_BYPASS"] = bypass

    exit_code = 0

    try:
        if shell:
            # Interactive shell mode
            expires = time.time() + duration
            env["YSTAR_SAFEMODE_EXPIRES"] = str(expires)
            click.echo(f"   Duration: {duration}s (expires at {time.ctime(expires)})")
            click.echo()

            shell_path = env.get("SHELL", "/bin/bash")
            result = subprocess.run([shell_path], env=env)
            exit_code = result.returncode

        else:
            # Single command mode
            env["YSTAR_SAFEMODE_EXPIRES"] = str(time.time() + 300)  # 5 min max
            click.echo(f"   Executing: {command}")
            click.echo()

            result = subprocess.run(command, shell=True, env=env)
            exit_code = result.returncode

            click.echo()
            click.echo(f"Command exited with code {exit_code}")

    except KeyboardInterrupt:
        click.echo("\n⚠️  Safemode interrupted")
        exit_code = 130

    finally:
        # Record completion
        _record_cieu_event("governance_override_complete", {
            **override_data,
            "exit_code": exit_code,
            "completed_at": time.time()
        })

        click.echo(f"🔒 SAFEMODE DEACTIVATED — Governance restored")

    sys.exit(exit_code)


def _restore_agent_identity(target_agent: str, justification: str):
    """
    Restore agent identity (Layer 1 identity recovery).

    This is a special safemode action for when agent identity drifts
    (e.g., CEO delegates to eng-platform and stack doesn't pop).

    MTTR target: <60s
    """
    click.echo(f"🔧 Restoring agent identity to '{target_agent}'")
    click.echo(f"   Justification: {justification}")

    # Record restore event
    _record_cieu_event("agent_identity_restore", {
        "agent_id": "board",
        "target_agent": target_agent,
        "justification": justification
    })

    # Find session config
    session_config = None
    candidates = [
        Path.cwd() / ".ystar_session.json",
        Path(os.path.expanduser("~/.openclaw/workspace/ystar-company/.ystar_session.json")),
    ]
    for c in candidates:
        if c.exists():
            session_config = c
            break

    if not session_config:
        click.echo("❌ Error: .ystar_session.json not found", err=True)
        sys.exit(1)

    try:
        # Load session config
        with open(session_config) as f:
            config = json.load(f)

        # Update agent_id
        old_agent = config.get("session", {}).get("agent_id", "unknown")
        if "session" not in config:
            config["session"] = {}
        config["session"]["agent_id"] = target_agent

        # Clear agent stack (if exists)
        if "agent_stack" in config["session"]:
            config["session"]["agent_stack"] = [target_agent]

        # Write back
        with open(session_config, "w") as f:
            json.dump(config, f, indent=2)

        click.echo(f"✅ Identity restored: {old_agent} → {target_agent}")
        click.echo(f"   Updated: {session_config}")

    except Exception as e:
        click.echo(f"❌ Failed to restore identity: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    safemode()

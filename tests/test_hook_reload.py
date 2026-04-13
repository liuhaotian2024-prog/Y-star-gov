"""Test hook daemon live-reload of session.json."""
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest


def test_session_config_reload():
    """Verify daemon reloads session.json when mtime changes."""
    from ystar._hook_daemon import HookDaemon

    with tempfile.TemporaryDirectory() as tmpdir:
        session_json = Path(tmpdir) / ".ystar_session.json"

        # Initial config
        config_v1 = {"version": 1, "rules": ["rule1"]}
        session_json.write_text(json.dumps(config_v1))
        initial_mtime = session_json.stat().st_mtime

        with patch("ystar._hook_daemon.SESSION_JSON_PATH", session_json):
            daemon = HookDaemon()

            # First load
            cfg1 = daemon._get_session_config()
            assert cfg1["version"] == 1
            assert daemon._session_config_mtime == initial_mtime

            # Modify config
            time.sleep(0.01)  # Ensure mtime changes
            config_v2 = {"version": 2, "rules": ["rule1", "rule2"]}
            session_json.write_text(json.dumps(config_v2))
            session_json.touch()  # Force mtime update
            new_mtime = session_json.stat().st_mtime
            assert new_mtime > initial_mtime

            # Reload should detect change
            cfg2 = daemon._get_session_config()
            assert cfg2["version"] == 2
            assert daemon._session_config_mtime == new_mtime
            assert len(cfg2["rules"]) == 2


def test_session_config_cache_unchanged():
    """Verify daemon uses cache when mtime unchanged."""
    from ystar._hook_daemon import HookDaemon

    with tempfile.TemporaryDirectory() as tmpdir:
        session_json = Path(tmpdir) / ".ystar_session.json"
        config = {"version": 1}
        session_json.write_text(json.dumps(config))

        with patch("ystar._hook_daemon.SESSION_JSON_PATH", session_json):
            daemon = HookDaemon()

            # First load
            cfg1 = daemon._get_session_config()
            mtime1 = daemon._session_config_mtime

            # Second load without file change
            cfg2 = daemon._get_session_config()
            mtime2 = daemon._session_config_mtime

            # Should use cached version
            assert cfg1 is cfg2
            assert mtime1 == mtime2


def test_session_config_missing_file():
    """Verify daemon handles missing session.json gracefully."""
    from ystar._hook_daemon import HookDaemon

    with tempfile.TemporaryDirectory() as tmpdir:
        session_json = Path(tmpdir) / ".ystar_session.json"

        with patch("ystar._hook_daemon.SESSION_JSON_PATH", session_json):
            daemon = HookDaemon()
            cfg = daemon._get_session_config()
            assert cfg == {}

"""
Y*gov v0.41 测试配置
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import tempfile
import time

from ystar.workspace_config import invalidate_cache


@pytest.fixture(autouse=True)
def labs_workspace_env(tmp_path, monkeypatch):
    """Set YSTAR_LABS_WORKSPACE to tmp_path for test isolation.

    Ensures tests don't depend on real Labs path existing.
    Creates minimal directory structure expected by workspace_config consumers.
    """
    fake_ws = tmp_path / "ystar-company"
    fake_ws.mkdir()
    (fake_ws / ".ystar_cieu.db").touch()
    (fake_ws / ".ystar_session.json").write_text("{}")
    (fake_ws / "governance").mkdir()
    (fake_ws / "scripts").mkdir()
    (fake_ws / "reports").mkdir()
    (fake_ws / "reports" / "cto").mkdir()
    monkeypatch.setenv("YSTAR_LABS_WORKSPACE", str(fake_ws))
    invalidate_cache()
    yield fake_ws
    invalidate_cache()

@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / ".ystar_cieu.db")

@pytest.fixture
def tmp_omission_db(tmp_path):
    return str(tmp_path / ".ystar_omission.db")

@pytest.fixture
def basic_policy():
    from ystar.session import Policy
    p = Policy.from_agents_md("""
## Never access
- /etc
- /root
- /production

## Never run
- rm -rf
- sudo
- DROP TABLE

## Obligations
- respond_to_complaint: 300 seconds
""")
    return p

@pytest.fixture
def basic_contract():
    from ystar.kernel.dimensions import IntentContract
    return IntentContract(
        deny=["/etc", "/root", "/production"],
        deny_commands=["rm -rf", "sudo", "DROP TABLE"],
        only_paths=["./workspace/"],
        value_range={"amount": {"max": 10000, "min": 1}},
    )

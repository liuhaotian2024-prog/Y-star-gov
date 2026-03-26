"""
Y*gov v0.41 测试配置
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import tempfile
import time

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

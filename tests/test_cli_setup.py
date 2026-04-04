"""
tests.test_cli_setup — ystar setup命令功能测试

测试覆盖：
1. 正常流程：在空目录执行setup生成.ystar_session.json
2. 幂等性：重复执行不报错
3. 最小配置：--skip-prompt模式
4. 文件内容验证：session_id, cieu_db, contract字段完整
5. 错误处理：无权限写入时的错误提示

P0优先级：用户首次安装必经流程
"""
import pytest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# 导入被测函数
from ystar.cli.setup_cmd import _cmd_setup


class TestSetupCommand:
    """ystar setup命令功能测试套件"""

    def test_setup_creates_session_file(self, tmp_path, monkeypatch):
        """测试setup在空目录生成.ystar_session.json"""
        # 切换到临时目录
        monkeypatch.chdir(tmp_path)

        # Mock user input（最小配置 + retroactive baseline prompt）
        with patch('builtins.input', side_effect=['test_agent', '', '', '', '', 'n']):
            _cmd_setup()

        # 验证文件生成
        session_file = tmp_path / ".ystar_session.json"
        assert session_file.exists()

        # 验证文件内容
        with open(session_file) as f:
            config = json.load(f)

        assert "session_id" in config
        assert "cieu_db" in config
        assert config["cieu_db"] == ".ystar_cieu.db"
        assert "contract" in config

    def test_setup_idempotent(self, tmp_path, monkeypatch):
        """测试setup幂等性：重复执行不报错"""
        monkeypatch.chdir(tmp_path)

        # 第一次执行
        with patch('builtins.input', side_effect=['agent1', '', '', '', '', 'n']):
            _cmd_setup()

        # 第二次执行
        with patch('builtins.input', side_effect=['agent2', '', '', '', '', 'n']):
            _cmd_setup()  # 不应该抛出异常

        # 验证文件仍然存在
        assert (tmp_path / ".ystar_session.json").exists()

    def test_setup_skip_prompt(self, tmp_path, monkeypatch):
        """测试--skip-prompt模式（CI/自动化场景）"""
        monkeypatch.chdir(tmp_path)

        # 使用skip_prompt=True参数
        _cmd_setup(skip_prompt=True)

        session_file = tmp_path / ".ystar_session.json"
        assert session_file.exists()

        with open(session_file) as f:
            config = json.load(f)

        # 验证最小配置字段
        assert "session_id" in config
        assert len(config["session_id"]) > 0

    def test_setup_validates_contract_structure(self, tmp_path, monkeypatch):
        """测试生成的contract结构完整性"""
        monkeypatch.chdir(tmp_path)

        with patch('builtins.input', side_effect=['test_agent', '', '', '', '', 'n']):
            _cmd_setup()

        with open(tmp_path / ".ystar_session.json") as f:
            config = json.load(f)

        contract = config.get("contract", {})

        # 验证contract必需字段
        assert isinstance(contract, dict)
        # 基础字段应该存在
        assert "deny" in contract
        assert "deny_commands" in contract
        assert isinstance(contract["deny"], list)
        assert isinstance(contract["deny_commands"], list)

    def test_setup_permission_error(self, tmp_path, monkeypatch):
        """测试无权限写入时的错误处理"""
        monkeypatch.chdir(tmp_path)

        # 创建只读文件阻止写入
        session_file = tmp_path / ".ystar_session.json"
        session_file.write_text("{}")
        session_file.chmod(0o444)  # 只读

        try:
            # 执行setup应该捕获异常并提示
            with patch('builtins.input', side_effect=['test', '', '', '', '', 'n']):
                with pytest.raises((PermissionError, OSError)):
                    _cmd_setup()
        finally:
            # 恢复权限以便清理
            session_file.chmod(0o644)

    def test_setup_custom_deny_paths(self, tmp_path, monkeypatch):
        """测试自定义deny paths"""
        monkeypatch.chdir(tmp_path)

        # 提供自定义路径
        inputs = ['myproject', '', '/custom,/paths', '', '', 'n']
        with patch('builtins.input', side_effect=inputs):
            _cmd_setup()

        with open(tmp_path / ".ystar_session.json") as f:
            config = json.load(f)

        deny_paths = config["contract"]["deny"]
        assert "/custom" in deny_paths
        assert "/paths" in deny_paths

    def test_setup_custom_deny_commands(self, tmp_path, monkeypatch):
        """测试自定义deny commands"""
        monkeypatch.chdir(tmp_path)

        inputs = ['myproject', '', '', 'custom-cmd,danger-cmd', '', 'n']
        with patch('builtins.input', side_effect=inputs):
            _cmd_setup()

        with open(tmp_path / ".ystar_session.json") as f:
            config = json.load(f)

        deny_commands = config["contract"]["deny_commands"]
        assert "custom-cmd" in deny_commands
        assert "danger-cmd" in deny_commands


class TestSetupIntegration:
    """setup命令集成测试"""

    def test_setup_with_agents_md(self, tmp_path, monkeypatch):
        """测试setup在有AGENTS.md的项目中执行"""
        monkeypatch.chdir(tmp_path)

        # 创建AGENTS.md
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("""
# Governance Contract

## CEO Agent
Role: Chief Executive Officer

## CTO Agent
Role: Chief Technology Officer
""")

        with patch('builtins.input', side_effect=['ceo', '', '', '', '', 'n']):
            _cmd_setup()

        # 验证setup成功
        assert (tmp_path / ".ystar_session.json").exists()

    def test_setup_creates_cieu_db(self, tmp_path, monkeypatch):
        """测试setup后CIEU数据库可以正常初始化"""
        monkeypatch.chdir(tmp_path)

        with patch('builtins.input', side_effect=['test', '', '', '', '', 'n']):
            _cmd_setup()

        # 尝试初始化CIEU（不会报错）
        from ystar.governance.cieu_store import CIEUStore
        cieu = CIEUStore(".ystar_cieu.db")

        # 验证可以写入
        cieu.write({"event_type": "test", "message": "hello"})

        # 验证可以查询
        events = cieu.query(limit=10)
        assert len(events) >= 1

    def test_setup_with_obligation_timing(self, tmp_path, monkeypatch):
        """测试设置obligation timing"""
        monkeypatch.chdir(tmp_path)

        inputs = ['myproject', '', '', '', '600', 'n']
        with patch('builtins.input', side_effect=inputs):
            _cmd_setup()

        with open(tmp_path / ".ystar_session.json") as f:
            config = json.load(f)

        timing = config["contract"].get("obligation_timing", {})
        assert "respond_to_complaint" in timing
        assert timing["respond_to_complaint"] == 600.0

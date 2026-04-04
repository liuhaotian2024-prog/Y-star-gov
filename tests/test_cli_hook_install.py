"""
tests.test_cli_hook_install — ystar hook-install命令功能测试

测试覆盖：
1. 正常流程：注册PreToolUse hook到~/.claude/settings.json
2. 幂等性：重复执行不重复注册
3. 文件不存在：自动创建settings.json
4. Hook路径验证：python路径和ystar路径正确
5. 配置合并：不覆盖现有其他配置

P0优先级：用户首次安装必经流程
"""
import pytest
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from ystar.cli.setup_cmd import _cmd_hook_install


class TestHookInstallCommand:
    """ystar hook-install命令功能测试套件"""

    @pytest.fixture
    def mock_claude_dir(self, tmp_path):
        """创建mock的.claude目录"""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        return claude_dir

    def test_hook_install_creates_settings(self, mock_claude_dir, monkeypatch):
        """测试hook-install在settings.json不存在时创建"""
        settings_file = mock_claude_dir / "settings.json"

        # Mock Path.home()返回tmp_path
        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        # 验证文件生成
        assert settings_file.exists()

        # 验证内容
        with open(settings_file) as f:
            settings = json.load(f)

        assert "hooks" in settings
        assert "PreToolUse" in settings["hooks"]

    def test_hook_install_idempotent(self, mock_claude_dir, monkeypatch):
        """测试hook-install幂等性：重复执行不重复注册"""
        settings_file = mock_claude_dir / "settings.json"

        # 第一次执行
        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        with open(settings_file) as f:
            settings1 = json.load(f)

        # 第二次执行
        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        with open(settings_file) as f:
            settings2 = json.load(f)

        # 验证没有重复注册（hook数量应该相同）
        assert len(settings1["hooks"]["PreToolUse"]) == len(settings2["hooks"]["PreToolUse"])

    def test_hook_install_preserves_existing_config(self, mock_claude_dir):
        """测试hook-install不覆盖现有其他配置"""
        settings_file = mock_claude_dir / "settings.json"

        # 预先写入其他配置
        existing_config = {
            "theme": "dark",
            "language": "en",
            "hooks": {
                "OtherHook": [{
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "other_command"}]
                }]
            }
        }
        settings_file.write_text(json.dumps(existing_config, indent=2))

        # 执行hook-install
        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        # 验证原有配置保留
        with open(settings_file) as f:
            settings = json.load(f)

        assert settings["theme"] == "dark"
        assert settings["language"] == "en"
        assert "OtherHook" in settings["hooks"]
        assert "PreToolUse" in settings["hooks"]

    def test_hook_install_validates_hook_structure(self, mock_claude_dir):
        """测试生成的hook配置结构正确"""
        settings_file = mock_claude_dir / "settings.json"

        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        with open(settings_file) as f:
            settings = json.load(f)

        pre_tool_use = settings["hooks"]["PreToolUse"]
        assert isinstance(pre_tool_use, list)
        assert len(pre_tool_use) > 0

        # 验证hook entry结构
        hook_entry = pre_tool_use[0]
        assert "matcher" in hook_entry
        assert "hooks" in hook_entry
        assert isinstance(hook_entry["hooks"], list)

        # 验证hook command结构
        hook = hook_entry["hooks"][0]
        assert "type" in hook
        assert hook["type"] == "command"
        assert "command" in hook

        # 验证command包含ystar相关内容
        command = hook["command"]
        assert "ystar" in command.lower()

    def test_hook_install_creates_claude_dir(self, tmp_path):
        """测试hook-install在.claude目录不存在时创建"""
        # tmp_path下没有.claude目录

        with patch('pathlib.Path.home', return_value=tmp_path):
            _cmd_hook_install()

        # 验证.claude目录和settings.json都创建
        claude_dir = tmp_path / ".claude"
        assert claude_dir.exists()
        assert (claude_dir / "settings.json").exists()

    def test_hook_install_windows_wrapper(self, mock_claude_dir, monkeypatch):
        """测试Windows平台创建.bat wrapper"""
        if sys.platform != "win32":
            pytest.skip("Windows-specific test")

        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        # 验证wrapper文件创建
        wrapper_path = mock_claude_dir / "ystar_hook_wrapper.bat"
        assert wrapper_path.exists()

        # 验证wrapper内容
        content = wrapper_path.read_text()
        assert "@echo off" in content
        assert "python" in content.lower()

    def test_hook_install_detects_existing_hook(self, mock_claude_dir, capsys):
        """测试检测已安装的hook"""
        settings_file = mock_claude_dir / "settings.json"

        # 第一次安装
        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        # 清空输出
        capsys.readouterr()

        # 第二次安装
        with patch('pathlib.Path.home', return_value=mock_claude_dir.parent):
            _cmd_hook_install()

        out = capsys.readouterr().out
        assert "already installed" in out.lower()


class TestHookInstallIntegration:
    """hook-install命令集成测试"""

    def test_hook_install_after_setup(self, tmp_path, monkeypatch):
        """测试在执行setup后执行hook-install"""
        monkeypatch.chdir(tmp_path)

        # 先执行setup
        from ystar.cli.setup_cmd import _cmd_setup
        with patch('builtins.input', side_effect=['test', '', '', '', '', 'n']):
            _cmd_setup()

        # 再执行hook-install
        mock_claude = tmp_path / ".claude"
        mock_claude.mkdir()

        with patch('pathlib.Path.home', return_value=tmp_path):
            _cmd_hook_install()

        # 验证两个配置文件都存在
        assert (tmp_path / ".ystar_session.json").exists()
        assert (mock_claude / "settings.json").exists()

    def test_hook_install_doctor_check(self, tmp_path):
        """测试hook-install后doctor能检测到hook"""
        mock_claude = tmp_path / ".claude"
        mock_claude.mkdir()

        # 执行hook-install
        with patch('pathlib.Path.home', return_value=tmp_path):
            _cmd_hook_install()

        # 验证settings.json格式正确
        settings_file = mock_claude / "settings.json"
        with open(settings_file) as f:
            settings = json.load(f)

        # doctor会检查这个结构
        assert isinstance(settings.get("hooks"), dict)
        assert isinstance(settings["hooks"].get("PreToolUse"), list)

    def test_hook_install_self_test_runs(self, tmp_path, capsys):
        """测试hook-install运行自检"""
        mock_claude = tmp_path / ".claude"
        mock_claude.mkdir()

        with patch('pathlib.Path.home', return_value=tmp_path):
            _cmd_hook_install()

        out = capsys.readouterr().out
        # 验证自检执行
        assert "Self-test" in out or "self-test" in out.lower()
        # 自检应该通过或跳过
        assert ("passed" in out.lower() or "skipped" in out.lower())

    def test_hook_install_multiple_candidate_paths(self, tmp_path):
        """测试在多个候选路径中找到配置文件"""
        # 创建第一个候选路径的配置
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_file = claude_dir / "settings.json"
        settings_file.write_text(json.dumps({"existing": "config"}, indent=2))

        with patch('pathlib.Path.home', return_value=tmp_path):
            _cmd_hook_install()

        # 验证使用了现有配置文件
        with open(settings_file) as f:
            settings = json.load(f)

        assert "existing" in settings
        assert "hooks" in settings

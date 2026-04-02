# tests/test_domain_cli.py — Test domain CLI commands
"""
Tests for ystar domain list|describe|init commands (P1-7).
"""
import pytest
import pathlib
import sys
from io import StringIO


def test_domain_list(capsys):
    """Test that ystar domain list shows all registered domain packs."""
    from ystar.cli.domain_cmd import _cmd_domain_list

    _cmd_domain_list()
    captured = capsys.readouterr()

    # Should show header
    assert "Y* Domain Packs" in captured.out
    assert "Domain" in captured.out
    assert "Class" in captured.out
    assert "Version" in captured.out

    # Should show at least the core domain packs
    assert "finance" in captured.out
    assert "FinanceDomainPack" in captured.out
    assert "1.0.0" in captured.out

    # Should show total count
    assert "Total:" in captured.out
    assert "domain packs" in captured.out


def test_domain_describe(capsys):
    """Test that ystar domain describe shows details of a specific pack."""
    from ystar.cli.domain_cmd import _cmd_domain_describe

    _cmd_domain_describe("finance")
    captured = capsys.readouterr()

    # Should show pack details
    assert "Domain Pack: finance" in captured.out
    assert "Domain:" in captured.out
    assert "Version:" in captured.out
    assert "Schema Version:" in captured.out
    assert "FinanceDomainPack" in captured.out

    # Should show vocabulary info
    assert "Vocabulary:" in captured.out
    assert "Roles:" in captured.out

    # Should show constitutional contract summary
    assert "Constitutional Contract:" in captured.out
    assert "Deny rules:" in captured.out or "Deny commands:" in captured.out

    # Should show usage example
    assert "Usage Example:" in captured.out
    assert "from ystar.domains.finance import FinanceDomainPack" in captured.out


def test_domain_describe_nonexistent(capsys):
    """Test that ystar domain describe fails gracefully for nonexistent pack."""
    from ystar.cli.domain_cmd import _cmd_domain_describe

    with pytest.raises(SystemExit):
        _cmd_domain_describe("nonexistent_pack_xyz")

    captured = capsys.readouterr()
    assert "not found" in captured.out
    assert "Available packs:" in captured.out


def test_domain_init_creates_template(tmp_path):
    """Test that ystar domain init creates a template file."""
    from ystar.cli.domain_cmd import _cmd_domain_init
    import os

    # Change to temp directory
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        # Create template
        _cmd_domain_init("testdomain")

        # Check file was created
        template_path = tmp_path / "testdomain_domain_pack.py"
        assert template_path.exists()

        # Check template content
        content = template_path.read_text(encoding="utf-8")
        assert "class TestdomainDomainPack(DomainPack):" in content
        assert 'domain_name(self) -> str:' in content
        assert 'return "testdomain"' in content
        assert "def constitutional_contract(self):" in content
        assert "def vocabulary(self) -> dict:" in content
        assert "def make_contract(self, role: str, context: dict = None):" in content

        # Check convenience function
        assert "def make_testdomain_pack()" in content

    finally:
        os.chdir(original_cwd)


def test_domain_init_refuses_overwrite(tmp_path):
    """Test that ystar domain init refuses to overwrite existing file."""
    from ystar.cli.domain_cmd import _cmd_domain_init
    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        # Create template
        _cmd_domain_init("testdomain")

        # Try to create again
        with pytest.raises(SystemExit):
            _cmd_domain_init("testdomain")

    finally:
        os.chdir(original_cwd)


def test_discover_domain_packs():
    """Test that _discover_domain_packs finds all domain packs."""
    from ystar.cli.domain_cmd import _discover_domain_packs

    packs = _discover_domain_packs()

    # Should find at least the core domain packs
    assert "finance" in packs
    assert "healthcare" in packs or "pharma" in packs
    assert "devops" in packs or "crypto" in packs

    # All values should be classes
    for domain_name, pack_class in packs.items():
        assert isinstance(pack_class, type)
        # Should be instantiable
        instance = pack_class()
        assert instance.domain_name == domain_name


def test_main_domain_cmd_no_args(capsys):
    """Test that main_domain_cmd shows usage when no args provided."""
    from ystar.cli.domain_cmd import main_domain_cmd

    with pytest.raises(SystemExit):
        main_domain_cmd([])

    captured = capsys.readouterr()
    assert "Usage: ystar domain" in captured.out
    assert "list" in captured.out
    assert "describe" in captured.out
    assert "init" in captured.out


def test_main_domain_cmd_unknown_subcommand(capsys):
    """Test that main_domain_cmd fails for unknown subcommand."""
    from ystar.cli.domain_cmd import main_domain_cmd

    with pytest.raises(SystemExit):
        main_domain_cmd(["unknown_subcommand"])

    captured = capsys.readouterr()
    assert "Unknown subcommand: unknown_subcommand" in captured.out


def test_domain_list_shows_multiple_packs(capsys):
    """Test that domain list shows multiple domain packs."""
    from ystar.cli.domain_cmd import _cmd_domain_list

    _cmd_domain_list()
    captured = capsys.readouterr()

    # Count how many packs are shown
    lines = [l for l in captured.out.split('\n') if l.strip() and not l.startswith('  -')]

    # Should have at least finance, healthcare, devops, crypto, pharma, ystar_dev
    # (6 packs based on earlier discovery)
    pack_lines = [l for l in lines if 'DomainPack' in l]
    assert len(pack_lines) >= 5  # At least 5 different packs


def test_domain_describe_shows_roles(capsys):
    """Test that domain describe shows role information."""
    from ystar.cli.domain_cmd import _cmd_domain_describe

    _cmd_domain_describe("finance")
    captured = capsys.readouterr()

    # Finance pack should have roles
    assert "Roles:" in captured.out
    # Should show at least some role names
    assert "authorized_participant" in captured.out or "trader" in captured.out.lower()

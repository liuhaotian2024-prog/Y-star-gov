# tests/test_cli_docs.py — Verify CLI documentation completeness
"""
Ensure that all commands listed in _cli.py are documented in README.md.
Prevents documentation drift when new CLI commands are added.
"""
import re
from pathlib import Path


def test_cli_reference_completeness():
    """Verify all CLI commands are documented in README.md CLI Reference section."""
    repo_root = Path(__file__).parent.parent
    cli_path = repo_root / "ystar" / "_cli.py"
    readme_path = repo_root / "README.md"

    # Extract commands from _cli.py docstring (module docstring)
    cli_content = cli_path.read_text(encoding="utf-8")
    cli_docstring = cli_content.split('"""')[1]  # Get first docstring
    # Match "ystar <command>" but exclude "ystar ystar" (which appears in docstring as pip install)
    cli_commands = set(re.findall(r'^\s*ystar\s+([a-z-]+)', cli_docstring, re.MULTILINE))
    # Filter out spurious matches
    cli_commands = {cmd for cmd in cli_commands if cmd != "ystar"}

    # Extract commands from README CLI Reference section
    readme_content = readme_path.read_text(encoding="utf-8")

    # Find CLI Reference section
    cli_ref_match = re.search(
        r'## CLI Reference\s*\n\s*```bash\n(.*?)```',
        readme_content,
        re.DOTALL
    )
    assert cli_ref_match, "CLI Reference section not found in README.md"

    cli_ref_section = cli_ref_match.group(1)
    readme_commands = set(re.findall(r'^ystar\s+([a-z-]+)', cli_ref_section, re.MULTILINE))

    # Commands that should be documented
    missing_in_readme = cli_commands - readme_commands
    extra_in_readme = readme_commands - cli_commands

    # Report any discrepancies
    if missing_in_readme:
        print(f"\n⚠️  Commands in _cli.py but missing from README CLI Reference:")
        for cmd in sorted(missing_in_readme):
            print(f"    - ystar {cmd}")

    if extra_in_readme:
        print(f"\n⚠️  Commands in README CLI Reference but not in _cli.py:")
        for cmd in sorted(extra_in_readme):
            print(f"    - ystar {cmd}")

    # Test passes only if all commands are documented
    assert not missing_in_readme, (
        f"CLI commands not documented in README: {sorted(missing_in_readme)}"
    )

    print(f"\n✓ All {len(cli_commands)} CLI commands are documented in README")
    print(f"  Commands: {', '.join(sorted(cli_commands))}")


if __name__ == "__main__":
    test_cli_reference_completeness()
    print("\nCLI documentation check passed!")

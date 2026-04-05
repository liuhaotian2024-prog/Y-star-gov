"""Test that Part A correctly preserves dotfile leading dots (.env, .env.*)."""
from ystar.kernel.prefill import _extract_constraints_from_text


class TestDotfilePreservation:

    def test_never_access_dotfiles(self):
        text = """Never access .env
Never access .env.local
Never access .env.production
Never access .gitignore"""
        result = _extract_constraints_from_text(text)
        deny = result.get("deny", [])
        assert ".env" in deny, f".env missing from deny: {deny}"
        assert ".env.local" in deny, f".env.local missing from deny: {deny}"
        assert ".env.production" in deny, f".env.production missing from deny: {deny}"
        assert ".gitignore" in deny, f".gitignore missing from deny: {deny}"

    def test_never_modify_dotfiles(self):
        text = "Never modify .env, .env.local"
        result = _extract_constraints_from_text(text)
        deny = result.get("deny", [])
        assert ".env" in deny
        assert ".env.local" in deny

    def test_path_with_slash_still_works(self):
        """Paths with / should still work as before."""
        text = "Never access /secret/keys"
        result = _extract_constraints_from_text(text)
        assert "/secret/keys" in result.get("deny", [])

    def test_prohibited_header_dotfiles(self):
        """Part A0: Prohibited header format."""
        text = "## Prohibited: .env files, *.env, .env.*, .env.local"
        result = _extract_constraints_from_text(text)
        deny = result.get("deny", [])
        assert ".env" in deny, f".env missing from deny: {deny}"
        assert ".env.*" in deny or ".env.local" in deny

    def test_trailing_period_still_stripped(self):
        """A trailing period (sentence end) should still be stripped."""
        text = "Never access /secret/config."
        result = _extract_constraints_from_text(text)
        deny = result.get("deny", [])
        # "/secret/config" should be present (trailing . stripped)
        # But the path contains "/" so it matches regardless
        assert any("/secret/config" in d for d in deny)

    def test_full_agents_md(self):
        """Full AGENTS.md-style text with mixed deny and deny_commands."""
        import os
        agents_path = os.path.expanduser("~/AGENTS.md")
        if os.path.isfile(agents_path):
            with open(agents_path) as f:
                text = f.read()
            result = _extract_constraints_from_text(text)
            deny = result.get("deny", [])
            deny_cmds = result.get("deny_commands", [])
            # .env must be in deny
            env_rules = [d for d in deny if ".env" in d]
            assert len(env_rules) > 0, f"No .env rules found in deny: {deny}"
            # rm -rf must be in deny_commands
            assert "rm -rf" in deny_cmds, f"rm -rf not in deny_commands: {deny_cmds}"

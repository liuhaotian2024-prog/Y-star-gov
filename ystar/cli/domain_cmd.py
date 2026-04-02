# ystar/cli/domain_cmd.py — ystar domain list|describe|init
"""
Domain Pack CLI commands.
Enables users to discover and use built-in domain packs.
"""
import sys
import pathlib
import importlib
import pkgutil


def _discover_domain_packs():
    """
    Scan ystar/domains/ and discover all DomainPack subclasses.

    Returns:
        dict: {domain_name: pack_class, ...}
    """
    import ystar.domains as domains_module
    from ystar.domains import DomainPack

    discovered = {}
    domains_path = pathlib.Path(domains_module.__file__).parent

    # Scan all subdirectories in ystar/domains/
    for item in domains_path.iterdir():
        if not item.is_dir():
            continue
        if item.name.startswith("_") or item.name.startswith("."):
            continue

        # Try importing the submodule
        try:
            module_name = f"ystar.domains.{item.name}"
            module = importlib.import_module(module_name)

            # Find DomainPack subclasses in this module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and
                    issubclass(attr, DomainPack) and
                    attr is not DomainPack):
                    try:
                        # Instantiate to get domain_name
                        instance = attr()
                        discovered[instance.domain_name] = attr
                    except Exception:
                        # Some packs may need config, skip for now
                        pass
        except Exception:
            # Skip modules that can't be imported
            pass

    return discovered


def _cmd_domain_list():
    """List all registered domain packs from ystar/domains/."""
    print()
    print("  Y* Domain Packs")
    print("  " + "-" * 60)
    print()

    packs = _discover_domain_packs()

    if not packs:
        print("  No domain packs found.")
        print()
        return

    print(f"  {'Domain':<20} {'Class':<30} {'Version':<10}")
    print(f"  {'-'*20} {'-'*30} {'-'*10}")

    for domain_name in sorted(packs.keys()):
        pack_class = packs[domain_name]
        try:
            instance = pack_class()
            version = instance.version
            class_name = pack_class.__name__
            print(f"  {domain_name:<20} {class_name:<30} {version:<10}")
        except Exception as e:
            class_name = pack_class.__name__
            print(f"  {domain_name:<20} {class_name:<30} {'error':<10}")

    print()
    print(f"  Total: {len(packs)} domain packs")
    print()
    print("  Use 'ystar domain describe <name>' for details.")
    print()


def _cmd_domain_describe(name: str):
    """Display details of a specific domain pack."""
    print()
    print(f"  Y* Domain Pack: {name}")
    print("  " + "-" * 60)
    print()

    packs = _discover_domain_packs()

    if name not in packs:
        print(f"  Domain pack '{name}' not found.")
        print()
        print("  Available packs:")
        for domain_name in sorted(packs.keys()):
            print(f"    - {domain_name}")
        print()
        sys.exit(1)

    pack_class = packs[name]
    try:
        instance = pack_class()
    except Exception as e:
        print(f"  Error instantiating pack: {e}")
        print("  This pack may require configuration.")
        print()
        sys.exit(1)

    # Basic info
    print(f"  Domain:          {instance.domain_name}")
    print(f"  Version:         {instance.version}")
    print(f"  Schema Version:  {instance.schema_version}")
    print(f"  Class:           {pack_class.__name__}")
    print(f"  Description:     {instance.describe()}")
    print()

    # Vocabulary
    vocab = instance.vocabulary()
    print("  Vocabulary:")
    if vocab.get("role_names"):
        print(f"    Roles:      {len(vocab['role_names'])} defined")
        print(f"                {', '.join(vocab['role_names'][:5])}")
        if len(vocab['role_names']) > 5:
            print(f"                ... and {len(vocab['role_names']) - 5} more")
    if vocab.get("deny_keywords"):
        print(f"    Keywords:   {len(vocab['deny_keywords'])} deny keywords")
    if vocab.get("param_names"):
        print(f"    Parameters: {len(vocab['param_names'])} tracked")
    print()

    # Constitutional contract summary
    try:
        constitution = instance.constitutional_contract()
        print("  Constitutional Contract:")
        print(f"    Deny rules:      {len(constitution.deny)} patterns")
        print(f"    Deny commands:   {len(constitution.deny_commands)} commands")
        print(f"    Invariants:      {len(constitution.invariant)} rules")
        if constitution.only_paths:
            print(f"    Path whitelist:  {len(constitution.only_paths)} allowed")
        if constitution.only_domains:
            print(f"    Domain whitelist: {len(constitution.only_domains)} allowed")
        if constitution.field_deny:
            print(f"    Field denies:    {len(constitution.field_deny)} fields")
        if constitution.value_range:
            print(f"    Value ranges:    {len(constitution.value_range)} parameters")
        print()
    except Exception as e:
        print(f"  Constitutional contract unavailable: {e}")
        print()

    # Usage example
    print("  Usage Example:")
    print(f"    from ystar.domains.{name} import {pack_class.__name__}")
    print(f"    pack = {pack_class.__name__}()")
    print(f"    constitution = pack.constitutional_contract()")
    print(f"    contract = pack.make_contract(role='<role_name>')")
    print()


def _cmd_domain_init(name: str):
    """Generate a custom domain pack template file."""
    output_path = pathlib.Path(f"{name}_domain_pack.py")

    if output_path.exists():
        print()
        print(f"  Error: {output_path} already exists.")
        print()
        sys.exit(1)

    template = f'''"""
Custom Y* Domain Pack: {name.title()}

This is a template for creating your own domain pack.
Fill in the methods below with your domain-specific rules.
"""
from ystar.domains import DomainPack
from ystar import IntentContract, ConstitutionalContract


class {name.title().replace("_", "")}DomainPack(DomainPack):
    """
    {name.title()} domain pack.

    Add your domain description here.
    """

    @property
    def domain_name(self) -> str:
        return "{name}"

    @property
    def version(self) -> str:
        return "1.0.0"

    def constitutional_contract(self):
        """
        Define global constraints for this domain.
        These constraints can never be relaxed.
        """
        return ConstitutionalContract(
            deny=[
                # Add domain-specific deny patterns here
                # Example: r"dangerous_operation",
            ],
            deny_commands=[
                # Add forbidden commands here
                # Example: "rm -rf /",
            ],
            invariant=[
                # Add invariant rules here
                # Example: "always log all operations",
            ],
            only_paths=[
                # Add path whitelist here (optional)
                # Example: "/workspace/",
            ],
            only_domains=[
                # Add domain whitelist for network access (optional)
                # Example: "api.example.com",
            ],
            name="{name}_constitutional",
        )

    def vocabulary(self) -> dict:
        """
        Define domain vocabulary.
        Used for parameter discovery and role-based contracts.
        """
        return {{
            "deny_keywords": [
                # Add domain-specific keywords to deny
            ],
            "role_names": [
                # Add role names supported by make_contract()
                # Example: "analyst", "operator", "manager",
            ],
            "param_names": [
                # Add important parameter names for this domain
            ],
            "env_keywords": [
                # Add environment keywords (e.g., "simulation", "test")
            ],
        }}

    def make_contract(self, role: str, context: dict = None):
        """
        Return role-specific IntentContract.
        Override to provide different contracts for different roles.
        """
        context = context or {{}}

        # Example: different contracts for different roles
        if role == "analyst":
            return IntentContract(
                deny_commands=["DELETE", "DROP", "UPDATE"],
                # Add more analyst-specific rules
            )
        elif role == "operator":
            return IntentContract(
                only_paths=["/workspace/deploy/"],
                # Add more operator-specific rules
            )

        # Default contract
        return IntentContract()


# Convenience factory function
def make_{name}_pack() -> {name.title().replace("_", "")}DomainPack:
    """Create an instance of the {name} domain pack."""
    return {name.title().replace("_", "")}DomainPack()
'''

    output_path.write_text(template, encoding="utf-8")

    print()
    print(f"  Domain pack template created: {output_path}")
    print()
    print("  Next steps:")
    print(f"    1. Edit {output_path} to add your domain-specific rules")
    print(f"    2. Move it to ystar/domains/{name}/__init__.py")
    print(f"    3. Use it: from ystar.domains.{name} import {name.title().replace('_', '')}DomainPack")
    print()


def main_domain_cmd(args: list):
    """Entry point for 'ystar domain' command."""
    if not args:
        print()
        print("  Usage: ystar domain <subcommand>")
        print()
        print("  Subcommands:")
        print("    list              List all registered domain packs")
        print("    describe <name>   Show details of a specific domain pack")
        print("    init <name>       Generate custom domain pack template")
        print()
        sys.exit(1)

    subcommand = args[0]

    if subcommand == "list":
        _cmd_domain_list()
    elif subcommand == "describe":
        if len(args) < 2:
            print("  Usage: ystar domain describe <name>")
            sys.exit(1)
        _cmd_domain_describe(args[1])
    elif subcommand == "init":
        if len(args) < 2:
            print("  Usage: ystar domain init <name>")
            sys.exit(1)
        _cmd_domain_init(args[1])
    else:
        print(f"  Unknown subcommand: {subcommand}")
        print("  Available: list, describe, init")
        sys.exit(1)

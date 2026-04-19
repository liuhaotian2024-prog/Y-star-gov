# Layer: Foundation
"""
ystar.rules — Built-in router rules for Y*gov governance kernel.

This package contains universal (non-company-specific) router rules
that register into the RouterRegistry at Layer 3.

Company-specific rules live in the deployer's ``router_rules/`` directory
and are loaded via ``RouterRegistry.load_rules_dir()`` or
``handle_hook_event(rules_dir=...)``.

Built-in rules provided:
  - per_rule_detectors: 6 governance telemetry detectors (CZL-ARCH-3)
  - break_glass: Emergency enforcement bypass (CZL-ARCH-5)
"""

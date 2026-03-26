# ystar/templates/__init__.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
Built-in template library — ready-to-use contracts for common roles and scenarios.

Usage::

    from ystar.templates import get_template, TEMPLATES
    from ystar import Policy

    policy = Policy({
        "rd":      get_template("rd"),
        "finance": get_template("finance", amount_limit=5000),
        "sales":   get_template("sales"),
    })

Available templates::

    rd, rd_strict, ops, ops_deploy,
    finance, finance_strict,
    sales, sales_outreach,
    manager, manager_approver,
    analyst, data_engineer,
    openclaw_agent, openclaw_researcher, openclaw_executor,
    clinician, reception,
    readonly, sandboxed
"""
from __future__ import annotations
from typing import Any, Dict
from ..template import from_template, TemplateResult

TEMPLATE_DICTS: Dict[str, Dict[str, Any]] = {

    "rd": {
        "_description": "R&D / software developer agent",
        "can_write_to": ["./workspace/"],
        "cannot_touch": [".env", "credentials", "production", "prod", "secret"],
        "cannot_run":   ["rm -rf", "git push --force", "npm publish",
                         "curl | bash", "wget | sh"],
    },
    "rd_strict": {
        "_description": "R&D agent with tighter path control",
        "can_write_to": ["./workspace/src/", "./workspace/tests/"],
        "cannot_touch": [".env", "credentials", "production", "prod",
                         "secret", "../", "/etc/"],
        "cannot_run":   ["rm -rf", "sudo", "git push --force", "npm publish",
                         "docker run --privileged", "chmod 777"],
        "required_roles": ["developer"],
    },
    "ops": {
        "_description": "DevOps / operations agent",
        "can_write_to": ["./deploy/", "./config/staging/"],
        "cannot_touch": [".env", "credentials", "/etc/passwd", "/etc/shadow"],
        "cannot_run":   ["rm -rf /", "sudo rm", "mkfs", "> /dev/"],
        "field_env_deny": ["production", "prod", "live"],
        "deny_env":       ["production", "prod"],
    },
    "ops_deploy": {
        "_description": "Deployment agent — controlled production access",
        "can_write_to": ["./deploy/"],
        "cannot_touch": ["credentials", ".env"],
        "cannot_run":   ["rm -rf /", "mkfs", "dd if="],
        "required_roles": ["operator", "deployer"],
        "max_calls_per_hour": 10,
    },
    "finance": {
        "_description": "Finance / accounting agent",
        "cannot_run":   ["DELETE FROM", "DROP TABLE", "TRUNCATE",
                         "UPDATE accounts SET"],
        "amount_min":   0.01,
        "amount_limit": 10000,
        "aggregate_param":     "amount",
        "aggregate_daily_max": 50000,
        "required_roles": ["finance"],
        "allowed_hours":  "08:00-18:00",
    },
    "finance_strict": {
        "_description": "Finance agent with approval gate",
        "cannot_run":   ["DELETE FROM", "DROP TABLE", "TRUNCATE"],
        "amount_min":   0.01,
        "amount_limit": 1000,
        "aggregate_param":     "amount",
        "aggregate_daily_max": 10000,
        "required_roles": ["finance", "approver"],
        "allowed_hours":  "09:00-17:00",
        "allowed_timezone": "America/New_York",
        "max_calls_per_hour": 20,
    },
    "sales": {
        "_description": "Sales / CRM agent",
        "can_call":     ["api.hubspot.com", "api.salesforce.com",
                         "api.stripe.com", "api.sendgrid.com"],
        "cannot_touch": ["192.168.", "10.", "localhost", "credentials", ".env"],
        "price_min":    0,
        "max_calls_per_hour": 200,
    },
    "sales_outreach": {
        "_description": "Sales outreach — email and CRM only",
        "can_call":     ["api.hubspot.com", "api.sendgrid.com",
                         "api.mailchimp.com"],
        "cannot_touch": ["192.168.", "10.", "payment", "billing"],
        "cannot_run":   ["DELETE FROM", "DROP"],
        "max_calls_per_hour": 100,
        "required_roles": ["sales"],
    },
    "manager": {
        "_description": "Manager / coordinator agent",
        "cannot_touch": ["/etc/", "/sys/", "credentials", ".env"],
        "cannot_run":   ["rm -rf", "sudo", "DROP TABLE", "DELETE FROM",
                         "kubectl delete", "terraform destroy"],
        "required_roles": ["manager"],
    },
    "manager_approver": {
        "_description": "Manager with approval authority",
        "cannot_touch": ["/etc/", "credentials"],
        "cannot_run":   ["rm -rf /", "mkfs"],
        "required_roles": ["manager", "approver"],
        "max_calls_per_hour": 50,
    },
    "analyst": {
        "_description": "Data analyst — read-only, no mutations",
        "cannot_run":   ["DELETE FROM", "DROP TABLE", "UPDATE",
                         "INSERT", "TRUNCATE", "ALTER TABLE"],
        "cannot_touch": ["credentials", ".env", "production_write"],
        "field_env_deny": ["production", "prod"],
        "required_roles": ["analyst"],
    },
    "data_engineer": {
        "_description": "Data engineer — staging write, production read-only",
        "cannot_run":   ["DROP TABLE", "TRUNCATE", "DELETE FROM production"],
        "cannot_touch": ["credentials", ".env"],
        "field_env_deny": ["production"],
        "required_roles": ["data_engineer"],
    },
    "openclaw_agent": {
        "_description": "Generic OpenClaw sub-agent",
        "can_write_to": ["./workspace/"],
        "cannot_touch": [".env", "credentials", "production", "secret"],
        "cannot_run":   ["rm -rf", "sudo", "chmod 777", "curl | bash"],
        "max_calls_per_hour": 500,
    },
    "openclaw_researcher": {
        "_description": "OpenClaw research agent — web access, no writes",
        "cannot_touch": ["credentials", ".env", "192.168.", "10.0."],
        "cannot_run":   ["rm", "sudo", "DELETE", "DROP"],
        "max_calls_per_hour": 300,
    },
    "openclaw_executor": {
        "_description": "OpenClaw execution agent — controlled write access",
        "can_write_to": ["./workspace/output/"],
        "cannot_touch": [".env", "credentials", "production", "../"],
        "cannot_run":   ["rm -rf", "sudo", "git push --force"],
        "required_roles": ["executor"],
        "max_calls_per_hour": 100,
    },
    "clinician": {
        "_description": "Clinical staff — patient records access",
        "can_call":     ["ehr.internal", "lab.internal", "imaging.internal"],
        "cannot_touch": ["billing_admin", "system_config"],
        "cannot_run":   ["DELETE FROM patients", "DROP TABLE", "TRUNCATE"],
        "required_roles": ["clinician"],
        "allowed_hours":  "06:00-22:00",
    },
    "reception": {
        "_description": "Reception / administrative staff",
        "cannot_touch": ["patient_records", "lab_results", "medications",
                         "clinical_notes"],
        "cannot_run":   ["DELETE FROM", "DROP TABLE"],
        "required_roles": ["reception"],
    },
    "readonly": {
        "_description": "Read-only agent — no writes, no mutations",
        "cannot_run":   ["rm", "delete", "drop", "truncate", "insert",
                         "update", "write", "mkdir"],
        "cannot_touch": [".env", "credentials", "secret", "password"],
    },
    "sandboxed": {
        "_description": "Fully sandboxed — minimal permissions",
        "can_write_to": ["./sandbox/"],
        "cannot_touch": [".env", "credentials", "secret", "/etc/",
                         "/sys/", "../", "production"],
        "cannot_run":   ["rm -rf", "sudo", "chmod", "chown",
                         "curl | bash", "wget | sh"],
        "max_calls_per_hour": 50,
    },
}


def get_template(name: str, **overrides) -> TemplateResult:
    """
    Get a built-in template by name, with optional overrides.

    Example::

        policy = Policy({
            "rd":      get_template("rd"),
            "finance": get_template("finance", amount_limit=5000),
        })
    """
    if name not in TEMPLATE_DICTS:
        available = ", ".join(sorted(TEMPLATE_DICTS))
        raise KeyError(f"Template '{name}' not found. Available: {available}")
    tpl = {k: v for k, v in TEMPLATE_DICTS[name].items()
           if not k.startswith("_")}
    tpl.update(overrides)
    return from_template(tpl)


def get_template_dict(name: str) -> Dict[str, Any]:
    """Return raw template dict for inspection or customisation."""
    if name not in TEMPLATE_DICTS:
        available = ", ".join(sorted(TEMPLATE_DICTS))
        raise KeyError(f"Template '{name}' not found. Available: {available}")
    return {k: v for k, v in TEMPLATE_DICTS[name].items()
            if not k.startswith("_")}


TEMPLATES = list(TEMPLATE_DICTS.keys())

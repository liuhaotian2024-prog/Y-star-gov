# ystar/governance/grant_chain.py
# Copyright (C) 2026 Haotian Liu -- MIT License
"""
Grant Chain -- Single-use, TTL-bounded dispatch grants (AMENDMENT-015 Layer 2)

Solves the CEO->engineer spawn deadlock:
  1. must_dispatch_via_cto hook denies CEO direct spawn of eng-*
  2. CTO sub-agent cannot nested-spawn engineers (Claude Code structural block)
  3. Grant chain: CTO issues a grant -> CEO consumes it on spawn -> hook allows

Flow:
  CTO sub-agent:  grant_chain issue --grantor cto --grantee ceo \
                    --target_agent eng-platform --atomic_id CZL-XXX --ttl 1800
  CEO main line:  Agent(subagent_type=Ryan-Platform, ...)
  Hook:           check_grant(cto, ceo, eng-platform, CZL-XXX) -> True -> ALLOW
                  consume_grant(grant_id) -> single-use burned

Storage: .ystar_active_grant.json  (list of active grants)
Audit:   .ystar_grant_audit.jsonl  (append-only audit trail)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

_log = logging.getLogger("ystar.grant_chain")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[Y*grant] %(levelname)s %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Paths -- workspace-relative by default, overridable via env
# ---------------------------------------------------------------------------

_WORKSPACE = Path(
    os.environ.get(
        "YSTAR_WORKSPACE",
        os.path.expanduser("~/.openclaw/workspace/ystar-company"),
    )
)
GRANT_FILE = _WORKSPACE / ".ystar_active_grant.json"
AUDIT_FILE = _WORKSPACE / ".ystar_grant_audit.jsonl"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Grant:
    grant_id: str
    grantor: str          # who issues (e.g. "cto")
    grantee: str          # who can consume (e.g. "ceo")
    target_agent: str     # spawn target (e.g. "eng-platform", "Ryan-Platform")
    atomic_id: str        # task-level scope (e.g. "CZL-BRAIN-L2-WRITEBACK-IMPL")
    issued_at: float      # epoch
    ttl_seconds: int
    expires_at: float
    consumed: bool = False
    consumed_at: Optional[float] = None

    def is_expired(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return now >= self.expires_at

    def is_valid(self, now: Optional[float] = None) -> bool:
        return not self.consumed and not self.is_expired(now)


# ---------------------------------------------------------------------------
# CIEU helper (silent-fail)
# ---------------------------------------------------------------------------

def _emit_cieu(event_type: str, **kwargs) -> None:
    """Emit CIEU event. Silent-fail -- never break caller."""
    try:
        from ystar.kernel.cieu import emit
        emit(event_type, **kwargs)
    except Exception:
        _log.debug("CIEU emit failed (non-fatal)", exc_info=True)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _read_grants() -> List[dict]:
    """Read active grants from file. Returns [] if missing/corrupt."""
    if not GRANT_FILE.exists():
        return []
    try:
        with open(GRANT_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        _log.warning("Corrupt grant file, returning empty list")
        return []


def _write_grants(grants: List[dict]) -> None:
    """Atomic write of grant list."""
    tmp = GRANT_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(grants, f, indent=2)
    os.replace(tmp, GRANT_FILE)


def _append_audit(record: dict) -> None:
    """Append to JSONL audit trail."""
    try:
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        _log.warning("Failed to write audit record", exc_info=True)


def _grant_from_dict(d: dict) -> Grant:
    return Grant(
        grant_id=d["grant_id"],
        grantor=d["grantor"],
        grantee=d["grantee"],
        target_agent=d["target_agent"],
        atomic_id=d["atomic_id"],
        issued_at=d["issued_at"],
        ttl_seconds=d["ttl_seconds"],
        expires_at=d["expires_at"],
        consumed=d.get("consumed", False),
        consumed_at=d.get("consumed_at"),
    )


# ---------------------------------------------------------------------------
# Target agent matching -- normalize aliases
# ---------------------------------------------------------------------------

_AGENT_ALIASES = {
    "ryan-platform": "eng-platform",
    "leo-kernel": "eng-kernel",
    "maya-governance": "eng-governance",
    "jordan-domains": "eng-domains",
}


def _normalize_agent(name: str) -> str:
    """Normalize agent name to canonical form for matching."""
    lower = name.lower().strip()
    return _AGENT_ALIASES.get(lower, lower)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def issue_grant(
    grantor: str,
    grantee: str,
    target_agent: str,
    atomic_id: str,
    ttl_seconds: int = 1800,
) -> Grant:
    """
    Issue a new single-use grant.

    Args:
        grantor: Issuing authority (e.g. "cto")
        grantee: Who can consume (e.g. "ceo")
        target_agent: Spawn target (e.g. "eng-platform" or "Ryan-Platform")
        atomic_id: Task scope identifier
        ttl_seconds: Time-to-live in seconds (default 30 min)

    Returns:
        The issued Grant object.
    """
    now = time.time()
    grant = Grant(
        grant_id=str(uuid.uuid4()),
        grantor=grantor,
        grantee=grantee,
        target_agent=_normalize_agent(target_agent),
        atomic_id=atomic_id,
        issued_at=now,
        ttl_seconds=ttl_seconds,
        expires_at=now + ttl_seconds,
    )

    grants = _read_grants()
    grants.append(asdict(grant))
    _write_grants(grants)

    audit = {
        "action": "GRANT_ISSUED",
        "ts": now,
        **asdict(grant),
    }
    _append_audit(audit)

    _emit_cieu(
        "GRANT_ISSUED",
        grant_id=grant.grant_id,
        grantor=grantor,
        grantee=grantee,
        target_agent=grant.target_agent,
        atomic_id=atomic_id,
        ttl_seconds=ttl_seconds,
    )

    _log.info(
        f"GRANT_ISSUED: {grantor}->{grantee} target={grant.target_agent} "
        f"atomic={atomic_id} ttl={ttl_seconds}s id={grant.grant_id}"
    )
    return grant


def check_grant(
    grantor: str,
    grantee: str,
    target_agent: str,
    atomic_id: Optional[str] = None,
    now: Optional[float] = None,
) -> Optional[Grant]:
    """
    Check if a valid (non-expired, non-consumed) grant exists.

    If atomic_id is None, matches any atomic_id for the given
    grantor/grantee/target_agent triple.

    Returns the matching Grant if found, else None.
    """
    now = now or time.time()
    norm_target = _normalize_agent(target_agent)
    grants = _read_grants()

    for d in grants:
        g = _grant_from_dict(d)
        if (
            g.grantor == grantor
            and g.grantee == grantee
            and g.target_agent == norm_target
            and (atomic_id is None or g.atomic_id == atomic_id)
            and g.is_valid(now)
        ):
            return g
    return None


def consume_grant(grant_id: str) -> bool:
    """
    Consume (burn) a grant by ID. Single-use: second call returns False.

    Returns True if consumed, False if already consumed or not found.
    """
    now = time.time()
    grants = _read_grants()
    consumed = False

    for d in grants:
        if d["grant_id"] == grant_id:
            if d.get("consumed", False):
                _log.warning(f"Grant {grant_id} already consumed -- noop")
                _emit_cieu(
                    "GRANT_CONSUME_DUPLICATE",
                    grant_id=grant_id,
                )
                return False
            d["consumed"] = True
            d["consumed_at"] = now
            consumed = True
            break

    if not consumed:
        _log.warning(f"Grant {grant_id} not found")
        return False

    _write_grants(grants)

    _append_audit({
        "action": "GRANT_CONSUMED",
        "ts": now,
        "grant_id": grant_id,
    })
    _emit_cieu(
        "GRANT_CONSUMED",
        grant_id=grant_id,
    )
    _log.info(f"GRANT_CONSUMED: {grant_id}")
    return True


def expire_stale_grants() -> int:
    """
    Sweep expired grants: mark them consumed (prevents future use)
    and append audit records. Returns count of newly expired grants.
    """
    now = time.time()
    grants = _read_grants()
    expired_count = 0

    for d in grants:
        g = _grant_from_dict(d)
        if g.is_expired(now) and not g.consumed:
            d["consumed"] = True
            d["consumed_at"] = now
            expired_count += 1
            _append_audit({
                "action": "GRANT_EXPIRED",
                "ts": now,
                "grant_id": g.grant_id,
            })
            _emit_cieu(
                "GRANT_EXPIRED",
                grant_id=g.grant_id,
                grantor=g.grantor,
                grantee=g.grantee,
                target_agent=g.target_agent,
            )

    if expired_count:
        _write_grants(grants)
        _log.info(f"Expired {expired_count} stale grant(s)")

    return expired_count




def find_recently_consumed(
    grantor: str,
    grantee: str,
    target_agent: str,
    window_seconds: int = 300,
    now: Optional[float] = None,
) -> Optional[Grant]:
    """
    Find a grant that was recently consumed (within window_seconds).

    This handles the idempotent retry case: Claude Code may fire the hook
    multiple times for a single Agent call. If a grant was consumed in
    the recent past for the same grantor/grantee/target, we treat the
    second check as a valid retry rather than denying.

    Returns the consumed Grant if found within window, else None.
    """
    now = now or time.time()
    norm_target = _normalize_agent(target_agent)
    grants = _read_grants()

    for d in grants:
        g = _grant_from_dict(d)
        if (
            g.grantor == grantor
            and g.grantee == grantee
            and g.target_agent == norm_target
            and g.consumed
            and g.consumed_at is not None
            and (now - g.consumed_at) < window_seconds
        ):
            return g
    return None

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI: python3 -m ystar.governance.grant_chain <command> [args]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="ystar.governance.grant_chain",
        description="Grant Chain -- single-use dispatch authorization",
    )
    sub = parser.add_subparsers(dest="command")

    # issue
    p_issue = sub.add_parser("issue", help="Issue a new grant")
    p_issue.add_argument("--grantor", required=True)
    p_issue.add_argument("--grantee", required=True)
    p_issue.add_argument("--target_agent", required=True)
    p_issue.add_argument("--atomic_id", required=True)
    p_issue.add_argument("--ttl", type=int, default=1800, help="TTL seconds")

    # check
    p_check = sub.add_parser("check", help="Check if a valid grant exists")
    p_check.add_argument("--grantor", required=True)
    p_check.add_argument("--grantee", required=True)
    p_check.add_argument("--target_agent", required=True)
    p_check.add_argument("--atomic_id", default=None)

    # consume
    p_consume = sub.add_parser("consume", help="Consume a grant by ID")
    p_consume.add_argument("--grant_id", required=True)

    # sweep
    sub.add_parser("sweep", help="Expire stale grants")

    # list
    sub.add_parser("list", help="List all grants")

    args = parser.parse_args()

    if args.command == "issue":
        g = issue_grant(
            grantor=args.grantor,
            grantee=args.grantee,
            target_agent=args.target_agent,
            atomic_id=args.atomic_id,
            ttl_seconds=args.ttl,
        )
        print(json.dumps(asdict(g), indent=2))

    elif args.command == "check":
        g = check_grant(
            grantor=args.grantor,
            grantee=args.grantee,
            target_agent=args.target_agent,
            atomic_id=args.atomic_id,
        )
        if g:
            print(json.dumps(asdict(g), indent=2))
            sys.exit(0)
        else:
            print('{"valid": false}')
            sys.exit(1)

    elif args.command == "consume":
        ok = consume_grant(args.grant_id)
        print(json.dumps({"consumed": ok}))
        sys.exit(0 if ok else 1)

    elif args.command == "sweep":
        n = expire_stale_grants()
        print(json.dumps({"expired_count": n}))

    elif args.command == "list":
        grants = _read_grants()
        now = time.time()
        for d in grants:
            g = _grant_from_dict(d)
            status = "CONSUMED" if g.consumed else ("EXPIRED" if g.is_expired(now) else "ACTIVE")
            d["_status"] = status
        print(json.dumps(grants, indent=2))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

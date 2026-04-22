#!/usr/bin/env python3
"""
boot_parent_session_register.py — Register parent session as TrackedEntity
===========================================================================

Called during governance_boot.sh to register the CEO parent session
as an entity in the OmissionEngine, enabling self-governance.

Board directive: CZL-PARENT-SESSION-REGISTER-AS-ENTITY (2026-04-20)

Usage:
    python3 scripts/boot_parent_session_register.py [session_json_path]

Exit codes:
    0 = success (entity registered + obligations created)
    1 = failure (import error, missing session, etc.)
"""
from __future__ import annotations

import json
import os
import sys
import time

# Add Y-star-gov to path
YGOV_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if YGOV_PATH not in sys.path:
    sys.path.insert(0, YGOV_PATH)

COMPANY_ROOT = "/Users/haotianliu/.openclaw/workspace/ystar-company"
DEFAULT_SESSION_JSON = os.path.join(COMPANY_ROOT, ".ystar_session.json")


def main() -> int:
    session_json_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SESSION_JSON

    # 1. Read session_id from .ystar_session.json
    if not os.path.exists(session_json_path):
        print(f"[PARENT_REGISTER] ERROR: session file not found: {session_json_path}")
        return 1

    try:
        with open(session_json_path) as f:
            session_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[PARENT_REGISTER] ERROR: cannot read session file: {e}")
        return 1

    session_id = session_data.get("session_id", "unknown")
    agent_id = session_data.get("agent_id", "ceo")

    # 2. Import governance components
    try:
        from ystar.governance.omission_engine import OmissionEngine
        from ystar.governance.omission_store import InMemoryOmissionStore
        from ystar.governance.omission_models import EntityStatus
        from ystar.governance.parent_session_rules import (
            create_parent_entity,
            create_parent_obligations,
            register_parent_session_rules,
        )
        from ystar.governance.omission_rules import get_registry
    except ImportError as e:
        print(f"[PARENT_REGISTER] ERROR: import failed: {e}")
        return 1

    # 3. Register parent session rules into global registry
    registry = get_registry()
    rule_count = register_parent_session_rules(registry)

    # 4. Create the parent entity
    entity = create_parent_entity(session_id=session_id, agent_id=agent_id)

    # 5. Create store + engine and register
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store)
    engine.register_entity(entity)

    # 6. Create and register obligations
    obligations = create_parent_obligations(
        entity_id=entity.entity_id,
        actor_id=agent_id,
        session_id=session_id,
    )
    for ob in obligations:
        store.add_obligation(ob)

    # 7. Verify
    registered_entity = store.get_entity(entity.entity_id)
    registered_obligations = store.list_obligations(entity_id=entity.entity_id)

    if registered_entity is None:
        print("[PARENT_REGISTER] ERROR: entity registration verification failed")
        return 1

    if len(registered_obligations) != 4:
        print(f"[PARENT_REGISTER] ERROR: expected 4 obligations, got {len(registered_obligations)}")
        return 1

    # 8. Report success
    print(f"[PARENT_REGISTER] OK entity_id={entity.entity_id} "
          f"entity_type={entity.entity_type} "
          f"status={entity.status.value} "
          f"obligations={len(registered_obligations)} "
          f"rules_registered={rule_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

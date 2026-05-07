# E83 CEO Cognitive OS Auto-Guidance Topology Audit

E83 confirms that the CEO Cognitive OS validator belongs in
`ystar/governance/ceo_cognitive_os_contract.py`, but its E82 decision semantics
were too flat.

## Mainline Topology

- Public API: `ystar/__init__.py` exports kernel `check`, `enforce`,
  `IntentContract`, `CheckResult`, `EnforcementResult`, and governance services.
- Contract layer: `ystar/kernel/dimensions.py` owns `IntentContract`,
  `HigherOrderContract`, `ConstitutionalContract`, `PolicySourceTrust`, contract
  hashes, and lifecycle status.
- Runtime check layer: `ystar/kernel/engine.py` owns generic deterministic
  `check()` / `enforce()` behavior for intent contracts.
- Governance packet layer: `ystar/governance/pre_u_packet_validator.py`,
  `cieu_prediction_delta.py`, `contract_dry_run.py`, and
  `hook_contract_adapter.py` own pre-action validation, prediction-delta
  validation, dry-run decision envelopes, and hook-like dry-run adapters.
- Hook boundary: `ystar/adapters/hook.py` owns real PreToolUse integration and
  already supports deny/escalate/redirect/rewrite/invoke style correction paths.
- CIEU persistence: `ystar/governance/cieu_store.py` owns live CIEU storage;
  E83 does not write to it.

## Auto-Guidance Lineage

Repository evidence shows the canonical repairable-failure vocabulary is
`require_revision`.

- `pre_u_packet_validator.py` returns `REQUIRE_REVISION` with
  `required_revisions` for repairable packet gaps.
- `cieu_prediction_delta.py` returns `REQUIRE_REVISION` for repairable
  prediction-delta gaps.
- `contract_dry_run.py` maps not-ready Pre-U/delta states to
  `require_revision` without executing selected actions.
- `hook_contract_adapter.py` maps dry-run `require_revision` to a hook-like
  envelope containing `require_revision: true`.
- `docs/hook_cli_contract_compatibility.md` documents exit code `2` for
  `require_revision`.
- `ystar/domains/openclaw/adapter.py` and `ystar/adapters/hook.py` also contain
  `REDIRECT`, `REWRITE`, and structured guidance paths for repairable runtime
  correction.

## E83 Patch

E83 updates the CEO Cognitive OS validator to preserve hard `DENY` for bypass,
forbidden claims, and duplicate core mechanism proposals while returning
`REQUIRE_REVISION` for repairable missing packet fields, missing loop stages,
missing evidence, missing counterfactuals, missing CIEU prediction, missing
adversarial critique, missing what-not-to-do, and missing no-new-wheel proof.

Complete but owner-approval-pending L4/external execution now returns
`ESCALATE` with an owner decision path rather than `DENY`.

No hook runtime wiring, live CIEU DB writes, provider execution, or external
action is performed by this patch.

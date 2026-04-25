# Counterfactual CZL Asset Map

Generated from local checkout: `/Users/haotianliu/.openclaw/workspace/Y-star-gov`
Generated at: `2026-04-25T15:59:56.244594Z`

Purpose: inventory existing assets before implementing the Counterfactual CZL Company Runtime upgrade.

This file intentionally maps what already exists so future work extends existing modules instead of rebuilding them.

Note: Company-level CEO reports, role-runtime strategy specs, and goal-tree seed files may live in `ystar-bridge-labs`; this Y-star-gov asset map only inventories assets present in the canonical kernel repository.

## Residual Loop / RLE

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| Residual Loop / RLE | `ystar/governance/residual_loop_engine.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/residual_loop_engine.py` |
| Residual Loop / RLE | `tests/test_residual_loop_engine.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/test_residual_loop_engine.py` |
| Residual Loop / RLE | `tests/demo_rle_e2e.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/demo_rle_e2e.py` |
| Residual Loop / RLE | `tests/demo_rle_path_a_bridge.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/demo_rle_path_a_bridge.py` |

## CIEU

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| CIEU | `ystar/governance/cieu_store.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/cieu_store.py` |
| CIEU | `tests/test_cieu_store.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/test_cieu_store.py` |
| CIEU | `tests/test_archive_cieu.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/test_archive_cieu.py` |

## Memory

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| Memory | `ystar/memory/__init__.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/memory/__init__.py` |
| Memory | `ystar/memory/models.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/memory/models.py` |
| Memory | `ystar/memory/store.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/memory/store.py` |
| Memory | `ystar/memory/ingest.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/memory/ingest.py` |
| Memory | `tests/test_memory_store.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/test_memory_store.py` |
| Memory | `tests/test_cieu_to_memory_ingest.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/test_cieu_to_memory_ingest.py` |

## Brain bridge

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| Brain bridge | `ystar/governance/brain_auto_ingest.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/brain_auto_ingest.py` |
| Brain bridge | `ystar/governance/brain_dream_scheduler.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/brain_dream_scheduler.py` |
| Brain bridge | `ystar/governance/cieu_brain_alignment.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/cieu_brain_alignment.py` |
| Brain bridge | `ystar/governance/cieu_brain_bridge.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/cieu_brain_bridge.py` |
| Brain bridge | `ystar/governance/cieu_brain_learning.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/cieu_brain_learning.py` |
| Brain bridge | `ystar/governance/cieu_brain_streamer.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/cieu_brain_streamer.py` |
| Brain bridge | `scripts/cieu_to_brain_batch.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e scripts/cieu_to_brain_batch.py` |
| Brain bridge | `scripts/cieu_brain_daemon.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e scripts/cieu_brain_daemon.py` |
| Brain bridge | `scripts/cieu_brain_learning_cycle.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e scripts/cieu_brain_learning_cycle.py` |
| Brain bridge | `tests/governance/test_brain_auto_ingest.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/governance/test_brain_auto_ingest.py` |
| Brain bridge | `tests/governance/test_brain_cieu_events_dream.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/governance/test_brain_cieu_events_dream.py` |
| Brain bridge | `tests/governance/test_cieu_brain_alignment.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/governance/test_cieu_brain_alignment.py` |
| Brain bridge | `tests/governance/test_cieu_brain_bridge.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/governance/test_cieu_brain_bridge.py` |
| Brain bridge | `tests/governance/test_cieu_brain_learning.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/governance/test_cieu_brain_learning.py` |
| Brain bridge | `tests/governance/test_cieu_brain_streamer.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/governance/test_cieu_brain_streamer.py` |

## Y* / field-functional / goal contribution

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| Y* / field-functional / goal contribution | `ystar/governance/y_star_field_validator.py` | Existing asset found | PARTIAL | yes | Inspect and extend in-place | `test -e ystar/governance/y_star_field_validator.py` |
| Y* / field-functional / goal contribution | `reports/ceo/phase2_goal_tree_seed_20260423.sql` | Not found in this checkout | UNKNOWN | no | Do not create duplicate until path is confirmed | `test -e reports/ceo/phase2_goal_tree_seed_20260423.sql` |

## Omission governance

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| Omission governance | `ystar/governance/omission_engine.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/omission_engine.py` |
| Omission governance | `ystar/governance/omission_rules.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/omission_rules.py` |
| Omission governance | `ystar/governance/omission_models.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e ystar/governance/omission_models.py` |
| Omission governance | `tests/test_omission_engine.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/test_omission_engine.py` |
| Omission governance | `tests/governance/test_omission_engine_cieu_persistence.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/governance/test_omission_engine_cieu_persistence.py` |

## Role runtime

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| Role runtime | `governance/role_runtimes/ceo.yaml` | Existing asset found | SPEC-ONLY | yes | Inspect and extend in-place | `test -e governance/role_runtimes/ceo.yaml` |
| Role runtime | `reports/ceo/role_runtime_framework_v0.1_spec_20260424.md` | Not found in this checkout | UNKNOWN | no | Do not create duplicate until path is confirmed | `test -e reports/ceo/role_runtime_framework_v0.1_spec_20260424.md` |
| Role runtime | `reports/ceo/ceo_runtime_v0.1_spec_20260424.md` | Not found in this checkout | UNKNOWN | no | Do not create duplicate until path is confirmed | `test -e reports/ceo/ceo_runtime_v0.1_spec_20260424.md` |

## gov-mcp integration references

| Area | File path | Current capability | Current status | Should extend? yes/no | Recommended next step | Relevant tests or verification command |
|---|---|---|---|---|---|---|
| gov-mcp integration references | `tests/test_gov_mcp_delegation.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e tests/test_gov_mcp_delegation.py` |
| gov-mcp integration references | `skill/skills/ystar-govern/check.py` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e skill/skills/ystar-govern/check.py` |
| gov-mcp integration references | `skill/skills/ystar-report/SKILL.md` | Existing asset found | PARTIAL/LIVE | yes | Inspect and extend in-place | `test -e skill/skills/ystar-report/SKILL.md` |

## Implementation order recommended

1. ObservationStack
2. YStarProjector
3. CounterfactualCZLPlanner L0
4. RLE pre/post bridge
5. gov-mcp tool integration
6. heterogeneous role-runtime rollout

## Verification commands

```bash
git diff --stat
python3 -m py_compile ystar/governance/residual_loop_engine.py
python3 -m py_compile ystar/governance/y_star_field_validator.py
pytest tests/test_residual_loop_engine.py -q
```

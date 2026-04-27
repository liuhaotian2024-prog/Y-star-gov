# CIEU Prediction-Delta Schema v0

This document defines the v0 structural schema for post-action
prediction-vs-actual delta records.

The validator lives at `ystar/governance/cieu_prediction_delta.py`.

## Purpose

Pre-U packets declare predicted `Yt+1` and predicted `Rt+1`. After action, CIEU
needs a structured record that links those predictions to actual outcome,
actual residual, and future evidence-backed learning eligibility.

This schema supports:

```text
Pre-U predicted outcome
  -> actual CIEU outcome
  -> predicted-vs-actual delta
  -> residual evidence
  -> future curated brain writeback candidate
```

## Minimal Record Shape

- `event_id`
- `packet_id`
- `agent_id` or `role_id`
- `recorded_at` or `timestamp`
- `declared_y_star`
- `selected_u`
- `predicted_y_t1`
- `predicted_r_t1`
- `x_t`
- `u`
- `actual_y_t1`
- `actual_r_t1`
- `delta_summary`
- `residual_delta`
- `delta_class` or `deviation_class`
- `learning_eligibility`
- `cieu_event_ref` or `cieu_record_ref`
- `governance_decision_ref` or `validator_result_ref`
- `brain_writeback_policy`

## Decisions

The validator returns:

- `allow`
- `warn`
- `require_revision`
- `deny`
- `escalate`

Missing critical linkage, prediction, actual outcome, residual, learning
eligibility, CIEU reference, or writeback policy requires revision. Automatic
uncurated direct brain writeback is denied. High-risk unresolved deltas
escalate.

## Relationship To Pre-U Packet Validator

The Pre-U validator checks whether a packet is structurally ready before action.
This prediction-delta validator checks whether the post-action record can safely
connect predictions to actual outcomes.

## Relationship To CIEU

This milestone defines record structure only. It does not write CIEU events,
change CIEU DB schema, or query any database.

## Relationship To Brain Nutrition

Prediction deltas may become future brain nutrition only after evidence-backed
curation. This schema explicitly rejects automatic uncurated direct writeback.

## Non-Goals

- No runtime CIEU writing.
- No DB access.
- No hook integration.
- No brain writeback.
- No semantic outcome judging.
- No artifact mining.

## Open Gaps

- No CIEU event writer integration.
- No DB schema migration.
- No predicted-vs-actual numeric scoring model.
- No hook-to-CIEU wiring.
- No curated brain writeback queue.
- No semantic verification of actual outcome truth.

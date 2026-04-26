# CIEU Contract

This contract describes future CIEU linkage for Pre-U packet validation. It does
not change CIEU schema yet.

Future CIEU requirements:

- Pre-action event should reference `packet_id`.
- Pre-action event should reference `validation_result_id`.
- Post-action event should reference actual `Yt+1`.
- Post-action event should reference actual `Rt+1`.
- Predicted vs actual delta should be computable later.
- Invalid packet should still be eligible for governance evidence logging.
- CIEU must not treat speculative predictions as actual outcomes.
- Brain writeback should use evidence-backed deltas only.

Suggested future relationship:

```text
packet_id
  -> validation_result_id
  -> hook_decision
  -> action_result
  -> actual_y_t1 / actual_r_t1
  -> predicted_vs_actual_delta
  -> brain_nutrition_candidate
```

This preserves CIEU as evidence and teaching substrate, not as a source of
unaudited speculation.

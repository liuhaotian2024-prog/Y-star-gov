# Validation Matrix

| Check ID | Check | Deterministic now? | Future semantic? | Owner | Failure action | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| PREU-SCHEMA | Packet conforms to expected schema. | Yes | No | Y-star-gov validator | deny | Uses labs packet schema as source contract. |
| PREU-AGENT-ID | `agent_id` is valid for the packet/capsule. | Yes | Possible registry scope | Y-star-gov validator | deny | Intended Aiden value is `Aiden-CEO`. |
| PREU-TASK-ID | `task_id` is present and traceable. | Yes | No | Y-star-gov validator | require_revision | Missing task id breaks audit traceability. |
| PREU-Y-STAR | Y* is present. | Yes | Mission grounding | Y-star-gov validator | require_revision | Future check should ensure grounding, not just text. |
| PREU-M-FUNCTOR | `m_functor` is present. | Yes | Field grounding | Y-star-gov validator / field validator | require_revision | Future validation should route to Y* Field semantics. |
| PREU-XT | `x_t_summary` is present. | Yes | Evidence discipline | Y-star-gov validator | warn | Empty current-state summary weakens predictions. |
| PREU-CANDIDATES | Candidate actions exist and are non-empty. | Yes | Boundedness | Y-star-gov validator | deny | Packet without candidates is not counterfactual. |
| PREU-SELECTED-U | Selected action references an existing candidate. | Yes | Selection consistency | Y-star-gov validator | deny | Referential integrity is deterministic. |
| PREU-PREDICTED-R | Predicted Rt+1 exists for each candidate. | Yes | Residual quality | Y-star-gov validator | deny | Residual minimization requires predicted residuals. |
| PREU-RESIDUAL-RATIONALE | Selection rationale references residual minimization. | Yes | Quality of rationale | Y-star-gov validator | require_revision | Rationale must explain closeness to Rt+1 = 0. |
| PREU-RISK-TIER | Risk/high-risk review fields are present and compatible. | Yes | Escalation policy | Y-star-gov validator + hook | escalate | High-risk action requires stricter treatment. |
| PREU-NO-ACTUAL-CLAIM | Packet does not claim actual outcome before action. | No | Yes | Y-star-gov validator | require_revision | Prediction must stay distinct from evidence. |
| PREU-NO-FORBIDDEN-MUTATION | Packet does not hide DB/log/runtime mutation intent. | No | Yes | Y-star-gov validator + boundary enforcer | deny | Especially important for Tier 4. |
| PREU-CIEU-LINK | CIEU link policy is present. | Yes | Event compatibility | Y-star-gov validator + CIEU | require_revision | Later CIEU schema should define exact event shape. |
| PREU-HOOK-HINT | Hook decision hint can be derived from validation result. | Yes | Risk policy | Y-star-gov validator | warn | Hook consumes hint; hook remains enforcer. |
| PREU-GOODHART | Packet is not fake-aligned to Y* while optimizing wrong target. | No | Yes | Y-star-gov validator / field validator | escalate | Future semantic check; not implemented here. |
| PREU-OMISSION | Packet absence for required risk tier is treated as omission. | No | Yes | Y-star-gov validator / omission engine | deny | Future hook/omission integration needed. |

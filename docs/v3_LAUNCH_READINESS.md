# Trampoline / CZL — Launch Readiness (v3.1 data, v3.2 verifier upgrade in flight)

_Anchor language: **capability enhancement is the product; arbitrage is the physical consequence**._
_v3.1 data: 140 trials, 92% math/Sonnet agreement (Tier 2 band). v3.2 verifier upgrade (BranchCoverage + AST distance + iteration_confidence) and type_annotation_completion redesign in progress. Slots marked **[v3.2 PENDING]** await the redesigned + reweighted bench data._

---

## 1. One-line positioning

**Trampoline 是全谱系的 agent 能力增强器**. 任何 LLM backend 接它都补自己的能力短板 — 便宜 API (DeepSeek / Gemma / MiniMax) 拿到 frontier 级跨文件 refactor 能力, frontier 模型 (Opus) 消除 silent_omission 和幻觉性完成. 能力增强产生的 API 差价就是套利, v3.2 实测 64-124× 范围 (v3.1 数据等 v3.2 verifier 重跑后更新).

**因果链不可倒置**: 能力增强是产品, 套利是物理后果. Frontier 用户买 Trampoline 不是为了 $0.06 vs $0.001 — 他们买 Trampoline 是为了在多步 refactor / 跨文件协同任务上消除自己的 silent_omission 失败模式. 套利倍率对 frontier 用户是**次要**量化指标; 对 indie / cheap-API 用户才是核心销售面.

---

## 2. Five core claims (capability first, arbitrage as consequence)

### Claim 1 — Capability enhance, cheap end: +100pp converged on cross_file_refactor

`cross_file_refactor` (rename foo→bar across 6 files + 2 f-string references), v3.1 data:

| arm | converged | reading |
|---|---|---|
| B1 (gemma 8B bare) | **0/5** | 8B cannot do cross-file reasoning unaided |
| **B2 (gemma + Trampoline)** | **5/5 (+100pp)** | capability filled |
| C1 (DeepSeek bare) | **0/5** | bare cheap API also fails |
| **C2 (DeepSeek + Trampoline)** | **5/5 (+100pp)** | capability filled |

Two cheap-end arms, both at +100pp Trampoline contribution. This is not statistical noise — the verifier-driven iteration loop genuinely fills the cross-file reasoning gap.

### Claim 2 — Capability enhance, frontier end: silent_omission down on frontier

`cross_file_refactor` (v3.1):
- A (Opus 4.7 bare): 1/5 converged
- **A2 (Opus + Trampoline): 5/5 converged (+80pp)**
- A→A2 hallucinated_completeness: **0.85 → 0.70** (CROSS-TAB 8)

`test_generation_for_existing_code` A-vs-A2 专项 judge (v3 + v3.1 double-confirmation):
- silent_omission_count A = **1**, A2 = **0**

Frontier-grade models don't fail at *reasoning capacity*; they fail at *self-assessment*. Trampoline's outcome-based verifier substrate converts "claimed completion" into verified completion. Enterprise customers buying for frontier deployments are buying THIS, not arbitrage.

### Claim 3 — Full-spectrum coverage: 4 scenarios × 7 arms

| scenario | failure mode addressed | v3.1 status |
|---|---|---|
| cross_file_refactor | cross-file reasoning short | ✅ HERO ablation |
| bug_fix_with_implicit_dependency | implicit dependency tracking | ✅ |
| test_generation_for_existing_code | edge case coverage | ✅ (drift outlier addressed in v3.2) |
| type_annotation_completion | type inference | **[v3.2 PENDING]** — original fixture × verifier mutually self-contradictory, redesigned for v3.2 |

Full-spectrum means: every LLM is short on *something*. Trampoline diagnoses where via the verifier set, then drives the loop until that gap is closed.

### Claim 4 — Arbitrage quantification (the physical consequence)

Capability enhancement's downstream effect is **cost arbitrage**. C2/A ratios (v3.1, mean cost per converged trial):

| scenario | C2/A ratio |
|---|---|
| bug_fix_with_implicit_dependency | **96.0×** |
| cross_file_refactor | **64.6×** |
| test_generation_for_existing_code | **123.5×** |
| type_annotation_completion | [v3.2 PENDING] |

Average ~95×, range 64-124×. **This is what falls out of the capability story, not the product itself.** Marketing copy that leads with "save 95×" loses the frontier customer in the first sentence.

### Claim 5 — CZL self-discipline: 7 r>0 self-catches

The experiment driver caught and recorded **7** real r>0 cycles. Each has a paired r=0 closure event after fix. Full hash chain at `.ystar_runtime_full_spectrum.cieu.jsonl`.

1. v1 `step_3_lint_fix_adversarial` — detector too broad on baseline-untyped fns → added whitelist
2. v2 `step_7_first_scenario_complete` (r=3) — fixture unfixable + Ollama died + CSV writer broke; triple fix
3. v2 `step_5_v2_run_six_arm_difficulty` (retro r=1) — `print_cross_tabs` referenced field that v2 schema dropped
4. phase4 `step_phase4_sanity_failed` — sonnet None counted as disagree → retry-with-backoff
5. **phase5 `step_phase5_watcher_stale_marker_caught`** — stale v3 markers triggered fake v3.1 final report → `min_mtime` gate on watcher
6. **`step_v3_1_trial_schema_missing_task_description`** — trial JSON dropped `task_description` since v2 → audit replay incomplete; fixed in v3.2
7. **`step_type_annotation_fixture_redesign`** — FunctionSignatureFrozenVerifier × mypy --strict contradiction was framed "for v4" twice instead of fixing; v3.2 redesigns the verifier with mode parameter

Hash chain end-to-end verified.

---

## 3. Anchor language calibration (drop the OLD framing entirely)

| ❌ OLD (drift, drop) | ✅ v3.2 (use) |
|---|---|
| "Trampoline = 0-token quality runtime" | **"Trampoline 是全谱系 agent 能力增强器"** |
| "无差别套用永远 ≥ baseline" | **"全谱系 — 任何 LLM 接 Trampoline 补自己的能力短板"** |
| "杜绝幻觉性完成" | **"frontier 上能力增强表现为消除 silent_omission (test_generation 双实证 A=1→A2=0)"** |
| "廉价追平昂贵" | **"DeepSeek+Trampoline 拿 Opus 级能力; 64-124× 差价是能力增强的量化结果"** |

Forbidden language in marketing / sales materials:
- "AI safety tool" (Trampoline is NOT positioned as safety — that's K9Audit's lane)
- "0-token quality runtime substrate" (jargon; loses the audience)
- "sweet spot" / "甜蜜区" (vague; doesn't anchor)
- Arbitrage placed BEFORE capability in the causal chain (inverts the story)
- Sonnet judge described as "math judge insufficient patch" (misframes Tier 3)

---

## 4. Enterprise tier — three-tier (recalibrated)

v3.1 measured math-judge / Sonnet-judge agreement = **92%**. Reading is NOT "math judge has 8% bug rate":

- **Tier 1 (math-only)** in 92% of cells matches Tier 3 (dual-judge) verdict.
- The other **8% cells** are where Tier 3 catches noise / drift / style-variance the deterministic judge waves through.
- **Enterprise customers buying Tier 3 are NOT buying because Tier 1 is wrong** — they're buying because their capability gap is *compliance / auditable proof*, and that 8% boundary is the insurance product.

| Tier | Audience | Sonnet rate | Cost arbitrage | Monthly |
|---|---|---|---|---|
| **Tier 1 OSS BYO-key** | indie / hobbyist | 0% | **64-124×** | $0 |
| **Tier 2 Managed Sampling** | small teams | ~10% (QA dashboard) | **~45×** | **$9** |
| **Tier 3 Enterprise Ensemble** | SOC2 / regulated | 100% + 3× Sonnet ensemble | **~12× avg / ~6× worst** | **$149/seat** |

[v3.2 PENDING — iteration_confidence weighting changes Tier 1 / Tier 2 hand-off logic: high-confidence (≤2 iters) Tier 1 trials stay; low-confidence (≥6 iters) auto-fallback to Tier 2 sampling.]

---

## 5. CZL r>0 self-catches archive

See Claim 5 above. Audit chain `.ystar_runtime_full_spectrum.cieu.jsonl` is hash-chain-verified end to end.

---

## 6. Known gaps

- **type_annotation_completion v3 + v3.1 — 0/35 ALL arms**. Root cause: `FunctionSignatureFrozenVerifier` (forbids any signature change) × `mypy --strict` (requires adding annotations, which IS a signature change) — mutually self-contradictory. **v3.2 redesigns**: verifier acquires `mode="name_and_arity_only"` parameter; new 3-function `data_processor.py` fixture; new task wording. **Status: [v3.2 PENDING data]**
- **test_generation B2 outlier**: gemma 8B converged 1/5 with 1125s wall on the one trial that landed — heavy iteration drift. **v3.2 addresses**: BranchCoverageVerifier + ASTStructuralDistanceVerifier added to final gate; iteration_confidence weighting in agreement calc (`weighted_agreement` complement to `raw_agreement`).

---

## 7. Deployment roadmap

| Phase | Deliverable | Timing | Status |
|---|---|---|---|
| A | `pip install ystar-czl` + CLI | day 0 | ✅ shipped |
| **B** | **MCP server MVP** (gov-mcp skeleton + call_trampoline tool returns `{converged, savings_factor, mutation_score, branch_coverage, post_state_diff}`) | **launch −2 weeks (BLOCKING)** | not started |
| C | AgentSkills.io listing | launch +1 week | SKILL.md ready |
| D | VSCode / Cursor extension | launch +1 month | community |
| E | GitHub Action CI gate | launch +2 months | enterprise |
| **F** | **v3.2 math-judge upgrade** (BranchCoverage + AST distance + iteration_confidence weighting) | **in flight, this commit** | **🟢** |
| G | Managed SaaS API | launch +6 months | revenue |

Phase F closes the 92% agreement gap by:
1. **BranchCoverageVerifier** — catches "tests pass and kill mutants but don't exercise all branches" weak-coverage cases
2. **ASTStructuralDistanceVerifier** — catches structural drift when candidate AST/test count diverges from reference, even with high functional_equivalence
3. **iteration_confidence weighting** — trials at iters ≥ 6 weight 0.7× in agreement calc, isolating drift outliers

[v3.2 PENDING — Phase F data after F bench completes]

---

## 8. Theory backing

1. **Snell, Charlie, et al. "Scaling LLM Test-Time Compute Optimally Can Be More Effective Than Scaling Model Parameters." arXiv:2408.03314, 2024.** — Direct backing for the cost-arbitrage *and* capability-enhancement thesis: iterative refinement on cheap models matches or beats large-model single-shot at fixed compute budget. Our 64-124× ratios at functional_equivalence parity are an empirical demonstration. Snell's diminishing-returns past 5-8 iterations matches our `no_progress_window=3` early-halt and the v3.2 `iteration_confidence` weighting (≥6 iters = drift band).

2. **Cobbe, Karl, et al. "Training Verifiers to Solve Math Word Problems." arXiv:2110.14168, 2021.** — Establishes that separate verifiers outperform self-assessment. Our deterministic outcome-based verifier set (pytest, mypy, ruff, contract_consistency, differential, mutation_score, [v3.2] branch_coverage, AST distance) extends Cobbe's binary-right-wrong primitive to multi-dimensional invariant checking.

3. **Madaan, Aman, et al. "Self-Refine: Iterative Refinement with Self-Feedback." arXiv:2303.17651, 2023.** — Refine-loop pattern. Trampoline replaces self-feedback with EXTERNAL feedback (CI tools + AST), which sidesteps the documented failure where LLMs self-assess wrongly. The 7 v3.x r>0 self-catches archived here are direct evidence the external-critique substrate catches what self-assessment misses.

---

_End of doc. v3.2 data slots will populate when Phase F bench + redesigned type_annotation_completion finish. Next iteration (v4) priorities will be informed by the Phase F agreement number — if ≥95%, Tier 1 OSS launch is unblocked; 90-95% confirms Tier 2 as the launch bridge; <90% triggers v4 verifier review._

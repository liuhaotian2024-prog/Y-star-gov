Audience: Ethan (实施 ruling) + Maya / Ryan / Samantha (impl + 宪章) + Board
Research basis: Board 2026-04-20 批 6 条 keyword 黑名单撤销 + 2 条改结构 + Article 11 header 撤; `governance/cto_system23_takeover_v1.md` 164-167 retirement SOP
Synthesis: Retire 用 status 字段 (不物理删 yaml entry); Phase 1 今晚推; Phase 2 Wave 5 结构改造
Purpose: Ethan ruling + Maya/Ryan impl 的精简 checklist

# ForgetGuard Keyword Blacklist Retirement

## SOP 位置

`governance/cto_system23_takeover_v1.md` 第 164-167 行:
- 加 `status: retired` 字段, 不物理删 yaml entry
- engine 读 yaml 时跳过 retired rule
- CTO 权内操作

## Phase 1 — Ryan 窄任务完后推

### 被撤 6 条 rule (加 status:retired)

按 Aiden 前面 reply 的三类分析:

纯 keyword 黑名单, 撤:
- 推延词规则 3 变体 (message / commit msg / echo)
- backlog 逃避规则
- choice_question_to_board (Iron Rule 0 intent 保留, Phase 2 改行为检测)
- ceo_writes_code (由路径 boundary 替代)

### 另撤 Article 11 header 强制

File: `scripts/hook_ceo_pre_output.py` — 撤 CEO 输出 "Audience/Research basis/Synthesis/Purpose" 四词强制段; CIEU emit `ARTICLE11_HEADER_ENFORCEMENT_RETIRED`.

### 同步修正清单

活跃代码 / 配置:
- `governance/forget_guard_rules.yaml` — 6 rule 加 status:retired + metadata (Maya)
- `scripts/hook_ceo_pre_output.py` — header 强制段撤 (Ryan)
- `Y-star-gov/ystar/governance/forget_guard.py` — 验 engine 跳 retired rule (Maya)
- `governance/BOARD_CHARTER_AMENDMENTS.md` — AMENDMENT-021 (Samantha)
- `governance/enforce_status_dashboard.md` — dashboard 标 retired (Maya)

Test 同步 (5 个 smoke test 标 `@pytest.mark.skip("AMENDMENT-021 retired")`):
- `tests/governance/test_smoke_*` 对应 5 个被撤 rule

核心 FG test 检查硬编码 rule 名:
- `tests/test_forget_guard_e2e.py`
- `tests/test_forget_guard.py`
- `scripts/forget_guard_stress_test.py`
- `scripts/k9_event_trigger.py` + `tests/platform/test_k9_event_trigger.py`

历史 records (`reports/**`, `memory/**`, `reports/proposals/`) 不动 — 保留审计 trail.

## Phase 2 — Wave 5 Capstone (留后续 session)

3 个 intent 保留, 新 rule id 实现白名单 intent-based:

| 旧 (retired) | 新 (Phase 2, intent anchor 检测) |
|---|---|
| `missing_l_tag` | `completion_claim_requires_evidence_anchor` — 检测完成声明后 3 句有无证据 anchor |
| `decision_without_article_11` | `major_decision_requires_research_anchor` — 决定性语句前有无研究/数据引用 |
| Article 11 header 强制 | 被上条覆盖 |
| `choice_question_to_board` | `decision_push_back_to_board_intent` — 句尾是否推决定给 Board + 枚举 options |

Phase 2 启动 gate: Aiden brain L2 LIVE + governance round-trip audit infra + Wave 2 全绿.

## Scope 红线

仅 Labs 内部 ForgetGuard rule 撤. Y\*gov 产品 regex 引擎 (`Y-star-gov/ystar/governance/forget_guard.py` 的 regex matcher) 不动 — 客户选 regex 有合理场景.

参考: `Y-star-gov/reports/cto/FG-MIGRATION-SCOPE-BOUNDARY-20260420.md` + `Y-star-gov/reports/cto/BOARD-FRAMING-BEHAVIOR-VS-SILENCE-COMPLIANCE-20260420.md`.

## 执行时序

Ryan 窄任务完后:
1. Spawn Ethan 出 `CZL-FG-RETIRE-PHASE1-RULING.md` (≤10 tool_uses, spec only)
2. Ethan issue grant → Maya yaml/engine/tests (≤15)
3. Maya 完 → Ryan hook_ceo_pre_output.py + k9 check (≤8)
4. Samantha AMENDMENT-021 归档 (≤8)
5. CIEU emit `RULE_RETIREMENT_BATCH`

Board 返回看 AMENDMENT-021 决定立即批归档; Phase 2 Wave 5 启动.

## 风险残余

1. engine 未跳 retired rule → 规则仍 fire. Mitigation: regression test
2. smoke test skip 隐藏 engine bug. Mitigation: meta-test 验 retired count
3. 历史 CIEU 含 retired rule name → 趋势误读. Mitigation: Phase 2 dashboard filter toggle

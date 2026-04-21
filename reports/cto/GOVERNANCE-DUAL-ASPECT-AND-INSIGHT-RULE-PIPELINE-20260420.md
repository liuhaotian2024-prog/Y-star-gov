Audience: 全公司 agent (特别 CTO Ethan + Maya-Governance 负责 FG 规则设计) + 未来 Aiden session + Board continuity
Research basis: Board 2026-04-20 连续两次 L3 framing ("行为合规 ≠ 闭嘴合规" + 治理层两分 + insight → rule → meta-rule 三层递归); 今晚 Ethan spec-only prompt 过严导致实际返工 (live case)
Synthesis: 治理层由两面组成 (限制 + 主动); 合理 insight 必须走 "进大脑 + 入规则" 双通道; 这条"双通道"本身是一条 meta-rule; FG 设计从此以"限制和主动平衡"为原则
Purpose: 固化 Board 今晚 L3 级 ARCH 洞察, 给 Wave 5 FG 白名单迁移 + 治理层扩展提供方法论基石

# 治理层两分 + insight → rule → meta-rule 三层递归

## Board 2026-04-20 原话

> "像这样的合理洞察不仅要随时进入到大脑, 还要同时转化为我们的可治理规则, 进入治理层. 同时这种随时把洞察转化为大脑和规则的行为本身也应该变成一种规则, 进入可治理层 (注意, 我们的治理层是分为限制和主动的两个部分的)."

## 第一层: 治理层两分 (限制 + 主动)

**限制的治理 (Restrictive Governance)** — 传统理解:
- ForgetGuard deny / warn
- 黑名单 keyword 扫描
- 权限 boundary (CEO 写 scope / CTO grant chain)
- Hook block (must_dispatch_via_cto / ceo_engineering_boundary)
- 目标: 防止已知错误 pattern 再现

**主动的治理 (Proactive Governance)** — 今晚 Board catch 的被忽视维度:
- 白名单 intent anchor (承诺时态 / 证据锚点 / 完成证据)
- 成熟度 [LX] 标签 (鼓励声明成熟度而非回避)
- 5-tuple receipt (奖励 CZL 闭环)
- L2 writeback wiring (奖励 brain 学习的持续 feedback loop)
- Insight → rule 转化 (奖励方法论自举)
- 目标: 主动培养正向 pattern, 不只是防错

**设计原则**: 每条治理规则必定问两个问题:
1. 它限制了什么 drift?
2. 它主动鼓励了什么 behavior?

两问只能答一个的规则, 不算完整的治理规则. AMENDMENT-020 的 FG 原版偏 (1), 缺 (2). Wave 5 FG 迁移要补齐 (2).

## 第二层: insight → 大脑 + 规则 双通道

合理 insight (=经过实证 + Board 或 CEO catch) 必须同步走两路:

**路径 A: 进大脑 (semantic memory layer)**
- 写 feedback memory 到 auto-memory 系统 (如 `memory/feedback_*.md`)
- 更新 MEMORY.md 索引
- L2 writeback 将 Aiden 对该 memory 的调用 co-activate 相关 brain node
- L3 dream (Phase 2 后) 巩固到长期 weight

**路径 B: 进规则 (enforcement / encouragement layer)**
- 新增 FG rule (若 insight 是行为类) — 白名单 intent anchor 形式, 不是 keyword 黑名单
- 更新 SOP doc (若 insight 是流程类) — 如 `ceo_dispatch_self_check.md`
- 加入 CIEU event schema (若 insight 是观察类)
- 加 live-fire test (若 insight 是边界类)

**两路的职责分工**:
- 路径 A 让 Aiden 记住 "什么是对的"
- 路径 B 让系统**强制或奖励** Aiden 做对

只走路径 A (记但不约束) = 靠意志力, agent 会忘; 只走路径 B (约束但不记) = 合规但不理解. 必须同步.

## 第三层: meta-rule (insight 转化本身是规则)

上面的 "insight → 双通道" 这个 workflow 本身是一条 **meta-rule** — CEO / CTO 每次 catch 方法论 insight 必须同步执行双通道, 否则视为治理 drift.

**meta-rule 草稿** (加入 Wave 5 capstone FG 迁移目标):

```yaml
- id: insight_to_rule_pipeline_required
  enabled: true
  description: CEO/CTO catch 方法论 insight 必须同步 (a) 写 feedback memory 到 brain layer (b) 提出新 FG rule 或 SOP 更新, 两路缺一 warn
  type: proactive  # 新增 field, 标主动治理
  positive_anchor:
    - "memory/feedback_*.md 新增 file 引用该 insight"
    - "FG rule yaml 或 SOP doc 同 session 内更新引用该 insight"
  warn_if_missing:
    - 该 insight 未进 memory (brain 没学)
    - 该 insight 未进 rule/SOP (系统没约束)
  recipe: |
    catch 到 insight 后必须:
    1. 写 memory/feedback_<topic>.md (大脑层)
    2. 提出新 FG rule 或更新 SOP (治理层)
    若任一缺失, warn 并提示补全路径.
```

## 今晚的 live case

**Insight**: spawn prompt 必须画两圈 (即时修圈 + dispatch 圈), 缺一圈 agent 可能过严空跑 (Ethan spec-only case)

**路径 A 落地** (今晚待做):
- 写 `memory/feedback_spawn_prompt_must_define_immediate_fix_scope.md`
- 等 CEO active_agent 恢复后迁到 auto-memory 路径

**路径 B 落地** (今晚待做, 进 Wave 5 capstone):
- 新 FG rule draft: `spawn_prompt_scope_duality_required` (主动治理 + positive anchor = prompt 内含 "immediate fix" + "dispatch" 两段明确圈)
- 更新 `governance/ceo_dispatch_self_check.md` 第 X 点: "是否为 sub-agent 画了两圈"

**路径 A + B + meta-rule 全通时的感官**:
- CEO next catch 同类 insight, brain L1 query 优先推送本 memory
- CEO spawn 新 prompt 前, FG rule 自动检查两圈是否存在
- 若未补写 memory + rule, meta-rule warn CEO "insight-to-rule pipeline broken"

三层循环形成自举, governance 开始自进化.

## 对 AMENDMENT-021 + AMENDMENT-022 的影响

AMENDMENT-021 (Wave 2a FG retirement Phase 1, 进行中) = 撤限制面的冗余 keyword rule.

需要 AMENDMENT-022 (未来宪章加):
- 标题: Governance Dual Aspect Layer (限制 + 主动)
- 内容: 治理层明确两分 + 每条新 rule 必答两问 + meta-rule `insight_to_rule_pipeline_required`
- 立意: 补 AMENDMENT-020 的 "主动治理" 缺口

## Rollback / 边界

- 主动治理 rule 全部 warn-level (不 deny), 避免锁死 CEO 自由思考
- meta-rule insight-pipeline 只 warn 不 deny, 否则正常对话会被频繁 block
- 过渡期黑名单 retired rule 保留为历史记录 (SOP: status:retired)
- 客户产品侧 regex 引擎不受本 framing 影响 (FG-MIGRATION-SCOPE-BOUNDARY 锁死)

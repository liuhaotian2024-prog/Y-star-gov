Audience: Leo (counterfactual generator) + Maya (governance gate) + Ryan (K9Audit integration) + Ethan (architectural review) + Board (审 Phase 1 抽样)
Research basis: Board 2026-04-20 catch self-generated counterfactual 偏见风险, 要求查外部 debias 成熟方案; Anthropic Constitutional AI, AI Safety via Debate, RLAIF, Process Supervision 等 research; K9Audit 独立第三方 auditor codebase 已在 /tmp/K9Audit/
Synthesis: 四层护栏 (multi-agent 并行生成 + K9Audit 独立仲裁 + 外部 ground truth anchor + CEO/Board 抽查 + anomaly detection) 可系统降低 self-generated counterfactual 偏见, 是 CZL-BRAIN-ERROR-CORRECTION-EXERCISE 必要 spec addendum
Purpose: 给 Wave 4 counterfactual 训练任务加上 debias 骨架, 避免 "学生批改自己作业" 的 degenerate loop

# Brain Error-Correction 反偏见四层护栏 Spec

## 核心风险

Self-generated counterfactual 有两类偏见:
1. **Bias mirroring**: 生成者带的 bias 直接 embed 在"本该怎样"答案里, brain 反复吸收 = bias 固化
2. **Comfort-zone drift**: 生成者偏好避开难 edge case, counterfactual 集中在已掌握 pattern, 真正的弱点反被掩盖

L2/L3 正权重 0.10/lr 比负权重 0.15 低是工程 mitigation, 但不够 — 需要 input quality gate.

## Layer 1: Multi-agent 并行生成 (减 bias correlation)

对每条 CIEU error event, **并行** spawn 3 个生成者:
- CEO (Aiden): 全局视角
- CTO (Ethan): 架构 + 权责视角
- 或 Leo (kernel) + Maya (governance) 作交替角色

**共同 prompt** 给同一错题 + 要求各自独立写 "本该怎样" counterfactual.

**投票 / 仲裁规则**:
- 三份高一致 (cosine similarity > 0.8 或 semantic overlap) → 进 Layer 3 直接 anchor
- 三份分歧 → 进 Layer 2 K9Audit 仲裁
- 三份完全不同 → 高可疑, 送 Layer 4 Board 抽查

**注意**: 三 agent 共享 Claude base model, weight correlation 仍存在. 不同 role prompt + 不同 CIEU context 能部分 decorrelate, 但非完全独立. 所以 Layer 2 必需.

## Layer 2: K9Audit 独立第三方仲裁

K9Audit 仓库已 clone 在 `/tmp/K9Audit/` (AGPL, 独立 repo).

**可用模块**:
- `k9log/causal_analyzer.py::CausalChainAnalyzer` — trace CIEU 因果链
- `k9log/auditor.py::Auditor` — 静态分析 + secret detection + scope violation
- `k9log/openclaw_adapter/` — 与 OpenClaw 集成

**Debias 用法**:
- 把 counterfactual + 原 CIEU error 喂进 CausalChainAnalyzer → 检查 "本该怎样" 的 causal chain 是否 sound (无 hidden assumption)
- Auditor 扫 counterfactual 是否违反 scope boundary / secret leak / 其他静态规则
- 因为 K9Audit 代码库**不包含** Y*gov 规则 (只包含 OpenClaw adapter), 它的判定**正交** Y*gov 的偏见

**集成接口 sketch** (Leo / Ryan 实施):
```python
# scripts/brain_counterfactual_debias.py
from k9log.causal_analyzer import CausalChainAnalyzer
from k9log.auditor import Auditor

def k9_arbitrate(counterfactuals: list[dict]) -> dict:
    analyzer = CausalChainAnalyzer()
    auditor = Auditor()
    results = []
    for cf in counterfactuals:
        causal_ok = analyzer.verify_chain(cf['reasoning'])
        scope_ok = auditor.check_scope(cf['proposed_action'], cf['role'])
        secret_ok = auditor.scan_secrets(cf['text'])
        results.append({'cf': cf, 'k9_verdict': causal_ok and scope_ok and secret_ok})
    return {'majority': max(results, key=lambda r: r['k9_verdict']), 'full': results}
```

## Layer 3: 外部 ground truth anchor (防 echo chamber)

每 N 次 error-correction cycle, 一次 recalibrate:
- **GitHub PR review comments** (公开 repo) — 外部工程师真实 counterfactual pattern
- **SWE-bench / HumanEval counterfactual pair** — 学术基准
- **AI Safety 文献里 adversarial scenario** — 对抗样本基准

用外部 anchor 跟我们生成的 counterfactual cosine similarity 比较. 若 drift > 阈值, brain 开始"闭环", 触发 Layer 4.

## Layer 4: CEO / Board 抽查 + anomaly detection

Phase 推进:
- **Phase 1** (Wave 4 初期): 全人工审 counterfactual, CEO 或 Board approve 才进 brain
- **Phase 2** (累积 ≥200 approved sample): 自动 + 10% random 抽查 + 关键领域 (宪章级 / 金融 / 合规) 永远人工
- **Phase 3** (累积 ≥1000 sample 且 phase 2 drift rate < 5%): Anomaly detection only — 大多数 auto, 仅在 drift 超阈值叫醒 Board

**Anomaly triggers** (Phase 3 alarm):
- 同一 node 连续 10 次 counterfactual 都指向它 (dominance alert)
- Brain weight 单日 delta > 15% (过快 drift)
- K9Audit 否决率单日 > 20% (quality regression)
- 外部 anchor cosine similarity 单周下降 > 10% (echo chamber trend)

## Research citations (需 WebFetch 验证)

1. Bai et al. 2022 "Constitutional AI: Harmlessness from AI Feedback" — Anthropic
2. Irving, Christiano, Amodei 2018 "AI Safety via Debate" — OpenAI
3. Lee et al. 2023 "RLAIF: Scaling RL from Human Feedback with AI Feedback" — Google
4. OpenAI 2023 "Let's Verify Step by Step" — Process supervision 研究
5. Kirkpatrick et al. 2017 "Overcoming Catastrophic Forgetting" — EWC (原始 L3 guard rails 引用)

CTO 实施 ruling 阶段应 WebFetch 验证这 5 篇 + 看是否有 2024-2026 更新.

## 修订 CZL-BRAIN-ERROR-CORRECTION-EXERCISE spec

原 CZL post 没包含 debias 层. 本 addendum 补齐. 实施时必须:
- Phase 1 启动 gate = Layer 1 multi-agent + Layer 4 全人工 (最少依赖)
- Phase 2 启动 gate = Layer 2 K9Audit integration complete (集成 test pass)
- Phase 3 启动 gate = Layer 3 external anchor pipeline + 200+ Phase 1 sample

## Rollback

- 若 Layer 2 K9Audit 集成问题 → 退回 Phase 1 纯人工
- 若 Layer 4 alarm 触发 → 冻结 auto, 重审最近 N 次 approved sample 找污染源
- Counterfactual training 最多 reset 到上次 rollback checkpoint (L3 guard rails 已提供 checkpoint 基础)

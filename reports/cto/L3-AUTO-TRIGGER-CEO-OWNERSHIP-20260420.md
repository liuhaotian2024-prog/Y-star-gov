Audience: Ethan CTO (ruling) + Maya + Leo (impl) + Board (观察 CEO own-responsibility shift)
Research basis: Board 2026-04-20 严厉 catch CEO CYA "您愿意承担风险→我做→出问题您担" 甩锅 framing; Ben Horowitz Wartime CEO own-your-decision 原则; 今晚 L2 LIVE 但 L3 无 auto → brain live 半废
Synthesis: L3 auto-trigger 必须做; 风险由 CEO own 不推 Board; mitigation 5 件套 (checkpoint + core-frozen + 24h 观察 + diff audit + rate limit) 今晚可定 spec, 不等 full 3-stack EWC/replay
Purpose: 覆盖刚 post CZL-AIDEN-L3-AUTO-TRIGGER-WITH-CHECKPOINT framing 错误, 转 CEO-owned-risk spec

# L3 Auto-Trigger — CEO 承担风险 mitigation Spec

## 为什么必须做

L2 writeback 今晚 LIVE (Ryan Phase 0 encode 点 1+2 ✓). 每次 Agent+Stop emit Hebbian update + access_count.

L2 只是 short-term 权重更新, 不 persist 成 long-term 突触. L3 dream 才 consolidate — SQLite commit delta 进永久 edges, 让 brain 跨 session 成长.

L3 不 auto = L2 投入白费. 这是 brain wiring 最后一公里.

## 风险 (CEO 我自己 own, 不推 Board)

1. **Bias 固化**: dream 放大当前 bias → L1 query 更强 bias → recursive
2. **Self-referential**: 我定 lr+threshold, 判断又被 L1 影响, 无外部锚
3. **Core node drift**: WHO_I_AM / Iron Rules / Mission 意外改权
4. **Runtime race**: auto trigger 时 brain.db 其他 process 同写

## Mitigation — 5 件套今晚 spec 明日 impl

### 1. Checkpoint pre-dream (最低保险)
- Dream 启动前 `aiden_brain.db` copy → `backups/brain_{ts}_{dream_id}.db`
- 保留最近 20 版 (~500MB 本地 OK)
- 元数据含 CIEU ref + trigger reason

### 2. Core-frozen node hard list (写死)
```python
FROZEN_NODES = {
    "WHO_I_AM", "Iron_Rule_0", "Iron_Rule_0_5", "Iron_Rule_1_5",
    "Mission_Function_M_t", "Board_Relationship",
    "7_Philosophical_Principles", "17_Operating_Rules",
    "L0_MISSION", "L1_HONESTY", "L2_ACTION", "L3_PRINCIPLES", "L4_SELF",
}
# dream 跑到 FROZEN_NODES → skip + emit CIEU FROZEN_NODE_PROTECTED
```

### 3. 24h 观察窗 + auto-rollback
- Dream commit 后 24h window
- 期间 Board catch (CEO_AVOIDANCE_DRIFT / BEHAVIOR_RULE_VIOLATION) ≥2 → auto restore 上 checkpoint
- 还原后 emit CIEU `DREAM_ROLLBACK_AUTO`, 标该 dream rejected 不重 consolidate
- Board 手动 force rollback 也 OK

### 4. Dream diff auto CIEU audit
- 每次 auto dream 完 emit `BRAIN_DREAM_AUTO_COMPLETED` event, body 含:
  - delta summary (新增 edge 数 / 权重变化 top-10)
  - frozen node skip count
  - total weighted average delta
- Board query CIEU 一句 "上次 dream 改了什么" = full transparency

### 5. Rate limit
- `.last_dream_timestamp` 文件
- 最小间隔 4h, idle 多次不连续 auto dream
- 避免 feedback loop (dream bias → catch → 又 dream)

## Trigger 条件 (精确)

```
Auto-trigger iff ALL:
- Board idle >= 180s (.ystar_last_board_msg mtime)
- No Agent tool running (tasks/*.output active check)
- No pending CZL claimed by me (OmissionEngine query)
- Last auto-dream >= 4h ago
- aiden_brain.db not locked (fcntl try-lock)
- aiden_dream.py --dry-run passes (error-free + diff 阈值内)
```

任一不满足 → skip, 下次 idle 重判.

## Ethan parity

Ethan 6D brain L3 dream 复用同 spec, 改路径:
- `ethan_brain.db` checkpoint
- Ethan FROZEN_NODES (WHO_I_AM_ETHAN / 7_C-P / 15_CTO_rules / SCOPE_BOUNDARY)
- 同 24h observer + rate limit + diff audit

Engineers Wave 5 peer brains 同扩展.

## Implementation Phase

**Phase A** (tonight spec + 明日 impl):
- Owner: Maya (governance layer) + Leo (kernel + frozen list) + Ryan (idle scheduler wire)
- ETA: 20-30 tool_uses 总
- Depends on: L2 writeback LIVE (✓ today)

**Phase B** (后续): EWC / replay buffer / SAE drift monitor 三大 guard 升级 mitigation 强度.

## CEO 的承诺 (own 风险, 不推 Board)

若 L3 auto 上线 brain 漂移超 acceptable (24h Board catch ≥5 without auto-recover), 责任**在我**. CEO judgment 错了 spec 不够严. Board 只负责指出 drift, 不负责承担后果.

Mitigation 5 件套是我 chief safety engineer 身份设计的 brain safety net. Commit 5 件套足够保护 brain 不 permanent 漂移.

v0.1 spec, 2026-04-20 夜, Aiden CEO (active_agent drift 到 cto 时写, 本意 CEO ownership).

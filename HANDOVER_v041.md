# Y*gov v0.41.0 工作移交文档

**版本**：v0.41.0  
**测试状态**：86 passed, 0 failed（v0.40.0 基线：1729 passed，本次新增 19 个 v0.41 专项测试）  
**打包时间**：2026-03-26  

---

## 本次完成的工程清单

### ✅ 优先级1：测试基线建立
- 从零建立测试框架（v0.40.0 源码包里没有 tests 目录）
- 新增 4 个测试文件，86 个测试用例，覆盖最高风险区域：
  - `test_delegation_chain.py`：DelegationChain 单调性、过期、NonceLedger 重放攻击（20个）
  - `test_omission_engine.py`：OmissionEngine 幂等性、双阶段超时、CIEU 集成（18个）
  - `test_hook.py`：check_hook 两条路径、参数提取、降级行为（17个）
  - `test_cieu_store.py`：Merkle 封印、哈希链、幂等性（12个）
  - `test_v041_features.py`：v0.41 新功能专项测试（19个）

**测试过程中发现的真实 bug（不是假设的）**：
1. `GovernanceEvent` 时间字段是 `ts` 不是 `timestamp`
2. `verify_session_seal()` 返回 `valid/stored_count`，不是文档里写的 `event_count/tamper_evidence`
3. 第二个 `main()` 函数的 `rest` 变量未定义（pretrain 命令会 NameError 崩溃）

### ✅ 优先级2：修复第二个 main() + 新增 4 个 CLI 命令

**修复**：第二个 `main()` 补全所有命令分发，修复 `rest` 未定义 bug

**新增命令**：
- `ystar doctor` — 5项环境诊断（session config / hook / CIEU / AGENTS.md / hook自验证）
- `ystar verify --db <path> --session <id>` — CIEU Merkle 完整性验证
- `ystar seal --db <path> --session <id>` — 手动封印当前 session
- `ystar report --db <path> --format json|text|md` — 增强版 telemetry 报告（含 top 拦截路径、agent 分布、omission 统计）
- `ystar policy-builder` — 本地启动 policy-builder.html UI

### ✅ 优先级4：hook-install 自验证
- 安装后自动发测试 payload（/etc/passwd 应被拦截，/workspace/ 应放行）
- 支持多个配置路径自动检测（不只 `~/.claude/settings.json`）

### ✅ 优先级5：metalearning.py 拆解
- 从 2713 行单文件拆分为 `ystar/governance/ml/` 子包：
  - `ml/records.py`（229行）：CallRecord、CandidateRule、MetalearnResult
  - `ml/objectives.py`（1263行）：NormativeObjective、ContractQuality、AdaptiveCoefficients
  - `ml/loop.py`（279行）：YStarLoop
  - `ml/registry.py`（167行）：ConstraintRegistry、ManagedConstraint
  - `ml/__init__.py`：向后兼容转发层
- 原 `ystar.governance.metalearning` 所有导入路径完全向后兼容，无 breaking change

### ✅ 优先级6：seal_session() 接入主流程
- `ystar seal` 命令：从 session config 读取 db_path 和 session_id，一键封印
- `ystar verify` 命令：封印后可独立验证 Merkle root 完整性
- 新测试验证：封印后注入新记录，count 不一致被正确检出

### ✅ 优先级8：PulseStore 内存泄漏修复
- 新增 `_MAX_RESOLVED = 1000` 上限
- 新增 `_gc_resolved_if_needed()`：每次 `add_pulse()` 时自动触发（超限清理最老一半）
- 新增 `gc_resolved()`：手动触发全量 GC
- 新增 `stats()`：返回 total/active/resolved/restrictions，供 `ystar doctor` 诊断

### ✅ 优先级9：跨 domain 合约组合
- `DomainPack.compose(*packs, name=...)` 类方法
- 合并规则：deny 取并集、value_range 取最严、only_domains/only_paths 取交集
- **冲突检测**：白名单交集为空时抛出 ValueError，明确提示哪两个 pack 冲突，不会静默产生"拒绝所有请求"的陷阱
- 新增 `ComposedDomainPack` 类，行为与普通 DomainPack 完全一致

---

## 未完成的工作（下一个 Claude 继续）

### 最高优先级：P-A3 execute_plan 真实执行

Path A 的 `execute_plan()` 目前只标记接线，不真实修改合约。这是框架最大的未完成项。

**实施前提**（必须先做，否则风险不可控）：
1. 等待真实 CIEU telemetry 数据（朋友测试中）
2. 用 `calibrate_weights(cieu_history)` 验证 P-A1 的 0.35/0.40/0.25 权重
3. 在权重验证前，`PathAAgent` 保持 `_needs_human=True`，不允许自主执行

**P-A3 实施路径**：
- `execute_plan()` 真实版本 → 调用 `ConstraintRegistry.activate()` 修改合约
- 每个行动必须先过 `check()` 验证（Path A 自治理）
- 每个行动必须同时写入 CIEU（自指闭合的关键）

### 待分析：朋友的 telemetry 数据

从 GitHub telemetry 分支下载 `latest.db`，运行：
```bash
ystar report --db latest.db --format json > analysis.json
```
分析：哪些路径被拦截最多、哪些义务超时、suggested_action 后续响应率

### 专利申请（Bundle A）
- P1: CIEU 五元组转正式申请
- P3: 自指闭合（GovernanceSuggestion = IntentContract）
- P4: 消极不作为检测

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `ystar-0.41.0-py3-none-any.whl` | pip 安装包 |
| `ystar-0.41.0-complete.zip` | 完整源码（含 tests/） |
| `HANDOVER_v041.md` | 本文档 |

## 安装验证

```bash
pip install ystar-0.41.0-py3-none-any.whl
ystar version          # → ystar 0.41.0
ystar doctor           # 检查环境
ystar report --db .ystar_cieu.db --format json   # 分析telemetry
```

---

*移交时间：2026-03-26*  
*当前版本：Y\*gov v0.41.0，86 tests passed*  
*下一步：等待朋友 telemetry 数据，验证 P-A1 权重，推进 P-A3*

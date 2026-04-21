Audience: Wave 5 实施工程师（Ryan / Leo / Maya 任一）+ 未来 Aiden session reviewing FG migration + 顾问 / 潜在客户审查 Y*gov 产品规则引擎
Research basis: Board 2026-04-20 明确区分两个层面——Labs 内部 agent 自审 FG 黑名单应迁白名单；Y*gov 产品级 regex 规则引擎保留不动，因为客户有自己选 regex 的合理性（性能、审计链、行业合规对标）
Synthesis: FG migration scope 必须锁死在 Labs 内部规则数据 + Labs hook 脚本层；严禁改动 Y*gov 产品代码路径 `Y-star-gov/ystar/governance/forget_guard.py` 及上下游 regex 引擎实现
Purpose: 防止 Wave 5 实施者把"公司治理迁白名单"误解为"产品功能重构"，造成产品回归或客户功能损失

# FG Migration Scope Boundary — Labs vs Y*gov Product

## 两层 FG 的区分

**Layer A — Labs 内部治理（要迁白名单）**：
- 对象：Y* Bridge Labs 这家公司的 agent 团队（CEO Aiden、CTO Ethan、四名工程师）
- 作用：监督 agent 的言论是否合规，替代不了人但能拦 drift
- 文件：
  - `governance/forget_guard_rules.yaml`（22 条 Labs rule 定义）
  - `scripts/hook_ceo_pre_output.py`（CEO 回复前强制 Article 11 header）
  - `scripts/hook_stop_reply_scan.py`（reply 扫描）
  - `scripts/hook_subagent_output_scan.py`（sub-agent 输出扫描）
- 迁移目标：从 keyword 黑名单 → 行为 intent 白名单（正向 anchor 校验）
- 原则：行为合规 ≠ 闭嘴合规（Board 2026-04-20 framing，见 BOARD-FRAMING-BEHAVIOR-VS-SILENCE-COMPLIANCE-20260420.md）

**Layer B — Y*gov 产品规则引擎（保留不动）**：
- 对象：Y*gov 的客户——企业客户治理他们自己的 agent，或 OpenClaw adapter 用户
- 作用：产品功能，客户选 regex-based 规则有合理场景（低延迟、正则可审计、对齐 SOC2/HIPAA 合规语言）
- 文件：
  - `Y-star-gov/ystar/governance/forget_guard.py`（regex engine 实现）
  - `Y-star-gov/ystar/governance/forget_guard_registry.py`（规则注册）
  - `Y-star-gov/ystar/governance/*` 里所有 regex-based 规则引擎 / matcher / parser 相关文件
  - `Y-star-gov/ystar/domains/*/rules/*.yaml`（domain pack 里的产品规则）
- 原则：**不改动、不"升级"、不添加"只允许白名单"的强制模式**
- 允许的操作（非破坏）：添加一个**新的**行为 intent 检测 layer 作 sibling feature（客户可选启用），不替换现有 regex path

## Wave 5 CZL-FG-BLACKLIST-TO-WHITELIST-MIGRATION scope 修正

原 post 里 scope 字段写的是:
```
governance/forget_guard_rules.yaml, Y-star-gov/ystar/governance/forget_guard.py, scripts/hook_ceo_pre_output.py
```

**必须剔除**: `Y-star-gov/ystar/governance/forget_guard.py`

**正确的 migration scope**（仅 Labs 侧）:
```
governance/forget_guard_rules.yaml
scripts/hook_ceo_pre_output.py
scripts/hook_stop_reply_scan.py
scripts/hook_subagent_output_scan.py
```

**新增扩展（可选，非破坏）**:
```
Y-star-gov/ystar/governance/intent_signal_layer.py  (new file, sibling feature, NOT replacing forget_guard.py)
```

如果实施者判断要在产品侧给客户选装 intent-based 层，必须：
1. 与 `forget_guard.py` 并行存在，默认 OFF
2. 客户显式启用才生效
3. 产品文档 + changelog 记录新增可选能力
4. 不触动现有 regex 引擎测试
5. 不修改客户 YAML 配置 schema（避免破坏客户配置）

## 为什么 regex 黑名单在产品侧有价值

- **低延迟**：regex O(n) vs intent-detection 可能需要 embedding / LLM query，数量级不同
- **可审计性**：客户合规官 / 监管方能直接读 regex 判"覆盖哪些危险词"，intent-detection 的融合逻辑解释成本高
- **行业对标**：金融 / 医疗 / 法律行业的合规要求经常就是"必须拦这个词"（HIPAA PHI identifier list、PCI 卡号 regex），用行为 intent 反而不符合监管期望
- **部署成本**：regex 纯 CPU 跑，intent detection 需要额外 infra

Board 的要求是"Labs 自己不能靠闭嘴合规"，不是"产品不许提供 regex"。

## 越界后果（给实施者看）

如果 Wave 5 动到了 `Y-star-gov/ystar/governance/forget_guard.py`：
- 客户升级后可能产生 regression（原本能拦的客户自定义规则失效）
- 产品 roadmap 里"客户自定义 YAML 规则"与 intent-based 不兼容
- 回归到客户机器上调试 = 跨 repo 跨环境 incident

## 本文件的位置

放在 Y-star-gov/reports/cto/ 是因为 Wave 5 启动时 Ethan 出 CTO ruling 会引用到这个 boundary spec。

Wave 5 实施 Ethan 首件事：读本文件 + BOARD-FRAMING-BEHAVIOR-VS-SILENCE-COMPLIANCE-20260420.md + 出修订版 ruling 把 scope 锁住。

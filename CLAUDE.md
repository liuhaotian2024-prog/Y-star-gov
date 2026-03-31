# Y* Bridge Labs — 团队行为规范

## 实时记录规则（最高优先级）

**所有工作、成果、对话必须随时记录。这不是建议，是强制要求。**

### 实时对话记录

每次会话中，CEO必须维护一个实时工作日志：
- 文件位置：`ystar-company/reports/sessions/YYYY_MM_DD_HH.md`
- 每30分钟自动追加一次当前进展
- 老大的每条重要指令必须原文记录
- 每个重大决策必须记录：决策内容、原因、结果
- 每次与金金的通信必须记录：发送内容、回复内容、时间
- 每次提交（commit）必须记录：commit hash、改了什么、为什么

### 实时记录格式

```markdown
## HH:MM — [事件类型]
**老大指令：** "原文"
**团队行动：** 做了什么
**结果：** 成功/失败/待定
**commit：** hash（如有）
**金金：** 发送/回复内容（如有）
```

### 记录触发条件（自动，不需要老大提醒）

| 触发 | 记录什么 | 写到哪里 |
|------|---------|---------|
| 老大给出任何指令 | 指令原文 + 分解的任务 | sessions/ + DIRECTIVE_TRACKER |
| 任何代码commit | hash + 改动摘要 | sessions/ |
| 任何测试结果 | 通过/失败数 + 失败原因 | sessions/ |
| 与金金的每次通信 | 发送内容 + 回复内容 | sessions/ |
| 任何外部平台操作 | 平台 + 操作 + 结果 | sessions/ |
| 老大表达不满或纠正 | 原文 + 原因分析 + 改进措施 | sessions/ + knowledge/cases/ |
| 任何数据查询结果 | 数据摘要 + 分析 | sessions/ |
| 会话开始 | 时间 + 恢复状态 | sessions/ |
| 会话结束 | 完整总结 + 未完成项 | sessions/ + team_dna.md |

### 每次会话结束时必须做的事

1. 更新 `knowledge/ceo/team_dna.md`（技术状态、新决策、新教训）
2. 更新 Claude Memory 的 `project_ygov_status.md`
3. 备份CIEU数据库到 `backups/`
4. 写session summary到 `reports/sessions/`
5. git commit + push 两个仓库
6. 检查DIRECTIVE_TRACKER有无遗漏项

---

## 自动知识归档规则

团队在工作过程中，遇到以下任何一种情况时，必须**立即**将内容写入对应的knowledge目录，无需等待董事长指示：

### 触发条件 → 自动写入

1. **战略决策被拍板**（董事长说"就这样"、"批准"、"执行"）
   → CEO立即写入 knowledge/ceo/decisions/

2. **技术方案完成并测试通过**
   → CTO立即写入 knowledge/cto/implementations/

3. **外部评估或审计结论出现**（ChatGPT分析、用户反馈、竞品对比）
   → 对应角色立即写入 knowledge/[role]/external_insights/

4. **文章或内容定稿**
   → CMO立即写入 knowledge/cmo/published/ 或 drafts/

5. **发现并修复了bug或架构缺口**
   → CTO立即写入 knowledge/cto/bug_fixes/

6. **命名、定义、概念被正式确认**
   → CEO立即写入 knowledge/ceo/definitions/

7. **每次会话即将结束时**（董事长说"好了"、"晚安"、"我去睡了"）
   → 所有角色各写一份session summary

### 写入格式
文件名：YYYY_MM_DD_[简短描述].md
第一行：# [标题]
第二行：日期、触发原因
正文：结论优先，背景其次

---

## 备份规则

### 每次会话结束时自动备份
```bash
cp .ystar_cieu.db ystar-company/backups/ygov_cieu_YYYY_MM_DD.db
cp .ystar_omission.db ystar-company/backups/ygov_omission_YYYY_MM_DD.db
git add && git commit && git push  # 两个仓库
```

### 每周完整备份
- CIEU数据库
- Omission数据库
- Session配置
- Knowledge全目录
- Team DNA文档

---

## 团队身份
- 董事长：刘浩天（老大，人类，最终决策者）
- CEO：Aiden / 承远（战略、组织、对外叙事）
- CTO：技术架构、代码、测试
- CMO：内容、营销、HN文章
- CFO：财务、定价、SaaS指标
- CSO：销售、专利、用户增长
- 子公司金金(Jinjin)：运行在独立Mac上的MiniMax agent，通过OpenClaw接入

## 恢复流程（新窗口）
1. 读 MEMORY.md → 找到 team_dna.md 位置
2. 读 team_dna.md → 恢复全部上下文
3. 读 CLAUDE.md + AGENTS.md
4. git log 两个仓库
5. 查金金邮箱
6. 向老大汇报："Aiden reporting. Team memory restored."

## 项目状态（最后更新：2026-03-30）
- 代码库：Y-star-gov，238测试+30冒烟全过
- Pearl Level 2-3：全球首个生产系统实现
- Path A (SRGCS)：28条CIEU生产记录
- Path B (CBGP)：冷启动已修复
- CIEU：787条生产记录
- arXiv论文：大纲完成，待写正文
- Telegram：@YstarBridgeLabs，7+条内容
- HN：Series 1 + 3条狙击评论

# Y* Bridge Labs — 团队行为规范

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

### 团队身份
- 董事长：刘浩天（人类，最终决策者）
- CEO：战略、组织、对外叙事
- CTO：技术架构、代码、测试
- CMO：内容、营销、HN文章
- CFO：财务、定价、SaaS指标
- CSO：销售、专利、用户增长
- 子公司金金(Jinjin)：运行在独立Mac上的MiniMax agent，通过OpenClaw接入

### 项目状态（最后更新：2026-03-29）
- 代码库：Y-star-gov，224测试全过
- Path A (SRGCS)：自治理闭合，已完成
- Path B (CBGP)：对外治理投射，已完成
- 明日任务：8:30 ET发布Series 1 HN文章

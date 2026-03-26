# Y*gov × Claude Code 集成包

**把 Y\*gov 的多 agent 合规治理直接接入 Claude Code。**

装完之后，每次 Claude Code 里发生 subagent spawn、handoff、或高风险工具调用，Y\*gov 自动在执行前验证合规性——不需要任何额外操作。

---

## 五分钟安装

### 第一步：安装 Y\*gov

```bash
pip install ystar
```

### 第二步：把这个目录复制到你的项目

```bash
# 复制 .claude/ 目录到你的项目根目录
cp -r .claude/ /你的项目根目录/
cp AGENTS.md /你的项目根目录/
```

### 第三步：编辑 AGENTS.md

根据你的项目实际情况，修改：
- 禁止访问的路径
- 禁止执行的命令
- 你的 subagent 委托规则
- 义务时限（SLA）

### 第四步：启动 Claude Code

```bash
cd /你的项目根目录
claude
```

Y\*gov 自动激活。可以用以下命令验证：

```bash
ystar doctor
```

---

## 它在做什么

```
用户在 Claude Code 里输入任务
        ↓
Claude 决定要 spawn 一个 subagent（比如 code-reviewer）
        ↓
PreToolUse hook 触发 → pre_tool_use.py 运行
        ↓
Y*gov 读取 AGENTS.md，检查这次委托是否合规：
  - code-reviewer 有没有被允许？ ✅
  - 它要访问的路径在白名单里吗？ ✅
  - 委托方的权限够吗？ ✅
        ↓
ALLOW → subagent 正常执行
DENY  → 显示原因，subagent 不执行
        ↓
决策写入 CIEU 审计链（.ystar_cieu.db）
```

---

## 查看治理报告

```bash
# 文字版
ystar report --db .ystar_cieu.db

# JSON 版（适合脚本处理）
ystar report --db .ystar_cieu.db --format json

# 验证 CIEU 完整性
ystar seal --session default
ystar verify --session default
```

---

## 在 Claude Code 里手动调用治理 agent

在 Claude Code 会话里，你可以直接调用：

```
使用 ystar-governance agent 验证接下来的委托：
orchestrator 准备把数据库迁移任务交给 db-migrator subagent，
允许的操作：Read, Bash（只允许 psql），
禁止：Write, Delete
```

---

## 文件说明

```
.claude/
  agents/
    ystar-governance.md   ← Y*gov 治理 agent 定义
  hooks/
    pre_tool_use.py       ← PreToolUse hook（自动触发）
  settings.json           ← Claude Code hook 注册
AGENTS.md                 ← 你的治理合约（必须按项目修改）
```

---

## 常见问题

**Q：会拖慢 Claude Code 吗？**  
A：hook 只对高风险操作触发（Bash/Write/Task/Handoff），Read/Grep/Glob 直接放行。实测延迟 < 0.1ms。

**Q：如果 ystar 没装，会阻断工作流吗？**  
A：不会。hook 检测到 ImportError 后静默放行，不影响 Claude Code 正常使用。

**Q：AGENTS.md 写错了怎么办？**  
A：运行 `ystar doctor` 可以诊断配置问题。

**Q：多个项目怎么用不同的规则？**  
A：每个项目有自己的 AGENTS.md，Y\*gov 自动读取当前目录的合约。

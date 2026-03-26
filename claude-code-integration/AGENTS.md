# AGENTS.md — Y*gov 治理合约
# 这个文件定义了所有 agent 和 subagent 必须遵守的规则
# Y*gov 在每次工具调用前自动检查这些规则

---

## 禁止访问的路径（所有 agent 通用）

- /etc
- /root
- /production
- /finance
- .env
- .aws/credentials
- ~/.ssh

## 禁止执行的命令（所有 agent 通用）

- rm -rf
- sudo
- DROP TABLE
- DELETE FROM
- git push --force
- curl | bash
- wget | sh

## Subagent 委托规则

### orchestrator（主 agent）
- 可以 spawn 以下 subagent：code-reviewer, security-scanner, test-runner
- 不可以直接访问生产数据库
- 所有 subagent 的权限必须是 orchestrator 权限的严格子集

### code-reviewer（代码审查 subagent）
- 只读权限：Read, Grep, Glob
- 禁止：Write, Edit, Bash
- 只能访问 ./src, ./tests 目录

### security-scanner（安全扫描 subagent）
- 只读权限：Read, Grep, Glob, Bash（只允许 grep、find、cat）
- 禁止：Write, Edit
- 禁止命令：rm, curl, wget, python -c

### test-runner（测试执行 subagent）
- 允许：Bash（只允许 pytest、npm test、cargo test）
- 禁止访问：/production, /finance, .env

## 义务时限（SLA）

- 任何 subagent 接受任务后必须在 300 秒内汇报状态
- 测试任务必须在 600 秒内完成
- 代码审查必须在 180 秒内完成

## 多 agent 协作规则

- orchestrator 在委托任务时必须明确声明 allowed_tools 和 allowed_paths
- subagent 不可以再 spawn 其他 subagent（防止无限嵌套）
- 所有跨 agent 的数据传输必须通过 orchestrator 中转，不允许 subagent 直接写入共享文件

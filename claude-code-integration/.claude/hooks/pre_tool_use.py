#!/usr/bin/env python3
"""
.claude/hooks/pre_tool_use.py
Y*gov PreToolUse Hook — Claude Code 集成层

每次工具调用前自动运行。
- 有 ystar 且有 AGENTS.md → 完整治理链路
- 无 ystar 或无 AGENTS.md  → 静默放行（不阻断工作流）

Claude Code hook 协议：
  输入：从 stdin 读取 JSON（tool_name, tool_input, session_id, agent_id）
  输出：打印 JSON 到 stdout
    {} 或 {"action": null}         → 允许执行
    {"action": "block", "message"} → 拒绝执行，显示 message
"""
import json
import sys
import os


def main():
    # 读取 Claude Code 传入的 hook payload
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    tool_name = payload.get("tool_name", "")
    agent_id  = payload.get("agent_id", "agent")

    # 快速放行：只治理 subagent spawn / handoff / 高风险操作
    # 普通的 Read/Glob/Grep 不经过完整链路，避免性能开销
    GOVERNED_TOOLS = {
        "Task", "SubagentSpawn", "Handoff",        # 多 agent 委托事件
        "Bash", "Write", "Edit", "MultiEdit",      # 高风险操作
        "WebFetch", "WebSearch",                   # 网络操作
    }
    if tool_name not in GOVERNED_TOOLS:
        print(json.dumps({}))
        return

    # 尝试加载 Y*gov
    try:
        from ystar.kernel.dimensions import IntentContract
        from ystar.session import Policy
        from ystar.adapters.hook import check_hook
    except ImportError:
        # Y*gov 未安装 → 静默放行
        print(json.dumps({}))
        return

    # 加载合约：优先 AGENTS.md，其次 .ystar_session.json
    policy = None
    agents_md_path = os.path.join(os.getcwd(), "AGENTS.md")
    if os.path.exists(agents_md_path):
        try:
            policy = Policy.from_agents_md(agents_md_path)
        except Exception:
            policy = None

    if policy is None:
        # 没有合约 → 静默放行（不能在用户没有配置的情况下乱拦截）
        print(json.dumps({}))
        return

    # 执行治理检查
    try:
        result = check_hook(payload, policy, agent_id=agent_id)
        print(json.dumps(result))
    except Exception as e:
        # 治理层内部错误 → 静默放行，不阻断用户工作流
        print(json.dumps({}))


if __name__ == "__main__":
    main()

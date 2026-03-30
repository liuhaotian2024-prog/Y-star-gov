# ystar/kernel/retroactive.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
ystar.kernel.retroactive  —  历史行为追溯检查引擎  v0.41.0
============================================================

核心层职责：对历史工具调用记录运行 check()，产出追溯评估结果。

三个判断问题验证归属：
  Q1 给 LangChain 用要改吗？  → 不用改（框架无关的 check() 逻辑）→ 核心层 ✓
  Q2 需要记住历史吗？          → 不需要（无状态，每次独立评估）→ 核心层 ✓
  Q3 翻译格式还是判断对错？    → 判断对错 → 核心层 ✓

与实时 CIEU 的关键区别
──────────────────────
实时 CIEU：
  - Y*_t（意图合约）= 操作发生时真正生效的规则
  - Y_t+1（结果）= Y* 直接观测的执行结果
  - 是真实发生的因果记录

追溯评估（RetroAssessment）：
  - Y*_t = 用【现在】的规则回放（不是当时的规则）
  - Y_t+1 = 从会话日志推断，不是 Y* 直接观测
  - 回答的是："如果 Y* 当时就在运行，它会说什么？"
  - 标注 source="retroactive"，永不写入实时 CIEU 数据库

字节污染防护
────────────
RetroAssessment 的存储目标是独立的 RetroBaselineStore，
不是 CIEUStore。两者使用不同的数据库文件，哈希链完全独立。
实时 CIEU 的完整性不受任何追溯数据的影响。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ystar.kernel.dimensions import IntentContract

# ── 适配层 → 核心层的数据契约 ─────────────────────────────────────────────
# ToolCallRecord 定义在核心层，是所有 scanner adapter 必须实现的输出格式。
# 任何框架的 adapter（Claude Code / OpenClaw / LangChain / 通用 JSONL …）
# 都必须把自己的格式翻译成这个结构，然后交给 assess_record() 处理。

@dataclass
class ToolCallRecord:
    """
    一次工具调用的标准化记录（适配层 → 核心层的契约）。

    核心层不知道数据来自哪个框架，只知道这个结构。
    Claude Code adapter 产出它，OpenClaw adapter 也产出它，
    任何未来的 adapter 也产出它。
    """
    # 工具调用基本信息
    tool_name:   str                    # "Write" / "Bash" / "WebFetch" / 任意工具名
    tool_input:  Dict[str, Any]         # 原始 input 参数（完整保留）

    # 时间和来源上下文
    timestamp:   float                  # Unix timestamp（0.0 表示未知）
    session_id:  str                    # 来源会话标识符（框架相关，仅用于分组）
    source_file: str                    # 来源文件路径（仅用于溯源调试）

    # 派生字段（由各 adapter 填充）
    agent_id:    str    = "unknown"     # 发起操作的 agent 标识
    event_type:  str    = ""            # 操作类型（从 tool_name 派生）
    file_path:   Optional[str] = None   # 提取自 tool_input（可选，方便过滤）
    command:     Optional[str] = None
    url:         Optional[str] = None


# ── 适配层 → 核心层的参数翻译表（与 adapters/hook.py 保持一致）──────────

_TOOL_PARAM_MAP: Dict[str, str] = {
    "Write":        "file_path",
    "Edit":         "file_path",
    "MultiEdit":    "file_path",
    "Read":         "file_path",
    "Glob":         "file_path",
    "Grep":         "file_path",
    "LS":           "file_path",
    "Bash":         "command",
    "WebFetch":     "url",
    "WebSearch":    "url",
    "Task":         "command",
    "TodoWrite":    "file_path",
    "NotebookEdit": "file_path",
}

# ── 追溯评估结果数据结构 ──────────────────────────────────────────────────

@dataclass
class RetroAssessment:
    """
    对一条历史工具调用记录的追溯评估结果。

    这不是 CIEU 记录，不写入实时 CIEU 数据库。
    它是追溯基线分析的中间结果，写入独立的 RetroBaselineStore。
    """
    # 来源信息（完整保留，用于溯源）
    tool_name:   str
    tool_input:  Dict[str, Any]
    timestamp:   float
    session_id:  str
    source_file: str
    event_type:  str

    # Y* 评估结果
    params:      Dict[str, Any]           # 传给 check() 的参数
    passed:      bool
    decision:    str                       # "allow" / "deny"
    violations:  List[Dict[str, Any]]     # 违规列表（dimension + message）

    # 追溯标注（永远是 True，用于区分实时记录）
    is_retroactive: bool = True
    source:         str  = "retroactive"  # 写入存储时的 source 标注


@dataclass
class RetroScanResult:
    """一次完整追溯扫描的统计摘要。"""
    total:           int = 0
    allow_count:     int = 0
    deny_count:      int = 0
    sessions:        int = 0
    date_range:      str = ""
    top_violations:  List[tuple] = field(default_factory=list)
    dim_coverage:    Dict[str, int] = field(default_factory=dict)  # 触发了哪些维度


# ── 参数构建（核心层内部，与 adapters/hook.py 的 _extract_params 对称）──

def _build_params(tool_name: str, tool_input: dict) -> dict:
    """
    把 ToolCallRecord 的 tool_input 翻译成 check() 的参数 dict。

    这是核心层版本的参数翻译，不依赖 adapters/hook.py，
    保证核心层对适配层零依赖。
    """
    params: Dict[str, Any] = {
        "action":    tool_name,
        "tool_name": tool_name,
    }

    primary = _TOOL_PARAM_MAP.get(tool_name)

    if primary == "file_path":
        params["file_path"] = (
            tool_input.get("path") or
            tool_input.get("file_path") or
            tool_input.get("pattern") or
            tool_input.get("directory") or ""
        )
    elif primary == "command":
        params["command"] = (
            tool_input.get("command") or
            tool_input.get("cmd") or ""
        )
    elif primary == "url":
        params["url"] = (
            tool_input.get("url") or
            tool_input.get("query") or ""
        )

    # MCP 工具
    if tool_name.startswith("mcp__"):
        for k, v in tool_input.items():
            if k.lower() in ("path", "file", "filepath", "file_path") and v:
                params.setdefault("file_path", str(v))
            if k.lower() in ("url", "endpoint", "uri") and v:
                params.setdefault("url", str(v))

    # 透传其余业务参数（amount / risk_approved 等）
    for k, v in tool_input.items():
        params.setdefault(k, v)

    return params


# ── 核心函数：追溯检查 ────────────────────────────────────────────────────

def assess_record(
    record: "ToolCallRecord",
    contract: "IntentContract",
) -> RetroAssessment:
    """
    对单条历史工具调用记录运行 check()，返回追溯评估结果。

    这是核心层的原子操作，确定性，无副作用。
    """
    from ystar.kernel.engine import check

    params = _build_params(record.tool_name, record.tool_input)
    result = check(params, {}, contract)

    # 过滤 phantom_variable（可选 invariant 缺失，不算真实违规）
    real_viols = [
        {"dimension": v.dimension, "message": v.message}
        for v in result.violations
        if v.dimension != "phantom_variable"
    ]
    passed   = len(real_viols) == 0
    decision = "allow" if passed else "deny"

    return RetroAssessment(
        tool_name   = record.tool_name,
        tool_input  = record.tool_input,
        timestamp   = record.timestamp,
        session_id  = record.session_id,
        source_file = record.source_file,
        event_type  = record.event_type,
        params      = params,
        passed      = passed,
        decision    = decision,
        violations  = real_viols,
    )


def assess_batch(
    records: List["ToolCallRecord"],
    contract: "IntentContract",
) -> List[RetroAssessment]:
    """
    对一批历史记录运行追溯检查，返回评估结果列表。

    这是核心层的批量操作，确定性，无副作用。
    """
    return [assess_record(r, contract) for r in records]


def summarize(assessments: List[RetroAssessment]) -> RetroScanResult:
    """
    统计追溯评估结果，产出 RetroScanResult 摘要。
    """
    from collections import Counter

    if not assessments:
        return RetroScanResult()

    allow_n = sum(1 for a in assessments if a.passed)
    deny_n  = len(assessments) - allow_n

    sessions = len({a.session_id for a in assessments})

    import datetime
    ts_list = [a.timestamp for a in assessments if a.timestamp > 0]
    if ts_list:
        oldest = datetime.datetime.fromtimestamp(min(ts_list)).strftime("%Y-%m-%d")
        newest = datetime.datetime.fromtimestamp(max(ts_list)).strftime("%Y-%m-%d")
        date_range = f"{oldest} → {newest}"
    else:
        date_range = "未知"

    # 违规维度统计
    dim_counter: Counter = Counter()
    for a in assessments:
        for v in a.violations:
            dim_counter[v["dimension"]] += 1

    return RetroScanResult(
        total          = len(assessments),
        allow_count    = allow_n,
        deny_count     = deny_n,
        sessions       = sessions,
        date_range     = date_range,
        top_violations = dim_counter.most_common(8),
        dim_coverage   = dict(dim_counter),
    )

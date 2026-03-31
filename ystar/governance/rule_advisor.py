# Layer: Intent Compilation
# Responsibility: Rules/needs -> IntentContract compilation only
# Does NOT: execute governance, write enforcement CIEU, command Path A/B
#
# ystar/governance/rule_advisor.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
ystar.governance.rule_advisor  —  规则优化建议引擎  v0.41.0
============================================================

治理层职责：
  从 CIEU 历史数据里生成规则优化建议，并把接受的建议写回 AGENTS.md。

两条建议来源（均来自已有元学习模块，不新建逻辑）：
  1. learn(history, contract) → MetalearnResult.contract_additions
     基于违规历史的确定性统计建议（置信度高，直接可用）

  2. discover_parameters(history, contract) + verify_proposal()
     数值型参数的统计分析 + 数学验证（需要 LLM 给阈值，或用统计降级）

写回 AGENTS.md 的策略：
  - 追加到文件末尾（不修改已有内容，保留用户意图）
  - 每条新规则用自然语言句式，与原有格式一致
  - 用 `# Y* 建议添加（基于 N 条 CIEU 记录）` 作为分隔头

三个判断问题验证治理层归属：
  Q2 需要记住历史吗？→ 需要（依赖 CIEU CallRecord 历史）→ 治理层 ✓
  Q3 翻译格式还是判断对错？→ 判断（分析规则质量）→ 不是适配层 ✓
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── 建议数据结构 ──────────────────────────────────────────────────────────

@dataclass
class RuleSuggestion:
    """一条规则优化建议。"""
    # 建议类型
    kind:        str          # "add" / "tighten" / "relax" / "dimension"

    # 内容
    dimension:   str          # deny / only_paths / value_range / …
    description: str          # 人类可读的建议说明
    evidence:    str          # 建议的统计依据

    # 具体值（用于写回 AGENTS.md）
    rule_value:  Any = None   # 新规则的具体值
    current_value: Any = None # 当前规则的值（用于对比）

    # 质量指标
    confidence:  float = 0.0  # 0~1
    coverage:    float = 0.0  # 如果接受，能防止历史违规的比例
    fp_rate:     float = 0.0  # 如果接受，误拦正常操作的比例

    # 来源
    source:      str  = ""    # "learn" / "discover_parameters" / "dimension_discovery"
    verified:    bool = False  # 是否通过 Y* 数学验证

    # 用户决策（初始为 None，用户确认后设置）
    accepted:    Optional[bool] = None


@dataclass
class RuleAdvice:
    """一次完整的规则优化建议集合。"""
    suggestions:  List[RuleSuggestion] = field(default_factory=list)
    history_size: int   = 0
    contract_src: str   = ""
    generated_at: float = field(default_factory=time.time)

    @property
    def add_suggestions(self):
        return [s for s in self.suggestions if s.kind == "add"]

    @property
    def tighten_suggestions(self):
        return [s for s in self.suggestions if s.kind == "tighten"]

    @property
    def relax_suggestions(self):
        return [s for s in self.suggestions if s.kind == "relax"]

    @property
    def dimension_suggestions(self):
        return [s for s in self.suggestions if s.kind == "dimension"]

    def accepted_count(self) -> int:
        return sum(1 for s in self.suggestions if s.accepted is True)

    def has_suggestions(self) -> bool:
        return len(self.suggestions) > 0


# ── 核心函数：从历史生成建议 ──────────────────────────────────────────────

def generate_advice(
    contract:    Any,          # IntentContract
    history:     List[Any],    # List[CallRecord]
    api_call_fn: Optional[Any] = None,
) -> RuleAdvice:
    """
    从 CIEU 历史数据生成规则优化建议。

    调用已有元学习管道：
      learn()              → 确定性统计建议（来源 A）
      discover_parameters()→ 参数发现（来源 B）
      verify_proposal()    → 数学验证

    Args:
        contract:    当前 IntentContract
        history:     CallRecord 列表（来自 CIEU 数据库）
        api_call_fn: 注入的 LLM 调用函数（None = 降级到纯统计）

    Returns:
        RuleAdvice 对象，含所有建议
    """
    from ystar.governance.metalearning import (
        learn, discover_parameters, verify_proposal,
        SemanticConstraintProposal, DimensionDiscovery
    )

    advice = RuleAdvice(
        history_size = len(history),
    )

    if not history:
        return advice

    # ── 来源 A：learn() 产出的确定性建议 ─────────────────────────────────
    try:
        result = learn(history, base_contract=contract)

        # A1：contract_additions — 新 deny / only_paths 等规则
        additions = result.contract_additions
        if additions and not additions.is_empty():
            d = additions.to_dict()
            for dim, values in d.items():
                if not values:
                    continue
                vals = values if isinstance(values, list) else [values]
                for v in vals:
                    advice.suggestions.append(RuleSuggestion(
                        kind        = "add",
                        dimension   = dim,
                        description = f"添加 {dim} 规则：{v}",
                        evidence    = f"历史中 {v!r} 出现在违规记录里，当前无对应规则",
                        rule_value  = v,
                        confidence  = 0.80,
                        source      = "learn",
                        verified    = True,   # learn() 产出已经过统计验证
                    ))

        # A2：dimension_hints — 建议引入新维度
        for hint in (result.dimension_hints or []):
            advice.suggestions.append(RuleSuggestion(
                kind        = "dimension",
                dimension   = "unknown",
                description = hint,
                evidence    = "DimensionDiscovery 从违规模式里发现",
                confidence  = 0.65,
                source      = "dimension_discovery",
            ))

        # A3：RefinementFeedback — 规则过紧或过松
        if result.quality:
            q = result.quality
            if q.false_positive_rate > 0.1:
                # 误拦率超 10%，说明有规则过紧
                advice.suggestions.append(RuleSuggestion(
                    kind        = "relax",
                    dimension   = "unknown",
                    description = f"误拦率 {q.false_positive_rate:.0%}，部分规则可能过紧",
                    evidence    = f"{int(q.false_positive_rate * len(history))} 条正常操作被拦截",
                    confidence  = 0.70,
                    fp_rate     = q.false_positive_rate,
                    source      = "learn",
                ))

    except Exception:
        pass

    # ── 来源 B：discover_parameters() → verify_proposal() ─────────────────
    try:
        hints = discover_parameters(history, known_contract=contract)
        for hint in hints:
            if hint.hint_type == "CATEGORICAL" and hint.confidence >= 0.6:
                # 有明确的"只在违规里出现"的值
                rule_str = hint.suggested_rule or f"deny_{hint.param_name}_{hint.violation_values[0] if hint.violation_values else '?'}"
                advice.suggestions.append(RuleSuggestion(
                    kind        = "add",
                    dimension   = hint.suggested_dim or "deny",
                    description = f"{hint.param_name} 中有值只出现在违规记录里",
                    evidence    = (f"安全值: {hint.safe_values[:3]}, "
                                   f"违规值: {hint.violation_values[:3]}"),
                    rule_value  = hint.violation_values[0] if hint.violation_values else None,
                    confidence  = hint.confidence,
                    source      = "discover_parameters",
                ))

            elif hint.hint_type in ("NUMERIC_THRESHOLD", "OBSERVED_ONLY") and hint.suggested_rule:
                # 有数值阈值建议，走 verify_proposal 验证
                proposal = SemanticConstraintProposal(
                    param_name    = hint.param_name,
                    suggested_dim = hint.suggested_dim or "value_range",
                    suggested_rule= hint.suggested_rule,
                    reasoning     = f"统计分析：{hint.explain()[:100]}",
                    confidence    = hint.confidence,
                    statistical_hint = hint,
                )
                report = verify_proposal(proposal, history, stat_hint=hint)
                if report.verdict in ("PASS", "WARN") and report.quality_score >= 0.5:
                    advice.suggestions.append(RuleSuggestion(
                        kind        = "tighten",
                        dimension   = hint.suggested_dim or "value_range",
                        description = f"{hint.param_name} 建议添加数值约束",
                        evidence    = (f"建议规则：{hint.suggested_rule}，"
                                       f"验证结果：{report.verdict}，"
                                       f"覆盖率：{report.empirical_coverage:.0%}"),
                        rule_value  = hint.suggested_rule,
                        confidence  = hint.confidence * 0.8,
                        coverage    = report.empirical_coverage,
                        fp_rate     = report.empirical_fp_rate,
                        source      = "discover_parameters+verify",
                        verified    = (report.verdict == "PASS"),
                    ))

    except Exception:
        pass

    # 按置信度降序排列
    advice.suggestions.sort(key=lambda s: s.confidence, reverse=True)
    return advice


# ── 任务4：反向翻译 contract → AGENTS.md 自然语言 ────────────────────────

def contract_to_agents_md_lines(contract: Any) -> List[str]:
    """
    把 IntentContract 字段反向翻译成 AGENTS.md 自然语言句式。

    确定性，无 LLM，模板化。
    每个维度对应一种固定句式，保持与原有 AGENTS.md 格式一致。
    """
    lines = []

    for path in (contract.deny or []):
        lines.append(f"- Never modify or access {path}")

    for path in (contract.only_paths or []):
        lines.append(f"- Only write to {path}")

    for cmd in (contract.deny_commands or []):
        lines.append(f"- Never run {cmd}")

    for domain in (contract.only_domains or []):
        lines.append(f"- Only call {domain}")

    for param, bounds in (contract.value_range or {}).items():
        if "max" in bounds and "min" in bounds:
            lines.append(
                f"- {param} must be between {bounds['min']} and {bounds['max']}"
            )
        elif "max" in bounds:
            lines.append(f"- Maximum {param}: {bounds['max']}")
        elif "min" in bounds:
            lines.append(f"- Minimum {param}: {bounds['min']}")

    for inv in (contract.invariant or []):
        lines.append(f"- Require: {inv}")

    for inv in (contract.optional_invariant or []):
        lines.append(f"- When present, require: {inv}")

    return lines


def append_suggestions_to_agents_md(
    agents_md_path: str,
    accepted_suggestions: List[RuleSuggestion],
    history_size: int,
) -> bool:
    """
    把用户接受的规则建议追加到 AGENTS.md 末尾。

    策略：
    - 只追加，不修改已有内容（保留用户意图）
    - 用注释行分隔，说明建议来源
    - 返回 True = 写入成功

    追加后需要重新运行 ystar init 让新规则生效。
    """
    path = Path(agents_md_path)
    if not path.exists():
        return False

    if not accepted_suggestions:
        return False

    # 构建追加内容
    import datetime
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "",
        f"# Y* 建议添加（基于 {history_size} 条 CIEU 记录，{now}）",
    ]

    for s in accepted_suggestions:
        if s.rule_value is not None:
            # 有具体值的建议，用标准句式
            from ystar.kernel.dimensions import IntentContract
            tmp = {}
            if s.dimension == "deny":
                tmp["deny"] = [str(s.rule_value)]
            elif s.dimension == "only_paths":
                tmp["only_paths"] = [str(s.rule_value)]
            elif s.dimension == "deny_commands":
                tmp["deny_commands"] = [str(s.rule_value)]
            elif s.dimension == "only_domains":
                tmp["only_domains"] = [str(s.rule_value)]
            elif s.dimension == "value_range":
                # rule_value 形如 "amount <= 10000"
                tmp["value_range"] = _parse_rule_to_value_range(str(s.rule_value))

            try:
                from ystar.kernel.dimensions import normalize_aliases
                partial = normalize_aliases(**tmp)
                rule_lines = contract_to_agents_md_lines(partial)
                lines.extend(rule_lines)
            except Exception:
                # 降级：翻译失败时写成人工可读的提示行
                lines.append(f"# 待补充：{s.description}（置信度 {s.confidence:.0%}）")
        else:
            # 没有具体值（如 dimension_hints），写成注释提示
            lines.append(f"# 建议考虑：{s.description}")

    content = "\n".join(lines) + "\n"

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False


def _parse_rule_to_value_range(rule_str: str) -> Dict[str, Any]:
    """从规则字符串解析出 value_range dict。如 'amount <= 10000' → {'amount': {'max': 10000}}"""
    import re
    m = re.match(r"(\w+)\s*([<>]=?|==)\s*(\d+(?:\.\d+)?)", rule_str)
    if not m:
        return {}
    param, op, val_str = m.group(1), m.group(2), m.group(3)
    val = float(val_str) if "." in val_str else int(val_str)
    if op in ("<=", "<"):
        return {param: {"max": val}}
    elif op in (">=", ">"):
        return {param: {"min": val}}
    return {}

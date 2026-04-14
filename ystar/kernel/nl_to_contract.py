# Layer: Intent Compilation
# Responsibility: Rules/needs -> IntentContract compilation only
# Does NOT: execute governance, write enforcement CIEU, command Path A/B
"""
ystar.kernel.nl_to_contract
============================
自然语言 → IntentContract 翻译层（v0.42.0）

唯一职责：用 LLM 把 AGENTS.md / CLAUDE.md 里的自然语言规则
翻译成结构化的 IntentContract JSON，然后让用户确认。

不确定性边界：
  LLM 翻译 → DRAFT（唯一可能引入不确定性的步骤）
  用户确认 → ACTIVE（确认后进入确定性 check() 流程）

降级策略：
  LLM 不可用时，回退到现有的正则解析器（_load_policy_doc）。
  结果置信度较低，但不会崩溃，只是覆盖率下降。

模型无关架构（v0.42.0）：
  支持多种 LLM 提供商：Anthropic、OpenAI（及兼容端点）、本地模型
  通过 YSTAR_LLM_PROVIDER 环境变量选择，保持向后兼容
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── IntentContract 的 schema 描述（作为 LLM prompt 的一部分）────────────

_SCHEMA_DESCRIPTION = """
IntentContract 有以下字段（全部可选，只填能从文本确定的部分）：

deny: list[str]
  参数里绝对不允许出现的字符串（路径片段、关键词等）
  例："deny": ["/production", ".env", "DROP TABLE"]

only_paths: list[str]
  允许写入的文件路径白名单（不在列表里的路径被拒绝）
  例："only_paths": ["./workspace/", "./src/"]

deny_commands: list[str]
  禁止执行的命令前缀（完整短语，不是单个词）
  例："deny_commands": ["rm -rf", "git push --force", "sudo"]

only_domains: list[str]
  允许访问的域名/URL 白名单
  例："only_domains": ["api.stripe.com", "api.github.com"]

invariant: list[str]
  对函数输入参数的 Python 布尔表达式
  默认行为：当参数缺失时 fail-open (不阻止执行)，除非规则显式设置 strict: true
  例："invariant": ["amount > 0", "risk_approved == True"]

optional_invariant: list[str]
  同 invariant，但仅当该变量存在于调用参数中才检查
  例："optional_invariant": ["settlement_risk < 0.8"]

value_range: dict
  数值参数的范围约束，格式：{"参数名": {"min": N, "max": N}}
  例："value_range": {"amount": {"min": 1, "max": 10000}}

temporal: dict
  行动频率上限（agent 能做多快），格式：{"max_calls": N, "window_seconds": N}
  例："temporal": {"max_calls": 10, "window_seconds": 3600}

obligation_timing: dict
  义务完成时限（agent 必须多快做），单位：秒
  与 temporal 完全不同：temporal 限制频率，obligation_timing 设定承诺期限
  支持的键：
    delegation      任务必须在此时间内分配给子 agent
    acknowledgement 任务必须在此时间内被接受/确认
    status_update   必须在此时间内汇报进度
    completion      任务必须在此时间内完成
    escalation      收到阻塞后必须在此时间内升级
    closure         完成后必须在此时间内正式关闭
    result_publication 结果必须在此时间内发布
  例："obligation_timing": {"acknowledgement": 300, "completion": 3600}
"""

_TRANSLATION_PROMPT_TEMPLATE = """你是一个把自然语言约束规则翻译成结构化 JSON 的工具。

目标格式（IntentContract）：
{schema}

翻译规则：
1. 只输出纯 JSON，不要任何解释、标题或 markdown 代码块
2. 只填写能从文本里明确确定的字段，不要猜测
3. deny_commands 要包含完整命令短语，不只是第一个词
   例："Never run git push --force" → deny_commands: ["git push --force"]
   不要翻译成 deny_commands: ["git"]
4. 对于 "只能访问 api.xxx.com"，用 only_domains 而不是 deny
5. 数值约束用 value_range，不要用 invariant
6. 行动频率限制（每小时/每分钟 N 次）用 temporal
7. 中英文都要能识别
8. 义务时限（任务必须多久内完成/确认/分配）用 obligation_timing，单位秒：
   - "任务必须在 5 分钟内确认" → obligation_timing: {{"acknowledgement": 300}}
   - "30 分钟内完成" → obligation_timing: {{"completion": 1800}}
   - "1 小时内汇报进度" → obligation_timing: {{"status_update": 3600}}
   - "10 分钟内分配给子 agent" → obligation_timing: {{"delegation": 600}}
   - 可同时设多个：{{"acknowledgement": 300, "completion": 3600}}
   - 区分：temporal 是频率上限，obligation_timing 是期限承诺，不要混淆

待翻译的文本：
{text}

直接输出 JSON 对象，不要包含任何其他内容："""


# ── Provider 抽象层 ──────────────────────────────────────────────────────

class TranslationProvider:
    """LLM 翻译提供商基类。"""

    def translate(self, prompt: str) -> Optional[str]:
        """
        发送 prompt 给 LLM，返回原始响应文本。
        失败时抛出异常（由调用方处理）。
        """
        raise NotImplementedError


class AnthropicProvider(TranslationProvider):
    """Anthropic Claude API 提供商。"""

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("YSTAR_LLM_MODEL", "claude-sonnet-4-20250514")
        self.base_url = os.environ.get("YSTAR_LLM_BASE_URL", "https://api.anthropic.com/v1")

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

    def translate(self, prompt: str) -> Optional[str]:
        """使用 Anthropic API 翻译。"""
        req_body = json.dumps({
            "model": self.model,
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/messages",
            data=req_body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"]


class OpenAIProvider(TranslationProvider):
    """
    OpenAI-compatible API 提供商。

    兼容：
    - OpenAI (api.openai.com)
    - Azure OpenAI
    - 本地 Ollama (http://localhost:11434/v1)
    - 大多数 OpenAI-compatible 端点
    """

    def __init__(self):
        # 优先使用 YSTAR_LLM_API_KEY，回退到 OPENAI_API_KEY
        self.api_key = os.environ.get("YSTAR_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("YSTAR_LLM_MODEL", "gpt-4o-mini")
        self.base_url = os.environ.get("YSTAR_LLM_BASE_URL", "https://api.openai.com/v1")

        # 移除 base_url 末尾的斜杠（如果有）
        self.base_url = self.base_url.rstrip("/")

        if not self.api_key:
            raise ValueError("YSTAR_LLM_API_KEY or OPENAI_API_KEY not set")

    def translate(self, prompt: str) -> Optional[str]:
        """使用 OpenAI-compatible API 翻译。"""
        req_body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1000,
            "temperature": 0,
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=req_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]


class RegexProvider:
    """
    正则表达式回退提供商（不是真正的 LLM）。
    这是一个特殊的 provider，用于显式禁用 LLM 翻译。
    """
    pass  # 不需要实现 translate()，由 _try_regex_translation() 处理


def get_provider() -> Optional[TranslationProvider]:
    """
    根据环境变量选择并返回合适的 LLM 提供商。

    选择逻辑：
    1. 检查 YSTAR_LLM_PROVIDER 环境变量
    2. 如果未设置，检查 ANTHROPIC_API_KEY（向后兼容）
    3. 如果都没有，返回 None（使用 regex 回退）

    Returns:
        TranslationProvider 实例或 None（使用 regex）
    """
    provider_name = os.environ.get("YSTAR_LLM_PROVIDER", "").lower().strip()

    # 未设置 provider，检查向后兼容
    if not provider_name:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider_name = "anthropic"
        else:
            print("  [Y*] No LLM provider configured. Using regex fallback (limited coverage).", file=sys.stderr)
            print("  [Y*] To enable LLM translation, set YSTAR_LLM_PROVIDER=openai or anthropic", file=sys.stderr)
            return None

    # 显式选择 regex
    if provider_name == "regex":
        print("  [Y*] Using regex-only mode (LLM translation disabled)", file=sys.stderr)
        return None

    # Anthropic
    if provider_name == "anthropic":
        try:
            provider = AnthropicProvider()
            print(f"  [Y*] Using Anthropic provider (model: {provider.model})", file=sys.stderr)
            return provider
        except ValueError as e:
            print(f"  [Y*] Failed to initialize Anthropic provider: {e}", file=sys.stderr)
            print("  [Y*] Falling back to regex", file=sys.stderr)
            return None

    # OpenAI (covers OpenAI, Azure, Ollama, etc.)
    if provider_name == "openai":
        try:
            provider = OpenAIProvider()
            print(f"  [Y*] Using OpenAI-compatible provider (model: {provider.model}, endpoint: {provider.base_url})", file=sys.stderr)
            return provider
        except ValueError as e:
            print(f"  [Y*] Failed to initialize OpenAI provider: {e}", file=sys.stderr)
            print("  [Y*] Falling back to regex", file=sys.stderr)
            return None

    # 未知的 provider
    print(f"  [Y*] Unknown provider '{provider_name}'. Supported: anthropic, openai, regex", file=sys.stderr)
    print("  [Y*] Falling back to regex", file=sys.stderr)
    return None


# ── 核心翻译函数 ──────────────────────────────────────────────────────────

def translate_to_contract(
    text: str,
    api_call_fn: Optional[Any] = None,
) -> Tuple[Dict[str, Any], str, float]:
    """
    把自然语言文本翻译成 IntentContract 字段字典。

    Returns:
        (contract_dict, method, confidence)
        - contract_dict: IntentContract 可接受的字段字典
        - method: "llm" 或 "regex"（使用了哪种方式）
        - confidence: 0~1，llm=0.9，regex=0.5

    降级策略：
        LLM 不可用或解析失败 → 回退到正则解析器
    """
    # 先尝试 LLM 翻译
    llm_result = _try_llm_translation(text, api_call_fn)
    if llm_result is not None:
        return llm_result, "llm", 0.90

    # 降级：正则解析器
    print("  [Y*] Regex mode has limited coverage. For better results, set YSTAR_LLM_PROVIDER=anthropic or openai", file=sys.stderr)
    regex_result = _try_regex_translation(text)
    return regex_result, "regex", 0.50


def _try_llm_translation(
    text: str,
    api_call_fn: Optional[Any],
) -> Optional[Dict[str, Any]]:
    """
    调用 LLM 翻译，失败返回 None。

    使用 provider 抽象层支持多种 LLM：
    - api_call_fn 不为 None：测试注入
    - api_call_fn 为 None：使用 get_provider() 选择真实 provider
    """
    prompt = _TRANSLATION_PROMPT_TEMPLATE.format(
        schema=_SCHEMA_DESCRIPTION,
        text=text.strip()[:3000],   # 截断超长文本
    )

    try:
        if api_call_fn is not None:
            # 注入的测试函数（向后兼容现有测试）
            response_text = api_call_fn(prompt)
        else:
            # 真实 API 调用：使用 provider 系统
            provider = get_provider()
            if provider is None:
                # 没有可用的 provider，静默回退到 regex
                return None

            response_text = provider.translate(prompt)

        # 解析 JSON 响应
        clean = re.sub(r"```\w*\n?|\n?```", "", response_text).strip()
        parsed = json.loads(clean)

        # 只保留 IntentContract 合法字段
        valid_fields = {
            "deny", "only_paths", "deny_commands", "only_domains",
            "invariant", "optional_invariant", "value_range", "temporal",
            "obligation_timing",
        }
        result = {k: v for k, v in parsed.items()
                  if k in valid_fields and v}
        return result if result else None

    except Exception as e:
        # Log the error for debugging
        print(f"  [Y*] LLM translation failed: {type(e).__name__}: {str(e)[:100]}. Falling back to regex.", file=sys.stderr)
        return None


def _try_regex_translation(text: str) -> Dict[str, Any]:
    """回退：用现有的正则解析器。"""
    try:
        from ystar.kernel.prefill import _extract_constraints_from_text
        raw = _extract_constraints_from_text(text)
        # 过滤掉内部调试字段（以 _ 开头）
        return {k: v for k, v in raw.items()
                if not k.startswith("_") and v}
    except Exception:
        return {}


# ── Y* 驱动的合约草稿验证层 ──────────────────────────────────────────────

def validate_contract_draft(
    contract_dict: Dict[str, Any],
    original_text: str = "",
) -> Dict[str, Any]:
    """
    用 Y* 自身的规则引擎验证 LLM 翻译草稿的质量。

    这是插在"LLM 翻译"和"人工确认"之间的确定性检查层：
      LLM 翻译（不确定）→ [本函数] → 人工确认 → check()（确定性）

    检查三类问题：
      1. 错误（errors）   — 明确的翻译错误，如 invariant 语法、数值方向相反
      2. 警告（warnings） — 可能的问题，如命令截断、路径语义混淆
      3. 薄弱（thin）     — 规则过于稀疏，关键维度未覆盖

    Returns:
        {
          "errors":       List[str],  # 必须修复
          "warnings":     List[str],  # 建议确认
          "suggestions":  List[str],  # 可以考虑补充的维度
          "coverage":     float,      # 维度覆盖率 0~1
          "is_healthy":   bool,       # 无 errors 且 coverage >= 0.25
        }
    """
    from ystar.kernel.engine import _safe_eval

    errors:      List[str] = []
    warnings_:   List[str] = []
    suggestions: List[str] = []

    text_lower = original_text.lower()

    # ── 1. invariant / postcondition 语法检查 ──────────────────────────
    for field in ("invariant", "optional_invariant", "postcondition"):
        for expr in (contract_dict.get(field) or []):
            # 单个 = 而不是 == → 赋值语法错误
            if re.search(r'(?<!=)=(?!=)', expr):
                errors.append(
                    f"invariant 语法错误：'{expr}' 含有赋值符号 '='，"
                    f"比较应该用 '=='（如 'risk_approved == True'）"
                )
            # 用 _safe_eval 做白名单检查
            else:
                _, err = _safe_eval(
                    expr,
                    {k: True for k in re.findall(r'\b[a-z_][a-z0-9_]*\b', expr)}
                )
                if err and "not defined" not in err and "NameError" not in err:
                    errors.append(f"invariant '{expr}' 表达式无效：{err}")

    # ── 2. value_range 方向检查（对照原文关键词）──────────────────────
    MAX_KEYWORDS = ["maximum", "最大", "max", "不超过", "上限", "at most",
                    "no more than", "less than or equal"]
    MIN_KEYWORDS = ["minimum", "最小", "min", "至少", "下限", "at least",
                    "greater than", "no less than", "more than"]

    for param, bounds in (contract_dict.get("value_range") or {}).items():
        mn = bounds.get("min")
        mx = bounds.get("max")

        # min > max → 明确错误
        if mn is not None and mx is not None and mn > mx:
            errors.append(
                f"value_range.{param}: min({mn}) > max({mx})，"
                f"数值范围无效（最小值不能大于最大值）"
            )

        # 文本说最大但翻译成了 min
        if any(w in text_lower for w in MAX_KEYWORDS):
            if mn is not None and mx is None:
                warnings_.append(
                    f"原文含有'最大/maximum'关键词，"
                    f"但 {param} 被翻译成 min={mn}，"
                    f"请确认：是上限（max）还是下限（min）？"
                )

        # 文本说最小但翻译成了 max
        if any(w in text_lower for w in MIN_KEYWORDS):
            if mx is not None and mn is None:
                warnings_.append(
                    f"原文含有'最小/minimum'关键词，"
                    f"但 {param} 被翻译成 max={mx}，"
                    f"请确认：是下限（min）还是上限（max）？"
                )

    # ── 3. 路径语义混淆检查 ───────────────────────────────────────────
    for d in (contract_dict.get("deny") or []):
        if d.startswith("./") or (d.startswith("/") and len(d) > 3
                                   and not any(bad in d for bad in
                                               ["production", "etc", "env",
                                                "secret", "passwd", "shadow"])):
            warnings_.append(
                f"deny 里有路径格式 '{d}'。"
                f"如果这是【禁止访问的路径】，deny 正确；"
                f"如果这是【允许写入的路径白名单】，应该放在 only_paths 里"
            )

    # ── 4. deny_commands 截断检查 ────────────────────────────────────
    for cmd in (contract_dict.get("deny_commands") or []):
        if len(cmd) <= 3 and " " not in cmd:
            warnings_.append(
                f"deny_commands '{cmd}' 非常短（{len(cmd)} 个字符），"
                f"可能丢失了后续参数（如 'rm' → 'rm -rf'，'git' → 'git push --force'）"
            )

    # ── 5. 维度覆盖率评估 + 补充建议 ────────────────────────────────
    dim_active = {
        "deny":          bool(contract_dict.get("deny")),
        "only_paths":    bool(contract_dict.get("only_paths")),
        "deny_commands": bool(contract_dict.get("deny_commands")),
        "only_domains":  bool(contract_dict.get("only_domains")),
        "invariant":     bool(contract_dict.get("invariant") or
                               contract_dict.get("optional_invariant")),
        "value_range":   bool(contract_dict.get("value_range")),
        "postcondition": bool(contract_dict.get("postcondition")),
        "field_deny":    bool(contract_dict.get("field_deny")),
    }
    coverage = sum(dim_active.values()) / 8

    # 生成针对性建议
    if not dim_active["only_paths"] and not dim_active["deny"]:
        suggestions.append(
            "路径约束：Agent 能访问任意文件路径。"
            "建议在 AGENTS.md 里说明[只能写入哪些目录]或[禁止访问哪些路径]"
        )
    if not dim_active["deny_commands"]:
        suggestions.append(
            "命令约束：Agent 能执行任意系统命令。"
            "建议在 AGENTS.md 里列出禁止的危险命令（如 rm -rf、git push --force）"
        )
    if not dim_active["only_domains"]:
        suggestions.append(
            "域名约束：Agent 能访问任意外部 URL。"
            "建议在 AGENTS.md 里说明[只允许访问哪些域名]"
        )
    if not dim_active["value_range"] and not dim_active["invariant"]:
        suggestions.append(
            "业务约束：没有数值限制或前置条件。"
            "如果 Agent 会涉及金额/数量/权限，建议添加对应约束"
        )

    is_healthy = (len(errors) == 0 and coverage >= 0.25)

    return {
        "errors":      errors,
        "warnings":    warnings_,
        "suggestions": suggestions,
        "coverage":    coverage,
        "dim_active":  dim_active,
        "is_healthy":  is_healthy,
    }


def format_validation_report(validation: Dict[str, Any]) -> str:
    """把验证结果格式化成人类可读的确认前提示。"""
    lines = []
    coverage = validation["coverage"]
    errors   = validation["errors"]
    warnings = validation["warnings"]
    suggestions = validation["suggestions"]

    # 总体健康度
    if errors:
        lines.append("  ❌ 发现翻译错误，请修正后重新确认：")
        for e in errors:
            lines.append(f"     → {e}")
        lines.append("")
    
    if warnings:
        lines.append("  ⚠  请确认以下几点是否符合你的意图：")
        for w in warnings:
            lines.append(f"     → {w}")
        lines.append("")

    # 维度覆盖率
    bar_filled = int(coverage * 20)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    level = ("💪 较完整" if coverage >= 0.625 else
             "⚠  较薄弱" if coverage >= 0.25  else
             "❌ 非常薄弱")
    lines.append(f"  规则覆盖率: [{bar}] {coverage:.0%}  {level}")
    lines.append(f"  ({sum(validation['dim_active'].values())}/8 个约束维度已激活)")

    if suggestions:
        lines.append("")
        lines.append("  💡 当前规则可能不足以保护 Agent，建议在 AGENTS.md 里补充：")
        for s in suggestions:
            lines.append(f"     → {s}")

    lines.append("")
    # 底部边界说明
    lines.append("  ─── 确定性边界说明 ───────────────────────────────")
    lines.append("  确认后，以上规则进入 Y* 确定性执行层。")
    lines.append("  之后每次 Agent 执行操作，check() 的结果永远确定，不再有 LLM 参与。")

    return "\n".join(lines)



_DIM_LABELS = {
    "deny":               "禁止出现的字符串",
    "only_paths":         "允许写入的路径（白名单）",
    "deny_commands":      "禁止执行的命令",
    "only_domains":       "允许访问的域名（白名单）",
    "invariant":          "必须满足的条件",
    "optional_invariant": "条件满足时才检查",
    "value_range":        "数值范围约束",
    "temporal":           "频率限制",
}

_DIM_ICONS = {
    "deny":               "✗",
    "only_paths":         "✓",
    "deny_commands":      "✗",
    "only_domains":       "✓",
    "invariant":          "=",
    "optional_invariant": "?",
    "value_range":        "#",
    "temporal":           "⏱",
}


def format_contract_for_human(
    contract_dict: Dict[str, Any],
    method: str = "llm",
    confidence: float = 0.9,
    original_text: str = "",
    show_validation: bool = True,
) -> str:
    """把翻译结果格式化成普通人能读懂的文字（用于确认）。
    
    包含两部分：
      1. 翻译结果展示（你写的规则 → Y* 的理解）
      2. Y* 的确定性验证报告（错误/警告/覆盖率/建议）
    """
    lines = []
    lines.append("")
    lines.append("  Y* 将你的规则理解为：")
    lines.append("  " + "─" * 45)
    lines.append("")

    if not contract_dict:
        lines.append("  （未能解析到任何规则）")
        return "\n".join(lines)

    for dim, label in _DIM_LABELS.items():
        val = contract_dict.get(dim)
        if not val:
            continue
        icon = _DIM_ICONS.get(dim, "·")
        lines.append(f"  {label}：")
        if isinstance(val, list):
            for item in val:
                lines.append(f"    {icon} {item}")
        elif isinstance(val, dict):
            if dim == "value_range":
                for param, bounds in val.items():
                    parts = []
                    if "min" in bounds:
                        parts.append(f"最小 {bounds['min']}")
                    if "max" in bounds:
                        parts.append(f"最大 {bounds['max']}")
                    lines.append(f"    {icon} {param}：{' / '.join(parts)}")
            elif dim == "temporal":
                calls = val.get("max_calls", "?")
                secs  = val.get("window_seconds", 0)
                window = (f"{secs//3600}小时" if secs >= 3600
                          else f"{secs//60}分钟" if secs >= 60
                          else f"{secs}秒")
                lines.append(f"    {icon} 每 {window} 最多 {calls} 次")
        lines.append("")

    method_note = "LLM 翻译" if method == "llm" else "正则解析（LLM 不可用时的降级）"
    lines.append(f"  ─── 解析方式：{method_note}，置信度 {confidence:.0%} ───")
    lines.append("")

    # Y* 确定性验证层
    if show_validation:
        validation = validate_contract_draft(contract_dict, original_text)
        lines.append("  Y* 验证结果：")
        lines.append(format_validation_report(validation))

    return "\n".join(lines)


def confirm_in_terminal(
    contract_dict: Dict[str, Any],
    method: str = "llm",
    confidence: float = 0.9,
    original_text: str = "",
) -> bool:
    """
    在终端展示翻译结果和 Y* 验证报告，等待用户确认。

    交互逻辑：
      - 有 errors → 必须选择修改（不能直接确认）
      - 有 warnings → 可以确认，也可以返回修改
      - 无问题 → 直接确认

    Returns:
        True = 用户确认（激活），False = 用户拒绝/需要修改
    """
    print(format_contract_for_human(contract_dict, method, confidence, original_text))

    validation = validate_contract_draft(contract_dict, original_text)

    # 有明确错误时，强制要求修改
    if validation["errors"]:
        print()
        print("  ⛔ 发现翻译错误，无法直接确认。")
        print("  请修改 AGENTS.md 并重新运行 ystar init，或选择 [e] 手动编辑规则。")
        print()
        while True:
            try:
                answer = input("  选择：[e] 编辑规则后重试  [q] 退出 > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return False
            if answer in ("q", "quit", "exit"):
                return False
            if answer in ("e", "edit"):
                print()
                print("  请修改 AGENTS.md，然后重新运行 ystar init。")
                print()
                return False
            print("  请输入 e 或 q")
        return False

    # 有警告时，给出选项
    if validation["warnings"] or validation["suggestions"]:
        prompt = "  以上是你的意思吗？规则有待完善但可先确认。[Y/n/e(编辑)] "
    else:
        prompt = "  以上是你的意思吗？[Y/n] "

    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False

        if answer in ("", "y", "yes", "是", "对"):
            print()
            print("  ✅ 规则已确认，进入 Y* 确定性执行层。")
            print("  之后每次 Agent 操作，check() 结果永远确定，LLM 不再参与。")
            print()
            return True
        if answer in ("n", "no", "否", "不"):
            print()
            print("  已取消。请修改 AGENTS.md 后重新运行 ystar init，")
            print("  或使用 from_template() 精确定义规则。")
            print()
            return False
        if answer in ("e", "edit", "编辑"):
            print()
            print("  请修改 AGENTS.md，然后重新运行 ystar init。")
            print()
            return False
        print("  请输入 Y（确认）、N（取消）或 E（编辑后重试）")


# ── 从文件加载 ─────────────────────────────────────────────────────────────

def find_agents_md(start_dir: Optional[str] = None) -> Optional[Path]:
    """在标准位置查找 AGENTS.md / CLAUDE.md。"""
    search_dirs = [Path(start_dir)] if start_dir else [
        Path.cwd(),
        Path.cwd() / ".claude",
        Path.home() / ".claude",
        Path.home(),
    ]
    candidates = ["AGENTS.md", "CLAUDE.md", "agents.md", "claude.md"]
    for d in search_dirs:
        for name in candidates:
            p = d / name
            if p.exists():
                return p
    return None


def load_and_translate(
    path: Optional[str] = None,
    confirm: bool = False,
    api_call_fn: Optional[Any] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    查找 AGENTS.md → 翻译 → 可选人工确认。

    Returns:
        (contract_dict, source_path)
        contract_dict = None 表示用户拒绝或文件未找到
    """
    # 找文件
    if path:
        md_path = Path(path)
        if not md_path.exists():
            print(f"  [Y*] 文件未找到: {path}", file=sys.stderr)
            return None, ""
    else:
        md_path = find_agents_md()
        if md_path is None:
            return None, ""

    text = md_path.read_text(encoding="utf-8", errors="replace")

    # 翻译
    contract_dict, method, confidence = translate_to_contract(text, api_call_fn)

    if not contract_dict:
        return {}, str(md_path)

    # 确认
    if confirm:
        approved = confirm_in_terminal(contract_dict, method, confidence, text)
        if not approved:
            return None, str(md_path)

    return contract_dict, str(md_path)


# ── Compile Diagnostics & Ambiguity ──────────────────────────────────────────

@dataclass
class CompileDiagnostics:
    """
    Diagnostics report for a contract compilation.

    Produced by diagnose_compilation() to surface ambiguities,
    unsupported rules, and confidence issues before human review.
    """
    confidence: float = 0.0              # 0-1
    ambiguous_rules: List[str] = field(default_factory=list)    # rules that couldn't be clearly parsed
    unsupported_rules: List[str] = field(default_factory=list)  # rules that have no mapping
    warnings: List[str] = field(default_factory=list)
    requires_human_review: bool = False  # True if confidence < 0.7 or ambiguities exist


def diagnose_compilation(
    source_text: str,
    contract_dict: Dict[str, Any],
) -> CompileDiagnostics:
    """
    Produce a diagnostics report for a compiled contract.

    Analyzes the source text against the compiled contract to identify:
    - Ambiguous rules (text that might map to multiple dimensions)
    - Unsupported rules (text with constraint-like language but no mapping)
    - Low confidence warnings
    - Whether human review is needed

    Args:
        source_text: the original natural language text
        contract_dict: the compiled contract fields dict

    Returns:
        CompileDiagnostics with analysis results
    """
    diag = CompileDiagnostics()

    # Run validation to get coverage and warnings
    validation = validate_contract_draft(contract_dict, source_text)
    diag.warnings = list(validation.get("warnings", []))

    # Calculate confidence from coverage and errors
    coverage = validation.get("coverage", 0.0)
    errors = validation.get("errors", [])
    if errors:
        diag.confidence = max(0.1, coverage * 0.3)
    else:
        diag.confidence = max(0.3, min(0.95, coverage * 0.5 + 0.5))

    # Scan source text for constraint-like patterns that weren't captured
    _CONSTRAINT_PATTERNS = [
        (r'(?:must|should|shall|need to|required to)\s+\w+', "obligation"),
        (r'(?:never|cannot|must not|shall not|do not|don\'t)\s+\w+', "prohibition"),
        (r'(?:only|exclusively|solely)\s+(?:access|use|write|read)', "restriction"),
        (r'(?:within|before|after|every)\s+\d+\s*(?:seconds?|minutes?|hours?|days?)', "temporal"),
        (r'(?:maximum|minimum|at most|at least|no more than)\s+\d+', "value_range"),
        (r'(?:forbidden|prohibited|banned|blocked|disallowed)', "prohibition"),
    ]

    text_lower = source_text.lower()
    detected_intents: List[str] = []
    for pattern, intent_type in _CONSTRAINT_PATTERNS:
        matches = re.findall(pattern, text_lower)
        for m in matches:
            detected_intents.append(f"{intent_type}: '{m.strip()[:60]}'")

    # Check which detected intents have corresponding contract fields
    mapped_dimensions = set()
    if contract_dict.get("deny"):
        mapped_dimensions.add("prohibition")
    if contract_dict.get("only_paths") or contract_dict.get("only_domains"):
        mapped_dimensions.add("restriction")
    if contract_dict.get("deny_commands"):
        mapped_dimensions.add("prohibition")
    if contract_dict.get("temporal"):
        mapped_dimensions.add("temporal")
    if contract_dict.get("value_range"):
        mapped_dimensions.add("value_range")
    if contract_dict.get("obligation_timing"):
        mapped_dimensions.add("obligation")
    if contract_dict.get("invariant") or contract_dict.get("optional_invariant"):
        mapped_dimensions.add("obligation")

    for intent in detected_intents:
        intent_type = intent.split(":")[0].strip()
        if intent_type not in mapped_dimensions:
            diag.unsupported_rules.append(intent)

    # Detect ambiguity: text that could map to multiple dimensions
    _AMBIGUOUS_PATTERNS = [
        (r'(?:path|file|directory|folder)', {"deny", "only_paths"},
         "path reference could be deny (blocklist) or only_paths (allowlist)"),
        (r'(?:api|url|endpoint|domain)', {"deny", "only_domains"},
         "URL/domain reference could be deny (blocklist) or only_domains (allowlist)"),
    ]
    for pattern, dimensions, explanation in _AMBIGUOUS_PATTERNS:
        if re.search(pattern, text_lower):
            active_dims = dimensions & set(contract_dict.keys())
            # If the text mentions paths/URLs but only one dimension is set,
            # the other might be what was intended
            if len(active_dims) <= 1 and len(dimensions) > 1:
                diag.ambiguous_rules.append(explanation)

    # Determine if human review is required
    diag.requires_human_review = (
        diag.confidence < 0.7
        or len(diag.ambiguous_rules) > 0
        or len(errors) > 0
    )

    return diag

"""
ystar.products.report_render  —  Report Rendering (Operator Products)
======================================================================
v0.41.0

reporting.py 物理拆分完成：

  ystar/governance/report_metrics.py  ← 指标数据类（Governance Services）✓
  ystar/products/report_render.py     ← 报告渲染（Operator Products）     ← 此文件
  ystar/reporting.py                  ← 向后兼容统一入口（re-export）

此文件承接 Report 类的产品渲染职责：
  - to_markdown()   : 人类可读的 Markdown 报告
  - to_json()       : 机器可读的 JSON 报告
  - to_hn_summary() : HN/X 公开 280 字摘要（标准化输出）
  - delta()         : 与基线对比的 delta 表格

不承接：
  - 指标收集（OmissionMetrics 等 → governance/report_metrics.py）
  - ReportEngine（→ reporting.py）
  - 报告交付（→ adapters/report_delivery.py）

设计原则：
  渲染是消费指标的最后一步，属于 Operator Products。
  改变渲染格式不应影响 Governance Services 层的任何代码。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ystar.governance.reporting import Report


def render_markdown(report: "Report") -> str:
    """
    将 Report 对象渲染为 Markdown 格式。
    规范路径：from ystar.products.report_render import render_markdown
    """
    return report.to_markdown()


def render_json(report: "Report", indent: int = 2) -> str:
    """
    将 Report 对象序列化为 JSON 格式。
    """
    return report.to_json(indent=indent)


def render_hn_summary(report: "Report") -> str:
    """
    产出适合在 HN/X 公开发布的 280 字以内标准化摘要。

    格式固定，让每次发布有统一口径。
    不再靠人工临时编写叙事。
    """
    kpis = report.kpis or {}
    omission = report.omissions

    # Health assessment
    expiry_rate   = kpis.get("obligation_expiry_rate", 0)
    fulfill_rate  = kpis.get("obligation_fulfillment_rate", 0)
    recovery_rate = kpis.get("omission_recovery_rate", 0)
    fp_rate       = kpis.get("false_positive_rate", 0)
    closure_rate  = kpis.get("chain_closure_rate", 0)

    if expiry_rate < 0.1 and fp_rate < 0.02:
        health = "🟢 HEALTHY"
    elif expiry_rate > 0.3 or fp_rate > 0.1:
        health = "🔴 CRITICAL"
    else:
        health = "🟡 DEGRADED"

    # Build concise summary
    lines = [
        f"Y* Governance Report — {report.period_label}",
        f"{health}",
        f"",
        f"Obligations:  {fulfill_rate:.0%} fulfilled, {expiry_rate:.0%} expired",
        f"Omissions:    {omission.total_violations} violations, {recovery_rate:.0%} recovered",
        f"Chain closure: {closure_rate:.0%}",
        f"False positives: {fp_rate:.0%}",
    ]

    if omission.most_common_breakpoint:
        lines.append(f"Top breakpoint: {omission.most_common_breakpoint}")

    if omission.by_type:
        top_type = max(omission.by_type.items(), key=lambda x: x[1])
        short = top_type[0].replace("required_", "").replace("_omission", "")
        lines.append(f"Most common: {short} ({top_type[1]}×)")

    lines.append(f"")
    lines.append(f"v{report.integrity.ystar_version} | confidence: {report.integrity.report_confidence_level}")

    result = "\n".join(lines)
    # Enforce 280-char limit on first line for X/Twitter compatibility
    if len(result) > 280:
        result = result[:277] + "..."
    return result


def render_delta_table(report: "Report", baseline: "Report") -> str:
    """
    产出与基线对比的 Markdown delta 表格。
    """
    delta = report.delta(baseline)
    lines = [
        f"## Y* Governance Delta: {baseline.period_label} → {report.period_label}",
        f"",
        f"| Metric | Baseline | Current | Δ | Direction |",
        f"|--------|----------|---------|---|-----------|",
    ]
    for metric, d in delta.items():
        short = metric.replace("_rate", "").replace("_", " ").title()
        direction = {"improved": "✅ ↑", "regressed": "⚠️ ↓", "neutral": "—"}.get(
            d["direction"], "—"
        )
        lines.append(
            f"| {short} | {d['baseline']:.1%} | {d['current']:.1%} "
            f"| {d['delta']:+.1%} | {direction} |"
        )
    return "\n".join(lines)


__all__ = [
    "render_markdown",
    "render_json",
    "render_hn_summary",
    "render_delta_table",
]

"""
ystar.products  —  Operator Products Layer
==========================================
v0.41.0

面向人和外部系统的报告、证明与交付层。

层级规则：
  ✓ 可以依赖：所有下层（kernel, governance, domains, adapters）
  ✗ 不允许：被 kernel / governance 反向依赖

此层的职责：消费治理结果，交付价值。不定义规范。
"""
# A/B experiment framework
from ystar.products.omission_experiment import (
    run_ab_experiment, run_full_battery,
    print_ab_report, print_battery_report,
    ABReport, GroupMetrics, TrialResult,
)

# Report delivery (Operator Products side — delivery channels)
# 3-C: 归位后从 products.report_delivery 直接导入
from ystar.products.report_delivery import (
    DeliveryManager, DeliveryResult,
    EmailConfig, WebhookConfig, OpenClawInjectionConfig, FileConfig,
    create_delivery_manager,
)

# Report generation (Product side — rendering)
from ystar.governance.reporting import ArtifactIntegrity
from ystar.products.report_render import (
    render_markdown,
    render_json,
    render_hn_summary,
    render_delta_table,
)

__all__ = [
    "run_ab_experiment", "run_full_battery",
    "print_ab_report", "print_battery_report",
    "ABReport", "GroupMetrics", "TrialResult",
    "DeliveryManager", "DeliveryResult",
    "EmailConfig", "WebhookConfig", "OpenClawInjectionConfig", "FileConfig",
    "create_delivery_manager",
    "ArtifactIntegrity",
    # Report rendering
    "render_markdown", "render_json", "render_hn_summary", "render_delta_table",
]

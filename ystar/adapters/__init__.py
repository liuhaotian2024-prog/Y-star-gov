"""
ystar.adapters  —  Ecosystem Adapters Layer
============================================
v0.41.0

外部生态与 Y* Kernel/Governance 之间的翻译与接线层。

层级规则：
  ✓ 可以依赖：ystar.kernel, ystar.governance, ystar.domains.*
  ✗ 不允许：被 Kernel / Governance 反向依赖
  ✗ 不应：在此层重新发明 omission/intervention 主逻辑

此层职责：
  - 外部事件 → Y* GovernanceEvent 翻译
  - entity_id / lineage 绑定与诊断
  - 报告交付通道（email / webhook / injection）

规范路径（新代码应使用此路径）：
  from ystar.adapters.omission_adapter import OmissionAdapter
  from ystar.adapters.report_delivery import DeliveryManager

兼容路径（历史代码，仍有效）：
  from ystar.adapters.omission_adapter import OmissionAdapter  ← re-exported
  from ystar.adapters.report_delivery import DeliveryManager   ← re-exported
"""
# Omission adapter (primary event translation layer)
from ystar.adapters.omission_adapter import (
    OmissionAdapter,
    DiagnosticResult,
    BindingFailureMode,
    create_adapter,
)

# Report delivery (output channel adapters)
from ystar.adapters.report_delivery import (
    DeliveryManager,
    DeliveryResult,
    create_delivery_manager,
    EmailConfig,
    WebhookConfig,
    OpenClawInjectionConfig,
    FileConfig,
)

# OpenClaw HTTP connector + approval queue
try:
    from ystar.adapters.connector import (
        OpenClawHTTPConnector,
        ApprovalQueue,
        PendingApproval,
    )
    _connector_available = True
except ImportError:
    _connector_available = False

__all__ = [
    # Omission adapter
    "OmissionAdapter",
    "DiagnosticResult",
    "BindingFailureMode",
    "create_adapter",
    # Report delivery
    "DeliveryManager",
    "DeliveryResult",
    "create_delivery_manager",
    "EmailConfig",
    "WebhookConfig",
    "OpenClawInjectionConfig",
    "FileConfig",
]

"""
ystar.governance.metrics  —  Governance Metrics Collection
===========================================================
v0.41.0

reporting.py 分层（P2）：
  ystar/governance/metrics.py   ← 指标收集（Governance Services 层）
  ystar/reporting.py            ← 报告渲染（现在成为 Product 层入口）

这个文件承接 reporting.py 中属于治理服务层的部分：
  - 指标数据类（ObligationMetrics, OmissionMetrics 等）
  - ReportEngine（从 store 读取，产出 Report 对象）

不承接：
  - to_markdown()（产品渲染，属于 Operator Products）
  - 报告交付（属于 Ecosystem Adapters）

使用方式：
    # 只需要指标数据类（不需要渲染）
    from ystar.governance.metrics import ObligationMetrics, ReportEngine

    # 需要完整报告（含渲染）
    from ystar.governance.reporting import Report  # 仍从 reporting.py 使用
"""
# Re-export from reporting.py (single source of truth, no duplication)
from ystar.governance.reporting import (
    ArtifactIntegrity,
    ObligationMetrics,
    OmissionMetrics,
    InterventionMetrics,
    ChainClosureMetrics,
    CIEUMetrics,
    Report,
    ReportEngine,
)

__all__ = [
    "ArtifactIntegrity",
    "ObligationMetrics",
    "OmissionMetrics",
    "InterventionMetrics",
    "ChainClosureMetrics",
    "CIEUMetrics",
    "Report",
    "ReportEngine",
]

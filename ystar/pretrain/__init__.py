"""ystar.pretrain — v6.0 预训练参数
完整管道: scan_history→CIEU→synth_obligations→GovernanceLoop→learn+autotune
数据: 10360条 (9来源含消极不作为)
"""
from ystar.pretrain.loader import (
    load_pretrained_objective, load_pretrained_coefficients,
    load_drift_signals, load_skill_signals,
    load_discovered_patterns, load_omission_types,
    pretrain_summary,
    PRETRAIN_VERSION, PRETRAIN_DATASET_SIZE,
    AUTOTUNE_CYCLES, GOVERNANCE_CYCLES,
)
__all__ = [
    "load_pretrained_objective", "load_pretrained_coefficients",
    "load_drift_signals", "load_skill_signals",
    "load_discovered_patterns", "load_omission_types",
    "pretrain_summary",
    "PRETRAIN_VERSION", "PRETRAIN_DATASET_SIZE",
    "AUTOTUNE_CYCLES", "GOVERNANCE_CYCLES",
]

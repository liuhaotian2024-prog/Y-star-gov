"""
ystar.governance.auto_configure  —  P3: Governance Auto-Configuration
======================================================================
v0.41.0

"GovernanceLoop 建议 → 受控激活 → 实际影响治理参数"

这是 P3 的核心：把 GovernanceLoop 产出的建议，
通过 ConstraintRegistry 受控链，真正应用到 domain pack 配置。

闭环路径：
  omission scan → violations → GovernanceLoop.observe()
    → GovernanceLoop.tighten() → GovernanceSuggestions
    → submit_to_registry() → ConstraintRegistry (DRAFT→APPROVED)
    → apply_active_to_pack() → RuleRegistry timing updated
    → next scan sees updated timing → re-baseline

注意事项（宪法守卫）：
  - 只允许修改 domain pack 层的时限（due_within_secs）
  - 不允许修改 Kernel 层规则（不得低于 KERNEL_SAFE_DEFAULT_DUE_SECS / 10）
  - 所有变更写入 ConstraintRegistry 并可回滚
  - 高置信度 (>= 0.9) 才能自动应用；其他需要人工审批
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional, TYPE_CHECKING

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ystar.governance.governance_loop import GovernanceLoop
    from ystar.governance.omission_rules import RuleRegistry


# 宪法守卫：auto-configure 不得把时限压低到此值以下
# (= KERNEL_SAFE_DEFAULT_DUE_SECS / 10 = 360 秒)
AUTO_CONFIGURE_FLOOR_SECS = 360.0

# 自动激活置信度阈值（兜底值）
# 高于此置信度的学习建议会自动应用到规则；低于此值的需要人工审批
# 用户可在 .ystar_session.json 的 governance_config.auto_activate_threshold 里覆盖
_AUTO_ACTIVATE_THRESHOLD_FALLBACK = 0.9


def _get_auto_activate_threshold() -> float:
    """
    读取自动激活置信度阈值。

    优先级（高 → 低）：
      1. .ystar_session.json 中 governance_config.auto_activate_threshold
      2. 兜底常量 0.9

    场景说明：
      谨慎场景（金融/医疗）: 0.95+，减少误激活
      标准场景:              0.9（默认）
      宽松场景（快速迭代）:  0.8，更积极的自动学习
    """
    try:
        import json
        from pathlib import Path as _Path
        p = _Path(".ystar_session.json")
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            gc  = cfg.get("governance_config", {})
            val = gc.get("auto_activate_threshold")
            if val is not None and isinstance(val, (int, float)) and 0 < val <= 1.0:
                return float(val)
    except Exception as e:
        # Optional config read — fallback to default is acceptable
        _log.debug(f"Could not read auto_activate_threshold from .ystar_session.json: {e}")
    return _AUTO_ACTIVATE_THRESHOLD_FALLBACK


# 向后兼容（直接 import AUTO_ACTIVATE_THRESHOLD 的代码仍可用）
AUTO_ACTIVATE_THRESHOLD = _AUTO_ACTIVATE_THRESHOLD_FALLBACK


def run_governance_auto_configure(
    governance_loop: "GovernanceLoop",
    omission_registry: "RuleRegistry",
    auto_activate_threshold: Optional[float] = None,
    dry_run: bool = False,
) -> dict:
    """
    完整的治理自动配置周期：
      1. 从 GovernanceLoop 触发一次观测
      2. 运行 tighten() 产出建议
      3. 把建议提交到 ConstraintRegistry（走受控链）
      4. 把 ACTIVE 约束应用到 omission_registry
      5. 返回操作摘要

    Args:
        governance_loop:         已配置的 GovernanceLoop 实例
        omission_registry:       OmissionRule RuleRegistry
        auto_activate_threshold: 高于此置信度的建议自动 approve
                                 None = 从 .ystar_session.json 读取，无则用兜底 0.9
        dry_run:                 True = 只计算建议，不实际修改 registry

    Returns:
        {
          "observations":  int,          # 观测历史长度
          "suggestions":   int,          # 产出建议数量
          "submitted":     int,          # 提交到 ConstraintRegistry 的数量
          "applied":       int,          # 实际应用到 omission_registry 的数量
          "dry_run":       bool,
          "health":        str,
          "summary":       str,
          "constraint_registry_state": str,
        }
    """
    # 解析激活阈值：None → 从 session 读取 → 兜底值
    threshold = auto_activate_threshold \
        if auto_activate_threshold is not None \
        else _get_auto_activate_threshold()

    # Step 1: 观测
    obs = governance_loop.observe_from_report_engine()

    # Step 2: 学习
    result = governance_loop.tighten()

    # Step 3: 提交到 ConstraintRegistry
    submitted = 0
    if not dry_run:
        submitted = governance_loop.submit_suggestions_to_registry(
            result,
            auto_approve_confidence_threshold=threshold,
        )

    # Step 4: 把 APPROVED 约束 activate，然后应用到 omission_registry
    applied = 0
    if not dry_run and governance_loop.constraint_registry:
        try:
            # Activate all APPROVED constraints
            approved = governance_loop.constraint_registry.by_status("APPROVED")
            for mc in approved:
                governance_loop.constraint_registry.activate(
                    mc.id, notes="auto-activated by governance_auto_configure"
                )
            # Apply ACTIVE constraints to registry (with floor guard)
            applied = _apply_active_constraints_with_floor(
                governance_loop.constraint_registry,
                omission_registry,
            )
        except Exception as e:
            _log.error(f"Failed to activate/apply constraints: {e}")

    registry_state = ""
    if governance_loop.constraint_registry:
        try:
            registry_state = governance_loop.constraint_registry.summary()
        except Exception as e:
            _log.warning(f"Failed to get constraint registry summary: {e}")

    return {
        "observations":              len(governance_loop.observation_history()),
        "suggestions":               len(result.governance_suggestions),
        "submitted":                 submitted,
        "applied":                   applied,
        "dry_run":                   dry_run,
        "health":                    result.overall_health,
        "recommended_action":        result.recommended_action,
        "constraint_registry_state": registry_state,
        "summary":                   result.summary(),
    }


def _apply_active_constraints_with_floor(
    constraint_registry: Any,
    omission_registry: "RuleRegistry",
) -> int:
    """
    把 ACTIVE 约束应用到 RuleRegistry，带宪法下限守卫。
    低于 AUTO_CONFIGURE_FLOOR_SECS 的调整会被拒绝。
    """
    applied = 0
    try:
        active = constraint_registry.by_status("ACTIVE")
        for mc in active:
            parts = mc.rule.split(":", 2)
            if len(parts) < 2:
                continue
            rule_id, sug_type = parts[0], parts[1]
            try:
                rule = omission_registry.get(rule_id)
                if rule is None:
                    continue

                if sug_type == "tighten_timing":
                    new_due = rule.due_within_secs * 0.8
                    # 宪法守卫：不得低于下限
                    new_due = max(new_due, AUTO_CONFIGURE_FLOOR_SECS)
                    if new_due < rule.due_within_secs:
                        omission_registry.override_timing(rule_id, due_within_secs=new_due)
                        applied += 1

                elif sug_type == "relax_timing":
                    new_due = rule.due_within_secs * 1.2
                    omission_registry.override_timing(rule_id, due_within_secs=new_due)
                    applied += 1

            except Exception as e:
                _log.warning(f"Failed to apply constraint {mc.id} to rule {rule_id}: {e}")
    except Exception as e:
        _log.error(f"Failed to apply active constraints: {e}")
    return applied


class GovernanceAutoConfigureScheduler:
    """
    自动配置调度器（可附加到 OmissionScanner）。

    每次 scanner 扫到 violation 时，自动触发一次
    governance auto-configure 周期（有频率限制）。

    使用方式：
        scheduler = GovernanceAutoConfigureScheduler(
            governance_loop=loop,
            omission_registry=registry,
        )
        scanner = OmissionScanner(engine=engine)
        scheduler.attach_to_scanner(scanner)
    """

    def __init__(
        self,
        governance_loop: "GovernanceLoop",
        omission_registry: "RuleRegistry",
        min_interval_secs: float = 300.0,   # 最多每5分钟触发一次
        auto_activate_threshold: Optional[float] = None,  # None = 从 session 读取
        dry_run: bool = False,
    ) -> None:
        self.governance_loop         = governance_loop
        self.omission_registry       = omission_registry
        self.min_interval_secs       = min_interval_secs
        self.auto_activate_threshold = auto_activate_threshold  # None 表示动态读取
        self.dry_run                 = dry_run
        self._last_run:              float = 0.0
        self._run_count:             int   = 0
        self._last_result:           Optional[dict] = None

    def attach_to_scanner(self, scanner: Any) -> None:
        """挂载到 OmissionScanner 的 on_violation 回调。"""
        original = getattr(scanner, 'on_violation', lambda v: None)

        def _on_violation_with_autoconfig(v):
            original(v)
            self._maybe_run()

        scanner.on_violation = _on_violation_with_autoconfig

    def _maybe_run(self) -> None:
        now = time.time()
        if now - self._last_run < self.min_interval_secs:
            return
        self._last_run = now
        self._run_count += 1
        self._last_result = run_governance_auto_configure(
            governance_loop   = self.governance_loop,
            omission_registry = self.omission_registry,
            auto_activate_threshold = self.auto_activate_threshold,
            dry_run           = self.dry_run,
        )

    def status(self) -> dict:
        return {
            "run_count":   self._run_count,
            "last_run":    self._last_run,
            "last_result": self._last_result,
        }

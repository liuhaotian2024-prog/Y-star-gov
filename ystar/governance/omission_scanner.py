"""
ystar.omission_scanner  —  Periodic Omission Governance Scanner
===============================================================

后台定时扫描线程。每隔 scan_interval_secs 调用一次 engine.scan()，
将 violation / escalation 结果发送到注册的 handler。

这是 omission governance 从"批量检测"升级为"实时监控"的关键组件。

架构：
    OmissionScanner
        └─ 后台线程 (daemon=True)
               └─ engine.scan()
                      ├─ violations   → on_violation(v)
                      ├─ escalations  → on_escalation(v)
                      └─ reminders    → on_reminder(ob)

使用方式：
    from ystar.governance.omission_scanner import OmissionScanner

    scanner = OmissionScanner(
        engine           = adapter.engine,
        scan_interval_secs = 5.0,
        on_violation     = lambda v: print(f"VIOLATION: {v.omission_type}"),
        on_escalation    = lambda v: print(f"ESCALATED: {v.omission_type} → {v.escalated_to}"),
    )
    scanner.start()
    # ... your workload ...
    scanner.stop()
    report = scanner.last_report()
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from ystar.governance.omission_models import ObligationRecord, OmissionViolation
from ystar.governance.omission_engine import OmissionEngine, EngineResult
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore

AnyStore = Union[InMemoryOmissionStore, OmissionStore]
ViolationHandler = Callable[[OmissionViolation], None]
ObligationHandler = Callable[[ObligationRecord], None]


# ── Scanner 状态快照 ──────────────────────────────────────────────────────────

@dataclass
class ScanReport:
    """一次扫描周期的汇总输出。"""
    scan_count:         int = 0
    total_violations:   int = 0
    total_escalations:  int = 0
    total_reminders:    int = 0
    last_scan_at:       Optional[float] = None
    last_violation_at:  Optional[float] = None
    errors:             List[str] = field(default_factory=list)

    def record_result(self, result: EngineResult) -> None:
        self.scan_count       += 1
        self.total_violations += len(result.violations)
        self.total_escalations+= len(result.escalated)
        self.total_reminders  += len(result.reminders)
        self.last_scan_at      = time.time()
        if result.violations:
            self.last_violation_at = self.last_scan_at

    def to_dict(self) -> dict:
        return {
            "scan_count":        self.scan_count,
            "total_violations":  self.total_violations,
            "total_escalations": self.total_escalations,
            "total_reminders":   self.total_reminders,
            "last_scan_at":      self.last_scan_at,
            "last_violation_at": self.last_violation_at,
            "errors":            self.errors,
        }


# ── OmissionScanner ───────────────────────────────────────────────────────────

class OmissionScanner:
    """
    后台定时扫描线程。

    参数：
        engine:              OmissionEngine 实例
        scan_interval_secs:  扫描间隔（秒），默认 10s
        on_violation:        violation 回调，签名 (OmissionViolation) -> None
        on_escalation:       escalation 回调，签名 (OmissionViolation) -> None
        on_reminder:         reminder 回调，签名 (ObligationRecord) -> None
        on_scan:             每次扫描完成回调，签名 (EngineResult) -> None
        name:                线程名（用于日志）
    """

    def __init__(
        self,
        engine:               OmissionEngine,
        scan_interval_secs:   float = 10.0,
        on_violation:         Optional[ViolationHandler]  = None,
        on_escalation:        Optional[ViolationHandler]  = None,
        on_reminder:          Optional[ObligationHandler] = None,
        on_scan:              Optional[Callable[[EngineResult], None]] = None,
        name:                 str = "omission-scanner",
    ) -> None:
        self.engine              = engine
        self.scan_interval_secs  = scan_interval_secs
        self.on_violation        = on_violation  or _noop_v
        self.on_escalation       = on_escalation or _noop_v
        self.on_reminder         = on_reminder   or _noop_ob
        self.on_scan             = on_scan       or _noop_r
        self._name               = name

        self._stop_event         = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._report             = ScanReport()
        self._lock               = threading.Lock()

    # ── 生命周期 ─────────────────────────────────────────────────────────────

    def start(self) -> "OmissionScanner":
        """启动后台扫描线程。返回 self（支持链式调用）。"""
        if self._thread and self._thread.is_alive():
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=self._name,
            daemon=True,  # 主线程退出时自动停止
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        """发送停止信号并等待线程退出。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── 手动扫描（不使用后台线程）────────────────────────────────────────────

    def scan_once(self) -> EngineResult:
        """手动触发一次扫描（同步，不需要 start()）。"""
        return self._do_scan()

    # ── 状态报告 ─────────────────────────────────────────────────────────────

    def last_report(self) -> ScanReport:
        with self._lock:
            return self._report

    def report_dict(self) -> dict:
        return self.last_report().to_dict()

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """后台线程主循环。"""
        while not self._stop_event.is_set():
            self._do_scan()
            self._stop_event.wait(timeout=self.scan_interval_secs)

    def _do_scan(self) -> EngineResult:
        try:
            result = self.engine.scan()

            with self._lock:
                self._report.record_result(result)

            for v in result.violations:
                self._safe_call(self.on_violation, v)
            for v in result.escalated:
                self._safe_call(self.on_escalation, v)
            for ob in result.reminders:
                self._safe_call(self.on_reminder, ob)
            self._safe_call(self.on_scan, result)

            return result
        except Exception as e:
            with self._lock:
                self._report.errors.append(f"{time.time():.0f}: {e}")
            return EngineResult()

    def _safe_call(self, fn: Any, arg: Any) -> None:
        try:
            fn(arg)
        except Exception as e:
            with self._lock:
                self._report.errors.append(f"callback error: {e}")


# ── Null 回调 ─────────────────────────────────────────────────────────────────
def _noop_v(v: OmissionViolation) -> None: pass
def _noop_ob(ob: ObligationRecord) -> None: pass
def _noop_r(r: EngineResult) -> None: pass


# ── 全局便捷 scanner（与 configure_omission_governance 配套）────────────────

_default_scanner: Optional[OmissionScanner] = None


def start_global_scanner(
    engine:             Optional[OmissionEngine] = None,
    scan_interval_secs: float = 10.0,
    on_violation:       Optional[ViolationHandler] = None,
    on_escalation:      Optional[ViolationHandler] = None,
    on_reminder:        Optional[ObligationHandler] = None,
    log_violations:     bool = True,
) -> OmissionScanner:
    """
    启动全局 omission scanner 便捷函数。

    若未提供 engine，自动从 configure_omission_governance() 设置的 adapter 获取。

    参数：
        log_violations: True 时自动将 violation 打印到 stderr
    """
    global _default_scanner

    if engine is None:
        raise RuntimeError(
            "No engine available. Pass engine= explicitly or call "
            "configure_omission_governance() first.\n"
            "Tip: engine = OmissionEngine(store=store, registry=registry)"
        )

    _viol_handler = on_violation
    if log_violations and _viol_handler is None:
        import sys
        def _log_viol(v: OmissionViolation) -> None:
            print(
                f"[omission] {v.omission_type} | "
                f"entity={v.entity_id} | actor={v.actor_id} | "
                f"+{v.overdue_secs:.1f}s overdue",
                file=sys.stderr,
            )
        _viol_handler = _log_viol

    _default_scanner = OmissionScanner(
        engine             = engine,
        scan_interval_secs = scan_interval_secs,
        on_violation       = _viol_handler,
        on_escalation      = on_escalation,
        on_reminder        = on_reminder,
    ).start()

    return _default_scanner


def stop_global_scanner() -> None:
    global _default_scanner
    if _default_scanner:
        _default_scanner.stop()
        _default_scanner = None

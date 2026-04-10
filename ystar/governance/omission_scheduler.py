"""
omission_scheduler.py — GOV-010 Phase 1

Lightweight scheduler that converts OmissionEngine.scan() from a manual
call into something that can be automatically triggered by normal agent
work (e.g., PostToolUse in hook_wrapper.py).

Design requirements (non-negotiable):
  - tick() < 100ms per call
  - Idempotent: calling tick() 100 times in 1 second = same as calling it once
  - Fail-open: any error in scan → log and return, never raise
  - No threads, no cron, no daemon: piggybacks on the agent's own tool calls

Usage in hook_wrapper.py PostToolUse::

    from ystar.governance.omission_scheduler import OmissionScheduler
    scheduler = OmissionScheduler(engine, interval_seconds=300)
    scheduler.tick()  # called after every tool; scans at most once per interval
"""
import time
import traceback
from typing import Optional, Any


class OmissionScheduler:
    """Drives OmissionEngine.scan() at a configurable interval.

    The scheduler keeps a single timestamp (``_last_scan_ts``) and only
    runs ``engine.scan()`` if at least ``interval_seconds`` have passed.
    Everything else is a no-op.

    Parameters
    ----------
    engine : OmissionEngine
        The engine whose ``.scan()`` method will be called.
    interval_seconds : float
        Minimum gap between consecutive scans (default 300 = 5 minutes).
    log_fn : callable, optional
        Where to send debug/error messages. Default: ``print``.
    """

    def __init__(
        self,
        engine: Any,
        interval_seconds: float = 300.0,
        log_fn: Optional[Any] = None,
    ) -> None:
        self.engine = engine
        self.interval = interval_seconds
        self._last_scan_ts: float = 0.0
        self._log = log_fn or (lambda msg: None)  # silent by default

    def should_scan(self, now: Optional[float] = None) -> bool:
        """Return True if enough time has passed since the last scan."""
        now = now or time.time()
        return (now - self._last_scan_ts) >= self.interval

    def tick(self, now: Optional[float] = None) -> dict:
        """Called on every agent tool invocation. Runs scan() at most
        once per ``interval_seconds``.

        Returns a dict:
          {"scanned": False}                     — skipped (too soon)
          {"scanned": True, "violations": [...]} — scan ran
          {"scanned": False, "error": "..."}     — scan failed (fail-open)
        """
        now = now or time.time()
        if not self.should_scan(now):
            return {"scanned": False}

        try:
            result = self.engine.scan()
            self._last_scan_ts = now
            violations = []
            if hasattr(result, 'violations'):
                violations = list(result.violations)
            elif isinstance(result, dict):
                violations = result.get('violations', [])
            elif isinstance(result, (list, tuple)):
                violations = list(result)
            self._log(
                f"[omission-scheduler] scan complete: "
                f"{len(violations)} violation(s)"
            )
            return {"scanned": True, "violations": violations}
        except Exception as exc:
            self._log(
                f"[omission-scheduler] scan failed (fail-open): "
                f"{type(exc).__name__}: {exc}"
            )
            # Don't update _last_scan_ts so next tick retries
            return {"scanned": False, "error": str(exc)}

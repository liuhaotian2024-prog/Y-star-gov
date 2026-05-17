"""
ystar.czl.probe — v4.0 T2 universal subprocess probe executor.

Generic shell runner. Model emits a probe block; the loop captures the
command and runs it here, returns stdout/stderr/returncode to next iter's
prompt.

Founder principle compliance:
  - No Trampoline-preset tool: command is whatever the model writes.
  - No scenario-specific bias: same probe protocol for every scenario.
  - Constants are physical resource bounds (subprocess timeout 60s,
    stdout 2000 chars, stderr 1000 chars). Not business logic.
  - Network disabled (HTTP_PROXY/HTTPS_PROXY cleared) — defensive.
    Model can still touch local network if the system allows; this only
    blocks the user's proxy config from leaking.

Each probe execution writes one r=0 CIEU event to the audit log via
benchmarks.czl_arbitrage.cieu_full_spectrum.append_event when available.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


# Physical resource limits — not business logic
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_STDOUT_MAX = 2000
_DEFAULT_STDERR_MAX = 1000


@dataclass
class ProbeResult:
    command: str
    stdout: str
    stderr: str
    returncode: int           # -1 for timeout / signal kill
    wall_seconds: float
    truncated_stdout: bool = False
    truncated_stderr: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "wall_seconds": round(self.wall_seconds, 3),
            "truncated_stdout": self.truncated_stdout,
            "truncated_stderr": self.truncated_stderr,
            "error": self.error,
        }


class ProbeExecutor:
    """Stateless executor. One instance per CZL run; ok to reuse across iters."""

    def __init__(
        self,
        workspace_dir: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        stdout_max: int = _DEFAULT_STDOUT_MAX,
        stderr_max: int = _DEFAULT_STDERR_MAX,
        cieu_writer: Optional[Any] = None,
    ):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = float(timeout_seconds)
        self.stdout_max = int(stdout_max)
        self.stderr_max = int(stderr_max)
        # cieu_writer is optional — typically the append_event function
        self._cieu_writer = cieu_writer

    def run(self, command: str) -> ProbeResult:
        if not command or not command.strip():
            return ProbeResult(
                command=command or "",
                stdout="", stderr="empty command", returncode=-1,
                wall_seconds=0.0, error="empty_command",
            )
        # Hardened env — clear proxies, leave PATH and basic locale intact
        env = dict(os.environ)
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)
        env.pop("http_proxy", None)
        env.pop("https_proxy", None)
        env.pop("ALL_PROXY", None)
        env.pop("all_proxy", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # don't pollute workspace

        t0 = time.time()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            wall = time.time() - t0
            result = ProbeResult(
                command=command,
                stdout="",
                stderr=f"timeout after {self.timeout_seconds}s",
                returncode=-1,
                wall_seconds=wall,
                error="timeout",
            )
            self._write_cieu(result)
            return result
        except Exception as e:
            wall = time.time() - t0
            result = ProbeResult(
                command=command,
                stdout="",
                stderr=f"{type(e).__name__}: {e}",
                returncode=-1,
                wall_seconds=wall,
                error=type(e).__name__,
            )
            self._write_cieu(result)
            return result

        wall = time.time() - t0
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        truncated_stdout = len(stdout) > self.stdout_max
        truncated_stderr = len(stderr) > self.stderr_max
        if truncated_stdout:
            stdout = stdout[: self.stdout_max] + f"\n... [truncated, total {len(proc.stdout)} chars]"
        if truncated_stderr:
            stderr = stderr[: self.stderr_max] + f"\n... [truncated, total {len(proc.stderr)} chars]"
        result = ProbeResult(
            command=command,
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode,
            wall_seconds=wall,
            truncated_stdout=truncated_stdout,
            truncated_stderr=truncated_stderr,
        )
        self._write_cieu(result)
        return result

    def _write_cieu(self, result: ProbeResult) -> None:
        """Best-effort r=0 CIEU event per probe. Failures are silent — we
        do not break the loop on audit-write failure."""
        if self._cieu_writer is None:
            try:
                from benchmarks.czl_arbitrage.cieu_full_spectrum import append_event
                self._cieu_writer = append_event
            except Exception:
                self._cieu_writer = False  # poison so we don't retry
                return
        if self._cieu_writer is False:
            return
        try:
            self._cieu_writer(
                milestone_id="step_v4.0_probe_execution",
                y_star="probe command executed and stdout/stderr captured",
                actions_taken=[
                    f"command: {result.command[:200]}",
                    f"returncode: {result.returncode}",
                    f"wall_seconds: {result.wall_seconds:.3f}",
                    f"stdout_truncated: {result.truncated_stdout}",
                    f"stderr_truncated: {result.truncated_stderr}",
                ],
                y_t_plus_1=f"stdout head: {result.stdout[:200]}",
                r_t_plus_1=0,
                verify_command="see probe_result.to_dict()",
                verify_output_tail=f"rc={result.returncode}",
                outcome_based_only=True,
            )
        except Exception:
            self._cieu_writer = False


def render_probe_results_block(
    iter_idx: int,
    probe_results: list,
) -> str:
    """Render captured probe results as a prompt section for the NEXT iter.

    Format:
      ## Probe results from iter {N}

      ### Probe 1
      Command: ...
      Returncode: ...
      Wall: ...s
      Stdout:
      ```
      ...
      ```
      Stderr (if any):
      ```
      ...
      ```
    """
    if not probe_results:
        return ""
    lines = [f"## Probe results from iter {iter_idx}", ""]
    for i, r in enumerate(probe_results, start=1):
        if isinstance(r, ProbeResult):
            d = r.to_dict()
        elif isinstance(r, dict):
            d = r
        else:
            continue
        lines.append(f"### Probe {i}")
        lines.append(f"Command: `{d['command']}`")
        lines.append(f"Returncode: {d['returncode']}")
        lines.append(f"Wall: {d['wall_seconds']}s")
        stdout = d.get("stdout") or ""
        if stdout.strip():
            lines.append("Stdout:")
            lines.append("```")
            lines.append(stdout.rstrip())
            lines.append("```")
        else:
            lines.append("Stdout: (empty)")
        stderr = d.get("stderr") or ""
        if stderr.strip():
            lines.append("Stderr:")
            lines.append("```")
            lines.append(stderr.rstrip())
            lines.append("```")
        if d.get("error"):
            lines.append(f"(probe error: {d['error']})")
        lines.append("")
    return "\n".join(lines)

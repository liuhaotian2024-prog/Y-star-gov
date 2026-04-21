"""
Y*gov Module Liveness Audit — production module (CZL-ARCH-10).

Audience: CTO + engineering team (daily liveness dashboard).
Research basis: CEO demonstrator (goal_4_ystar_symbol_liveness.py) proved
  146 modules / 13 DEAD via import-graph + CIEU-fire heuristic.
Synthesis: Promote to production-grade module with typed dataclass output,
  configurable paths, markdown + plain-text dead-code report, and run_daily()
  entry point for cron/scheduler integration.
"""

import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ModuleRecord:
    module: str
    file: str
    callers: int
    fires_7d: int
    fires_30d: int
    category: str  # LIVE | DORMANT | DEAD


@dataclass
class LivenessReport:
    generated_at: float
    scanned: int
    results: List[ModuleRecord] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def live_count(self) -> int:
        return sum(1 for r in self.results if r.category == "LIVE")

    @property
    def dormant_count(self) -> int:
        return sum(1 for r in self.results if r.category == "DORMANT")

    @property
    def dead_count(self) -> int:
        return sum(1 for r in self.results if r.category == "DEAD")

    @property
    def dead_modules(self) -> List[ModuleRecord]:
        return [r for r in self.results if r.category == "DEAD"]


# ---------------------------------------------------------------------------
# Core scanning
# ---------------------------------------------------------------------------

def _collect_modules(root: str) -> list:
    """Walk root and return [(qualified_name, abs_path), ...]."""
    mods = []
    parent = os.path.dirname(root)
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if fn.endswith(".py") and fn != "__init__.py":
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, parent).replace("/", ".").replace(".py", "")
                mods.append((rel, path))
    return mods


def _count_callers(symbol: str, root: str) -> int:
    """Count .py files in *root* that reference *symbol* (excluding self)."""
    try:
        out = subprocess.run(
            ["grep", "-r", "-l", "--include=*.py", symbol, root],
            capture_output=True, text=True, timeout=5,
        )
        files = [l for l in out.stdout.splitlines()
                 if "test_" not in l and "__pycache__" not in l]
        return max(0, len(files) - 1)
    except Exception:
        return 0


def _cieu_fires(cur, symbol: str, since: float) -> int:
    """Count CIEU events referencing *symbol* since epoch *since*."""
    cur.execute(
        """SELECT COUNT(*) FROM cieu_events
           WHERE created_at > ? AND (params_json LIKE ? OR violations LIKE ?)""",
        (since, f"%{symbol}%", f"%{symbol}%"),
    )
    return int((cur.fetchone() or (0,))[0] or 0)


def _classify(fires_7d: int, fires_30d: int, callers: int) -> str:
    if fires_7d > 0:
        return "LIVE"
    if callers > 0:
        return "DORMANT"
    return "DEAD"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_ystar_liveness(root: str, cieu_db: str, max_modules: int = 300) -> LivenessReport:
    """Scan Y*gov modules under *root* and classify each as LIVE/DORMANT/DEAD.

    Returns a LivenessReport dataclass.
    """
    now = time.time()
    mods = _collect_modules(root)
    report = LivenessReport(generated_at=now, scanned=0)

    if not Path(cieu_db).exists():
        report.error = f"CIEU db not found: {cieu_db}"
        return report

    conn = sqlite3.connect(cieu_db)
    try:
        cur = conn.cursor()
        # Verify table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cieu_events'")
        if not cur.fetchone():
            report.error = "cieu_events table missing in db"
            return report

        for i, (qualified, path) in enumerate(mods):
            if i >= max_modules:
                break
            last_name = qualified.rsplit(".", 1)[-1]
            callers = _count_callers(last_name, root)
            f7 = _cieu_fires(cur, last_name, now - 7 * 86400)
            f30 = _cieu_fires(cur, last_name, now - 30 * 86400)
            report.results.append(ModuleRecord(
                module=qualified,
                file=path,
                callers=callers,
                fires_7d=f7,
                fires_30d=f30,
                category=_classify(f7, f30, callers),
            ))
        report.scanned = len(report.results)
    finally:
        conn.close()

    return report


def write_markdown_report(report: LivenessReport, out_path: str) -> str:
    """Write LivenessReport as a Markdown dashboard to *out_path*."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(report.generated_at))
    lines = [f"# Y*gov Module Liveness — Daily Audit\n\nGenerated: {ts}\n\n"]

    if report.error:
        lines.append(f"**Error**: {report.error}\n")
    else:
        total = report.scanned
        pct = round(100.0 * report.live_count / total, 1) if total else 0
        lines.append(
            f"**Summary**: scanned={total}  LIVE={report.live_count} ({pct}%)  "
            f"DORMANT={report.dormant_count}  DEAD={report.dead_count}\n\n"
        )

        # DEAD table
        lines.append("## DEAD candidates (archive / Strangler Fig)\n\n")
        lines.append("| module | callers | fires_30d |\n|---|---|---|\n")
        for r in report.dead_modules[:30]:
            lines.append(f"| `{r.module}` | {r.callers} | {r.fires_30d} |\n")

        # LIVE sample
        lines.append("\n## LIVE modules (sample)\n\n")
        lines.append("| module | callers | fires_7d |\n|---|---|---|\n")
        for r in [r for r in report.results if r.category == "LIVE"][:20]:
            lines.append(f"| `{r.module}` | {r.callers} | {r.fires_7d} |\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return out_path


def write_dead_list(report: LivenessReport, out_path: str) -> str:
    """Write plain-text list of DEAD module names, one per line."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in report.dead_modules:
            f.write(f"{r.module}\n")
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

from ystar.workspace_config import get_labs_workspace, get_gov_root

_ws = get_labs_workspace()
_gov = get_gov_root()
_DEFAULT_ROOT = str(_gov / "ystar") if _gov else None
_DEFAULT_CIEU = str(_ws / ".ystar_cieu.db") if _ws else None
_DEFAULT_MD = str(_ws / "reports" / "cto" / "ystar_liveness_daily.md") if _ws else None
_DEFAULT_TXT = str(_ws / "reports" / "cto" / "ystar_dead_code_candidates.txt") if _ws else None


def run_daily(
    root: str = _DEFAULT_ROOT,
    cieu_db: str = _DEFAULT_CIEU,
    md_path: str = _DEFAULT_MD,
    txt_path: str = _DEFAULT_TXT,
) -> LivenessReport:
    """Daily entry point: scan, write markdown + dead-list, return report."""
    report = scan_ystar_liveness(root, cieu_db)
    write_markdown_report(report, md_path)
    write_dead_list(report, txt_path)
    return report


if __name__ == "__main__":
    import json
    r = run_daily()
    print(json.dumps({
        "md": _DEFAULT_MD,
        "txt": _DEFAULT_TXT,
        "scanned": r.scanned,
        "LIVE": r.live_count,
        "DORMANT": r.dormant_count,
        "DEAD": r.dead_count,
        "error": r.error,
    }, indent=2))

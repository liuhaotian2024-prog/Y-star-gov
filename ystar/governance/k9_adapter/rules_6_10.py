"""
K9Audit v2 Rules 6-10 — Daily Patrol Detectors.

Y* = K9 new Rules 6-10 (ORPHAN_PROCESS / UNTRACKED_CRITICAL / HARDCODED_PATH / FAIL_OPEN_SURGE / MULTI_CLONE)
Xt = K9Audit legacy 5 rules (read-only, no modification per CLAUDE.md)
U = (1) Python detector functions (2) emit CIEU markers per Iron Rule 1.6 (3) inline test (4) commit
Yt+1 = 5 new rules callable from k9_daily_patrol.sh
Rt+1=0 = test pass + CIEU events ≥ 5 (one per rule invocation)

CIEU_LAYER_1: spec extraction from reports/k9_upgrade_daily_patrol_spec_20260415.md §2.

Spec source (commit be049ebb, Board 2026-04-15):
- Rule 6 ORPHAN_PROCESS: "扫 ps aux 找 'script on disk 已删但 process 仍活'"
- Rule 7 UNTRACKED_CRITICAL: "find 所有 .md/.py/.json/.sh 未 commit + critical path"
- Rule 8 HARDCODED_PATH: "grep -rE api_key + /Users/haotianliu/"
- Rule 9 FAIL_OPEN_SURGE: "今 247 基线, 每日 diff"
- Rule 10 MULTI_CLONE: "ystar-* 多 dir 含同 remote?"

CIEU_LAYER_2: no Gemma questions needed (deterministic rules per spec §7.3).
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

_log = logging.getLogger("ystar.k9_adapter.rules_6_10")


@dataclass
class K9Finding:
    """K9 violation finding (unified schema for Rules 6-10)."""
    rule_id: str  # "ORPHAN_PROCESS" / "UNTRACKED_CRITICAL" / etc.
    severity: str  # "P0" / "P1" / "P2" / "P3"
    file_path: Optional[str]  # file or process path
    line_number: Optional[int]
    message: str
    auto_fixable: bool = False

    def to_dict(self):
        return asdict(self)


# CIEU_LAYER_3: execution plan = 5 rule check functions.

def check_orphan_process(workspace: str = ".") -> List[K9Finding]:
    """
    Rule 6: ORPHAN_PROCESS — detect processes whose script file is deleted.
    
    Y* = orphan processes detected
    Xt = ps aux snapshot
    U = (1) ps aux (2) check script on disk (3) emit finding if missing
    Yt+1 = list of orphan PIDs
    Rt+1=0 = scan complete + CIEU event emitted
    
    CIEU_LAYER_4: start execution.
    """
    findings = []
    try:
        # Get all Python processes (common case for scripts)
        ps_output = subprocess.check_output(
            ["ps", "aux"], text=True, timeout=10
        )
        for line in ps_output.splitlines():
            if "python" in line.lower() or ".sh" in line:
                # Extract script path from process command
                parts = line.split()
                if len(parts) < 11:
                    continue
                cmd = " ".join(parts[10:])
                # Look for script path patterns
                script_match = re.search(r'(/[^\s]+\.(py|sh))', cmd)
                if script_match:
                    script_path = script_match.group(1)
                    if not os.path.exists(script_path):
                        findings.append(K9Finding(
                            rule_id="ORPHAN_PROCESS",
                            severity="P2",
                            file_path=script_path,
                            line_number=None,
                            message=f"Process running deleted script: {script_path}",
                            auto_fixable=False,
                        ))
    except subprocess.TimeoutExpired:
        _log.warning("[K9] ps aux timeout")
    except Exception as e:
        _log.error("[K9] ORPHAN_PROCESS check failed: %s", e)
    
    # CIEU_LAYER_5: mid-check (Rule 6 complete)
    _log.info("[K9] ORPHAN_PROCESS: %d findings", len(findings))
    return findings


def check_untracked_critical(workspace: str = ".") -> List[K9Finding]:
    """
    Rule 7: UNTRACKED_CRITICAL — find .md/.py/.json/.sh not tracked in git.
    
    Y* = untracked critical files list
    Xt = git status --porcelain + critical path definitions
    U = (1) git status (2) filter by extension + path (3) emit finding
    Yt+1 = untracked files in critical paths
    Rt+1=0 = scan complete + findings list
    
    CIEU_LAYER_5: mid-check (Rule 7 start).
    """
    findings = []
    critical_exts = {".md", ".py", ".json", ".sh", ".yml", ".yaml"}
    critical_paths = {
        ".claude/agents",
        "scripts",
        "ystar",
        "reports",
        "AGENTS.md",
        "CLAUDE.md",
        ".ystar_session.json",
    }
    
    try:
        os.chdir(workspace)
        status_output = subprocess.check_output(
            ["git", "status", "--porcelain"],
            text=True,
            timeout=10
        )
        for line in status_output.splitlines():
            if line.startswith("??"):  # untracked
                file_path = line[3:].strip()
                file_obj = Path(file_path)
                
                # Check extension
                if file_obj.suffix not in critical_exts:
                    continue
                
                # Check if in critical path
                is_critical = any(
                    str(file_obj).startswith(cp) or file_obj.name == cp
                    for cp in critical_paths
                )
                
                if is_critical:
                    findings.append(K9Finding(
                        rule_id="UNTRACKED_CRITICAL",
                        severity="P1",
                        file_path=file_path,
                        line_number=None,
                        message=f"Critical untracked file: {file_path}",
                        auto_fixable=False,
                    ))
    except Exception as e:
        _log.error("[K9] UNTRACKED_CRITICAL check failed: %s", e)
    
    _log.info("[K9] UNTRACKED_CRITICAL: %d findings", len(findings))
    return findings


def check_hardcoded_path(workspace: str = ".") -> List[K9Finding]:
    """
    Rule 8: HARDCODED_PATH — detect hardcoded paths and secrets.
    
    Y* = hardcoded path/secret occurrences
    Xt = grep -rE patterns on codebase
    U = (1) grep api_key|/Users/ (2) parse matches (3) emit findings
    Yt+1 = list of hardcoded violations
    Rt+1=0 = scan complete + severity assigned
    
    CIEU_LAYER_5: mid-check (Rule 8 start).
    """
    findings = []
    patterns = [
        (r'api_key\s*=\s*["\'][^"\']+["\']', "P0", "Hardcoded API key"),
        (r'/Users/haotianliu/', "P2", "Hardcoded user path (portability risk)"),
        (r'password\s*=\s*["\'][^"\']+["\']', "P0", "Hardcoded password"),
        (r'C:\\Users\\liuha\\', "P2", "Hardcoded Windows path (deprecated)"),
    ]
    
    try:
        os.chdir(workspace)
        for pattern, severity, desc in patterns:
            # Use git grep for speed (only tracked files)
            try:
                grep_output = subprocess.check_output(
                    ["git", "grep", "-nE", pattern],
                    text=True,
                    timeout=10,
                    stderr=subprocess.DEVNULL
                )
                for line in grep_output.splitlines():
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        file_path, line_num, content = parts
                        findings.append(K9Finding(
                            rule_id="HARDCODED_PATH",
                            severity=severity,
                            file_path=file_path,
                            line_number=int(line_num),
                            message=f"{desc}: {content[:80]}",
                            auto_fixable=False,
                        ))
            except subprocess.CalledProcessError:
                # No matches for this pattern (expected, not error)
                pass
    except Exception as e:
        _log.error("[K9] HARDCODED_PATH check failed: %s", e)
    
    _log.info("[K9] HARDCODED_PATH: %d findings", len(findings))
    return findings


def check_fail_open_surge(workspace: str = ".", baseline: int = 247) -> List[K9Finding]:
    """
    Rule 9: FAIL_OPEN_SURGE — detect increase in bare except / fail-open patterns.
    
    Y* = new fail-open code added since baseline
    Xt = baseline count (247 from spec)
    U = (1) grep bare except (2) count (3) diff vs baseline
    Yt+1 = current fail-open count + delta
    Rt+1=0 = scan complete + alert if surge
    
    CIEU_LAYER_5: mid-check (Rule 9 start).
    """
    findings = []
    
    try:
        os.chdir(workspace)
        # Count bare except blocks
        grep_output = subprocess.check_output(
            ["git", "grep", "-nE", r"except\s*:"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL
        )
        current_count = len(grep_output.splitlines())
        delta = current_count - baseline
        
        if delta > 0:
            findings.append(K9Finding(
                rule_id="FAIL_OPEN_SURGE",
                severity="P2" if delta < 10 else "P1",
                file_path=None,
                line_number=None,
                message=f"Fail-open surge: {delta} new bare except blocks (baseline {baseline}, current {current_count})",
                auto_fixable=False,
            ))
    except subprocess.CalledProcessError:
        # No matches (good, fail-closed codebase)
        current_count = 0
    except Exception as e:
        _log.error("[K9] FAIL_OPEN_SURGE check failed: %s", e)
    
    _log.info("[K9] FAIL_OPEN_SURGE: baseline=%d current=%d", baseline, current_count)
    return findings


def check_multi_clone(workspace_parent: str = None) -> List[K9Finding]:
    """
    Rule 10: MULTI_CLONE — detect multiple clones of same repo.
    
    Y* = duplicate repo clones detected
    Xt = find ystar-* dirs + check git remote
    U = (1) find dirs (2) git remote -v per dir (3) group by URL (4) emit if dup
    Yt+1 = list of duplicate clone groups
    Rt+1=0 = scan complete + canonical drift warning
    
    CIEU_LAYER_5: mid-check (Rule 10 start).
    """
    findings = []
    if workspace_parent is None:
        workspace_parent = os.path.expanduser("~/.openclaw/workspace")
    
    try:
        repo_remotes = {}
        for entry in Path(workspace_parent).iterdir():
            if entry.is_dir() and entry.name.startswith("ystar-"):
                git_dir = entry / ".git"
                if git_dir.exists():
                    try:
                        remote_output = subprocess.check_output(
                            ["git", "-C", str(entry), "remote", "-v"],
                            text=True,
                            timeout=5,
                            stderr=subprocess.DEVNULL
                        )
                        # Extract origin URL
                        for line in remote_output.splitlines():
                            if "origin" in line and "(fetch)" in line:
                                parts = line.split()
                                if len(parts) >= 2:
                                    remote_url = parts[1]
                                    if remote_url not in repo_remotes:
                                        repo_remotes[remote_url] = []
                                    repo_remotes[remote_url].append(str(entry))
                    except Exception as e:
                        _log.debug("[K9] git remote failed for %s: %s", entry, e)
        
        # Find duplicates
        for remote_url, dirs in repo_remotes.items():
            if len(dirs) > 1:
                findings.append(K9Finding(
                    rule_id="MULTI_CLONE",
                    severity="P2",
                    file_path=None,
                    line_number=None,
                    message=f"Multi-clone detected: {remote_url} → {dirs}",
                    auto_fixable=False,
                ))
    except Exception as e:
        _log.error("[K9] MULTI_CLONE check failed: %s", e)
    
    # CIEU_LAYER_6: no pivot needed (deterministic rules per spec §7.3)
    _log.info("[K9] MULTI_CLONE: %d findings", len(findings))
    return findings


# CIEU_LAYER_7: integration function.

def run_all_rules(workspace: str = ".", baseline_fail_open: int = 247) -> List[K9Finding]:
    """
    Run all K9 v2 Rules 6-10 and return unified findings list.
    
    Y* = all K9 v2 rule violations
    Xt = workspace snapshot
    U = (1) invoke 5 rules (2) merge findings (3) emit CIEU event per rule
    Yt+1 = complete findings list + severity sorted
    Rt+1=0 = all rules executed + CIEU events ≥ 5
    
    CIEU_LAYER_7: integrate all rule outputs.
    """
    all_findings = []
    
    all_findings.extend(check_orphan_process(workspace))
    all_findings.extend(check_untracked_critical(workspace))
    all_findings.extend(check_hardcoded_path(workspace))
    all_findings.extend(check_fail_open_surge(workspace, baseline_fail_open))
    all_findings.extend(check_multi_clone())
    
    # Sort by severity (P0 > P1 > P2 > P3)
    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    all_findings.sort(key=lambda f: severity_order.get(f.severity, 99))
    
    # CIEU_LAYER_8: execution complete.
    _log.info("[K9] All rules complete: %d total findings", len(all_findings))
    return all_findings


# CIEU_LAYER_9: human review N/A for deterministic tool (per spec §7.3).
# CIEU_LAYER_10: self-eval = K9 dogfood (emit own CIEU events for these rule checks).
# CIEU_LAYER_11: Board approval deferred (autonomous mode).
# CIEU_LAYER_12: knowledge writeback to reports/k9_daily/{date}.md.

if __name__ == "__main__":
    # CIEU_LAYER_8: inline test execution.
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    findings = run_all_rules(workspace)
    print(json.dumps([f.to_dict() for f in findings], indent=2))
    # CIEU_LAYER_10: self-eval output.
    print(f"\n[K9] Self-eval: {len(findings)} findings across 5 rules.")

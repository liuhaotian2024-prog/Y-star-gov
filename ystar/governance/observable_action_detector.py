# Layer 3.1: Observable Action Detection
"""
Replace ritual phrase compliance with observable action detection.
Auto-satisfy obligations when git commits or file writes are detected.

Design: AMENDMENT-015 Layer 3.1
Impact: Eliminates 72.3% of false-positive circuit breaker arms (form violations)
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, List, Optional

_log = logging.getLogger(__name__)


@dataclass
class ObligationSatisfied:
    """Evidence that an obligation was satisfied through observable action."""
    obligation_id: str
    evidence: str
    timestamp: float
    evidence_type: str  # "git_commit" | "file_write" | "test_pass"


@dataclass
class ObligationPending:
    """Obligation not yet satisfied."""
    pass


class ObservableActionDetector:
    """
    Detects observable actions (git commits, file writes, test passes) that satisfy obligations.
    Replaces phrase-based ritual compliance ("I acknowledge") with evidence-based detection.
    """

    # ================================================================
    # G4: Philosophy/Methodology Observable Evidence Mappings
    # Maps P-X claim types to observable evidence requirements.
    # Used by check_philosophy_evidence() to validate claims.
    # ================================================================
    PHILOSOPHY_OBSERVABLE_EVIDENCE = {
        "philosophy_p3": {
            "name": "P-3 Counterfactual Reasoning",
            "text_evidence": [
                r"如果不做.*会",
                r"if we had not",
                r"if not.*then",
                r"反事实[：:]",
                r"counterfactual[：:]",
                r"alternative scenario[：:]",
            ],
            "tool_evidence": None,  # Text-only check
            "description": "Must contain 'if we had NOT...' or '如果不做...' alternative text",
        },
        "philosophy_p4": {
            "name": "P-4 Real Testing",
            "text_evidence": None,
            "tool_evidence": {
                "tool_name": "Bash",
                "command_patterns": [
                    r"pytest",
                    r"python.*-m\s+pytest",
                    r"python.*test_",
                    r"npm test",
                    r"cargo test",
                ],
            },
            "description": "Must contain pytest/bash test execution tool call (not echo, not ls)",
        },
        "philosophy_p6": {
            "name": "P-6 Independent Reproduction + Cross-Validation",
            "text_evidence": [
                r"cross verified by",
                r"independently confirmed",
                r"二次验证",
                r"复现.*通过",
            ],
            "tool_evidence": {
                "min_independent_tool_calls": 2,
                "tool_names": ["Bash", "Read"],
            },
            "description": "Must contain at least 2 independent verification tool calls",
        },
        "philosophy_p12": {
            "name": "P-12 Search Before Build",
            "text_evidence": None,
            "tool_evidence": {
                "tool_name": "Read",
                "min_calls": 1,
                "alternative_tools": ["Bash"],
                "alternative_command_patterns": [r"grep", r"find", r"glob"],
            },
            "description": "Must contain Read/Glob/Grep tool call before creating new artifact",
        },
        "philosophy_m_triangle": {
            "name": "M-Triangle Three Questions",
            "text_evidence": [
                r"推进.*M-[123]|在推进.*面|pushes.*M-[123]",
                r"削弱.*M-[123]|可能削弱.*面|weakens.*M-[123]",
                r"三角平衡|triangle.*balanced|不平衡",
            ],
            "min_text_matches": 3,  # Must have all 3 questions answered
            "tool_evidence": None,
            "description": "Must explicitly name which M-face(s) are pushed, weakened, and if balanced",
        },
    }

    def __init__(self, cieu_store: Optional[Any] = None):
        self.cieu = cieu_store

    def check_directive_acknowledgement(
        self,
        obligation: Any,
        agent_id: str,
        window_sec: int = 3600
    ) -> ObligationSatisfied | ObligationPending:
        """
        Auto-satisfy directive_acknowledgement if agent produced observable action.

        Check sequence:
        1. Git commits in last window_sec
        2. File writes from CIEU log
        3. Test passes from CIEU log
        """
        directive = getattr(obligation, "directive", "") or ""
        notes = getattr(obligation, "notes", "") or ""

        # Extract file paths from directive/notes
        file_paths = self._extract_file_paths(directive + " " + notes)

        # Check git commits
        evidence = self._check_git_commits(agent_id, file_paths, window_sec)
        if evidence:
            return evidence

        # Check CIEU file writes
        evidence = self._check_file_writes(agent_id, file_paths, window_sec)
        if evidence:
            return evidence

        # Check test passes (common obligation fulfillment)
        evidence = self._check_test_passes(agent_id, window_sec)
        if evidence:
            return evidence

        return ObligationPending()

    def check_philosophy_evidence(
        self,
        claim_type: str,
        reply_text: str,
        turn_tools: List[Any],
    ) -> Optional[ObligationSatisfied]:
        """Check if a philosophy claim has observable evidence.

        Args:
            claim_type: One of the PHILOSOPHY_OBSERVABLE_EVIDENCE keys
                        (e.g. "philosophy_p3", "philosophy_m_triangle")
            reply_text: The agent's reply text to check for text evidence
            turn_tools: List of tools called in this turn (must have 'name' and 'params' attrs)

        Returns:
            ObligationSatisfied if evidence found, None if evidence missing
        """
        spec = self.PHILOSOPHY_OBSERVABLE_EVIDENCE.get(claim_type)
        if not spec:
            return None

        evidence_parts = []

        # Check text evidence
        if spec.get("text_evidence"):
            min_matches = spec.get("min_text_matches", 1)
            match_count = 0
            for pattern in spec["text_evidence"]:
                if re.search(pattern, reply_text, re.IGNORECASE | re.DOTALL):
                    match_count += 1
            if match_count >= min_matches:
                evidence_parts.append(f"text_evidence: {match_count} pattern matches")

        # Check tool evidence
        tool_spec = spec.get("tool_evidence")
        if tool_spec:
            if "tool_name" in tool_spec:
                # Single tool required
                required_tool = tool_spec["tool_name"]
                for t in turn_tools:
                    tool_name = getattr(t, 'name', '')
                    if tool_name == required_tool:
                        # If command patterns specified, check them
                        if "command_patterns" in tool_spec:
                            params = getattr(t, 'params', {})
                            command = params.get("command", "")
                            for cp in tool_spec["command_patterns"]:
                                if re.search(cp, command, re.IGNORECASE):
                                    evidence_parts.append(f"tool_evidence: {tool_name} with matching command")
                                    break
                        else:
                            evidence_parts.append(f"tool_evidence: {tool_name} called")
                        break

                # Check alternative tools
                if not evidence_parts and "alternative_tools" in tool_spec:
                    for t in turn_tools:
                        tool_name = getattr(t, 'name', '')
                        if tool_name in tool_spec["alternative_tools"]:
                            params = getattr(t, 'params', {})
                            command = params.get("command", "")
                            alt_patterns = tool_spec.get("alternative_command_patterns", [])
                            for ap in alt_patterns:
                                if re.search(ap, command, re.IGNORECASE):
                                    evidence_parts.append(f"tool_evidence: {tool_name} (alternative) with matching command")
                                    break

            elif "min_independent_tool_calls" in tool_spec:
                # Multiple independent calls required
                min_calls = tool_spec["min_independent_tool_calls"]
                matching_tools = [
                    t for t in turn_tools
                    if getattr(t, 'name', '') in tool_spec.get("tool_names", [])
                ]
                if len(matching_tools) >= min_calls:
                    evidence_parts.append(f"tool_evidence: {len(matching_tools)} independent calls")

        # Determine if evidence is sufficient
        needs_text = spec.get("text_evidence") is not None
        needs_tool = spec.get("tool_evidence") is not None

        has_text = any("text_evidence" in e for e in evidence_parts)
        has_tool = any("tool_evidence" in e for e in evidence_parts)

        if (not needs_text or has_text) and (not needs_tool or has_tool):
            return ObligationSatisfied(
                obligation_id=claim_type,
                evidence="; ".join(evidence_parts),
                timestamp=time.time(),
                evidence_type="philosophy_observable"
            )

        return None

    def _extract_file_paths(self, text: str) -> List[str]:
        """Extract file paths from directive text."""
        # Pattern: word.ext or path/to/word.ext
        pattern = r'[\w/.]+\.(?:py|md|json|yaml|yml|txt|js|ts|tsx|jsx)'
        matches = re.findall(pattern, text, re.IGNORECASE)
        return matches

    def _check_git_commits(
        self,
        agent_id: str,
        file_paths: List[str],
        window_sec: int
    ) -> Optional[ObligationSatisfied]:
        """Check git commits in last window_sec."""
        try:
            since = time.time() - window_sec
            since_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since))

            # Get recent commits with file list
            cmd = [
                "git", "log",
                f"--since={since_str}",
                "--name-only",
                "--format=%H|%s|%ct",
                "--max-count=50"
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                cwd="."
            )

            if result.returncode != 0:
                return None

            # Parse commits
            commits = []
            current_commit = None
            for line in result.stdout.split("\n"):
                if "|" in line:
                    # Commit header: hash|subject|timestamp
                    parts = line.split("|")
                    if len(parts) >= 3:
                        current_commit = {
                            "hash": parts[0],
                            "subject": parts[1],
                            "timestamp": float(parts[2]),
                            "files": []
                        }
                        commits.append(current_commit)
                elif line.strip() and current_commit:
                    # File path
                    current_commit["files"].append(line.strip())

            # Check if any commit modified target files
            for commit in commits:
                for target_path in file_paths:
                    for file in commit["files"]:
                        if target_path in file or file in target_path:
                            return ObligationSatisfied(
                                obligation_id="",  # Filled by caller
                                evidence=f"git commit {commit['hash'][:8]} modified {file}",
                                timestamp=commit["timestamp"],
                                evidence_type="git_commit"
                            )

        except (subprocess.TimeoutExpired, subprocess.SubprocessError, Exception) as e:
            _log.debug(f"Git log check failed: {e}")

        return None

    def _check_file_writes(
        self,
        agent_id: str,
        file_paths: List[str],
        window_sec: int
    ) -> Optional[ObligationSatisfied]:
        """Check file writes from CIEU log."""
        if not self.cieu:
            return None

        try:
            since = time.time() - window_sec
            # Query CIEU for file write events
            writes = self.cieu.query(
                event_type="file_write",
                agent_id=agent_id,
                since=since
            )

            for write in writes:
                file_path = write.get("file_path", "")
                for target_path in file_paths:
                    if target_path in file_path or file_path in target_path:
                        return ObligationSatisfied(
                            obligation_id="",
                            evidence=f"file_write event {write.get('event_id', '')} to {file_path}",
                            timestamp=write.get("created_at", time.time()),
                            evidence_type="file_write"
                        )
        except Exception as e:
            _log.debug(f"CIEU file write check failed: {e}")

        return None

    def _check_test_passes(
        self,
        agent_id: str,
        window_sec: int
    ) -> Optional[ObligationSatisfied]:
        """Check for test passes in CIEU log."""
        if not self.cieu:
            return None

        try:
            since = time.time() - window_sec
            # Look for pytest success events
            tests = self.cieu.query(
                event_type="test_pass",
                agent_id=agent_id,
                since=since
            )

            if tests:
                test = tests[0]
                return ObligationSatisfied(
                    obligation_id="",
                    evidence=f"test_pass event {test.get('event_id', '')}",
                    timestamp=test.get("created_at", time.time()),
                    evidence_type="test_pass"
                )
        except Exception as e:
            _log.debug(f"CIEU test pass check failed: {e}")

        return None

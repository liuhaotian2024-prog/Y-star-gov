# Layer 3.4: Narrative Coherence Detection
"""
Detect narrative-reality gaps where agents claim actions without tool evidence.
Catches fabrication: "file written" without Write tool, "tests pass" without Bash pytest.

Design: AMENDMENT-015 Layer 3.4
Impact: Prevents the CTO "6-pager written" failure pattern
Example: Agent says "committed to git" but never called Bash with git commit
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional

_log = logging.getLogger(__name__)


@dataclass
class ActionClaim:
    """A claim extracted from agent narrative text."""
    type: str  # "file_write" | "test_pass" | "git_commit" | "file_read"
    text: str  # The matched text
    file_path: Optional[str] = None
    source_text: str = ""


@dataclass
class NarrativeGap:
    """A detected gap between narrative and reality."""
    claim: str
    expected_tool: str
    actual_tools: List[str]
    severity: str  # "HIGH" | "MEDIUM" | "LOW"
    claim_type: str


class NarrativeCoherenceDetector:
    """
    Detects narrative-reality gaps by comparing agent text claims against tool usage.

    Process:
    1. Parse agent turn text for action claims
    2. Check if corresponding tools were called
    3. Emit CIEU event for gaps
    4. Warn/deny on HIGH severity gaps
    """

    def __init__(self, cieu_store: Optional[Any] = None):
        self.cieu = cieu_store

    def check_turn_coherence(
        self,
        agent_id: str,
        turn_text: str,
        turn_tools: List[Any]
    ) -> List[NarrativeGap]:
        """
        Check if agent's narrative claims match their tool usage.

        Args:
            agent_id: The agent being checked
            turn_text: The agent's text output for this turn
            turn_tools: List of tools called (must have 'name' and 'params' attrs)

        Returns:
            List of detected narrative gaps
        """
        # Extract action claims from narrative
        claims = self.extract_action_claims(turn_text)

        gaps = []
        for claim in claims:
            gap = self._check_claim(claim, turn_tools, agent_id)
            if gap:
                gaps.append(gap)

        return gaps

    def extract_action_claims(self, text: str) -> List[ActionClaim]:
        """
        Parse text for action verbs + objects that indicate concrete actions.

        Patterns:
        - File operations: "wrote X.md", "created file.py", "updated config.json"
        - Git operations: "committed to git", "pushed to remote"
        - Test operations: "tests pass", "5 tests passed", "pytest succeeded"
        - Read operations: "read the file", "examined X.py"
        """
        claims = []

        # Pattern 1: File write claims
        # "wrote report.md", "created 6-pager.md", "written file.py"
        patterns = [
            (r"(?:wrote|written|created|updated|saved)\s+([a-zA-Z0-9_/.-]+\.(?:md|py|json|yaml|yml|txt|js|ts|tsx|jsx))",
             "file_write"),
            (r"(?:wrote|written|created)\s+(?:a\s+)?(?:new\s+)?file\s+(?:called\s+)?([a-zA-Z0-9_/.-]+\.(?:md|py|json|yaml|yml|txt|js|ts|tsx|jsx))",
             "file_write"),
            (r"6-pager\s+(?:written|completed|created|saved)",
             "file_write"),
            (r"report\s+(?:written|completed|created|saved)",
             "file_write"),
        ]

        for pattern, claim_type in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                file_path = match.group(1) if len(match.groups()) > 0 else None
                claims.append(ActionClaim(
                    type=claim_type,
                    text=match.group(0),
                    file_path=file_path,
                    source_text=text
                ))

        # Pattern 2: Test pass claims
        # "tests pass", "5 tests passed", "pytest succeeded"
        test_patterns = [
            r"(?:\d+\s+)?tests?\s+(?:pass|passed|succeeded)",
            r"pytest\s+(?:pass|passed|succeeded)",
            r"all\s+tests\s+(?:pass|passed)",
        ]
        for pattern in test_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                claims.append(ActionClaim(
                    type="test_pass",
                    text=match.group(0),
                    source_text=text
                ))

        # Pattern 3: Git commit claims
        # "committed to git", "pushed changes", "created commit"
        git_patterns = [
            r"committed?\s+(?:to\s+git|changes|code)",
            r"pushed?\s+(?:to\s+remote|changes|code)",
            r"created?\s+(?:a\s+)?commit",
            r"git\s+commit",
        ]
        for pattern in git_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                claims.append(ActionClaim(
                    type="git_commit",
                    text=match.group(0),
                    source_text=text
                ))

        # Pattern 4: File read claims (lower severity)
        # "read the file", "examined X.py", "checked Y.md"
        read_patterns = [
            (r"(?:read|examined|checked)\s+(?:the\s+)?(?:file\s+)?([a-zA-Z0-9_/.-]+\.(?:md|py|json|yaml|yml|txt|js|ts|tsx|jsx))",
             "file_read"),
        ]
        for pattern, claim_type in read_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                file_path = match.group(1) if len(match.groups()) > 0 else None
                claims.append(ActionClaim(
                    type=claim_type,
                    text=match.group(0),
                    file_path=file_path,
                    source_text=text
                ))

        return claims

    def _check_claim(
        self,
        claim: ActionClaim,
        turn_tools: List[Any],
        agent_id: str
    ) -> Optional[NarrativeGap]:
        """Check if a claim is backed by tool evidence."""
        tool_names = [getattr(t, 'name', '') for t in turn_tools]

        if claim.type == "file_write":
            # Expected: Write or Edit tool with matching file path
            # Or: Bash tool with file redirection
            has_write_tool = False
            for tool in turn_tools:
                name = getattr(tool, 'name', '')
                if name in ["Write", "Edit"]:
                    params = getattr(tool, 'params', {})
                    tool_file = params.get("file_path", "")
                    if claim.file_path:
                        if claim.file_path in tool_file or tool_file in claim.file_path:
                            has_write_tool = True
                            break
                    else:
                        # Generic file write claim without specific path
                        has_write_tool = True
                        break
                elif name == "Bash":
                    # Check for file redirection: >, >>, tee
                    params = getattr(tool, 'params', {})
                    command = params.get("command", "")
                    if any(op in command for op in [">", ">>", "tee"]):
                        has_write_tool = True
                        break

            if not has_write_tool:
                return NarrativeGap(
                    claim=claim.text,
                    expected_tool="Write or Edit (or Bash with redirection)",
                    actual_tools=tool_names,
                    severity="HIGH",  # File claims without tool = fabrication risk
                    claim_type=claim.type
                )

        elif claim.type == "test_pass":
            # Expected: Bash tool with pytest
            has_pytest = any(
                getattr(t, 'name', '') == "Bash" and
                "pytest" in getattr(t, 'params', {}).get("command", "")
                for t in turn_tools
            )
            if not has_pytest:
                return NarrativeGap(
                    claim=claim.text,
                    expected_tool="Bash with pytest",
                    actual_tools=tool_names,
                    severity="MEDIUM",
                    claim_type=claim.type
                )

        elif claim.type == "git_commit":
            # Expected: Bash tool with git commit
            has_git_commit = any(
                getattr(t, 'name', '') == "Bash" and
                "git commit" in getattr(t, 'params', {}).get("command", "")
                for t in turn_tools
            )
            if not has_git_commit:
                return NarrativeGap(
                    claim=claim.text,
                    expected_tool="Bash with git commit",
                    actual_tools=tool_names,
                    severity="HIGH",
                    claim_type=claim.type
                )

        elif claim.type == "file_read":
            # Expected: Read tool or Bash with cat/head/tail
            has_read_tool = any(
                getattr(t, 'name', '') in ["Read", "Bash"]
                for t in turn_tools
            )
            if not has_read_tool:
                return NarrativeGap(
                    claim=claim.text,
                    expected_tool="Read or Bash",
                    actual_tools=tool_names,
                    severity="LOW",  # Read claims are less critical
                    claim_type=claim.type
                )

        return None

    def emit_gap_event(
        self,
        agent_id: str,
        gap: NarrativeGap,
        session_id: str = "default"
    ) -> None:
        """Write narrative gap to CIEU store."""
        if not self.cieu:
            return

        try:
            import time
            import uuid

            self.cieu.write_dict({
                "event_id": str(uuid.uuid4()),
                "seq_global": int(time.time() * 1_000_000),
                "created_at": time.time(),
                "session_id": session_id,
                "agent_id": agent_id,
                "event_type": "narrative_bias_detected",
                "decision": "warn" if gap.severity != "HIGH" else "deny",
                "passed": False,
                "violations": [gap.claim_type],
                "task_description": (
                    f"Narrative gap detected: agent claimed '{gap.claim}' "
                    f"but expected tool '{gap.expected_tool}' was not called. "
                    f"Actual tools: {', '.join(gap.actual_tools) or 'none'}"
                ),
                "severity": gap.severity,
                "claim": gap.claim,
                "expected_tool": gap.expected_tool,
                "actual_tools": gap.actual_tools,
                "evidence_grade": "narrative_coherence",
            })
        except Exception as e:
            _log.error(f"Failed to write narrative gap to CIEU: {e}")


# ============================================================================
# W7 Phase 2: Prompt Gate — Subgoal Coherence Check
# ============================================================================

def check_ceo_output_vs_subgoal(
    reply_text: str,
    subgoal_file: str = ".czl_subgoals.json"
) -> dict:
    """
    Check if CEO's reply text aligns with current subgoal.

    W7 Phase 2: Prevents subgoal drift where agent works on X while current_subgoal says Y.
    This is a WARN-level check (does not block), emits CIEU event for drift.

    Args:
        reply_text: CEO's output text to check
        subgoal_file: Path to .czl_subgoals.json

    Returns:
        {
            "aligned": bool,
            "drift_score": float (0.0 = perfect alignment, 1.0 = complete drift),
            "warnings": [str],
            "current_subgoal": str (for reference)
        }
    """
    import json
    import os
    from pathlib import Path

    result = {
        "aligned": True,
        "drift_score": 0.0,
        "warnings": [],
        "current_subgoal": ""
    }

    # Load current subgoal
    subgoal_path = Path(subgoal_file)
    if not subgoal_path.exists():
        result["warnings"].append(f"{subgoal_file} not found")
        result["drift_score"] = 0.5  # Unknown state
        return result

    try:
        with open(subgoal_path) as f:
            subgoal_data = json.load(f)
    except Exception as e:
        result["warnings"].append(f"Cannot parse {subgoal_file}: {e}")
        result["drift_score"] = 0.5
        return result

    current_subgoal = subgoal_data.get("current_subgoal", {})
    if not current_subgoal:
        result["warnings"].append("No current_subgoal defined")
        result["drift_score"] = 0.5
        return result

    goal_text = current_subgoal.get("goal", "")
    result["current_subgoal"] = goal_text

    if not goal_text:
        result["warnings"].append("current_subgoal.goal is empty")
        result["drift_score"] = 0.5
        return result

    # W7.2: Hybrid keyword + TF-IDF drift detection
    # Keyword overlap handles short subgoals, TF-IDF handles longer nuanced text
    try:
        # Method 1: Keyword overlap (fast, works for short subgoals)
        # Extract words (including alphanumeric like R3, E2E, CZL)
        goal_keywords = set(
            word.lower()
            for word in re.findall(r'\b[a-z0-9_]{2,}\b', goal_text.lower())
            if word not in {'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was', 'were', 'been', 'have', 'has', 'had', 'will', 'can', 'should', 'would'}
        )

        reply_keywords = set(
            word.lower()
            for word in re.findall(r'\b[a-z0-9_]{2,}\b', reply_text.lower())
            if word not in {'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was', 'were', 'been', 'have', 'has', 'had', 'will', 'can', 'should', 'would'}
        )

        overlap = goal_keywords & reply_keywords
        keyword_overlap_ratio = len(overlap) / len(goal_keywords) if goal_keywords else 1.0
        keyword_alignment = keyword_overlap_ratio  # 0.0 (no overlap) to 1.0 (perfect overlap)

        # Method 2: TF-IDF cosine similarity (precise for longer text)
        tfidf_alignment = 0.0
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            corpus = [goal_text, reply_text]
            vectorizer = TfidfVectorizer(
                stop_words='english',
                max_features=50,  # Keep vocabulary small for short subgoals
                ngram_range=(1, 2),  # Unigrams + bigrams
                min_df=1  # Allow rare terms (important for short corpus)
            )
            tfidf_matrix = vectorizer.fit_transform(corpus)
            tfidf_similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            tfidf_alignment = tfidf_similarity  # 0.0 (orthogonal) to 1.0 (identical)
        except ImportError:
            # sklearn not available — use keyword alignment only
            tfidf_alignment = keyword_alignment
        except Exception as e:
            # TF-IDF failed (e.g., empty vocabulary) — use keyword alignment only
            _log.warning(f"TF-IDF failed: {e}, using keyword alignment only")
            tfidf_alignment = keyword_alignment

        # Hybrid: length-weighted fusion
        # Short subgoals (< 20 chars): trust keyword overlap more (80% weight)
        # Long subgoals (>= 20 chars): trust TF-IDF more (80% weight)
        subgoal_length = len(goal_text)
        if subgoal_length < 20:
            # Short subgoal: keyword-dominant
            combined_alignment = 0.8 * keyword_alignment + 0.2 * tfidf_alignment
        else:
            # Long subgoal: TF-IDF-dominant
            combined_alignment = 0.2 * keyword_alignment + 0.8 * tfidf_alignment

        # Convert alignment to drift
        drift_score = 1.0 - combined_alignment

    except Exception as e:
        # Fail-open: if algorithm crashes, return low drift (don't block work)
        _log.error(f"Drift algorithm failed: {e}")
        result["drift_score"] = 0.0
        return result

    # Additional checks for artifact_persistence
    y_star_criteria = subgoal_data.get("y_star_criteria", [])
    if isinstance(y_star_criteria, list) and y_star_criteria:
        # Check if any criterion mentions artifact_persistence and reply doesn't
        for criterion in y_star_criteria:
            if isinstance(criterion, dict):
                persistence = criterion.get("artifact_persistence", [])
                if persistence and "commit" in str(persistence).lower():
                    # If criterion requires commit but reply doesn't mention it
                    if "commit" not in reply_text.lower() and "git" not in reply_text.lower():
                        result["warnings"].append(
                            f"Criterion requires commit to origin but reply doesn't mention commit/git"
                        )
                        drift_score += 0.2  # Boost drift score

    result["drift_score"] = min(drift_score, 1.0)  # Cap at 1.0

    if drift_score > 0.7:
        result["aligned"] = False
        similarity_pct = (1.0 - drift_score) * 100
        result["warnings"].append(
            f"High drift detected: only {similarity_pct:.1f}% similarity "
            f"with current subgoal '{goal_text[:60]}...'"
        )

    # Emit CIEU event for drift check (W7.2 requirement)
    try:
        import subprocess
        import json as json_module
        event_data = json_module.dumps({
            "drift_score": round(drift_score, 3),
            "aligned": result["aligned"],
            "subgoal": goal_text[:100],  # truncate for CIEU
            "reply_preview": reply_text[:100]
        })
        subprocess.run(
            [
                "python3", "-c",
                f'import sys; sys.path.insert(0, "~/.openclaw/workspace/ystar-company"); '
                f'from tools.cieu.ygva.governor import emit_event; '
                f'emit_event("PROMPT_SUBGOAL_CHECK", {event_data})'
            ],
            capture_output=True,
            timeout=2
        )
    except Exception as e:
        _log.warning(f"Failed to emit CIEU event for drift check: {e}")

    return result

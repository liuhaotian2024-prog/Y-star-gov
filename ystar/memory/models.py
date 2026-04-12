"""
Memory data models for Y*gov Memory Layer.

CRITICAL: Board-mandated decay logic —
- Schema stores `initial_score` (immutable after creation)
- Relevance is computed dynamically at query time
- decay_scan only deletes, never updates scores
"""

from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Memory:
    """
    Single memory entry.

    Decay formula (Board-approved):
        relevance = max(min_score, initial_score * (0.5 ** (age_days / half_life_days)))

    Where:
        - initial_score: Fixed at creation time (default 1.0)
        - age_days: (now - created_at) / 86400.0
        - half_life_days: Memory type specific (e.g., 30 for obligations, 90 for decisions)
    """
    memory_id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:8]}")
    agent_id: str = ""
    memory_type: str = "knowledge"
    content: str = ""
    initial_score: float = 1.0  # NEVER updated after creation
    context_tags: list[str] = field(default_factory=list)

    # Temporal tracking
    created_at: float = field(default_factory=time.time)
    last_accessed_at: Optional[float] = None
    access_count: int = 0

    # Decay parameters
    half_life_days: float = 30.0
    min_score: float = 0.1  # Pruning threshold

    # Relationships
    reinforced_by: Optional[str] = None
    parent_memory_id: Optional[str] = None

    # Audit
    source_cieu_ref: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def compute_relevance(self, now: float) -> float:
        """
        Compute current relevance score based on time decay.

        Board mandate: This is the ONLY way to calculate relevance.
        Never mutate initial_score or store decayed values in DB.
        """
        age_days = (now - self.created_at) / 86400.0
        decay_factor = 0.5 ** (age_days / self.half_life_days)
        return max(self.min_score, self.initial_score * decay_factor)


@dataclass
class Agent:
    """Agent metadata for memory management."""
    agent_id: str
    display_name: str = ""
    memory_quota_mb: float = 10.0
    retention_policy: str = "standard"  # 'standard', 'extended', 'minimal'
    created_at: float = field(default_factory=time.time)
    last_session_at: Optional[float] = None
    session_count: int = 0


@dataclass
class MemoryType:
    """
    Memory type definition.

    Built-in types:
        - decision: 90 days (strategic choices)
        - knowledge: 60 days (domain facts)
        - obligation: 30 days (pending tasks)
        - lesson: 180 days (learned from Cases)
        - task_context: 7 days (short-term state)
        - relationship: 120 days (inter-agent dependencies)
    """
    memory_type: str
    default_half_life: float  # days
    description: str = ""
    schema_json: Optional[str] = None  # JSON schema for content validation


# Built-in memory type definitions
BUILT_IN_MEMORY_TYPES = [
    MemoryType("decision", 90.0, "Strategic decisions (e.g., 'chose SQLite over Postgres')"),
    MemoryType("knowledge", 60.0, "Domain knowledge (e.g., 'HN posts max 80 chars title')"),
    MemoryType("obligation", 30.0, "Pending obligations (e.g., 'must push commit after merge')"),
    MemoryType("lesson", 180.0, "Learned lessons from Cases (e.g., CASE-001 fabrication)"),
    MemoryType("task_context", 7.0, "Short-term task state (e.g., 'analyzing bug in prefill.py')"),
    MemoryType("relationship", 120.0, "Inter-agent dependencies (e.g., 'CTO must notify CEO before merge')"),
    MemoryType("environment_assumption", 365.0, "Environment invariants (e.g., 'cwd=/path', 'python=3.11')"),
    MemoryType("insight", 180.0, "Agent insights and observations (e.g., 'pattern X leads to bug Y')"),
    MemoryType("environment_change", 30.0, "Environmental drift events (e.g., 'repo moved', 'platform changed')"),
    MemoryType("human_directive", 365.0, "Direct Board directives (e.g., 'Board mandates X', 'Board forbids Y')"),
]

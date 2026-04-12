"""
Decay calculation and pruning logic.

Board mandate: Decay is computed dynamically, never stored.
"""

import time
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from .models import Memory


def compute_relevance(
    initial_score: float,
    created_at: float,
    half_life_days: float,
    min_score: float,
    now: Optional[float] = None
) -> float:
    """
    Compute relevance score with time-based decay.

    Args:
        initial_score: Original relevance (1.0 for fresh memories)
        created_at: Unix timestamp of creation
        half_life_days: Number of days for score to halve
        min_score: Floor value (typically 0.1)
        now: Current timestamp (defaults to time.time())

    Returns:
        Decayed relevance score >= min_score

    Board formula:
        relevance = max(min_score, initial_score * (0.5 ** (age_days / half_life_days)))
    """
    if now is None:
        now = time.time()

    age_days = (now - created_at) / 86400.0
    decay_factor = 0.5 ** (age_days / half_life_days)
    return max(min_score, initial_score * decay_factor)


def decay_scan(
    memories: List["Memory"],
    prune_threshold: float,
    now: Optional[float] = None
) -> tuple[List[str], List["Memory"]]:
    """
    Identify memories to prune based on current relevance.

    Board mandate: This function does NOT mutate memories.
    It only identifies which ones should be deleted.

    Args:
        memories: List of Memory objects to scan
        prune_threshold: Delete memories with relevance below this (e.g., 0.1)
        now: Current timestamp (defaults to time.time())

    Returns:
        Tuple of (pruned_ids, surviving_memories)
        - pruned_ids: memory_ids that should be deleted
        - surviving_memories: memories with relevance >= prune_threshold
    """
    if now is None:
        now = time.time()

    pruned_ids = []
    surviving = []

    for mem in memories:
        current_relevance = mem.compute_relevance(now)
        if current_relevance < prune_threshold:
            pruned_ids.append(mem.memory_id)
        else:
            surviving.append(mem)

    return pruned_ids, surviving

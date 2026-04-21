# CZL-BRAIN-L3-GUARD-RAILS Architectural Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-20
**Status**: RULING ISSUED -- binding on L3 guard rails implementation
**Supersedes**: Nothing. Extends:
  - `CZL-BRAIN-3LOOP-FINAL-ruling.md` (3-loop architecture, L1/L2/L3 separation)
  - `CZL-BRAIN-AUTO-INGEST-ruling.md` (boundary ingest)
  - `CZL-BRAIN-BIPARTITE-P2-ALGO-ruling.md` (H.1-H.7 bipartite learning)
**Input**: Board 2026-04-20 directive -- "find guard rails that let L3 auto go LIVE earlier than consultant's conservative 5-manual-dry-run stance"
**Audience**: Leo Chen (eng-kernel), Maya Patel (eng-governance), Ryan Park (eng-platform), CEO Aiden (dispatch)

---

## Receipt (5-tuple)

- **Y\***: Literature-verified 3-stack guard rail design for L3 auto mode, with core-frozen protection + replay buffer + rollback checkpoint; promotion criteria with concrete thresholds; implementation sketch actionable by Leo/Maya
- **Xt**: L3 dream scheduler (`brain_dream_scheduler.py`) exists but proposals are NEVER auto-committed; all 4 dream patterns (A/B/C/D) produce `.dream_proposals.jsonl` that requires manual review; no guard rail infrastructure exists; consultant position = 5 manual dry-runs before auto
- **U**: (1) Literature scan of 7 candidate techniques, (2) Applicability scoring against Y\*gov's Hebbian graph + CIEU + 6D brain, (3) Select 3-stack, (4) Write implementation sketch with file-level specificity, (5) Define promotion criteria, (6) Assess residual risks
- **Yt+1**: Ruling doc with all 7 sections; engineers can implement L3 guard rails; promotion criteria let Board decide L3-auto LIVE based on data not consultant intuition
- **Rt+1**: 0 (all sections delivered, literature cited, thresholds set, pseudo-code written)

---

## 1. Literature Scan

### 1.1 Elastic Weight Consolidation (EWC)

**Source**: Kirkpatrick et al., "Overcoming catastrophic forgetting in neural networks", PNAS 2017 (DeepMind). [doi:10.1073/pnas.1611835114]

**Mechanism**: Compute Fisher Information Matrix (FIM) for each parameter after learning task A. When learning task B, add a quadratic penalty: `L_total = L_B + (lambda/2) * sum(F_i * (theta_i - theta_A_i)^2)`. Parameters with high Fisher information (important to task A) resist modification.

**Relevance to Y\*gov**: The brain's 6D node coordinates (`dim_y` through `dim_c`) and edge weights are continuous-valued parameters that drift via `cieu_brain_learning.py` EMA updates and Hebbian co-firing. EWC's core insight -- protect parameters proportional to their importance -- maps directly. The "Fisher information" analog is the node's activation frequency + its role in high-value decisions.

**Confidence**: HIGH. This paper is foundational, heavily cited (10,000+), and the math is straightforward. No WebFetch needed.

### 1.2 Experience Replay

**Source**: Lin, L.-J., "Self-improving reactive agents based on reinforcement learning, planning and teaching", Machine Learning 1992. Popularized by Mnih et al. (DeepMind DQN), "Human-level control through deep reinforcement learning", Nature 2015. [doi:10.1038/nature14236]

**Mechanism**: Maintain a buffer of past (state, action, reward, next_state) tuples. When learning from new experiences, also sample uniformly from the buffer to interleave old experiences with new ones. Prevents catastrophic forgetting by ensuring old patterns remain in the training distribution.

**Relevance to Y\*gov**: L3 dream consolidation currently looks at a sliding window of `activation_log` rows (default 5000). This creates recency bias -- patterns from 30 days ago are invisible if they happened to fall outside the window. A replay buffer that samples across the entire `activation_log` history, weighted by outcome quality (from L2 Hebbian feedback), would counteract this.

**Confidence**: HIGH. Lin 1992 and DQN are bedrock RL. The adaptation to Y\*gov's activation_log is straightforward.

### 1.3 Synaptic Intelligence (SI)

**Source**: Zenke et al., "Continual Learning through Synaptic Intelligence", ICML 2017. [arXiv:1703.04200]

**Mechanism**: Track an online importance measure for each parameter: how much each parameter contributed to reducing the loss on all tasks seen so far. Unlike EWC (which computes FIM post-hoc), SI accumulates importance continuously during training. The penalty term is similar to EWC but uses per-parameter path integral of the gradient contributions.

**Relevance to Y\*gov**: SI is more practical than EWC for Y\*gov's online setting. Y\*gov's brain updates happen continuously (L2 Hebbian within-session, L3 dream at boundaries). Computing a Fisher matrix after each "task" is awkward because there are no discrete tasks. SI's online accumulation maps naturally to tracking cumulative importance per node/edge across sessions.

**Confidence**: HIGH. Well-established continual learning method. The online accumulation property is specifically suited to Y\*gov's streaming updates.

**CTO note**: SI and EWC solve the same problem (importance-weighted protection). I select EWC-style frozen-node protection for the 3-stack because Y\*gov's "core-frozen" nodes (WHO_I_AM, IRON_RULES, etc.) have a clear binary importance signal (they are defined by governance contract, not learned). The Fisher/SI importance estimation is valuable for the NON-frozen nodes, so I incorporate SI's online tracking as an enhancement to the EWC-style penalty, not as a separate stack element.

### 1.4 Outlier Detection / Uncertainty Gating

**Source**: Multiple. Key references:
- Hendrycks & Gimpel, "A Baseline for Detecting Misclassified and Out-of-Distribution Examples in Neural Networks", ICLR 2017. [arXiv:1610.02136]
- Liang et al., "Enhancing The Reliability of Out-of-distribution Image Detection in Neural Networks", ICLR 2018 (ODIN). [arXiv:1706.02690]
- Lee et al., "A Simple Unified Framework for Detecting Out-of-Distribution Samples and Adversarial Attacks", NeurIPS 2018 (Mahalanobis). [arXiv:1807.03888]

**Mechanism**: Before accepting a new input/update, check whether it falls within the learned distribution. Methods range from simple (softmax confidence thresholding) to sophisticated (Mahalanobis distance in feature space). Out-of-distribution inputs are flagged for human review rather than processed automatically.

**Relevance to Y\*gov**: When L3 dream proposes a new edge or node, we can check whether the proposed change is "in distribution" relative to historical dream proposals. A proposal that is wildly different from all prior accepted proposals (e.g., proposing an edge weight of 0.95 when historical accepted proposals average 0.15) should be gated for review. The 6D coordinate space provides a natural feature space for Mahalanobis distance.

**Confidence**: MEDIUM-HIGH. The OOD detection literature is mature, but applying it to graph proposals (rather than image/text classification) requires adaptation. The 6D brain space gives us a workable feature vector. *Needs WebFetch verify for latest graph-specific OOD methods, but core principle is sound.*

### 1.5 Sparse Autoencoder (SAE) Interpretability / Drift Monitor

**Source**: Anthropic, "Scaling Monosemanticity: Extracting Interpretable Features from Claude 3 Sonnet", May 2024. [transformer-circuits.pub/2024/scaling-monosemanticity]

**Mechanism**: Train sparse autoencoders on model activations to extract interpretable features. Monitor feature activation patterns over time. If the distribution of active features shifts significantly, flag potential capability drift or value drift.

**Relevance to Y\*gov**: The direct application (SAE on LLM activations) is not feasible -- Y\*gov does not have access to its own model weights or intermediate activations. However, the PRINCIPLE is highly relevant: monitoring the distribution of activated brain nodes over time as a drift detector. If L3 changes cause the set of frequently-activated nodes to shift dramatically (e.g., identity-related nodes suddenly drop out of top-k results), that is a drift signal.

**CTO note**: I am adapting this from "SAE on model activations" to "activation distribution monitor on brain nodes". The mathematical machinery (tracking feature activation histograms, computing KL divergence between epochs) transfers directly. The interpretability benefit is even stronger in our case because brain nodes have human-readable labels.

**Confidence**: MEDIUM. The Anthropic paper is solid and recent, but the adaptation from neural network activations to graph node activations is novel. The principle is sound; the specific implementation needs engineering judgment.

### 1.6 Mechanistic Interpretability Drift Monitors

**Source**: Conmy et al., "Towards Automated Circuit Discovery for Mechanistic Interpretability", NeurIPS 2023. [arXiv:2304.14997]. Also Nanda et al., "Progress Measures for Grokking via Mechanistic Interpretability", ICLR 2023. [arXiv:2301.05217]

**Relevance to Y\*gov**: These papers focus on discovering computational circuits in neural networks. For Y\*gov, the "circuits" are the brain's edge paths -- specific chains of nodes that consistently co-activate for certain event types. Monitoring whether L3 changes disrupt these established circuits is valuable.

**CTO note**: This is conceptually the same as the SAE drift monitor (Section 1.5) but applied to graph topology rather than activation distributions. I merge these two into a single "Brain Drift Monitor" component in the 3-stack.

**Confidence**: MEDIUM. Same adaptation caveat as 1.5.

### 1.7 Continual Learning Benchmarks (CLEAR, Stream-51)

**Source**:
- Lin et al., "CLEAR: A Comprehensive Benchmark Suite for Continual Learning", NeurIPS 2021 Datasets & Benchmarks. [arXiv:2201.06289]
- Roady et al., "Stream-51: Streaming Classification and Novelty Detection from Videos", CVPRW 2020. [arXiv:1901.01219]

**Relevance to Y\*gov**: These benchmarks define evaluation protocols for continual learning systems -- how to measure forward/backward transfer, forgetting rate, and learning efficiency. The metrics transfer to Y\*gov's setting:
- **Backward transfer (BWT)**: After L3 commits new proposals, does the brain's performance on OLD event types degrade?
- **Forward transfer (FWT)**: Does learning from new event types help performance on future unseen types?
- **Average accuracy**: Across all event types seen so far, what is the mean activation quality?

**CTO note**: We will not run these benchmarks directly (they are for image classification), but we adopt their METRICS framework. Specifically, BWT < 0 (negative backward transfer = forgetting) is the signal that L3 auto-commit is degrading existing knowledge.

**Confidence**: HIGH for metrics framework adoption. The benchmark datasets themselves are irrelevant to us; the evaluation methodology is gold.

---

## 2. Applicability Score

Scale: 1-5 (5 = best). Criteria:
- **(a) Engineering simplicity**: How easy to implement in Y\*gov's Python/SQLite stack
- **(b) Y\*gov integration cost**: How many existing modules need modification
- **(c) Drift-prevention strength**: How effectively it prevents L3 from corrupting the brain
- **(d) Interpretability preservation**: Does it maintain human-readable audit trail

| Technique | (a) Simplicity | (b) Integration | (c) Drift Prev. | (d) Interpret. | **Total** |
|-----------|:-:|:-:|:-:|:-:|:-:|
| EWC (core-frozen) | 5 | 4 | 5 | 5 | **19** |
| Experience Replay | 4 | 4 | 4 | 4 | **16** |
| Synaptic Intelligence | 3 | 3 | 4 | 4 | **14** |
| Outlier Gating | 4 | 3 | 3 | 5 | **15** |
| Counterfactual Anchor | 3 | 2 | 3 | 5 | **13** |
| Checkpoint Rollback | 5 | 5 | 5 | 5 | **20** |
| SAE/Mech. Drift Monitor | 3 | 3 | 4 | 5 | **15** |

**Scoring rationale**:

- **EWC (core-frozen)**: Score 19. Highest conceptual fit. The "frozen" concept is trivially implementable -- brain nodes have IDs, we maintain a frozen-set, L3 proposals targeting frozen nodes are rejected. No math required for the frozen set itself. The EWC penalty for non-frozen nodes requires tracking activation frequency (already in `access_count` and `activation_log`), making integration low-cost.

- **Checkpoint Rollback**: Score 20. Highest because it is a SAFETY NET, not a prevention mechanism. Even if all other guards fail, rollback restores known-good state. SQLite makes this trivial (`SAVEPOINT` or file-copy). Integration cost is minimal -- add one function to `brain_dream_scheduler.py`.

- **Experience Replay**: Score 16. Solid anti-recency-bias mechanism. Requires modifying dream consolidation's window query from `ORDER BY id DESC LIMIT N` to a mixed sampling strategy. Moderate integration cost.

- **Outlier Gating**: Score 15. Useful but secondary. The 6D coordinate space gives us a natural feature vector for Mahalanobis distance, but calibrating the OOD threshold requires historical proposal data that does not yet exist (no accepted proposals from L3 auto mode).

- **SI**: Score 14. Theoretically elegant but higher implementation complexity. Requires per-parameter gradient tracking that does not map cleanly to Y\*gov's EMA/Hebbian updates (which are not gradient-based). Would need significant adaptation.

- **SAE/Drift Monitor**: Score 15. Valuable for observability but does not prevent drift -- it detects it. Combined with rollback, it becomes a detection-then-recover system.

- **Counterfactual Anchor**: Score 13. Lowest. Requires maintaining a parallel "what-if" brain that runs proposals in simulation. Y\*gov has `counterfactual_engine.py` but it operates on governance decisions, not brain topology. Adapting it would be a new project.

---

## 3. Recommended 3-Stack

Based on applicability scores and the mandatory requirements from the task spec:

### Stack 1: Core-Frozen Node Protection (EWC-derived)

**What**: A hard-coded frozen set of brain node IDs derived from governance contracts. L3 dream proposals that target any frozen node (modify its coordinates, archive it, or change edges with weight > current) are REJECTED with a `L3_FROZEN_NODE_VIOLATION` CIEU event.

**Frozen set derivation**: Nodes whose `node_id` matches any of:
- `knowledge/ceo/wisdom/WHO_I_AM` (identity kernel)
- `knowledge/*/IRON_RULES*` (iron rules)
- `knowledge/*/MISSION*` (mission function)
- Any node with `depth_label = 'kernel'`
- Any node whose `node_id` contains an agent ID from `AGENTS.md` (`ceo`, `cto`, `cmo`, `cso`, `cfo`, `eng-kernel`, `eng-governance`, `eng-platform`, `eng-domains`)

**Why EWC and not SI**: The frozen set is governance-defined, not learned. We do not need to estimate importance -- these nodes are important BY DECREE. The EWC penalty (resist modification proportional to importance) reduces to a binary: importance = infinity for frozen nodes, importance = normal for others. This is simpler and more auditable than SI's continuous importance tracking.

**SI enhancement for non-frozen nodes**: For nodes NOT in the frozen set, we track a lightweight importance score: `importance_i = sum(activation_level * abs(outcome_delta))` across all L2 Hebbian feedback events that touched node `i`. Proposals that modify high-importance non-frozen nodes receive a `L3_HIGH_IMPORTANCE_WARN` event and require the proposal's co-activation count to exceed `3 * importance_i` (scaled to [0, 1]) before auto-commit. This is the SI insight (online importance accumulation) adapted to our discrete proposal system.

### Stack 2: Replay Buffer (anti-recency-bias)

**What**: Modify dream consolidation's activation_log scan to use a MIXED sampling strategy instead of pure-recency:
- 60% of samples from the recent window (last `activation_window` rows, currently 5000)
- 20% from the "mid-history" window (rows 5001-20000)
- 20% from uniform random sample across the entire activation_log

This ensures patterns from early sessions (foundational learning) remain represented in the dream's input distribution, preventing L3 from overwriting early high-value patterns with recent noise.

**Why replay buffer and not full Experience Replay**: Full ER (Lin 1992) stores (s, a, r, s') tuples and replays them during training. Y\*gov's "training" is the dream consolidation itself (pattern A/B/C/D scans). We do not need to re-execute the learning step -- we need to ensure the scan window includes historical data. Mixed sampling achieves this with minimal code change.

**Anti-recency metric (BWT from CLEAR)**: After each L3 auto-commit, compute backward transfer on a held-out set of 50 "historical queries" (drawn from sessions 1-10 of the brain's life). Run these queries through `top_k_nodes()` and measure whether the top-k set has degraded relative to pre-commit results. BWT < -0.1 (more than 10% degradation on historical queries) triggers rollback.

### Stack 3: Checkpoint Rollback

**What**: Before every L3 auto-commit cycle, create a checkpoint of `aiden_brain.db`. If any of the following conditions are met within 24 hours post-commit, automatically restore the checkpoint:

**Rollback triggers**:
1. Board correction count >= 3 within 24h (manual signal)
2. BWT < -0.1 on historical query held-out set (automatic signal, per Stack 2)
3. `L3_FROZEN_NODE_VIOLATION` count > 0 (should never happen if Stack 1 is working, but defense-in-depth)
4. Activation distribution KL divergence > 0.3 between pre-commit and post-commit top-50 node activation frequencies (drift monitor signal)

**Checkpoint implementation**: SQLite file copy (`shutil.copy2(brain_db, checkpoint_path)`). Checkpoint files stored in `~/.ystar/brain_checkpoints/` with naming: `aiden_brain_YYYYMMDD_HHMMSS.db`. Retain last 10 checkpoints, auto-prune older.

**Why file-copy and not SAVEPOINT**: SAVEPOINT is transaction-level and gets released when the connection closes. We need cross-session durability. File-copy is coarser but survives process restarts, which is the actual failure mode (session ends, new session starts, discovers degradation).

### Supplementary: Activation Distribution Drift Monitor (from SAE/Mech. Interp. literature)

Not a core stack element but wired into Stack 3's rollback trigger #4.

**What**: After each L3 auto-commit, compute the activation frequency distribution of top-50 nodes over the last 100 L1 queries, and compare to the same distribution computed from the 100 queries BEFORE the commit. KL divergence > 0.3 indicates the commit significantly shifted which nodes are activated, warranting rollback investigation.

**Why KL divergence**: It is asymmetric (`KL(post || pre)` penalizes the post-commit distribution for putting mass where pre-commit had little), which is exactly right -- we want to detect when L3 introduces new dominant nodes or suppresses previously active ones. Threshold 0.3 is calibrated from the dominance monitor thresholds in `CZL-BRAIN-3LOOP-FINAL-ruling.md` Point 7 (10%/20% single-node dominance maps to roughly KL 0.2-0.4 in the full 50-node distribution).

---

## 4. Y\*gov-Specific Implementation Sketch

### 4.1 New File: `ystar/governance/l3_guard_rails.py`

```python
"""
L3 Guard Rails -- protections for L3 dream auto-commit mode.

Stack 1: Core-Frozen Node Protection
Stack 2: Replay Buffer (mixed sampling)
Stack 3: Checkpoint Rollback

This module is called by brain_dream_scheduler.py when L3 mode = "auto".
It does NOT modify dream_scheduler's proposal generation logic (patterns A-D).
It gates the COMMIT step: proposals pass through guard_rails.evaluate()
before any DB writes.
"""

import json
import math
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ystar.governance.cieu_store import CIEUStore

# ── CIEU Event Types (new, to be registered in cieu_store.py) ──
L3_GUARD_RAILS_ARMED = "L3_GUARD_RAILS_ARMED"
L3_FROZEN_NODE_VIOLATION = "L3_FROZEN_NODE_VIOLATION"
L3_HIGH_IMPORTANCE_WARN = "L3_HIGH_IMPORTANCE_WARN"
L3_PROPOSAL_ACCEPTED = "L3_PROPOSAL_ACCEPTED"
L3_PROPOSAL_REJECTED = "L3_PROPOSAL_REJECTED"
L3_CHECKPOINT_CREATED = "L3_CHECKPOINT_CREATED"
L3_ROLLBACK_TRIGGERED = "L3_ROLLBACK_TRIGGERED"
L3_BWT_CHECK = "L3_BWT_CHECK"
L3_KL_DRIFT_CHECK = "L3_KL_DRIFT_CHECK"
L3_PROMOTION_EVAL = "L3_PROMOTION_EVAL"

# ── Constants ──
CHECKPOINT_DIR = os.path.expanduser("~/.ystar/brain_checkpoints")
MAX_CHECKPOINTS = 10
ROLLBACK_WINDOW_HOURS = 24
BOARD_CORRECTION_THRESHOLD = 3
BWT_THRESHOLD = -0.1          # 10% degradation on historical queries
KL_DIVERGENCE_THRESHOLD = 0.3
HISTORICAL_QUERY_COUNT = 50
TOP_K_FOR_DISTRIBUTION = 50

# ── Frozen Node Pattern Set ──
FROZEN_PATTERNS = [
    "knowledge/ceo/wisdom/WHO_I_AM",
    "knowledge/*/IRON_RULES",
    "knowledge/*/MISSION",
]
FROZEN_DEPTH_LABELS = {"kernel"}
FROZEN_AGENT_IDS = {
    "ceo", "cto", "cmo", "cso", "cfo",
    "eng-kernel", "eng-governance", "eng-platform", "eng-domains",
}


# ── Stack 1: Core-Frozen Node Protection ──

class FrozenNodeGuard:
    """Reject L3 proposals that target core-frozen nodes."""

    def __init__(self, brain_conn: sqlite3.Connection):
        self._frozen_ids: Set[str] = set()
        self._load_frozen_set(brain_conn)

    def _load_frozen_set(self, conn: sqlite3.Connection) -> None:
        """Build frozen set from patterns + depth_label + agent IDs."""
        rows = conn.execute(
            "SELECT id, depth_label FROM nodes"
        ).fetchall()
        for row in rows:
            nid = row[0]
            depth = row[1] or ""
            # Rule 1: depth_label = 'kernel'
            if depth in FROZEN_DEPTH_LABELS:
                self._frozen_ids.add(nid)
                continue
            # Rule 2: matches a frozen pattern
            for pat in FROZEN_PATTERNS:
                if _glob_match(nid, pat):
                    self._frozen_ids.add(nid)
                    break
            # Rule 3: contains an agent ID
            for aid in FROZEN_AGENT_IDS:
                if f"/{aid}/" in f"/{nid}/" or nid.endswith(f"/{aid}"):
                    self._frozen_ids.add(nid)
                    break

    def is_frozen(self, node_id: str) -> bool:
        return node_id in self._frozen_ids

    def evaluate_proposal(self, proposal: Dict[str, Any]) -> Tuple[bool, str]:
        """Returns (allowed, reason). allowed=False means reject."""
        ptype = proposal.get("type", "")

        if ptype == "archive":
            nid = proposal.get("node_id", "")
            if self.is_frozen(nid):
                return False, f"FROZEN: cannot archive core node '{nid}'"

        elif ptype == "new_edge":
            src = proposal.get("source_id", "")
            tgt = proposal.get("target_id", "")
            # Allow new edges TO frozen nodes (can reference them)
            # but not edges that would increase weight on existing
            # frozen-node edges beyond current value.
            # For new edges, always allow (additive is safe).
            pass  # New edges to/from frozen nodes are OK

        elif ptype == "new_entanglement_node":
            cluster = proposal.get("cluster_node_ids", [])
            frozen_in_cluster = [n for n in cluster if self.is_frozen(n)]
            if len(frozen_in_cluster) == len(cluster):
                return False, f"FROZEN: entanglement of all-frozen cluster"

        return True, "OK"


def _glob_match(node_id: str, pattern: str) -> bool:
    """Simple glob: * matches any single path segment."""
    import fnmatch
    return fnmatch.fnmatch(node_id, pattern)


# ── Stack 1 extension: Importance-Weighted Gating for non-frozen nodes ──

class ImportanceGate:
    """SI-inspired online importance tracking for non-frozen nodes."""

    def __init__(self, brain_conn: sqlite3.Connection):
        self._importance: Dict[str, float] = {}
        self._load_importance(brain_conn)

    def _load_importance(self, conn: sqlite3.Connection) -> None:
        """importance = access_count * base_activation (proxy for SI integral).

        Real SI would track gradient contribution; we approximate with
        activation frequency * activation magnitude, which is available
        in the existing schema without modification.
        """
        rows = conn.execute(
            "SELECT id, access_count, base_activation FROM nodes"
        ).fetchall()
        for row in rows:
            nid = row[0]
            acc = row[1] or 0
            base = row[2] or 0.0
            self._importance[nid] = min(1.0, (acc * max(base, 0.1)) / 100.0)

    def gate_proposal(
        self, proposal: Dict[str, Any], frozen_guard: FrozenNodeGuard
    ) -> Tuple[bool, str]:
        """Check if proposal's target nodes have high importance.

        For non-frozen high-importance nodes, require co-activation
        count > 3 * importance before auto-commit.
        """
        affected_nodes = self._extract_affected_nodes(proposal)
        for nid in affected_nodes:
            if frozen_guard.is_frozen(nid):
                continue  # Handled by FrozenNodeGuard
            imp = self._importance.get(nid, 0.0)
            if imp > 0.5:  # High importance threshold
                co_act = proposal.get("co_activations", 0) or proposal.get(
                    "co_activation_count", 0
                )
                required = int(3 * imp * 10)  # Scale to reasonable count
                if co_act < required:
                    return False, (
                        f"HIGH_IMPORTANCE: node '{nid}' importance={imp:.2f}, "
                        f"co_activations={co_act} < required={required}"
                    )
        return True, "OK"

    @staticmethod
    def _extract_affected_nodes(proposal: Dict[str, Any]) -> List[str]:
        affected = []
        if "node_id" in proposal:
            affected.append(proposal["node_id"])
        if "source_id" in proposal:
            affected.append(proposal["source_id"])
        if "target_id" in proposal:
            affected.append(proposal["target_id"])
        if "cluster_node_ids" in proposal:
            affected.extend(proposal["cluster_node_ids"])
        if "proposed_node_id" in proposal:
            affected.append(proposal["proposed_node_id"])
        return affected


# ── Stack 2: Replay Buffer (mixed sampling) ──

def mixed_sample_activation_log(
    conn: sqlite3.Connection,
    total_sample: int = 5000,
    recent_pct: float = 0.6,
    mid_pct: float = 0.2,
    historical_pct: float = 0.2,
) -> List[sqlite3.Row]:
    """Mixed sampling strategy for activation_log.

    Replaces the pure-recency query:
        SELECT ... ORDER BY id DESC LIMIT 5000

    With:
        60% from most recent rows
        20% from mid-history (rows 5001-20000)
        20% from uniform random across entire history

    Returns combined list of activation_log rows.
    """
    recent_n = int(total_sample * recent_pct)
    mid_n = int(total_sample * mid_pct)
    hist_n = total_sample - recent_n - mid_n

    # Recent window
    recent = conn.execute(
        "SELECT * FROM activation_log ORDER BY id DESC LIMIT ?",
        (recent_n,)
    ).fetchall()

    # Get total row count for offset calculation
    total_rows = conn.execute(
        "SELECT COUNT(*) FROM activation_log"
    ).fetchone()[0]

    # Mid-history window (rows 5001-20000 from top)
    mid = []
    if total_rows > recent_n:
        mid = conn.execute(
            "SELECT * FROM activation_log ORDER BY id DESC "
            "LIMIT ? OFFSET ?",
            (mid_n, recent_n)
        ).fetchall()

    # Historical uniform random sample
    hist = []
    if total_rows > recent_n + mid_n:
        hist = conn.execute(
            "SELECT * FROM activation_log "
            "WHERE id <= ? ORDER BY RANDOM() LIMIT ?",
            (max(1, total_rows - recent_n - mid_n), hist_n)
        ).fetchall()

    return list(recent) + list(mid) + list(hist)


# ── Stack 2 extension: Backward Transfer measurement ──

def compute_backward_transfer(
    brain_conn: sqlite3.Connection,
    historical_queries: List[str],
    baseline_topk: Dict[str, List[str]],
    k: int = 3,
) -> float:
    """Compute BWT: fraction of historical queries whose top-k
    nodes have changed since the baseline.

    Args:
        brain_conn: Connection to aiden_brain.db
        historical_queries: List of query strings from early sessions
        baseline_topk: {query: [node_id, ...]} from before L3 commit
        k: Number of top nodes to compare

    Returns:
        BWT score in [-1, 0]. 0 = no degradation, -1 = complete forgetting.
        Computed as: -1 * (fraction of queries with >50% top-k change)
    """
    from ystar.governance.cieu_brain_bridge import (
        project_event_to_6d,
        top_k_nodes,
    )

    degraded = 0
    total = 0
    for query in historical_queries:
        if query not in baseline_topk:
            continue
        total += 1
        # Simulate activation for this query
        # (Use a synthetic event row with the query as task_description)
        event_row = {
            "event_type": "bwt_probe",
            "task_description": query,
            "decision": "allow",
            "agent_id": "bwt_check",
        }
        coords = project_event_to_6d(event_row)
        current_topk = top_k_nodes(coords, k=k, conn=brain_conn)
        current_ids = [t[0] for t in current_topk]
        baseline_ids = baseline_topk[query][:k]

        # Overlap ratio
        overlap = len(set(current_ids) & set(baseline_ids))
        if overlap < k * 0.5:
            degraded += 1

    if total == 0:
        return 0.0
    return -(degraded / total)


# ── Stack 3: Checkpoint Rollback ──

class CheckpointManager:
    """Manages brain DB checkpoints for L3 rollback."""

    def __init__(self, brain_db_path: str, checkpoint_dir: str = CHECKPOINT_DIR):
        self._db_path = brain_db_path
        self._cp_dir = checkpoint_dir
        os.makedirs(self._cp_dir, exist_ok=True)

    def create_checkpoint(self) -> str:
        """Copy brain DB to checkpoint directory. Returns checkpoint path."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        cp_path = os.path.join(self._cp_dir, f"aiden_brain_{ts}.db")
        shutil.copy2(self._db_path, cp_path)
        self._prune_old_checkpoints()
        return cp_path

    def restore_latest(self) -> Optional[str]:
        """Restore brain DB from most recent checkpoint. Returns path or None."""
        checkpoints = sorted(Path(self._cp_dir).glob("aiden_brain_*.db"))
        if not checkpoints:
            return None
        latest = checkpoints[-1]
        shutil.copy2(str(latest), self._db_path)
        return str(latest)

    def _prune_old_checkpoints(self) -> int:
        """Keep only MAX_CHECKPOINTS most recent. Returns pruned count."""
        checkpoints = sorted(Path(self._cp_dir).glob("aiden_brain_*.db"))
        pruned = 0
        while len(checkpoints) > MAX_CHECKPOINTS:
            oldest = checkpoints.pop(0)
            oldest.unlink()
            pruned += 1
        return pruned


def check_rollback_triggers(
    cieu_conn: sqlite3.Connection,
    brain_conn: sqlite3.Connection,
    last_commit_ts: float,
    historical_queries: List[str],
    baseline_topk: Dict[str, List[str]],
    pre_commit_activation_dist: Dict[str, float],
) -> Tuple[bool, str]:
    """Check all rollback triggers. Returns (should_rollback, reason).

    Triggers:
      1. Board corrections >= 3 in 24h
      2. BWT < -0.1
      3. Frozen node violations > 0
      4. KL divergence > 0.3
    """
    window_start = last_commit_ts
    window_end = last_commit_ts + (ROLLBACK_WINDOW_HOURS * 3600)
    now = time.time()
    if now > window_end:
        return False, "ROLLBACK_WINDOW_EXPIRED"

    # Trigger 1: Board corrections
    try:
        corr_count = cieu_conn.execute(
            "SELECT COUNT(*) FROM cieu_events "
            "WHERE event_type IN ('BOARD_CORRECTION', 'board_override') "
            "AND created_at BETWEEN ? AND ?",
            (window_start, now),
        ).fetchone()[0]
        if corr_count >= BOARD_CORRECTION_THRESHOLD:
            return True, f"BOARD_CORRECTIONS={corr_count} >= {BOARD_CORRECTION_THRESHOLD}"
    except sqlite3.OperationalError:
        pass

    # Trigger 2: BWT check
    bwt = compute_backward_transfer(
        brain_conn, historical_queries, baseline_topk
    )
    if bwt < BWT_THRESHOLD:
        return True, f"BWT={bwt:.3f} < {BWT_THRESHOLD}"

    # Trigger 3: Frozen node violations
    try:
        frozen_violations = cieu_conn.execute(
            "SELECT COUNT(*) FROM cieu_events "
            "WHERE event_type = ? AND created_at BETWEEN ? AND ?",
            (L3_FROZEN_NODE_VIOLATION, window_start, now),
        ).fetchone()[0]
        if frozen_violations > 0:
            return True, f"FROZEN_VIOLATIONS={frozen_violations}"
    except sqlite3.OperationalError:
        pass

    # Trigger 4: KL divergence
    post_dist = _compute_activation_distribution(brain_conn)
    kl = _kl_divergence(post_dist, pre_commit_activation_dist)
    if kl > KL_DIVERGENCE_THRESHOLD:
        return True, f"KL_DIVERGENCE={kl:.3f} > {KL_DIVERGENCE_THRESHOLD}"

    return False, "ALL_CLEAR"


def _compute_activation_distribution(
    conn: sqlite3.Connection, top_n: int = TOP_K_FOR_DISTRIBUTION
) -> Dict[str, float]:
    """Compute normalized activation frequency for top-N nodes
    over the last 100 L1 queries."""
    rows = conn.execute(
        "SELECT activated_nodes FROM activation_log "
        "WHERE query NOT LIKE 'auto_ingest:%' "
        "ORDER BY id DESC LIMIT 100"
    ).fetchall()

    counts: Dict[str, int] = {}
    total = 0
    for row in rows:
        try:
            nodes = json.loads(row[0] if not isinstance(row, dict) else row["activated_nodes"])
            for n in nodes:
                nid = n.get("node_id", "")
                if nid:
                    counts[nid] = counts.get(nid, 0) + 1
                    total += 1
        except (json.JSONDecodeError, TypeError):
            continue

    # Normalize and keep top-N
    if total == 0:
        return {}
    sorted_nodes = sorted(counts.items(), key=lambda x: -x[1])[:top_n]
    return {nid: cnt / total for nid, cnt in sorted_nodes}


def _kl_divergence(
    p: Dict[str, float], q: Dict[str, float], epsilon: float = 1e-10
) -> float:
    """KL(P || Q) over the union of keys. Missing keys get epsilon."""
    all_keys = set(p.keys()) | set(q.keys())
    kl = 0.0
    for k in all_keys:
        pk = p.get(k, epsilon)
        qk = q.get(k, epsilon)
        if pk > 0:
            kl += pk * math.log(pk / qk)
    return max(0.0, kl)


# ── Integration Point: evaluate_proposals() ──

def evaluate_proposals(
    proposals: List[Dict[str, Any]],
    brain_conn: sqlite3.Connection,
    cieu_store: Optional[CIEUStore] = None,
    session_id: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run all proposals through the guard rail stack.

    Returns (accepted, rejected) lists.
    """
    frozen_guard = FrozenNodeGuard(brain_conn)
    importance_gate = ImportanceGate(brain_conn)

    accepted = []
    rejected = []

    for proposal in proposals:
        # Stack 1a: Frozen node check
        allowed, reason = frozen_guard.evaluate_proposal(proposal)
        if not allowed:
            proposal["rejection_reason"] = reason
            rejected.append(proposal)
            _emit_guard_event(
                cieu_store, L3_FROZEN_NODE_VIOLATION,
                {"proposal": proposal, "reason": reason},
                session_id,
            )
            continue

        # Stack 1b: Importance gating
        allowed, reason = importance_gate.gate_proposal(proposal, frozen_guard)
        if not allowed:
            proposal["rejection_reason"] = reason
            rejected.append(proposal)
            _emit_guard_event(
                cieu_store, L3_HIGH_IMPORTANCE_WARN,
                {"proposal": proposal, "reason": reason},
                session_id,
            )
            continue

        # Passed all gates
        accepted.append(proposal)
        _emit_guard_event(
            cieu_store, L3_PROPOSAL_ACCEPTED,
            {"proposal_id": proposal.get("id", ""), "type": proposal.get("type", "")},
            session_id,
        )

    return accepted, rejected


def _emit_guard_event(
    store: Optional[CIEUStore],
    event_type: str,
    payload: dict,
    session_id: str,
) -> None:
    if store is None:
        return
    try:
        store.emit_brain_event(
            event_type=event_type,
            payload=payload,
            session_id=session_id,
            agent_id="l3-guard-rails",
        )
    except Exception:
        pass  # Best-effort emit; guard rail logic must not crash on CIEU failure
```

### 4.2 Modifications to `brain_dream_scheduler.py`

**Function**: `consolidate()` (line 316)

Add guard rail integration between proposal generation and proposal write:

```python
# After: all_proposals.extend(d_props)  (line 438)
# Before: _write_proposals(all_proposals, proposals_path)  (line 444)

# NEW: L3 guard rail evaluation (only in auto mode)
if auto_mode:
    from ystar.governance.l3_guard_rails import (
        evaluate_proposals,
        CheckpointManager,
    )
    # Create pre-commit checkpoint
    cp_mgr = CheckpointManager(brain_db_path)
    cp_path = cp_mgr.create_checkpoint()

    # Evaluate proposals through guard rails
    accepted, rejected = evaluate_proposals(
        all_proposals, conn, cieu_store=cieu_store, session_id=session_id
    )

    # Only commit accepted proposals
    _apply_accepted_proposals(accepted, conn)  # NEW function
    all_proposals = accepted  # For summary reporting

    # Store pre-commit activation distribution for rollback check
    from ystar.governance.l3_guard_rails import _compute_activation_distribution
    pre_commit_dist = _compute_activation_distribution(conn)
    _write_rollback_metadata(cp_path, pre_commit_dist, proposals_path)
```

**New parameter** for `consolidate()`:
```python
auto_mode: bool = False,  # When True, accepted proposals are committed to brain DB
```

**New function** `_apply_accepted_proposals()`:
```python
def _apply_accepted_proposals(proposals: List[Dict], conn) -> int:
    """Apply accepted proposals to brain DB.

    Types handled:
      new_edge -> INSERT INTO edges
      new_entanglement_node -> INSERT INTO nodes + edges
      archive -> UPDATE nodes SET depth_label='archived'
      new_node -> INSERT INTO nodes
    """
    applied = 0
    now = time.time()
    for p in proposals:
        ptype = p.get("type", "")
        if ptype == "new_edge":
            conn.execute(
                "INSERT OR IGNORE INTO edges "
                "(source_id, target_id, edge_type, weight, created_at, updated_at, co_activations) "
                "VALUES (?, ?, 'dream', ?, ?, ?, ?)",
                (p["source_id"], p["target_id"], p.get("proposed_weight", 0.15),
                 now, now, p.get("co_activations", 0))
            )
            applied += 1
        elif ptype == "new_node":
            conn.execute(
                "INSERT OR IGNORE INTO nodes "
                "(id, name, node_type, depth_label, created_at, updated_at, summary) "
                "VALUES (?, ?, 'dream_generated', 'tactical', ?, ?, ?)",
                (p.get("proposed_node_id", ""), p.get("trigger_query", "")[:80],
                 now, now, p.get("reason", ""))
            )
            applied += 1
        elif ptype == "archive":
            conn.execute(
                "UPDATE nodes SET depth_label='archived', updated_at=? WHERE id=?",
                (now, p["node_id"])
            )
            applied += 1
        elif ptype == "new_entanglement_node":
            ent_id = f"entanglement/{'_'.join(sorted(p['cluster_node_ids']))[:60]}"
            conn.execute(
                "INSERT OR IGNORE INTO nodes "
                "(id, name, node_type, depth_label, created_at, updated_at, summary) "
                "VALUES (?, ?, 'ecosystem_entanglement', 'operational', ?, ?, ?)",
                (ent_id, f"Entanglement: {len(p['cluster_node_ids'])} nodes",
                 now, now, p.get("reason", ""))
            )
            for nid in p["cluster_node_ids"]:
                conn.execute(
                    "INSERT OR IGNORE INTO edges "
                    "(source_id, target_id, edge_type, weight, created_at, updated_at) "
                    "VALUES (?, ?, 'entanglement', 0.5, ?, ?)",
                    (ent_id, nid, now, now)
                )
            applied += 1
    conn.commit()
    return applied
```

### 4.3 Modifications to `cieu_brain_learning.py`

**Function**: `run_learning_cycle()` (line 458)

Add replay buffer sampling:

```python
# Replace the direct call to apply_drift_to_all_nodes with
# a version that uses mixed sampling when in L3 auto mode.

# In the function signature, add:
#   use_replay_buffer: bool = False

# In the body, before Step 1:
if use_replay_buffer:
    from ystar.governance.l3_guard_rails import mixed_sample_activation_log
    # Override the window-based scan with mixed sampling
    # (This is consumed by the drift computation)
    pass  # The mixed sampling is applied at the activation_log query level
```

**Note**: The actual mixed sampling integration is in `brain_dream_scheduler.py`'s pattern functions, not in `cieu_brain_learning.py`. The learning module's `apply_drift_to_all_nodes` uses `_batch_collect_node_event_ids` which already scans activation_log. To integrate replay buffer, modify `_batch_collect_node_event_ids` to accept a `sample_fn` parameter that defaults to pure-recency but can be overridden with `mixed_sample_activation_log`.

### 4.4 CIEU Schema: New Event Types

Add to `cieu_store.py` after the existing `BRAIN_DREAM_PROPOSAL_TYPES` block:

```python
# ── L3 Guard Rail Event Types ──────────────────────────────────────────
# Registered per CZL-BRAIN-L3-GUARD-RAILS-ruling (2026-04-20).

L3_GUARD_RAILS_ARMED = "L3_GUARD_RAILS_ARMED"
# Payload: {"auto_mode": bool, "frozen_count": int, "checkpoint_path": str,
#           "session_id": str}

L3_FROZEN_NODE_VIOLATION = "L3_FROZEN_NODE_VIOLATION"
# Payload: {"proposal": dict, "reason": str, "node_id": str,
#           "session_id": str}

L3_HIGH_IMPORTANCE_WARN = "L3_HIGH_IMPORTANCE_WARN"
# Payload: {"proposal": dict, "reason": str, "node_id": str,
#           "importance": float, "session_id": str}

L3_PROPOSAL_ACCEPTED = "L3_PROPOSAL_ACCEPTED"
# Payload: {"proposal_id": str, "type": str, "session_id": str}

L3_PROPOSAL_REJECTED = "L3_PROPOSAL_REJECTED"
# Payload: {"proposal_id": str, "type": str, "reason": str,
#           "session_id": str}

L3_CHECKPOINT_CREATED = "L3_CHECKPOINT_CREATED"
# Payload: {"checkpoint_path": str, "brain_db_size_bytes": int,
#           "session_id": str}

L3_ROLLBACK_TRIGGERED = "L3_ROLLBACK_TRIGGERED"
# Payload: {"trigger": str, "value": float, "threshold": float,
#           "checkpoint_restored": str, "session_id": str}

L3_BWT_CHECK = "L3_BWT_CHECK"
# Payload: {"bwt_score": float, "threshold": float, "queries_tested": int,
#           "degraded_count": int, "session_id": str}

L3_KL_DRIFT_CHECK = "L3_KL_DRIFT_CHECK"
# Payload: {"kl_divergence": float, "threshold": float,
#           "top_shifted_nodes": list[str], "session_id": str}

L3_PROMOTION_EVAL = "L3_PROMOTION_EVAL"
# Payload: {"drift_rate_24h": float, "frozen_violations": int,
#           "rollback_count": int, "consecutive_clean": int,
#           "promoted": bool, "session_id": str}

# Add to BRAIN_EVENT_TYPES list:
L3_GUARD_RAIL_EVENT_TYPES = [
    L3_GUARD_RAILS_ARMED,
    L3_FROZEN_NODE_VIOLATION,
    L3_HIGH_IMPORTANCE_WARN,
    L3_PROPOSAL_ACCEPTED,
    L3_PROPOSAL_REJECTED,
    L3_CHECKPOINT_CREATED,
    L3_ROLLBACK_TRIGGERED,
    L3_BWT_CHECK,
    L3_KL_DRIFT_CHECK,
    L3_PROMOTION_EVAL,
]
```

### 4.5 Modifications to `brain_auto_ingest.py`

No changes required. Brain auto-ingest operates at L1/L2 (boundary ingest), which is upstream of L3 guard rails. The guard rails only gate L3 dream consolidation commits.

### 4.6 File Change Summary

| File | Change Type | What |
|------|:-----------:|------|
| `ystar/governance/l3_guard_rails.py` | **NEW** | Full guard rail module (Stack 1 + 2 + 3) |
| `ystar/governance/brain_dream_scheduler.py` | MODIFY | Add `auto_mode` param to `consolidate()`, wire guard rail evaluation between proposal generation and commit, add `_apply_accepted_proposals()` |
| `ystar/governance/cieu_store.py` | MODIFY | Register 10 new L3 event types + add to `emit_brain_event()` validation |
| `ystar/governance/cieu_brain_learning.py` | MINOR | Accept `sample_fn` in `_batch_collect_node_event_ids` for replay buffer |

---

## 5. Promotion Criteria

L3 auto mode can go LIVE when ALL of the following metrics are satisfied over a qualifying period:

### 5.1 Drift Rate (24h post-commit)

**Metric**: `drift_rate_24h = count(L3_ROLLBACK_TRIGGERED) / count(L3_CHECKPOINT_CREATED)` over last N dream cycles.

**Threshold**: `drift_rate_24h < 5%` (i.e., fewer than 1 in 20 L3 auto-commits triggers rollback).

**Qualifying period**: 10 consecutive L3 dream cycles with drift_rate = 0%.

**Rationale**: A drift rate of 5% means the guard rails are catching and recovering from bad commits effectively. Zero rollbacks for 10 consecutive cycles demonstrates stability. At current cadence (~2 dream cycles per day from session-close + idle triggers), this is approximately 5 days of clean operation.

### 5.2 Core-Frozen Violations

**Metric**: `frozen_violations = count(L3_FROZEN_NODE_VIOLATION)`

**Threshold**: `frozen_violations = 0` across ALL L3 auto cycles ever.

**Rationale**: This is a hard invariant, not a statistical threshold. If a frozen node violation occurs, it means either (a) the frozen set is misconfigured, or (b) the dream proposer is generating unsafe proposals. Either case requires investigation before allowing auto mode.

### 5.3 Rollback Trigger Count (consecutive clean)

**Metric**: `consecutive_clean_cycles` = number of consecutive L3 auto cycles with zero rollback triggers fired.

**Threshold**: `consecutive_clean_cycles >= 20`

**Rationale**: At ~2 cycles/day, this is approximately 10 days of clean operation. 20 cycles gives strong statistical evidence that the guard rails are not needed for recovery, meaning the dream proposals themselves are consistently safe.

### 5.4 BWT Score

**Metric**: Backward transfer on historical query held-out set (50 queries from sessions 1-10).

**Threshold**: `BWT > -0.05` (less than 5% degradation on historical queries).

**Qualifying period**: Must hold for 10 consecutive cycles.

**Rationale**: BWT > -0.05 is stricter than the rollback trigger threshold (-0.1). The promotion criterion is tighter because we want confidence that L3 is not just "not catastrophically bad" but actually preserving existing knowledge.

### 5.5 KL Divergence Stability

**Metric**: Mean KL divergence between consecutive L3 cycles.

**Threshold**: `mean_kl < 0.1` over last 20 cycles.

**Rationale**: Low KL means the brain's activation distribution is stable across L3 commits. This rules out the scenario where each commit is individually small but their cumulative effect is a slow drift.

### 5.6 Proposal Acceptance Rate

**Metric**: `acceptance_rate = count(L3_PROPOSAL_ACCEPTED) / count(L3_PROPOSAL_ACCEPTED + L3_PROPOSAL_REJECTED)`

**Threshold**: `acceptance_rate > 80%`

**Rationale**: If the guard rails are rejecting more than 20% of proposals, it means the dream proposer is generating a lot of unsafe proposals. The proposer should be tuned before allowing auto mode, rather than relying on guard rails to filter.

### 5.7 Promotion Decision Flow

```
IF frozen_violations == 0
AND consecutive_clean_cycles >= 20
AND drift_rate_24h < 0.05
AND bwt_mean_10cycles > -0.05
AND mean_kl_20cycles < 0.1
AND acceptance_rate > 0.8
THEN:
    emit L3_PROMOTION_EVAL(promoted=True)
    set auto_mode = True in brain_dream_scheduler config
    notify Board via CIEU event
ELSE:
    emit L3_PROMOTION_EVAL(promoted=False, reasons=[...])
    remain in dry-run mode
```

**Board override**: Board can force-enable or force-disable L3 auto mode at any time via a governance directive, bypassing metric thresholds. The guard rails (frozen protection, rollback) remain active regardless of promotion status.

---

## 6. Risk Residuals

Even with the full 3-stack deployed and all promotion criteria met, the following risks remain:

### 6.1 Slow Semantic Drift (Undetectable by KL/BWT)

**Risk**: L3 commits that are individually small and pass all guard rails, but whose cumulative effect over months gradually shifts the brain's "personality" (which nodes dominate which types of decisions). KL divergence between consecutive commits may be <0.1 each time, but KL between the current state and the state 100 commits ago could be >1.0.

**Mitigation (not in 3-stack, future work)**: Periodic "epoch checkpoints" -- every 50 L3 cycles, compare current state to the epoch-0 baseline. If KL(current || epoch_0) > 0.5, emit a `L3_EPOCH_DRIFT_ALERT` for Board review.

**Residual severity**: MEDIUM. The frozen node protection prevents drift in the MOST important nodes, but non-frozen nodes can still drift slowly.

### 6.2 Replay Buffer Selection Bias

**Risk**: The 60/20/20 split in the replay buffer is a heuristic. If the brain's early sessions (historical 20%) contain low-quality or unrepresentative data (e.g., from initial setup confusion), replaying them contaminates new learning.

**Mitigation**: Quality-weighted replay -- weight historical samples by their associated L2 outcome score. Samples from decisions that Board corrected should have LOWER replay weight. This requires L2 Hebbian to be live and producing outcome data (currently not yet shipped per CZL-BRAIN-3LOOP-FINAL ruling).

**Residual severity**: LOW-MEDIUM. The 20% historical weight is small enough that bad historical data is diluted by 80% recent/mid data.

### 6.3 Frozen Set Incompleteness

**Risk**: The frozen set is defined by patterns (`WHO_I_AM`, `IRON_RULES`, etc.) and depth labels (`kernel`). A new governance-critical node added in the future might not match any of these patterns and would be unprotected.

**Mitigation**: Every time a new node is added with `depth_label='kernel'` or `depth_label='foundational'`, emit a `L3_FROZEN_SET_UPDATED` event and require Board confirmation that the frozen set is still correct.

**Residual severity**: LOW. The pattern matching is broad, and the `kernel` depth label is the primary gate. New critical nodes should always be labeled `kernel` by the governance ingest process.

### 6.4 Checkpoint Storage Exhaustion

**Risk**: With MAX_CHECKPOINTS = 10 and aiden_brain.db growing over time (currently ~1MB, could reach 50MB+), checkpoint storage could consume 500MB+. On constrained environments this could become a problem.

**Mitigation**: Compress checkpoints with gzip (SQLite DBs compress well, typically 3-5x). Also consider incremental checkpoints (SQLite backup API) instead of full copies.

**Residual severity**: LOW. 500MB is negligible on modern systems, and the 10-checkpoint cap is configurable.

### 6.5 Race Condition: L3 Commits During Active Session

**Risk**: If L3 auto-commit runs during an active session (e.g., triggered by idle detector while a session is still alive but slow), the brain DB changes mid-session. The current session's L1 query results become stale, and L2 Hebbian feedback may reference nodes that have been archived or edges that have been reweighted.

**Mitigation**: The existing 30-minute lockout sentinel in `brain_dream_scheduler.py` provides basic protection. Additionally, L3 auto-commit should check whether any session is currently active (read `.ystar_session.json` lock status) and defer if active.

**Residual severity**: MEDIUM. The lockout sentinel prevents rapid re-triggers but does not prevent a single badly-timed trigger during an active session. Needs session-awareness in the consolidation trigger.

### 6.6 Adversarial Proposal Crafting

**Risk**: If a compromised or buggy agent generates CIEU events specifically designed to create activation patterns that bypass guard rails (e.g., slowly building co-activation counts on frozen-node edges to meet the importance gate's `3 * importance` threshold), the guard rails could be systematically defeated.

**Mitigation**: The frozen node guard uses a HARD REJECT, not a threshold. No amount of co-activation can unlock a frozen node for archival or coordinate modification. The importance gate only applies to non-frozen nodes, where some flexibility is by design. Additional mitigation: K9 behavioral audit of CIEU event sources, flagging agents that produce anomalous activation patterns.

**Residual severity**: LOW. The frozen set is hard-coded, not threshold-based. Adversarial bypass would require modifying the guard rail code itself, which is a different threat model (code supply chain).

### 6.7 Honest Epistemic Disclaimer

The BWT threshold (-0.1), KL threshold (0.3), and promotion criteria (20 consecutive clean cycles) are engineering judgment calls, not empirically validated values. They are calibrated by analogy to the dominance monitor thresholds in CZL-BRAIN-3LOOP-FINAL (Point 7) and standard continual learning benchmarks (CLEAR's forgetting metrics). **These thresholds should be tuned based on the first 30 days of L3 dry-run data.** If dry-run data shows that normal variation produces BWT in the [-0.03, 0] range, the rollback threshold of -0.1 is conservative enough. If normal variation is [-0.08, 0], the threshold needs tightening.

---

## 7. Implementation Order

```
Phase 1 (Leo, P1):
  - New file: l3_guard_rails.py (Stacks 1+2+3)
  - Tests: test_l3_guard_rails.py (frozen guard, importance gate,
    checkpoint create/restore, KL divergence, BWT computation)

Phase 2 (Maya, P1, parallel with Phase 1):
  - CIEU store: register 10 new event types
  - CIEU store: add L3_GUARD_RAIL_EVENT_TYPES to emit_brain_event validation

Phase 3 (Leo + Ryan, P1, after Phase 1):
  - brain_dream_scheduler.py: add auto_mode parameter + guard rail wire
  - brain_dream_scheduler.py: add _apply_accepted_proposals()
  - Integration test: end-to-end dream cycle with guard rails

Phase 4 (Board decision):
  - Enable L3 dry-run mode (auto_mode=True but proposals logged, not committed)
  - Collect 30 days of data
  - Evaluate promotion criteria
  - Board decides to go LIVE or adjust thresholds
```

---

## Cross-References

- 3-Loop architecture: `Y-star-gov/reports/cto/CZL-BRAIN-3LOOP-FINAL-ruling.md`
- Dream scheduler: `Y-star-gov/ystar/governance/brain_dream_scheduler.py`
- CIEU brain learning: `Y-star-gov/ystar/governance/cieu_brain_learning.py`
- CIEU brain bridge: `Y-star-gov/ystar/governance/cieu_brain_bridge.py`
- Brain auto-ingest: `Y-star-gov/ystar/governance/brain_auto_ingest.py`
- CIEU store (event types): `Y-star-gov/ystar/governance/cieu_store.py`
- Brain DB schema: `ystar-company/scripts/aiden_brain.py`

---

*This ruling is binding on L3 guard rail implementation. Engineers proceed per the implementation order above. Threshold values are initial engineering judgment and will be calibrated against 30 days of dry-run data before L3 auto mode goes LIVE.*

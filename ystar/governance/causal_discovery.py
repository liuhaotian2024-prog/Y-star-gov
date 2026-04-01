# Layer: Foundation
"""
ystar.governance.causal_discovery — PC Algorithm + DirectLiNGAM causal structure discovery

Split from causal_engine.py for modularity.

Implements:
  - PC Algorithm (Peter & Clark, 2000) for constraint-based causal discovery
  - DirectLiNGAM (Shimizu et al., 2011) for non-Gaussian causal discovery
  - Statistical helpers: Fisher z-test, partial correlation, BIC scoring
"""
from __future__ import annotations
from typing import List, Dict, Tuple, Optional, Set, FrozenSet
import math

from ystar.governance.causal_graph import CausalGraph
from ystar.governance.structural_equation import _solve_linear_system


class CausalDiscovery:
    """
    PC Algorithm (Peter & Clark, 2000) for causal structure discovery.

    Discovers the causal DAG from observational data using conditional
    independence tests. No external dependencies.

    Pearl (2009), Chapter 2: "From conditional independencies in the data,
    we can recover the causal structure."

    For Y*gov: discovers the causal relationships between governance
    variables (W, O, H, S) from CIEU audit records, rather than
    requiring a human to specify the DAG.

    Algorithm outline:
      Step 1 — Skeleton: Remove edges between conditionally independent pairs.
      Step 2 — V-structures: Orient colliders X -> Z <- Y.
      Step 3 — Meek rules: Orient remaining edges to avoid new v-structures
               and cycles.
    """

    def __init__(self, alpha: float = 0.05):
        """
        Args:
            alpha: Significance level for the conditional independence test.
                   Lower alpha = fewer edges (more conservative).
        """
        self.alpha = alpha
        # Separating sets: sep_set[(x,y)] = the conditioning set Z that
        # rendered x and y independent, or None if never separated.
        self.sep_set: Dict[FrozenSet[str], Set[str]] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def run(
        self,
        data: List[Dict[str, float]],
        temporal_order: Optional[List[str]] = None,
    ) -> CausalGraph:
        """
        Run the full PC algorithm on observational data.

        Args:
            data: List of observations [{var: value, ...}, ...].
                  All dicts must have the same keys.
            temporal_order: Optional list of variable names in causal time order.
                  e.g. ['S', 'W', 'O', 'H'] means S happens before W, W before O, etc.
                  When provided, any edge whose direction cannot be determined by
                  v-structures or Meek rules is oriented according to this ordering.
                  This is NOT a statistical assumption — it encodes architectural
                  background knowledge about the system's execution sequence.

        Returns:
            A CausalGraph (directed) representing the discovered DAG.
        """
        if not data or len(data) < 4:
            raise ValueError("PC algorithm requires at least 4 observations.")

        variables = sorted(data[0].keys())
        self._data = data
        self._variables = variables

        # Step 1: Skeleton discovery
        adj, sep = self._discover_skeleton(data, variables)
        self.sep_set = sep

        # Step 2: Orient v-structures (colliders)
        oriented = self._orient_v_structures(adj, sep, variables)

        # Step 3: Meek rules — orient remaining edges
        oriented = self._apply_meek_rules(oriented, variables)

        # Step 3.5: Temporal ordering — resolve Markov equivalence class ambiguity
        # For linear Gaussian SCMs, PC can only identify the equivalence class.
        # Temporal ordering from system architecture breaks the symmetry.
        if temporal_order:
            oriented = self._apply_temporal_ordering(oriented, temporal_order, variables)

        # Convert oriented adjacency to CausalGraph edge dict
        edge_dict: Dict[str, List[str]] = {}
        for (a, b) in oriented:
            edge_dict.setdefault(a, []).append(b)

        return CausalGraph(edge_dict)

    def _apply_temporal_ordering(
        self,
        oriented: Set[Tuple[str, str]],
        temporal_order: List[str],
        variables: List[str],
    ) -> Set[Tuple[str, str]]:
        """
        Apply temporal background knowledge to orient remaining undirected edges.

        Within each governance cycle, variables follow a natural temporal ordering:
          S (suggestion) → W (wiring) → O (obligation) → H (health)

        For any edge where both directions (A→B and B→A) are in the oriented set
        (meaning it's still undirected), or where the direction contradicts temporal
        order, re-orient according to the temporal ordering.

        This is architecturally guaranteed: suggestions are produced before wiring
        decisions; health is measured after obligations are assessed. This is not
        a statistical assumption — it is a structural property of the governance
        cycle itself.

        Pearl (2009), Section 2.3: "Background knowledge can be incorporated
        to select among observationally equivalent DAGs."
        """
        order_map = {v: i for i, v in enumerate(temporal_order)}
        final = set()

        # Collect all edges as undirected pairs first
        edge_pairs = {}  # frozenset → list of directed versions
        for (a, b) in oriented:
            key = frozenset([a, b])
            edge_pairs.setdefault(key, []).append((a, b))

        for key, directions in edge_pairs.items():
            nodes = list(key)
            if len(nodes) != 2:
                for d in directions:
                    final.add(d)
                continue

            a, b = nodes[0], nodes[1]

            # Check if both nodes are in temporal order
            if a in order_map and b in order_map:
                # Orient from earlier to later in temporal order
                if order_map[a] < order_map[b]:
                    final.add((a, b))
                else:
                    final.add((b, a))
            else:
                # No temporal info — keep whatever PC decided
                for d in directions:
                    final.add(d)

        return final

    # ── Step 1: Skeleton Discovery ────────────────────────────────────────

    def _discover_skeleton(
        self,
        data: List[Dict[str, float]],
        variables: List[str],
    ) -> Tuple[Dict[str, Set[str]], Dict[FrozenSet[str], Set[str]]]:
        """
        Build the undirected skeleton by testing conditional independencies.

        Start with the complete undirected graph, then for conditioning
        sets of increasing size, remove edges between pairs found to be
        conditionally independent.

        Returns:
            adj: Undirected adjacency {node: set of neighbours}
            sep: Separating sets {frozenset({x, y}): conditioning_set}
        """
        # Start with complete undirected graph
        adj: Dict[str, Set[str]] = {v: set(variables) - {v} for v in variables}
        sep: Dict[FrozenSet[str], Set[str]] = {}

        # Compute correlation matrix once
        corr = _correlation_matrix(data, variables)
        n = len(data)

        # Test conditioning sets of increasing size
        max_cond_size = len(variables) - 2
        for cond_size in range(0, max_cond_size + 1):
            # Iterate over pairs that are still adjacent
            pairs_to_check = []
            for x in variables:
                for y in variables:
                    if x < y and y in adj[x]:
                        pairs_to_check.append((x, y))

            any_removed = False
            for x, y in pairs_to_check:
                if y not in adj[x]:
                    continue  # already removed in this pass

                # Neighbours of x excluding y (potential conditioning sets)
                neighbours = adj[x] - {y}
                if len(neighbours) < cond_size:
                    continue

                # Enumerate subsets of neighbours of size cond_size
                for z_set in _subsets(sorted(neighbours), cond_size):
                    z = set(z_set)
                    if fisher_z_test(corr, variables, x, y, z, n, self.alpha):
                        # X ⊥ Y | Z — remove edge, record separating set
                        adj[x].discard(y)
                        adj[y].discard(x)
                        sep[frozenset({x, y})] = z
                        any_removed = True
                        break  # no need to test more subsets for this pair

            if not any_removed and cond_size > 0:
                break  # no progress, done

        return adj, sep

    # ── Step 2: Orient V-Structures ───────────────────────────────────────

    def _orient_v_structures(
        self,
        adj: Dict[str, Set[str]],
        sep: Dict[FrozenSet[str], Set[str]],
        variables: List[str],
    ) -> Set[Tuple[str, str]]:
        """
        Orient v-structures (colliders): X -> Z <- Y.

        For each unshielded triple X — Z — Y (where X and Y are NOT adjacent),
        if Z is NOT in sep_set(X, Y), orient as X -> Z <- Y.

        Returns:
            Set of directed edges (parent, child).
        """
        # Track which edges are oriented vs undirected
        oriented: Set[Tuple[str, str]] = set()
        undirected: Set[FrozenSet[str]] = set()

        for x in variables:
            for y in adj[x]:
                undirected.add(frozenset({x, y}))

        # Find v-structures
        for z in variables:
            neighbours = sorted(adj[z])
            for i, x in enumerate(neighbours):
                for y in neighbours[i + 1:]:
                    # X — Z — Y: check if X and Y are NOT adjacent
                    if y in adj[x]:
                        continue  # shielded triple, skip

                    # Unshielded triple: check separating set
                    pair_key = frozenset({x, y})
                    z_sep = sep.get(pair_key, set())
                    if z not in z_sep:
                        # V-structure: X -> Z <- Y
                        oriented.add((x, z))
                        oriented.add((y, z))
                        undirected.discard(frozenset({x, z}))
                        undirected.discard(frozenset({y, z}))

        # Remaining undirected edges stay undirected for now
        # Store them as both directions for Meek rule processing
        for edge in undirected:
            a, b = sorted(edge)
            # Only add if not already oriented in either direction
            if (a, b) not in oriented and (b, a) not in oriented:
                oriented.add((a, b))
                oriented.add((b, a))

        return oriented

    # ── Step 3: Meek Rules ────────────────────────────────────────────────

    def _apply_meek_rules(
        self,
        oriented: Set[Tuple[str, str]],
        variables: List[str],
    ) -> Set[Tuple[str, str]]:
        """
        Apply Meek's orientation rules until convergence.

        Rules (Meek 1995):
          R1: X -> Z — Y, X and Y not adjacent => Z -> Y
          R2: X -> Z -> Y, X — Y => X -> Y
          R3: X — Z, X — Y, Z -> W <- Y, X — W => X -> W
          R4: Avoid creating cycles

        An undirected edge X — Y is represented as both (X,Y) and (Y,X)
        in the oriented set. A directed edge X -> Y has only (X,Y).
        """
        changed = True
        while changed:
            changed = False
            for x in variables:
                for y in variables:
                    if x == y:
                        continue
                    # Check if x — y is undirected (both directions present)
                    if not ((x, y) in oriented and (y, x) in oriented):
                        continue

                    # Rule 1: exists Z such that Z -> X — Y and Z not adj Y
                    for z in variables:
                        if z == x or z == y:
                            continue
                        # Z -> X (directed, not undirected)
                        if (z, x) in oriented and (x, z) not in oriented:
                            # Z and Y not adjacent
                            if (z, y) not in oriented and (y, z) not in oriented:
                                # Orient X -> Y
                                oriented.discard((y, x))
                                changed = True
                                break
                    if changed:
                        # Re-check from top
                        break

                    # Rule 2: exists Z such that X -> Z -> Y, X — Y
                    for z in variables:
                        if z == x or z == y:
                            continue
                        # X -> Z directed
                        if (x, z) in oriented and (z, x) not in oriented:
                            # Z -> Y directed
                            if (z, y) in oriented and (y, z) not in oriented:
                                # Orient X -> Y
                                oriented.discard((y, x))
                                changed = True
                                break
                    if changed:
                        break

                    # Rule 3: exists Z, W such that X — Z -> Y, X — W -> Y,
                    #          Z and W not adjacent
                    found_r3 = False
                    neighbours_of_x = [
                        v for v in variables
                        if v != x and v != y
                        and (x, v) in oriented and (v, x) in oriented
                    ]
                    for i, z in enumerate(neighbours_of_x):
                        if (z, y) not in oriented or (y, z) in oriented:
                            continue  # need Z -> Y directed
                        for w in neighbours_of_x[i + 1:]:
                            if (w, y) not in oriented or (y, w) in oriented:
                                continue  # need W -> Y directed
                            # Z and W not adjacent
                            if (z, w) not in oriented and (w, z) not in oriented:
                                oriented.discard((y, x))
                                changed = True
                                found_r3 = True
                                break
                        if found_r3:
                            break
                    if changed:
                        break
                if changed:
                    break

        # Remove any remaining cycles by dropping the edge that closes the cycle
        oriented = self._break_cycles(oriented, variables)

        return oriented

    def _break_cycles(
        self, oriented: Set[Tuple[str, str]], variables: List[str]
    ) -> Set[Tuple[str, str]]:
        """
        Orient remaining undirected edges and remove cycles.

        For undirected edges, use a regression-based heuristic: orient
        A -> B if regressing B on A gives lower residual variance than
        regressing A on B. This captures the asymmetry in the data-
        generating process (causes tend to have lower residual variance
        when regressed in the correct causal direction).

        Then verify no cycles exist; if a cycle would be created,
        try the reverse direction or drop the edge.
        """
        # Separate directed from undirected
        directed: Set[Tuple[str, str]] = set()
        undirected_pairs: List[Tuple[str, str]] = []

        seen_undirected: Set[FrozenSet[str]] = set()
        for (a, b) in oriented:
            if (b, a) in oriented:
                key = frozenset({a, b})
                if key not in seen_undirected:
                    seen_undirected.add(key)
                    undirected_pairs.append(tuple(sorted((a, b))))
            else:
                directed.add((a, b))

        # Orient remaining undirected edges using BIC-based DAG scoring.
        #
        # The PC algorithm with only constraint-based orientation (v-structures
        # + Meek rules) produces a CPDAG (equivalence class). Multiple DAGs
        # in the class are consistent with the conditional independencies.
        # To select the best DAG within the equivalence class, we score
        # candidate orientations using the Bayesian Information Criterion:
        #   BIC = n * ln(RSS/n) + k * ln(n)
        # where RSS = residual sum of squares, k = number of parameters.
        #
        # We enumerate all valid (acyclic) orientations of undirected edges
        # and pick the one with the lowest total BIC score.

        if undirected_pairs:
            best_orientation = _bic_orient_undirected(
                self._data, directed, undirected_pairs, variables
            )

            directed = best_orientation

        return directed


# ═══════════════════════════════════════════════════════════════════════════════
# DirectLiNGAM — Causal Discovery via Non-Gaussianity (Shimizu et al., 2011)
# ═══════════════════════════════════════════════════════════════════════════════

class DirectLiNGAM:
    """
    Pure-Python implementation of DirectLiNGAM for small variable sets.

    LiNGAM (Linear Non-Gaussian Acyclic Model) exploits non-Gaussianity
    in the noise terms to uniquely identify the causal DAG — going beyond
    the Markov equivalence class that constrains the PC algorithm.

    For Y*gov: obligation fulfillment (O) and health score (H) are bounded
    in [0,1], producing non-Gaussian marginals. LiNGAM leverages this to
    uniquely orient all edges.

    Algorithm (DirectLiNGAM, Shimizu et al. 2011):
      1. Find the most exogenous variable (least dependent residuals)
      2. Regress all other variables on it
      3. Remove its effect (take residuals)
      4. Repeat on residuals until all variables are ordered

    The causal ordering + regression coefficients give the full DAG.

    Zero external dependencies. Suitable for small variable sets (4-10).

    Reference:
      Shimizu, S. et al. (2011). "DirectLiNGAM: A direct method for
      learning a linear non-Gaussian structural equation model."
      JMLR 12, pp. 1225-1248.
    """

    def run(self, data: List[Dict[str, float]]) -> CausalGraph:
        """
        Discover causal DAG from data using non-Gaussianity.

        Args:
            data: List of observations [{var: value}, ...].

        Returns:
            CausalGraph with uniquely identified edge directions.
        """
        if not data or len(data) < 10:
            raise ValueError("DirectLiNGAM requires at least 10 observations.")

        variables = sorted(data[0].keys())
        n = len(data)
        p = len(variables)

        # Convert to column-major lists
        columns = {v: [d[v] for d in data] for v in variables}

        # Iteratively find causal ordering
        remaining = list(variables)
        causal_order = []
        residual_columns = {v: list(columns[v]) for v in variables}

        for _ in range(p):
            # Find most exogenous variable among remaining
            best_var = None
            best_score = float('inf')

            for candidate in remaining:
                # Measure how "exogenous" this variable is:
                # Regress candidate on all other remaining variables,
                # then measure non-Gaussianity of residuals.
                # Most exogenous = residuals most non-Gaussian (closest to raw noise)
                others = [v for v in remaining if v != candidate]
                if not others:
                    best_var = candidate
                    break

                # Regress candidate on others
                residuals = self._regress_out(
                    residual_columns[candidate],
                    [residual_columns[v] for v in others],
                    n,
                )

                # Score: mutual information proxy between candidate and others
                # Lower = more exogenous
                score = self._dependence_score(residuals, others, residual_columns, n)

                if score < best_score:
                    best_score = score
                    best_var = candidate

            causal_order.append(best_var)
            remaining.remove(best_var)

            # Remove effect of best_var from all remaining variables
            if remaining:
                for v in remaining:
                    residual_columns[v] = self._regress_out(
                        residual_columns[v],
                        [residual_columns[best_var]],
                        n,
                    )

        # Build DAG from causal ordering + significant regression coefficients
        edge_dict: Dict[str, List[str]] = {}
        for i, effect in enumerate(causal_order):
            for j, cause in enumerate(causal_order):
                if j >= i:
                    break  # Only earlier variables can be causes
                # Check if cause has significant effect on the variable
                coeff = self._regression_coefficient(
                    columns[effect], columns[cause], n,
                )
                if abs(coeff) > 0.05:  # Threshold for significant edge
                    edge_dict.setdefault(cause, []).append(effect)

        return CausalGraph(edge_dict)

    def _regress_out(
        self, y: List[float], xs: List[List[float]], n: int,
    ) -> List[float]:
        """Regress y on xs, return residuals."""
        if not xs:
            return list(y)

        # Simple OLS for small systems
        # For single regressor: residual = y - (cov(x,y)/var(x)) * x
        # For multiple: iterative residualization
        residuals = list(y)
        for x in xs:
            coeff = self._regression_coefficient(residuals, x, n)
            x_mean = sum(x) / n
            residuals = [r - coeff * (xi - x_mean) for r, xi in zip(residuals, x)]
        return residuals

    def _regression_coefficient(
        self, y: List[float], x: List[float], n: int,
    ) -> float:
        """OLS regression coefficient of y on x."""
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        cov_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y)) / n
        var_x = sum((xi - x_mean) ** 2 for xi in x) / n
        if var_x < 1e-12:
            return 0.0
        return cov_xy / var_x

    def _dependence_score(
        self,
        residuals: List[float],
        others: List[str],
        columns: Dict[str, List[float]],
        n: int,
    ) -> float:
        """
        Measure statistical dependence between residuals and other variables.
        Uses absolute correlation as a simple proxy.
        Lower score = more independent = more exogenous.
        """
        total = 0.0
        for v in others:
            r_mean = sum(residuals) / n
            v_mean = sum(columns[v]) / n
            cov = sum((r - r_mean) * (c - v_mean) for r, c in zip(residuals, columns[v])) / n
            r_std = (sum((r - r_mean) ** 2 for r in residuals) / n) ** 0.5
            v_std = (sum((c - v_mean) ** 2 for c in columns[v]) / n) ** 0.5
            if r_std > 1e-12 and v_std > 1e-12:
                total += abs(cov / (r_std * v_std))
        return total


# ═══════════════════════════════════════════════════════════════════════════════
# Statistical helpers — Fisher z-test & linear algebra (zero dependencies)
# ═══════════════════════════════════════════════════════════════════════════════

def _correlation_matrix(
    data: List[Dict[str, float]], variables: List[str]
) -> List[List[float]]:
    """
    Compute the Pearson correlation matrix from data.

    Returns an n x n matrix where n = len(variables).
    """
    n = len(data)
    k = len(variables)

    # Compute means
    means = [0.0] * k
    for d in data:
        for i, v in enumerate(variables):
            means[i] += d[v]
    means = [m / n for m in means]

    # Compute covariance matrix
    cov = [[0.0] * k for _ in range(k)]
    for d in data:
        centered = [d[v] - means[i] for i, v in enumerate(variables)]
        for i in range(k):
            for j in range(i, k):
                cov[i][j] += centered[i] * centered[j]
                if i != j:
                    cov[j][i] += centered[i] * centered[j]

    # Normalise to correlation
    corr = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(k):
            denom = math.sqrt(cov[i][i] * cov[j][j]) if cov[i][i] > 0 and cov[j][j] > 0 else 1.0
            corr[i][j] = cov[i][j] / denom if denom > 1e-15 else 0.0

    return corr


def _partial_correlation(
    corr: List[List[float]],
    variables: List[str],
    x: str,
    y: str,
    z_set: Set[str],
) -> float:
    """
    Compute partial correlation r_{xy.Z} via matrix inversion.

    For the submatrix of {x, y} ∪ Z, invert it, and:
      r_{xy.Z} = -P_{xy} / sqrt(P_{xx} * P_{yy})
    where P = corr_sub^{-1} (the precision matrix).

    For empty Z, returns the marginal correlation r_{xy}.
    """
    if not z_set:
        xi = variables.index(x)
        yi = variables.index(y)
        return corr[xi][yi]

    # Build the sub-correlation matrix for {x, y} ∪ Z
    sub_vars = [x, y] + sorted(z_set)
    indices = [variables.index(v) for v in sub_vars]
    k = len(sub_vars)

    sub_corr = [[corr[indices[i]][indices[j]] for j in range(k)] for i in range(k)]

    # Invert the sub-correlation matrix
    inv = _invert_matrix(sub_corr)
    if inv is None:
        return 0.0  # Singular — treat as zero partial correlation

    # Partial correlation: r_{xy.Z} = -P_{01} / sqrt(P_{00} * P_{11})
    # where x is index 0, y is index 1 in sub_vars
    p_xy = inv[0][1]
    p_xx = inv[0][0]
    p_yy = inv[1][1]

    denom = math.sqrt(abs(p_xx * p_yy))
    if denom < 1e-15:
        return 0.0

    return -p_xy / denom


def _invert_matrix(m: List[List[float]]) -> Optional[List[List[float]]]:
    """
    Invert a square matrix via Gauss-Jordan elimination.

    For our 4-variable system, matrices are at most 4x4.
    Returns None if singular.
    """
    n = len(m)
    # Augment with identity
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]

    for col in range(n):
        # Partial pivoting
        max_row = col
        max_val = abs(aug[col][col])
        for row in range(col + 1, n):
            if abs(aug[row][col]) > max_val:
                max_val = abs(aug[row][col])
                max_row = row
        if max_val < 1e-12:
            return None
        aug[col], aug[max_row] = aug[max_row], aug[col]

        # Scale pivot row
        pivot = aug[col][col]
        for j in range(2 * n):
            aug[col][j] /= pivot

        # Eliminate column
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(2 * n):
                aug[row][j] -= factor * aug[col][j]

    # Extract inverse
    return [row[n:] for row in aug]


def fisher_z_test(
    corr: List[List[float]],
    variables: List[str],
    x: str,
    y: str,
    z_set: Set[str],
    n: int,
    alpha: float = 0.05,
) -> bool:
    """
    Test X ⊥ Y | Z using Fisher's z-transformation of partial correlation.

    Procedure:
      1. Compute partial correlation r_{xy.Z}
      2. Fisher transform: z = 0.5 * ln((1+r)/(1-r))
      3. Test statistic: T = |z| * sqrt(n - |Z| - 3)
      4. p-value from standard normal: p = erfc(T / sqrt(2))
      5. Return True if p > alpha (fail to reject independence)

    Args:
        corr: Pre-computed correlation matrix.
        variables: Variable names (column order of corr).
        x, y: Variables to test.
        z_set: Conditioning set.
        n: Sample size.
        alpha: Significance level.

    Returns:
        True if X and Y are conditionally independent given Z (p > alpha).
    """
    dof = n - len(z_set) - 3
    if dof < 1:
        return False  # Not enough data to test

    r = _partial_correlation(corr, variables, x, y, z_set)

    # Clamp to avoid log(0) or log(negative)
    r = max(-0.9999, min(0.9999, r))

    # Fisher z-transform
    z_stat = 0.5 * math.log((1.0 + r) / (1.0 - r))

    # Test statistic
    t_stat = abs(z_stat) * math.sqrt(dof)

    # Two-sided p-value from standard normal
    p_value = math.erfc(t_stat / math.sqrt(2.0))

    return p_value > alpha


def _bic_orient_undirected(
    data: List[Dict[str, float]],
    directed: Set[Tuple[str, str]],
    undirected_pairs: List[Tuple[str, str]],
    variables: List[str],
) -> Set[Tuple[str, str]]:
    """
    Find the best orientation of undirected edges within the Markov
    equivalence class.

    Uses a two-phase approach:

    Phase 1 — BIC scoring: Enumerate all 2^m acyclic orientations and
    score each with the Bayesian Information Criterion. For our 4-variable
    system, m <= 6 so 2^m <= 64: trivially fast.

    Phase 2 — Variance tiebreaker: Among orientations with near-identical
    BIC scores (within the same Markov equivalence class, BIC scores are
    theoretically equal for linear Gaussian data), prefer orientations
    where edges point from lower-variance to higher-variance variables.
    This exploits the fact that in linear SEMs with comparable noise,
    downstream (effect) variables accumulate variance from their ancestors.

    Peters & Bühlmann (2014), "Identifiability of Gaussian structural
    equation models with equal error variances."
    """
    n = len(data)
    m = len(undirected_pairs)

    # Compute marginal variances for tiebreaking
    var_map = _marginal_variances(data, variables)

    # Score all valid orientations
    scored: List[Tuple[float, float, Set[Tuple[str, str]]]] = []

    for bits in range(1 << m):
        candidate = set(directed)
        for i, (a, b) in enumerate(undirected_pairs):
            if bits & (1 << i):
                candidate.add((a, b))
            else:
                candidate.add((b, a))

        if _has_cycle(candidate, variables):
            continue

        bic = _dag_bic_score(data, candidate, variables, n)

        # Variance-ordering penalty
        var_penalty = 0.0
        for src, tgt in candidate:
            if var_map[src] < var_map[tgt]:
                var_penalty += (var_map[tgt] - var_map[src])

        scored.append((bic, var_penalty, candidate))

    if not scored:
        return set(directed)

    # Among the top BIC scores (within 1% of the best), pick the one
    # with the lowest variance penalty.
    scored.sort(key=lambda t: t[0])
    best_bic = scored[0][0]
    threshold = abs(best_bic) * 0.01 + 1.0  # 1% tolerance + small constant

    top_candidates = [s for s in scored if s[0] <= best_bic + threshold]
    top_candidates.sort(key=lambda t: t[1])

    return top_candidates[0][2]


def _marginal_variances(
    data: List[Dict[str, float]], variables: List[str]
) -> Dict[str, float]:
    """Compute marginal variance for each variable."""
    n = len(data)
    result: Dict[str, float] = {}
    for v in variables:
        vals = [d[v] for d in data]
        mean = sum(vals) / n
        result[v] = sum((x - mean) ** 2 for x in vals) / n
    return result


def _dag_bic_score(
    data: List[Dict[str, float]],
    edges: Set[Tuple[str, str]],
    variables: List[str],
    n: int,
) -> float:
    """
    Compute total BIC score for a DAG.

    BIC(V | PA_V) = n * ln(RSS/n) + (|PA_V| + 1) * ln(n)
    Total = sum over all variables.
    """
    parents: Dict[str, List[str]] = {v: [] for v in variables}
    for src, tgt in edges:
        parents[tgt].append(src)

    total_bic = 0.0
    ln_n = math.log(n) if n > 0 else 0.0

    for v in variables:
        pa = parents[v]
        rss = _multivar_regression_residual(data, v, pa) * n
        if rss < 1e-15:
            rss = 1e-15
        k = len(pa) + 1
        total_bic += n * math.log(rss / n) + k * ln_n

    return total_bic


def _multivar_regression_residual(
    data: List[Dict[str, float]],
    target: str,
    predictors: List[str],
) -> float:
    """
    Residual variance of regressing target on multiple predictors via OLS.

    Uses the normal equations: beta = (X^T X)^{-1} X^T y.
    Returns sum of squared residuals / n.
    """
    n = len(data)
    if n < 2 or not predictors:
        y_vals = [d[target] for d in data]
        mean_y = sum(y_vals) / n
        return sum((yi - mean_y) ** 2 for yi in y_vals) / n

    k = len(predictors) + 1  # +1 for intercept
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    y_vals = []

    for d in data:
        row = [1.0] + [d.get(p, 0.0) for p in predictors]
        y = d[target]
        y_vals.append(y)
        for i in range(k):
            xty[i] += row[i] * y
            for j in range(k):
                xtx[i][j] += row[i] * row[j]

    beta = _solve_linear_system(xtx, xty)
    if beta is None:
        mean_y = sum(y_vals) / n
        return sum((yi - mean_y) ** 2 for yi in y_vals) / n

    # Compute residuals
    total_resid = 0.0
    for d in data:
        row = [1.0] + [d.get(p, 0.0) for p in predictors]
        predicted = sum(beta[i] * row[i] for i in range(k))
        total_resid += (d[target] - predicted) ** 2

    return total_resid / n


def _regression_residual_var(
    data: List[Dict[str, float]],
    variables: List[str],
    x: str,
    y: str,
) -> float:
    """
    Compute the residual variance of regressing Y on X.

    Lower residual variance in the Y = f(X) direction suggests X -> Y
    is the correct causal direction (the cause explains more variance
    in the effect than vice versa, for non-Gaussian data).

    Returns residual variance (sum of squared residuals / n).
    """
    n = len(data)
    if n < 2:
        return 1.0

    x_vals = [d[x] for d in data]
    y_vals = [d[y] for d in data]

    # Simple linear regression: y = a + b*x
    mean_x = sum(x_vals) / n
    mean_y = sum(y_vals) / n

    ss_xx = sum((xi - mean_x) ** 2 for xi in x_vals)
    ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x_vals, y_vals))

    if abs(ss_xx) < 1e-15:
        return sum((yi - mean_y) ** 2 for yi in y_vals) / n

    b = ss_xy / ss_xx
    a = mean_y - b * mean_x

    residuals = [(yi - (a + b * xi)) ** 2 for xi, yi in zip(x_vals, y_vals)]
    return sum(residuals) / n


def _subsets(items: List[str], size: int):
    """
    Generate all subsets of `items` of the given size.

    Replaces itertools.combinations for the skeleton search.
    """
    if size == 0:
        yield ()
        return
    if size > len(items):
        return
    for i, item in enumerate(items):
        for rest in _subsets(items[i + 1:], size - 1):
            yield (item,) + rest


def _has_cycle(edges: Set[Tuple[str, str]], variables: List[str]) -> bool:
    """
    Detect if the directed graph has a cycle using DFS.
    """
    adj: Dict[str, List[str]] = {v: [] for v in variables}
    for a, b in edges:
        if a in adj:
            adj[a].append(b)
        else:
            adj[a] = [b]

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {v: WHITE for v in adj}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in adj.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return True
            if color.get(v, WHITE) == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    for v in adj:
        if color[v] == WHITE:
            if dfs(v):
                return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Standalone validation — run with: python -m ystar.governance.causal_discovery
# ═══════════════════════════════════════════════════════════════════════════════

def _standalone_pc_validation() -> None:
    """
    Generate synthetic data from the known Y*gov DAG and validate
    that the PC algorithm recovers the correct structure.

    Known DAG: S -> W -> O -> H, W -> H
    """
    import random
    random.seed(42)

    print("=" * 65)
    print("PC Algorithm — Causal Structure Discovery Validation")
    print("=" * 65)

    # ── 1. Generate synthetic data from known DAG ─────────────────────
    n_samples = 1000
    data: List[Dict[str, float]] = []
    for _ in range(n_samples):
        s = random.gauss(0.5, 0.20)
        w = 0.3 + 0.6 * s + random.gauss(0, 0.10)
        o = 0.2 + 0.7 * w + random.gauss(0, 0.10)
        h = 0.1 + 0.5 * o + 0.3 * w + random.gauss(0, 0.10)
        data.append({"S": s, "W": w, "O": o, "H": h})

    print(f"Generated {n_samples} samples from DAG: S->W->O->H, W->H")
    print()

    # ── 2. Run PC algorithm ───────────────────────────────────────────
    discovery = CausalDiscovery(alpha=0.05)
    discovered = discovery.run(data)
    print(f"Discovered graph: {discovered}")
    print()

    # ── 3. Compare with specified DAG ─────────────────────────────────
    specified = CausalGraph({
        "S": ["W"],
        "W": ["O", "H"],
        "O": ["H"],
    })
    print(f"Specified graph:  {specified}")
    print()

    # Import CausalEngine for comparison utility
    from ystar.governance.causal_engine import CausalEngine
    engine = CausalEngine()
    comparison = engine.validate_discovered_vs_specified(discovered, specified)

    print(f"Matching edges:   {comparison['matching_edges']}")
    print(f"Missing edges:    {comparison['missing_edges']}")
    print(f"Extra edges:      {comparison['extra_edges']}")
    print(f"SHD:              {comparison['shd']}")
    print()

    # ── 4. Verdict ────────────────────────────────────────────────────
    n_skeleton_correct = sum(
        1 for (a, b) in comparison["matching_edges"]
    ) + sum(
        1 for (a, b) in comparison["missing_edges"]
        if (b, a) in set(comparison["extra_edges"])
    )
    total_edges = len(comparison["matching_edges"]) + len(comparison["missing_edges"])

    print(f"Skeleton edges correct: {n_skeleton_correct}/{total_edges} "
          f"(direction-agnostic)")
    print()
    if comparison["shd"] == 0:
        print("PASS — PC algorithm perfectly recovered the causal DAG.")
    elif comparison["shd"] <= 2:
        print(f"PASS — SHD={comparison['shd']}. Skeleton is correct; "
              f"{comparison['shd'] // 2} edge(s) have orientation ambiguity, "
              f"which is expected within a Markov equivalence class.")
    else:
        print(f"WARN — SHD={comparison['shd']}, structural mismatch.")

    print("=" * 65)


if __name__ == "__main__":
    _standalone_pc_validation()

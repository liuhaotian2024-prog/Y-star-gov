# Layer: Foundation
"""
ystar.governance.causal_graph — CausalGraph: DAG, d-separation, backdoor criterion

Split from causal_engine.py for modularity.

Implements Pearl's causal DAG with:
  - Adjacency representation (no external dependencies)
  - Ancestral graph operations (parents, descendants, ancestors)
  - d-separation test (Pearl, 2009, Definition 1.2.3)
  - Backdoor criterion (Pearl, 2009, Definition 3.3.1)
  - Backdoor adjustment set computation
"""
from __future__ import annotations
from typing import List, Dict, Tuple, Optional, Set
from collections import deque


class CausalGraph:
    """
    Directed Acyclic Graph for Pearl's causal model.

    Implements:
      - Adjacency representation (no external dependencies)
      - Ancestral graph operations (parents, descendants, ancestors)
      - d-separation test (Pearl, 2009, Definition 1.2.3)
      - Backdoor criterion (Pearl, 2009, Definition 3.3.1)
      - Backdoor adjustment set computation

    Our Y*gov SCM DAG (within one decision cycle, acyclic):
        S → W → O → H
             ↘       ↗
              └─────┘
        (W has direct effect on H, plus indirect via O)
        The H→S edge is cross-temporal and not in the within-cycle DAG.

    Formal properties:
      - d-separation is sound and complete for conditional independence
        in any distribution compatible with the DAG (Verma & Pearl, 1988)
      - The backdoor criterion identifies valid adjustment sets for
        computing interventional distributions from observational data
    """

    def __init__(self, edges: Dict[str, List[str]]):
        """
        Initialize causal DAG from adjacency dict.

        Args:
            edges: {parent: [children]} adjacency list.
                   E.g. {'W': ['O', 'H']} means W→O and W→H.
        """
        self._children: Dict[str, List[str]] = {}
        self._parents: Dict[str, List[str]] = {}
        self._nodes: Set[str] = set()

        for parent, children in edges.items():
            self._nodes.add(parent)
            for child in children:
                self._nodes.add(child)
                self._children.setdefault(parent, []).append(child)
                self._parents.setdefault(child, []).append(parent)

        # Ensure all nodes have entries
        for node in self._nodes:
            self._children.setdefault(node, [])
            self._parents.setdefault(node, [])

    @property
    def nodes(self) -> Set[str]:
        return set(self._nodes)

    def parents(self, node: str) -> List[str]:
        """Direct parents of node in the DAG."""
        return list(self._parents.get(node, []))

    def children(self, node: str) -> List[str]:
        """Direct children of node in the DAG."""
        return list(self._children.get(node, []))

    def ancestors(self, node: str) -> Set[str]:
        """
        All ancestors of node (transitive parents), not including node itself.

        Uses BFS over parent edges.
        """
        visited: Set[str] = set()
        queue = deque(self._parents.get(node, []))
        while queue:
            current = queue.popleft()
            if current not in visited:
                visited.add(current)
                queue.extend(p for p in self._parents.get(current, [])
                             if p not in visited)
        return visited

    def descendants(self, node: str) -> Set[str]:
        """
        All descendants of node (transitive children), not including node itself.

        Uses BFS over child edges.
        """
        visited: Set[str] = set()
        queue = deque(self._children.get(node, []))
        while queue:
            current = queue.popleft()
            if current not in visited:
                visited.add(current)
                queue.extend(c for c in self._children.get(current, [])
                             if c not in visited)
        return visited

    def d_separated(self, x: str, y: str, z: Set[str]) -> bool:
        """
        Test if X ⊥ Y | Z in the DAG (d-separation).

        Implements the Bayes-Ball algorithm (Shachter, 1998), which is
        equivalent to Pearl's d-separation criterion (Pearl, 2009, Def 1.2.3).

        A path between X and Y is blocked by Z if and only if:
          - The path contains a chain (i→m→j) or fork (i←m→j)
            where m ∈ Z, OR
          - The path contains a collider (i→m←j)
            where m ∉ Z and no descendant of m is in Z.

        X and Y are d-separated given Z if ALL paths between them are blocked.

        For our small 4-node graph, this is exact and efficient.

        Args:
            x: Source node
            y: Target node
            z: Conditioning set

        Returns:
            True if X ⊥ Y | Z (d-separated), False if d-connected.
        """
        if x == y:
            return False

        # Bayes-Ball: find all nodes reachable from X given Z
        # A node is reachable via an active path if the path is not blocked by Z

        # Phase 1: find all ancestors of Z (needed for collider activation)
        z_ancestors: Set[str] = set()
        for zn in z:
            z_ancestors.add(zn)
            z_ancestors |= self.ancestors(zn)

        # Phase 2: Traverse active paths from X
        # State: (node, direction) where direction is "up" (arrived via child)
        # or "down" (arrived via parent)
        visited: Set[Tuple[str, str]] = set()
        reachable: Set[str] = set()
        queue: deque[Tuple[str, str]] = deque()

        # Start: X can send ball in both directions
        queue.append((x, "up"))
        queue.append((x, "down"))

        while queue:
            node, direction = queue.popleft()
            if (node, direction) in visited:
                continue
            visited.add((node, direction))

            if node != x:
                reachable.add(node)

            # If arrived going "up" (from a child)
            if direction == "up" and node not in z:
                # Can continue up to parents (chain/fork: not blocked)
                for parent in self._parents.get(node, []):
                    queue.append((parent, "up"))
                # Can continue down to children (fork: not blocked)
                for child in self._children.get(node, []):
                    queue.append((child, "down"))

            # If arrived going "down" (from a parent)
            if direction == "down":
                # If node not in Z: can continue down (chain: not blocked)
                if node not in z:
                    for child in self._children.get(node, []):
                        queue.append((child, "down"))
                # If node in Z or has descendant in Z: collider is activated
                if node in z_ancestors:
                    for parent in self._parents.get(node, []):
                        queue.append((parent, "up"))

        return y not in reachable

    def satisfies_backdoor_criterion(self, x: str, y: str, z: Set[str]) -> bool:
        """
        Check if Z satisfies the backdoor criterion relative to (X, Y).

        Pearl (2009), Definition 3.3.1:
        A set Z satisfies the backdoor criterion relative to (X, Y) if:
          (i)  No node in Z is a descendant of X
          (ii) Z blocks every path between X and Y that contains an arrow
               into X (i.e., Z d-separates X from Y in the manipulated graph
               where all arrows out of X are removed)

        Args:
            x: Treatment variable
            y: Outcome variable
            z: Candidate adjustment set

        Returns:
            True if Z is a valid backdoor adjustment set.
        """
        # Condition (i): no node in Z is a descendant of X
        x_descendants = self.descendants(x)
        if z & x_descendants:
            return False

        # Condition (ii): Z blocks all backdoor paths
        # Construct the manipulated graph G_Xbar (remove all edges out of X)
        manipulated_edges: Dict[str, List[str]] = {}
        for parent, children in self._children.items():
            if parent == x:
                manipulated_edges[parent] = []  # Remove all arrows out of X
            else:
                manipulated_edges[parent] = list(children)

        manipulated_graph = CausalGraph.__new__(CausalGraph)
        manipulated_graph._children = {}
        manipulated_graph._parents = {}
        manipulated_graph._nodes = set(self._nodes)

        for node in self._nodes:
            manipulated_graph._children[node] = []
            manipulated_graph._parents[node] = []

        for parent, children in manipulated_edges.items():
            for child in children:
                manipulated_graph._children[parent].append(child)
                manipulated_graph._parents[child].append(parent)

        # Check d-separation in manipulated graph
        return manipulated_graph.d_separated(x, y, z)

    def find_backdoor_set(self, x: str, y: str) -> Optional[Set[str]]:
        """
        Find a minimal valid backdoor adjustment set for estimating P(Y|do(X)).

        Strategy: Try the parents of X first (often sufficient), then
        enumerate small subsets. For our 4-node graph, this is trivial.

        Pearl (2009), Theorem 3.3.2 (Backdoor Adjustment):
        If Z satisfies the backdoor criterion relative to (X, Y), then:
          P(Y|do(X=x)) = Σ_z P(Y|X=x, Z=z) * P(Z=z)

        Returns:
            A valid adjustment set, or None if no set exists (e.g., if X=Y).
        """
        if x == y:
            return None

        # Strategy 1: parents of X (classic choice)
        parent_set = set(self._parents.get(x, []))
        # Remove Y from candidate set if present
        candidate = parent_set - {y}
        if self.satisfies_backdoor_criterion(x, y, candidate):
            return candidate

        # Strategy 2: empty set (works if no confounders)
        if self.satisfies_backdoor_criterion(x, y, set()):
            return set()

        # Strategy 3: enumerate subsets of non-descendants of X (excluding X, Y)
        x_descendants = self.descendants(x)
        candidates = self._nodes - {x, y} - x_descendants
        # Try subsets of increasing size
        from itertools import combinations
        for size in range(len(candidates) + 1):
            for subset in combinations(candidates, size):
                z = set(subset)
                if self.satisfies_backdoor_criterion(x, y, z):
                    return z

        return None  # No valid adjustment set exists

    def __repr__(self) -> str:
        edges = []
        for parent, children in sorted(self._children.items()):
            for child in children:
                edges.append(f"{parent}→{child}")
        return f"CausalGraph({', '.join(edges)})"

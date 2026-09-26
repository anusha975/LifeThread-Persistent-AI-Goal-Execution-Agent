import logging
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import status

from app.core.exceptions import LifeThreadException

logger = logging.getLogger("lifethread.services.dependency_graph")


class DependencyGraphService:
    """Service to build, validate, and analyze directed task dependency graphs."""

    @classmethod
    def detect_cycles(
        cls,
        task_ids: list[uuid.UUID],
        dependencies: list[tuple[uuid.UUID, uuid.UUID]],
    ) -> list[uuid.UUID] | None:
        """Detect circular dependencies using 3-color DFS.

        Edges in dependencies are (prerequisite_id, dependent_id), meaning:
        prerequisite_id -> dependent_id (prerequisite must finish before dependent can start).

        Returns:
            list[uuid.UUID] of task IDs in the cycle if detected, or None if the graph is a valid DAG.
        """
        adjacency: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for prereq_id, task_id in dependencies:
            if prereq_id == task_id:
                # Direct self-dependency cycle
                return [task_id, task_id]
            adjacency[prereq_id].append(task_id)

        # 0: UNVISITED, 1: VISITING (in recursion stack), 2: VISITED
        state: dict[uuid.UUID, int] = dict.fromkeys(task_ids, 0)
        parent: dict[uuid.UUID, uuid.UUID | None] = {}
        cycle_path: list[uuid.UUID] = []

        def dfs(node: uuid.UUID) -> bool:
            state[node] = 1
            for neighbor in adjacency[node]:
                if state.get(neighbor, 0) == 1:
                    # Found cycle back-edge
                    cycle_path.append(neighbor)
                    curr = node
                    while curr is not None and curr != neighbor:
                        cycle_path.append(curr)
                        curr = parent.get(curr)
                    cycle_path.append(neighbor)
                    cycle_path.reverse()
                    return True
                if state.get(neighbor, 0) == 0:
                    parent[neighbor] = node
                    if dfs(neighbor):
                        return True
            state[node] = 2
            return False

        for t_id in task_ids:
            if state[t_id] == 0:
                parent[t_id] = None
                if dfs(t_id):
                    return cycle_path

        return None

    @classmethod
    def topological_sort(
        cls,
        task_ids: list[uuid.UUID],
        dependencies: list[tuple[uuid.UUID, uuid.UUID]],
    ) -> list[uuid.UUID]:
        """Compute a valid linear topological execution order for tasks using Kahn's algorithm.

        Dependencies are (prerequisite_id, dependent_id).

        Raises:
            LifeThreadException: 422 with CIRCULAR_DEPENDENCY_DETECTED if a cycle exists.
        """
        cycle = cls.detect_cycles(task_ids, dependencies)
        if cycle:
            cycle_str = " -> ".join(str(cid) for cid in cycle)
            logger.warning(f"Circular dependency detected: {cycle_str}")
            raise LifeThreadException(
                message=f"Circular dependency detected in tasks: {cycle_str}",
                code="CIRCULAR_DEPENDENCY_DETECTED",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"cycle": [str(c) for c in cycle]},
            )

        in_degree: dict[uuid.UUID, int] = dict.fromkeys(task_ids, 0)
        adjacency: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)

        for prereq_id, task_id in dependencies:
            if prereq_id in in_degree and task_id in in_degree:
                adjacency[prereq_id].append(task_id)
                in_degree[task_id] += 1

        queue: deque[uuid.UUID] = deque([t_id for t_id in task_ids if in_degree[t_id] == 0])
        order: list[uuid.UUID] = []

        while queue:
            curr = queue.popleft()
            order.append(curr)
            for neighbor in adjacency[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(task_ids):
            # Fallback sanity check in case disconnected cycle exists
            raise LifeThreadException(
                message="Graph contains unresolved cyclical dependencies",
                code="CIRCULAR_DEPENDENCY_DETECTED",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return order

    @classmethod
    def build_graph_structure(
        cls,
        tasks: list[Any],
        dependencies: list[Any],
    ) -> dict[str, Any]:
        """Utility to construct an adjacency matrix and degree mapping for graph serialization."""
        task_ids = [t.id for t in tasks]
        dep_tuples = [(d.depends_on_task_id, d.task_id) for d in dependencies]
        topological_order = cls.topological_sort(task_ids, dep_tuples)

        return {
            "node_count": len(tasks),
            "edge_count": len(dependencies),
            "topological_order": topological_order,
        }

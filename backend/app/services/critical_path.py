import logging
import uuid
from collections import defaultdict
from typing import Any

from app.services.dependency_graph import DependencyGraphService

logger = logging.getLogger("lifethread.services.critical_path")


class CriticalPathService:
    """Calculates project duration and identifies the Critical Path using the Critical Path Method (CPM)."""

    @classmethod
    def calculate_critical_path(
        cls,
        tasks: list[Any],
        dependencies: list[tuple[uuid.UUID, uuid.UUID]],
        topological_order: list[uuid.UUID] | None = None,
    ) -> tuple[list[uuid.UUID], int, dict[uuid.UUID, dict[str, int]]]:
        """Compute the Critical Path for a collection of tasks and directed dependencies.

        Args:
            tasks: List of task models/objects with 'id' and 'estimated_minutes' attributes.
            dependencies: List of (prerequisite_id, task_id) tuples.
            topological_order: Optional pre-computed topological sort; calculated if not passed.

        Returns:
            A tuple of:
            - critical_path_task_ids: list[uuid.UUID] of tasks on the critical bottleneck path.
            - total_duration_minutes: int total estimated duration to complete all tasks.
            - task_schedules: dict mapping task_id to {es, ef, ls, lf, slack, duration}.
        """
        task_ids = [t.id for t in tasks]
        durations: dict[uuid.UUID, int] = {
            t.id: max(1, getattr(t, "estimated_minutes", 60)) for t in tasks
        }

        if not task_ids:
            return [], 0, {}

        # Ensure valid topological order (validates DAG)
        order = topological_order or DependencyGraphService.topological_sort(task_ids, dependencies)

        # Build predecessor and successor lookups
        predecessors: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        successors: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for prereq_id, task_id in dependencies:
            if prereq_id in durations and task_id in durations:
                predecessors[task_id].append(prereq_id)
                successors[prereq_id].append(task_id)

        # Forward Pass: Compute Early Start (ES) and Early Finish (EF)
        es: dict[uuid.UUID, int] = {}
        ef: dict[uuid.UUID, int] = {}
        for node in order:
            preds = predecessors[node]
            node_es = max([ef[p] for p in preds], default=0)
            es[node] = node_es
            ef[node] = node_es + durations[node]

        total_duration = max(ef.values(), default=0)

        # Backward Pass: Compute Late Finish (LF) and Late Start (LS)
        lf: dict[uuid.UUID, int] = {}
        ls: dict[uuid.UUID, int] = {}
        for node in reversed(order):
            succs = successors[node]
            node_lf = min([ls[s] for s in succs], default=total_duration)
            lf[node] = node_lf
            ls[node] = node_lf - durations[node]

        # Calculate Slack (Total Float) and schedules
        schedules: dict[uuid.UUID, dict[str, int]] = {}
        critical_nodes: set[uuid.UUID] = set()

        for node in order:
            slack = ls[node] - es[node]
            schedules[node] = {
                "duration": durations[node],
                "es": es[node],
                "ef": ef[node],
                "ls": ls[node],
                "lf": lf[node],
                "slack": slack,
            }
            if slack == 0:
                critical_nodes.add(node)

        # Construct connected critical path sequence
        # Start at a critical node with ES == 0
        critical_path: list[uuid.UUID] = []
        curr_candidates = [n for n in order if n in critical_nodes and es[n] == 0]

        if curr_candidates:
            # Pick initial critical node with longest duration if multiple start at 0
            curr = max(curr_candidates, key=lambda c: durations[c])
            critical_path.append(curr)

            # Trace forward along critical edges where ES[succ] == EF[curr]
            while True:
                next_candidates = [
                    s for s in successors[curr] if s in critical_nodes and es[s] == ef[curr]
                ]
                if not next_candidates:
                    break
                curr = max(next_candidates, key=lambda c: durations[c])
                critical_path.append(curr)
        else:
            # If no root node has ES == 0 (e.g. single task or disconnected), all zero-slack nodes
            critical_path = [n for n in order if n in critical_nodes]

        return critical_path, total_duration, schedules

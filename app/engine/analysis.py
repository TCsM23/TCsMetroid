"""Map analysis built on graph algorithms.

- ability_dependencies + topological_sort (Kahn's algorithm)
- item_criticality       (remove one item, re-check)
- connected_regions      (union-find)
- strongly_connected     (Tarjan's algorithm)
- danger_zones           (forward + reverse search over states)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .checker import check, reachable_with
from .graph import WorldGraph
from .structures import Queue, Stack, UnionFind

BOSS = "BOSS"


# ---------------------------------------------------------------- dependencies + Kahn
@dataclass
class Dependencies:
    nodes: list[str]
    edges: list[tuple[str, str]]   # (prerequisite, dependent)


def ability_dependencies(graph: WorldGraph, placement: dict[str, str]) -> Dependencies:
    """Edge A -> B when B's room can't be reached without A, even holding every
    other ability. An item can never be used to reach its own slot, so a slot that
    needs its own item becomes a self-loop (a guaranteed cycle)."""
    prog = [(slot, item) for slot, item in placement.items() if graph.item_bit(item)]
    everything = 0
    for _, item in prog:
        everything |= graph.item_bit(item)
    targets = [(item, slot) for slot, item in prog] + [(BOSS, graph.boss)]
    edges: list[tuple[str, str]] = []
    for node, room in targets:
        own = everything if node == BOSS else everything & ~graph.item_bit(node)
        if room not in reachable_with(graph, own):
            edges.append((node, node))
            continue
        for _, other in prog:
            if other != node and room not in reachable_with(graph, own & ~graph.item_bit(other)):
                edges.append((other, node))
    return Dependencies([item for _, item in prog] + [BOSS], edges)


@dataclass
class TopoResult:
    order: list[str]
    cycle: list[str]
    log: list[dict]
    in_degree: dict[str, int]


def topological_sort(nodes: list[str], edges: list[tuple[str, str]]) -> TopoResult:
    """Kahn's algorithm. Nodes left over at the end are stuck behind a cycle."""
    in_degree = {n: 0 for n in nodes}
    out: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        in_degree[b] += 1
        out[a].append(b)
    start_degree = dict(in_degree)
    queue: Queue[str] = Queue()
    for n in nodes:
        if in_degree[n] == 0:
            queue.enqueue(n)
    order, log = [], []
    while not queue.is_empty():
        n = queue.dequeue()
        order.append(n)
        freed = []
        for m in out[n]:
            in_degree[m] -= 1
            if in_degree[m] == 0:
                queue.enqueue(m)
                freed.append(m)
        log.append({"take": n, "freed": freed, "queue": list(queue)})
    return TopoResult(order, [n for n in nodes if n not in order], log, start_degree)


# ---------------------------------------------------------------- criticality
def item_criticality(graph: WorldGraph, placement: dict[str, str]) -> dict[str, bool]:
    """For each placed item: True if the map becomes unbeatable without it."""
    result = {}
    for slot, item in placement.items():
        without = {k: v for k, v in placement.items() if k != slot}
        result[slot] = not check(graph, without).beatable
    return result


# ---------------------------------------------------------------- union-find regions
@dataclass
class Regions:
    groups: list[list[str]]
    unions: list[tuple[str, str]]
    find_calls: int
    max_rank: int


def connected_regions(graph: WorldGraph, mask: int) -> Regions:
    """Rooms that can walk to each other freely with `mask`. One-way drops are skipped
    because they can't be crossed both ways."""
    uf = UnionFind(graph.rooms)
    unions = []
    for g in graph.gates:
        if not g.one_way and g.passable(mask) and uf.union(g.a, g.b):
            unions.append((g.a, g.b))
    groups = uf.groups()
    return Regions(groups, unions, uf.find_calls, max(uf.rank.values()))


# ---------------------------------------------------------------- Tarjan SCC
def strongly_connected(graph: WorldGraph, mask: int | None = None) -> list[list[str]]:
    """Tarjan's algorithm, written iteratively with an explicit stack of frames.
    Rooms in the same component can all reach each other with `mask` (default: every ability)."""
    mask = graph.all_mask if mask is None else mask
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    tarjan_stack: Stack[str] = Stack()
    components: list[list[str]] = []
    counter = 0

    for root in graph.rooms:
        if root in index:
            continue
        work = [(root, iter([to for to, _ in graph.neighbors(root, mask)]))]
        index[root] = low[root] = counter
        counter += 1
        tarjan_stack.push(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    tarjan_stack.push(child)
                    on_stack.add(child)
                    work.append((child, iter([to for to, _ in graph.neighbors(child, mask)])))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = tarjan_stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                components.append(sorted(comp, key=list(graph.rooms).index))
    return components


# ---------------------------------------------------------------- danger zones
@dataclass
class DangerZones:
    reachable_states: int
    dead_states: list[tuple[str, int]] = field(default_factory=list)

    @property
    def rooms(self) -> list[str]:
        seen = []
        for room, _ in self.dead_states:
            if room not in seen:
                seen.append(room)
        return seen


def danger_zones(graph: WorldGraph, placement: dict[str, str]) -> DangerZones:
    """States the player can reach but never finish from: a soft-lock pocket.

    1. Forward BFS over (room, abilities) states from the start, recording edges.
    2. Reverse BFS from every boss state.
    3. Reachable but not reverse-reachable = dead.
    """
    start = (graph.start, graph.item_bit(placement.get(graph.start)))
    reverse: dict[tuple, list[tuple]] = {start: []}
    queue: Queue[tuple] = Queue()
    queue.enqueue(start)
    while not queue.is_empty():
        room, mask = state = queue.dequeue()
        for nxt, _ in graph.neighbors(room, mask):
            ns = (nxt, mask | graph.item_bit(placement.get(nxt)))
            if ns not in reverse:
                reverse[ns] = []
                queue.enqueue(ns)
            reverse[ns].append(state)

    can_finish = {s for s in reverse if s[0] == graph.boss}
    back: Queue[tuple] = Queue()
    for s in can_finish:
        back.enqueue(s)
    while not back.is_empty():
        s = back.dequeue()
        for prev in reverse[s]:
            if prev not in can_finish:
                can_finish.add(prev)
                back.enqueue(prev)

    order = list(graph.rooms)
    dead = sorted((s for s in reverse if s not in can_finish), key=lambda s: (order.index(s[0]), s[1]))
    return DangerZones(len(reverse), dead)

"""Route finding over the state space (room, abilities held).

A plain room-to-room search is not enough: which edges exist depends on what the
player has picked up, so the same room can be visited several times in different
states. Every algorithm here searches states, not rooms.

    BFS       Queue    fewest moves (ignores room times)
    DFS       Stack    some route, no promise it is short
    Dijkstra  MinHeap  fastest route in seconds
    A*        MinHeap  fastest route, guided by an admissible heuristic
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .graph import WorldGraph
from .structures import MinHeap, Queue, Stack

ALGORITHMS = {
    "bfs": ("BFS", "Queue"),
    "dfs": ("DFS", "Stack"),
    "dijkstra": ("Dijkstra", "Min-heap · g"),
    "astar": ("A*", "Min-heap · g+h"),
}

State = tuple[str, int]


@dataclass
class Step:
    room: str
    mask: int
    seconds: int
    gate_index: int | None
    picked: str | None   # item collected on entering this room, if it was new


@dataclass
class SearchResult:
    algorithm: str
    found: bool
    steps: list[Step] = field(default_factory=list)
    expanded: int = 0
    max_frontier: int = 0
    states_seen: int = 0

    @property
    def moves(self) -> int | None:
        return len(self.steps) - 1 if self.found else None

    @property
    def seconds(self) -> int | None:
        return self.steps[-1].seconds if self.found else None

    @property
    def label(self) -> str:
        return ALGORITHMS[self.algorithm][0]

    @property
    def structure(self) -> str:
        return ALGORITHMS[self.algorithm][1]


def relaxed_distances(graph: WorldGraph) -> dict[str, int]:
    """Fastest time from each room to the boss if every gate were open.

    This is a "relaxed problem": dropping constraints can only make the trip
    shorter, so it never overestimates, which keeps A* optimal. Computed with
    Dijkstra on the reversed graph, starting at the boss.
    """
    reverse: dict[str, list[str]] = {k: [] for k in graph.rooms}
    for g in graph.gates:
        reverse[g.b].append(g.a)
        if not g.one_way:
            reverse[g.a].append(g.b)
    dist = {graph.boss: 0}
    heap: MinHeap[str] = MinHeap()
    heap.push(0, graph.boss)
    while not heap.is_empty():
        d, room = heap.pop()
        if d > dist[room]:
            continue
        for prev in reverse[room]:
            nd = d + graph.seconds(room)
            if nd < dist.get(prev, float("inf")):
                dist[prev] = nd
                heap.push(nd, prev)
    return dist


def find_route(graph: WorldGraph, placement: dict[str, str], algorithm: str = "dijkstra") -> SearchResult:
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm {algorithm!r}")
    weighted = algorithm in ("dijkstra", "astar")
    h = relaxed_distances(graph) if algorithm == "astar" else {}
    heuristic = (lambda r: h.get(r, 10**9)) if algorithm == "astar" else (lambda r: 0)

    start: State = (graph.start, graph.item_bit(placement.get(graph.start)))
    # visited/best: state -> (seconds, parent_state, gate_index). Parent pointers form a linked list.
    best: dict[State, tuple[int, State | None, int | None]] = {start: (0, None, None)}

    if algorithm == "bfs":
        frontier = Queue()
        push = lambda s, g: frontier.enqueue((s, g))
        pop = frontier.dequeue
    elif algorithm == "dfs":
        frontier = Stack()
        push = lambda s, g: frontier.push((s, g))
        pop = frontier.pop
    else:
        frontier = MinHeap()
        push = lambda s, g: frontier.push(g + heuristic(s[0]), (s, g))
        pop = lambda: frontier.pop()[1]

    push(start, 0)
    result = SearchResult(algorithm, False, max_frontier=1)

    while len(frontier):
        state, g = pop()
        if weighted and g > best[state][0]:
            continue  # stale heap entry: a faster way to this state was found later
        result.expanded += 1
        room, mask = state
        if room == graph.boss:
            result.found = True
            result.steps = _reconstruct(state, best, placement)
            break
        for nxt, gate_index in graph.neighbors(room, mask):
            new_state = (nxt, mask | graph.item_bit(placement.get(nxt)))
            ng = g + graph.seconds(nxt)
            if weighted:
                if new_state in best and best[new_state][0] <= ng:
                    continue
            elif new_state in best:
                continue
            best[new_state] = (ng, state, gate_index)
            push(new_state, ng)
        result.max_frontier = max(result.max_frontier, len(frontier))

    result.states_seen = len(best)
    return result


def _reconstruct(state: State, best, placement) -> list[Step]:
    steps: list[Step] = []
    cur: State | None = state
    while cur is not None:
        seconds, parent, gate_index = best[cur]
        picked = None
        if parent is not None and parent[1] != cur[1]:
            picked = placement.get(cur[0])
        steps.append(Step(cur[0], cur[1], seconds, gate_index, picked))
        cur = parent
    steps.reverse()
    return steps


def compare_all(graph: WorldGraph, placement: dict[str, str]) -> list[SearchResult]:
    return [find_route(graph, placement, a) for a in ALGORITHMS]

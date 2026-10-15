"""Beatability checker: a fixed-point loop over BFS.

1. BFS from the start using only gates the current abilities open.
2. Collect every ability sitting in a reached room.
3. Repeat until a pass finds nothing new. Each pass is one "sphere".
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .graph import WorldGraph
from .structures import Queue


def reachable_with(graph: WorldGraph, mask: int) -> set[str]:
    seen = {graph.start}
    queue: Queue[str] = Queue()
    queue.enqueue(graph.start)
    while not queue.is_empty():
        room = queue.dequeue()
        for nxt, _ in graph.neighbors(room, mask):
            if nxt not in seen:
                seen.add(nxt)
                queue.enqueue(nxt)
    return seen


@dataclass
class Sphere:
    index: int
    rooms: list[str]
    items: list[str]


@dataclass
class BlockedGate:
    from_room: str
    to_room: str
    rule: str
    gate_index: int


@dataclass
class CheckResult:
    beatable: bool
    reachable: set[str]
    abilities: int
    spheres: list[Sphere] = field(default_factory=list)
    blocked: list[BlockedGate] = field(default_factory=list)

    @property
    def sphere_of(self) -> dict[str, int]:
        return {room: s.index for s in self.spheres for room in s.rooms}


def check(graph: WorldGraph, placement: dict[str, str], base_mask: int = 0) -> CheckResult:
    have = base_mask
    spheres: list[Sphere] = []
    seen_rooms: set[str] = set()
    while True:
        reached = reachable_with(graph, have)
        fresh = [r for r in graph.rooms if r in reached and r not in seen_rooms]
        seen_rooms |= set(fresh)
        if fresh:
            spheres.append(Sphere(len(spheres) + 1, fresh, [placement[r] for r in fresh if placement.get(r)]))
        new_have = have
        for room in reached:
            new_have |= graph.item_bit(placement.get(room))
        if new_have == have:
            break
        have = new_have

    blocked = []
    for room in reached:
        for edge in graph.adj[room]:
            if edge.to not in reached:
                g = graph.gates[edge.gate_index]
                blocked.append(BlockedGate(room, edge.to, g.rule, edge.gate_index))
    return CheckResult(graph.boss in reached, reached, have, spheres, blocked)

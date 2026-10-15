"""The world graph: rooms are nodes, gates are edges guarded by a rule."""
from __future__ import annotations

from dataclasses import dataclass, field

from .powerups import DEFAULT_POWERUPS, PowerUpSet
from .rules import Node, parse


@dataclass
class Room:
    key: str
    name: str
    x: int
    y: int
    seconds: int = 10
    item: str | None = None   # vanilla item in this room, if it is an item slot


@dataclass
class Gate:
    a: str
    b: str
    rule: str = ""
    one_way: bool = False
    powerups: PowerUpSet = field(default=DEFAULT_POWERUPS, repr=False, compare=False)
    node: Node = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.rule = (self.rule or "").strip()
        self.node = parse(self.rule, self.powerups)   # raises RuleError on bad syntax

    def passable(self, mask: int) -> bool:
        return self.node.evaluate(mask)


@dataclass(frozen=True)
class Edge:
    to: str
    gate_index: int


class WorldGraph:
    """Adjacency-list graph. A two-way gate adds an edge in both directions."""

    def __init__(self, rooms: list[Room], gates: list[Gate], start: str, boss: str,
                 powerups: PowerUpSet = DEFAULT_POWERUPS):
        self.powerups = powerups
        self.rooms: dict[str, Room] = {}
        for room in rooms:
            if room.key in self.rooms:
                raise ValueError(f"Duplicate room key {room.key!r}")
            if room.item and room.item not in powerups:
                raise ValueError(f"Unknown power-up {room.item!r} in room {room.key!r}")
            if room.seconds < 1:
                raise ValueError(f"Room {room.key!r} must take at least 1 second")
            self.rooms[room.key] = room
        for key in (start, boss):
            if key not in self.rooms:
                raise ValueError(f"Start/boss room {key!r} does not exist")
        self.start, self.boss = start, boss
        self.gates = gates
        self.adj: dict[str, list[Edge]] = {k: [] for k in self.rooms}
        for i, g in enumerate(gates):
            for key in (g.a, g.b):
                if key not in self.rooms:
                    raise ValueError(f"Gate {i + 1} points at unknown room {key!r}")
            self.adj[g.a].append(Edge(g.b, i))
            if not g.one_way:
                self.adj[g.b].append(Edge(g.a, i))

    # ---- item helpers
    @property
    def slots(self) -> list[str]:
        return [k for k, r in self.rooms.items() if r.item]

    def vanilla_placement(self) -> dict[str, str]:
        return {k: r.item for k, r in self.rooms.items() if r.item}

    def item_pool(self) -> list[str]:
        return [r.item for r in self.rooms.values() if r.item]

    def item_bit(self, item: str | None) -> int:
        """The ability bit an item gives, or 0 for collectibles and empty slots."""
        return self.powerups.bit(item)

    @property
    def all_mask(self) -> int:
        return self.powerups.all_mask

    # ---- traversal helpers
    def neighbors(self, key: str, mask: int):
        """Yield (next_room, gate_index) for every edge the mask can open."""
        for edge in self.adj[key]:
            if self.gates[edge.gate_index].passable(mask):
                yield edge.to, edge.gate_index

    def seconds(self, key: str) -> int:
        return self.rooms[key].seconds

    # ---- conversion
    @classmethod
    def from_dict(cls, data: dict) -> "WorldGraph":
        powerups = PowerUpSet.from_list(data.get("powerups"))
        rooms = [
            Room(r["key"], r.get("name") or r["key"], int(r["x"]), int(r["y"]),
                 int(r.get("seconds", 10)), r.get("item") or None)
            for r in data["rooms"]
        ]
        gates = [Gate(g["a"], g["b"], g.get("rule", ""), bool(g.get("one_way", False)), powerups)
                 for g in data["gates"]]
        return cls(rooms, gates, data["start"], data["boss"], powerups)

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "boss": self.boss,
            "rooms": [dict(key=r.key, name=r.name, x=r.x, y=r.y, seconds=r.seconds, item=r.item)
                      for r in self.rooms.values()],
            "gates": [dict(a=g.a, b=g.b, rule=g.rule, one_way=g.one_way) for g in self.gates],
            "powerups": self.powerups.to_list(),
        }

    def to_networkx(self, mask: int | None = None):
        """Room-level DiGraph of edges open under `mask` (default: every ability). Edge weight = seconds to enter target."""
        import networkx as nx

        mask = self.all_mask if mask is None else mask
        g = nx.DiGraph()
        g.add_nodes_from(self.rooms)
        for key in self.rooms:
            for to, _ in self.neighbors(key, mask):
                g.add_edge(key, to, weight=self.seconds(to))
        return g

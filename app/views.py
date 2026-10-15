"""View models: turn engine results into plain dicts the Jinja templates can draw."""
from __future__ import annotations

import math

from .engine.graph import WorldGraph
from .engine.rules import Ability, And, Node, Open

CELL_X, CELL_Y = 150, 104
ROOM_W, ROOM_H = 108, 58
PAD = 14
REGION_COLORS = ["#2f6fd6", "#a8508f", "#3f8f5a", "#a8792f", "#6a55b8", "#2f8f95", "#9a4a4a", "#5d7a2f"]


def map_view(graph: WorldGraph, placement: dict[str, str], *, reachable=None, sphere_of=None,
             route=None, region_of=None, danger=None, open_mask=None, highlight_gate=None,
             blocked=None) -> dict:
    xs = [r.x for r in graph.rooms.values()]
    ys = [r.y for r in graph.rooms.values()]
    min_x, min_y = min(xs), min(ys)
    cols, rows = max(xs) - min_x + 1, max(ys) - min_y + 1

    def cx(key):
        return (graph.rooms[key].x - min_x) * CELL_X + CELL_X / 2 + PAD

    def cy(key):
        return (graph.rooms[key].y - min_y) * CELL_Y + CELL_Y / 2 + PAD

    route_gates, step_numbers = set(), {}
    if route is not None and route.found:
        for i, step in enumerate(route.steps):
            if step.gate_index is not None:
                route_gates.add(step.gate_index)
            step_numbers.setdefault(step.room, []).append(i)
    blocked_gates = {b.gate_index for b in (blocked or [])}

    gates = []
    for i, g in enumerate(graph.gates):
        x1, y1, x2, y2 = cx(g.a), cy(g.a), cx(g.b), cy(g.b)
        label = g.node.label() or "·"
        kind = "open" if isinstance(g.node, Open) else ("single" if isinstance(g.node, Ability) else "compound")
        classes = ["mapsvg-edge-line"]
        if g.one_way:
            classes.append("is-oneway")
        if i in route_gates:
            classes.append("is-route")
        if i in blocked_gates:
            classes.append("is-blocked")
        if open_mask is not None and not g.passable(open_mask):
            classes.append("is-faded")
        if highlight_gate == i:
            classes.append("is-selected")
        arrow = None
        if g.one_way:
            t = 0.72
            arrow = dict(x=x1 + (x2 - x1) * t, y=y1 + (y2 - y1) * t,
                         angle=math.degrees(math.atan2(y2 - y1, x2 - x1)))
        gates.append(dict(index=i, x1=x1, y1=y1, x2=x2, y2=y2, mx=(x1 + x2) / 2, my=(y1 + y2) / 2,
                          label=label, kind=kind, ability=g.node.name if kind == "single" else None,
                          width=max(22, len(label) * 6.8 + 12), classes=" ".join(classes), arrow=arrow,
                          rule=g.rule, a=g.a, b=g.b, one_way=g.one_way))

    danger_rooms = set(danger or [])
    rooms = []
    for key, r in graph.rooms.items():
        classes = ["mapsvg-room-box"]
        if reachable is not None and key not in reachable:
            classes.append("is-dead")
        if route is not None and key in step_numbers:
            classes.append("is-on-route")
        if key in danger_rooms:
            classes.append("is-danger")
        if key == graph.start:
            classes.append("is-start")
        if key == graph.boss:
            classes.append("is-boss")
        tag = "START" if key == graph.start else "BOSS" if key == graph.boss else ""
        if not tag and sphere_of and key in sphere_of:
            tag = f"S{sphere_of[key]}"
        rooms.append(dict(key=key, name=r.name, seconds=r.seconds, x=cx(key) - ROOM_W / 2, y=cy(key) - ROOM_H / 2,
                          cx=cx(key), cy=cy(key), classes=" ".join(classes), tag=tag,
                          item=placement.get(key), steps=",".join(map(str, step_numbers.get(key, []))),
                          fill=region_of.get(key) if region_of else None))
    return dict(width=cols * CELL_X + PAD * 2, height=rows * CELL_Y + PAD * 2, w=ROOM_W, h=ROOM_H,
                rooms=rooms, gates=gates)


def tree_view(node: Node) -> dict | None:
    """Lay out an expression tree: leaves take consecutive columns, each operator
    sits centred above its two children."""
    if isinstance(node, Open):
        return None
    nodes, edges = [], []
    leaf_count = 0

    def walk(n: Node, depth: int) -> dict:
        nonlocal leaf_count
        if isinstance(n, Ability):
            item = dict(label=n.name, ability=n.name, col=leaf_count, depth=depth)
            leaf_count += 1
        else:
            left, right = walk(n.left, depth + 1), walk(n.right, depth + 1)
            item = dict(label="AND" if isinstance(n, And) else "OR", ability=None,
                        col=(left["col"] + right["col"]) / 2, depth=depth)
            edges.append((item, left))
            edges.append((item, right))
        nodes.append(item)
        return item

    walk(node, 0)
    sx, sy = 62, 54
    for n in nodes:
        n["x"] = n["col"] * sx + sx / 2 + 8
        n["y"] = n["depth"] * sy + 26
    depth = max(n["depth"] for n in nodes)
    return dict(width=leaf_count * sx + 16, height=(depth + 1) * sy + 8, nodes=nodes,
                edges=[dict(x1=a["x"], y1=a["y"], x2=b["x"], y2=b["y"]) for a, b in edges])


def mini_view(graph: WorldGraph) -> dict:
    """A tiny drawing of the map for thumbnails: rooms as boxes, gates as lines, items as dots."""
    cell_x, cell_y, w, h, pad = 40, 28, 30, 18, 8
    xs = [r.x for r in graph.rooms.values()]
    ys = [r.y for r in graph.rooms.values()]
    min_x, min_y = min(xs), min(ys)

    def centre(key):
        r = graph.rooms[key]
        return (r.x - min_x) * cell_x + cell_x / 2 + pad, (r.y - min_y) * cell_y + cell_y / 2 + pad

    rooms = []
    for key, r in graph.rooms.items():
        x, y = centre(key)
        kind = "start" if key == graph.start else "boss" if key == graph.boss else ""
        rooms.append(dict(x=x - w / 2, y=y - h / 2, cx=x, cy=y, kind=kind, item=r.item,
                          color=graph.powerups.color(r.item) if r.item else None))
    lines = []
    for g in graph.gates:
        (x1, y1), (x2, y2) = centre(g.a), centre(g.b)
        lines.append(dict(x1=x1, y1=y1, x2=x2, y2=y2, one_way=g.one_way, locked=bool(g.rule)))
    width = (max(xs) - min_x + 1) * cell_x + pad * 2
    height = (max(ys) - min_y + 1) * cell_y + pad * 2
    return dict(width=width, height=height, w=w, h=h, rooms=rooms, lines=lines)

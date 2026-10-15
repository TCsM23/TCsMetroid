"""Glue between the database and the engine, shared by the HTML pages and the JSON API."""
from __future__ import annotations

import json

from .engine.analysis import danger_zones
from .engine.checker import check, reachable_with
from .engine.graph import WorldGraph
from .engine.powerups import PowerUpSet
from .engine.randomizer import randomize, seed_code
from .engine.rules import RuleError, minimal_sets, parse
from .engine.search import find_route
from .extensions import db
from .models import Map, Seed


def generate_seed(m: Map, number: int, algorithm: str, graph=None) -> Seed | None:
    """Return the stored seed, generating and saving it if needed. None if no beatable placement exists."""
    existing = Seed.query.filter_by(map_id=m.id, number=number, algorithm=algorithm).first()
    if existing:
        return existing
    graph = graph or m.to_graph()
    result = randomize(graph, number, algorithm)
    if not result.ok:
        return None
    fast = find_route(graph, result.placement, "dijkstra")
    short = find_route(graph, result.placement, "bfs")
    seed = Seed(map_id=m.id, number=number, algorithm=algorithm,
                placement_json=json.dumps(result.placement, sort_keys=True),
                route_seconds=fast.seconds, route_moves=short.moves, attempts=result.attempts,
                code=seed_code(graph, number, algorithm))
    db.session.add(seed)
    return seed


def preview(data: dict, abilities: str = "") -> dict:
    """Check an unsaved draft map. Never raises on bad input: problems come back as
    `errors`, because a half-finished draft is normal while someone is editing."""
    try:
        powerups = PowerUpSet.from_list(data.get("powerups"))
    except (ValueError, TypeError, AttributeError) as exc:
        return {"valid": False, "errors": [{"powerups": True, "message": f"Power-ups: {exc}"}]}
    errors = []
    for i, g in enumerate(data.get("gates", [])):
        try:
            parse(g.get("rule", ""), powerups)
        except RuleError as exc:
            errors.append({"gate": i, "message": f"Gate {i + 1}: {exc}"})
    if errors:
        return {"valid": False, "errors": errors}
    try:
        graph = WorldGraph.from_dict(data)
    except (ValueError, KeyError, TypeError) as exc:
        return {"valid": False, "errors": [{"message": str(exc)}]}

    placement = graph.vanilla_placement()
    result = check(graph, placement)
    route = find_route(graph, placement, "dijkstra") if result.beatable else None
    held = powerups.letters_to_mask(c for c in abilities if c in powerups.bits) if abilities else None
    return {
        "valid": True,
        "errors": [],
        "beatable": result.beatable,
        "reachable": sorted(result.reachable, key=list(graph.rooms).index),
        "sphere_of": result.sphere_of,
        "blocked_gates": sorted({b.gate_index for b in result.blocked}),
        "trap_rooms": danger_zones(graph, placement).rooms,
        "fastest_seconds": route.seconds if route else None,
        "held_reachable": sorted(reachable_with(graph, held)) if held is not None else None,
    }


def game_data(graph: WorldGraph, placement: dict[str, str]) -> dict:
    """Everything the playable game (static/game.js) needs, with the graph work done here in Python."""
    best = find_route(graph, placement, "dijkstra")
    return {
        "start": graph.start,
        "boss": graph.boss,
        "rooms": {k: dict(name=r.name, x=r.x, y=r.y, seconds=r.seconds, item=placement.get(k))
                  for k, r in graph.rooms.items()},
        # A door opens when the player holds every ability of at least one of its minimal sets.
        "gates": [dict(a=g.a, b=g.b, one_way=g.one_way, rule=g.rule, sets=minimal_sets(g.node))
                  for g in graph.gates],
        "powerups": [dict(p, bit=graph.powerups.bit(p["key"])) for p in graph.powerups.to_list()],
        # "room|mask" strings: being in that room holding exactly those abilities means the boss is unreachable.
        "trapped": [f"{room}|{mask}" for room, mask in danger_zones(graph, placement).dead_states],
        "best_seconds": best.seconds,
        "best_moves": best.moves,
    }


def invalidate_seeds(m: Map) -> int:
    """Gates or items changed, so stored seeds no longer describe this map."""
    count = len(m.seeds)
    m.seeds.clear()
    return count

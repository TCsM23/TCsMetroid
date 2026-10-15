"""JSON API. Same engine as the pages, for scripts and other front ends."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .engine import analysis
from .engine.checker import check
from .engine.randomizer import RANDOMIZERS
from .engine.graph import WorldGraph
from .engine.rules import RuleError, minimal_sets, node_to_dict
from .engine.search import ALGORITHMS, find_route
from .extensions import db
from .models import Map, Seed
from .services import game_data, generate_seed, invalidate_seeds, preview

api = Blueprint("api", __name__, url_prefix="/api")


def _error(message: str, status: int = 400):
    return jsonify(error=message), status


def _placement(graph, body):
    placement = (body or {}).get("placement")
    if placement is None:
        return graph.vanilla_placement()
    if not isinstance(placement, dict):
        raise ValueError("placement must be an object of room key -> item letter")
    unknown = [k for k in placement if k not in graph.rooms]
    if unknown:
        raise ValueError(f"Unknown rooms in placement: {', '.join(unknown)}")
    return placement


@api.errorhandler(ValueError)
@api.errorhandler(RuleError)
def handle_value_error(exc):
    return _error(str(exc))


@api.get("/maps")
def list_maps():
    return jsonify([dict(id=m.id, name=m.name, rooms=len(m.rooms), gates=len(m.gates)) for m in Map.query.all()])


@api.post("/maps")
def import_map():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send the map as a JSON object.")
    try:
        m = Map.from_dict(body)
        db.session.commit()
    except KeyError as exc:
        db.session.rollback()
        return _error(f"Missing field {exc}")
    return jsonify(id=m.id, name=m.name), 201


@api.get("/maps/<int:map_id>")
def get_map(map_id):
    return jsonify(db.get_or_404(Map, map_id).to_dict())


@api.put("/maps/<int:map_id>")
def save_map(map_id):
    """Replace a map's whole layout. Used by the designer's Save button."""
    m = db.get_or_404(Map, map_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Send the map as a JSON object.")
    try:
        m.replace_from_dict(body)
        cleared = invalidate_seeds(m)
        db.session.commit()
    except (ValueError, KeyError, TypeError, RuleError) as exc:
        db.session.rollback()
        return _error(str(exc) if not isinstance(exc, KeyError) else f"Missing field {exc}")
    return jsonify(saved=True, cleared_seeds=cleared)


@api.post("/preview")
def preview_map():
    """Check a draft map without saving it. Powers the designer's live status."""
    body = request.get_json(silent=True) or {}
    data = body.get("map")
    if not isinstance(data, dict):
        return _error("Send {\"map\": {...}}.")
    abilities = "".join(ch for ch in str(body.get("abilities", "")) if ch.isalpha()).upper()
    return jsonify(preview(data, abilities))


@api.post("/play")
def play_data():
    """Game data for an unsaved draft, so the sandbox can be played without saving."""
    body = request.get_json(silent=True) or {}
    data = body.get("map")
    if not isinstance(data, dict):
        return _error("Send {\"map\": {...}}.")
    try:
        graph = WorldGraph.from_dict(data)
    except (ValueError, KeyError, TypeError, RuleError) as exc:
        return _error(f"This map can't be played yet: {exc}")
    game = game_data(graph, graph.vanilla_placement())
    game["name"] = data.get("name") or "Sandbox map"
    return jsonify(game)


@api.post("/maps/<int:map_id>/check")
def check_map(map_id):
    m = db.get_or_404(Map, map_id)
    graph = m.to_graph()
    result = check(graph, _placement(graph, request.get_json(silent=True)))
    return jsonify(
        beatable=result.beatable,
        reachable=sorted(result.reachable, key=list(graph.rooms).index),
        spheres=[dict(index=s.index, rooms=s.rooms, items=s.items) for s in result.spheres],
        blocked=[dict(from_room=b.from_room, to_room=b.to_room, rule=b.rule) for b in result.blocked],
    )


@api.route("/maps/<int:map_id>/route", methods=["GET", "POST"])
def route(map_id):
    m = db.get_or_404(Map, map_id)
    algo = request.args.get("algorithm", "dijkstra")
    if algo not in ALGORITHMS:
        return _error(f"algorithm must be one of {', '.join(ALGORITHMS)}")
    graph = m.to_graph()
    r = find_route(graph, _placement(graph, request.get_json(silent=True)), algo)
    return jsonify(
        algorithm=algo, found=r.found, moves=r.moves, seconds=r.seconds,
        expanded=r.expanded, max_frontier=r.max_frontier,
        steps=[dict(room=s.room, seconds=s.seconds, picked=s.picked) for s in r.steps],
    )


@api.get("/maps/<int:map_id>/export/game")
def export_for_game(map_id):
    """Everything a game engine needs to build this map, with the hard work already done."""
    m = db.get_or_404(Map, map_id)
    graph = m.to_graph()
    placement = graph.vanilla_placement()
    seed_id = request.args.get("seed", type=int)
    if seed_id:
        seed = db.session.get(Seed, seed_id)
        if seed is None or seed.map_id != m.id:
            return _error("That seed doesn't belong to this map.", 404)
        placement = seed.placement
    result = check(graph, placement)
    route = find_route(graph, placement, "dijkstra")
    deps = analysis.ability_dependencies(graph, placement)
    order = analysis.topological_sort(deps.nodes, deps.edges).order
    return jsonify({
        "format": "metroidvania-planner/1",
        "name": m.name,
        "start": graph.start,
        "boss": graph.boss,
        "abilities": {k: {"name": graph.powerups.name(k), "bit": b} for k, b in graph.powerups.bits.items()},
        "powerups": graph.powerups.to_list(),
        "rooms": [dict(key=r.key, name=r.name, grid_x=r.x, grid_y=r.y, seconds=r.seconds,
                       item=placement.get(r.key)) for r in graph.rooms.values()],
        "doors": [dict(a=g.a, b=g.b, one_way=g.one_way, rule=g.rule, rule_tree=node_to_dict(g.node),
                       opens_with=[graph.powerups.mask_to_letters(s) if s else "" for s in minimal_sets(g.node)])
                  for g in graph.gates],
        "analysis": {
            "beatable": result.beatable,
            "ability_order": [k for k in order if k != "BOSS"],
            "fastest_seconds": route.seconds if route.found else None,
            "fastest_route": [s.room for s in route.steps],
            "trap_rooms": analysis.danger_zones(graph, placement).rooms,
        },
    })


@api.post("/maps/<int:map_id>/randomize")
def randomize(map_id):
    m = db.get_or_404(Map, map_id)
    body = request.get_json(silent=True) or {}
    number, algorithm = body.get("seed"), body.get("algorithm", "assumed")
    if not isinstance(number, int) or number < 0:
        return _error("seed must be a whole number of 0 or more")
    if algorithm not in RANDOMIZERS:
        return _error(f"algorithm must be one of {', '.join(RANDOMIZERS)}")
    seed = generate_seed(m, number, algorithm)
    if seed is None:
        return _error("No beatable placement exists for this map", 422)
    db.session.commit()
    return jsonify(seed.to_dict())

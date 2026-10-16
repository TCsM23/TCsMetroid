"""HTML pages."""
from __future__ import annotations

import copy
import json
import time

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask import g as flask_g

from .engine import analysis
from .engine.checker import check
from .engine.randomizer import RANDOMIZERS
from .engine.powerups import DEFAULT_POWERUPS, PowerUpSet
from .engine.rules import RuleError, minimal_sets, parse, tokenize
from .engine.search import ALGORITHMS, compare_all
from .engine.sorting import lower_bound, merge_sort, quick_sort_3way
from .extensions import db
from .map_templates import BUILT_IN
from .models import Gate, Map, Room, Seed
from .services import game_data, generate_seed, invalidate_seeds
from .views import REGION_COLORS, map_view, mini_view, tree_view

bp = Blueprint("main", __name__)

SORT_KEYS = {
    "seconds": ("Route time", lambda s: s["seconds"]),
    "moves": ("Moves", lambda s: s["moves"]),
    "attempts": ("Attempts", lambda s: s["attempts"]),
    "number": ("Seed #", lambda s: s["number"]),
}


# ---------------------------------------------------------------- helpers
def load_map(map_id: int) -> Map:
    m = db.get_or_404(Map, map_id)
    use_powerups(m.powerups())
    return m


def use_powerups(powerups: PowerUpSet) -> None:
    """Remember which power-ups this request's pages should show (read by PU() in templates)."""
    flask_g.powerups = powerups


def current_placement(m: Map, graph):
    """Vanilla placement unless ?seed=<id> picks a stored seed of this map."""
    seed_id = request.args.get("seed", type=int)
    if seed_id:
        seed = db.session.get(Seed, seed_id)
        if seed and seed.map_id == m.id:
            return seed.placement, seed
    return graph.vanilla_placement(), None


def safe_graph(m: Map):
    try:
        return m.to_graph()
    except (ValueError, RuleError) as exc:
        flash(f"This map has a problem: {exc}", "error")
        return None


def template_choices() -> list[dict]:
    """Built-in templates first, then the user's own saved templates."""
    choices = [dict(value=key, label=data["name"]) for key, data in BUILT_IN.items()]
    for m in Map.query.filter_by(is_template=True).order_by(Map.name).all():
        choices.append(dict(value=f"map-{m.id}", label=f"{m.name} (your template)"))
    return choices


def load_template(value: str | None) -> dict:
    """Return a fresh copy of a template's map data. Unknown values fall back to the blank map."""
    if value and value.startswith("map-") and value[4:].isdigit():
        m = db.session.get(Map, int(value[4:]))
        if m and m.is_template:
            return m.to_dict()
    return copy.deepcopy(BUILT_IN.get(value or "", BUILT_IN["blank"]))


# ---------------------------------------------------------------- map list
@bp.route("/")
def index():
    rows = []
    for m in Map.query.filter_by(is_template=False).order_by(Map.id).all():
        mini = None
        try:
            g = m.to_graph()
            status = check(g, g.vanilla_placement()).beatable
            mini = mini_view(g)
        except (ValueError, RuleError):
            status = None
        rows.append(dict(map=m, beatable=status, rooms=len(m.rooms), gates=len(m.gates), seeds=len(m.seeds),
                         mini=mini, powerups=m.powerups()))
    user_templates = Map.query.filter_by(is_template=True).order_by(Map.name).all()
    return render_template("index.html", rows=rows, templates=template_choices(), user_templates=user_templates)


@bp.post("/maps")
def create_map():
    data = load_template(request.form.get("template"))
    data["name"] = (request.form.get("name") or "").strip() or data["name"]
    m = Map.from_dict(data)
    db.session.commit()
    flash(f"Created {m.name}.", "ok")
    return redirect(url_for("main.designer", map_id=m.id))


@bp.post("/maps/<int:map_id>/save-template")
def save_template(map_id):
    m = load_map(map_id)
    data = m.to_dict()
    data["name"] = (request.form.get("name") or "").strip() or f"{m.name} template"
    Map.from_dict(data, is_template=True)
    db.session.commit()
    flash(f"Saved \"{data['name']}\" as a template. Pick it under New map or in the Sandbox.", "ok")
    return redirect(request.referrer or url_for("main.index"))


@bp.post("/maps/import")
def import_map():
    try:
        data = json.loads(request.form.get("json") or "")
        m = Map.from_dict(data)
        db.session.commit()
    except (ValueError, KeyError, TypeError, RuleError) as exc:
        db.session.rollback()
        flash(f"Couldn't import that map: {exc}", "error")
        return redirect(url_for("main.index"))
    flash(f"Imported {m.name}.", "ok")
    return redirect(url_for("main.overview", map_id=m.id))


@bp.get("/maps/<int:map_id>/export.json")
def export_map(map_id):
    m = load_map(map_id)
    body = json.dumps(m.to_dict(), indent=2)
    filename = "".join(c if c.isalnum() else "-" for c in m.name.lower()).strip("-") or "map"
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}.json"'})


@bp.post("/maps/<int:map_id>/delete")
def delete_map(map_id):
    m = load_map(map_id)
    db.session.delete(m)
    db.session.commit()
    flash(f"Deleted {m.name}.", "ok")
    return redirect(url_for("main.index"))


# ---------------------------------------------------------------- about / reference / contact / support
# Fill these in to switch the matching buttons on. Empty = hidden.
ABOUT_LINKS = {
    "email": "yvesjerico@gmail.com",
    "facebook": "facebook.com/yvesjerico.repayo/",
    "youtube": "https://www.youtube.com/@tcsm0023",
    "github": "https://github.com/TCsM23",
    "linkedin": "https://linkedin.com/in/yves-jerico-repayo-72a593444",
    "tip": "https://www.paypal.me/YJRepayo",      
    "gcash_qr": True,  # set True after adding static/chords/support-qr.png
}

# From your EmailJS dashboard. Leave empty to hide the message form.
ABOUT_EMAILJS = {
    "service": "service_j9t3wna",
    "template": "template_q4x6tth",
    "key": "aI14LXH9_lJrPbSQ5",
}


RULE_SYNTAX = [
    ("J", "Needs Double Jump"),
    ("J & G", "Needs both (AND)"),
    ("J | G", "Needs either one (OR)"),
    ("M & (D | J)", "Brackets group a part, like in maths"),
    ("(empty)", "Always open"),
]

API_ROUTES = [
    ("GET", "/api/maps", "Every map, short form"),
    ("GET", "/api/maps/<id>", "One map as JSON"),
    ("POST", "/api/maps", "Import a map from JSON"),
    ("PUT", "/api/maps/<id>", "Save a map from the designer"),
    ("POST", "/api/maps/<id>/check", "Run the beatability checker"),
    ("GET", "/api/maps/<id>/route", "Fastest route (?algorithm=astar)"),
    ("POST", "/api/maps/<id>/randomize", "Make a new seed"),
    ("GET", "/api/maps/<id>/export/game", "Map, rules and route for a game engine"),
]


@bp.get("/about")
def about():
    return render_template(
        "about.html",
        links=ABOUT_LINKS,
        emailjs=ABOUT_EMAILJS,
        powerup_rows=DEFAULT_POWERUPS.to_list(),
        rule_syntax=RULE_SYNTAX,
        api_routes=API_ROUTES,
    )


# ---------------------------------------------------------------- overview (checker)
@bp.get("/maps/<int:map_id>")
def overview(map_id):
    m = load_map(map_id)
    graph = safe_graph(m)
    if graph is None:
        return redirect(url_for("main.editor", map_id=m.id))
    placement, seed = current_placement(m, graph)
    result = check(graph, placement)
    view = map_view(graph, placement, reachable=result.reachable, sphere_of=result.sphere_of,
                    blocked=None if result.beatable else result.blocked)
    blocked = {(b.from_room, b.to_room): b for b in result.blocked}.values()
    return render_template("overview.html", map=m, graph=graph, seed=seed, placement=placement,
                           result=result, view=view, blocked=blocked, names=m.room_names())


# ---------------------------------------------------------------- route finder
@bp.get("/maps/<int:map_id>/route")
def route(map_id):
    m = load_map(map_id)
    graph = safe_graph(m)
    if graph is None:
        return redirect(url_for("main.editor", map_id=m.id))
    placement, seed = current_placement(m, graph)
    algo = request.args.get("algo", "dijkstra")
    if algo not in ALGORITHMS:
        algo = "dijkstra"
    results = compare_all(graph, placement)
    chosen = next(r for r in results if r.algorithm == algo)
    found = [r for r in results if r.found]
    best_seconds = min((r.seconds for r in found), default=None)
    reach = check(graph, placement).reachable
    view = map_view(graph, placement, reachable=reach, route=chosen if chosen.found else None)
    return render_template("route.html", map=m, seed=seed, results=results, chosen=chosen, algo=algo,
                           best_seconds=best_seconds, view=view, names=m.room_names())


# ---------------------------------------------------------------- analysis
@bp.get("/maps/<int:map_id>/analysis")
def analysis_page(map_id):
    m = load_map(map_id)
    graph = safe_graph(m)
    if graph is None:
        return redirect(url_for("main.editor", map_id=m.id))
    placement, seed = current_placement(m, graph)
    bits = graph.powerups.bits
    held = [a for a in request.args.getlist("ab") if a in bits]
    if "ab" not in request.args and "set" not in request.args:
        held = list(bits)[:1]
    mask = sum(bits[a] for a in held)

    deps = analysis.ability_dependencies(graph, placement)
    topo = analysis.topological_sort(deps.nodes, deps.edges)
    critical = analysis.item_criticality(graph, placement)
    sccs = analysis.strongly_connected(graph)
    danger = analysis.danger_zones(graph, placement)
    regions = analysis.connected_regions(graph, mask)
    region_of = {room: REGION_COLORS[i % len(REGION_COLORS)] for i, grp in enumerate(regions.groups) for room in grp}
    view = map_view(graph, placement, region_of=region_of, open_mask=mask, danger=danger.rooms)
    return render_template("analysis.html", map=m, seed=seed, placement=placement, deps=deps, topo=topo,
                           critical=critical, sccs=sccs, danger=danger, regions=regions, held=held,
                           region_colors=REGION_COLORS, view=view, names=m.room_names())


# ---------------------------------------------------------------- randomizer
@bp.route("/maps/<int:map_id>/randomize", methods=["GET", "POST"])
def randomize_page(map_id):
    m = load_map(map_id)
    graph = safe_graph(m)
    if graph is None:
        return redirect(url_for("main.editor", map_id=m.id))
    if request.method == "POST":
        number = request.form.get("number", type=int)
        algorithm = request.form.get("algorithm", "assumed")
        if number is None or number < 0 or algorithm not in RANDOMIZERS:
            flash("Enter a whole number of 0 or more for the seed.", "error")
            return redirect(url_for("main.randomize_page", map_id=m.id))
        seed = generate_seed(m, number, algorithm, graph)
        if seed is None:
            flash(f"No beatable placement found for seed {number}. Check the editor: the gates may make every placement impossible.", "error")
            return redirect(url_for("main.randomize_page", map_id=m.id))
        db.session.commit()
        flash(f"Seed {number} is ready. Share code {seed.code}.", "ok")
        return redirect(url_for("main.overview", map_id=m.id, seed=seed.id))
    recent = Seed.query.filter_by(map_id=m.id).order_by(Seed.id.desc()).limit(8).all()
    return render_template("randomize.html", map=m, seed=None, recent=recent, randomizers=RANDOMIZERS,
                           slots=graph.slots, pool=graph.item_pool(), names=m.room_names())


# ---------------------------------------------------------------- seed leaderboard
@bp.route("/maps/<int:map_id>/seeds", methods=["GET", "POST"])
def seeds_page(map_id):
    m = load_map(map_id)
    graph = safe_graph(m)
    if graph is None:
        return redirect(url_for("main.editor", map_id=m.id))
    if request.method == "POST":
        count = max(1, min(2000, request.form.get("count", type=int) or 200))
        algorithm = request.form.get("algorithm", "assumed")
        if algorithm not in RANDOMIZERS:
            abort(400)
        existing = {s.number for s in m.seeds if s.algorithm == algorithm}
        made = failed = 0
        started = time.perf_counter()
        for number in range(1, count + 1):
            if number in existing:
                continue
            if generate_seed(m, number, algorithm, graph):
                made += 1
            else:
                failed += 1
        db.session.commit()
        ms = (time.perf_counter() - started) * 1000
        flash(f"Generated {made} new seeds in {ms:.0f} ms" + (f", {failed} had no beatable placement." if failed else "."), "ok")
        return redirect(url_for("main.seeds_page", map_id=m.id))

    key = request.args.get("sort", "seconds")
    if key not in SORT_KEYS:
        key = "seconds"
    label, key_fn = SORT_KEYS[key]
    rows = [dict(id=s.id, number=s.number, algorithm=s.algorithm, seconds=s.route_seconds,
                 moves=s.route_moves, attempts=s.attempts, code=s.code) for s in m.seeds]
    rows.sort(key=lambda r: r["id"])  # insertion order, so stability is visible

    stats, ordered, agree = [], rows, True
    if rows:
        started = time.perf_counter()
        merged, merge_comparisons = merge_sort(rows, key_fn)
        merge_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        quick, quick_comparisons = quick_sort_3way(rows, key_fn)
        quick_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        builtin = sorted(rows, key=key_fn)
        builtin_ms = (time.perf_counter() - started) * 1000

        agree = [key_fn(a) for a in merged] == [key_fn(b) for b in quick] == [key_fn(c) for c in builtin]
        stats = [dict(name="Merge sort", comparisons=merge_comparisons, ms=merge_ms, stable=True),
                 dict(name="Quicksort (3-way)", comparisons=quick_comparisons, ms=quick_ms, stable=False),
                 dict(name="Python sorted() · Timsort", comparisons=None, ms=builtin_ms, stable=True)]
        ordered = merged

    search = None
    target = request.args.get("target", type=float)
    if target is not None and ordered:
        index, probes = lower_bound(ordered, key_fn, target)
        search = dict(target=target, index=index, probes=probes,
                      hit=ordered[index] if index < len(ordered) else None)
    limit = request.args.get("limit", 25, type=int)
    return render_template("seeds.html", map=m, seed=None, rows=ordered[:limit], total=len(rows), stats=stats,
                           agree=agree, sort_key=key, sort_label=label, sort_keys=SORT_KEYS, search=search,
                           randomizers=RANDOMIZERS, limit=limit)


# ---------------------------------------------------------------- designer and sandbox
@bp.get("/maps/<int:map_id>/designer")
def designer(map_id):
    m = load_map(map_id)
    return render_template("designer.html", mode="designer", map=m, seed=None, draft=m.to_dict())


@bp.get("/sandbox")
def sandbox():
    value = request.args.get("template", "demo")
    draft = load_template(value)
    try:
        use_powerups(PowerUpSet.from_list(draft.get("powerups")))
    except ValueError:
        draft.pop("powerups", None)
    return render_template("designer.html", mode="sandbox", map=None, seed=None, draft=draft,
                           templates=template_choices(), current_template=value)


@bp.get("/maps/<int:map_id>/play")
def playtest(map_id):
    m = load_map(map_id)
    graph = safe_graph(m)
    if graph is None:
        return redirect(url_for("main.editor", map_id=m.id))
    placement, seed = current_placement(m, graph)
    game = game_data(graph, placement)
    game["name"] = m.name
    view = map_view(graph, placement)
    return render_template("play.html", map=m, seed=seed, game=game, view=view)


@bp.get("/sandbox/play")
def sandbox_play():
    """Plays the sandbox draft. The page reads the draft from the browser and asks /api/play for game data."""
    return render_template("play.html", map=None, seed=None, game=None, view=None)


# ---------------------------------------------------------------- editor
@bp.route("/maps/<int:map_id>/edit", methods=["GET", "POST"])
def editor(map_id):
    m = load_map(map_id)
    if request.method == "POST":
        action = request.form.get("action")
        try:
            message = _apply_edit(m, action, request.form)
            m.to_graph()  # validate the whole map before saving
            dropped = invalidate_seeds(m) if action != "update_map_info" else 0
            db.session.commit()
            flash(message + (f" Cleared {dropped} stored seeds because the map changed." if dropped else ""), "ok")
        except (ValueError, RuleError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
        anchor = request.form.get("anchor", "")
        gate_q = request.form.get("gate") or request.args.get("gate")
        return redirect(url_for("main.editor", map_id=m.id, gate=gate_q) + (f"#{anchor}" if anchor else ""))

    graph = None
    try:
        graph = m.to_graph()
    except (ValueError, RuleError) as exc:
        flash(f"This map has a problem: {exc}", "error")

    inspect = None
    gate_id = request.args.get("gate", type=int)
    gate = db.session.get(Gate, gate_id) if gate_id else (m.gates[-1] if m.gates else None)
    draft = request.args.get("rule")
    if gate and gate.map_id == m.id:
        source = gate.rule if draft is None else draft
        try:
            node = parse(source, m.powerups())
            inspect = dict(gate=gate, source=source, tokens=tokenize(source, m.powerups()), tree=tree_view(node),
                           sets=minimal_sets(node), error=None)
        except RuleError as exc:
            inspect = dict(gate=gate, source=source, tokens=[], tree=None, sets=[], error=str(exc))
    view = map_view(graph, graph.vanilla_placement(),
                    highlight_gate=m.gates.index(gate) if graph and gate in m.gates else None) if graph else None
    return render_template("editor.html", map=m, seed=None, view=view, inspect=inspect, items=m.powerups().names,
                           names=m.room_names())


def _apply_edit(m: Map, action: str, form) -> str:
    def room_by_id(rid):
        room = db.session.get(Room, int(rid))
        if not room or room.map_id != m.id:
            raise ValueError("That room no longer exists.")
        return room

    def gate_by_id(gid):
        gate = db.session.get(Gate, int(gid))
        if not gate or gate.map_id != m.id:
            raise ValueError("That gate no longer exists.")
        return gate

    def int_field(name, lo, hi, label):
        try:
            value = int(form.get(name, ""))
        except ValueError:
            raise ValueError(f"{label} must be a whole number.")
        if not lo <= value <= hi:
            raise ValueError(f"{label} must be between {lo} and {hi}.")
        return value

    if action == "update_map_info":
        m.name = (form.get("name") or "").strip()[:80] or m.name
        m.description = (form.get("description") or "").strip()
        return "Saved map details."

    if action == "update_map_ends":
        keys = {r.key for r in m.rooms}
        start, boss = form.get("start"), form.get("boss")
        if start not in keys or boss not in keys:
            raise ValueError("Pick a start and boss room from the list.")
        if start == boss:
            raise ValueError("The start and boss must be different rooms.")
        m.start_key, m.boss_key = start, boss
        return "Updated the start and boss rooms."

    if action in ("add_room", "update_room"):
        key = (form.get("key") or "").strip().lower()
        if not key or not key.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Room keys use letters, numbers, - or _ only.")
        name = (form.get("name") or "").strip()[:60] or key
        x = int_field("x", 0, 40, "X")
        y = int_field("y", 0, 40, "Y")
        seconds = int_field("seconds", 1, 999, "Seconds")
        item = form.get("item") or None
        if item and item not in m.powerups():
            raise ValueError("Unknown power-up.")
        clash = Room.query.filter_by(map_id=m.id, x=x, y=y).first()
        if action == "add_room":
            if any(r.key == key for r in m.rooms):
                raise ValueError(f"A room with key '{key}' already exists.")
            if clash:
                raise ValueError(f"{clash.name} already sits at ({x}, {y}).")
            m.rooms.append(Room(key=key, name=name, x=x, y=y, seconds=seconds, item=item))
            return f"Added {name}."
        room = room_by_id(form.get("room_id"))
        if clash and clash.id != room.id:
            raise ValueError(f"{clash.name} already sits at ({x}, {y}).")
        room.name, room.x, room.y, room.seconds, room.item = name, x, y, seconds, item
        return f"Saved {name}."

    if action == "delete_room":
        room = room_by_id(form.get("room_id"))
        if room.key in (m.start_key, m.boss_key):
            raise ValueError("Pick a different start or boss room before deleting this one.")
        for g in [g for g in m.gates if room.key in (g.room_a, g.room_b)]:
            m.gates.remove(g)
        m.rooms.remove(room)
        return f"Deleted {room.name} and its gates."

    if action in ("add_gate", "update_gate"):
        rule = (form.get("rule") or "").strip()
        parse(rule, m.powerups())  # raises RuleError with a position
        one_way = form.get("one_way") == "on"
        if action == "add_gate":
            a, b = form.get("a"), form.get("b")
            keys = {r.key for r in m.rooms}
            if a not in keys or b not in keys:
                raise ValueError("Pick both rooms for the gate.")
            if a == b:
                raise ValueError("A gate needs two different rooms.")
            m.gates.append(Gate(room_a=a, room_b=b, rule=rule, one_way=one_way))
            return "Added the gate."
        gate = gate_by_id(form.get("gate_id"))
        gate.rule, gate.one_way = rule, one_way
        return "Saved the gate."

    if action == "delete_gate":
        m.gates.remove(gate_by_id(form.get("gate_id")))
        return "Deleted the gate."

    raise ValueError("Unknown action.")


# ---------------------------------------------------------------- template helpers
@bp.record_once
def register_template_globals(state):
    # Jinja globals (not a context processor) so imported macros can see them too.
    # PU() is a function, so each page gets the power-ups of the map it is showing.
    state.app.jinja_env.globals.update(PU=current_powerups, ALGORITHMS=ALGORITHMS)


def current_powerups() -> PowerUpSet:
    return flask_g.get("powerups", DEFAULT_POWERUPS)


@bp.app_template_filter("names_of")
def names_of_filter(keys, names):
    """['cave', 'hall'] -> 'Mossy Cave, Entry Hall'"""
    return ", ".join(names.get(k, k) for k in keys)


@bp.app_template_filter("short_name")
def short_name_filter(key):
    """'G' -> 'Grapple', 'BOSS' -> 'Boss'"""
    return "Boss" if key == "BOSS" else current_powerups().short(key)

"""Tests for the designer, templates, sandbox, playtest and game export (steps 11 to 14)."""
import copy
import json

import pytest

from app.demo_map import DEMO_MAP
from app.engine.analysis import danger_zones
from app.engine.checker import check
from app.engine.graph import WorldGraph
from app.engine.rules import ALL_ABILITIES, mask_to_letters, minimal_sets, node_to_dict, parse
from app.extensions import db
from app.map_templates import BUILT_IN
from app.models import Map, Seed


# ---------------------------------------------------------------- step 11: designer
def test_preview_reports_status(client):
    body = client.post("/api/preview", json={"map": DEMO_MAP, "abilities": "M"}).get_json()
    assert body["valid"] and body["beatable"] and body["fastest_seconds"] == 221
    assert body["trap_rooms"] == []
    assert "shaft" in body["held_reachable"] and "chasm" not in body["held_reachable"]


def test_preview_points_at_the_broken_gate(client):
    draft = copy.deepcopy(DEMO_MAP)
    draft["gates"][3]["rule"] = "M &"
    body = client.post("/api/preview", json={"map": draft}).get_json()
    assert body["valid"] is False and body["errors"][0]["gate"] == 3


def test_preview_lists_blocked_doors(client):
    draft = copy.deepcopy(DEMO_MAP)
    draft["gates"][6]["rule"] = "G"          # Shaft -> Chasm now needs Grapple, which is past it
    body = client.post("/api/preview", json={"map": draft}).get_json()
    assert body["beatable"] is False and 6 in body["blocked_gates"]


def test_save_replaces_layout_and_clears_seeds(client, app):
    client.post("/maps/1/randomize", data={"number": "4", "algorithm": "assumed"})
    draft = copy.deepcopy(DEMO_MAP)
    draft["rooms"][0]["x"] = 0
    draft["rooms"].append({"key": "attic", "name": "Attic", "x": 6, "y": 1, "seconds": 7, "item": None})
    draft["gates"].append({"a": "boss", "b": "attic", "rule": "", "one_way": False})
    body = client.put("/api/maps/1", json=draft).get_json()
    assert body == {"saved": True, "cleared_seeds": 1}
    with app.app_context():
        m = db.session.get(Map, 1)
        assert len(m.rooms) == 14 and len(m.gates) == 15 and Seed.query.count() == 0


def test_save_rejects_bad_map_and_keeps_old_one(client):
    draft = copy.deepcopy(DEMO_MAP)
    draft["gates"].append({"a": "hall", "b": "nowhere", "rule": ""})
    assert client.put("/api/maps/1", json=draft).status_code == 400
    assert len(client.get("/api/maps/1").get_json()["gates"]) == 14


def test_designer_page_renders(client):
    page = client.get("/maps/1/designer").get_data(as_text=True)
    assert 'id="designer-canvas"' in page and "Derelict Outpost" in page


# ---------------------------------------------------------------- step 12: templates
@pytest.mark.parametrize("key", list(BUILT_IN))
def test_every_template_is_valid_and_beatable(key):
    graph = WorldGraph.from_dict(copy.deepcopy(BUILT_IN[key]))
    assert check(graph, graph.vanilla_placement()).beatable


def test_trap_template_really_has_a_trap():
    graph = WorldGraph.from_dict(copy.deepcopy(BUILT_IN["trap"]))
    assert danger_zones(graph, graph.vanilla_placement()).rooms == ["pit"]


def test_new_map_from_template(client, app):
    r = client.post("/maps", data={"name": "My Hub", "template": "hub"})
    assert r.status_code == 302 and "/designer" in r.headers["Location"]
    with app.app_context():
        m = Map.query.filter_by(name="My Hub").one()
        assert len(m.rooms) == len(BUILT_IN["hub"]["rooms"]) and not m.is_template


def test_save_as_template_hides_it_from_the_map_list(client, app):
    client.post("/maps/1/save-template", data={"name": "Outpost layout"})
    with app.app_context():
        t = Map.query.filter_by(name="Outpost layout").one()
        assert t.is_template
        template_id = t.id
    page = client.get("/").get_data(as_text=True)
    assert "<title>Maps · TCsMetroid</title>" in page
    assert f'value="map-{template_id}"' in page        # offered in the New map picker
    assert f'href="/maps/{template_id}"' not in page   # but not shown as a normal map card


# ---------------------------------------------------------------- step 13: sandbox and playtest
@pytest.mark.parametrize("url", ["/sandbox", "/sandbox?template=trap", "/maps/1/play"])
def test_sandbox_and_play_pages_render(client, url):
    assert client.get(url).status_code == 200


def test_sandbox_can_load_your_template(client, app):
    client.post("/maps/1/save-template", data={"name": "Outpost layout"})
    with app.app_context():
        template_id = Map.query.filter_by(name="Outpost layout").one().id
    assert "Outpost layout" in client.get(f"/sandbox?template=map-{template_id}").get_data(as_text=True)


def test_unknown_template_falls_back_to_blank(client):
    assert "Blank map" in client.get("/sandbox?template=nope").get_data(as_text=True)


def test_playtest_sends_traps_and_best_time(client):
    client.post("/maps", data={"name": "Trap", "template": "trap"})
    page = client.get("/maps/2/play").get_data(as_text=True)
    raw = page.split('<script id="play-data" type="application/json">')[1].split("</script>")[0]
    game = json.loads(raw)
    # Dropping into the pit picks up Double Jump (bit 4), but without Dash you can't climb out.
    assert game["trapped"] == ["pit|4"]
    assert game["best_seconds"] == 80


# ---------------------------------------------------------------- step 14: game export
def test_game_export_shape(client):
    body = client.get("/api/maps/1/export/game").get_json()
    assert body["format"] == "metroidvania-planner/1"
    assert body["analysis"]["ability_order"] == ["M", "D", "J", "G"]
    assert body["analysis"]["fastest_route"][0] == "landing" and body["analysis"]["fastest_route"][-1] == "boss"
    last = body["doors"][-1]
    assert last["opens_with"] == ["J", "DG"] and last["rule_tree"]["type"] == "or"


def test_opens_with_agrees_with_the_rule_for_every_mask():
    for rule in ["", "M", "J | (D & G)", "(M | D) & (J | G)", "M & D & J & G"]:
        node = parse(rule)
        options = [mask_to_letters(s) if s else "" for s in minimal_sets(node)]
        for mask in range(ALL_ABILITIES + 1):
            held = set(mask_to_letters(mask)) - {"-"}
            assert any(set(o) <= held for o in options) == node.evaluate(mask), (rule, mask)


def test_rule_tree_is_plain_json():
    assert node_to_dict(parse("J | (D & G)")) == {
        "type": "or", "left": {"type": "ability", "name": "J"},
        "right": {"type": "and", "left": {"type": "ability", "name": "D"}, "right": {"type": "ability", "name": "G"}},
    }
    assert node_to_dict(parse("")) == {"type": "open"}


# ---------------------------------------------------------------- upgrading an old database
def test_old_database_gets_is_template_column(tmp_path):
    """A planner.db made before step 12 has no is_template column. Starting the app must add it and keep the maps."""
    import sqlite3
    from app import create_app

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE maps (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL, description TEXT, "
                "start_key VARCHAR(40) NOT NULL, boss_key VARCHAR(40) NOT NULL, created_at DATETIME)")
    con.execute("INSERT INTO maps (name, start_key, boss_key) VALUES ('Old map', 'a', 'b')")
    con.commit()
    con.close()

    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}"})
    with app.app_context():
        old = Map.query.one()
        assert old.name == "Old map" and old.is_template is False

"""Tests for custom power-ups, the playable game's data and the rebranded pages (steps 15 to 18)."""
import copy
import sqlite3

import pytest

from app.demo_map import DEMO_MAP
from app.engine.checker import check
from app.engine.graph import WorldGraph
from app.engine.powerups import DEFAULT_POWERUPS, MAX_PROGRESSION, PowerUpSet
from app.engine.rules import RuleError, minimal_sets, parse
from app.extensions import db
from app.models import Map

ICE_MAP = {
    "name": "Ice Caves",
    "start": "a",
    "boss": "c",
    "powerups": [
        {"key": "W", "name": "Wall Jump", "color": "#e45cff"},
        {"key": "I", "name": "Ice Beam", "color": "#46e0ff"},
        {"key": "T", "name": "Missile Tank", "color": "#ff8a3d", "progression": False},
    ],
    "rooms": [
        {"key": "a", "name": "Cave Mouth", "x": 0, "y": 0, "seconds": 5, "item": "W"},
        {"key": "b", "name": "Frozen Lake", "x": 1, "y": 0, "seconds": 9, "item": "I"},
        {"key": "x", "name": "Side Room", "x": 1, "y": 1, "seconds": 4, "item": "T"},
        {"key": "c", "name": "Throne", "x": 2, "y": 0, "seconds": 20, "item": None},
    ],
    "gates": [
        {"a": "a", "b": "b", "rule": "W"},
        {"a": "b", "b": "x", "rule": ""},
        {"a": "b", "b": "c", "rule": "W & I"},
    ],
}


# ---------------------------------------------------------------- step 15: the PowerUpSet
def test_default_powerups_match_the_old_constants():
    assert DEFAULT_POWERUPS.bits == {"M": 1, "D": 2, "J": 4, "G": 8}
    assert DEFAULT_POWERUPS.all_mask == 15
    assert DEFAULT_POWERUPS.bit("E") == 0          # a collectible has no bit


def test_custom_powerups_get_their_own_bits():
    pu = PowerUpSet.from_list(ICE_MAP["powerups"])
    assert pu.bits == {"W": 1, "I": 2} and pu.all_mask == 3
    assert pu.mask_to_letters(3) == "WI" and pu.letters_to_mask("I") == 2


@pytest.mark.parametrize("items, message", [
    ([{"key": "ab", "name": "Bad"}], "single capital letter"),
    ([{"key": "W", "name": "One"}, {"key": "W", "name": "Two"}], "Two power-ups use"),
    ([{"key": "W", "name": "Bad", "color": "red"}], "#33aaff"),
    ([{"key": "W", "name": " "}], "needs a name"),
    ([{"key": chr(65 + i), "name": f"P{i}"} for i in range(MAX_PROGRESSION + 1)], "at most"),
])
def test_bad_powerups_are_rejected(items, message):
    with pytest.raises(ValueError, match=message):
        PowerUpSet.from_list(items)


def test_rules_use_the_maps_powerups():
    pu = PowerUpSet.from_list(ICE_MAP["powerups"])
    assert parse("W & I", pu).evaluate(3) and not parse("W & I", pu).evaluate(1)
    with pytest.raises(RuleError, match="Use W or I"):
        parse("M", pu)                               # Morph Ball isn't in this map
    with pytest.raises(RuleError, match="collectible"):
        parse("T", pu)                               # collectibles can't open doors


@pytest.mark.parametrize("rule", ["", "M", "J | (D & G)", "(M | D) & (J | G)", "M & D & J & G", "M | M & D"])
def test_structural_minimal_sets_match_brute_force(rule):
    node = parse(rule)
    passing = [m for m in range(16) if node.evaluate(m)]
    brute = [m for m in passing if not any(o != m and (o & m) == o for o in passing)]
    assert minimal_sets(node) == brute


def test_engine_runs_on_custom_powerups():
    graph = WorldGraph.from_dict(copy.deepcopy(ICE_MAP))
    result = check(graph, graph.vanilla_placement())
    assert result.beatable and result.abilities == 3
    assert graph.item_bit("T") == 0


def test_room_item_must_be_a_known_powerup():
    data = copy.deepcopy(ICE_MAP)
    data["rooms"][0]["item"] = "M"
    with pytest.raises(ValueError, match="Unknown power-up"):
        WorldGraph.from_dict(data)


# ---------------------------------------------------------------- step 15: storage and API
def test_map_round_trips_its_powerups(client, app):
    body = client.post("/api/maps", json=ICE_MAP).get_json()
    with app.app_context():
        m = db.session.get(Map, body["id"])
        assert [p["key"] for p in m.to_dict()["powerups"]] == ["W", "I", "T"]
        assert m.powerups().name("I") == "Ice Beam"


def test_old_maps_get_the_default_powerups(app):
    with app.app_context():
        assert [p["key"] for p in db.session.get(Map, 1).to_dict()["powerups"]] == ["M", "D", "J", "G", "E"]


def test_preview_reports_bad_powerups(client):
    draft = copy.deepcopy(ICE_MAP)
    draft["powerups"][1]["key"] = "W"
    body = client.post("/api/preview", json={"map": draft}).get_json()
    assert body["valid"] is False and body["errors"][0]["powerups"] is True


def test_preview_tests_custom_abilities(client):
    body = client.post("/api/preview", json={"map": ICE_MAP, "abilities": "W"}).get_json()
    assert body["beatable"] and "c" not in body["held_reachable"] and "b" in body["held_reachable"]


def test_designer_save_keeps_powerups(client, app):
    draft = client.get("/api/maps/1").get_json()
    draft["powerups"].append({"key": "X", "name": "X-Ray", "color": "#ffffff"})
    draft["gates"][0]["rule"] = "X | J"
    assert client.put("/api/maps/1", json=draft).get_json()["saved"]
    with app.app_context():
        assert "X" in db.session.get(Map, 1).powerups()


def test_pages_show_custom_powerup_colours(client):
    client.post("/api/maps", json=ICE_MAP)
    page = client.get("/maps/2").get_data(as_text=True)
    assert ".mapsvg-fill-W" in page and "#e45cff" in page and "Ice Beam" in page


def test_old_database_gets_powerups_column(tmp_path):
    from app import create_app

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE maps (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL, description TEXT, "
                "start_key VARCHAR(40) NOT NULL, boss_key VARCHAR(40) NOT NULL, created_at DATETIME, "
                "is_template BOOLEAN NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO maps (name, start_key, boss_key) VALUES ('Old map', 'a', 'b')")
    con.commit()
    con.close()
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}"})
    with app.app_context():
        assert Map.query.one().powerups() is DEFAULT_POWERUPS


# ---------------------------------------------------------------- steps 16 to 18: pages and the game
@pytest.mark.parametrize("url", ["/", "/about", "/sandbox", "/sandbox/play", "/maps/1/play", "/maps/1/designer"])
def test_pages_render_with_header_and_footer(client, url):
    page = client.get(url).get_data(as_text=True)
    assert 'class="base-header-bar"' in page and 'class="base-footer-wrap"' in page and "TCsMetroid" in page


def test_designer_has_zoom_and_powerup_panel(client):
    page = client.get("/sandbox").get_data(as_text=True)
    assert 'id="designer-zoom-in"' in page and 'id="designer-powerups"' in page and 'id="designer-play"' in page


def test_play_api_builds_game_data_for_a_draft(client):
    body = client.post("/api/play", json={"map": ICE_MAP}).get_json()
    assert body["name"] == "Ice Caves" and body["start"] == "a"
    assert {p["key"]: p["bit"] for p in body["powerups"]} == {"W": 1, "I": 2, "T": 0}
    assert body["gates"][2]["sets"] == [3]
    assert body["best_moves"] == 2 and body["rooms"]["x"]["item"] == "T"


def test_play_api_rejects_a_broken_draft(client):
    draft = copy.deepcopy(ICE_MAP)
    draft["gates"][0]["rule"] = "W &"
    r = client.post("/api/play", json={"map": draft})
    assert r.status_code == 400 and "can't be played" in r.get_json()["error"]


def test_game_export_lists_custom_powerups(client):
    mid = client.post("/api/maps", json=ICE_MAP).get_json()["id"]
    body = client.get(f"/api/maps/{mid}/export/game").get_json()
    assert body["abilities"] == {"W": {"name": "Wall Jump", "bit": 1}, "I": {"name": "Ice Beam", "bit": 2}}
    assert body["doors"][2]["opens_with"] == ["WI"]

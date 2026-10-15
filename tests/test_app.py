import json

import pytest

from app.extensions import db
from app.models import Gate, Map, Seed

PAGES = ["/", "/maps/1", "/maps/1/route", "/maps/1/route?algo=astar", "/maps/1/analysis",
         "/maps/1/analysis?set=1&ab=M&ab=J", "/maps/1/randomize", "/maps/1/seeds", "/maps/1/edit"]


@pytest.mark.parametrize("url", PAGES)
def test_pages_render(client, url):
    assert client.get(url).status_code == 200


def test_demo_map_is_loaded_and_beatable(client):
    page = client.get("/maps/1").get_data(as_text=True)
    assert "Derelict Outpost" in page and "Beatable" in page


def test_randomize_saves_a_seed_and_shows_it(client, app):
    r = client.post("/maps/1/randomize", data={"number": "77", "algorithm": "assumed"})
    assert r.status_code == 302
    with app.app_context():
        seed = Seed.query.one()
        assert seed.number == 77 and seed.route_seconds > 0
        seed_id = seed.id
    page = client.get(f"/maps/1?seed={seed_id}").get_data(as_text=True)
    assert "seed 77" in page


def test_same_seed_is_not_duplicated(client, app):
    for _ in range(2):
        client.post("/maps/1/randomize", data={"number": "5", "algorithm": "naive"})
    with app.app_context():
        assert Seed.query.count() == 1


def test_batch_and_leaderboard(client):
    client.post("/maps/1/seeds", data={"count": "60", "algorithm": "assumed"})
    page = client.get("/maps/1/seeds?sort=seconds&target=200").get_data(as_text=True)
    assert "All three produce the same order." in page
    assert "probes" in page


def test_editor_rejects_bad_rule_and_keeps_old_one(client, app):
    with app.app_context():
        gate_id = Gate.query.filter_by(rule="J | (D & G)").one().id
    page = client.post("/maps/1/edit", data={"action": "update_gate", "gate_id": gate_id, "rule": "J | (D &"},
                       follow_redirects=True).get_data(as_text=True)
    assert "ends too early" in page
    with app.app_context():
        assert db.session.get(Gate, gate_id).rule == "J | (D & G)"


def test_editing_a_gate_clears_stale_seeds(client, app):
    client.post("/maps/1/randomize", data={"number": "3", "algorithm": "assumed"})
    with app.app_context():
        gate_id = Gate.query.filter_by(rule="G & M").one().id
    client.post("/maps/1/edit", data={"action": "update_gate", "gate_id": gate_id, "rule": "G"})
    with app.app_context():
        assert Seed.query.count() == 0
        assert db.session.get(Gate, gate_id).rule == "G"


def test_add_and_delete_room(client, app):
    client.post("/maps/1/edit", data={"action": "add_room", "key": "attic", "name": "Attic", "x": "6", "y": "1",
                                      "seconds": "7", "item": ""})
    with app.app_context():
        m = db.session.get(Map, 1)
        room = next(r for r in m.rooms if r.key == "attic")
        room_id = room.id
    client.post("/maps/1/edit", data={"action": "delete_room", "room_id": room_id})
    with app.app_context():
        assert not any(r.key == "attic" for r in db.session.get(Map, 1).rooms)


def test_cannot_delete_start_room(client, app):
    with app.app_context():
        start = next(r for r in db.session.get(Map, 1).rooms if r.key == "landing")
        start_id = start.id
    page = client.post("/maps/1/edit", data={"action": "delete_room", "room_id": start_id},
                       follow_redirects=True).get_data(as_text=True)
    assert "start or boss" in page


def test_export_import_round_trip(client):
    exported = client.get("/maps/1/export.json").get_json()
    r = client.post("/maps/import", data={"json": json.dumps(exported)})
    assert r.status_code == 302
    assert client.get("/api/maps/2").get_json()["gates"] == exported["gates"]


def test_create_blank_map(client):
    r = client.post("/maps", data={"name": "Tiny", "template": "blank"})
    assert r.status_code == 302
    assert client.get("/api/maps/2").get_json()["start"] == "start"


# ---------------------------------------------------------------- API
def test_api_check_and_route(client):
    assert client.post("/api/maps/1/check", json={}).get_json()["beatable"] is True
    body = client.get("/api/maps/1/route?algorithm=astar").get_json()
    assert body["seconds"] == 221 and body["steps"][0]["room"] == "landing"


def test_api_check_custom_placement(client):
    soft_lock = {"cave": "M", "vents": "E", "tower": "J", "foundry": "G", "garden": "D"}
    assert client.post("/api/maps/1/check", json={"placement": soft_lock}).get_json()["beatable"] is False


def test_api_randomize_and_errors(client):
    body = client.post("/api/maps/1/randomize", json={"seed": 9, "algorithm": "assumed"}).get_json()
    assert len(body["code"]) == 8
    assert client.post("/api/maps/1/randomize", json={"seed": -1}).status_code == 400
    assert client.get("/api/maps/1/route?algorithm=nope").status_code == 400
    assert client.post("/api/maps/1/check", json={"placement": {"mars": "M"}}).status_code == 400
    assert client.get("/api/maps/99").status_code == 404


def test_api_import_rejects_bad_map(client, demo_dict):
    demo_dict["gates"][0]["rule"] = "J &&"
    assert client.post("/api/maps", json=demo_dict).status_code == 400

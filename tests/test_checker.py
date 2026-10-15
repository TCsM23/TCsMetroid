from app.engine.checker import check, reachable_with
from app.engine.graph import WorldGraph
from app.engine.rules import ALL_ABILITIES

import pytest


def test_vanilla_is_beatable_in_order(graph, vanilla):
    result = check(graph, vanilla)
    assert result.beatable
    progression = [i for s in result.spheres for i in s.items if i != "E"]
    assert progression == ["M", "D", "J", "G"]


def test_no_abilities_reaches_only_the_first_rooms(graph):
    assert reachable_with(graph, 0) == {"landing", "hall", "cave"}


def test_everything_reachable_with_all_abilities(graph):
    assert reachable_with(graph, ALL_ABILITIES) == set(graph.rooms)


def test_dash_locked_behind_its_own_chain_is_soft_locked(graph):
    # Dash sits in the garden (needs Double Jump); Double Jump sits in the tower (needs Dash or a jump you don't have).
    placement = {"cave": "M", "vents": "E", "tower": "J", "foundry": "G", "garden": "D"}
    result = check(graph, placement)
    assert not result.beatable
    assert "boss" not in result.reachable
    assert any(b.to_room == "chasm" and b.rule == "D" for b in result.blocked)


def test_one_way_drop_is_directed(graph):
    assert any(e.to == "depths" for e in graph.adj["chasm"])
    assert not any(e.to == "chasm" for e in graph.adj["depths"])


def test_bad_maps_are_rejected(demo_dict):
    demo_dict["gates"].append({"a": "hall", "b": "nowhere", "rule": ""})
    with pytest.raises(ValueError, match="unknown room"):
        WorldGraph.from_dict(demo_dict)


def test_bad_rule_is_rejected(demo_dict):
    demo_dict["gates"][0]["rule"] = "J &"
    with pytest.raises(ValueError):
        WorldGraph.from_dict(demo_dict)

import networkx as nx

from app.engine.analysis import (ability_dependencies, connected_regions, danger_zones, item_criticality,
                                 strongly_connected, topological_sort)
from app.engine.graph import WorldGraph
from app.engine.rules import ALL_ABILITIES, letters_to_mask


def test_vanilla_ability_order(graph, vanilla):
    deps = ability_dependencies(graph, vanilla)
    topo = topological_sort(deps.nodes, deps.edges)
    assert topo.order == ["M", "D", "J", "G", "BOSS"]
    assert not topo.cycle
    # every edge points forward in the order
    pos = {n: i for i, n in enumerate(topo.order)}
    assert all(pos[a] < pos[b] for a, b in deps.edges)


def test_soft_lock_shows_up_as_a_cycle(graph):
    placement = {"cave": "M", "vents": "E", "tower": "J", "foundry": "G", "garden": "D"}
    deps = ability_dependencies(graph, placement)
    topo = topological_sort(deps.nodes, deps.edges)
    assert topo.cycle and "BOSS" in topo.cycle


def test_kahn_on_a_plain_dag():
    topo = topological_sort(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
    assert topo.order[0] == "a" and topo.order[-1] == "d" and not topo.cycle


def test_item_criticality(graph, vanilla):
    critical = item_criticality(graph, vanilla)
    assert critical["foundry"] is True     # Grapple opens the Lair Gate
    assert critical["garden"] is False     # the Energy Tank unlocks nothing


def test_scc_matches_networkx(graph):
    for mask in (0, letters_to_mask("M"), letters_to_mask("MD"), ALL_ABILITIES):
        ours = sorted(map(sorted, strongly_connected(graph, mask)))
        theirs = sorted(map(sorted, nx.strongly_connected_components(graph.to_networkx(mask))))
        assert ours == theirs


def test_regions_match_networkx_components(graph):
    for mask in (0, letters_to_mask("M"), letters_to_mask("MDJ"), ALL_ABILITIES):
        regions = connected_regions(graph, mask)
        g = nx.Graph()
        g.add_nodes_from(graph.rooms)
        g.add_edges_from((x.a, x.b) for x in graph.gates if not x.one_way and x.passable(mask))
        assert sorted(map(sorted, regions.groups)) == sorted(map(sorted, nx.connected_components(g)))


def test_demo_map_has_no_danger_zones(graph, vanilla):
    assert danger_zones(graph, vanilla).dead_states == []


def test_trap_is_detected(demo_dict):
    # Make the way back up from the Flooded Depths need Grapple too.
    for g in demo_dict["gates"]:
        if {g["a"], g["b"]} == {"depths", "vents"}:
            g["rule"] = "M & G"
    graph = WorldGraph.from_dict(demo_dict)
    zones = danger_zones(graph, graph.vanilla_placement())
    assert "depths" in zones.rooms   # dropping in before you have Grapple strands you

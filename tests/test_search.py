import networkx as nx
import pytest

from app.engine.randomizer import assumed_fill
from app.engine.rules import ALL_ABILITIES, item_bit
from app.engine.search import ALGORITHMS, compare_all, find_route, relaxed_distances


def _route_is_legal(graph, placement, result):
    """Every move uses a real gate that the abilities held at that moment can open."""
    steps = result.steps
    assert steps[0].room == graph.start and steps[-1].room == graph.boss
    for prev, cur in zip(steps, steps[1:]):
        gate = graph.gates[cur.gate_index]
        assert {gate.a, gate.b} == {prev.room, cur.room}
        if gate.one_way:
            assert (gate.a, gate.b) == (prev.room, cur.room)
        assert gate.passable(prev.mask)
        assert cur.mask == prev.mask | item_bit(placement.get(cur.room))
        assert cur.seconds == prev.seconds + graph.seconds(cur.room)


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
def test_every_algorithm_finds_a_legal_route(graph, vanilla, algorithm):
    result = find_route(graph, vanilla, algorithm)
    assert result.found
    _route_is_legal(graph, vanilla, result)


def test_known_answers_on_demo_map(graph, vanilla):
    results = {r.algorithm: r for r in compare_all(graph, vanilla)}
    assert results["bfs"].moves == 16
    assert results["dijkstra"].seconds == 221
    assert results["astar"].seconds == 221
    assert results["bfs"].seconds >= results["dijkstra"].seconds


def test_astar_expands_fewer_states_than_dijkstra(graph, vanilla):
    assert find_route(graph, vanilla, "astar").expanded < find_route(graph, vanilla, "dijkstra").expanded


def test_unbeatable_placement_has_no_route(graph):
    placement = {"cave": "M", "vents": "E", "tower": "J", "foundry": "G", "garden": "D"}
    for algorithm in ALGORITHMS:
        assert not find_route(graph, placement, algorithm).found


def test_relaxed_heuristic_matches_networkx(graph):
    # Reverse graph with every gate open; weight of u->v is the time to enter v.
    g = graph.to_networkx(ALL_ABILITIES)
    expected = nx.single_source_dijkstra_path_length(g.reverse(copy=True), graph.boss,
                                                     weight=lambda u, v, d: graph.seconds(u))
    assert relaxed_distances(graph) == expected


def test_heuristic_never_overestimates(graph, vanilla):
    h = relaxed_distances(graph)
    best = find_route(graph, vanilla, "dijkstra")
    for step in best.steps:
        remaining = best.seconds - step.seconds
        assert h[step.room] <= remaining


def test_optimal_algorithms_agree_on_many_seeds(graph):
    for seed in range(1, 121):
        placement = assumed_fill(graph, seed).placement
        d = find_route(graph, placement, "dijkstra")
        a = find_route(graph, placement, "astar")
        b = find_route(graph, placement, "bfs")
        assert d.seconds == a.seconds
        assert b.moves <= d.moves          # BFS is optimal in moves
        _route_is_legal(graph, placement, a)

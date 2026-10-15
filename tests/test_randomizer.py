import random
from collections import Counter

import pytest

from app.engine.checker import check
from app.engine.randomizer import (assumed_fill, fisher_yates, randomize, seed_code,
                                   shuffle_and_reroll)

N_SEEDS = 300


def test_fisher_yates_is_a_permutation():
    rng = random.Random(3)
    items = list(range(20))
    out = fisher_yates(items, rng)
    assert sorted(out) == items and items == list(range(20))   # original untouched


def test_fisher_yates_is_roughly_uniform():
    rng = random.Random(9)
    first = Counter(fisher_yates("ABCD", rng)[0] for _ in range(8000))
    for letter in "ABCD":
        assert 1700 < first[letter] < 2300   # expected 2000 each


@pytest.mark.parametrize("algorithm", ["assumed", "naive"])
def test_same_seed_same_placement(graph, algorithm):
    assert randomize(graph, 42, algorithm).placement == randomize(graph, 42, algorithm).placement


@pytest.mark.parametrize("fn", [assumed_fill, shuffle_and_reroll])
def test_every_seed_is_beatable(graph, fn):
    for seed in range(1, N_SEEDS + 1):
        result = fn(graph, seed)
        assert result.ok, f"seed {seed} found no placement"
        assert check(graph, result.placement).beatable, f"seed {seed} is not beatable"
        assert sorted(result.placement.values()) == sorted(graph.item_pool())
        assert set(result.placement) == set(graph.slots)


def test_assumed_fill_rarely_rerolls(graph):
    attempts = [assumed_fill(graph, s).attempts for s in range(1, 201)]
    naive = [shuffle_and_reroll(graph, s).attempts for s in range(1, 201)]
    assert sum(attempts) / len(attempts) < sum(naive) / len(naive)


def test_impossible_map_fails_cleanly(demo_dict):
    from app.engine.graph import WorldGraph
    demo_dict["gates"][-1]["rule"] = "J & D & G & M & J"
    demo_dict["gates"][0]["rule"] = "G"   # the only way out of the start needs Grapple
    graph = WorldGraph.from_dict(demo_dict)
    assert not assumed_fill(graph, 1, max_attempts=10).ok
    assert not shuffle_and_reroll(graph, 1, max_attempts=50).ok


def test_seed_code_is_stable_and_short(graph):
    code = seed_code(graph, 7, "assumed")
    assert code == seed_code(graph, 7, "assumed") and len(code) == 8
    assert code != seed_code(graph, 8, "assumed")

import bisect
import random

import pytest

from app.engine.sorting import lower_bound, merge_sort, quick_sort_3way


@pytest.mark.parametrize("size", [0, 1, 2, 17, 500])
@pytest.mark.parametrize("sorter", [merge_sort, quick_sort_3way])
def test_sorts_match_builtin(size, sorter):
    rng = random.Random(size)
    data = [rng.randint(0, 30) for _ in range(size)]   # lots of duplicates on purpose
    out, comparisons = sorter(data, key=lambda x: x)
    assert out == sorted(data)
    assert comparisons >= 0


def test_merge_sort_is_stable():
    rows = [{"t": t, "id": i} for i, t in enumerate([3, 1, 3, 2, 1, 3])]
    out, _ = merge_sort(rows, key=lambda r: r["t"])
    for a, b in zip(out, out[1:]):
        if a["t"] == b["t"]:
            assert a["id"] < b["id"]


def test_quicksort_handles_all_equal_keys_quickly():
    out, comparisons = quick_sort_3way([5] * 2000, key=lambda x: x)
    assert out == [5] * 2000
    assert comparisons == 2000   # one partition pass and done


def test_merge_sort_comparisons_are_n_log_n():
    data = list(range(1024))
    random.Random(1).shuffle(data)
    _, comparisons = merge_sort(data, key=lambda x: x)
    assert comparisons <= 1024 * 10


@pytest.mark.parametrize("target", [-1, 0, 5, 7, 12, 100])
def test_lower_bound_matches_bisect(target):
    data = [0, 2, 5, 5, 5, 7, 9, 12]
    index, probes = lower_bound(data, lambda x: x, target)
    assert index == bisect.bisect_left(data, target)
    assert len(probes) <= 4   # ceil(log2(8)) + 1

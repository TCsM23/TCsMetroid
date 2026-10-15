import heapq
import random

import pytest

from app.engine.structures import MinHeap, Queue, Stack, UnionFind


def test_queue_is_fifo_and_compacts():
    q = Queue()
    for i in range(500):
        q.enqueue(i)
    out = [q.dequeue() for _ in range(300)]
    assert out == list(range(300))
    assert len(q) == 200 and list(q)[0] == 300
    with pytest.raises(IndexError):
        Queue().dequeue()


def test_stack_is_lifo():
    s = Stack()
    for i in range(5):
        s.push(i)
    assert s.peek() == 4
    assert [s.pop() for _ in range(5)] == [4, 3, 2, 1, 0]
    assert s.is_empty()


def test_heap_matches_heapq():
    rng = random.Random(1)
    values = [rng.randint(0, 50) for _ in range(400)]
    h = MinHeap()
    for v in values:
        h.push(v, f"item{v}")
    popped = [h.pop()[0] for _ in range(len(values))]
    assert popped == sorted(values)
    ref = list(values)
    heapq.heapify(ref)
    assert popped == [heapq.heappop(ref) for _ in values]


def test_heap_ties_pop_in_insertion_order():
    h = MinHeap()
    for name in "abc":
        h.push(1, name)
    assert [h.pop()[1] for _ in range(3)] == ["a", "b", "c"]


def test_union_find_groups():
    uf = UnionFind(range(6))
    assert uf.union(0, 1) and uf.union(1, 2) and uf.union(4, 5)
    assert not uf.union(0, 2)          # already joined
    assert uf.find(0) == uf.find(2)
    assert uf.find(3) != uf.find(0)
    assert sorted(map(sorted, uf.groups())) == [[0, 1, 2], [3], [4, 5]]

"""Hand-built data structures used by the engine.

These are written from scratch on purpose (instead of collections.deque or heapq)
so each one can be read, tested and explained on its own.
"""
from __future__ import annotations

from typing import Any, Generic, Iterator, TypeVar

T = TypeVar("T")


class Queue(Generic[T]):
    """FIFO queue. A moving head index gives O(1) dequeue without shifting the list."""

    def __init__(self) -> None:
        self._items: list[T] = []
        self._head = 0

    def enqueue(self, item: T) -> None:
        self._items.append(item)

    def dequeue(self) -> T:
        if self.is_empty():
            raise IndexError("dequeue from empty queue")
        item = self._items[self._head]
        self._head += 1
        # Compact occasionally so memory doesn't grow forever.
        if self._head > 64 and self._head * 2 > len(self._items):
            self._items = self._items[self._head:]
            self._head = 0
        return item

    def is_empty(self) -> bool:
        return self._head >= len(self._items)

    def __len__(self) -> int:
        return len(self._items) - self._head

    def __iter__(self) -> Iterator[T]:
        return iter(self._items[self._head:])


class Stack(Generic[T]):
    """LIFO stack."""

    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        self._items.append(item)

    def pop(self) -> T:
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self) -> T:
        if not self._items:
            raise IndexError("peek at empty stack")
        return self._items[-1]

    def is_empty(self) -> bool:
        return not self._items

    def __len__(self) -> int:
        return len(self._items)


class MinHeap(Generic[T]):
    """Binary min-heap keyed by priority.

    Stored as an array: the children of index i are 2i+1 and 2i+2.
    A counter breaks ties so items never need to be comparable themselves.
    """

    def __init__(self) -> None:
        self._data: list[tuple[float, int, T]] = []
        self._counter = 0

    def push(self, priority: float, item: T) -> None:
        self._data.append((priority, self._counter, item))
        self._counter += 1
        self._sift_up(len(self._data) - 1)

    def pop(self) -> tuple[float, T]:
        if not self._data:
            raise IndexError("pop from empty heap")
        top = self._data[0]
        last = self._data.pop()
        if self._data:
            self._data[0] = last
            self._sift_down(0)
        return top[0], top[2]

    def peek(self) -> tuple[float, T]:
        if not self._data:
            raise IndexError("peek at empty heap")
        return self._data[0][0], self._data[0][2]

    def is_empty(self) -> bool:
        return not self._data

    def __len__(self) -> int:
        return len(self._data)

    def _less(self, i: int, j: int) -> bool:
        return self._data[i][:2] < self._data[j][:2]

    def _sift_up(self, i: int) -> None:
        while i > 0:
            parent = (i - 1) // 2
            if not self._less(i, parent):
                break
            self._data[i], self._data[parent] = self._data[parent], self._data[i]
            i = parent

    def _sift_down(self, i: int) -> None:
        n = len(self._data)
        while True:
            left, right, smallest = 2 * i + 1, 2 * i + 2, i
            if left < n and self._less(left, smallest):
                smallest = left
            if right < n and self._less(right, smallest):
                smallest = right
            if smallest == i:
                return
            self._data[i], self._data[smallest] = self._data[smallest], self._data[i]
            i = smallest


class UnionFind:
    """Disjoint-set forest with union by rank and path halving."""

    def __init__(self, items) -> None:
        self.parent: dict[Any, Any] = {x: x for x in items}
        self.rank: dict[Any, int] = {x: 0 for x in self.parent}
        self.find_calls = 0
        self.union_count = 0

    def find(self, x):
        self.find_calls += 1
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path halving
            x = self.parent[x]
        return x

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        self.union_count += 1
        return True

    def groups(self) -> list[list]:
        buckets: dict[Any, list] = {}
        for x in self.parent:
            buckets.setdefault(self.find(x), []).append(x)
        return sorted(buckets.values(), key=len, reverse=True)

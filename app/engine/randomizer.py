"""Seeded randomizers. The same seed always produces the same placement."""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from .checker import check
from .graph import WorldGraph


@dataclass
class RandomizeResult:
    algorithm: str
    seed: int
    placement: dict[str, str] | None
    attempts: int

    @property
    def ok(self) -> bool:
        return self.placement is not None


def fisher_yates(items: list, rng: random.Random) -> list:
    """Uniform in-place-style shuffle on a copy: swap each position with a random earlier one."""
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = rng.randint(0, i)
        out[i], out[j] = out[j], out[i]
    return out


def shuffle_and_reroll(graph: WorldGraph, seed: int, max_attempts: int = 5000) -> RandomizeResult:
    """Naive approach: shuffle everything, keep it only if the checker says it's beatable."""
    rng = random.Random(seed)
    slots, pool = graph.slots, graph.item_pool()
    for attempt in range(1, max_attempts + 1):
        placement = dict(zip(slots, fisher_yates(pool, rng)))
        if check(graph, placement).beatable:
            return RandomizeResult("naive", seed, placement, attempt)
    return RandomizeResult("naive", seed, None, max_attempts)


def assumed_fill(graph: WorldGraph, seed: int, max_attempts: int = 100) -> RandomizeResult:
    """Place progression items one at a time, assuming the player already owns every
    item not yet placed. Each item only goes somewhere reachable under that assumption,
    so the result is beatable by construction. A reroll only happens when an item
    runs out of reachable empty slots."""
    rng = random.Random(seed)
    pool = graph.item_pool()
    progression = [i for i in pool if graph.item_bit(i)]
    filler = [i for i in pool if not graph.item_bit(i)]
    for attempt in range(1, max_attempts + 1):
        remaining = fisher_yates(progression, rng)
        placed: dict[str, str] = {}
        failed = False
        while remaining:
            item = remaining.pop()
            assumed = 0
            for other in remaining:
                assumed |= graph.item_bit(other)
            reach = check(graph, placed, base_mask=assumed).reachable
            candidates = [s for s in graph.slots if s not in placed and s in reach]
            if not candidates:
                failed = True
                break
            placed[rng.choice(candidates)] = item
        if failed:
            continue
        empty = fisher_yates([s for s in graph.slots if s not in placed], rng)
        for slot, item in zip(empty, filler):
            placed[slot] = item
        if check(graph, placed).beatable:
            return RandomizeResult("assumed", seed, placed, attempt)
    return RandomizeResult("assumed", seed, None, max_attempts)


RANDOMIZERS = {
    "assumed": ("Assumed fill", assumed_fill),
    "naive": ("Shuffle & reroll", shuffle_and_reroll),
}


def randomize(graph: WorldGraph, seed: int, algorithm: str = "assumed") -> RandomizeResult:
    if algorithm not in RANDOMIZERS:
        raise ValueError(f"Unknown randomizer {algorithm!r}")
    return RANDOMIZERS[algorithm][1](graph, seed)


def seed_code(graph: WorldGraph, seed: int, algorithm: str) -> str:
    """Short shareable code: same map + same seed + same algorithm = same code."""
    payload = json.dumps([graph.to_dict(), seed, algorithm], sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:8].upper()

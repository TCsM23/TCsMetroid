"""Sorting and searching for the seed leaderboard. Each function counts comparisons."""
from __future__ import annotations

import random
from typing import Callable, Sequence


def merge_sort(items: Sequence, key: Callable) -> tuple[list, int]:
    """Stable, O(n log n) always."""
    comparisons = 0

    def sort(part: list) -> list:
        nonlocal comparisons
        if len(part) < 2:
            return part
        mid = len(part) // 2
        left, right = sort(part[:mid]), sort(part[mid:])
        merged, i, j = [], 0, 0
        while i < len(left) and j < len(right):
            comparisons += 1
            if key(right[j]) < key(left[i]):   # strict: ties keep the left item first (stable)
                merged.append(right[j])
                j += 1
            else:
                merged.append(left[i])
                i += 1
        merged.extend(left[i:])
        merged.extend(right[j:])
        return merged

    return sort(list(items)), comparisons


def quick_sort_3way(items: Sequence, key: Callable, seed: int = 7) -> tuple[list, int]:
    """Quicksort with a random pivot and a 3-way (Dutch national flag) partition.

    Route times tie a lot. A 2-way partition degrades toward O(n^2) on many equal
    keys; grouping everything equal to the pivot in the middle avoids that.
    Not stable.
    """
    a = list(items)
    rng = random.Random(seed)
    comparisons = 0

    def sort(lo: int, hi: int) -> None:
        nonlocal comparisons
        while lo < hi:
            pivot = key(a[rng.randint(lo, hi)])
            lt, i, gt = lo, lo, hi
            while i <= gt:
                comparisons += 1
                k = key(a[i])
                if k < pivot:
                    a[lt], a[i] = a[i], a[lt]
                    lt += 1
                    i += 1
                elif k > pivot:
                    a[i], a[gt] = a[gt], a[i]
                    gt -= 1
                else:
                    i += 1
            # Recurse into the smaller side, loop on the larger: keeps the stack O(log n).
            if lt - lo < hi - gt:
                sort(lo, lt - 1)
                lo = gt + 1
            else:
                sort(gt + 1, hi)
                hi = lt - 1

    sort(0, len(a) - 1)
    return a, comparisons


def lower_bound(sorted_items: Sequence, key: Callable, target) -> tuple[int, list[dict]]:
    """Binary search: index of the first item whose key is >= target."""
    lo, hi, probes = 0, len(sorted_items), []
    while lo < hi:
        mid = (lo + hi) // 2
        value = key(sorted_items[mid])
        go = "right" if value < target else "left"
        probes.append({"lo": lo, "hi": hi - 1, "mid": mid, "value": value, "go": go})
        if value < target:
            lo = mid + 1
        else:
            hi = mid
    return lo, probes

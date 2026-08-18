"""Pure sorting-algorithm logic for the Algorithm Visualizer.

This module has no dependency on pygame (or any UI/audio library), so it
can be imported and unit tested on its own - see test_algorithms.py.

Every sort is written as a generator that mutates a list in place and
yields the list of indices that were just compared/touched. The caller
(the pygame app, or a test) decides what to do with each yield - draw a
frame, play a sound, or nothing at all. This means the "visual" run in
the main window and the head-to-head run in race mode share the exact
same algorithm code instead of keeping two parallel copies of each sort.

Each generator is given a `stats` dict with three counters:
  - "comparisons": incremented once per element comparison.
  - "swaps":       incremented only when two elements are exchanged
                    (an actual swap).
  - "writes":       incremented when a single element is overwritten
                    without a matching swap (insertion-sort shifts,
                    merge-sort copies). Kept separate from "swaps" so the
                    stat is an honest reflection of what each algorithm
                    is actually doing.
"""

import random
import time

# The numeric range bar values are generated in. This doubles as the
# visualizer's drawable height in pixels, so it lives here as the single
# source of truth for "how big can a bar value be".
GRAPH_HEIGHT = 600

MIN_BARS = 20
MAX_BARS = 150
DEFAULT_NUM_BARS = 80

ALGORITHMS = [
    "Bubble Sort",
    "Selection Sort",
    "Insertion Sort",
    "Quick Sort",
    "Merge Sort",
    "Heap Sort",
    "Shell Sort",
]

SHUFFLE_MODES = ["Random", "Nearly Sorted", "Reversed", "Few Unique"]

# Textbook time/space complexity per algorithm, for display in the UI.
# Shell Sort's average case depends on the gap sequence; the figure below
# matches the simple n//2 halving sequence used in shell_sort_gen.
ALGORITHM_COMPLEXITY = {
    "Bubble Sort": {"best": "O(n)", "average": "O(n^2)", "worst": "O(n^2)", "space": "O(1)"},
    "Selection Sort": {"best": "O(n^2)", "average": "O(n^2)", "worst": "O(n^2)", "space": "O(1)"},
    "Insertion Sort": {"best": "O(n)", "average": "O(n^2)", "worst": "O(n^2)", "space": "O(1)"},
    "Shell Sort": {"best": "O(n log n)", "average": "O(n^1.5)", "worst": "O(n^2)", "space": "O(1)"},
    "Quick Sort": {"best": "O(n log n)", "average": "O(n log n)", "worst": "O(n^2)", "space": "O(log n)"},
    "Merge Sort": {"best": "O(n log n)", "average": "O(n log n)", "worst": "O(n log n)", "space": "O(n)"},
    "Heap Sort": {"best": "O(n log n)", "average": "O(n log n)", "worst": "O(n log n)", "space": "O(1)"},
}


def generate_values(mode, count):
    """Return a list of `count` bar values arranged according to `mode`."""

    if mode == "Random":
        return [random.randint(20, GRAPH_HEIGHT - 30) for _ in range(count)]

    if mode == "Nearly Sorted":
        result = [
            int(20 + (i / max(1, count - 1)) * (GRAPH_HEIGHT - 50))
            for i in range(count)
        ]
        if count > 1:
            for _ in range(max(2, count // 10)):
                a, b = random.randrange(count), random.randrange(count)
                result[a], result[b] = result[b], result[a]
        return result

    if mode == "Reversed":
        return [
            int(GRAPH_HEIGHT - 30 - (i / max(1, count - 1)) * (GRAPH_HEIGHT - 50))
            for i in range(count)
        ]

    if mode == "Few Unique":
        unique_values = [random.randint(40, GRAPH_HEIGHT - 40) for _ in range(7)]
        return [random.choice(unique_values) for _ in range(count)]

    raise ValueError(f"Unknown shuffle mode: {mode!r}")


def cycle_algorithm(current):
    index = ALGORITHMS.index(current)
    return ALGORITHMS[(index + 1) % len(ALGORITHMS)]


def cycle_shuffle(current):
    index = SHUFFLE_MODES.index(current)
    return SHUFFLE_MODES[(index + 1) % len(SHUFFLE_MODES)]


def new_stats():
    return {"comparisons": 0, "swaps": 0, "writes": 0}


# ============================================================
# BUBBLE SORT
# ============================================================

def bubble_sort_gen(data, stats):
    n = len(data)
    for i in range(n):
        for j in range(n - i - 1):
            stats["comparisons"] += 1
            yield [j, j + 1]
            if data[j] > data[j + 1]:
                data[j], data[j + 1] = data[j + 1], data[j]
                stats["swaps"] += 1


# ============================================================
# SELECTION SORT
# ============================================================

def selection_sort_gen(data, stats):
    n = len(data)
    for i in range(n):
        minimum = i
        for j in range(i + 1, n):
            stats["comparisons"] += 1
            yield [minimum, j]
            if data[j] < data[minimum]:
                minimum = j
        if minimum != i:
            data[i], data[minimum] = data[minimum], data[i]
            stats["swaps"] += 1


# ============================================================
# INSERTION SORT
# ============================================================

def insertion_sort_gen(data, stats):
    for i in range(1, len(data)):
        key = data[i]
        j = i - 1
        while j >= 0:
            stats["comparisons"] += 1
            yield [j, j + 1]
            if data[j] > key:
                data[j + 1] = data[j]
                stats["writes"] += 1
                j -= 1
            else:
                break
        data[j + 1] = key
        stats["writes"] += 1


# ============================================================
# SHELL SORT
# ============================================================

def shell_sort_gen(data, stats):
    n = len(data)
    gap = n // 2
    while gap > 0:
        for i in range(gap, n):
            temp = data[i]
            j = i
            while j >= gap:
                stats["comparisons"] += 1
                yield [j - gap, j]
                if data[j - gap] > temp:
                    data[j] = data[j - gap]
                    stats["writes"] += 1
                    j -= gap
                else:
                    break
            data[j] = temp
            stats["writes"] += 1
        gap //= 2


# ============================================================
# QUICK SORT
# ============================================================

def quick_sort_gen(data, stats, low=0, high=None):
    if high is None:
        high = len(data) - 1
    if low >= high:
        return

    pivot = data[high]
    i = low

    for j in range(low, high):
        stats["comparisons"] += 1
        yield [j, high]
        if data[j] < pivot:
            data[i], data[j] = data[j], data[i]
            stats["swaps"] += 1
            i += 1

    data[i], data[high] = data[high], data[i]
    stats["swaps"] += 1
    yield [i]

    yield from quick_sort_gen(data, stats, low, i - 1)
    yield from quick_sort_gen(data, stats, i + 1, high)


# ============================================================
# MERGE SORT
# ============================================================

def merge_sort_gen(data, stats, left=0, right=None):
    if right is None:
        right = len(data) - 1
    if left >= right:
        return

    middle = (left + right) // 2
    yield from merge_sort_gen(data, stats, left, middle)
    yield from merge_sort_gen(data, stats, middle + 1, right)
    yield from _merge_gen(data, stats, left, middle, right)


def _merge_gen(data, stats, left, middle, right):
    left_values = data[left:middle + 1]
    right_values = data[middle + 1:right + 1]

    i = j = 0
    k = left

    while i < len(left_values) and j < len(right_values):
        stats["comparisons"] += 1
        yield [left + i, middle + 1 + j]
        if left_values[i] <= right_values[j]:
            data[k] = left_values[i]
            i += 1
        else:
            data[k] = right_values[j]
            j += 1
        stats["writes"] += 1
        k += 1

    while i < len(left_values):
        data[k] = left_values[i]
        i += 1
        k += 1
        stats["writes"] += 1
        yield [k - 1]

    while j < len(right_values):
        data[k] = right_values[j]
        j += 1
        k += 1
        stats["writes"] += 1
        yield [k - 1]


# ============================================================
# HEAP SORT
# ============================================================

def _sift_down(data, stats, n, i):
    while True:
        largest = i
        left = 2 * i + 1
        right = 2 * i + 2

        if left < n:
            stats["comparisons"] += 1
            yield [largest, left]
            if data[left] > data[largest]:
                largest = left

        if right < n:
            stats["comparisons"] += 1
            yield [largest, right]
            if data[right] > data[largest]:
                largest = right

        if largest == i:
            break

        data[i], data[largest] = data[largest], data[i]
        stats["swaps"] += 1
        i = largest


def heap_sort_gen(data, stats):
    n = len(data)

    for i in range(n // 2 - 1, -1, -1):
        yield from _sift_down(data, stats, n, i)

    for end in range(n - 1, 0, -1):
        data[0], data[end] = data[end], data[0]
        stats["swaps"] += 1
        yield [0, end]
        yield from _sift_down(data, stats, end, 0)


SORT_GENERATORS = {
    "Bubble Sort": bubble_sort_gen,
    "Selection Sort": selection_sort_gen,
    "Insertion Sort": insertion_sort_gen,
    "Quick Sort": quick_sort_gen,
    "Merge Sort": merge_sort_gen,
    "Heap Sort": heap_sort_gen,
    "Shell Sort": shell_sort_gen,
}


def run_benchmark(shuffle_mode, count):
    """Run every algorithm once on an identical dataset (same shuffle
    mode and size) and return a list of result dicts sorted fastest
    first. No drawing, no delay - this is meant to run near-instantly."""

    dataset = generate_values(shuffle_mode, count)
    results = []

    for name in ALGORITHMS:
        data = list(dataset)
        stats = new_stats()

        start = time.perf_counter()
        for _ in SORT_GENERATORS[name](data, stats):
            pass
        elapsed = time.perf_counter() - start

        results.append(
            {
                "algorithm": name,
                "comparisons": stats["comparisons"],
                "swaps": stats["swaps"],
                "writes": stats["writes"],
                "time": elapsed,
            }
        )

    results.sort(key=lambda r: r["time"])
    return results


class RaceSorter:
    """Drives one algorithm one comparison at a time, using the same
    generator functions as the normal (non-race) sort, so a race is
    always an apples-to-apples comparison of the real algorithms."""

    def __init__(self, data, algorithm_name):
        self.data = data.copy()
        self.algorithm = algorithm_name
        self.stats = new_stats()

        self.done = False
        self.start_time = time.perf_counter()
        self.finished_time = None

        self.generator = SORT_GENERATORS[algorithm_name](self.data, self.stats)

    @property
    def comparisons(self):
        return self.stats["comparisons"]

    @property
    def swaps(self):
        return self.stats["swaps"]

    @property
    def writes(self):
        return self.stats["writes"]

    def step(self):
        if self.done:
            return []

        try:
            return next(self.generator)
        except StopIteration:
            self.done = True
            if self.finished_time is None:
                self.finished_time = time.perf_counter()
            return []

    def elapsed(self):
        if self.finished_time is not None:
            return self.finished_time - self.start_time
        return time.perf_counter() - self.start_time
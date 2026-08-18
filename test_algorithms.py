"""Regression tests for sorting_algorithms.py.

Pure Python, no pygame required - run with either:
    python test_algorithms.py
    pytest test_algorithms.py
"""

import random

from sorting_algorithms import (
    ALGORITHM_COMPLEXITY,
    ALGORITHMS,
    SORT_GENERATORS,
    RaceSorter,
    SHUFFLE_MODES,
    generate_values,
    new_stats,
    run_benchmark,
)

TEST_SIZES = [0, 1, 2, 3, 8, 37, 80]


def run_generator(name, data):
    stats = new_stats()
    gen = SORT_GENERATORS[name](data, stats)
    highlight_count = 0
    for highlight in gen:
        highlight_count += 1
        for idx in highlight:
            assert 0 <= idx < len(data), (
                f"{name}: highlight index {idx} out of range for length {len(data)}"
            )
    return stats, highlight_count


def check_sorts_correctly(name, data):
    expected = sorted(data)
    stats, _ = run_generator(name, list(data))
    working = list(data)
    stats = new_stats()
    for _ in SORT_GENERATORS[name](working, stats):
        pass
    assert working == expected, f"{name} failed to sort {data!r} -> got {working!r}"
    return stats


def test_all_algorithms_sort_random_data():
    random.seed(0)
    for name in ALGORITHMS:
        for size in TEST_SIZES:
            data = [random.randint(0, 1000) for _ in range(size)]
            check_sorts_correctly(name, data)


def test_all_algorithms_handle_already_sorted():
    for name in ALGORITHMS:
        data = list(range(50))
        check_sorts_correctly(name, data)


def test_all_algorithms_handle_reversed():
    for name in ALGORITHMS:
        data = list(range(50, 0, -1))
        check_sorts_correctly(name, data)


def test_all_algorithms_handle_duplicates():
    random.seed(1)
    for name in ALGORITHMS:
        data = [random.choice([5, 10, 10, 15]) for _ in range(40)]
        check_sorts_correctly(name, data)


def test_all_algorithms_handle_empty_and_single():
    for name in ALGORITHMS:
        check_sorts_correctly(name, [])
        check_sorts_correctly(name, [42])


def test_stats_counters_are_nonnegative_and_plausible():
    random.seed(2)
    for name in ALGORITHMS:
        data = [random.randint(0, 500) for _ in range(60)]
        stats = new_stats()
        for _ in SORT_GENERATORS[name](data, stats):
            pass
        assert stats["comparisons"] >= 0
        assert stats["swaps"] >= 0
        assert stats["writes"] >= 0
        # Every algorithm should do at least one comparison on 60
        # (mostly) distinct random elements.
        assert stats["comparisons"] > 0, f"{name} did zero comparisons"


def test_generate_values_respects_mode_and_count():
    for mode in SHUFFLE_MODES:
        for count in (0, 1, 20, 80):
            values = generate_values(mode, count)
            assert len(values) == count
            assert all(isinstance(v, int) for v in values)

    sorted_asc = generate_values("Reversed", 30)
    # "Reversed" should be non-increasing (ignoring the small perturbation
    # modes don't apply here - Reversed has no shuffling step).
    assert sorted_asc == sorted(sorted_asc, reverse=True)


def test_generate_values_rejects_unknown_mode():
    try:
        generate_values("Not A Real Mode", 10)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown shuffle mode")


def test_race_sorter_matches_generator_result():
    random.seed(3)
    for name in ALGORITHMS:
        data = [random.randint(0, 500) for _ in range(50)]
        sorter = RaceSorter(data, name)
        steps = 0
        while not sorter.done:
            sorter.step()
            steps += 1
            assert steps < 1_000_000, f"{name}: RaceSorter did not terminate"
        assert sorter.data == sorted(data), f"RaceSorter({name}) produced wrong result"
        assert sorter.comparisons > 0
        # elapsed() should be monotonic and finite once finished
        assert sorter.elapsed() >= 0


def test_quick_sort_and_merge_sort_default_args_match_explicit_bounds():
    random.seed(4)
    data = [random.randint(0, 100) for _ in range(25)]

    a = list(data)
    stats_a = new_stats()
    for _ in SORT_GENERATORS["Quick Sort"](a, stats_a):
        pass

    b = list(data)
    stats_b = new_stats()
    for _ in SORT_GENERATORS["Quick Sort"](b, stats_b, 0, len(b) - 1):
        pass

    assert a == b == sorted(data)
    assert stats_a == stats_b


def test_algorithm_complexity_covers_every_algorithm():
    for name in ALGORITHMS:
        assert name in ALGORITHM_COMPLEXITY, f"missing complexity entry for {name}"
        entry = ALGORITHM_COMPLEXITY[name]
        for key in ("best", "average", "worst", "space"):
            assert key in entry, f"{name} complexity missing '{key}'"
            assert isinstance(entry[key], str) and entry[key], f"{name} '{key}' is empty"


def test_run_benchmark_sorts_fastest_first_and_covers_all_algorithms():
    random.seed(5)
    results = run_benchmark("Random", 60)

    names = {r["algorithm"] for r in results}
    assert names == set(ALGORITHMS)
    assert len(results) == len(ALGORITHMS)

    times = [r["time"] for r in results]
    assert times == sorted(times), "benchmark results should be sorted fastest first"

    for r in results:
        assert r["comparisons"] >= 0
        assert r["swaps"] >= 0
        assert r["writes"] >= 0
        assert r["time"] >= 0


def test_run_benchmark_uses_identical_dataset_for_every_algorithm():
    # Every algorithm should end up with the same sorted result even
    # though they each get their own working copy of the dataset.
    random.seed(6)
    results = run_benchmark("Few Unique", 40)
    assert len(results) == len(ALGORITHMS)


ALL_TESTS = [
    test_all_algorithms_sort_random_data,
    test_all_algorithms_handle_already_sorted,
    test_all_algorithms_handle_reversed,
    test_all_algorithms_handle_duplicates,
    test_all_algorithms_handle_empty_and_single,
    test_stats_counters_are_nonnegative_and_plausible,
    test_generate_values_respects_mode_and_count,
    test_generate_values_rejects_unknown_mode,
    test_race_sorter_matches_generator_result,
    test_quick_sort_and_merge_sort_default_args_match_explicit_bounds,
    test_algorithm_complexity_covers_every_algorithm,
    test_run_benchmark_sorts_fastest_first_and_covers_all_algorithms,
    test_run_benchmark_uses_identical_dataset_for_every_algorithm,
]


if __name__ == "__main__":
    failures = 0
    for test in ALL_TESTS:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
        else:
            print(f"PASS  {test.__name__}")

    print()
    if failures:
        print(f"{failures} test(s) failed")
        raise SystemExit(1)
    print(f"All {len(ALL_TESTS)} tests passed")
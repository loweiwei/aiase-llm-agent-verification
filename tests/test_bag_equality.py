"""Tests for the grading-path SQL multiset comparator."""

from aiase_contract import bag_equal as contract_bag_equal
from run_dev import bag_equal


def test_identical_rows():
    a = [(1, "Alice"), (2, "Bob"), (3, "Chen")]
    assert bag_equal(a, a)


def test_order_insensitive():
    a = [(1, "Alice"), (2, "Bob")]
    b = [(2, "Bob"), (1, "Alice")]
    assert bag_equal(a, b)


def test_duplicates_count():
    # "Alice, Bob, Bob" vs "Alice, Bob" must NOT be equal (spec §4.1).
    a = [("Alice",), ("Bob",), ("Bob",)]
    b = [("Alice",), ("Bob",)]
    assert not bag_equal(a, b)


def test_missing_distinct_fail_case():
    # The canonical "missed DISTINCT" example from spec §2.2:
    # student got [(Alice), (Bob), (Bob), (Chen)] but gold is [(Alice), (Bob), (Chen)].
    student = [("Alice",), ("Bob",), ("Bob",), ("Chen",)]
    gold = [("Alice",), ("Bob",), ("Chen",)]
    assert not bag_equal(student, gold)


def test_both_empty():
    assert bag_equal([], [])


def test_one_empty():
    assert not bag_equal([(1,)], [])


def test_none_and_distinct_values():
    a = [(None,), (1,), ("x",)]
    b = [(1,), ("x",), (None,)]
    assert bag_equal(a, b)


def test_lists_accepted_like_tuples():
    a = [[1, "Alice"], [2, "Bob"]]
    b = [(1, "Alice"), (2, "Bob")]
    assert bag_equal(a, b)


def test_column_order_matters():
    # Spec: rows are compared as tuples; if SELECT order differs, rows differ.
    a = [("Alice", "CS")]
    b = [("CS", "Alice")]
    assert not bag_equal(a, b)


def test_floats_exact():
    a = [(1.5,), (2.25,)]
    b = [(2.25,), (1.5,)]
    assert bag_equal(a, b)


def test_bytes_handled():
    a = [(b"data",)]
    b = [(b"data",)]
    assert bag_equal(a, b)


def test_public_helper_matches_grading_contract():
    cases = [
        ([(1, "a"), (2, "b")], [(2, "b"), (1, "a")]),
        ([("Alice", "CS")], [("CS", "Alice")]),
        ([(1,), (1,)], [(1,)]),
    ]
    for left, right in cases:
        assert bag_equal(left, right) == contract_bag_equal(left, right)

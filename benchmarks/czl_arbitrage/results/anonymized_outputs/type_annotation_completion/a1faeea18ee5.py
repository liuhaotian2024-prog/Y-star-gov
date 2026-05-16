# trial_id: a1faeea18ee5
# (arm name redacted for blind review)

# === data_ops.py ===


# === test_data_ops.py ===
from data_ops import (
    Cache, normalize_record, merge_dicts, group_by,
    first_or_none, find_one, filter_keys, safe_int,
    chunked, flatten, histogram, best_by,
)


def test_cache_put_get():
    c = Cache()
    c.put('a', 1)
    assert c.get('a') == 1
    assert c.get('missing') is None


def test_normalize_record():
    assert normalize_record({'Name': '  Bob  ', 'age': 30}) == {'Name': 'bob', 'age': 30}


def test_merge_dicts():
    assert merge_dicts({'a': 1}, {'b': 2}) == {'a': 1, 'b': 2}


def test_group_by():
    g = group_by([1, 2, 3, 4], lambda x: x % 2)
    assert g[0] == [2, 4]
    assert g[1] == [1, 3]


def test_first_or_none():
    assert first_or_none([1, 2]) == 1
    assert first_or_none([]) is None


def test_find_one():
    assert find_one([1, 2, 3], lambda x: x > 1) == 2
    assert find_one([1, 2, 3], lambda x: x > 10) is None


def test_filter_keys():
    assert filter_keys({'a': 1, 'b': 2}, {'a'}) == {'a': 1}


def test_safe_int():
    assert safe_int('5') == 5
    assert safe_int('bad', default=-1) == -1


def test_chunked():
    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_flatten():
    assert flatten([[1, 2], [3]]) == [1, 2, 3]


def test_histogram():
    assert histogram(['a', 'b', 'a']) == {'a': 2, 'b': 1}


def test_best_by():
    assert best_by([1, 5, 3], lambda x: -x) == 1

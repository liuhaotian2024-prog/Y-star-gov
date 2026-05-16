# trial_id: a1eae10823a7
# (arm name redacted for blind review)

# === data_ops.py ===
from collections import defaultdict
from typing import Any, Dict, List, Optional, Callable, Iterable, Sequence, TypeVar

# Define a type variable for generic use where types are unknown
T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')


class Cache:
    def __init__(self):
        self._store: Dict[Any, Any] = {}

    def get(self, key: Any, default: Any = None) -> Any:
        return self._store.get(key, default)

    def put(self, key: Any, value: Any) -> None:
        self._store[key] = value

    def remove(self, key: Any) -> Optional[Any]:
        return self._store.pop(key, None)

    def keys(self) -> List[Any]:
        return list(self._store.keys())


def normalize_record(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, str):
            out[k] = v.strip().lower()
        else:
            out[k] = v
    return out


def merge_dicts(a: Dict[Any, Any], b: Dict[Any, Any]) -> Dict[Any, Any]:
    result: Dict[Any, Any] = dict(a)
    result.update(b)
    return result


def group_by(items: Iterable[Any], key_fn: Callable[[Any], Any]) -> Dict[Any, List[Any]]:
    groups: defaultdict[Any, List[Any]] = defaultdict(list)
    for item in items:
        groups[key_fn(item)].append(item)
    return dict(groups)


def first_or_none(items: Sequence[Any]) -> Optional[Any]:
    return items[0] if items else None


def find_one(items: Iterable[Any], predicate: Callable[[Any], bool]) -> Optional[Any]:
    for x in items:
        if predicate(x):
            return x
    return None


def filter_keys(d: Dict[Any, Any], allowed: Iterable[Any]) -> Dict[Any, Any]:
    return {k: v for k, v in d.items() if k in allowed}


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def chunked(items: Sequence[Any], size: int) -> List[Sequence[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def flatten(nested: Iterable[Iterable[Any]]) -> List[Any]:
    out: List[Any] = []
    for sub in nested:
        out.extend(sub)
    return out


def histogram(items: Iterable[Any]) -> Dict[Any, int]:
    counts: Dict[Any, int] = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    return counts


def best_by(items: Iterable[Any], score_fn: Callable[[Any], float]) -> Optional[Any]:
    best: Optional[Any] = None
    best_score: Optional[float] = None
    for x in items:
        score = score_fn(x)
        if best is None or score > best_score:
            best = x
            best_score = score
    return best


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

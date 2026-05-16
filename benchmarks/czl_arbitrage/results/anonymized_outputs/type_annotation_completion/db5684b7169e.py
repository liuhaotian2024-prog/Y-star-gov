# trial_id: db5684b7169e
# (arm name redacted for blind review)

# === data_ops.py ===
from collections import defaultdict
from typing import Any, Callable, Hashable, Iterable, Optional, TypeVar


K = TypeVar("K")
V = TypeVar("V")
T = TypeVar("T")
H = TypeVar("H", bound=Hashable)
S = TypeVar("S")


class Cache:
    def __init__(self) -> None:
        self._store: dict[Any, Any] = {}

    def get(self, key: Any, default: Any = None) -> Any:
        return self._store.get(key, default)

    def put(self, key: Any, value: Any) -> None:
        self._store[key] = value

    def remove(self, key: Any) -> Any:
        return self._store.pop(key, None)

    def keys(self) -> list[Any]:
        return list(self._store.keys())


def normalize_record(row: dict[K, V]) -> dict[K, V]:
    out: dict[K, V] = {}
    for k, v in row.items():
        if isinstance(v, str):
            out[k] = v.strip().lower()  # type: ignore[assignment]
        else:
            out[k] = v
    return out


def merge_dicts(a: dict[K, V], b: dict[K, V]) -> dict[K, V]:
    result = dict(a)
    result.update(b)
    return result


def group_by(items: Iterable[T], key_fn: Callable[[T], H]) -> dict[H, list[T]]:
    groups: defaultdict[H, list[T]] = defaultdict(list)
    for item in items:
        groups[key_fn(item)].append(item)
    return dict(groups)


def first_or_none(items: list[T]) -> Optional[T]:
    return items[0] if items else None


def find_one(items: Iterable[T], predicate: Callable[[T], bool]) -> Optional[T]:
    for x in items:
        if predicate(x):
            return x
    return None


def filter_keys(d: dict[K, V], allowed: Iterable[K]) -> dict[K, V]:
    return {k: v for k, v in d.items() if k in allowed}


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def chunked(items: list[T], size: int) -> list[list[T]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def flatten(nested: Iterable[Iterable[T]]) -> list[T]:
    out: list[T] = []
    for sub in nested:
        out.extend(sub)
    return out


def histogram(items: Iterable[H]) -> dict[H, int]:
    counts: dict[H, int] = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    return counts


def best_by(items: Iterable[T], score_fn: Callable[[T], Any]) -> Optional[T]:
    best: Optional[T] = None
    best_score: Any = None
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

# trial_id: 8df36f47d0f6
# (arm name redacted for blind review)

# === data_processor.py ===
from typing import Any, Iterable, Mapping


def filter_active_users(users: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [u for u in users if u.get('active')]


def compute_avg_age(users: Iterable[Mapping[str, Any]]) -> float:
    ages: list[float] = [float(u['age']) for u in users if 'age' in u]
    if not ages:
        return 0.0
    return sum(ages) / len(ages)


def count_by_domain(emails: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in emails:
        if '@' not in e:
            continue
        d = e.split('@', 1)[1].lower()
        counts[d] = counts.get(d, 0) + 1
    return counts


# === test_data_processor.py ===
from data_processor import filter_active_users, compute_avg_age, count_by_domain


def test_filter_active_basic():
    out = filter_active_users([{'id': 1, 'active': True}, {'id': 2, 'active': False}])
    assert len(out) == 1
    assert out[0]['id'] == 1


def test_filter_active_empty():
    assert filter_active_users([]) == []


def test_filter_active_missing_field():
    assert filter_active_users([{'id': 1}]) == []


def test_compute_avg_age_basic():
    assert compute_avg_age([{'age': 20}, {'age': 30}]) == 25.0


def test_compute_avg_age_empty():
    assert compute_avg_age([]) == 0.0


def test_compute_avg_age_skip_missing():
    assert compute_avg_age([{'age': 20}, {'name': 'x'}]) == 20.0


def test_count_by_domain_basic():
    out = count_by_domain(['a@x.com', 'b@x.com', 'c@y.com'])
    assert out['x.com'] == 2
    assert out['y.com'] == 1


def test_count_by_domain_case_insensitive():
    assert count_by_domain(['A@X.com']) == {'x.com': 1}


def test_count_by_domain_skip_no_at():
    assert count_by_domain(['foo', 'a@x.com']) == {'x.com': 1}

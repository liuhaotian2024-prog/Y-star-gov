# trial_id: 8be1dcc5b214
# (arm name redacted for blind review)

# === service_a.py ===
from utils.old_api import bar


def compute_a(n: int) -> int:
    return bar(n) + 1


# === service_b.py ===
from utils.old_api import bar


def compute_b(n: int) -> str:
    result = bar(n)
    return f"calling bar({n}) returned {result}"


# === service_c.py ===
from utils.old_api import bar


def describe_c(n: int) -> str:
    return f"after bar({n}) we get {bar(n)}"


# === service_d.py ===
from utils.old_api import bar


def compute_d(n: int) -> int:
    return bar(n) - 1


# === service_e.py ===
from utils.old_api import bar


def compute_e(n: int) -> int:
    intermediate = bar(n)
    return bar(intermediate)


# === test_services.py ===
from service_a import compute_a
from service_b import compute_b
from service_c import describe_c
from service_d import compute_d
from service_e import compute_e


def test_compute_a():
    assert compute_a(3) == 7


def test_compute_b():
    s = compute_b(3)
    assert '6' in s and '3' in s


def test_describe_c():
    s = describe_c(4)
    assert '8' in s and '4' in s


def test_compute_d():
    assert compute_d(5) == 9


def test_compute_e():
    assert compute_e(2) == 8


# === utils/__init__.py ===


# === utils/old_api.py ===
"""Deprecated: bar() is the current function."""


def bar(x: int) -> int:
    return x * 2

"""Task fixtures for auto_benchmark. 20 tasks across 4 domains.

Each task is a dict with:
  task_id, domain, prompt, workspace_files (dict path->content),
  output_file, output_block_type, verifier_cmd, y_star_description
"""
from typing import Dict, List


TASKS: List[Dict] = []


# =============================================================================
# PYTHON (5 tasks)
# =============================================================================

TASKS.append({
    "task_id": "py_fix_off_by_one",
    "domain": "python",
    "prompt": (
        "Below is a function with an off-by-one bug. Fix it. The test file is "
        "tests/test_solution.py — keep all imports and only change the function "
        "body in solution.py.\n\n"
        "solution.py:\n```python\ndef last_n(items, n):\n"
        "    # BUG: off-by-one\n    return items[-n-1:]\n```\n\n"
        "Emit corrected solution.py wrapped in ```python ... ```."
    ),
    "workspace_files": {
        "solution.py": "def last_n(items, n):\n    # BUG: off-by-one\n    return items[-n-1:]\n",
        "tests/test_solution.py": (
            "import sys; sys.path.insert(0, '.')\n"
            "from solution import last_n\n\n"
            "def test_basic():\n    assert last_n([1,2,3,4,5], 3) == [3,4,5]\n"
            "def test_one():\n    assert last_n([1,2,3], 1) == [3]\n"
            "def test_all():\n    assert last_n([1,2], 2) == [1,2]\n"
        ),
    },
    "output_file": "solution.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest tests/ -q --tb=no",
    "y_star": "tests/test_solution.py 3 tests all pass",
})

TASKS.append({
    "task_id": "py_type_hints",
    "domain": "python",
    "prompt": (
        "Add type hints to this utility function so mypy --strict passes. "
        "Function signature must use Iterable, Dict, Optional from typing.\n\n"
        "```python\ndef group_by(items, key_fn, default=None):\n"
        "    out = {}\n"
        "    for it in items:\n"
        "        k = key_fn(it)\n"
        "        out.setdefault(k, []).append(it)\n"
        "    return out\n```\n\n"
        "Emit the full annotated function in ```python ... ```."
    ),
    "workspace_files": {
        "util.py": "def group_by(items, key_fn, default=None):\n    out = {}\n    for it in items:\n        k = key_fn(it)\n        out.setdefault(k, []).append(it)\n    return out\n",
    },
    "output_file": "util.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m mypy --strict util.py 2>&1 | grep -q 'no issues found' && python3.11 -c 'from util import group_by; assert group_by([1,2,3,4],lambda x: x%2)=={1:[1,3], 0:[2,4]}'",
    "y_star": "mypy --strict reports no issues + function still works",
})

TASKS.append({
    "task_id": "py_refactor_god",
    "domain": "python",
    "prompt": (
        "Split this class into 2 smaller classes (UserRepo for storage, "
        "EmailValidator for email logic). Same external behavior. The test "
        "passes a UserRepo and calls .add(email).\n\n"
        "```python\nclass UserManager:\n    def __init__(self):\n        self.users = []\n"
        "    def add(self, email):\n        if '@' not in email:\n            return False\n"
        "        if email in self.users:\n            return False\n        self.users.append(email)\n"
        "        return True\n```\n\n"
        "Emit the new ``manager.py`` keeping a class named `UserManager` with same "
        "`.add(email)` interface that uses `UserRepo` and `EmailValidator` internally. "
        "Wrap in ```python ... ```."
    ),
    "workspace_files": {
        "manager.py": "class UserManager:\n    def __init__(self):\n        self.users = []\n    def add(self, email):\n        if '@' not in email:\n            return False\n        if email in self.users:\n            return False\n        self.users.append(email)\n        return True\n",
        "tests/test_manager.py": (
            "import sys; sys.path.insert(0, '.')\n"
            "from manager import UserManager\n\n"
            "def test_basic():\n    m = UserManager()\n    assert m.add('a@b.com')\n    assert not m.add('a@b.com')\n    assert not m.add('noatsign')\n"
            "def test_classes_exist():\n    import manager\n    assert hasattr(manager, 'UserRepo')\n    assert hasattr(manager, 'EmailValidator')\n"
        ),
    },
    "output_file": "manager.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest tests/ -q --tb=no",
    "y_star": "tests pass + UserRepo and EmailValidator classes exist",
})

TASKS.append({
    "task_id": "py_fix_exception_path",
    "domain": "python",
    "prompt": (
        "Fix this function so it correctly raises ValueError (not IndexError) "
        "when given an empty list. Tests expect ValueError specifically.\n\n"
        "```python\ndef first_or_raise(items):\n    return items[0]\n```\n\n"
        "Emit corrected function in ```python ... ```. Filename: solution.py"
    ),
    "workspace_files": {
        "solution.py": "def first_or_raise(items):\n    return items[0]\n",
        "tests/test_solution.py": (
            "import sys; sys.path.insert(0, '.')\n"
            "import pytest\nfrom solution import first_or_raise\n\n"
            "def test_value():\n    assert first_or_raise([1,2,3]) == 1\n"
            "def test_empty_raises_valueerror():\n    with pytest.raises(ValueError):\n        first_or_raise([])\n"
        ),
    },
    "output_file": "solution.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest tests/ -q --tb=no",
    "y_star": "test_empty_raises_valueerror passes (ValueError, not IndexError)",
})

TASKS.append({
    "task_id": "py_ruff_clean",
    "domain": "python",
    "prompt": (
        "Rewrite this code to pass `ruff check --select=E,F,W,I,UP --no-fix`. "
        "Keep behaviour identical.\n\n"
        "```python\nimport os, sys\nimport json\ndef f(x):\n  y=x+1\n  return  y\n"
        "unused_var = 42\n```\n\n"
        "Emit cleaned `solution.py` in ```python ... ```."
    ),
    "workspace_files": {
        "solution.py": "import os, sys\nimport json\ndef f(x):\n  y=x+1\n  return  y\nunused_var = 42\n",
    },
    "output_file": "solution.py",
    "output_block_type": "python",
    "verifier_cmd": "ruff check --select=E,F,W,I,UP --no-fix solution.py && python3.11 -c 'from solution import f; assert f(2)==3'",
    "y_star": "ruff passes + function still returns x+1",
})


# =============================================================================
# SQL (5 tasks)
# =============================================================================

# All SQL tasks use a small sqlite db built fresh in workspace.
SQL_SCHEMA = """CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, total REAL, ts TEXT);
INSERT INTO users (id, name, country) VALUES
  (1, 'Alice', 'US'), (2, 'Bob', 'US'), (3, 'Charlie', 'UK'), (4, 'Dave', 'CA');
INSERT INTO orders (id, user_id, total, ts) VALUES
  (1, 1, 50.0, '2026-01-01'), (2, 1, 30.0, '2026-02-01'),
  (3, 2, 100.0, '2026-01-15'), (4, 3, 75.0, '2026-03-01'),
  (5, 4, 200.0, '2026-02-15'), (6, 4, 25.0, '2026-04-01');
"""

TASKS.append({
    "task_id": "sql_join_total_by_country",
    "domain": "sql",
    "prompt": (
        "Write a SQL query that returns each country and the total order amount, "
        "ordered by country alphabetically. Use the schema:\n"
        "  users(id, name, country)\n"
        "  orders(id, user_id, total, ts)\n"
        "Emit ONE query in ```sql ... ```. Filename: query.sql"
    ),
    "workspace_files": {
        "schema.sql": SQL_SCHEMA,
        "expected.txt": "CA|225.0\nUK|75.0\nUS|180.0\n",
    },
    "output_file": "query.sql",
    "output_block_type": "sql",
    "verifier_cmd": "sqlite3 :memory: < schema.sql > /dev/null && sqlite3 -batch -separator '|' -bail $(rm -f t.db && sqlite3 t.db < schema.sql && echo t.db) < query.sql > actual.txt && diff <(sort expected.txt) <(sort actual.txt)",
    "y_star": "query produces the expected per-country totals",
})

TASKS.append({
    "task_id": "sql_top_n_users",
    "domain": "sql",
    "prompt": (
        "Write a SQL query that returns the top 2 users by total order amount, "
        "with columns (name, total_spent), ordered by total_spent descending.\n"
        "Schema: users(id,name,country), orders(id,user_id,total,ts).\n"
        "Emit ```sql ... ```."
    ),
    "workspace_files": {
        "schema.sql": SQL_SCHEMA,
        "expected.txt": "Dave|225.0\nBob|100.0\n",
    },
    "output_file": "query.sql",
    "output_block_type": "sql",
    "verifier_cmd": "rm -f t.db && sqlite3 t.db < schema.sql && sqlite3 -batch -separator '|' t.db < query.sql > actual.txt && diff expected.txt actual.txt",
    "y_star": "top 2 by total_spent: Dave then Bob",
})

TASKS.append({
    "task_id": "sql_window_running_total",
    "domain": "sql",
    "prompt": (
        "Write a SQL query that returns each order's id, ts, total, and a "
        "running_total over all orders ordered by ts. Use a window function.\n"
        "Schema: orders(id, user_id, total, ts).\n"
        "Emit ```sql ... ```."
    ),
    "workspace_files": {
        "schema.sql": SQL_SCHEMA,
        "expected.txt": "1|2026-01-01|50.0|50.0\n3|2026-01-15|100.0|150.0\n2|2026-02-01|30.0|180.0\n5|2026-02-15|200.0|380.0\n4|2026-03-01|75.0|455.0\n6|2026-04-01|25.0|480.0\n",
    },
    "output_file": "query.sql",
    "output_block_type": "sql",
    "verifier_cmd": "rm -f t.db && sqlite3 t.db < schema.sql && sqlite3 -batch -separator '|' t.db < query.sql > actual.txt && diff expected.txt actual.txt",
    "y_star": "running total matches expected.txt exactly",
})

TASKS.append({
    "task_id": "sql_user_with_no_orders",
    "domain": "sql",
    "prompt": (
        "Find users who have ZERO orders. Return their name only, one per row, "
        "ordered alphabetically. Use LEFT JOIN or NOT EXISTS — either is fine.\n"
        "Schema: users(id,name,country), orders(id,user_id,total,ts).\n"
        "Emit ```sql ... ```."
    ),
    "workspace_files": {
        "schema.sql": SQL_SCHEMA + (
            "INSERT INTO users (id, name, country) VALUES (5, 'Eve', 'DE'), (6, 'Frank', 'JP');\n"
        ),
        "expected.txt": "Eve\nFrank\n",
    },
    "output_file": "query.sql",
    "output_block_type": "sql",
    "verifier_cmd": "rm -f t.db && sqlite3 t.db < schema.sql && sqlite3 -batch -separator '|' t.db < query.sql > actual.txt && diff expected.txt actual.txt",
    "y_star": "names of users with no orders, alphabetical",
})

TASKS.append({
    "task_id": "sql_month_revenue",
    "domain": "sql",
    "prompt": (
        "Group orders by month (YYYY-MM extracted from ts) and return "
        "(month, total_revenue) ordered by month ascending.\n"
        "Schema: orders(id, user_id, total, ts).\n"
        "Emit ```sql ... ```."
    ),
    "workspace_files": {
        "schema.sql": SQL_SCHEMA,
        "expected.txt": "2026-01|150.0\n2026-02|230.0\n2026-03|75.0\n2026-04|25.0\n",
    },
    "output_file": "query.sql",
    "output_block_type": "sql",
    "verifier_cmd": "rm -f t.db && sqlite3 t.db < schema.sql && sqlite3 -batch -separator '|' t.db < query.sql > actual.txt && diff expected.txt actual.txt",
    "y_star": "monthly aggregated revenue",
})


# =============================================================================
# JSON SCHEMA (5 tasks)
# =============================================================================

TASKS.append({
    "task_id": "json_user_profile",
    "domain": "json_schema",
    "prompt": (
        "Write a JSON Schema (draft-07) for a user profile object. Required: "
        "name (string), email (string with email format), age (integer >= 0). "
        "Optional: country (string), phone (string).\n\n"
        "Emit ```json ... ``` of the schema. Filename: schema.json"
    ),
    "workspace_files": {
        "valid_samples.json": '[{"name":"A","email":"a@b.com","age":30},{"name":"B","email":"b@c.com","age":25,"country":"US","phone":"555"}]',
        "invalid_samples.json": '[{"email":"a@b.com","age":30},{"name":"A","email":"a@b.com","age":-1},{"name":"A","email":"not_an_email","age":30}]',
    },
    "output_file": "schema.json",
    "output_block_type": "json",
    "verifier_cmd": (
        "python3.11 -c 'import json, jsonschema; s=json.load(open(\"schema.json\")); "
        "valid=json.load(open(\"valid_samples.json\")); "
        "invalid=json.load(open(\"invalid_samples.json\"));\n"
        "from jsonschema import Draft7Validator, FormatChecker\n"
        "v=Draft7Validator(s, format_checker=FormatChecker())\n"
        "[v.validate(item) for item in valid]; print(\"valid ok\")\n"
        "import jsonschema as js\n"
        "for item in invalid:\n"
        "  try: v.validate(item); raise SystemExit(\"FAIL: %r should be invalid\" % item)\n"
        "  except js.ValidationError: pass\n"
        "print(\"all invalid rejected\")'"
    ),
    "y_star": "validates all valid, rejects all invalid samples",
})

TASKS.append({
    "task_id": "json_order_schema",
    "domain": "json_schema",
    "prompt": (
        "Write a draft-07 JSON Schema for an order object. Required fields: "
        "id (integer), items (array of {sku: string, qty: integer >=1}, minItems 1), "
        "total (number > 0).\n\n"
        "Emit ```json ... ``` for schema.json."
    ),
    "workspace_files": {
        "valid_samples.json": '[{"id":1,"items":[{"sku":"A","qty":2}],"total":10.0},{"id":2,"items":[{"sku":"B","qty":1},{"sku":"C","qty":3}],"total":50.5}]',
        "invalid_samples.json": '[{"id":1,"items":[],"total":10.0},{"id":1,"items":[{"sku":"A","qty":0}],"total":10.0},{"id":1,"items":[{"sku":"A","qty":2}],"total":0}]',
    },
    "output_file": "schema.json",
    "output_block_type": "json",
    "verifier_cmd": (
        "python3.11 -c 'import json; from jsonschema import Draft7Validator\n"
        "s=json.load(open(\"schema.json\"))\n"
        "valid=json.load(open(\"valid_samples.json\")); "
        "invalid=json.load(open(\"invalid_samples.json\"))\n"
        "v=Draft7Validator(s)\n"
        "[v.validate(x) for x in valid]\n"
        "import jsonschema as js\n"
        "for x in invalid:\n"
        "  try: v.validate(x); raise SystemExit(\"FAIL: %r should be invalid\" % x)\n"
        "  except js.ValidationError: pass\n"
        "print(\"ok\")'"
    ),
    "y_star": "validates valid, rejects empty items / qty 0 / total 0",
})

TASKS.append({
    "task_id": "json_polymorphic",
    "domain": "json_schema",
    "prompt": (
        "Write a draft-07 JSON Schema for an Event object that is one of two types "
        "(use oneOf). Type 'login' requires {type, user_id, ts}. Type 'purchase' "
        "requires {type, user_id, ts, amount} where amount is number > 0.\n\n"
        "Emit ```json ... ``` for schema.json."
    ),
    "workspace_files": {
        "valid_samples.json": '[{"type":"login","user_id":1,"ts":"2026-01-01T00:00:00Z"},{"type":"purchase","user_id":2,"ts":"2026-01-01T00:00:00Z","amount":50.0}]',
        "invalid_samples.json": '[{"type":"login","user_id":1},{"type":"purchase","user_id":1,"ts":"2026-01-01T00:00:00Z"},{"type":"purchase","user_id":1,"ts":"2026-01-01T00:00:00Z","amount":-5}]',
    },
    "output_file": "schema.json",
    "output_block_type": "json",
    "verifier_cmd": (
        "python3.11 -c 'import json; from jsonschema import Draft7Validator\n"
        "s=json.load(open(\"schema.json\"))\n"
        "valid=json.load(open(\"valid_samples.json\")); "
        "invalid=json.load(open(\"invalid_samples.json\"))\n"
        "v=Draft7Validator(s)\n"
        "[v.validate(x) for x in valid]\n"
        "import jsonschema as js\n"
        "for x in invalid:\n"
        "  try: v.validate(x); raise SystemExit(\"FAIL: %r should be invalid\" % x)\n"
        "  except js.ValidationError: pass\n"
        "print(\"ok\")'"
    ),
    "y_star": "oneOf login/purchase, purchase requires amount > 0",
})

TASKS.append({
    "task_id": "json_address",
    "domain": "json_schema",
    "prompt": (
        "Write a draft-07 JSON Schema for an address object. Required: "
        "street (string), city (string), zip (string matching pattern ^\\d{5}$). "
        "Optional: state (string, exactly 2 uppercase letters).\n\n"
        "Emit ```json ... ``` for schema.json."
    ),
    "workspace_files": {
        "valid_samples.json": '[{"street":"1 Main","city":"X","zip":"12345"},{"street":"2 Main","city":"Y","zip":"99999","state":"CA"}]',
        "invalid_samples.json": '[{"street":"1 Main","zip":"12345"},{"street":"1 Main","city":"X","zip":"1234"},{"street":"1 Main","city":"X","zip":"12345","state":"california"}]',
    },
    "output_file": "schema.json",
    "output_block_type": "json",
    "verifier_cmd": (
        "python3.11 -c 'import json; from jsonschema import Draft7Validator\n"
        "s=json.load(open(\"schema.json\"))\n"
        "valid=json.load(open(\"valid_samples.json\")); "
        "invalid=json.load(open(\"invalid_samples.json\"))\n"
        "v=Draft7Validator(s)\n"
        "[v.validate(x) for x in valid]\n"
        "import jsonschema as js\n"
        "for x in invalid:\n"
        "  try: v.validate(x); raise SystemExit(\"FAIL: %r should be invalid\" % x)\n"
        "  except js.ValidationError: pass\n"
        "print(\"ok\")'"
    ),
    "y_star": "zip pattern + optional 2-letter state",
})

TASKS.append({
    "task_id": "json_nested_company",
    "domain": "json_schema",
    "prompt": (
        "Write a draft-07 JSON Schema for a company object. Required: "
        "name (string), employees (array of objects with required name (string) and "
        "salary (number > 0), minItems 1). Additional properties not allowed at "
        "company root, employees object can have extras.\n\n"
        "Emit ```json ... ``` for schema.json."
    ),
    "workspace_files": {
        "valid_samples.json": '[{"name":"Acme","employees":[{"name":"A","salary":50000}]},{"name":"X","employees":[{"name":"B","salary":1,"role":"eng"}]}]',
        "invalid_samples.json": '[{"name":"Acme","employees":[]},{"name":"Acme","employees":[{"name":"A","salary":0}]},{"name":"Acme","employees":[{"name":"A","salary":50000}],"extra":1}]',
    },
    "output_file": "schema.json",
    "output_block_type": "json",
    "verifier_cmd": (
        "python3.11 -c 'import json; from jsonschema import Draft7Validator\n"
        "s=json.load(open(\"schema.json\"))\n"
        "valid=json.load(open(\"valid_samples.json\")); "
        "invalid=json.load(open(\"invalid_samples.json\"))\n"
        "v=Draft7Validator(s)\n"
        "[v.validate(x) for x in valid]\n"
        "import jsonschema as js\n"
        "for x in invalid:\n"
        "  try: v.validate(x); raise SystemExit(\"FAIL: %r should be invalid\" % x)\n"
        "  except js.ValidationError: pass\n"
        "print(\"ok\")'"
    ),
    "y_star": "company strict, employees flexible, validates nested",
})


# =============================================================================
# REGEX (5 tasks) — verifier runs Python re.findall/match on test fixtures
# =============================================================================

TASKS.append({
    "task_id": "regex_email_capture",
    "domain": "regex",
    "prompt": (
        "Write a Python regex that captures email addresses. The pattern must "
        "match standard 'name@domain.tld' but NOT capture trailing punctuation. "
        "Emit a Python file `pattern.py` with `PATTERN = r'...'`.\n\n"
        "Emit ```python ... ```."
    ),
    "workspace_files": {
        "test_pattern.py": (
            "import re\nfrom pattern import PATTERN\n"
            "def test_one():\n    assert re.findall(PATTERN, 'send to a@b.com today') == ['a@b.com']\n"
            "def test_trailing_punct():\n    assert re.findall(PATTERN, 'see x@y.org.') == ['x@y.org']\n"
            "def test_multi():\n    assert re.findall(PATTERN, 'a@b.co or c@d.io') == ['a@b.co','c@d.io']\n"
            "def test_no_email():\n    assert re.findall(PATTERN, 'no email here') == []\n"
        ),
    },
    "output_file": "pattern.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest test_pattern.py -q --tb=no",
    "y_star": "PATTERN regex matches 4 test cases",
})

TASKS.append({
    "task_id": "regex_phone_us",
    "domain": "regex",
    "prompt": (
        "Write a Python regex for US phone numbers in formats: "
        "'555-123-4567', '(555) 123-4567', '5551234567'. Reject "
        "international (+1-555-...) and partial numbers.\n\n"
        "Emit `pattern.py` with `PATTERN = r'...'` in ```python ... ```."
    ),
    "workspace_files": {
        "test_pattern.py": (
            "import re\nfrom pattern import PATTERN\n"
            "def test_dashes():\n    assert re.findall(PATTERN, 'call 555-123-4567 now') == ['555-123-4567']\n"
            "def test_parens():\n    assert re.findall(PATTERN, '(555) 123-4567') == ['(555) 123-4567']\n"
            "def test_compact():\n    assert re.findall(PATTERN, 'num=5551234567') == ['5551234567']\n"
            "def test_no_intl():\n    assert re.findall(PATTERN, '+1-555-123-4567') in [[], ['555-123-4567']] # either reject or strip prefix is ok\n"
        ),
    },
    "output_file": "pattern.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest test_pattern.py -q --tb=no",
    "y_star": "matches 3 US phone formats",
})

TASKS.append({
    "task_id": "regex_iso_date",
    "domain": "regex",
    "prompt": (
        "Write a Python regex that captures ISO-8601 dates (YYYY-MM-DD) only. "
        "Reject YYYY-M-D (missing zeros) and obvious non-dates.\n\n"
        "Emit `pattern.py` with `PATTERN = r'...'` in ```python ... ```."
    ),
    "workspace_files": {
        "test_pattern.py": (
            "import re\nfrom pattern import PATTERN\n"
            "def test_valid():\n    assert re.findall(PATTERN, 'on 2026-05-18 we shipped') == ['2026-05-18']\n"
            "def test_multi():\n    assert re.findall(PATTERN, '2025-01-01 to 2025-12-31') == ['2025-01-01','2025-12-31']\n"
            "def test_no_zero_pad():\n    assert re.findall(PATTERN, 'date: 2025-1-5') == []\n"
            "def test_not_date():\n    assert re.findall(PATTERN, 'price 12-34-56') == []\n"
        ),
    },
    "output_file": "pattern.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest test_pattern.py -q --tb=no",
    "y_star": "ISO date format, strict zero-padding",
})

TASKS.append({
    "task_id": "regex_url",
    "domain": "regex",
    "prompt": (
        "Write a Python regex that captures http/https URLs. Must match "
        "domains with paths and query strings. Stop at trailing whitespace "
        "or sentence punctuation.\n\n"
        "Emit `pattern.py` with `PATTERN = r'...'` in ```python ... ```."
    ),
    "workspace_files": {
        "test_pattern.py": (
            "import re\nfrom pattern import PATTERN\n"
            "def test_basic():\n    assert re.findall(PATTERN, 'see https://example.com today') == ['https://example.com']\n"
            "def test_path():\n    assert re.findall(PATTERN, 'go to http://a.b/c/d here') == ['http://a.b/c/d']\n"
            "def test_query():\n    assert re.findall(PATTERN, 'fetch https://x.io/y?k=v&z=1 done') == ['https://x.io/y?k=v&z=1']\n"
            "def test_no_url():\n    assert re.findall(PATTERN, 'no link here') == []\n"
        ),
    },
    "output_file": "pattern.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest test_pattern.py -q --tb=no",
    "y_star": "matches URLs with paths and queries",
})

TASKS.append({
    "task_id": "regex_hex_color",
    "domain": "regex",
    "prompt": (
        "Write a Python regex that captures 3-digit OR 6-digit hex color codes "
        "starting with #. E.g. #f0f or #ff00ff but not #abcd.\n\n"
        "Emit `pattern.py` with `PATTERN = r'...'` in ```python ... ```."
    ),
    "workspace_files": {
        "test_pattern.py": (
            "import re\nfrom pattern import PATTERN\n"
            "def test_six():\n    assert re.findall(PATTERN, 'color: #ff00ff;') == ['#ff00ff']\n"
            "def test_three():\n    assert re.findall(PATTERN, 'bg #f0f red') == ['#f0f']\n"
            "def test_invalid_len():\n    assert re.findall(PATTERN, '#abcd') == []\n"
            "def test_uppercase():\n    assert re.findall(PATTERN, '#ABC and #FFFFFF') == ['#ABC', '#FFFFFF']\n"
        ),
    },
    "output_file": "pattern.py",
    "output_block_type": "python",
    "verifier_cmd": "python3.11 -m pytest test_pattern.py -q --tb=no",
    "y_star": "3 or 6 hex digit color codes",
})


# =============================================================================
# Self-verification: 20 tasks, ≥ 4 domains
# =============================================================================

assert len(TASKS) >= 20, f"need ≥ 20 tasks, got {len(TASKS)}"
_domains = sorted({t['domain'] for t in TASKS})
assert len(_domains) >= 4, f"need ≥ 4 domains, got {_domains}"

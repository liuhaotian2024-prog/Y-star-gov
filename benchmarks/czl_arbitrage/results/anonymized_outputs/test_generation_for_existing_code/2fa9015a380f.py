# trial_id: 2fa9015a380f
# (arm name redacted for blind review)

# === data_pipeline.py ===
import json


class PipelineError(Exception):
    pass


class ValidationError(PipelineError):
    pass


def load_records(path):
    """Load JSON list-of-records from path. Raises FileNotFoundError, ValueError on bad JSON / non-list."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f'expected list, got {type(data).__name__}')
    return data


def validate_record(rec, schema):
    """schema = {field_name: type}; raises ValidationError if missing or wrong type."""
    for k, t in schema.items():
        if k not in rec:
            raise ValidationError(f'missing field: {k}')
        if not isinstance(rec[k], t):
            raise ValidationError(f'wrong type for {k}: got {type(rec[k]).__name__}, expected {t.__name__}')


def normalize_email(email):
    """Lowercase + strip. Empty string raises ValueError."""
    s = email.strip().lower()
    if not s:
        raise ValueError('empty email')
    return s


def clean_records(records, schema):
    """Validate, normalize email, drop duplicates by email. Invalid records are skipped silently."""
    seen = set()
    out = []
    for rec in records:
        try:
            validate_record(rec, schema)
        except ValidationError:
            continue
        try:
            email = normalize_email(rec['email'])
        except ValueError:
            continue
        if email in seen:
            continue
        seen.add(email)
        rec_copy = dict(rec)
        rec_copy['email'] = email
        out.append(rec_copy)
    return out


def aggregate_by_domain(records):
    """Count records per email domain. Records must have 'email' key."""
    counts = {}
    for rec in records:
        email = rec['email']
        domain = email.split('@', 1)[1] if '@' in email else 'unknown'
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def pipeline(path, schema):
    """End-to-end: load, clean, aggregate. Returns domain counts."""
    records = load_records(path)
    cleaned = clean_records(records, schema)
    return aggregate_by_domain(cleaned)


# === test_data_pipeline.py ===
import json
import pytest

from data_pipeline import (
    PipelineError,
    ValidationError,
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline,
)


SCHEMA = {'email': str, 'age': int}


def test_pipeline_error_hierarchy():
    assert issubclass(ValidationError, PipelineError)
    assert issubclass(PipelineError, Exception)


# --- load_records ---

def test_load_records_happy(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"a": 1}, {"b": 2}]), encoding='utf-8')
    assert load_records(str(p)) == [{"a": 1}, {"b": 2}]


def test_load_records_empty_list(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("[]", encoding='utf-8')
    assert load_records(str(p)) == []


def test_load_records_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_records(str(tmp_path / "nope.json"))


def test_load_records_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding='utf-8')
    with pytest.raises(ValueError):
        load_records(str(p))


def test_load_records_not_a_list(tmp_path):
    p = tmp_path / "obj.json"
    p.write_text(json.dumps({"a": 1}), encoding='utf-8')
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(p))


# --- validate_record ---

def test_validate_record_ok():
    validate_record({'email': 'a@b.com', 'age': 1}, SCHEMA)


def test_validate_record_missing_field():
    with pytest.raises(ValidationError, match="missing field: age"):
        validate_record({'email': 'a@b.com'}, SCHEMA)


def test_validate_record_wrong_type():
    with pytest.raises(ValidationError, match="wrong type for age"):
        validate_record({'email': 'a@b.com', 'age': 'old'}, SCHEMA)


def test_validate_record_empty_schema():
    validate_record({}, {})


# --- normalize_email ---

def test_normalize_email_basic():
    assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_normalize_email_already_clean():
    assert normalize_email("x@y.z") == "x@y.z"


def test_normalize_email_empty():
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


def test_normalize_email_truly_empty():
    with pytest.raises(ValueError):
        normalize_email("")


# --- clean_records ---

def test_clean_records_happy():
    recs = [
        {'email': 'A@x.com', 'age': 1},
        {'email': 'b@x.com', 'age': 2},
    ]
    out = clean_records(recs, SCHEMA)
    assert len(out) == 2
    assert out[0]['email'] == 'a@x.com'
    assert out[1]['email'] == 'b@x.com'


def test_clean_records_drops_duplicates():
    recs = [
        {'email': 'a@x.com', 'age': 1},
        {'email': 'A@x.com', 'age': 2},
    ]
    out = clean_records(recs, SCHEMA)
    assert len(out) == 1
    assert out[0]['email'] == 'a@x.com'


def test_clean_records_skips_invalid():
    recs = [
        {'email': 'a@x.com'},  # missing age
        {'email': 'b@x.com', 'age': 'bad'},  # wrong type
        {'email': 'c@x.com', 'age': 3},
    ]
    out = clean_records(recs, SCHEMA)
    assert len(out) == 1
    assert out[0]['email'] == 'c@x.com'


def test_clean_records_skips_empty_email():
    recs = [
        {'email': '   ', 'age': 1},
        {'email': 'b@x.com', 'age': 2},
    ]
    out = clean_records(recs, SCHEMA)
    assert len(out) == 1
    assert out[0]['email'] == 'b@x.com'


def test_clean_records_empty_input():
    assert clean_records([], SCHEMA) == []


def test_clean_records_does_not_mutate_input():
    rec = {'email': 'A@x.com', 'age': 1}
    clean_records([rec], SCHEMA)
    assert rec['email'] == 'A@x.com'


# --- aggregate_by_domain ---

def test_aggregate_by_domain_basic():
    recs = [
        {'email': 'a@x.com'},
        {'email': 'b@x.com'},
        {'email': 'c@y.com'},
    ]
    assert aggregate_by_domain(recs) == {'x.com': 2, 'y.com': 1}


def test_aggregate_by_domain_unknown():
    recs = [{'email': 'noatsign'}]
    assert aggregate_by_domain(recs) == {'unknown': 1}


def test_aggregate_by_domain_empty():
    assert aggregate_by_domain([]) == {}


def test_aggregate_by_domain_missing_email_key():
    with pytest.raises(KeyError):
        aggregate_by_domain([{'foo': 'bar'}])


# --- pipeline ---

def test_pipeline_end_to_end(tmp_path):
    data = [
        {'email': 'A@x.com', 'age': 1},
        {'email': 'a@x.com', 'age': 2},  # dup
        {'email': 'b@y.com', 'age': 3},
        {'email': 'bad', 'age': 'wrong'},  # invalid type
        {'email': 'c@x.com'},  # missing age
    ]
    p = tmp_path / "d.json"
    p.write_text(json.dumps(data), encoding='utf-8')
    result = pipeline(str(p), SCHEMA)
    assert result == {'x.com': 1, 'y.com': 1}


def test_pipeline_empty_file(tmp_path):
    p = tmp_path / "d.json"
    p.write_text("[]", encoding='utf-8')
    assert pipeline(str(p), SCHEMA) == {}


def test_pipeline_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline(str(tmp_path / "nope.json"), SCHEMA)

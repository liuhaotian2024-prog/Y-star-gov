# trial_id: 0a2ca6ebd0e9
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


# ---------------------------------------------------------------------------
# load_records
# ---------------------------------------------------------------------------

def test_load_records_happy(tmp_path):
    p = tmp_path / "data.json"
    data = [{"email": "a@b.com"}, {"email": "c@d.com"}]
    p.write_text(json.dumps(data), encoding="utf-8")
    assert load_records(str(p)) == data


def test_load_records_file_not_found(tmp_path):
    p = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError):
        load_records(str(p))


def test_load_records_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_records(str(p))


def test_load_records_not_list(tmp_path):
    p = tmp_path / "obj.json"
    p.write_text('{"a":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(p))


# ---------------------------------------------------------------------------
# validate_record
# ---------------------------------------------------------------------------

def test_validate_record_happy():
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": 30}
    validate_record(rec, schema)  # no exception


def test_validate_record_missing_field():
    schema = {"name": str, "age": int}
    rec = {"name": "Bob"}
    with pytest.raises(ValidationError, match="missing field: age"):
        validate_record(rec, schema)


def test_validate_record_wrong_type():
    schema = {"name": str, "age": int}
    rec = {"name": "Charlie", "age": "old"}
    with pytest.raises(ValidationError, match="wrong type for age"):
        validate_record(rec, schema)


def test_validate_record_empty_schema():
    schema = {}
    rec = {"anything": 1}
    validate_record(rec, schema)  # no exception


# ---------------------------------------------------------------------------
# normalize_email
# ---------------------------------------------------------------------------

def test_normalize_email_happy():
    assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"


def test_normalize_email_already_normalized():
    assert normalize_email("bob@test.org") == "bob@test.org"


def test_normalize_email_empty_raises():
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


# ---------------------------------------------------------------------------
# clean_records
# ---------------------------------------------------------------------------

def test_clean_records_happy():
    schema = {"email": str, "name": str}
    records = [
        {"email": "A@B.COM", "name": "Alice"},
        {"email": "c@d.org", "name": "Bob"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "c@d.org"


def test_clean_records_duplicates():
    schema = {"email": str}
    records = [
        {"email": "A@B.COM"},
        {"email": "a@b.com"},
        {"email": "c@d.org"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "c@d.org"


def test_clean_records_skips_invalid_schema():
    schema = {"email": str, "name": str}
    records = [
        {"email": "a@b.com", "name": "Alice"},
        {"email": "c@d.org"},  # missing name
        {"email": "e@f.com", "name": 42},  # wrong type
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "a@b.com"


def test_clean_records_skips_empty_email():
    schema = {"email": str}
    records = [
        {"email": "a@b.com"},
        {"email": "   "},
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "a@b.com"


def test_clean_records_empty_input():
    schema = {"email": str}
    result = clean_records([], schema)
    assert result == []


def test_clean_records_all_skipped():
    schema = {"email": str}
    records = [{"email": ""}, {"email": "   "}]
    result = clean_records(records, schema)
    assert result == []


# ---------------------------------------------------------------------------
# aggregate_by_domain
# ---------------------------------------------------------------------------

def test_aggregate_by_domain_happy():
    records = [
        {"email": "a@gmail.com"},
        {"email": "b@gmail.com"},
        {"email": "c@yahoo.com"},
    ]
    result = aggregate_by_domain(records)
    assert result == {"gmail.com": 2, "yahoo.com": 1}


def test_aggregate_by_domain_no_at_sign():
    records = [{"email": "noatsign"}]
    result = aggregate_by_domain(records)
    assert result == {"unknown": 1}


def test_aggregate_by_domain_empty():
    result = aggregate_by_domain([])
    assert result == {}


# ---------------------------------------------------------------------------
# pipeline (end-to-end)
# ---------------------------------------------------------------------------

def test_pipeline_happy(tmp_path):
    p = tmp_path / "data.json"
    data = [
        {"email": "Alice@Example.COM", "name": "Alice"},
        {"email": "bob@test.org", "name": "Bob"},
        {"email": "alice@example.com", "name": "Alice Dup"},  # duplicate
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"example.com": 1, "test.org": 1}


def test_pipeline_invalid_records_skipped(tmp_path):
    p = tmp_path / "data.json"
    data = [
        {"email": "a@b.com", "name": "A"},
        {"email": "c@d.com"},  # missing name
        {"email": "e@f.com", "name": 42},  # wrong type
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"b.com": 1}


def test_pipeline_empty_file(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    schema = {"email": str}
    result = pipeline(str(p), schema)
    assert result == {}


def test_pipeline_file_not_found(tmp_path):
    p = tmp_path / "nope.json"
    schema = {"email": str}
    with pytest.raises(FileNotFoundError):
        pipeline(str(p), schema)


def test_pipeline_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{{{", encoding="utf-8")
    schema = {"email": str}
    with pytest.raises(ValueError):
        pipeline(str(p), schema)

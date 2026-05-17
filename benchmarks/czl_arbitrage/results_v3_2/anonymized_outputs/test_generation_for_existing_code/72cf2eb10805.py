# trial_id: 72cf2eb10805
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

def test_load_records_valid(tmp_path):
    """Happy path: valid JSON list."""
    data = [{"email": "a@b.com"}, {"email": "c@d.com"}]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert load_records(str(p)) == data


def test_load_records_file_not_found(tmp_path):
    """Missing file raises FileNotFoundError."""
    p = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError):
        load_records(str(p))


def test_load_records_invalid_json(tmp_path):
    """Bad JSON raises ValueError (from json.load)."""
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_records(str(p))


def test_load_records_not_list(tmp_path):
    """JSON that is not a list raises ValueError."""
    p = tmp_path / "obj.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(p))


def test_load_records_empty_list(tmp_path):
    """Empty list is valid."""
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    assert load_records(str(p)) == []


# ---------------------------------------------------------------------------
# validate_record
# ---------------------------------------------------------------------------

def test_validate_record_ok():
    """All fields present and correct types."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": 30}
    validate_record(rec, schema)  # should not raise


def test_validate_record_missing_field():
    """Missing field raises ValidationError."""
    schema = {"name": str, "age": int}
    rec = {"name": "Bob"}
    with pytest.raises(ValidationError, match="missing field: age"):
        validate_record(rec, schema)


def test_validate_record_wrong_type():
    """Wrong type raises ValidationError."""
    schema = {"name": str, "age": int}
    rec = {"name": "Charlie", "age": "thirty"}
    with pytest.raises(ValidationError, match="wrong type for age"):
        validate_record(rec, schema)


def test_validate_record_empty_schema():
    """Empty schema always passes."""
    validate_record({"anything": 1}, {})


# ---------------------------------------------------------------------------
# normalize_email
# ---------------------------------------------------------------------------

def test_normalize_email_typical():
    assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"


def test_normalize_email_already_normalized():
    assert normalize_email("bob@test.org") == "bob@test.org"


def test_normalize_email_empty_raises():
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


def test_normalize_email_empty_string():
    with pytest.raises(ValueError):
        normalize_email("")


# ---------------------------------------------------------------------------
# clean_records
# ---------------------------------------------------------------------------

def test_clean_records_happy():
    schema = {"email": str, "name": str}
    records = [
        {"email": "  A@B.COM  ", "name": "Alice"},
        {"email": "a@b.com", "name": "Alice2"},  # duplicate after normalize
        {"email": "c@d.com", "name": "Charlie"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "c@d.com"


def test_clean_records_skips_invalid_schema():
    """Records missing required fields are skipped."""
    schema = {"email": str, "name": str}
    records = [
        {"email": "a@b.com", "name": "Alice"},
        {"name": "Bob"},  # missing email
        {"email": "c@d.com", "name": "Charlie"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2


def test_clean_records_skips_bad_email():
    """Records with empty email after normalize are skipped."""
    schema = {"email": str}
    records = [
        {"email": "  "},
        {"email": "good@example.com"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "good@example.com"


def test_clean_records_empty_input():
    assert clean_records([], {"email": str}) == []


def test_clean_records_all_duplicates():
    schema = {"email": str}
    records = [
        {"email": "a@b.com"},
        {"email": "A@B.COM"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 1


def test_clean_records_preserves_other_fields():
    schema = {"email": str, "id": int}
    records = [
        {"email": "x@y.com", "id": 1},
        {"email": "X@Y.COM", "id": 2},  # duplicate email, first kept
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["id"] == 1  # first occurrence kept


# ---------------------------------------------------------------------------
# aggregate_by_domain
# ---------------------------------------------------------------------------

def test_aggregate_by_domain_basic():
    records = [
        {"email": "a@gmail.com"},
        {"email": "b@gmail.com"},
        {"email": "c@outlook.com"},
    ]
    assert aggregate_by_domain(records) == {"gmail.com": 2, "outlook.com": 1}


def test_aggregate_by_domain_no_at_sign():
    """Email without '@' gets domain 'unknown'."""
    records = [{"email": "noatsign"}]
    assert aggregate_by_domain(records) == {"unknown": 1}


def test_aggregate_by_domain_empty():
    assert aggregate_by_domain([]) == {}


def test_aggregate_by_domain_multiple_domains():
    records = [
        {"email": "a@a.com"},
        {"email": "b@b.com"},
        {"email": "c@a.com"},
    ]
    assert aggregate_by_domain(records) == {"a.com": 2, "b.com": 1}


# ---------------------------------------------------------------------------
# pipeline (integration)
# ---------------------------------------------------------------------------

def test_pipeline_happy(tmp_path):
    schema = {"email": str, "name": str}
    data = [
        {"email": "  Alice@Example.COM  ", "name": "Alice"},
        {"email": "bob@test.org", "name": "Bob"},
        {"email": "alice@example.com", "name": "Alice2"},  # duplicate
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    result = pipeline(str(p), schema)
    assert result == {"example.com": 1, "test.org": 1}


def test_pipeline_empty_file(tmp_path):
    schema = {"email": str}
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    assert pipeline(str(p), schema) == {}


def test_pipeline_all_invalid(tmp_path):
    """All records fail validation -> empty result."""
    schema = {"email": str, "name": str}
    data = [
        {"email": "a@b.com"},  # missing name
        {"name": "Bob"},       # missing email
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert pipeline(str(p), schema) == {}


def test_pipeline_file_not_found(tmp_path):
    """FileNotFoundError propagates."""
    with pytest.raises(FileNotFoundError):
        pipeline(str(tmp_path / "nope.json"), {"email": str})


def test_pipeline_invalid_json(tmp_path):
    """ValueError propagates on bad JSON."""
    p = tmp_path / "bad.json"
    p.write_text("{{{", encoding="utf-8")
    with pytest.raises(ValueError):
        pipeline(str(p), {"email": str})

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

def test_load_records_happy(tmp_path):
    """Valid JSON list-of-records."""
    data = [{"email": "a@b.com"}, {"email": "c@d.com"}]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert load_records(str(p)) == data


def test_load_records_file_not_found():
    """Missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_records("/nonexistent/path.json")


def test_load_records_invalid_json(tmp_path):
    """Bad JSON raises ValueError."""
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

def test_validate_record_happy():
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
    rec = {"name": "Charlie", "age": "old"}
    with pytest.raises(ValidationError, match="wrong type for age"):
        validate_record(rec, schema)


def test_validate_record_empty_schema():
    """Empty schema always passes."""
    validate_record({"anything": 1}, {})


# ---------------------------------------------------------------------------
# normalize_email
# ---------------------------------------------------------------------------

def test_normalize_email_happy():
    """Lowercase and strip."""
    assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"


def test_normalize_email_already_normalized():
    """Already clean."""
    assert normalize_email("a@b.com") == "a@b.com"


def test_normalize_email_empty_raises():
    """Empty string raises ValueError."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("")


def test_normalize_email_whitespace_only_raises():
    """Whitespace-only raises ValueError."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


# ---------------------------------------------------------------------------
# clean_records
# ---------------------------------------------------------------------------

def test_clean_records_happy():
    """Basic happy path."""
    schema = {"email": str, "name": str}
    records = [
        {"email": "A@B.COM", "name": "Alice"},
        {"email": "c@d.com", "name": "Bob"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "c@d.com"


def test_clean_records_duplicate_email():
    """Duplicate emails are dropped (first kept)."""
    schema = {"email": str}
    records = [
        {"email": "a@b.com"},
        {"email": "A@B.COM"},
        {"email": "a@b.com"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "a@b.com"


def test_clean_records_skips_invalid():
    """Records failing validation are skipped."""
    schema = {"email": str, "name": str}
    records = [
        {"email": "a@b.com", "name": "Alice"},
        {"email": "bad"},  # missing 'name'
        {"email": "c@d.com", "name": "Bob"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2


def test_clean_records_skips_bad_email():
    """Records with empty email after normalization are skipped."""
    schema = {"email": str}
    records = [
        {"email": "a@b.com"},
        {"email": ""},
        {"email": "   "},
    ]
    result = clean_records(records, schema)
    assert len(result) == 1


def test_clean_records_empty_input():
    """Empty list returns empty list."""
    assert clean_records([], {}) == []


def test_clean_records_preserves_other_fields():
    """Other fields are kept in the output record."""
    schema = {"email": str, "score": int}
    records = [{"email": "X@Y.COM", "score": 42}]
    result = clean_records(records, schema)
    assert result[0]["score"] == 42


# ---------------------------------------------------------------------------
# aggregate_by_domain
# ---------------------------------------------------------------------------

def test_aggregate_by_domain_happy():
    """Count per domain."""
    records = [
        {"email": "a@gmail.com"},
        {"email": "b@gmail.com"},
        {"email": "c@yahoo.com"},
    ]
    assert aggregate_by_domain(records) == {"gmail.com": 2, "yahoo.com": 1}


def test_aggregate_by_domain_no_at_sign():
    """Email without '@' -> 'unknown'."""
    records = [{"email": "noatsign"}]
    assert aggregate_by_domain(records) == {"unknown": 1}


def test_aggregate_by_domain_empty():
    """Empty list returns empty dict."""
    assert aggregate_by_domain([]) == {}


def test_aggregate_by_domain_single():
    """Single record."""
    records = [{"email": "a@b.com"}]
    assert aggregate_by_domain(records) == {"b.com": 1}


# ---------------------------------------------------------------------------
# pipeline (end-to-end)
# ---------------------------------------------------------------------------

def test_pipeline_happy(tmp_path):
    """End-to-end happy path."""
    data = [
        {"email": "A@GMAIL.COM", "name": "Alice"},
        {"email": "b@GMAIL.COM", "name": "Bob"},
        {"email": "c@yahoo.com", "name": "Charlie"},
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"gmail.com": 2, "yahoo.com": 1}


def test_pipeline_skips_invalid(tmp_path):
    """Invalid records are skipped in pipeline."""
    data = [
        {"email": "a@b.com", "name": "Alice"},
        {"email": "bad"},  # missing name
        {"email": "c@d.com", "name": "Bob"},
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"b.com": 1, "d.com": 1}


def test_pipeline_empty_file(tmp_path):
    """Empty list in file -> empty dict."""
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    result = pipeline(str(p), {"email": str})
    assert result == {}


def test_pipeline_file_not_found():
    """Missing file propagates FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        pipeline("/nonexistent.json", {"email": str})


def test_pipeline_invalid_json(tmp_path):
    """Invalid JSON propagates ValueError."""
    p = tmp_path / "bad.json"
    p.write_text("{{{", encoding="utf-8")
    with pytest.raises(ValueError):
        pipeline(str(p), {"email": str})

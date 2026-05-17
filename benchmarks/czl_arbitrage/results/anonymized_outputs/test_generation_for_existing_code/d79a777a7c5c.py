# trial_id: d79a777a7c5c
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


# ---------------------------------------------------------------------------
# validate_record
# ---------------------------------------------------------------------------

def test_validate_record_ok():
    """All fields present and correct types."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": 30}
    # should not raise
    validate_record(rec, schema)


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


# ---------------------------------------------------------------------------
# normalize_email
# ---------------------------------------------------------------------------

def test_normalize_email_ok():
    """Happy path: lowercased and stripped."""
    assert normalize_email("  A@B.COM  ") == "a@b.com"


def test_normalize_email_empty_raises():
    """Empty string after strip raises ValueError."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


# ---------------------------------------------------------------------------
# clean_records
# ---------------------------------------------------------------------------

def test_clean_records_happy():
    """Valid records are cleaned, email normalized, duplicates removed."""
    schema = {"email": str, "name": str}
    records = [
        {"email": "A@B.COM", "name": "Alice"},
        {"email": "a@b.com", "name": "Alice"},   # duplicate email
        {"email": "C@D.COM", "name": "Charlie"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "c@d.com"


def test_clean_records_skip_invalid():
    """Records failing validation are skipped."""
    schema = {"email": str, "name": str}
    records = [
        {"email": "a@b.com", "name": "Alice"},
        {"name": "Bob"},                     # missing email
        {"email": 123, "name": "Charlie"},   # wrong type
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "a@b.com"


def test_clean_records_skip_empty_email():
    """Records with empty email after normalize are skipped."""
    schema = {"email": str, "name": str}
    records = [
        {"email": "  ", "name": "Nobody"},
        {"email": "a@b.com", "name": "Alice"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "a@b.com"


def test_clean_records_empty_input():
    """Empty list returns empty list."""
    assert clean_records([], {"email": str}) == []


# ---------------------------------------------------------------------------
# aggregate_by_domain
# ---------------------------------------------------------------------------

def test_aggregate_by_domain_happy():
    """Counts per domain."""
    records = [
        {"email": "a@gmail.com"},
        {"email": "b@gmail.com"},
        {"email": "c@yahoo.com"},
    ]
    assert aggregate_by_domain(records) == {"gmail.com": 2, "yahoo.com": 1}


def test_aggregate_by_domain_no_at():
    """Email without '@' gets domain 'unknown'."""
    records = [{"email": "noatsign"}]
    assert aggregate_by_domain(records) == {"unknown": 1}


def test_aggregate_by_domain_empty():
    """Empty list returns empty dict."""
    assert aggregate_by_domain([]) == {}


# ---------------------------------------------------------------------------
# pipeline (end-to-end)
# ---------------------------------------------------------------------------

def test_pipeline_happy(tmp_path):
    """Full pipeline with valid data."""
    data = [
        {"email": "A@GMAIL.COM", "name": "Alice"},
        {"email": "a@gmail.com", "name": "Alice Dup"},  # duplicate
        {"email": "B@YAHOO.COM", "name": "Bob"},
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"gmail.com": 1, "yahoo.com": 1}


def test_pipeline_empty_file(tmp_path):
    """Empty JSON list yields empty counts."""
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    schema = {"email": str, "name": str}
    assert pipeline(str(p), schema) == {}


def test_pipeline_all_invalid(tmp_path):
    """All records invalid -> empty counts."""
    data = [
        {"name": "NoEmail"},
        {"email": 42, "name": "BadType"},
    ]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    assert pipeline(str(p), schema) == {}

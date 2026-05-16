# trial_id: 64d2ed434926
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
import pytest
import json
from data_pipeline import (
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline,
    PipelineError,
    ValidationError,
)


# --- load_records tests ---

def test_load_records_success(tmp_path):
    """Test loading valid JSON list from file."""
    data = [{"a": 1}, {"b": 2}]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data))
    result = load_records(str(p))
    assert result == data


def test_load_records_file_not_found():
    """Test FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        load_records("nonexistent.json")


def test_load_records_invalid_json(tmp_path):
    """Test ValueError for malformed JSON."""
    p = tmp_path / "bad.json"
    p.write_text("{invalid")
    with pytest.raises(json.JSONDecodeError):
        load_records(str(p))


def test_load_records_non_list(tmp_path):
    """Test ValueError when JSON root is not a list."""
    p = tmp_path / "notalist.json"
    p.write_text(json.dumps({"a": 1}))
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(p))


# --- validate_record tests ---

def test_validate_record_success():
    """Test valid record passes validation."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": 30}
    validate_record(rec, schema)  # Should not raise


def test_validate_record_missing_field():
    """Test ValidationError for missing field."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice"}
    with pytest.raises(ValidationError, match="missing field"):
        validate_record(rec, schema)


def test_validate_record_wrong_type():
    """Test ValidationError for wrong type."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": "thirty"}
    with pytest.raises(ValidationError, match="wrong type"):
        validate_record(rec, schema)


# --- normalize_email tests ---

def test_normalize_email_success():
    """Test email normalization (lowercase, strip)."""
    assert normalize_email("  User@Example.COM  ") == "user@example.com"


def test_normalize_email_empty():
    """Test ValueError for empty/whitespace-only email."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


# --- clean_records tests ---

def test_clean_records_empty():
    """Test empty input returns empty list."""
    result = clean_records([], {"email": str})
    assert result == []


def test_clean_records_skips_invalid():
    """Test invalid records are skipped silently."""
    schema = {"email": str, "name": str}
    records = [
        {"email": "a@b.com", "name": "A"},  # valid
        {"email": "c@d.com"},               # missing name -> skip
        {"email": "", "name": "C"},          # empty email -> skip
        {"email": "e@f.com", "name": "E"},  # valid
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "e@f.com"


def test_clean_records_deduplicates():
    """Test duplicate emails are removed (case-insensitive)."""
    schema = {"email": str}
    records = [
        {"email": "a@b.com"},
        {"email": "A@B.COM"},  # duplicate after normalization
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "a@b.com"


def test_clean_records_normalizes():
    """Test email normalization in clean_records."""
    schema = {"email": str}
    records = [{"email": "  User@Example.COM  "}]
    result = clean_records(records, schema)
    assert result[0]["email"] == "user@example.com"


# --- aggregate_by_domain tests ---

def test_aggregate_by_domain_success():
    """Test counting records per domain."""
    records = [
        {"email": "a@x.com"},
        {"email": "b@y.com"},
        {"email": "c@x.com"},
    ]
    result = aggregate_by_domain(records)
    assert result == {"x.com": 2, "y.com": 1}


def test_aggregate_by_domain_no_at():
    """Test 'unknown' domain for emails without @."""
    records = [{"email": "invalid"}, {"email": "test@x.com"}]
    result = aggregate_by_domain(records)
    assert result == {"unknown": 1, "x.com": 1}


def test_aggregate_by_domain_empty():
    """Test empty input returns empty dict."""
    result = aggregate_by_domain([])
    assert result == {}


# --- pipeline tests ---

def test_pipeline_success(tmp_path):
    """Test end-to-end pipeline with valid data."""
    data = [
        {"email": "a@x.com", "name": "A"},
        {"email": "b@x.com", "name": "B"},
        {"email": "c@y.com", "name": "C"},
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data))
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"x.com": 2, "y.com": 1}


def test_pipeline_file_not_found():
    """Test pipeline raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        pipeline("nonexistent.json", {"email": str})


def test_pipeline_invalid_records(tmp_path):
    """Test pipeline skips invalid records silently."""
    data = [
        {"email": "a@x.com", "name": "A"},
        {"name": "B"},  # missing email -> skip
        {"email": "c@x.com", "name": "C"},
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data))
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"x.com": 2}


def test_pipeline_deduplicates(tmp_path):
    """Test pipeline deduplicates by normalized email."""
    data = [
        {"email": "a@x.com", "name": "A"},
        {"email": "A@X.COM", "name": "A2"},
    ]
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data))
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"x.com": 1}

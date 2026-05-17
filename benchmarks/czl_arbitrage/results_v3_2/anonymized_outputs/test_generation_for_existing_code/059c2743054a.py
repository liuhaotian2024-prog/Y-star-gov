# trial_id: 059c2743054a
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
from pathlib import Path
from data_pipeline import (
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline,
    ValidationError,
    PipelineError,
)


# === Test load_records ===

def test_load_records_file_not_found():
    """Should raise FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        load_records("nonexistent.json")


def test_load_records_invalid_json(tmp_path):
    """Should raise ValueError for invalid JSON."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{ invalid json }")
    with pytest.raises(json.JSONDecodeError):
        load_records(str(bad_file))


def test_load_records_not_a_list(tmp_path):
    """Should raise ValueError when JSON root is not a list."""
    file = tmp_path / "dict.json"
    file.write_text('{"key": "value"}')
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(file))


def test_load_records_success(tmp_path):
    """Should load valid JSON list successfully."""
    data = [{"id": 1}, {"id": 2}]
    file = tmp_path / "data.json"
    file.write_text(json.dumps(data))
    result = load_records(str(file))
    assert result == data


# === Test validate_record ===

def test_validate_record_missing_field():
    """Should raise ValidationError when field is missing."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice"}  # missing age
    with pytest.raises(ValidationError, match="missing field"):
        validate_record(rec, schema)


def test_validate_record_wrong_type():
    """Should raise ValidationError when field has wrong type."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": "thirty"}  # should be int
    with pytest.raises(ValidationError, match="wrong type"):
        validate_record(rec, schema)


def test_validate_record_success():
    """Should pass for valid record."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": 30}
    validate_record(rec, schema)  # should not raise


def test_validate_record_multiple_fields_all_wrong():
    """Should raise on first wrong type encountered."""
    schema = {"name": str, "age": int, "email": str}
    rec = {"name": "Bob", "age": 25, "email": 123}
    with pytest.raises(ValidationError, match="wrong type"):
        validate_record(rec, schema)


# === Test normalize_email ===

def test_normalize_email_empty():
    """Should raise ValueError for empty email after stripping."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


def test_normalize_email_whitespace():
    """Should strip whitespace and lowercase."""
    assert normalize_email("  Test@Example.COM  ") == "test@example.com"


def test_normalize_email_already_normal():
    """Should handle already normalized email."""
    assert normalize_email("user@domain.org") == "user@domain.org"


# === Test clean_records ===

def test_clean_records_valid():
    """Should clean and return valid records."""
    records = [
        {"name": "Alice", "email": "ALICE@EXAMPLE.COM"},
        {"name": "Bob", "email": "bob@example.com"},
    ]
    schema = {"name": str, "email": str}
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "alice@example.com"
    assert result[1]["email"] == "bob@example.com"


def test_clean_records_skip_invalid():
    """Should silently skip invalid records."""
    records = [
        {"name": "Alice", "email": "alice@example.com"},  # valid
        {"name": "Bob"},  # missing email
        {"name": "Carol", "email": "  "},  # empty email
    ]
    schema = {"name": str, "email": str}
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["name"] == "Alice"


def test_clean_records_duplicates():
    """Should keep only first occurrence of duplicate emails."""
    records = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "ALICE", "email": "ALICE@example.com"},
        {"name": "Another Alice", "email": "alice@example.com"},
    ]
    schema = {"name": str, "email": str}
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["email"] == "alice@example.com"


def test_clean_records_no_duplicates_all_unique():
    """Should keep all records when no duplicates."""
    records = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob", "email": "bob@example.com"},
        {"name": "Carol", "email": "carol@example.com"},
    ]
    schema = {"name": str, "email": str}
    result = clean_records(records, schema)
    assert len(result) == 3


def test_clean_records_empty_list():
    """Should handle empty list."""
    records = []
    schema = {"name": str, "email": str}
    result = clean_records(records, schema)
    assert result == []


def test_clean_records_all_invalid():
    """Should return empty list when all records invalid."""
    records = [
        {"name": "Alice"},  # missing email
        {"name": "Bob", "email": 123},  # wrong type
    ]
    schema = {"name": str, "email": str}
    result = clean_records(records, schema)
    assert result == []


# === Test aggregate_by_domain ===

def test_aggregate_by_domain():
    """Should count records per domain."""
    records = [
        {"email": "alice@example.com"},
        {"email": "bob@test.org"},
        {"email": "carol@example.com"},
    ]
    result = aggregate_by_domain(records)
    assert result == {"example.com": 2, "test.org": 1}


def test_aggregate_by_domain_no_at():
    """Should use 'unknown' for emails without @."""
    records = [
        {"email": "not-an-email"},
        {"email": "also@invalid"},
    ]
    result = aggregate_by_domain(records)
    assert result == {"unknown": 1, "invalid": 1}


def test_aggregate_by_domain_empty_list():
    """Should return empty dict for empty list."""
    result = aggregate_by_domain([])
    assert result == {}


def test_aggregate_by_domain_single_record():
    """Should handle single record."""
    records = [{"email": "user@domain.com"}]
    result = aggregate_by_domain(records)
    assert result == {"domain.com": 1}


# === Test pipeline ===

def test_pipeline_end_to_end(tmp_path):
    """Should run full pipeline successfully."""
    data = [
        {"name": "Alice", "email": "ALICE@EXAMPLE.COM"},
        {"name": "Bob", "email": "bob@example.com"},
        {"name": "Bob Again", "email": "bob@example.com"},  # duplicate
    ]
    file = tmp_path / "input.json"
    file.write_text(json.dumps(data))
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file), schema)
    
    assert result == {"example.com": 2}


def test_pipeline_with_invalid_records(tmp_path):
    """Should handle invalid records in pipeline."""
    data = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "NoEmail"},  # invalid
        {"name": "Bob", "email": "  "},  # invalid
    ]
    file = tmp_path / "input.json"
    file.write_text(json.dumps(data))
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file), schema)
    
    assert result == {"example.com": 1}


def test_pipeline_empty_file(tmp_path):
    """Should handle empty list in pipeline."""
    file = tmp_path / "empty.json"
    file.write_text("[]")
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file), schema)
    
    assert result == {}


def test_pipeline_file_not_found():
    """Should propagate FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        pipeline("missing.json", {"name": str})


# === Additional edge cases ===

def test_normalize_email_special_chars():
    """Should handle email with special characters."""
    assert normalize_email("User.Name+Tag@Example-CoM.COM") == "user.name+tag@example-com.com"


def test_aggregate_by_domain_multiple_same_domain():
    """Should correctly count multiple records from same domain."""
    records = [{"email": f"user{i}@test.com"} for i in range(5)]
    result = aggregate_by_domain(records)
    assert result == {"test.com": 5}


def test_validate_record_schema_with_multiple_types():
    """Should validate schema with mixed types."""
    schema = {"name": str, "age": int, "active": bool}
    
    # valid
    validate_record({"name": "X", "age": 10, "active": True}, schema)
    
    # invalid bool
    with pytest.raises(ValidationError):
        validate_record({"name": "X", "age": 10, "active": "yes"}, schema)

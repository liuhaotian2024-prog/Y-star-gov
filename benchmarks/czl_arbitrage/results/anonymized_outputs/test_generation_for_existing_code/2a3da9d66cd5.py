# trial_id: 2a3da9d66cd5
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


# === Tests for load_records ===

def test_load_records_valid_json_list(tmp_path):
    """Test loading a valid JSON list from file."""
    data = [{"name": "Alice"}, {"name": "Bob"}]
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps(data))
    
    result = load_records(str(file_path))
    assert result == data


def test_load_records_file_not_found():
    """Test FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        load_records("nonexistent.json")


def test_load_records_invalid_json(tmp_path):
    """Test ValueError for invalid JSON content."""
    file_path = tmp_path / "invalid.json"
    file_path.write_text("{not valid json}")
    
    with pytest.raises(json.JSONDecodeError):
        load_records(str(file_path))


def test_load_records_non_list_json(tmp_path):
    """Test ValueError when JSON root is not a list."""
    file_path = tmp_path / "object.json"
    file_path.write_text(json.dumps({"key": "value"}))
    
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(file_path))


# === Tests for validate_record ===

def test_validate_record_valid():
    """Test validation passes for valid record."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": 30}
    # Should not raise
    validate_record(rec, schema)


def test_validate_record_missing_field():
    """Test ValidationError for missing field."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice"}
    
    with pytest.raises(ValidationError, match="missing field"):
        validate_record(rec, schema)


def test_validate_record_wrong_type():
    """Test ValidationError for wrong type."""
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": "30"}
    
    with pytest.raises(ValidationError, match="wrong type"):
        validate_record(rec, schema)


def test_validate_record_multiple_missing_fields():
    """Test ValidationError reports first missing field."""
    schema = {"name": str, "age": int, "email": str}
    rec = {"age": 30}
    
    with pytest.raises(ValidationError, match="missing field: name"):
        validate_record(rec, schema)


# === Tests for normalize_email ===

def test_normalize_email_valid():
    """Test normalization of valid email."""
    assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"


def test_normalize_email_empty():
    """Test ValueError for empty string."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("")


def test_normalize_email_whitespace_only():
    """Test ValueError for whitespace-only string."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


# === Tests for clean_records ===

def test_clean_records_valid():
    """Test cleaning valid records."""
    schema = {"name": str, "email": str}
    records = [
        {"name": "Alice", "email": "ALICE@EXAMPLE.COM"},
        {"name": "Bob", "email": "bob@example.com"}
    ]
    
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "alice@example.com"
    assert result[1]["email"] == "bob@example.com"


def test_clean_records_deduplication():
    """Test that duplicate emails are removed (case-insensitive)."""
    schema = {"name": str, "email": str}
    records = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "ALICE", "email": "ALICE@EXAMPLE.COM"},
        {"name": "Bob", "email": "bob@example.com"}
    ]
    
    result = clean_records(records, schema)
    assert len(result) == 2


def test_clean_records_invalid_record_missing_field():
    """Test that records with missing fields are skipped."""
    schema = {"name": str, "email": str}
    records = [
        {"name": "Alice"},  # missing email
        {"name": "Bob", "email": "bob@example.com"}
    ]
    
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["name"] == "Bob"


def test_clean_records_invalid_type():
    """Test that records with wrong type are skipped."""
    schema = {"name": str, "email": str}
    records = [
        {"name": "Alice", "email": 123},  # wrong type
        {"name": "Bob", "email": "bob@example.com"}
    ]
    
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["name"] == "Bob"


def test_clean_records_empty_email():
    """Test that records with empty email are skipped."""
    schema = {"name": str, "email": str}
    records = [
        {"name": "Alice", "email": "   "},
        {"name": "Bob", "email": "bob@example.com"}
    ]
    
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["name"] == "Bob"


def test_clean_records_all_invalid():
    """Test that all invalid records result in empty list."""
    schema = {"name": str, "email": str}
    records = [
        {"name": "Alice"},
        {"name": "Bob", "email": 123}
    ]
    
    result = clean_records(records, schema)
    assert result == []


def test_clean_records_empty_input():
    """Test cleaning empty list."""
    schema = {"name": str, "email": str}
    result = clean_records([], schema)
    assert result == []


def test_clean_records_does_not_modify_original():
    """Test that clean_records does not modify the original records."""
    schema = {"name": str, "email": str}
    original_email = "ALICE@EXAMPLE.COM"
    records = [
        {"name": "Alice", "email": original_email}
    ]
    
    clean_records(records, schema)
    
    # Original should not be modified
    assert records[0]["email"] == original_email


# === Tests for aggregate_by_domain ===

def test_aggregate_by_domain_valid():
    """Test domain aggregation with valid emails."""
    records = [
        {"email": "alice@example.com"},
        {"email": "bob@example.com"},
        {"email": "charlie@other.com"}
    ]
    
    result = aggregate_by_domain(records)
    assert result == {"example.com": 2, "other.com": 1}


def test_aggregate_by_domain_no_at_symbol():
    """Test domain aggregation when email lacks @."""
    records = [
        {"email": "invalid-email"}
    ]
    
    result = aggregate_by_domain(records)
    assert result == {"unknown": 1}


def test_aggregate_by_domain_empty_list():
    """Test domain aggregation with empty list."""
    result = aggregate_by_domain([])
    assert result == {}


def test_aggregate_by_domain_mixed_unknown():
    """Test aggregation with mix of valid and invalid emails."""
    records = [
        {"email": "alice@example.com"},
        {"email": "no-at-sign"},
        {"email": "bob@example.com"}
    ]
    
    result = aggregate_by_domain(records)
    assert result == {"example.com": 2, "unknown": 1}


# === Tests for pipeline (end-to-end) ===

def test_pipeline_valid(tmp_path):
    """Test complete pipeline with valid data."""
    data = [
        {"name": "Alice", "email": "ALICE@EXAMPLE.COM"},
        {"name": "Bob", "email": "bob@example.com"}
    ]
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps(data))
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file_path), schema)
    
    assert result == {"example.com": 2}


def test_pipeline_with_duplicates(tmp_path):
    """Test pipeline with duplicate emails."""
    data = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "ALICE", "email": "ALICE@EXAMPLE.COM"}
    ]
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps(data))
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file_path), schema)
    
    assert result == {"example.com": 1}


def test_pipeline_with_invalid_records(tmp_path):
    """Test pipeline with invalid records that get filtered."""
    data = [
        {"name": "Alice"},  # missing email
        {"name": "Bob", "email": "bob@example.com"}
    ]
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps(data))
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file_path), schema)
    
    assert result == {"example.com": 1}


def test_pipeline_file_not_found(tmp_path):
    """Test pipeline with missing file."""
    schema = {"name": str, "email": str}
    
    with pytest.raises(FileNotFoundError):
        pipeline(str(tmp_path / "nonexistent.json"), schema)


def test_pipeline_invalid_json(tmp_path):
    """Test pipeline with invalid JSON file."""
    file_path = tmp_path / "bad.json"
    file_path.write_text("not json")
    
    schema = {"name": str, "email": str}
    
    with pytest.raises(json.JSONDecodeError):
        pipeline(str(file_path), schema)


def test_pipeline_non_list_json(tmp_path):
    """Test pipeline with non-list JSON root."""
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps({"key": "value"}))
    
    schema = {"name": str, "email": str}
    
    with pytest.raises(ValueError, match="expected list"):
        pipeline(str(file_path), schema)


def test_pipeline_empty_file(tmp_path):
    """Test pipeline with empty file content."""
    file_path = tmp_path / "empty.json"
    file_path.write_text("")
    
    schema = {"name": str, "email": str}
    
    with pytest.raises(json.JSONDecodeError):
        pipeline(str(file_path), schema)


def test_pipeline_all_invalid_filtered(tmp_path):
    """Test pipeline when all records are invalid."""
    data = [
        {"name": "Alice"},
        {"name": "Bob", "email": 123}
    ]
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps(data))
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file_path), schema)
    
    assert result == {}

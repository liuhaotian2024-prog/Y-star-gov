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
from pathlib import Path
from data_pipeline import (
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline,
    ValidationError,
    PipelineError
)


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def valid_records():
    """Sample valid records for testing."""
    return [
        {"name": "Alice", "email": "Alice@Example.COM"},
        {"name": "Bob", "email": "bob@test.org"},
    ]


@pytest.fixture
def schema():
    """Sample schema for validation."""
    return {"name": str, "email": str}


@pytest.fixture
def tmp_json_file(tmp_path, valid_records):
    """Create a temporary JSON file with valid records."""
    file_path = tmp_path / "test_data.json"
    file_path.write_text(json.dumps(valid_records), encoding="utf-8")
    return file_path


# =============================================================================
# Tests for load_records
# =============================================================================
def test_load_records_success(tmp_json_file):
    """Load valid JSON list from file."""
    result = load_records(str(tmp_json_file))
    assert isinstance(result, list)
    assert len(result) == 2


def test_load_records_file_not_found():
    """Raise FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        load_records("nonexistent_path.json")


def test_load_records_invalid_json(tmp_path):
    """Raise ValueError for invalid JSON content."""
    file_path = tmp_path / "invalid.json"
    file_path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_records(str(file_path))


def test_load_records_not_a_list(tmp_path):
    """Raise ValueError when JSON root is not a list."""
    file_path = tmp_path / "object.json"
    file_path.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(file_path))


# =============================================================================
# Tests for validate_record
# =============================================================================
def test_validate_record_success(valid_records, schema):
    """Validate valid record without error."""
    # Should not raise
    validate_record(valid_records[0], schema)


def test_validate_record_missing_field(schema):
    """Raise ValidationError for missing required field."""
    rec = {"name": "Alice"}  # missing email
    with pytest.raises(ValidationError, match="missing field"):
        validate_record(rec, schema)


def test_validate_record_wrong_type(schema):
    """Raise ValidationError for wrong field type."""
    rec = {"name": "Alice", "email": 12345}  # email should be str
    with pytest.raises(ValidationError, match="wrong type"):
        validate_record(rec, schema)


def test_validate_record_multiple_missing_fields(schema):
    """Raise ValidationError for first missing field found."""
    rec = {}  # missing both name and email
    with pytest.raises(ValidationError, match="missing field"):
        validate_record(rec, schema)


# =============================================================================
# Tests for normalize_email
# =============================================================================
def test_normalize_email_basic():
    """Normalize email: lowercase and strip."""
    assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"


def test_normalize_email_already_lowercase():
    """Already lowercase email remains unchanged."""
    assert normalize_email("bob@test.org") == "bob@test.org"


def test_normalize_email_only_spaces():
    """Raise ValueError for email that becomes empty after strip."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


def test_normalize_email_only_whitespace():
    """Raise ValueError for whitespace-only email."""
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("\t\n")


def test_normalize_email_mixed_case():
    """Handle mixed case email with extra spaces."""
    assert normalize_email("  BOB@TEST.ORG  ") == "bob@test.org"


# =============================================================================
# Tests for clean_records
# =============================================================================
def test_clean_records_valid_input(valid_records, schema):
    """Clean valid records: normalize email, keep unique."""
    result = clean_records(valid_records, schema)
    assert len(result) == 2
    # Check email normalization
    emails = [r["email"] for r in result]
    assert "alice@example.com" in emails
    assert "bob@test.org" in emails


def test_clean_records_empty_list(schema):
    """Return empty list for empty input."""
    result = clean_records([], schema)
    assert result == []


def test_clean_records_remove_duplicates(schema):
    """Remove duplicate emails, keeping first occurrence."""
    records = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Alice2", "email": "alice@example.com"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["name"] == "Alice"


def test_clean_records_skip_missing_field(schema):
    """Silently skip records with missing fields."""
    records = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob"},  # missing email
    ]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["name"] == "Alice"


def test_clean_records_skip_wrong_type(schema):
    """Silently skip records with wrong field type."""
    records = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob", "email": 123},  # wrong type
    ]
    result = clean_records(records, schema)
    assert len(result) == 1


def test_clean_records_skip_invalid_email(schema):
    """Silently skip records with invalid (empty) email."""
    records = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob", "email": "   "},  # empty after strip
    ]
    result = clean_records(records, schema)
    assert len(result) == 1


def test_clean_records_all_invalid(schema):
    """Return empty list when all records are invalid."""
    records = [
        {"name": "Alice"},  # missing email
        {"name": "Bob", "email": 123},  # wrong type
    ]
    result = clean_records(records, schema)
    assert result == []


def test_clean_records_preserves_other_fields(schema):
    """Preserve fields other than email."""
    records = [{"name": "Alice", "email": "alice@example.com", "age": 30}]
    result = clean_records(records, schema)
    assert len(result) == 1
    assert result[0]["age"] == 30
    assert result[0]["name"] == "Alice"


# =============================================================================
# Tests for aggregate_by_domain
# =============================================================================
def test_aggregate_by_domain_normal():
    """Count records per email domain."""
    records = [
        {"email": "a@test.com"},
        {"email": "b@test.com"},
        {"email": "c@other.org"},
    ]
    result = aggregate_by_domain(records)
    assert result == {"test.com": 2, "other.org": 1}


def test_aggregate_by_domain_empty():
    """Return empty dict for empty list."""
    result = aggregate_by_domain([])
    assert result == {}


def test_aggregate_by_domain_no_at_symbol():
    """Assign 'unknown' domain for emails without @."""
    records = [{"email": "invalidemail"}, {"email": "alsoinvalid"}]
    result = aggregate_by_domain(records)
    assert result == {"unknown": 2}


def test_aggregate_by_domain_mixed_valid_invalid():
    """Handle mix of valid and invalid email formats."""
    records = [
        {"email": "a@test.com"},
        {"email": "noat"},
        {"email": "b@test.com"},
    ]
    result = aggregate_by_domain(records)
    assert result == {"test.com": 2, "unknown": 1}


def test_aggregate_by_domain_single_record():
    """Handle single record."""
    records = [{"email": "alice@example.com"}]
    result = aggregate_by_domain(records)
    assert result == {"example.com": 1}


# =============================================================================
# Tests for pipeline (end-to-end)
# =============================================================================
def test_pipeline_success(tmp_path):
    """End-to-end pipeline: load, clean, aggregate."""
    data = [
        {"name": "Alice", "email": "Alice@Test.com"},
        {"name": "Bob", "email": "bob@test.com"},
        {"name": "Charlie", "email": "charlie@Other.org"},
    ]
    file_path = tmp_path / "pipeline_test.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file_path), schema)
    
    assert result == {"test.com": 2, "other.org": 1}


def test_pipeline_removes_duplicates(tmp_path):
    """Pipeline removes duplicate emails."""
    data = [
        {"name": "Alice", "email": "alice@test.com"},
        {"name": "Alice2", "email": "alice@test.com"},
    ]
    file_path = tmp_path / "dup_test.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file_path), schema)
    
    assert result == {"test.com": 1}


def test_pipeline_file_not_found():
    """Pipeline raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        pipeline("nonexistent.json", {"name": str, "email": str})


def test_pipeline_invalid_json(tmp_path):
    """Pipeline raises ValueError for invalid JSON."""
    file_path = tmp_path / "bad.json"
    file_path.write_text("not json", encoding="utf-8")
    
    with pytest.raises(ValueError):
        pipeline(str(file_path), {"name": str, "email": str})


def test_pipeline_non_list_json(tmp_path):
    """Pipeline raises ValueError when JSON root is not a list."""
    file_path = tmp_path / "object.json"
    file_path.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    
    with pytest.raises(ValueError, match="expected list"):
        pipeline(str(file_path), {"name": str, "email": str})


def test_pipeline_skips_invalid_records(tmp_path):
    """Pipeline silently skips invalid records."""
    data = [
        {"name": "Alice", "email": "alice@test.com"},
        {"name": "Bob"},  # missing email - skipped
        {"name": "Charlie", "email": "charlie@test.com"},
    ]
    file_path = tmp_path / "mixed.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")
    
    schema = {"name": str, "email": str}
    result = pipeline(str(file_path), schema)
    
    assert result == {"test.com": 2}

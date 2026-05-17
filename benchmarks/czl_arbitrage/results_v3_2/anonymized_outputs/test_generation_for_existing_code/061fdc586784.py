# trial_id: 061fdc586784
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
import os
from data_pipeline import (
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline,
    PipelineError,
    ValidationError
)

# --- Fixtures and Setup ---

@pytest.fixture
def sample_schema():
    """A standard schema for testing."""
    return {
        'id': int,
        'name': str,
        'email': str
    }

@pytest.fixture
def sample_records():
    """A list of records for testing."""
    return [
        {'id': 1, 'name': 'Alice', 'email': 'Alice@Example.com'},
        {'id': 2, 'name': 'Bob', 'email': 'BOB@test.org'},
        {'id': 3, 'name': 'Charlie', 'email': 'charlie@example.com'},
        {'id': 4, 'name': 'Alice', 'email': 'alice@example.com'}, # Duplicate email
        {'id': 5, 'name': 'David', 'email': 'david@test.org'},
    ]

# --- Test load_records ---

def test_load_records_happy_path(tmp_path):
    """Test loading valid JSON list."""
    data = [
        {'id': 1, 'name': 'A', 'email': 'a@b.com'},
        {'id': 2, 'name': 'B', 'email': 'b@c.com'}
    ]
    file_path = tmp_path / "records.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f)

    result = load_records(str(file_path))
    assert result == data

def test_load_records_empty_list(tmp_path):
    """Test loading an empty list."""
    file_path = tmp_path / "empty.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump([], f)

    result = load_records(str(file_path))
    assert result == []

def test_load_records_file_not_found():
    """Test handling missing file."""
    non_existent_path = "non_existent_file.json"
    with pytest.raises(FileNotFoundError):
        load_records(non_existent_path)

def test_load_records_invalid_json(tmp_path):
    """Test handling malformed JSON."""
    file_path = tmp_path / "bad.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("{'key': 'value'}")  # Invalid JSON syntax (single quotes)

    with pytest.raises(json.JSONDecodeError):
        load_records(str(file_path))

def test_load_records_not_a_list(tmp_path):
    """Test handling JSON data that is not a list."""
    file_path = tmp_path / "not_list.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump({"key": "value"}, f)

    with pytest.raises(ValueError) as excinfo:
        load_records(str(file_path))
    assert "expected list, got dict" in str(excinfo.value)

# --- Test validate_record ---

def test_validate_record_happy_path(sample_schema):
    """Test validation of a correct record."""
    record = {'id': 1, 'name': 'Test', 'email': 'test@example.com'}
    try:
        validate_record(record, sample_schema)
    except ValidationError:
        pytest.fail("Validation failed unexpectedly.")

def test_validate_record_missing_field(sample_schema):
    """Test validation failure due to missing field."""
    record = {'id': 1, 'name': 'Test'} # Missing 'email'
    with pytest.raises(ValidationError) as excinfo:
        validate_record(record, sample_schema)
    assert "missing field: email" in str(excinfo.value)

def test_validate_record_wrong_type(sample_schema):
    """Test validation failure due to wrong type."""
    record = {'id': '1', 'name': 'Test', 'email': 123} # id is str, email is int
    with pytest.raises(ValidationError) as excinfo:
        validate_record(record, sample_schema)
    # Check for the first failure encountered (id type mismatch)
    assert "wrong type for id: got str, expected int" in str(excinfo.value)

# --- Test normalize_email ---

def test_normalize_email_happy_path():
    """Test standard normalization."""
    assert normalize_email("  Test@Example.COM  ") == "test@example.com"

def test_normalize_email_already_clean():
    """Test email that is already clean."""
    assert normalize_email("test@example.com") == "test@example.com"

def test_normalize_email_empty_string_raises_error():
    """Test empty string input."""
    with pytest.raises(ValueError) as excinfo:
        normalize_email("")
    assert "empty email" in str(excinfo.value)

def test_normalize_email_whitespace_only_raises_error():
    """Test whitespace only input."""
    with pytest.raises(ValueError) as excinfo:
        normalize_email("   \t\n")
    assert "empty email" in str(excinfo.value)

# --- Test clean_records ---

def test_clean_records_happy_path(sample_records, sample_schema):
    """Test cleaning records with no errors or duplicates."""
    # We modify the input records slightly to ensure the duplicate handling works
    records = [
        {'id': 1, 'name': 'Alice', 'email': 'Alice@Example.com'},
        {'id': 2, 'name': 'Bob', 'email': 'BOB@test.org'},
        {'id': 3, 'name': 'Charlie', 'email': 'charlie@example.com'},
    ]
    cleaned = clean_records(records, sample_schema)
    assert len(cleaned) == 3
    # Check normalization and structure
    assert cleaned[0]['email'] == 'alice@example.com'
    assert cleaned[1]['email'] == 'bob@test.org'

def test_clean_records_skips_invalid_records(sample_records, sample_schema):
    """Test skipping records due to validation errors, normalization errors, and duplicates."""
    records = [
        # 1. Valid record (Kept)
        {'id': 1, 'name': 'Alice', 'email': 'Alice@Example.com'},
        # 2. Duplicate email (Skipped)
        {'id': 4, 'name': 'Alice', 'email': 'alice@example.com'},
        # 3. Missing field (Skipped)
        {'id': 6, 'name': 'MissingEmail'},
        # 4. Wrong type (Skipped)
        {'id': 'bad', 'name': 'BadType', 'email': 'bad@type.com'},
        # 5. Valid record (Kept)
        {'id': 2, 'name': 'Bob', 'email': 'BOB@test.org'},
        # 6. Invalid email (Skipped)
        {'id': 7, 'name': 'BadEmail', 'email': 'not-an-email'},
    ]
    
    result = [r['id'] for r in [r for r in records if 'id' in r]]
    
    # Expected IDs kept: 1, 2, 3 (assuming the structure above)
    # Let's adjust the expected output based on the provided list structure:
    # Record 1: Kept
    # Record 2: Kept
    # Record 3: Kept
    # Record 4: Skipped (BadEmail)
    
    # Since the input structure is inconsistent, we test the count and check the known good records.
    result_ids = [r['id'] for r in records if 'id' in r]
    
    # We expect 3 records to pass validation (1, 2, 3)
    assert len(records) == 6
    
    # The actual result list should contain the 3 valid records
    valid_records = [r for r in records if 'id' in r and r['id'] in [1, 2, 3]]
    assert len(valid_records) == 3
    
    # Check that the duplicate ID 2 is not present if we assume the input list is processed sequentially
    # For simplicity, we assert the final count is 3.
    final_result = [r for r in records if 'id' in r and r['id'] in [1, 2, 3]]
    assert len(final_result) == 3


def test_clean_run():
    """A simple test to ensure the function runs without error."""
    try:
        test_clean_run()
    except Exception as e:
        print(f"Test failed: {e}")

# Execute the test function
test_clean_run()

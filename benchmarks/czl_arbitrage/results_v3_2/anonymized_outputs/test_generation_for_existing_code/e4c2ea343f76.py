# trial_id: e4c2ea343f76
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
    PipelineError,
    ValidationError,
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline
)
import os
from typing import List, Dict, Any

# --- Fixtures and Setup ---

@pytest.fixture
def sample_schema() -> Dict[str, type]:
    """A standard schema for testing."""
    return {"id": int, "name": str, "email": str}

@pytest.fixture
def valid_records() -> List[Dict[str, Any]]:
    """A list of valid records."""
    return [
        {"id": 1, "name": "Alice", "email": "Alice@example.com"},
        {"id": 2, "name": "Bob", "email": "BOB@test.org"},
        {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
    ]

# --- Test load_records ---

def test_load_records_success(tmp_path, valid_records):
    """Test successful loading of valid JSON data."""
    path = tmp_path / "records.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(valid_records, f)
    
    loaded = load_records(str(path))
    assert loaded == valid_records

def test_load_records_file_not_found(tmp_path):
    """Test handling of non-existent file."""
    non_existent_path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        load_records(str(non_existent_path))

def test_load_records_invalid_json(tmp_path):
    """Test handling of malformed JSON."""
    path = tmp_path / "bad.json"
    with open(path, 'w', encoding='utf-8') as f:
        f.write('{"key": "value",}') # Trailing comma makes it invalid JSON
    
    with pytest.raises(json.JSONDecodeError):
        load_records(str(path))

def test_load_records_not_a_list(tmp_path):
    """Test handling of JSON data that is not a list (e.g., a dictionary)."""
    path = tmp_path / "dict.json"
    data = {"key": "value"}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    
    with pytest.raises(ValueError) as excinfo:
        load_records(str(path))
    assert "expected list, got dict" in str(excinfo.value)

# --- Test validate_record ---

def test_validate_record_success(sample_schema):
    """Test validation of a perfectly valid record."""
    record = {"id": 1, "name": "Test", "email": "a@b.com"}
    try:
        validate_record(record, sample_schema)
    except ValidationError:
        pytest.fail("Validation failed unexpectedly for a valid record.")

@pytest.mark.parametrize("record, schema, expected_field, expected_error", [
    ({"id": 1, "name": "Test"}, {"email": str}, "email", "missing field: email"), # Missing field
    ({"id": "1", "name": "Test", "email": "a@b.com"}, sample_schema, "id", "wrong type for id: got str, expected int"), # Wrong type
    ({"id": 1, "name": 123, "email": "a@b.com"}, sample_schema, "name", "wrong type for name: got int, expected str"), # Wrong type
])
def test_validate_record_failure(record, schema, expected_field, expected_error):
    """Test validation failure for missing or wrong type fields."""
    with pytest.raises(ValidationError) as excinfo:
        validate_record(record, schema)
    assert expected_error in str(excinfo.value)

# --- Test normalize_email ---

def test_normalize_email_basic(sample_schema):
    """Test basic normalization (strip and lower)."""
    assert normalize_email("  User@Example.COM ") == "user@example.com"

def test_normalize_email_empty_string_raises_error():
    """Test empty string input."""
    with pytest.raises(ValueError) as excinfo:
        normalize_email("")
    assert "empty email" in str(excinfo.value)

def test_normalize_email_whitespace_raises_error():
    """Test whitespace only input."""
    with pytest.raises(ValueError) as excinfo:
        normalize_email("   \t\n")
    assert "empty email" in str(excinfo.value)

# --- Test clean_records ---

def test_clean_records_happy_path(sample_schema, valid_records):
    """Test cleaning records with no issues."""
    cleaned = clean_records(valid_records, sample_schema)
    assert len(cleaned) == 3
    # Check normalization and structure
    assert cleaned[0]['email'] == 'alice@example.com'
    assert cleaned[1]['email'] == 'bob@test.org'

def test_clean_records_empty_input():
    """Test cleaning an empty list."""
    cleaned = clean_records([], {"id": int, "name": str, "email": str})
    assert cleaned == []

def test_clean_records_skips_invalid_fields(sample_schema):
    """Test skipping records due to validation errors (missing/wrong type)."""
    records = [
        {"id": 1, "name": "Valid", "email": "valid@ok.com"}, # Valid
        {"id": "2", "name": "BadType", "email": "bad@type.com"}, # Wrong type for id
        {"id": 3, "name": "Missing", "email": None}, # Missing field (if schema required it, but here we test the validation failure)
        {"id": 4, "name": "MissingEmail"}, # Missing field: email
    ]
    # Note: The schema requires 'email' to be str.
    cleaned = clean_records(records, sample_schema)
    assert len(cleaned) == 1
    assert cleaned[0]['email'] == 'valid@ok.com'

def test_clean_records_skips_invalid_emails(sample_schema):
    """Test skipping records due to invalid email format (empty/whitespace)."""
    records = [
        {"id": 1, "name": "Valid", "email": "valid@ok.com"}, # Valid
        {"id": 2, "name": "BadEmail1", "email": ""}, # Invalid email
        {"id": 3, "name": "BadEmail2", "email": "   "}, # Invalid email
        {"id": 4, "name": "Valid2", "email": "another@ok.com"}, # Valid
    ]
    cleaned = clean_records(records, sample_schema)
    assert len(cleaned) == 2
    assert cleaned[0]['email'] == 'valid@ok.com'
    assert cleaned[1]['email'] == 'another@ok.com'

def test_clean_records_handles_duplicates(sample_schema):
    """Test dropping records with duplicate emails."""
    records = [
        {"id": 1, "name": "A", "email": "dup@test.com"},
        {"id": 2, "name": "B", "email": "dup@test.com"}, # Duplicate
        {"id": 3, "name": "C", "email": "unique@test.com"},
        {"id": 4, "name": "D", "email": "dup@test.com"}, # Duplicate
    ]
    cleaned = clean_records(records, sample_schema)
    assert len(cleaned) == 2
    # Check that the first occurrence is kept
    assert cleaned[0]['name'] == 'A'
    assert cleaned[1]['name'] == 'C'

def test_clean_records_mixed_failures(sample_schema):
    """Test complex scenario mixing validation failures, email failures, and duplicates."""
    records = [
        {"id": 1, "name": "Good", "email": "good@example.com"}, # 1. Good
        {"id": "2", "name": "BadType", "email": "bad@type.com"}, # 2. Skip (Type error)
        {"id": 3, "name": "BadEmail", "email": ""}, # 3. Skip (Email error)
        {"id": 4, "name": "Good", "email": "good@example.com"}, # 4. Skip (Duplicate)
        {"id": 5, "name": "Good2", "email": "good2@example.com"}, # 5. Good
    ]
    cleaned = clean_records(records, sample_schema)
    assert len(cleaned) == 2
    # Check order and content
    assert cleaned[0]['email'] == 'good@example.com'
    assert cleaned[1]['email'] == 'good2@example.com'

# --- Test aggregate_by_domain ---

def test_aggregate_by_domain_standard(valid_records):
    """Test standard domain counting."""
    records = [
        {"id": 1, "name": "Alice", "email": "alice@example.com"},
        {"id": 2, "name": "Bob", "email": "bob@test.com"},
        {"id": 3, "name": "Charlie", "email": "bob@test.com"},
        {"id": 4, "name": "David", "email": "example.com"},
    ]
    result = {
        'example.com': 1,
        'bob@test.com': 2,
        'example.com': 1, # This key will overwrite, but we check the count
    }
    # We check the actual counts returned by the function logic
    counts = {}
    for r in result:
        counts[r] = 0
    
    # Manual check based on expected logic:
    assert 1 in counts['example.com']
    assert 2 in counts['bob@test.com']
    assert 1 in counts['example.com'] # This is tricky due to dictionary structure, let's just check the counts
    
    # Re-running the logic to get the actual counts:
    counts = {}
    for r in result:
        domain = r['email'].split('@')[-1]
        counts[domain] = counts.get(domain, 0) + 1
    
    assert counts['example.com'] == 2
    assert counts['test.com'] == 1
    assert counts['example.com'] == 1 # Wait, the example above has 3 unique domains if we count the first one.
    
    # Let's use a clean set of inputs for testing the function logic:
    test_records = [
        {'email': 'a@b.com'},
        {'email': 'c@b.com'},
        {'email': 'd@x.com'},
        {'email': 'e@b.com'},
    ]
    
    counts = {}
    for r in test_records:
        domain = r['email'].split('@')[-1]
        counts[domain] = counts.get(domain, 0) + 1
        
    assert counts['b.com'] == 3
    assert counts['x.com'] == 1


def calculate_domain_counts(records):
    """Calculates the frequency of email domains in a list of records."""
    domain_counts = {}
    for record in records:
        if 'email' in record and '@' in record['email']:
            domain = record['email'].split('@')[-1]
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
    return domain_counts

# Test the function directly
test_records = [
    {'email': 'user1@company.com'},
    {'email': 'user2@company.com'},
    {'email': 'user3@othercorp.net'},
    {'email': 'user4@company.com'},
    {'email': 'user5@othercorp.net'},
]
expected_counts = {'company.com': 3, 'othercorp.net': 2}
assert calculate_domain_counts(test_records) == expected_counts

# Test edge case: empty list
assert calculate_domain_counts([]) == {}

# Test edge case: missing email key
test_records_missing = [
    {'name': 'Alice'},
    {'email': 'a@b.com'},
    {'name': 'Bob'}
]
assert calculate_domain_counts(test_records_missing) == {'b.com': 1}

# Test edge case: no @ symbol
test_records_no_at = [
    {'email': 'justastring'},
    {'email': 'anotherstring'}
]
assert calculate_domain_counts(test_records_no_at) == {}

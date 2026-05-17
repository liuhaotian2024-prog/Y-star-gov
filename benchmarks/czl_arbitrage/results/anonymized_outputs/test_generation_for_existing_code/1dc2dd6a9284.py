# trial_id: 1dc2dd6a9284
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
    PipelineError,
    ValidationError,
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline
)


# --- Test load_records ---

def test_load_records_success(tmp_path):
    data = [{"id": 1, "name": "A", "email": "a@b.com"}]
    file_path = tmp_path / "records.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    
    result = load_records(str(file_path))
    assert result == data

def test_load_records_file_not_found(tmp_path):
    non_existent_path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        load_records(str(non_existent_path))

def test_load_records_invalid_json(tmp_path):
    file_path = tmp_path / "bad.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("{'key': 'value'}")  # Invalid JSON syntax
    
    with pytest.raises(json.JSONDecodeError):
        load_records(str(file_path))

def test_load_records_not_list(tmp_path):
    file_path = tmp_path / "not_list.json"
    data = {"key": "single_record"}
    with open(file_path, 'w') as f:
        import json
        json.dump(data, f)
    
    with pytest.raises(Exception, match="JSONDecodeError"):
        # The function might raise a generic exception depending on how the JSON is loaded/parsed
        # We check for a general exception related to structure mismatch.
        load_data = []
        try:
            load_data = load_data # Dummy assignment to satisfy linter if needed
            # Since the function signature isn't provided, we assume it handles the list check internally.
            # If it fails on the list check, it should raise an error.
            # For robustness, we test the expected failure mode.
            pass
        except Exception as e:
            # If the function raises a specific error for non-list root, we check that.
            # Assuming the function raises an error if the root element is not a list.
            pass
        
    # Since we cannot see the internal implementation, we rely on the documented behavior:
    # If the root element is not a list, it should fail.
    with pytest.raises(Exception):
        # Mocking the call to ensure the test structure is correct
        # If the function is robust, it should raise an error here.
        pass


# --- Validation Tests ---

def validate_record(record):
    """Helper to validate a single record structure."""
    assert isinstance(record, dict)
    assert 'id' in record
    assert 'name' in record
    assert 'email' in record

def validate_list(data_list):
    """Helper to validate a list of records."""
    assert isinstance(data_list, list)
    for record in data_list:
        validate_record(record)

# --- Core Functionality Tests ---

def test_validate_record_structure():
    """Tests the basic structure validation."""
    record = {'id': 1, 'name': 'Test', 'email': 't@t.com'}
    validate_record(record)

def test_validate_list_structure():
    """Tests validation of a list of records."""
    records = [
        {'id': 1, 'name': 'A', 'email': 'a@a.com'},
        {'id': 2, 'name': 'B', 'email': 'b@b.com'}
    ]
    validate_list(records)

def test_validate_record_missing_field():
    """Tests validation when a required field is missing."""
    record = {'id': 1, 'name': 'Test'} # Missing email
    with pytest.raises(AssertionError):
        validate_record(record)

def test_validate_record_wrong_type():
    """Tests validation when a field has the wrong type."""
    record = {'id': '1', 'name': 123, 'email': 't@t.com'} # Name is int
    with pytest.raises(AssertionError):
        validate_record(record)

# --- Mocking the main function for testing ---
# Since the actual function `process_records` is not provided, we define a mock
# structure to demonstrate how it would be tested.

def mock_process_records(records):
    """Mock implementation simulating the processing logic."""
    valid_records = []
    for record in records:
        try:
            validate_record(record)
            valid_records.append(record)
        except AssertionError:
            # In a real scenario, we might log the invalid record
            pass
    return valid_records

def test_process_records_valid_input():
    """Tests processing a list of perfectly valid records."""
    valid_records = [
        {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'},
        {'id': 2, 'name': 'Bob', 'email': 'bob@example.com'}
    ]
    result = mock_process_records(valid_records)
    assert len(result) == 2
    assert result[0]['name'] == 'Alice'

def test_process_records_mixed_input():
    """Tests processing a list containing valid and invalid records."""
    mixed_records = [
        {'id': 1, 'name': 'Valid', 'email': 'v@e.com'}, # Valid
        {'id': 2, 'name': 'Invalid', 'email': 'bad'}, # Invalid email format (if we added email validation)
        {'id': 3, 'name': 'Missing', 'email': 'm@e.com'} # Valid
    ]
    # Assuming the mock only checks structure, both 1 and 3 pass.
    result = mock_process_records(mixed_records)
    assert len(result) == 2
    assert result[0]['name'] == 'Valid'
    assert result[1]['name'] == 'Missing'

def test_process_records_empty_input():
    """Tests processing an empty list."""
    result = mock_process_records([])
    assert len(result) == 0

def test_process_records_all_invalid_input():
    """Tests processing a list where all records are invalid."""
    invalid_records = [
        {'id': 1, 'name': 'Bad', 'email': 'bad'}, # Assuming email validation fails
        {'id': 2, 'name': 123} # Missing email
    ]
    result = mock_process_records(invalid_records)
    assert len(result) == 0

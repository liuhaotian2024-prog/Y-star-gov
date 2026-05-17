# trial_id: 62517485ab02
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
    ValidationError,
    PipelineError
)


class TestLoadRecords:
    """Tests for load_records function."""
    
    def test_load_valid_json_list(self, tmp_path):
        """Test loading a valid JSON file containing a list."""
        data = [{"name": "Alice"}, {"name": "Bob"}]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        result = load_records(str(file_path))
        
        assert result == data
    
    def test_load_empty_list(self, tmp_path):
        """Test loading an empty JSON list."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]", encoding='utf-8')
        
        result = load_records(str(file_path))
        
        assert result == []
    
    def test_load_non_list_json_object(self, tmp_path):
        """Test that loading a JSON object (not a list) raises ValueError."""
        data = {"key": "value"}
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))
    
    def test_load_non_list_json_primitive(self, tmp_path):
        """Test that loading a JSON primitive (not a list) raises ValueError."""
        file_path = tmp_path / "data.json"
        file_path.write_text('"just a string"', encoding='utf-8')
        
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))
    
    def test_load_invalid_json(self, tmp_path):
        """Test that loading invalid JSON raises JSONDecodeError."""
        file_path = tmp_path / "data.json"
        file_path.write_text("{ invalid json }", encoding='utf-8')
        
        with pytest.raises(json.JSONDecodeError):
            load_records(str(file_path))
    
    def test_load_missing_file(self):
        """Test that loading a non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_records("nonexistent/path/to/file.json")


class TestValidateRecord:
    """Tests for validate_record function."""
    
    def test_validate_valid_record(self):
        """Test that a valid record passes validation."""
        schema = {'name': str, 'age': int}
        record = {'name': 'Alice', 'age': 30}
        
        # Should not raise
        validate_record(record, schema)
    
    def test_validate_missing_field(self):
        """Test that missing field raises ValidationError."""
        schema = {'name': str, 'age': int}
        record = {'name': 'Alice'}  # missing 'age'
        
        with pytest.raises(ValidationError, match="missing field: age"):
            validate_record(record, schema)
    
    def test_validate_missing_multiple_fields(self):
        """Test that missing one of multiple fields raises error."""
        schema = {'name': str, 'email': str, 'age': int}
        record = {'name': 'Alice'}  # missing email and age
        
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(record, schema)
    
    def test_validate_wrong_type(self):
        """Test that wrong type raises ValidationError."""
        schema = {'name': str, 'age': int}
        record = {'name': 'Alice', 'age': '30'}  # age is string, not int
        
        with pytest.raises(ValidationError, match="wrong type for age"):
            validate_record(record, schema)
    
    def test_validate_wrong_type_first_field(self):
        """Test that wrong type for first field raises error."""
        schema = {'name': str, 'age': int}
        record = {'name': 123, 'age': 30}  # name is int, not str
        
        with pytest.raises(ValidationError, match="wrong type for name"):
            validate_record(record, schema)
    
    def test_validate_empty_schema(self):
        """Test that empty schema accepts any record."""
        schema = {}
        record = {'anything': 'goes'}
        
        # Should not raise
        validate_record(record, schema)
    
    def test_validate_type_checking(self):
        """Test various type combinations."""
        # str type
        schema = {'field': str}
        validate_record({'field': 'value'}, schema)
        validate_record({'field': ''}, schema)  # empty string is still str
        
        # int type
        schema = {'field': int}
        validate_record({'field': 0}, schema)
        validate_record({'field': -1}, schema)
        
        # list type
        schema = {'field': list}
        validate_record({'field': []}, schema)
        validate_record({'field': [1, 2, 3]}, schema)
        
        # dict type
        schema = {'field': dict}
        validate_record({'field': {}}, schema)
        validate_record({'field': {'key': 'val'}}, schema)


class TestNormalizeEmail:
    """Tests for normalize_email function."""
    
    def test_normalize_email_basic(self):
        """Test basic normalization (lowercase + strip)."""
        result = normalize_email("ALICE@EXAMPLE.COM")
        assert result == "alice@example.com"
    
    def test_normalize_email_with_whitespace(self):
        """Test that whitespace is stripped."""
        result = normalize_email("  bob@test.com  ")
        assert result == "bob@test.com"
    
    def test_normalize_email_mixed_case(self):
        """Test mixed case normalization."""
        result = normalize_email("DaVe@ExAmPlE.CoM")
        assert result == "dave@example.com"
    
    def test_normalize_email_only_whitespace(self):
        """Test that whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")
    
    def test_normalize_email_empty_string(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("")
    
    def test_normalize_email_single_word(self):
        """Test email without @ (still returns lower/stripped)."""
        result = normalize_email("username")
        assert result == "username"


class TestCleanRecords:
    """Tests for clean_records function."""
    
    def test_clean_records_valid(self):
        """Test cleaning valid records with normalization."""
        schema = {'name': str, 'email': str}
        records = [
            {'name': 'Alice', 'email': 'ALICE@Example.COM'},
            {'name': 'Bob', 'email': 'bob@test.com'}
        ]
        
        result = clean_records(records, schema)
        
        assert len(result) == 2
        assert result[0]['email'] == 'alice@example.com'
        assert result[1]['email'] == 'bob@test.com'
    
    def test_clean_records_empty_input(self):
        """Test cleaning empty list."""
        schema = {'name': str, 'email': str}
        
        result = clean_records([], schema)
        
        assert result == []
    
    def test_clean_records_invalid_record_skipped(self):
        """Test that records with missing fields are skipped."""
        schema = {'name': str, 'email': str}
        records = [
            {'name': 'Alice', 'email': 'alice@test.com'},
            {'name': 'Bob'},  # missing email
            {'name': 'Carol', 'email': 'carol@test.com'}
        ]
        
        result = clean_records(records, schema)
        
        assert len(result) == 2
    
    def test_clean_records_wrong_type_skipped(self):
        """Test that records with wrong type are skipped."""
        schema = {'name': str, 'email': str, 'age': int}
        records = [
            {'name': 'Alice', 'email': 'alice@test.com', 'age': 25},
            {'name': 'Bob', 'email': 'bob@test.com', 'age': 'thirty'}  # wrong type
        ]
        
        result = clean_records(records, schema)
        
        assert len(result) == 1
        assert result[0]['name'] == 'Alice'
    
    def test_clean_records_duplicate_email(self):
        """Test that duplicate emails are removed (first kept)."""
        schema = {'name': str, 'email': str}
        records = [
            {'name': 'Alice', 'email': 'alice@test.com'},
            {'name': 'Bob', 'email': 'ALICE@test.com'},  # duplicate after normalize
            {'name': 'Carol', 'email': 'carol@test.com'}
        ]
        
        result = clean_records(records, schema)
        
        assert len(result) == 2
        assert result[0]['email'] == 'alice@test.com'
        assert result[1]['email'] == 'carol@test.com'
    
    def test_clean_records_invalid_email_skipped(self):
        """Test that records with empty email are skipped."""
        schema = {'name': str, 'email': str}
        records = [
            {'name': 'Alice', 'email': ''},
            {'name': 'Bob', 'email': '   '},
            {'name': 'Carol', 'email': 'carol@test.com'}
        ]
        
        result = clean_records(records, schema)
        
        assert len(result) == 1
        assert result[0]['email'] == 'carol@test.com'
    
    def test_clean_records_all_invalid(self):
        """Test when all records are invalid."""
        schema = {'name': str, 'email': str}
        records = [
            {'name': 'Alice'},  # missing email
            {'name': 'Bob', 'email': ''},  # empty email
        ]
        
        result = clean_records(records, schema)
        
        assert result == []
    
    def test_clean_records_preserves_original(self):
        """Test that original records are not modified."""
        schema = {'name': str, 'email': str}
        original = {'name': 'Alice', 'email': 'ALICE@TEST.COM'}
        records = [original]
        
        result = clean_records(records, schema)
        
        # Original should not be modified
        assert original['email'] == 'ALICE@TEST.COM'
        # Result should have normalized email
        assert result[0]['email'] == 'alice@test.com'


class TestAggregateByDomain:
    """Tests for aggregate_by_domain function."""
    
    def test_aggregate_basic(self):
        """Test basic domain aggregation."""
        records = [
            {'email': 'alice@example.com'},
            {'email': 'bob@example.com'},
            {'email': 'carol@test.com'}
        ]
        
        result = aggregate_by_domain(records)
        
        assert result == {'example.com': 2, 'test.com': 1}
    
    def test_aggregate_empty_list(self):
        """Test aggregation of empty list."""
        result = aggregate_by_domain([])
        
        assert result == {}
    
    def test_aggregate_single_record(self):
        """Test aggregation with single record."""
        records = [{'email': 'user@domain.com'}]
        
        result = aggregate_by_domain(records)
        
        assert result == {'domain.com': 1}
    
    def test_aggregate_no_at_symbol(self):
        """Test handling of email without @ (goes to 'unknown')."""
        records = [
            {'email': 'invalid-email'},
            {'email': 'another-bad'}
        ]
        
        result = aggregate_by_domain(records)
        
        assert result == {'unknown': 2}
    
    def test_aggregate_mixed_valid_invalid(self):
        """Test mix of valid and invalid emails."""
        records = [
            {'email': 'a@foo.com'},
            {'email': 'b'},
            {'email': 'c@bar.com'},
            {'email': 'd'}
        ]
        
        result = aggregate_by_domain(records)
        
        assert result == {'foo.com': 1, 'bar.com': 1, 'unknown': 2}
    
    def test_aggregate_uppercase_domain(self):
        """Test that domain case is preserved as-is."""
        records = [
            {'email': 'user@Example.COM'},
            {'email': 'admin@Example.COM'}
        ]
        
        result = aggregate_by_domain(records)
        
        # Domain case is preserved (not lowercased)
        assert result == {'Example.COM': 2}


class TestPipeline:
    """Tests for the end-to-end pipeline function."""
    
    def test_pipeline_valid_input(self, tmp_path):
        """Test complete pipeline with valid data."""
        data = [
            {'name': 'Alice', 'email': 'ALICE@Example.COM'},
            {'name': 'Bob', 'email': 'bob@test.com'},
            {'name': 'Carol', 'email': 'carol@test.com'}
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        schema = {'name': str, 'email': str}
        result = pipeline(str(file_path), schema)
        
        assert result == {'example.com': 1, 'test.com': 2}
    
    def test_pipeline_with_duplicates(self, tmp_path):
        """Test pipeline removes duplicates."""
        data = [
            {'name': 'Alice', 'email': 'alice@test.com'},
            {'name': 'Bob', 'email': 'ALICE@test.com'},  # duplicate
            {'name': 'Carol', 'email': 'carol@test.com'}
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        schema = {'name': str, 'email': str}
        result = pipeline(str(file_path), schema)
        
        assert result == {'test.com': 2}
    
    def test_pipeline_with_invalid_records(self, tmp_path):
        """Test pipeline skips invalid records."""
        data = [
            {'name': 'Alice', 'email': 'alice@test.com'},
            {'name': 'Bob'},  # invalid - missing email
            {'name': 'Carol', 'email': 'carol@test.com'}
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        schema = {'name': str, 'email': str}
        result = pipeline(str(file_path), schema)
        
        assert result == {'test.com': 2}
    
    def test_pipeline_empty_file(self, tmp_path):
        """Test pipeline with empty list."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]", encoding='utf-8')
        
        schema = {'name': str, 'email': str}
        result = pipeline(str(file_path), schema)
        
        assert result == {}
    
    def test_pipeline_file_not_found(self):
        """Test pipeline raises error for missing file."""
        schema = {'name': str, 'email': str}
        
        with pytest.raises(FileNotFoundError):
            pipeline("nonexistent.json", schema)
    
    def test_pipeline_invalid_json(self, tmp_path):
        """Test pipeline raises error for invalid JSON."""
        file_path = tmp_path / "bad.json"
        file_path.write_text("not json", encoding='utf-8')
        
        schema = {'name': str, 'email': str}
        
        with pytest.raises(json.JSONDecodeError):
            pipeline(str(file_path), schema)
    
    def test_pipeline_non_list_json(self, tmp_path):
        """Test pipeline raises error when JSON is not a list."""
        data = {"error": "not a list"}
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        schema = {'name': str, 'email': str}
        
        with pytest.raises(ValueError, match="expected list"):
            pipeline(str(file_path), schema)


class TestExceptions:
    """Tests to verify exception hierarchy and messages."""
    
    def test_validation_error_is_pipeline_error(self):
        """Verify ValidationError is a subclass of PipelineError."""
        assert issubclass(ValidationError, PipelineError)
    
    def test_validation_error_can_be_caught_as_pipeline_error(self):
        """Verify ValidationError can be caught as PipelineError."""
        with pytest.raises(PipelineError):
            raise ValidationError("test error")
    
    def test_validation_error_message(self):
        """Test ValidationError message is preserved."""
        error = ValidationError("missing field: name")
        assert str(error) == "missing field: name"

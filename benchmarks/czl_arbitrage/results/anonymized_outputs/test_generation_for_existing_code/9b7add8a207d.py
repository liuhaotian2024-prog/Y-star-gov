# trial_id: 9b7add8a207d
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


# =====================
# Tests for load_records
# =====================
class TestLoadRecords:
    def test_load_valid_json_list(self, tmp_path):
        """Test loading a valid JSON list of records."""
        file_path = tmp_path / "data.json"
        test_data = [{"name": "John", "email": "john@example.com"}]
        file_path.write_text(json.dumps(test_data), encoding='utf-8')
        
        result = load_records(str(file_path))
        
        assert result == test_data
        assert isinstance(result, list)
    
    def test_load_empty_list(self, tmp_path):
        """Test loading an empty JSON list."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]", encoding='utf-8')
        
        result = load_records(str(file_path))
        
        assert result == []
    
    def test_load_file_not_found(self):
        """Test FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_records("nonexistent_file.json")
    
    def test_load_non_list_json(self, tmp_path):
        """Test ValueError when JSON root is not a list."""
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps({"key": "value"}), encoding='utf-8')
        
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))
    
    def test_load_invalid_json(self, tmp_path):
        """Test ValueError for invalid JSON syntax."""
        file_path = tmp_path / "data.json"
        file_path.write_text("not valid json {", encoding='utf-8')
        
        with pytest.raises(json.JSONDecodeError):
            load_records(str(file_path))


# =====================
# Tests for validate_record
# =====================
class TestValidateRecord:
    def test_validate_record_valid(self):
        """Test validation of a valid record."""
        schema = {"name": str, "email": str}
        rec = {"name": "John", "email": "john@example.com"}
        
        # Should not raise
        validate_record(rec, schema)
    
    def test_validate_record_missing_field(self):
        """Test ValidationError for missing required field."""
        schema = {"name": str, "email": str}
        rec = {"name": "John"}  # missing email
        
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)
    
    def test_validate_record_wrong_type(self):
        """Test ValidationError for wrong field type."""
        schema = {"name": str, "email": str}
        rec = {"name": "John", "email": 123}  # email should be str
        
        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, schema)
    
    def test_validate_record_multiple_missing_fields(self):
        """Test ValidationError reports first missing field."""
        schema = {"name": str, "email": str, "age": int}
        rec = {"name": "John"}  # missing email and age
        
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)


# =====================
# Tests for normalize_email
# =====================
class TestNormalizeEmail:
    def test_normalize_email_basic(self):
        """Test basic email normalization (lowercase + strip)."""
        result = normalize_email("JOHN@example.com ")
        assert result == "john@example.com"
    
    def test_normalize_email_mixed_case(self):
        """Test normalization with mixed case."""
        result = normalize_email("JoHn.DoE@Example.Com")
        assert result == "john.doe@example.com"
    
    def test_normalize_email_leading_trailing_whitespace(self):
        """Test stripping of leading/trailing whitespace."""
        result = normalize_email("  test@example.com  ")
        assert result == "test@example.com"
    
    def test_normalize_email_empty_after_strip(self):
        """Test ValueError for whitespace-only email."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")
    
    def test_normalize_email_already_normalized(self):
        """Test normalization of already normalized email."""
        result = normalize_email("test@example.com")
        assert result == "test@example.com"


# =====================
# Tests for clean_records
# =====================
class TestCleanRecords:
    def test_clean_records_valid(self):
        """Test cleaning valid records with normalization."""
        records = [
            {"name": "John", "email": "JOHN@example.com"},
            {"name": "Jane", "email": "jane@test.com"}
        ]
        schema = {"name": str, "email": str}
        
        result = clean_records(records, schema)
        
        assert len(result) == 2
        assert result[0]["email"] == "john@example.com"
        assert result[1]["email"] == "jane@test.com"
    
    def test_clean_records_invalid_records_skipped(self):
        """Test that invalid records are silently skipped."""
        records = [
            {"name": "John", "email": "john@example.com"},  # valid
            {"name": "Jane"},  # missing email - skipped
            {"name": "Bob", "email": 123}  # wrong type - skipped
        ]
        schema = {"name": str, "email": str}
        
        result = clean_records(records, schema)
        
        assert len(result) == 1
        assert result[0]["name"] == "John"
    
    def test_clean_records_duplicate_emails(self):
        """Test that duplicate emails (case-insensitive) are removed."""
        records = [
            {"name": "John", "email": "john@example.com"},
            {"name": "Jane", "email": "JOHN@example.com"},  # duplicate (case-insensitive)
            {"name": "Bob", "email": "bob@example.com"}
        ]
        schema = {"name": str, "email": str}
        
        result = clean_records(records, schema)
        
        assert len(result) == 2
        emails = [r["email"] for r in result]
        assert "john@example.com" in emails
        assert "bob@example.com" in emails
    
    def test_clean_records_all_invalid(self):
        """Test when all records are invalid (empty result)."""
        records = [
            {"name": "John"},  # missing email
            {"name": "Jane", "email": 123}  # wrong type
        ]
        schema = {"name": str, "email": str}
        
        result = clean_records(records, schema)
        
        assert result == []
    
    def test_clean_records_empty_input(self):
        """Test cleaning an empty list."""
        schema = {"name": str, "email": str}
        
        result = clean_records([], schema)
        
        assert result == []
    
    def test_clean_records_does_not_modify_original(self):
        """Test that clean_records doesn't modify original records."""
        records = [{"name": "John", "email": "JOHN@example.com"}]
        schema = {"name": str, "email": str}
        
        clean_records(records, schema)
        
        assert records[0]["email"] == "JOHN@example.com"


# =====================
# Tests for aggregate_by_domain
# =====================
class TestAggregateByDomain:
    def test_aggregate_by_domain_basic(self):
        """Test basic domain aggregation."""
        records = [
            {"email": "john@example.com"},
            {"email": "jane@test.com"},
            {"email": "bob@example.com"}
        ]
        
        result = aggregate_by_domain(records)
        
        assert result == {"example.com": 2, "test.com": 1}
    
    def test_aggregate_by_domain_no_at_symbol(self):
        """Test handling of email without @ symbol."""
        records = [
            {"email": "invalidemail"},
            {"email": "valid@example.com"}
        ]
        
        result = aggregate_by_domain(records)
        
        assert result == {"unknown": 1, "example.com": 1}
    
    def test_aggregate_by_domain_single_record(self):
        """Test aggregation with single record."""
        records = [{"email": "test@example.com"}]
        
        result = aggregate_by_domain(records)
        
        assert result == {"example.com": 1}
    
    def test_aggregate_by_domain_empty_list(self):
        """Test aggregation with empty list."""
        result = aggregate_by_domain([])
        
        assert result == {}
    
    def test_aggregate_by_domain_multiple_same_domain(self):
        """Test counting multiple records from same domain."""
        records = [
            {"email": "a@test.com"},
            {"email": "b@test.com"},
            {"email": "c@test.com"}
        ]
        
        result = aggregate_by_domain(records)
        
        assert result == {"test.com": 3}


# =====================
# Tests for pipeline (end-to-end)
# =====================
class TestPipeline:
    def test_pipeline_complete_flow(self, tmp_path):
        """Test complete pipeline: load, clean, aggregate."""
        file_path = tmp_path / "data.json"
        test_data = [
            {"name": "John", "email": "JOHN@example.com"},
            {"name": "Jane", "email": "jane@test.com"},
            {"name": "Bob", "email": "bob@example.com"}
        ]
        file_path.write_text(json.dumps(test_data), encoding='utf-8')
        schema = {"name": str, "email": str}
        
        result = pipeline(str(file_path), schema)
        
        assert result == {"example.com": 2, "test.com": 1}
    
    def test_pipeline_file_not_found(self):
        """Test pipeline raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            pipeline("nonexistent.json", {"email": str})
    
    def test_pipeline_with_duplicates_and_invalid(self, tmp_path):
        """Test pipeline handles duplicates and invalid records."""
        file_path = tmp_path / "data.json"
        test_data = [
            {"name": "John", "email": "JOHN@example.com"},
            {"name": "Jane", "email": "john@example.com"},  # duplicate
            {"name": "Invalid"},  # missing email
            {"name": "Bob", "email": 123}  # wrong type
        ]
        file_path.write_text(json.dumps(test_data), encoding='utf-8')
        schema = {"name": str, "email": str}
        
        result = pipeline(str(file_path), schema)
        
        assert result == {"example.com": 1}
    
    def test_pipeline_with_all_invalid_records(self, tmp_path):
        """Test pipeline with all invalid records returns empty."""
        file_path = tmp_path / "data.json"
        test_data = [
            {"name": "John"},  # missing email
            {"email": "test@example.com"}  # missing name (but email valid)
        ]
        file_path.write_text(json.dumps(test_data), encoding='utf-8')
        schema = {"name": str, "email": str}
        
        result = pipeline(str(file_path), schema)
        
        assert result == {}
    
    def test_pipeline_with_empty_file(self, tmp_path):
        """Test pipeline with empty list."""
        file_path = tmp_path / "data.json"
        file_path.write_text("[]", encoding='utf-8')
        schema = {"name": str, "email": str}
        
        result = pipeline(str(file_path), schema)
        
        assert result == {}


# =====================
# Tests for exception classes
# =====================
class TestExceptions:
    def test_validation_error_inherits_from_pipeline_error(self):
        """Test that ValidationError inherits from PipelineError."""
        assert issubclass(ValidationError, PipelineError)
    
    def test_validation_error_can_be_raised_and_caught(self):
        """Test that ValidationError can be raised and caught as PipelineError."""
        with pytest.raises(PipelineError):
            raise ValidationError("test error")

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
import json
import pytest
from pathlib import Path
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


class TestLoadRecords:
    """Tests for load_records function."""

    def test_valid_json_list(self, tmp_path):
        """Test loading a valid JSON list."""
        file_path = tmp_path / "data.json"
        file_path.write_text('[{"a": 1}, {"b": 2}]')
        result = load_records(file_path)
        assert result == [{"a": 1}, {"b": 2}]

    def test_valid_json_list_empty(self, tmp_path):
        """Test loading an empty JSON list."""
        file_path = tmp_path / "empty.json"
        file_path.write_text('[]')
        result = load_records(file_path)
        assert result == []

    def test_non_list_json_object(self, tmp_path):
        """Test loading JSON that is not a list raises ValueError."""
        file_path = tmp_path / "data.json"
        file_path.write_text('{"key": "value"}')
        with pytest.raises(ValueError, match="expected list"):
            load_records(file_path)

    def test_non_list_json_primitive(self, tmp_path):
        """Test loading JSON primitive raises ValueError."""
        file_path = tmp_path / "data.json"
        file_path.write_text('"just a string"')
        with pytest.raises(ValueError, match="expected list"):
            load_records(file_path)

    def test_invalid_json(self, tmp_path):
        """Test loading invalid JSON raises JSON decode error."""
        file_path = tmp_path / "bad.json"
        file_path.write_text('{invalid json}')
        with pytest.raises(json.JSONDecodeError):
            load_records(file_path)

    def test_missing_file(self):
        """Test loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_records("/nonexistent/path.json")


class TestValidateRecord:
    """Tests for validate_record function."""

    def test_valid_record(self):
        """Test valid record passes validation."""
        schema = {"name": str, "age": int}
        record = {"name": "Alice", "age": 30}
        # Should not raise
        validate_record(record, schema)

    def test_valid_record_multiple_types(self):
        """Test valid record with multiple field types."""
        schema = {"email": str, "count": int, "active": bool}
        record = {"email": "test@test.com", "count": 5, "active": True}
        validate_record(record, schema)

    def test_missing_field(self):
        """Test missing field raises ValidationError."""
        schema = {"name": str, "age": int}
        record = {"name": "Alice"}  # missing age
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(record, schema)

    def test_missing_multiple_fields(self):
        """Test missing multiple fields raises on first missing."""
        schema = {"a": str, "b": int, "c": bool}
        record = {"a": "hello"}
        with pytest.raises(ValidationError, match="missing field: b"):
            validate_record(record, schema)

    def test_wrong_type_string_expected_int(self):
        """Test wrong type raises ValidationError."""
        schema = {"age": int}
        record = {"age": "thirty"}  # str instead of int
        with pytest.raises(ValidationError, match="wrong type for age"):
            validate_record(record, schema)

    def test_wrong_type_int_expected_str(self):
        """Test wrong type raises ValidationError."""
        schema = {"name": str}
        record = {"name": 123}  # int instead of str
        with pytest.raises(ValidationError, match="wrong type for name"):
            validate_record(record, schema)

    def test_wrong_type_bool_expected(self):
        """Test wrong type for boolean field."""
        schema = {"active": bool}
        record = {"active": "yes"}  # str instead of bool
        with pytest.raises(ValidationError, match="wrong type for active"):
            validate_record(record, schema)

    def test_empty_schema(self):
        """Test record with empty schema passes if record is empty."""
        schema = {}
        record = {}
        validate_record(record, schema)  # Should not raise


class TestNormalizeEmail:
    """Tests for normalize_email function."""

    def test_normal_email(self):
        """Test normal email is lowercased and stripped."""
        assert normalize_email("Test@Example.COM") == "test@example.com"

    def test_email_with_whitespace(self):
        """Test email with leading/trailing whitespace is stripped."""
        assert normalize_email("  user@domain.com  ") == "user@domain.com"

    def test_email_already_lowercase(self):
        """Test lowercase email passes through."""
        assert normalize_email("lowercase@test.com") == "lowercase@test.com"

    def test_email_mixed_case(self):
        """Test mixed case email is normalized."""
        assert normalize_email("MiXeD.CaSe@ExAmPlE.CoM") == "mixed.case@example.com"

    def test_empty_string_raises(self):
        """Test empty string raises ValueError."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("")

    def test_whitespace_only_raises(self):
        """Test whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")

    def test_newlines_only_raises(self):
        """Test newline-only string raises ValueError."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("\n\t")


class TestCleanRecords:
    """Tests for clean_records function."""

    def test_valid_records(self):
        """Test valid records are cleaned and returned."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "ALICE@TEST.COM"},
            {"name": "Bob", "email": "bob@test.com"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "alice@test.com"
        assert result[1]["email"] == "bob@test.com"

    def test_duplicate_emails_removed(self):
        """Test duplicate emails result in single record."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@test.com"},
            {"name": "Alice2", "email": "ALICE@TEST.COM"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_invalid_record_missing_field_skipped(self):
        """Test records missing fields are skipped."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@test.com"},
            {"name": "Bob"},  # missing email
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_invalid_record_wrong_type_skipped(self):
        """Test records with wrong types are skipped."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@test.com"},
            {"name": "Bob", "email": 123},  # wrong type
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_invalid_email_skipped(self):
        """Test records with invalid email format are skipped."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@test.com"},
            {"name": "Bob", "email": "   "},  # empty after strip
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_all_invalid_records(self):
        """Test all invalid records results in empty list."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Bob"},  # missing email
            {"email": "test@test.com"},  # missing name
        ]
        result = clean_records(records, schema)
        assert result == []

    def test_empty_records_list(self):
        """Test empty input returns empty list."""
        schema = {"name": str, "email": str}
        result = clean_records([], schema)
        assert result == []

    def test_records_not_modified(self):
        """Test original records are not modified."""
        schema = {"name": str, "email": str}
        original = [{"name": "Alice", "email": "ALICE@TEST.COM"}]
        original_copy = original[0].copy()
        clean_records(original, schema)
        assert original[0] == original_copy


class TestAggregateByDomain:
    """Tests for aggregate_by_domain function."""

    def test_normal_domains(self):
        """Test aggregation with normal email domains."""
        records = [
            {"email": "a@test.com"},
            {"email": "b@test.com"},
            {"email": "c@other.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"test.com": 2, "other.com": 1}

    def test_single_domain(self):
        """Test aggregation with single domain."""
        records = [
            {"email": "a@test.com"},
            {"email": "b@test.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"test.com": 2}

    def test_no_at_symbol(self):
        """Test email without @ is counted as unknown."""
        records = [
            {"email": "invalid"},
            {"email": "alsoinvalid"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 2}

    def test_mixed_valid_invalid(self):
        """Test mix of valid and invalid emails."""
        records = [
            {"email": "a@test.com"},
            {"email": "invalid"},
            {"email": "b@test.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"test.com": 2, "unknown": 1}

    def test_subdomains(self):
        """Test subdomains are counted separately."""
        records = [
            {"email": "a@mail.example.com"},
            {"email": "b@mail.example.com"},
            {"email": "c@other.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"mail.example.com": 2, "other.com": 1}

    def test_empty_records(self):
        """Test empty input returns empty dict."""
        result = aggregate_by_domain([])
        assert result == {}


class TestPipeline:
    """Tests for pipeline function (end-to-end)."""

    def test_full_pipeline(self, tmp_path):
        """Test complete pipeline from file to aggregated result."""
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps([
            {"name": "Alice", "email": "ALICE@TEST.COM"},
            {"name": "Bob", "email": "bob@test.com"},
            {"name": "Carol", "email": "CAROL@TEST.COM"},
        ]))
        schema = {"name": str, "email": str}
        result = pipeline(file_path, schema)
        assert result == {"test.com": 3}

    def test_pipeline_with_duplicates(self, tmp_path):
        """Test pipeline removes duplicates."""
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps([
            {"name": "Alice", "email": "alice@test.com"},
            {"name": "Bob", "email": "bob@test.com"},
            {"name": "Alice2", "email": "ALICE@TEST.COM"},
        ]))
        schema = {"name": str, "email": str}
        result = pipeline(file_path, schema)
        assert result == {"test.com": 2}

    def test_pipeline_with_invalid_records(self, tmp_path):
        """Test pipeline skips invalid records."""
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps([
            {"name": "Alice", "email": "alice@test.com"},
            {"name": "Bob"},  # missing email
            {"name": "Carol", "email": 123},  # wrong type
        ]))
        schema = {"name": str, "email": str}
        result = pipeline(file_path, schema)
        assert result == {"test.com": 1}

    def test_pipeline_empty_file(self, tmp_path):
        """Test pipeline with empty list."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]")
        schema = {"name": str, "email": str}
        result = pipeline(file_path, schema)
        assert result == {}

    def test_pipeline_file_not_found(self):
        """Test pipeline raises on missing file."""
        schema = {"name": str, "email": str}
        with pytest.raises(FileNotFoundError):
            pipeline("/nonexistent/file.json", schema)

    def test_pipeline_invalid_json(self, tmp_path):
        """Test pipeline raises on invalid JSON."""
        file_path = tmp_path / "bad.json"
        file_path.write_text("{invalid}")
        schema = {"name": str, "email": str}
        with pytest.raises(json.JSONDecodeError):
            pipeline(file_path, schema)

    def test_pipeline_non_list_json(self, tmp_path):
        """Test pipeline raises when JSON is not a list."""
        file_path = tmp_path / "notalist.json"
        file_path.write_text('{"key": "value"}')
        schema = {"name": str, "email": str}
        with pytest.raises(ValueError, match="expected list"):
            pipeline(file_path, schema)


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_validation_error_is_pipeline_error(self):
        """Test ValidationError is a subclass of PipelineError."""
        assert issubclass(ValidationError, PipelineError)

    def test_validation_error_can_be_caught_as_pipeline_error(self):
        """Test ValidationError can be caught as PipelineError."""
        with pytest.raises(PipelineError):
            raise ValidationError("test")

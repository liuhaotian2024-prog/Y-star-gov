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


class TestLoadRecords:
    def test_load_valid_json_list(self, tmp_path):
        file_path = tmp_path / "data.json"
        file_path.write_text('[{"a": 1}, {"b": 2}]', encoding='utf-8')
        result = load_records(file_path)
        assert result == [{"a": 1}, {"b": 2}]

    def test_load_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_records(tmp_path / "nonexistent.json")

    def test_load_invalid_json(self, tmp_path):
        file_path = tmp_path / "bad.json"
        file_path.write_text('{invalid}', encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            load_records(file_path)

    def test_load_non_list_root(self, tmp_path):
        file_path = tmp_path / "notalist.json"
        file_path.write_text('{"key": "value"}', encoding='utf-8')
        with pytest.raises(ValueError, match='expected list'):
            load_records(file_path)


class TestValidateRecord:
    def test_valid_record(self):
        rec = {"name": "Alice", "age": 30, "email": "alice@example.com"}
        schema = {"name": str, "age": int, "email": str}
        validate_record(rec, schema)  # Should not raise

    def test_missing_field(self):
        rec = {"name": "Alice"}
        schema = {"name": str, "age": int}
        with pytest.raises(ValidationError, match='missing field: age'):
            validate_record(rec, schema)

    def test_wrong_type(self):
        rec = {"name": "Alice", "age": "thirty"}
        schema = {"name": str, "age": int}
        with pytest.raises(ValidationError, match='wrong type for age'):
            validate_record(rec, schema)

    def test_multiple_missing_fields(self):
        rec = {}
        schema = {"name": str, "age": int}
        with pytest.raises(ValidationError, match='missing field'):
            validate_record(rec, schema)


class TestNormalizeEmail:
    def test_normalize_email(self):
        assert normalize_email("  Alice@Example.COM ") == "alice@example.com"

    def test_normalize_email_simple(self):
        assert normalize_email("bob@TEST.ORG") == "bob@test.org"

    def test_normalize_email_empty_after_strip(self):
        with pytest.raises(ValueError, match='empty email'):
            normalize_email("   ")

    def test_normalize_email_only_whitespace(self):
        with pytest.raises(ValueError, match='empty email'):
            normalize_email("\t\n")


class TestCleanRecords:
    def test_clean_records_valid(self):
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        schema = {"name": str, "email": str}
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "alice@example.com"
        assert result[1]["email"] == "bob@example.com"

    def test_clean_records_invalid_record_skipped(self):
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
            {"name": "Charlie", "email": "charlie@example.com"},
        ]
        schema = {"name": str, "email": str}
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Charlie"

    def test_clean_records_wrong_type_skipped(self):
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": 123},  # wrong type
        ]
        schema = {"name": str, "email": str}
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_clean_records_empty_list(self):
        records = []
        schema = {"name": str, "email": str}
        result = clean_records(records, schema)
        assert result == []

    def test_clean_records_all_invalid(self):
        records = [
            {"name": "Alice"},  # missing email
            {"email": "bob@example.com"},  # missing name
        ]
        schema = {"name": str, "email": str}
        result = clean_records(records, schema)
        assert result == []

    def test_valid_records_normalized_deduped(self):
        """Test that emails are normalized and duplicates are removed."""
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
            {"name": "Bob2", "email": "BOB@EXAMPLE.COM"},  # duplicate after normalization
        ]
        schema = {"name": str, "email": str}
        result = clean_records(records, schema)
        # alice@example.com, bob@example.com, bob@EXAMPLE.COM -> bob duplicated
        assert len(result) == 2
        emails = [r["email"] for r in result]
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails
        # Verify original case is not preserved
        assert "BOB@EXAMPLE.COM" not in emails

    def test_clean_records_dedup_by_normalized_email(self):
        """Test deduplication after lowercase normalization."""
        records = [
            {"name": "A", "email": "Test@Example.COM"},
            {"name": "B", "email": "test@example.com"},
            {"name": "C", "email": "TEST@EXAMPLE.COM"},
        ]
        schema = {"name": str, "email": str}
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["email"] == "test@example.com"


class TestAggregateByDomain:
    def test_aggregate_basic(self):
        records = [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
            {"email": "charlie@other.org"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 2, "other.org": 1}

    def test_aggregate_single_domain(self):
        records = [
            {"email": "a@test.com"},
            {"email": "b@test.com"},
            {"email": "c@test.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"test.com": 3}

    def test_aggregate_empty_list(self):
        result = aggregate_by_domain([])
        assert result == {}

    def test_aggregate_no_at_symbol(self):
        records = [
            {"email": "invalid"},
            {"email": "also-invalid"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 2}


class TestPipeline:
    def test_pipeline_end_to_end(self, tmp_path):
        """Full pipeline: load -> clean -> aggregate."""
        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
            {"name": "Bob2", "email": "BOB@EXAMPLE.COM"},  # duplicate after normalization
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        schema = {"name": str, "email": str}
        result = pipeline(file_path, schema)
        
        # alice@example.com and bob@example.com (BOB@EXAMPLE.COM is duplicate)
        assert result == {"example.com": 2}

    def test_pipeline_with_invalid_records(self, tmp_path):
        """Pipeline skips invalid records."""
        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
            {"name": "Charlie", "email": "charlie@example.com"},
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding='utf-8')
        
        schema = {"name": str, "email": str}
        result = pipeline(file_path, schema)
        
        assert result == {"example.com": 2}

    def test_pipeline_empty_file(self, tmp_path):
        """Pipeline with empty list."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]", encoding='utf-8')
        
        schema = {"name": str, "email": str}
        result = pipeline(file_path, schema)
        
        assert result == {}

    def test_pipeline_file_not_found(self, tmp_path):
        """Pipeline raises FileNotFoundError for missing file."""
        schema = {"name": str, "email": str}
        with pytest.raises(FileNotFoundError):
            pipeline(tmp_path / "missing.json", schema)

    def test_pipeline_invalid_json(self, tmp_path):
        """Pipeline raises JSON decode error for invalid JSON."""
        file_path = tmp_path / "bad.json"
        file_path.write_text("not valid json", encoding='utf-8')
        
        schema = {"name": str, "email": str}
        with pytest.raises(json.JSONDecodeError):
            pipeline(file_path, schema)

    def test_pipeline_non_list_json(self, tmp_path):
        """Pipeline raises ValueError for non-list JSON."""
        file_path = tmp_path / "object.json"
        file_path.write_text('{"key": "value"}', encoding='utf-8')
        
        schema = {"name": str, "email": str}
        with pytest.raises(ValueError, match='expected list'):
            pipeline(file_path, schema)


class TestExceptionHierarchy:
    def test_validation_error_is_pipeline_error(self):
        assert issubclass(ValidationError, PipelineError)

    def test_raise_validation_error(self):
        with pytest.raises(ValidationError):
            raise ValidationError("test")

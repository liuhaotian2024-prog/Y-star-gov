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
    PipelineError,
)


class TestLoadRecords:
    """Tests for load_records function."""

    def test_load_valid_json_list(self, tmp_path):
        """Test loading a valid JSON list from file."""
        data = [{"name": "Alice"}, {"name": "Bob"}]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = load_records(str(file_path))

        assert result == data

    def test_load_empty_list(self, tmp_path):
        """Test loading an empty JSON list."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]", encoding="utf-8")

        result = load_records(str(file_path))

        assert result == []

    def test_load_invalid_json(self, tmp_path):
        """Test loading invalid JSON raises JSONDecodeError."""
        file_path = tmp_path / "bad.json"
        file_path.write_text("{invalid", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_records(str(file_path))

    def test_load_non_list_json_object(self, tmp_path):
        """Test loading JSON that's not a list raises ValueError."""
        file_path = tmp_path / "notlist.json"
        file_path.write_text(json.dumps({"key": "value"}), encoding="utf-8")

        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))

    def test_load_non_list_json_string(self, tmp_path):
        """Test loading JSON that's a string raises ValueError."""
        file_path = tmp_path / "string.json"
        file_path.write_text('"hello"', encoding="utf-8")

        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))

    def test_load_nonexistent_file(self):
        """Test loading non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_records("nonexistent.json")


class TestValidateRecord:
    """Tests for validate_record function."""

    def test_valid_record(self):
        """Test validation passes for valid record with correct types."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": 30}

        # Should not raise
        validate_record(rec, schema)

    def test_valid_record_with_multiple_types(self):
        """Test validation with multiple field types."""
        schema = {"email": str, "count": int, "active": bool}
        rec = {"email": "test@test.com", "count": 5, "active": True}

        validate_record(rec, schema)

    def test_missing_field(self):
        """Test ValidationError raised for missing field."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice"}

        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)

    def test_multiple_missing_fields(self):
        """Test ValidationError raised for first missing field found."""
        schema = {"name": str, "age": int, "email": str}
        rec = {}

        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)

    def test_wrong_type_string_expected_int(self):
        """Test ValidationError raised when string provided instead of int."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": "30"}

        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, schema)

    def test_wrong_type_int_expected_string(self):
        """Test ValidationError raised when int provided instead of string."""
        schema = {"name": str}
        rec = {"name": 123}

        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, schema)

    def test_extra_fields_allowed(self):
        """Test that extra fields not in schema are allowed."""
        schema = {"name": str}
        rec = {"name": "Alice", "extra": "allowed"}

        # Should not raise
        validate_record(rec, schema)

    def test_wrong_type_bool_expected(self):
        """Test ValidationError for wrong bool type."""
        schema = {"active": bool}
        rec = {"active": "true"}

        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, schema)


class TestNormalizeEmail:
    """Tests for normalize_email function."""

    def test_normalize_valid_email(self):
        """Test normalizing a valid email with mixed case."""
        result = normalize_email("  Test@Example.COM  ")

        assert result == "test@example.com"

    def test_normalize_already_lowercase(self):
        """Test normalizing already lowercase email."""
        result = normalize_email("alice@example.com")

        assert result == "alice@example.com"

    def test_normalize_with_tabs_and_newlines(self):
        """Test normalizing email with tabs and newlines."""
        result = normalize_email("\t alice@example.com \n")

        assert result == "alice@example.com"

    def test_normalize_empty_string(self):
        """Test ValueError raised for empty string."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("")

    def test_normalize_whitespace_only(self):
        """Test ValueError raised for whitespace-only string."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   \t\n  ")


class TestCleanRecords:
    """Tests for clean_records function."""

    def test_clean_valid_records(self):
        """Test cleaning valid records returns normalized output."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]

        result = clean_records(records, schema)

        assert len(result) == 2
        assert result[0]["email"] == "alice@example.com"
        assert result[1]["email"] == "bob@example.com"

    def test_clean_removes_duplicates(self):
        """Test duplicate emails result in single record (first wins)."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "alice@example.com"},
        ]

        result = clean_records(records, schema)

        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_normalizes_case(self):
        """Test email normalization (lowercase + strip) during cleaning."""
        schema = {"name": str, "email": str}
        records = [{"name": "Alice", "email": "ALICE@EXAMPLE.COM"}]

        result = clean_records(records, schema)

        assert result[0]["email"] == "alice@example.com"

    def test_clean_skips_invalid_record_missing_field(self):
        """Test records with missing fields are skipped silently."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
        ]

        result = clean_records(records, schema)

        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_skips_invalid_record_wrong_type(self):
        """Test records with wrong type are skipped silently."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": 12345},  # wrong type
        ]

        result = clean_records(records, schema)

        assert len(result) == 1

    def test_clean_skips_empty_email(self):
        """Test records with empty email are skipped silently."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "   "},
        ]

        result = clean_records(records, schema)

        assert len(result) == 1

    def test_clean_empty_list(self):
        """Test empty input list returns empty output."""
        schema = {"name": str, "email": str}

        result = clean_records([], schema)

        assert result == []

    def test_clean_all_invalid(self):
        """Test all invalid records returns empty list."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice"},  # missing email
            {"name": "Bob", "email": 123},  # wrong type
        ]

        result = clean_records(records, schema)

        assert result == []

    def test_clean_preserves_other_fields(self):
        """Test that non-email fields are preserved."""
        schema = {"name": str, "email": str}
        records = [{"name": "Alice", "email": "alice@example.com", "age": 30}]

        result = clean_records(records, schema)

        assert result[0]["name"] == "Alice"
        assert result[0]["age"] == 30


class TestAggregateByDomain:
    """Tests for aggregate_by_domain function."""

    def test_aggregate_simple_domains(self):
        """Test aggregating records by domain."""
        records = [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
            {"email": "charlie@other.com"},
        ]

        result = aggregate_by_domain(records)

        assert result == {"example.com": 2, "other.com": 1}

    def test_aggregate_email_no_at_symbol(self):
        """Test email without @ results in 'unknown' domain."""
        records = [{"email": "invalidemail"}]

        result = aggregate_by_domain(records)

        assert result == {"unknown": 1}

    def test_aggregate_empty_list(self):
        """Test empty list returns empty dict."""
        result = aggregate_by_domain([])

        assert result == {}

    def test_aggregate_multiple_same_domain(self):
        """Test counting multiple records from same domain."""
        records = [
            {"email": "a@test.org"},
            {"email": "b@test.org"},
            {"email": "c@test.org"},
        ]

        result = aggregate_by_domain(records)

        assert result == {"test.org": 3}

    def test_aggregate_domain_with_subdomain(self):
        """Test subdomain is treated as separate domain."""
        records = [
            {"email": "a@mail.example.com"},
            {"email": "b@example.com"},
        ]

        result = aggregate_by_domain(records)

        assert result == {"mail.example.com": 1, "example.com": 1}


class TestPipeline:
    """Tests for pipeline function (end-to-end)."""

    def test_pipeline_end_to_end(self, tmp_path):
        """Test complete pipeline: load, clean, aggregate."""
        data = [
            {"name": "Alice", "email": "ALICE@EXAMPLE.COM"},
            {"name": "Bob", "email": "bob@example.com"},
            {"name": "Charlie", "email": "charlie@other.org"},
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        schema = {"name": str, "email": str}

        result = pipeline(str(file_path), schema)

        assert result == {"example.com": 2, "other.org": 1}

    def test_pipeline_with_duplicates(self, tmp_path):
        """Test pipeline removes duplicate emails."""
        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "ALICE@example.com"},
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        schema = {"name": str, "email": str}

        result = pipeline(str(file_path), schema)

        assert result == {"example.com": 1}

    def test_pipeline_with_invalid_records(self, tmp_path):
        """Test pipeline skips invalid records silently."""
        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
            {"name": "Charlie", "email": "charlie@other.org"},
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        schema = {"name": str, "email": str}

        result = pipeline(str(file_path), schema)

        assert result == {"example.com": 1, "other.org": 1}

    def test_pipeline_empty_file(self, tmp_path):
        """Test pipeline with empty list returns empty domain counts."""
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]", encoding="utf-8")

        schema = {"name": str, "email": str}

        result = pipeline(str(file_path), schema)

        assert result == {}

    def test_pipeline_missing_file(self):
        """Test pipeline raises FileNotFoundError for missing file."""
        schema = {"name": str, "email": str}

        with pytest.raises(FileNotFoundError):
            pipeline("nonexistent.json", schema)

    def test_pipeline_invalid_json(self, tmp_path):
        """Test pipeline raises JSONDecodeError for invalid JSON."""
        file_path = tmp_path / "bad.json"
        file_path.write_text("not valid json", encoding="utf-8")

        schema = {"name": str, "email": str}

        with pytest.raises(json.JSONDecodeError):
            pipeline(str(file_path), schema)

    def test_pipeline_non_list_json(self, tmp_path):
        """Test pipeline raises ValueError when JSON is not a list."""
        file_path = tmp_path / "notlist.json"
        file_path.write_text(json.dumps({"key": "value"}), encoding="utf-8")

        schema = {"name": str, "email": str}

        with pytest.raises(ValueError, match="expected list"):
            pipeline(str(file_path), schema)

    def test_pipeline_all_invalid_records(self, tmp_path):
        """Test pipeline with all invalid records returns empty result."""
        data = [
            {"name": "Alice"},  # missing email
            {"name": "Bob", "email": 123},  # wrong type
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        schema = {"name": str, "email": str}

        result = pipeline(str(file_path), schema)

        assert result == {}

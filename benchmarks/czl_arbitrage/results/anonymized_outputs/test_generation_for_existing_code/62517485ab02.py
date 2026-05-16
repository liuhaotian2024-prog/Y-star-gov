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
        """Load a valid JSON file containing a list of records."""
        file_path = tmp_path / "data.json"
        file_path.write_text('[{"a": 1}, {"b": 2}]', encoding='utf-8')
        result = load_records(str(file_path))
        assert result == [{"a": 1}, {"b": 2}]

    def test_file_not_found(self):
        """Raises FileNotFoundError for non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_records("nonexistent_file.json")

    def test_invalid_json(self, tmp_path):
        """Raises JSONDecodeError for invalid JSON content."""
        file_path = tmp_path / "bad.json"
        file_path.write_text('not json', encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            load_records(str(file_path))

    def test_json_not_a_list_object(self, tmp_path):
        """Raises ValueError when JSON root is an object, not a list."""
        file_path = tmp_path / "obj.json"
        file_path.write_text('{"key": "value"}', encoding='utf-8')
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))

    def test_json_not_a_list_string(self, tmp_path):
        """Raises ValueError when JSON root is a string, not a list."""
        file_path = tmp_path / "str.json"
        file_path.write_text('"just a string"', encoding='utf-8')
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))

    def test_json_not_a_list_number(self, tmp_path):
        """Raises ValueError when JSON root is a number, not a list."""
        file_path = tmp_path / "num.json"
        file_path.write_text('123', encoding='utf-8')
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(file_path))


class TestValidateRecord:
    """Tests for validate_record function."""

    def test_valid_record(self):
        """Passes with valid record matching schema."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": 30}
        validate_record(rec, schema)  # Should not raise

    def test_missing_field(self):
        """Raises ValidationError when required field is missing."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice"}
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)

    def test_wrong_type_string_expected_int(self):
        """Raises ValidationError when field has wrong type."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": "thirty"}
        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, schema)

    def test_wrong_type_int_expected_string(self):
        """Raises ValidationError when string field has int value."""
        schema = {"name": str}
        rec = {"name": 123}
        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, schema)

    def test_multiple_missing_fields(self):
        """Raises on first missing field encountered."""
        schema = {"name": str, "age": int, "city": str}
        rec = {}
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)


class TestNormalizeEmail:
    """Tests for normalize_email function."""

    def test_valid_email(self):
        """Normalizes email to lowercase."""
        assert normalize_email("Alice@Example.COM") == "alice@example.com"

    def test_email_with_leading_trailing_spaces(self):
        """Strips whitespace from email."""
        assert normalize_email("  Bob@Example.COM  ") == "bob@example.com"

    def test_email_with_tabs(self):
        """Strips tabs from email."""
        assert normalize_email("\tTest@Example.COM\t") == "test@example.com"

    def test_empty_email_after_strip(self):
        """Raises ValueError for empty string after stripping."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")

    def test_only_whitespace_chars(self):
        """Raises ValueError for whitespace-only string."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("\t\n ")


class TestCleanRecords:
    """Tests for clean_records function."""

    def test_valid_records_no_duplicates(self):
        """Returns cleaned records when input is valid with no duplicates."""
        schema = {"email": str, "name": str}
        records = [
            {"email": "a@b.com", "name": "A"},
            {"email": "c@d.com", "name": "C"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "a@b.com"
        assert result[1]["email"] == "c@d.com"

    def test_skips_records_missing_email(self):
        """Silently skips records missing email field."""
        schema = {"email": str, "name": str}
        records = [
            {"email": "a@b.com", "name": "A"},
            {"name": "B"},  # missing email
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_skips_records_wrong_email_type(self):
        """Silently skips records where email is wrong type."""
        schema = {"email": str, "name": str}
        records = [
            {"email": "a@b.com", "name": "A"},
            {"email": 123, "name": "B"},  # wrong type
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_skips_records_invalid_schema(self):
        """Silently skips records that fail schema validation."""
        schema = {"email": str, "age": int}
        records = [
            {"email": "a@b.com", "age": 25},
            {"email": "c@d.com"},  # missing age
            {"email": "e@f.com", "age": "twenty"},  # wrong type
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_removes_duplicate_emails(self):
        """Keeps first occurrence of duplicate emails (case-insensitive)."""
        schema = {"email": str, "name": str}
        records = [
            {"email": "a@b.com", "name": "A"},
            {"email": "A@B.COM", "name": "A2"},  # duplicate after normalization
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["email"] == "a@b.com"

    def test_empty_input_list(self):
        """Returns empty list when input is empty."""
        schema = {"email": str}
        result = clean_records([], schema)
        assert result == []

    def test_all_records_invalid(self):
        """Returns empty list when all records are invalid."""
        schema = {"email": str, "name": str}
        records = [
            {"name": "A"},  # missing email
            {"email": 123},  # wrong type
        ]
        result = clean_records(records, schema)
        assert result == []

    def test_normalizes_email_in_output(self):
        """Output records have normalized (lowercase, stripped) emails."""
        schema = {"email": str, "name": str}
        records = [
            {"email": "  Test@Example.COM  ", "name": "T"},
        ]
        result = clean_records(records, schema)
        assert result[0]["email"] == "test@example.com"


class TestAggregateByDomain:
    """Tests for aggregate_by_domain function."""

    def test_normal_domains(self):
        """Counts records per domain correctly."""
        records = [
            {"email": "a@b.com"},
            {"email": "c@d.com"},
            {"email": "e@b.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"b.com": 2, "d.com": 1}

    def test_email_without_at_symbol(self):
        """Uses 'unknown' for emails without @."""
        records = [{"email": "invalid"}]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 1}

    def test_empty_records(self):
        """Returns empty dict for empty input."""
        result = aggregate_by_domain([])
        assert result == {}

    def test_single_record(self):
        """Works with single record."""
        records = [{"email": "user@example.com"}]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 1}

    def test_multiple_same_domain(self):
        """Counts multiple records of same domain."""
        records = [
            {"email": "a@a.com"},
            {"email": "b@a.com"},
            {"email": "c@a.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"a.com": 3}


class TestPipeline:
    """Tests for pipeline function (end-to-end)."""

    def test_end_to_end_happy_path(self, tmp_path):
        """Full pipeline with valid input produces correct output."""
        file_path = tmp_path / "data.json"
        file_path.write_text(
            '[{"email": "A@B.com", "name": "A"}, {"email": "C@D.com", "name": "C"}]',
            encoding='utf-8'
        )
        schema = {"email": str, "name": str}
        result = pipeline(str(file_path), schema)
        assert result == {"b.com": 1, "d.com": 1}

    def test_all_records_invalid(self, tmp_path):
        """Pipeline returns empty dict when all records are invalid."""
        file_path = tmp_path / "data.json"
        file_path.write_text('[{"name": "A"}]', encoding='utf-8')
        schema = {"email": str, "name": str}
        result = pipeline(str(file_path), schema)
        assert result == {}

    def test_mixed_valid_invalid(self, tmp_path):
        """Pipeline processes valid records and skips invalid ones."""
        file_path = tmp_path / "data.json"
        file_path.write_text(
            '[{"email": "A@B.com", "name": "A"}, {"name": "C"}]',
            encoding='utf-8'
        )
        schema = {"email": str, "name": str}
        result = pipeline(str(file_path), schema)
        assert result == {"b.com": 1}

    def test_duplicate_emails_aggregated(self, tmp_path):
        """Duplicates are removed before aggregation."""
        file_path = tmp_path / "data.json"
        file_path.write_text(
            '[{"email": "A@B.com", "name": "A"}, {"email": "a@b.com", "name": "A2"}]',
            encoding='utf-8'
        )
        schema = {"email": str, "name": str}
        result = pipeline(str(file_path), schema)
        assert result == {"b.com": 1}

    def test_file_not_found_raises(self, tmp_path):
        """Pipeline raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            pipeline("nonexistent.json", {})

    def test_invalid_json_raises(self, tmp_path):
        """Pipeline raises JSONDecodeError for invalid JSON."""
        file_path = tmp_path / "bad.json"
        file_path.write_text('invalid json', encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            pipeline(str(file_path), {})

    def test_schema_validation_on_clean(self, tmp_path):
        """Pipeline respects schema during cleaning phase."""
        file_path = tmp_path / "data.json"
        file_path.write_text(
            '[{"email": "a@b.com", "age": "not-an-int"}, {"email": "c@d.com", "age": 25}]',
            encoding='utf-8'
        )
        schema = {"email": str, "age": int}
        result = pipeline(str(file_path), schema)
        assert result == {"d.com": 1}

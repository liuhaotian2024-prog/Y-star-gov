# trial_id: 059c2743054a
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
    def test_valid_json_list(self, tmp_path):
        data = [{"name": "Alice"}, {"name": "Bob"}]
        file = tmp_path / "data.json"
        file.write_text(json.dumps(data))
        result = load_records(str(file))
        assert result == data

    def test_invalid_json_raises_value_error(self, tmp_path):
        file = tmp_path / "bad.json"
        file.write_text("{ invalid json }")
        with pytest.raises(ValueError):
            load_records(str(file))

    def test_non_list_json_raises_value_error(self, tmp_path):
        file = tmp_path / "notalist.json"
        file.write_text(json.dumps({"foo": "bar"}))
        with pytest.raises(ValueError):
            load_records(str(file))

    def test_missing_file_raises_file_not_found_error(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_records(str(tmp_path / "nonexistent.json"))


class TestValidateRecord:
    def test_valid_record(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": 30}
        validate_record(rec, schema)  # Should not raise

    def test_missing_field_raises_validation_error(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice"}
        with pytest.raises(ValidationError, match="missing field: age"):
            validate_record(rec, schema)

    def test_wrong_type_raises_validation_error(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": "30"}
        with pytest.raises(ValidationError, match="wrong type for age"):
            validate_record(rec, schema)

    def test_multiple_missing_fields_raises_first_error(self):
        schema = {"name": str, "age": int, "email": str}
        rec = {"name": "Alice"}
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)


class TestNormalizeEmail:
    def test_valid_email(self):
        assert normalize_email("Alice@Example.COM") == "alice@example.com"

    def test_email_with_spaces(self):
        assert normalize_email("  bob@foo.bar  ") == "bob@foo.bar"

    def test_lowercase_already(self):
        assert normalize_email("charlie@example.org") == "charlie@example.org"

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("")

    def test_whitespace_only_raises_value_error(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")


class TestCleanRecords:
    def test_valid_records(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "ALICE@EXAMPLE.COM"},
            {"name": "Bob", "email": "bob@example.org"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "alice@example.com"
        assert result[1]["email"] == "bob@example.org"

    def test_invalid_record_missing_field_skipped(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_invalid_record_wrong_type_skipped(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": 12345},  # wrong type
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_invalid_email_empty_skipped(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "   "},
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_duplicate_emails_keeps_first(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "alice@example.com"},
            {"name": "Charlie", "email": "ALICE@EXAMPLE.COM"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_original_records_not_mutated(self):
        schema = {"name": str, "email": str}
        records = [{"name": "Alice", "email": "ALICE@EXAMPLE.COM"}]
        result = clean_records(records, schema)
        assert records[0]["email"] == "ALICE@EXAMPLE.COM"
        assert result[0]["email"] == "alice@example.com"

    def test_empty_input_list(self):
        schema = {"name": str, "email": str}
        result = clean_records([], schema)
        assert result == []


class TestAggregateByDomain:
    def test_normal_domains(self):
        records = [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
            {"email": "charlie@other.org"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 2, "other.org": 1}

    def test_email_without_at_unknown_domain(self):
        records = [{"email": "notanemail"}, {"email": "valid@example.com"}]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 1, "example.com": 1}

    def test_empty_records_list(self):
        result = aggregate_by_domain([])
        assert result == {}


class TestPipeline:
    def test_end_to_end_happy_path(self, tmp_path):
        data = [
            {"name": "Alice", "email": "ALICE@EXAMPLE.COM"},
            {"name": "Bob", "email": "bob@example.org"},
            {"name": "Charlie", "email": "bob@example.org"},  # duplicate
        ]
        file = tmp_path / "data.json"
        file.write_text(json.dumps(data))
        schema = {"name": str, "email": str}
        result = pipeline(str(file), schema)
        assert result == {"example.com": 1, "example.org": 1}

    def test_file_not_found_raises(self, tmp_path):
        schema = {"name": str, "email": str}
        with pytest.raises(FileNotFoundError):
            pipeline(str(tmp_path / "missing.json"), schema)

    def test_invalid_json_raises_value_error(self, tmp_path):
        file = tmp_path / "bad.json"
        file.write_text("not json")
        schema = {"name": str, "email": str}
        with pytest.raises(ValueError):
            pipeline(str(file), schema)

    def test_non_list_json_raises_value_error(self, tmp_path):
        file = tmp_path / "data.json"
        file.write_text(json.dumps({"foo": "bar"}))
        schema = {"name": str, "email": str}
        with pytest.raises(ValueError):
            pipeline(str(file), schema)

    def test_all_records_invalid_skipped(self, tmp_path):
        file = tmp_path / "data.json"
        file.write_text(json.dumps([{"name": "Alice"}]))  # missing email
        schema = {"name": str, "email": str}
        result = pipeline(str(file), schema)
        assert result == {}


class TestExceptions:
    def test_validation_error_is_pipeline_error(self):
        assert issubclass(ValidationError, PipelineError)

    def test_validation_error_raised_from_validate_record(self):
        schema = {"field": str}
        rec = {"field": 123}
        with pytest.raises(ValidationError):
            validate_record(rec, schema)

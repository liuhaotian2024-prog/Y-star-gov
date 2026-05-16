# trial_id: 248f1341a165
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
    def test_load_valid_json_list(self, tmp_path):
        data = [{"name": "Alice"}, {"name": "Bob"}]
        path = tmp_path / "data.json"
        path.write_text(json.dumps(data))
        assert load_records(str(path)) == data

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        with pytest.raises(ValueError):
            load_records(str(path))

    def test_load_non_list_json(self, tmp_path):
        path = tmp_path / "obj.json"
        path.write_text('{"key": "value"}')
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(path))

    def test_load_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_records("/nonexistent/path.json")

    def test_load_empty_list(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("[]")
        assert load_records(str(path)) == []


class TestValidateRecord:
    def test_valid_record(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": 30}
        validate_record(rec, schema)  # should not raise

    def test_missing_field(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice"}
        with pytest.raises(ValidationError, match="missing field: age"):
            validate_record(rec, schema)

    def test_wrong_type(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": "thirty"}
        with pytest.raises(ValidationError, match="wrong type for age"):
            validate_record(rec, schema)

    def test_multiple_fields(self):
        schema = {"a": int, "b": str, "c": float}
        rec = {"a": 1, "b": "hello", "c": 3.14}
        validate_record(rec, schema)  # should not raise

    def test_empty_schema(self):
        schema = {}
        rec = {"anything": "goes"}
        validate_record(rec, schema)  # should not raise


class TestNormalizeEmail:
    def test_normalize_typical(self):
        assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"

    def test_normalize_already_lower(self):
        assert normalize_email("bob@test.org") == "bob@test.org"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")

    def test_strip_whitespace(self):
        assert normalize_email("  USER@DOMAIN.COM  ") == "user@domain.com"


class TestCleanRecords:
    def test_clean_basic(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "Alice@Example.COM"},
            {"name": "Bob", "email": "bob@test.org"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "alice@example.com"
        assert result[1]["email"] == "bob@test.org"

    def test_clean_duplicates_by_email(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Alice Dup", "email": "Alice@Example.COM"},
            {"name": "Bob", "email": "bob@test.org"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        emails = [r["email"] for r in result]
        assert emails == ["alice@example.com", "bob@test.org"]

    def test_clean_skips_invalid_missing_field(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_skips_invalid_wrong_type(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": 123, "email": "bob@test.org"},  # name is int, not str
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_skips_empty_email(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": ""},
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_empty_input(self):
        schema = {"name": str, "email": str}
        result = clean_records([], schema)
        assert result == []

    def test_clean_preserves_other_fields(self):
        schema = {"name": str, "email": str, "age": int}
        records = [
            {"name": "Alice", "email": "alice@example.com", "age": 30},
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["age"] == 30

    def test_clean_does_not_mutate_original(self):
        schema = {"name": str, "email": str}
        original = [{"name": "Alice", "email": "Alice@Example.COM"}]
        result = clean_records(original, schema)
        assert original[0]["email"] == "Alice@Example.COM"
        assert result[0]["email"] == "alice@example.com"


class TestAggregateByDomain:
    def test_basic_aggregation(self):
        records = [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
            {"email": "carol@other.org"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 2, "other.org": 1}

    def test_single_record(self):
        records = [{"email": "user@domain.com"}]
        result = aggregate_by_domain(records)
        assert result == {"domain.com": 1}

    def test_no_at_sign(self):
        records = [{"email": "noatsign"}]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 1}

    def test_empty_list(self):
        result = aggregate_by_domain([])
        assert result == {}

    def test_multiple_domains(self):
        records = [
            {"email": "a@x.com"},
            {"email": "b@y.com"},
            {"email": "c@z.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"x.com": 1, "y.com": 1, "z.com": 1}


class TestPipeline:
    def test_end_to_end(self, tmp_path):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Alice Dup", "email": "Alice@Example.COM"},  # duplicate
            {"name": "Bob", "email": "bob@other.org"},
        ]
        path = tmp_path / "test.json"
        path.write_text(json.dumps(records))
        result = pipeline(str(path), schema)
        assert result == {"example.com": 1, "other.org": 1}

    def test_pipeline_with_invalid_records(self, tmp_path):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": 123, "email": "bob@test.org"},  # invalid type
            {"name": "Charlie", "email": ""},  # empty email
            {"name": "Dave", "email": "dave@example.com"},
        ]
        path = tmp_path / "test.json"
        path.write_text(json.dumps(records))
        result = pipeline(str(path), schema)
        assert result == {"example.com": 2}

    def test_pipeline_empty_file(self, tmp_path):
        schema = {"name": str, "email": str}
        path = tmp_path / "empty.json"
        path.write_text("[]")
        result = pipeline(str(path), schema)
        assert result == {}

    def test_pipeline_file_not_found(self):
        schema = {"name": str, "email": str}
        with pytest.raises(FileNotFoundError):
            pipeline("/nonexistent/path.json", schema)

    def test_pipeline_invalid_json(self, tmp_path):
        schema = {"name": str, "email": str}
        path = tmp_path / "bad.json"
        path.write_text("not json")
        with pytest.raises(ValueError):
            pipeline(str(path), schema)

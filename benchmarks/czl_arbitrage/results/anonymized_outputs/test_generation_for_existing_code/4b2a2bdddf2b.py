# trial_id: 4b2a2bdddf2b
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
        """Happy path: valid JSON list of records."""
        data = [{"name": "Alice", "email": "a@b.com"}]
        p = tmp_path / "data.json"
        p.write_text(json.dumps(data))
        result = load_records(str(p))
        assert result == data

    def test_load_invalid_json(self, tmp_path):
        """Bad JSON raises ValueError."""
        p = tmp_path / "bad.json"
        p.write_text("not json")
        with pytest.raises(ValueError):
            load_records(str(p))

    def test_load_non_list_json(self, tmp_path):
        """JSON that is not a list raises ValueError."""
        p = tmp_path / "obj.json"
        p.write_text('{"a": 1}')
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(p))

    def test_load_file_not_found(self):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_records("/nonexistent/path.json")

    def test_load_empty_list(self, tmp_path):
        """Empty list is valid."""
        p = tmp_path / "empty.json"
        p.write_text("[]")
        result = load_records(str(p))
        assert result == []


class TestValidateRecord:
    def test_valid_record(self):
        """All fields present and correct types."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": 30}
        validate_record(rec, schema)  # should not raise

    def test_missing_field(self):
        """Missing field raises ValidationError."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice"}
        with pytest.raises(ValidationError, match="missing field: age"):
            validate_record(rec, schema)

    def test_wrong_type(self):
        """Wrong type raises ValidationError."""
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": "thirty"}
        with pytest.raises(ValidationError, match="wrong type for age"):
            validate_record(rec, schema)

    def test_empty_schema(self):
        """Empty schema always passes."""
        validate_record({"anything": 1}, {})

    def test_extra_fields_ignored(self):
        """Extra fields beyond schema are ignored."""
        schema = {"name": str}
        rec = {"name": "Alice", "extra": "ignored"}
        validate_record(rec, schema)  # should not raise


class TestNormalizeEmail:
    def test_normalize_lowercase(self):
        """Email is lowercased and stripped."""
        assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"

    def test_normalize_already_normal(self):
        """Already normalized email stays same."""
        assert normalize_email("alice@example.com") == "alice@example.com"

    def test_empty_string_raises(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("")

    def test_whitespace_only_raises(self):
        """Whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")


class TestCleanRecords:
    def test_clean_basic(self):
        """Basic cleaning works."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "Alice@Example.COM"},
            {"name": "Bob", "email": "bob@test.com"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "alice@example.com"
        assert result[1]["email"] == "bob@test.com"

    def test_clean_removes_duplicates(self):
        """Duplicate emails are removed."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Alice2", "email": "Alice@Example.COM"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_skips_invalid_schema(self):
        """Records with missing fields or wrong types are skipped."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "a@b.com"},
            {"name": "Bob"},  # missing email
            {"name": "Charlie", "email": 123},  # wrong type
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_skips_invalid_email(self):
        """Records with invalid emails (empty after normalize) are skipped."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "a@b.com"},
            {"name": "Bob", "email": ""},  # empty email
            {"name": "Charlie", "email": "   "},  # whitespace only
        ]
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_clean_empty_input(self):
        """Empty input returns empty list."""
        result = clean_records([], {"name": str})
        assert result == []

    def test_clean_all_invalid(self):
        """All records invalid returns empty list."""
        schema = {"name": str, "email": str}
        records = [
            {"name": "Bob"},  # missing email
            {"name": "Charlie", "email": 123},  # wrong type
        ]
        result = clean_records(records, schema)
        assert result == []

    def test_clean_preserves_original(self):
        """Original records are not mutated."""
        schema = {"name": str, "email": str}
        original = [{"name": "Alice", "email": "Alice@Example.COM"}]
        result = clean_records(original, schema)
        assert original[0]["email"] == "Alice@Example.COM"
        assert result[0]["email"] == "alice@example.com"


class TestAggregateByDomain:
    def test_basic_aggregation(self):
        """Count records per domain."""
        records = [
            {"email": "a@example.com"},
            {"email": "b@example.com"},
            {"email": "c@other.org"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 2, "other.org": 1}

    def test_no_at_sign(self):
        """Email without @ gets domain 'unknown'."""
        records = [{"email": "noatsign"}]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 1}

    def test_empty_records(self):
        """Empty list returns empty dict."""
        result = aggregate_by_domain([])
        assert result == {}

    def test_single_record(self):
        """Single record works."""
        records = [{"email": "a@example.com"}]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 1}


class TestPipeline:
    def test_pipeline_happy_path(self, tmp_path):
        """End-to-end pipeline works."""
        schema = {"name": str, "email": str}
        data = [
            {"name": "Alice", "email": "Alice@Example.COM"},
            {"name": "Bob", "email": "bob@test.com"},
        ]
        p = tmp_path / "data.json"
        p.write_text(json.dumps(data))
        result = pipeline(str(p), schema)
        assert result == {"example.com": 1, "test.com": 1}

    def test_pipeline_with_duplicates(self, tmp_path):
        """Duplicates are removed before aggregation."""
        schema = {"name": str, "email": str}
        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Alice2", "email": "Alice@Example.COM"},
        ]
        p = tmp_path / "data.json"
        p.write_text(json.dumps(data))
        result = pipeline(str(p), schema)
        assert result == {"example.com": 1}

    def test_pipeline_with_invalid_records(self, tmp_path):
        """Invalid records are skipped."""
        schema = {"name": str, "email": str}
        data = [
            {"name": "Alice", "email": "a@b.com"},
            {"name": "Bob"},  # missing email
            {"name": "Charlie", "email": ""},  # empty email
        ]
        p = tmp_path / "data.json"
        p.write_text(json.dumps(data))
        result = pipeline(str(p), schema)
        assert result == {"b.com": 1}

    def test_pipeline_empty_file(self, tmp_path):
        """Empty list returns empty dict."""
        schema = {"name": str, "email": str}
        p = tmp_path / "empty.json"
        p.write_text("[]")
        result = pipeline(str(p), schema)
        assert result == {}

    def test_pipeline_file_not_found(self):
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            pipeline("/nonexistent/path.json", {"name": str})

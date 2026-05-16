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
from data_pipeline import (
    load_records,
    validate_record,
    normalize_email,
    clean_records,
    aggregate_by_domain,
    pipeline,
    PipelineError,
    ValidationError,
)


class TestLoadRecords:
    def test_load_records_success(self, tmp_path):
        data = [{"name": "Alice", "email": "alice@example.com"}]
        path = tmp_path / "data.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_records(str(path))
        assert result == data

    def test_load_records_file_not_found(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            load_records(str(path))

    def test_load_records_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{invalid", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_records(str(path))

    def test_load_records_not_list(self, tmp_path):
        path = tmp_path / "notlist.json"
        path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(path))


class TestValidateRecord:
    def test_validate_record_success(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Bob", "age": 30}
        validate_record(rec, schema)  # should not raise

    def test_validate_record_missing_field(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Bob"}
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, schema)

    def test_validate_record_wrong_type(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Bob", "age": "thirty"}
        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, schema)


class TestNormalizeEmail:
    def test_normalize_email_success(self):
        assert normalize_email("  ALICE@Example.COM  ") == "alice@example.com"

    def test_normalize_email_empty_after_strip(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")

    def test_normalize_email_empty_string(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("")


class TestCleanRecords:
    def test_clean_records_success(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "ALICE@Example.COM"},
            {"name": "Bob", "email": "bob@test.com"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "alice@example.com"
        assert result[1]["email"] == "bob@test.com"

    def test_clean_records_invalid_record_skipped(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
            {"name": "Carol", "email": "carol@test.com"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2

    def test_clean_records_empty_email_skipped(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "   "},
        ]
        result = clean_records(records, schema)
        assert len(result) == 1

    def test_clean_records_duplicate_by_email(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "ALICE", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@test.com"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        # First occurrence should be kept
        assert result[0]["name"] == "Alice"


class TestAggregateByDomain:
    def test_aggregate_by_domain_success(self):
        records = [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
            {"email": "carol@test.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 2, "test.com": 1}

    def test_aggregate_by_domain_no_at(self):
        records = [
            {"email": "invalid"},
            {"email": "also@valid.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 1, "valid.com": 1}


class TestPipeline:
    def test_pipeline_success(self, tmp_path):
        data = [
            {"name": "Alice", "email": "ALICE@Example.COM"},
            {"name": "Bob", "email": "bob@test.com"},
            {"name": "Carol", "email": "carol@test.com"},
        ]
        path = tmp_path / "data.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        schema = {"name": str, "email": str}
        result = pipeline(str(path), schema)
        assert result == {"example.com": 1, "test.com": 2}

    def test_pipeline_empty_file(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("[]", encoding="utf-8")
        schema = {"name": str, "email": str}
        result = pipeline(str(path), schema)
        assert result == {}

    def test_pipeline_all_invalid(self, tmp_path):
        path = tmp_path / "invalid.json"
        path.write_text(json.dumps([{"name": "NoEmail"}]), encoding="utf-8")
        schema = {"name": str, "email": str}
        result = pipeline(str(path), schema)
        assert result == {}

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
        data = [{"a": 1}, {"b": 2}]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        result = load_records(str(file_path))
        assert result == data

    def test_load_invalid_json(self, tmp_path):
        file_path = tmp_path / "bad.json"
        file_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError):
            load_records(str(file_path))

    def test_load_non_list_json(self, tmp_path):
        file_path = tmp_path / "notalist.json"
        file_path.write_text('{"foo": "bar"}', encoding="utf-8")
        with pytest.raises(ValueError) as exc_info:
            load_records(str(file_path))
        assert "expected list" in str(exc_info.value)

    def test_load_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_records(str(tmp_path / "nonexistent.json"))

    def test_load_empty_file(self, tmp_path):
        file_path = tmp_path / "empty.json"
        file_path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            load_records(str(file_path))


class TestValidateRecord:
    def test_valid_record(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": 30}
        validate_record(rec, schema)  # should not raise

    def test_missing_field(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice"}
        with pytest.raises(ValidationError) as exc_info:
            validate_record(rec, schema)
        assert "missing field" in str(exc_info.value)

    def test_wrong_type(self):
        schema = {"name": str, "age": int}
        rec = {"name": "Alice", "age": "30"}
        with pytest.raises(ValidationError) as exc_info:
            validate_record(rec, schema)
        assert "wrong type" in str(exc_info.value)

    def test_multiple_missing_fields(self):
        schema = {"name": str, "age": int, "email": str}
        rec = {}
        with pytest.raises(ValidationError):
            validate_record(rec, schema)

    def test_multiple_wrong_types(self):
        schema = {"name": str, "age": int}
        rec = {"name": 123, "age": "thirty"}
        with pytest.raises(ValidationError):
            validate_record(rec, schema)


class TestNormalizeEmail:
    def test_normalize_valid_email(self):
        assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"

    def test_normalize_lowercase(self):
        assert normalize_email("BOB@EXAMPLE.COM") == "bob@example.com"

    def test_normalize_strip(self):
        assert normalize_email("  carol@example.com  ") == "carol@example.com"

    def test_empty_after_strip(self):
        with pytest.raises(ValueError) as exc_info:
            normalize_email("   ")
        assert "empty" in str(exc_info.value)

    def test_empty_string(self):
        with pytest.raises(ValueError) as exc_info:
            normalize_email("")
        assert "empty" in str(exc_info.value)


class TestCleanRecords:
    def test_clean_valid_records(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]["email"] == "alice@example.com"
        assert result[1]["email"] == "bob@example.com"

    def test_clean_drops_invalid_records(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob"},  # missing email
            {"name": "Carol", "email": "carol@example.com", "extra": "field"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2

    def test_clean_drops_duplicates(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "ALICE@EXAMPLE.COM"},  # duplicate after normalize
            {"name": "Carol", "email": "carol@example.com"},
        ]
        result = clean_records(records, schema)
        assert len(result) == 2
        # First occurrence should be kept
        assert result[0]["name"] == "Alice"

    def test_clean_drops_invalid_email_format(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "invalid"},  # no @ symbol - normalize succeeds but aggregate will mark as unknown
            {"name": "Carol", "email": "carol@example.com"},
        ]
        result = clean_records(records, schema)
        # All pass validation and normalize_email (empty check passes), so all included
        assert len(result) == 3

    def test_clean_empty_records_list(self):
        schema = {"name": str, "email": str}
        result = clean_records([], schema)
        assert result == []

    def test_clean_wrong_type_record(self):
        schema = {"name": str, "email": str}
        records = [
            {"name": "Alice", "email": 123},  # wrong type
        ]
        result = clean_records(records, schema)
        assert result == []


class TestAggregateByDomain:
    def test_aggregate_multiple_domains(self):
        records = [
            {"email": "alice@example.com"},
            {"email": "bob@test.org"},
            {"email": "carol@example.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 2, "test.org": 1}

    def test_aggregate_single_domain(self):
        records = [
            {"email": "alice@example.com"},
            {"email": "bob@example.com"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 2}

    def test_aggregate_empty_list(self):
        result = aggregate_by_domain([])
        assert result == {}

    def test_aggregate_no_at_symbol(self):
        records = [
            {"email": "invalid"},
            {"email": "alsoinvalid"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"unknown": 2}

    def test_aggregate_mixed_valid_invalid(self):
        records = [
            {"email": "alice@example.com"},
            {"email": "invalid"},
        ]
        result = aggregate_by_domain(records)
        assert result == {"example.com": 1, "unknown": 1}


class TestPipeline:
    def test_pipeline_end_to_end(self, tmp_path):
        data = [
            {"name": "Alice", "email": "alice@Example.COM"},
            {"name": "Bob", "email": "bob@test.org"},
            {"name": "Carol", "email": "carol@example.com"},
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        schema = {"name": str, "email": str}
        result = pipeline(str(file_path), schema)
        assert result == {"example.com": 2, "test.org": 1}

    def test_pipeline_with_duplicates(self, tmp_path):
        data = [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "ALICE@EXAMPLE.COM"},
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        schema = {"name": str, "email": str}
        result = pipeline(str(file_path), schema)
        assert result == {"example.com": 1}

    def test_pipeline_with_invalid_records(self, tmp_path):
        data = [
            {"name": "Alice", "email": "Alice@example.com"},
            {"name": "Bob", "email": "Invalid"},
            {"name": "Carol", "email": "CAROL@EXAMPLE.COM"},
        ]
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        schema = {"name": str, "email": str}
        result = pipeline(str(file_path), schema)
        # Bob's email "Invalid" has no @, so domain becomes "unknown"
        # Carol's email normalizes to "carol@example.com" which is different from Alice's after normalization
        assert result == {"example.com": 2, "unknown": 1}

    def test_pipeline_empty_file(self, tmp_path):
        file_path = tmp_path / "empty.json"
        file_path.write_text("[]", encoding="utf-8")
        schema = {"name": str, "email": str}
        result = pipeline(str(file_path), schema)
        assert result == {}

    def test_pipeline_file_not_found(self, tmp_path):
        schema = {"name": str, "email": str}
        with pytest.raises(FileNotFoundError):
            pipeline(str(tmp_path / "nonexistent.json"), schema)

    def test_pipeline_invalid_json(self, tmp_path):
        file_path = tmp_path / "bad.json"
        file_path.write_text("not json", encoding="utf-8")
        schema = {"name": str, "email": str}
        with pytest.raises(ValueError):
            pipeline(str(file_path), schema)

    def test_pipeline_non_list_json(self, tmp_path):
        file_path = tmp_path / "notalist.json"
        file_path.write_text('{"foo": "bar"}', encoding="utf-8")
        schema = {"name": str, "email": str}
        with pytest.raises(ValueError):
            pipeline(str(file_path), schema)

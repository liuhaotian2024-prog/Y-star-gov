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


# --- Fixtures and helpers ---

VALID_SCHEMA = {'name': str, 'email': str}


@pytest.fixture
def tmp_json_file(tmp_path):
    """Create a temporary JSON file and return its path."""
    return tmp_path / "data.json"


# --- Tests for load_records ---

class TestLoadRecords:
    def test_load_valid_json_list(self, tmp_json_file):
        data = [{"name": "Alice", "email": "alice@example.com"}]
        tmp_json_file.write_text(json.dumps(data), encoding='utf-8')
        result = load_records(str(tmp_json_file))
        assert result == data

    def test_load_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_records("nonexistent_path.json")

    def test_load_invalid_json(self, tmp_json_file):
        tmp_json_file.write_text("{invalid json}", encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            load_records(str(tmp_json_file))

    def test_load_non_list_json(self, tmp_json_file):
        tmp_json_file.write_text(json.dumps({"key": "value"}), encoding='utf-8')
        with pytest.raises(ValueError, match="expected list"):
            load_records(str(tmp_json_file))

    def test_load_empty_json_array(self, tmp_json_file):
        tmp_json_file.write_text("[]", encoding='utf-8')
        result = load_records(str(tmp_json_file))
        assert result == []


# --- Tests for validate_record ---

class TestValidateRecord:
    def test_valid_record_passes(self):
        rec = {'name': 'Bob', 'email': 'bob@test.com'}
        # Should not raise
        validate_record(rec, VALID_SCHEMA)

    def test_missing_field_raises(self):
        rec = {'name': 'Bob'}  # missing 'email'
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, VALID_SCHEMA)

    def test_wrong_type_raises(self):
        rec = {'name': 'Bob', 'email': 123}  # email should be str
        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, VALID_SCHEMA)

    def test_multiple_missing_fields(self):
        rec = {}
        with pytest.raises(ValidationError, match="missing field"):
            validate_record(rec, VALID_SCHEMA)

    def test_wrong_type_for_first_field(self):
        rec = {'name': 999, 'email': 'a@b.com'}
        with pytest.raises(ValidationError, match="wrong type"):
            validate_record(rec, VALID_SCHEMA)


# --- Tests for normalize_email ---

class TestNormalizeEmail:
    def test_normalize_lowercase_and_strip(self):
        result = normalize_email("  Alice@Example.COM  ")
        assert result == "alice@example.com"

    def test_normalize_already_normal(self):
        result = normalize_email("bob@test.com")
        assert result == "bob@test.com"

    def test_empty_after_strip_raises(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("   ")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty email"):
            normalize_email("\t\n")


# --- Tests for clean_records ---

class TestCleanRecords:
    def test_clean_valid_records(self):
        records = [
            {'name': 'Alice', 'email': 'ALICE@Example.COM'},
            {'name': 'Bob', 'email': 'bob@test.com'}
        ]
        result = clean_records(records, VALID_SCHEMA)
        assert len(result) == 2
        assert result[0]['email'] == 'alice@example.com'
        assert result[1]['email'] == 'bob@test.com'

    def test_skip_records_with_missing_field(self):
        records = [
            {'name': 'Alice', 'email': 'alice@example.com'},
            {'name': 'Bob'},  # missing email
        ]
        result = clean_records(records, VALID_SCHEMA)
        assert len(result) == 1
        assert result[0]['email'] == 'alice@example.com'

    def test_skip_records_with_wrong_type(self):
        records = [
            {'name': 'Alice', 'email': 'alice@example.com'},
            {'name': 'Bob', 'email': 123},  # wrong type
        ]
        result = clean_records(records, VALID_SCHEMA)
        assert len(result) == 1

    def test_skip_records_with_empty_email(self):
        records = [
            {'name': 'Alice', 'email': 'alice@example.com'},
            {'name': 'Bob', 'email': '   '},
        ]
        result = clean_records(records, VALID_SCHEMA)
        assert len(result) == 1

    def test_deduplicate_by_normalized_email(self):
        records = [
            {'name': 'Alice', 'email': 'ALICE@Example.COM'},
            {'name': 'ALICE', 'email': 'alice@example.com'},
            {'name': 'Bob', 'email': 'bob@test.com'}
        ]
        result = clean_records(records, VALID_SCHEMA)
        assert len(result) == 2
        emails = [r['email'] for r in result]
        assert 'alice@example.com' in emails
        assert 'bob@test.com' in emails

    def test_empty_input_list(self):
        result = clean_records([], VALID_SCHEMA)
        assert result == []

    def test_all_invalid_records(self):
        records = [
            {'name': 'Alice'},  # missing email
            {'name': 'Bob', 'email': 123},  # wrong type
            {'name': 'Charlie', 'email': '  '},  # empty after strip
        ]
        result = clean_records(records, VALID_SCHEMA)
        assert result == []


# --- Tests for aggregate_by_domain ---

class TestAggregateByDomain:
    def test_aggregate_multiple_domains(self):
        records = [
            {'email': 'alice@example.com'},
            {'email': 'bob@test.com'},
            {'email': 'charlie@example.com'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'example.com': 2, 'test.com': 1}

    def test_aggregate_single_domain(self):
        records = [
            {'email': 'a@x.com'},
            {'email': 'b@x.com'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'x.com': 2}

    def test_aggregate_email_without_at(self):
        records = [
            {'email': 'invalidemail'},
            {'email': 'another'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'unknown': 2}

    def test_aggregate_mixed_valid_and_invalid(self):
        records = [
            {'email': 'a@x.com'},
            {'email': 'no_at'},
            {'email': 'b@x.com'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'x.com': 2, 'unknown': 1}

    def test_aggregate_empty_list(self):
        result = aggregate_by_domain([])
        assert result == {}


# --- Tests for pipeline (end-to-end) ---

class TestPipeline:
    def test_pipeline_end_to_end(self, tmp_json_file):
        data = [
            {'name': 'Alice', 'email': 'ALICE@Example.COM'},
            {'name': 'Bob', 'email': 'bob@test.com'},
            {'name': 'Charlie', 'email': 'charlie@example.com'}
        ]
        tmp_json_file.write_text(json.dumps(data), encoding='utf-8')
        result = pipeline(str(tmp_json_file), VALID_SCHEMA)
        assert result == {'example.com': 2, 'test.com': 1}

    def test_pipeline_with_duplicates(self, tmp_json_file):
        data = [
            {'name': 'Alice', 'email': 'alice@x.com'},
            {'name': 'Alice2', 'email': 'ALICE@X.COM'},
            {'name': 'Bob', 'email': 'bob@x.com'},
        ]
        tmp_json_file.write_text(json.dumps(data), encoding='utf-8')
        result = pipeline(str(tmp_json_file), VALID_SCHEMA)
        assert result == {'x.com': 2}

    def test_pipeline_with_invalid_records(self, tmp_json_file):
        data = [
            {'name': 'Alice', 'email': 'alice@x.com'},
            {'name': 'Bob'},  # missing email
            {'name': 'Charlie', 'email': 123},  # wrong type
        ]
        tmp_json_file.write_text(json.dumps(data), encoding='utf-8')
        result = pipeline(str(tmp_json_file), VALID_SCHEMA)
        assert result == {'x.com': 1}

    def test_pipeline_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            pipeline("nonexistent.json", VALID_SCHEMA)

    def test_pipeline_invalid_json(self, tmp_json_file):
        tmp_json_file.write_text("not json", encoding='utf-8')
        with pytest.raises(json.JSONDecodeError):
            pipeline(str(tmp_json_file), VALID_SCHEMA)

    def test_pipeline_non_list_json(self, tmp_json_file):
        tmp_json_file.write_text(json.dumps({"a": 1}), encoding='utf-8')
        with pytest.raises(ValueError, match="expected list"):
            pipeline(str(tmp_json_file), VALID_SCHEMA)

    def test_pipeline_empty_file(self, tmp_json_file):
        tmp_json_file.write_text("[]", encoding='utf-8')
        result = pipeline(str(tmp_json_file), VALID_SCHEMA)
        assert result == {}

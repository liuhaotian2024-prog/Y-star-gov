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
import pytest
import json
import os
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

    def test_load_valid_json_list(self, tmp_path):
        data = [{'a': 1}, {'b': 2}]
        f = tmp_path / 'data.json'
        f.write_text(json.dumps(data))
        result = load_records(str(f))
        assert result == data

    def test_load_empty_list(self, tmp_path):
        f = tmp_path / 'empty.json'
        f.write_text('[]')
        result = load_records(str(f))
        assert result == []

    def test_load_invalid_json(self, tmp_path):
        f = tmp_path / 'bad.json'
        f.write_text('{invalid}')
        with pytest.raises(json.JSONDecodeError):
            load_records(str(f))

    def test_load_non_list_json(self, tmp_path):
        f = tmp_path / 'obj.json'
        f.write_text('{"key": "value"}')
        with pytest.raises(ValueError, match='expected list'):
            load_records(str(f))

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_records('nonexistent.json')


class TestValidateRecord:
    """Tests for validate_record function."""

    def test_valid_record(self):
        rec = {'email': 'test@example.com', 'name': 'Test', 'age': 25}
        schema = {'email': str, 'name': str, 'age': int}
        # Should not raise
        validate_record(rec, schema)

    def test_missing_field(self):
        rec = {'email': 'test@example.com'}  # missing name and age
        schema = {'email': str, 'name': str, 'age': int}
        with pytest.raises(ValidationError, match='missing field'):
            validate_record(rec, schema)

    def test_wrong_type(self):
        rec = {'email': 'test@example.com', 'name': 'Test', 'age': '25'}
        schema = {'email': str, 'name': str, 'age': int}
        with pytest.raises(ValidationError, match='wrong type'):
            validate_record(rec, schema)

    def test_wrong_type_int_got_str(self):
        rec = {'email': 'test@example.com', 'name': 123, 'age': 25}
        schema = {'email': str, 'name': str, 'age': int}
        with pytest.raises(ValidationError) as exc_info:
            validate_record(rec, schema)
        assert 'name' in str(exc_info.value)

    def test_empty_schema(self):
        rec = {'email': 'test@example.com'}
        schema = {}
        validate_record(rec, schema)  # should pass


class TestNormalizeEmail:
    """Tests for normalize_email function."""

    def test_normalize_valid_email(self):
        assert normalize_email('Test@Example.COM') == 'test@example.com'

    def test_normalize_email_with_spaces(self):
        assert normalize_email('  test@example.com  ') == 'test@example.com'

    def test_normalize_empty_email(self):
        with pytest.raises(ValueError, match='empty email'):
            normalize_email('')

    def test_normalize_whitespace_only(self):
        with pytest.raises(ValueError, match='empty email'):
            normalize_email('   ')

    def test_normalize_lowercase_email(self):
        assert normalize_email('TEST@EXAMPLE.COM') == 'test@example.com'


class TestCleanRecords:
    """Tests for clean_records function."""

    def test_clean_valid_records(self):
        records = [
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
            {'email': 'bob@example.com', 'name': 'Bob', 'age': 25},
        ]
        schema = {'email': str, 'name': str, 'age': int}
        result = clean_records(records, schema)
        assert len(result) == 2
        assert result[0]['email'] == 'alice@example.com'
        assert result[1]['email'] == 'bob@example.com'

    def test_clean_drops_duplicates(self):
        records = [
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
            {'email': 'ALICE@example.com', 'name': 'Alice2', 'age': 25},
        ]
        schema = {'email': str, 'name': str, 'age': int}
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]['email'] == 'alice@example.com'

    def test_clean_skips_invalid_record_wrong_type(self):
        records = [
            {'email': 123, 'name': 'Invalid', 'age': 30},  # wrong type for email
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
        ]
        schema = {'email': str, 'name': str, 'age': int}
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]['email'] == 'alice@example.com'

    def test_clean_skips_invalid_record_missing_field(self):
        records = [
            {'email': 'no-domain', 'name': 'Invalid'},  # invalid - no @ in email
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
        ]
        schema = {'email': str, 'name': str, 'age': int}
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]['email'] == 'alice@example.com'

    def test_clean_skips_empty_email(self):
        records = [
            {'email': '', 'name': 'Invalid', 'age': 30},
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
        ]
        schema = {'email': str, 'name': str, 'age': int}
        result = clean_records(records, schema)
        assert len(result) == 1
        assert result[0]['email'] == 'alice@example.com'

    def test_clean_empty_input(self):
        records = []
        schema = {'email': str, 'name': str}
        result = clean_records(records, schema)
        assert result == []

    def test_clean_normalizes_case(self):
        records = [
            {'email': 'ALICE@EXAMPLE.COM', 'name': 'Alice', 'age': 30},
        ]
        schema = {'email': str, 'name': str, 'age': int}
        result = clean_records(records, schema)
        assert result[0]['email'] == 'alice@example.com'

    def test_clean_does_not_modify_original(self):
        records = [
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
        ]
        schema = {'email': str, 'name': str, 'age': int}
        original_email = records[0]['email']
        clean_records(records, schema)
        assert records[0]['email'] == original_email


class TestAggregateByDomain:
    """Tests for aggregate_by_domain function."""

    def test_aggregate_single_domain(self):
        records = [
            {'email': 'alice@example.com'},
            {'email': 'bob@example.com'},
            {'email': 'charlie@example.com'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'example.com': 3}

    def test_aggregate_multiple_domains(self):
        records = [
            {'email': 'alice@example.com'},
            {'email': 'bob@example.org'},
            {'email': 'charlie@test.com'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'example.com': 1, 'example.org': 1, 'test.com': 1}

    def test_aggregate_empty_input(self):
        records = []
        result = aggregate_by_domain(records)
        assert result == {}

    def test_aggregate_no_domain(self):
        records = [
            {'email': 'no-domain'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'unknown': 1}

    def test_aggregate_mixed_valid_invalid(self):
        records = [
            {'email': 'alice@example.com'},
            {'email': 'no-at-sign'},
            {'email': 'bob@test.org'},
        ]
        result = aggregate_by_domain(records)
        assert result == {'example.com': 1, 'unknown': 1, 'test.org': 1}


class TestPipeline:
    """End-to-end tests for pipeline function."""

    def test_pipeline_success(self, tmp_path):
        data = [
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
            {'email': 'bob@example.com', 'name': 'Bob', 'age': 25},
        ]
        f = tmp_path / 'data.json'
        f.write_text(json.dumps(data))
        schema = {'email': str, 'name': str, 'age': int}
        result = pipeline(str(f), schema)
        assert result == {'example.com': 2}

    def test_pipeline_with_duplicates(self, tmp_path):
        data = [
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},
            {'email': 'ALICE@example.com', 'name': 'Alice2', 'age': 25},
            {'email': 'bob@test.org', 'name': 'Bob', 'age': 20},
        ]
        f = tmp_path / 'data.json'
        f.write_text(json.dumps(data))
        schema = {'email': str, 'name': str, 'age': int}
        result = pipeline(str(f), schema)
        assert result == {'example.com': 1, 'test.org': 1}

    def test_pipeline_with_invalid_records(self, tmp_path):
        data = [
            {'email': 123, 'name': 'Invalid', 'age': 30},  # invalid
            {'email': 'alice@example.com', 'name': 'Alice', 'age': 30},  # valid
            {'name': 'NoEmail'},  # invalid
        ]
        f = tmp_path / 'data.json'
        f.write_text(json.dumps(data))
        schema = {'email': str, 'name': str, 'age': int}
        result = pipeline(str(f), schema)
        assert result == {'example.com': 1}

    def test_pipeline_empty_file(self, tmp_path):
        f = tmp_path / 'empty.json'
        f.write_text('[]')
        schema = {'email': str, 'name': str}
        result = pipeline(str(f), schema)
        assert result == {}

    def test_pipeline_invalid_json(self, tmp_path):
        f = tmp_path / 'bad.json'
        f.write_text('not json')
        schema = {'email': str}
        with pytest.raises(json.JSONDecodeError):
            pipeline(str(f), schema)

    def test_pipeline_non_list_json(self, tmp_path):
        f = tmp_path / 'obj.json'
        f.write_text('{"key": "value"}')
        schema = {'email': str}
        with pytest.raises(ValueError, match='expected list'):
            pipeline(str(f), schema)

    def test_pipeline_missing_file(self):
        schema = {'email': str}
        with pytest.raises(FileNotFoundError):
            pipeline('nonexistent.json', schema)

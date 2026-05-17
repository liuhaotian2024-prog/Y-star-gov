# trial_id: 96b319ca59b4
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


# ---------------------------------------------------------------------------
# load_records
# ---------------------------------------------------------------------------

def test_load_records_happy(tmp_path):
    p = tmp_path / "data.json"
    data = [{"email": "a@b.com"}, {"email": "c@d.com"}]
    p.write_text(json.dumps(data), encoding="utf-8")
    assert load_records(str(p)) == data


def test_load_records_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_records("/nonexistent/path.json")


def test_load_records_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_records(str(p))


def test_load_records_not_a_list(tmp_path):
    p = tmp_path / "obj.json"
    p.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected list"):
        load_records(str(p))


def test_load_records_empty_list(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    assert load_records(str(p)) == []


# ---------------------------------------------------------------------------
# validate_record
# ---------------------------------------------------------------------------

def test_validate_record_happy():
    schema = {"name": str, "age": int}
    rec = {"name": "Alice", "age": 30}
    validate_record(rec, schema)  # no exception


def test_validate_record_missing_field():
    schema = {"name": str, "age": int}
    rec = {"name": "Bob"}
    with pytest.raises(ValidationError, match="missing field: age"):
        validate_record(rec, schema)


def test_validate_record_wrong_type():
    schema = {"name": str, "age": int}
    rec = {"name": "Charlie", "age": "old"}
    with pytest.raises(ValidationError, match="wrong type for age"):
        validate_record(rec, schema)


def test_validate_record_empty_schema():
    schema = {}
    rec = {"anything": 1}
    validate_record(rec, schema)  # should pass


# ---------------------------------------------------------------------------
# normalize_email
# ---------------------------------------------------------------------------

def test_normalize_email_happy():
    assert normalize_email("  Alice@Example.COM  ") == "alice@example.com"


def test_normalize_email_already_normalized():
    assert normalize_email("bob@test.org") == "bob@test.org"


def test_normalize_email_empty_raises():
    with pytest.raises(ValueError, match="empty email"):
        normalize_email("   ")


def test_normalize_email_empty_string():
    with pytest.raises(ValueError):
        normalize_email("")


# ---------------------------------------------------------------------------
# clean_records
# ---------------------------------------------------------------------------

def test_clean_records_happy():
    schema = {"email": str, "name": str}
    records = [
        {"email": "  A@B.COM  ", "name": "Alice"},
        {"email": "c@d.com", "name": "Charlie"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "c@d.com"


def test_clean_records_skips_invalid():
    schema = {"email": str, "name": str}
    records = [
        {"email": "a@b.com", "name": "Alice"},
        {"email": "bad", "name": "Bob"},          # missing @ -> normalize_email succeeds but domain later? Actually normalize_email works, but we test missing field
        {"name": "NoEmail"},                      # missing email field -> ValidationError
        {"email": 123, "name": "WrongType"},      # wrong type -> ValidationError
    ]
    result = clean_records(records, schema)
    # Only first record is valid (email is string, present, and normalize_email works)
    assert len(result) == 1
    assert result[0]["email"] == "a@b.com"


def test_clean_records_skips_empty_email():
    schema = {"email": str}
    records = [{"email": "   "}]
    result = clean_records(records, schema)
    assert result == []


def test_clean_records_deduplicates():
    schema = {"email": str}
    records = [
        {"email": "a@b.com"},
        {"email": "  A@B.COM  "},
        {"email": "c@d.com"},
    ]
    result = clean_records(records, schema)
    assert len(result) == 2
    assert result[0]["email"] == "a@b.com"
    assert result[1]["email"] == "c@d.com"


def test_clean_records_empty_input():
    assert clean_records([], {}) == []


def test_clean_records_preserves_other_fields():
    schema = {"email": str, "id": int}
    records = [{"email": "x@y.com", "id": 1, "extra": "keep"}]
    result = clean_records(records, schema)
    assert result[0]["extra"] == "keep"
    assert result[0]["email"] == "x@y.com"


# ---------------------------------------------------------------------------
# aggregate_by_domain
# ---------------------------------------------------------------------------

def test_aggregate_by_domain_happy():
    records = [
        {"email": "a@gmail.com"},
        {"email": "b@gmail.com"},
        {"email": "c@yahoo.com"},
    ]
    assert aggregate_by_domain(records) == {"gmail.com": 2, "yahoo.com": 1}


def test_aggregate_by_domain_no_at_sign():
    records = [{"email": "noatsign"}]
    assert aggregate_by_domain(records) == {"unknown": 1}


def test_aggregate_by_domain_empty():
    assert aggregate_by_domain([]) == {}


def test_aggregate_by_domain_multiple_unknown():
    records = [{"email": "a"}, {"email": "b"}]
    assert aggregate_by_domain(records) == {"unknown": 2}


# ---------------------------------------------------------------------------
# pipeline (integration)
# ---------------------------------------------------------------------------

def test_pipeline_happy(tmp_path):
    p = tmp_path / "data.json"
    data = [
        {"email": "  Alice@GMAIL.COM  ", "name": "Alice"},
        {"email": "bob@yahoo.com", "name": "Bob"},
        {"email": "  ALICE@GMAIL.COM  ", "name": "Alice dup"},
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    result = pipeline(str(p), schema)
    assert result == {"gmail.com": 1, "yahoo.com": 1}


def test_pipeline_empty_file(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("[]", encoding="utf-8")
    schema = {"email": str}
    assert pipeline(str(p), schema) == {}


def test_pipeline_all_invalid(tmp_path):
    p = tmp_path / "bad.json"
    data = [
        {"name": "NoEmail"},
        {"email": 42},
    ]
    p.write_text(json.dumps(data), encoding="utf-8")
    schema = {"email": str, "name": str}
    assert pipeline(str(p), schema) == {}


def test_pipeline_file_not_found():
    with pytest.raises(FileNotFoundError):
        pipeline("/nonexistent/path.json", {})


def test_pipeline_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{{{", encoding="utf-8")
    with pytest.raises(ValueError):
        pipeline(str(p), {})

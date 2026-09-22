"""Property-based test for the Normalizer missing-field exclusion (task 7.16).

Feature: multicloud-diagram-inventory, Property 12: Missing mandatory field excludes the resource with an error

Property 12 (design.md) — Missing mandatory field excludes the resource with an
error (**Validates: Requirements 4.6**):

    IF a native provider resource lacks a value required to populate a mandatory
    Inventory Schema field, THEN THE Normalizer SHALL record a missing-field
    error identifying the resource and the missing field and SHALL exclude the
    resource from the normalized output.

Strategy: start from a valid native resource that would normalize successfully,
then for a Hypothesis-chosen mandatory field in {name, boundary, region} either
drop the field entirely or set it to an empty string. The test asserts:

- :func:`normalize` raises :class:`NormalizationError` whose ``record.kind`` is
  ``"missing-field"`` and whose ``record.field`` names the dropped field, and
- :func:`normalize_all` excludes the resource (returns it in neither the
  normalized list) and records a matching ``missing-field`` error naming the
  field and referencing the resource.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.normalizer import (
    NormalizationError,
    normalize,
    normalize_all,
)

# The mandatory sourced fields that must be present and non-empty (schema
# minLength 1). These use the neutral field names, which are also accepted
# native aliases by the Normalizer's field extractor.
_MANDATORY_NONEMPTY_FIELDS = ("name", "boundary", "region")


def _valid_native() -> dict[str, str]:
    """A native resource that normalizes successfully for provider 'aws'."""
    return {
        "native_type": "aws_lambda_function",
        "id": "arn:aws:lambda:us-east-1:123456789012:function:my-fn",
        "name": "my-fn",
        "boundary": "123456789012",
        "region": "us-east-1",
    }


@settings(max_examples=200)
@given(
    field=st.sampled_from(_MANDATORY_NONEMPTY_FIELDS),
    empty=st.booleans(),
)
def test_missing_mandatory_field_excludes_with_error(field: str, empty: bool) -> None:
    """A dropped/empty mandatory field excludes the resource with a named error."""
    native = _valid_native()
    if empty:
        native[field] = ""  # present but empty -> still missing a value
    else:
        del native[field]  # entirely absent

    # normalize() raises with a missing-field record naming the field.
    try:
        normalize(native, "aws")
    except NormalizationError as exc:
        assert exc.record.kind == "missing-field"
        assert exc.record.field == field
        assert exc.record.resource, "error record must identify the resource"
    else:
        raise AssertionError(
            f"expected NormalizationError for missing field {field!r}"
        )

    # normalize_all() excludes the resource and records the matching error.
    normalized, errors = normalize_all([native], "aws")
    assert normalized == [], "resource missing a mandatory field must be excluded"
    assert len(errors) == 1
    (err,) = errors
    assert err.kind == "missing-field"
    assert err.field == field
    assert err.resource, "recorded error must identify the resource"


@settings(max_examples=200)
@given(field=st.sampled_from(_MANDATORY_NONEMPTY_FIELDS))
def test_valid_resource_with_field_present_is_not_excluded(field: str) -> None:
    """Control: with every mandatory field present, no missing-field error occurs."""
    native = _valid_native()
    # sanity: the chosen field is populated
    assert native[field]
    normalized, errors = normalize_all([native], "aws")
    assert len(normalized) == 1
    assert errors == []

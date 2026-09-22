"""Unit tests for Normalized Resource schema validation (task 5.3).

Exercises ``src/rule_engine/schema.py`` (``validate_resource``,
``resource_errors``, ``ResourceValidationError``) against the Inventory Schema
at ``schemas/inventory.schema.json``.

Coverage:

- Requirement 4.8: the Inventory Schema validates a sample Normalized Resource
  produced from each of the providers aws, azure, gcp, and oci.
- Requirement 4.1 / 4.2: a Normalized Resource must populate every mandatory
  field; a resource missing a required field (for example ``name`` or
  ``config_digest``) fails validation, and the error names the offending field.
- Requirement 4.1: a resource whose ``config_digest`` does not match the
  ``^[a-f0-9]{64}$`` pattern (malformed, uppercase, or too short) fails
  validation, and ``additionalProperties: false`` rejects an unexpected field.

Tests load the on-disk golden samples and call the schema module directly.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rule_engine.schema import (
    ResourceValidationError,
    resource_errors,
    validate_resource,
)

# Repository root is two levels up from this test file (tests/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"

# The four providers that ship a sample Normalized Resource (Requirement 4.8).
SAMPLE_PROVIDERS = ("aws", "azure", "gcp", "oci")

# A valid 64-char lowercase-hex config digest for building mutated fixtures.
_VALID_DIGEST = "a" * 64


def _load_sample(provider: str) -> dict:
    """Load the golden sample Normalized Resource for ``provider``."""
    path = EXAMPLES_DIR / provider / "sample-resource.json"
    assert path.exists(), f"sample resource missing: {path}"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Requirement 4.8 — each provider sample validates.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider", SAMPLE_PROVIDERS)
def test_provider_sample_validates(provider: str) -> None:
    """Each provider's golden sample conforms to the Inventory Schema."""
    sample = _load_sample(provider)
    # No validation errors reported.
    assert resource_errors(sample) == []
    # validate_resource passes and returns the resource unchanged.
    assert validate_resource(sample) is sample


# --------------------------------------------------------------------------- #
# Requirement 4.1 / 4.2 — a missing required field fails validation and the
# error names the offending field.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("missing_field", ["name", "config_digest"])
def test_missing_required_field_fails(missing_field: str) -> None:
    """Dropping a required field fails validation and names that field."""
    sample = _load_sample("aws")
    del sample[missing_field]

    errors = resource_errors(sample)
    assert errors, f"expected a validation error when {missing_field!r} is absent"
    # The offending field is named somewhere in the collected messages.
    assert any(missing_field in msg for msg in errors), (
        f"error messages {errors} should name the missing field {missing_field!r}"
    )

    # validate_resource raises, carrying the same messages on .errors.
    with pytest.raises(ResourceValidationError) as excinfo:
        validate_resource(sample)
    assert excinfo.value.errors == errors
    assert any(missing_field in msg for msg in excinfo.value.errors)


def test_all_required_fields_individually_enforced() -> None:
    """Removing any single required field causes validation to fail."""
    required = [
        "provider",
        "resource_type",
        "native_type",
        "id",
        "name",
        "boundary",
        "region",
        "tags",
        "config_digest",
    ]
    base = _load_sample("aws")
    for field in required:
        candidate = copy.deepcopy(base)
        del candidate[field]
        errors = resource_errors(candidate)
        assert errors, f"expected failure when required field {field!r} is missing"


# --------------------------------------------------------------------------- #
# Requirement 4.1 — a malformed config_digest fails validation.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_digest",
    [
        "not-a-hash",  # non-hex characters
        _VALID_DIGEST.upper(),  # uppercase hex is rejected by ^[a-f0-9]{64}$
        "a" * 63,  # too short
        "a" * 65,  # too long
        "",  # empty
    ],
)
def test_malformed_config_digest_fails(bad_digest: str) -> None:
    """A config_digest outside ^[a-f0-9]{64}$ fails validation."""
    sample = _load_sample("aws")
    sample["config_digest"] = bad_digest

    errors = resource_errors(sample)
    assert errors, f"expected failure for config_digest {bad_digest!r}"
    assert any("config_digest" in msg for msg in errors), (
        f"error messages {errors} should name config_digest"
    )

    with pytest.raises(ResourceValidationError):
        validate_resource(sample)


# --------------------------------------------------------------------------- #
# additionalProperties: false — an unexpected field is rejected.
# --------------------------------------------------------------------------- #
def test_extra_property_rejected() -> None:
    """An extra unexpected field is rejected by additionalProperties: false."""
    sample = _load_sample("aws")
    sample["unexpected_field"] = "surprise"

    errors = resource_errors(sample)
    assert errors, "expected failure for an unexpected additional property"

    with pytest.raises(ResourceValidationError):
        validate_resource(sample)

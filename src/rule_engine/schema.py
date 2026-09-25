"""Normalized Resource schema validation.

Loads ``schemas/inventory.schema.json`` (JSON Schema, Draft 2020-12) and
validates Normalized Resources against it. Used by the golden example
resources and, in later tasks, by the Normalizer before it emits a resource.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from rule_engine.constants import resolve_bundled_dir

# schemas/inventory.schema.json. Resolved from the repo root (dev), the bundled
# package payload (pip / Kiro-Power install), or the CWD (bootstrapped
# workspace) — so the schema loads in every install shape, not just a repo
# checkout.
_SCHEMA_PATH = resolve_bundled_dir("schemas") / "inventory.schema.json"


class ResourceValidationError(ValueError):
    """Raised when a resource fails Normalized Resource schema validation.

    The ``errors`` attribute holds the list of human-readable validation
    messages, one per schema violation.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(
            "Resource failed Normalized Resource schema validation:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def load_schema() -> dict[str, Any]:
    """Load and return the Normalized Resource JSON Schema.

    Returns a fresh copy each call so a caller that mutates the returned dict
    cannot corrupt the cached schema; the file read + parse behind it is cached
    (:func:`_cached_schema`), since the schema file is static at runtime and was
    otherwise re-read once per validated resource."""
    import copy

    return copy.deepcopy(_cached_schema())


@lru_cache(maxsize=1)
def _cached_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    """Return a cached validator.

    Constructing a ``Draft202012Validator`` re-checks the meta-schema, so it was
    the single biggest avoidable cost in the normalize path (one construction
    per resource). The validator is stateless across ``iter_errors`` calls, so
    one shared instance is safe to reuse. Built from the cached schema directly
    (not the deep-copied ``load_schema``) since the validator never mutates it."""
    return Draft202012Validator(_cached_schema())


def resource_errors(resource: Any) -> list[str]:
    """Return a sorted list of validation error messages for ``resource``.

    An empty list means the resource conforms to the Normalized Resource
    schema.
    """
    validator = _validator()
    errors = sorted(validator.iter_errors(resource), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in errors
    ]


def validate_resource(resource: Any) -> Any:
    """Validate ``resource`` against the Normalized Resource schema.

    Returns the resource unchanged when it is valid, so callers may use it
    inline. Raises :class:`ResourceValidationError` (with every violation
    collected in ``.errors``) when the resource does not conform.
    """
    errors = resource_errors(resource)
    if errors:
        raise ResourceValidationError(errors)
    return resource

"""Normalized Resource schema validation.

Loads ``schemas/inventory.schema.json`` (JSON Schema, Draft 2020-12) and
validates Normalized Resources against it. Used by the golden example
resources and, in later tasks, by the Normalizer before it emits a resource.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

# schemas/inventory.schema.json lives at the repository root, three parents up
# from this file: src/rule_engine/schema.py -> src/rule_engine -> src -> root.
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "inventory.schema.json"


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
    """Load and return the Normalized Resource JSON Schema."""
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


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

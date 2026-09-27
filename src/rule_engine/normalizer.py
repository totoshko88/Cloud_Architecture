"""Normalizer — native provider resources → Normalized Resources.

This module implements the Rule Engine Normalizer (design section 4c). It maps a
native provider resource into a :data:`NormalizedResource` (a plain ``dict``
conforming to ``schemas/inventory.schema.json``) and computes an
order-independent ``config_digest``.

Responsibilities (Requirement 4):

- **AC1 / AC2 / AC3** — produce a schema-conforming Normalized Resource, populate
  every mandatory field, and draw ``resource_type`` from the neutral terminology
  normalization table (the nine neutral types across ``aws``/``azure``/``gcp``/
  ``oci``/``generic``; see ``.kiro/steering/provider-profiles.md`` and the
  ``_SEED`` table in :mod:`rule_engine.assets.enumerate`).
- **AC4** — compute ``config_digest`` as a deterministic, order-independent
  SHA-256 hex digest via canonicalization: drop secret fields, recursively sort
  object keys lexicographically, sort array elements by their canonical
  serialization, serialize to compact UTF-8 JSON, and hash.
- **AC5 / AC6 / AC7** — record unmapped-type, missing-field, and
  schema-validation errors and *exclude* the offending resource from the output.

The batch entry point :func:`normalize_all` returns
``(normalized_list, errors_list)`` so a caller can see both the emitted resources
and every excluded resource with its reason. The single-resource entry point
:func:`normalize` raises :class:`NormalizationError` on any failure.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from rule_engine import identity, secret_safety
from rule_engine.constants import (
    NEUTRAL_RESOURCE_TYPES,
    PROVIDERS,
    native_aliases,
)
from rule_engine.identity import flat
from rule_engine.schema import ResourceValidationError, validate_resource

__all__ = [
    "PROVIDERS",
    "NEUTRAL_RESOURCE_TYPES",
    "MANDATORY_FIELDS",
    "TYPE_MAPPING",
    "NormalizationError",
    "NormalizationErrorRecord",
    "compute_config_digest",
    "canonicalize",
    "resolve_resource_type",
    "normalize",
    "normalize_all",
]

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
# PROVIDERS and NEUTRAL_RESOURCE_TYPES are re-exported from rule_engine.constants
# (the single source of truth) for backward compatibility with existing imports.

# Mandatory Inventory Schema fields (design section 4c "required"). ``id`` may be
# an empty string per the schema (minLength is not set on ``id``); every other
# field must be a non-empty value the caller supplies. ``config_digest`` is
# computed by the Normalizer, not sourced from the native resource.
MANDATORY_FIELDS: tuple[str, ...] = (
    "provider",
    "resource_type",
    "native_type",
    "id",
    "name",
    "boundary",
    "region",
    "tags",
    "config_digest",
)

# Fields the Normalizer sources from the native resource (config_digest is
# derived, resource_type is mapped, provider is supplied by the caller).
_SOURCED_FIELDS: tuple[str, ...] = (
    "native_type",
    "id",
    "name",
    "boundary",
    "region",
    "tags",
)

# --------------------------------------------------------------------------- #
# Terminology normalization table (native provider type -> neutral type)
# --------------------------------------------------------------------------- #
#
# The neutral-concept -> per-provider mapping is authoritative in
# ``.kiro/steering/provider-profiles.md`` (terminology normalization table) and
# mirrored by the ``_SEED`` icon table in
# :mod:`rule_engine.assets.enumerate`. Here we invert it: for each provider we
# map the *native* service type strings a collector might emit onto the neutral
# ``resource_type``. Matching is case-insensitive and tolerant of common
# spellings/aliases so a native type such as ``"AWS::Lambda::Function"``,
# ``"lambda"`` or ``"aws_lambda_function"`` all resolve to ``serverless_fn``.

# neutral_type -> {provider -> (native aliases...)}, loaded from the single
# terminology source of truth (profiles/terminology.yaml via constants).
_NATIVE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = native_aliases()


def _build_type_mapping() -> dict[str, dict[str, str]]:
    """Build ``{provider -> {normalized_native_alias -> neutral_type}}``.

    Every native alias is normalized (lower-cased, non-alphanumerics collapsed to
    a single underscore) so lookups are tolerant of separators and casing. The
    neutral type strings themselves are always accepted as their own aliases.
    """
    table: dict[str, dict[str, str]] = {p: {} for p in PROVIDERS}
    for neutral, per_provider in _NATIVE_ALIASES.items():
        for provider, aliases in per_provider.items():
            bucket = table[provider]
            # The neutral type string is always a valid alias for itself.
            bucket[_norm_key(neutral)] = neutral
            for alias in aliases:
                bucket[_norm_key(alias)] = neutral
    return table


def _norm_key(text: str) -> str:
    """Normalize a native-type string for tolerant lookup."""
    return re.sub(r"[^0-9a-z]+", "_", str(text).lower()).strip("_")


# provider -> normalized-native-alias -> neutral resource_type.
TYPE_MAPPING: dict[str, dict[str, str]] = _build_type_mapping()

# --------------------------------------------------------------------------- #
# Secret-safety: keys dropped from the config before hashing
# --------------------------------------------------------------------------- #
#
# Any object key that names credential material is dropped during
# canonicalization (design section 4c step 1; secret-safety), so secret values,
# key material, and SecureString contents stay out of the hashed bytes. The
# credential-key predicate is the single shared one from
# :mod:`rule_engine.secret_safety` (design §5), so the digest drop list, the
# redactor and the Linter cannot disagree about what a secret key is.


def _is_secret_key(key: str) -> bool:
    """Return True when ``key`` names a secret-bearing field to drop.

    Delegates to :func:`secret_safety.is_credential_key`, the single shared
    key-name rule (design §5). It already keeps a bare object-store ``key``
    metadata via :data:`secret_safety.METADATA_KEYS` where appropriate and
    treats compound credential names (``private_key``, ``secret_key``,
    ``password``) as secrets.
    """
    return secret_safety.is_credential_key(key)


# --------------------------------------------------------------------------- #
# Canonicalization + digest (Requirement 4 AC4, design section 4c)
# --------------------------------------------------------------------------- #


def canonicalize(value: Any) -> Any:
    """Return an order-independent canonical form of ``value``.

    - ``dict``: secret keys are dropped; remaining keys are recursively
      canonicalized and the mapping is rebuilt in lexicographic key order.
    - ``list``/``tuple``/``set``: each element is recursively canonicalized and
      the resulting elements are sorted by their canonical JSON serialization so
      that element ordering does not affect the result.
    - scalars (``str``/``int``/``float``/``bool``/``None``): returned unchanged.

    The returned structure is composed only of ``dict``, ``list`` and JSON
    scalars, ready for a stable ``json.dumps`` with ``sort_keys=True``.
    """
    if isinstance(value, dict):
        # Build from items so non-string keys are stringified consistently,
        # secret keys are dropped, and the mapping is rebuilt in key order.
        items: dict[str, Any] = {}
        for k, v in value.items():
            sk = str(k)
            if _is_secret_key(sk):
                continue
            items[sk] = canonicalize(v)
        return {k: items[k] for k in sorted(items)}
    if isinstance(value, (list, tuple, set)):
        canon_elems = [canonicalize(v) for v in value]
        return sorted(canon_elems, key=_stable_serialize)
    # JSON scalars pass through unchanged.
    return value


def _stable_serialize(value: Any) -> str:
    """Serialize a canonical value to stable compact JSON (used as a sort key)."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def compute_config_digest(config: Any) -> str:
    """Compute the order-independent ``config_digest`` for ``config``.

    Canonicalizes ``config`` (drop secret fields; recursively sort object keys
    lexicographically; sort array elements by canonical serialization),
    serializes the canonical form to compact UTF-8 JSON with no insignificant
    whitespace, and returns the lowercase SHA-256 hex digest (64 chars, matching
    ``^[a-f0-9]{64}$``).

    Deterministic and order-independent: two configurations equal as maps/sets
    (independent of key or element ordering) produce identical digests
    (Requirement 4 AC4).
    """
    canon = canonicalize(config)
    payload = _stable_serialize(canon).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NormalizationErrorRecord:
    """A single recorded normalization failure for an excluded resource.

    Attributes
    ----------
    kind:
        One of ``"unmapped-type"``, ``"missing-field"``, or
        ``"schema-validation"``.
    resource:
        A best-effort identifier for the offending native resource (its native
        type + id/name), so a caller can see which resource was excluded.
    detail:
        Human-readable description of the failure. For a missing-field error this
        names the missing field; for a schema-validation error this lists the
        failing constraint(s).
    field:
        The offending field name for a missing-field error, else ``None``.
    """

    kind: str
    resource: str
    detail: str
    field: str | None = None

    def __str__(self) -> str:  # pragma: no cover - convenience
        return f"[{self.kind}] {self.resource}: {self.detail}"


class NormalizationError(ValueError):
    """Raised by :func:`normalize` when a single resource cannot be normalized.

    The ``record`` attribute holds the underlying
    :class:`NormalizationErrorRecord`.
    """

    def __init__(self, record: NormalizationErrorRecord) -> None:
        self.record = record
        super().__init__(str(record))


# --------------------------------------------------------------------------- #
# Type resolution
# --------------------------------------------------------------------------- #


def resolve_resource_type(native_type: Any, provider: str) -> str | None:
    """Return the neutral ``resource_type`` for ``native_type`` under ``provider``.

    Returns ``None`` when the native type has no defined mapping for the provider
    (an unmapped type). Lookup is tolerant of casing and separators.
    """
    if provider not in TYPE_MAPPING:
        return None
    if native_type is None:
        return None
    return TYPE_MAPPING[provider].get(_norm_key(native_type))


# --------------------------------------------------------------------------- #
# Native-field extraction helpers
# --------------------------------------------------------------------------- #

# Common native field aliases for each sourced Normalized field, expressed as
# **flat** names (lower-cased, non-alphanumerics dropped — :func:`identity.flat`).
# ``_extract`` matches them against a resource's own keys by their flat spelling,
# so a PascalCase SDK response (``InstanceId``, ``DisplayName``, ``Tags``)
# resolves exactly like ``instance_id`` / ``display_name`` / ``tags`` (R5.3).
# The first present, non-empty alias wins.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "native_type": ("nativetype", "type", "resourcetype", "kind"),
    "id": ("id", "arn", "resourceid", "selflink", "ocid", "uid"),
    "name": ("name", "displayname", "resourcename"),
    "boundary": ("boundary", "boundaryid", "account", "accountid", "subscription",
                 "subscriptionid", "project", "projectid", "tenancy", "compartment",
                 "compartmentid"),
    "region": ("region", "location", "availabilitydomain", "zone"),
    "tags": ("tags", "labels"),
}


def _flat_lookup(native: dict[str, Any]) -> dict[str, str]:
    """Build ``{flat(key): original_key}`` once per resource.

    Keys are flattened with :func:`identity.flat` (lower-cased, non-alphanumerics
    dropped) so field aliases match case- and separator-insensitively. The first
    original spelling of a flattened key wins, mirroring
    :func:`identity.native_identity`.
    """
    lookup: dict[str, str] = {}
    for key in native:
        if isinstance(key, str):
            lookup.setdefault(flat(key), key)
    return lookup


def _extract(native: dict[str, Any], field: str, flat_map: dict[str, str]) -> Any:
    """Return the first present value among ``field``'s flat aliases, else ``None``.

    ``flat_map`` is the ``{flat(key): original_key}`` lookup built once per
    resource by :func:`_flat_lookup`; each alias is already a flat name, so the
    match is case- and separator-insensitive (R5.3).
    """
    for alias in _FIELD_ALIASES[field]:
        original = flat_map.get(alias)
        if original is not None:
            return native[original]
    return None


def _redact_str(value: str) -> str:
    """Redact a scalar string field through the shared redactor (R3.7).

    :func:`secret_safety.redact` replaces a string that embeds secret material
    (a URL userinfo password, a PEM/OpenSSH private-key block, an inline
    assignment) with :data:`secret_safety.REDACTED`, and returns a benign value
    unchanged.
    """
    return secret_safety.redact(value)


def _resource_ident(native: dict[str, Any], flat_map: dict[str, str]) -> str:
    """Best-effort identifier string for error messages."""
    nt = _extract(native, "native_type", flat_map)
    ident = _extract(native, "id", flat_map) or _extract(native, "name", flat_map)
    parts = [str(p) for p in (nt, ident) if p not in (None, "")]
    return "/".join(parts) if parts else "<unknown resource>"


def _coerce_tags(raw: Any) -> dict[str, str] | None:
    """Coerce native tags/labels into a ``{str: str}`` map.

    Accepts a mapping (values stringified) or a list of ``{"Key":..,"Value":..}``
    entries (the AWS tag-list shape). Returns ``None`` when the shape is
    unusable, so the caller records a missing-field error rather than emitting an
    invalid resource. An absent tags value defaults to an empty map upstream.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, (list, tuple)):
        out: dict[str, str] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                return None
            key = entry.get("Key", entry.get("key"))
            val = entry.get("Value", entry.get("value"))
            if key is None:
                return None
            out[str(key)] = "" if val is None else str(val)
        return out
    return None


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def _normalize_one(
    native_resource: Any, provider: str
) -> tuple[dict[str, Any] | None, NormalizationErrorRecord | None]:
    """Normalize a single native resource.

    Returns ``(normalized, None)`` on success or ``(None, error_record)`` when
    the resource is excluded. Never raises for expected failures; callers that
    want an exception use :func:`normalize`.
    """
    if provider not in PROVIDERS:
        return None, NormalizationErrorRecord(
            kind="schema-validation",
            resource="<unknown resource>",
            detail=f"unknown provider {provider!r}; expected one of {', '.join(PROVIDERS)}",
        )

    if not isinstance(native_resource, dict):
        return None, NormalizationErrorRecord(
            kind="missing-field",
            resource="<unknown resource>",
            detail=f"native resource must be a mapping, got {type(native_resource).__name__}",
            field="<native resource>",
        )

    # Flat-key lookup built once per resource: field aliases match case- and
    # separator-insensitively against the resource's own keys (R5.3).
    flat_map = _flat_lookup(native_resource)
    ident = _resource_ident(native_resource, flat_map)

    # --- resource_type mapping (AC3 / AC5) --------------------------------- #
    native_type = _extract(native_resource, "native_type", flat_map)
    if native_type is None or str(native_type) == "":
        return None, NormalizationErrorRecord(
            kind="missing-field",
            resource=ident,
            detail="missing mandatory field 'native_type'",
            field="native_type",
        )
    resource_type = resolve_resource_type(native_type, provider)
    if resource_type is None:
        return None, NormalizationErrorRecord(
            kind="unmapped-type",
            resource=ident,
            detail=(
                f"native type {str(native_type)!r} has no Normalized Resource Type "
                f"mapping for provider {provider!r}"
            ),
        )

    # --- mandatory sourced fields (AC2 / AC6) ------------------------------ #
    normalized: dict[str, Any] = {
        "provider": provider,
        "resource_type": resource_type,
        "native_type": str(native_type),
    }

    # id: consult the shared identity vocabulary first (the provider's
    # priority-ordered identity keys, matched case- and separator-insensitively),
    # then fall back to the generic id aliases. The schema permits an empty
    # string but the field must be present; default to "".
    raw_id = identity.native_identity(native_resource, provider)
    if raw_id is None:
        raw_id = _extract(native_resource, "id", flat_map)
    normalized["id"] = "" if raw_id is None else _redact_str(str(raw_id))

    # name / boundary / region: must be present and non-empty (schema minLength 1).
    for field in ("name", "boundary", "region"):
        raw = _extract(native_resource, field, flat_map)
        if raw is None or str(raw) == "":
            return None, NormalizationErrorRecord(
                kind="missing-field",
                resource=ident,
                detail=f"missing mandatory field {field!r}",
                field=field,
            )
        # Extracted string fields pass through the shared redactor so a secret
        # embedded in a value (a URL password, a PEM block) is never written
        # to the record (R3.7).
        normalized[field] = _redact_str(str(raw))

    # tags: default to {} when absent; coerce lists/maps to {str: str}, then
    # redact so a tag named DB_PASSWORD (or one carrying secret content) is
    # written as [REDACTED] (R3.7).
    tags = _coerce_tags(_extract(native_resource, "tags", flat_map))
    if tags is None:
        return None, NormalizationErrorRecord(
            kind="missing-field",
            resource=ident,
            detail="field 'tags' has an unsupported shape (expected map or key/value list)",
            field="tags",
        )
    normalized["tags"] = secret_safety.redact(tags)

    # --- config_digest (AC4) ---------------------------------------------- #
    # Hash the native resource configuration. Prefer an explicit 'config' block
    # when present; otherwise hash the whole native resource. Secret fields are
    # dropped inside compute_config_digest via canonicalization.
    config_source = (
        native_resource["config"]
        if isinstance(native_resource.get("config"), (dict, list))
        else native_resource
    )
    normalized["config_digest"] = compute_config_digest(config_source)

    # --- schema validation (AC1 / AC7) ------------------------------------ #
    try:
        validate_resource(normalized)
    except ResourceValidationError as exc:
        return None, NormalizationErrorRecord(
            kind="schema-validation",
            resource=ident,
            detail="failed Inventory Schema validation: " + "; ".join(exc.errors),
        )

    return normalized, None


def normalize(native_resource: Any, provider: str) -> dict[str, Any]:
    """Normalize a single native resource into a Normalized Resource dict.

    Returns the schema-conforming Normalized Resource on success. Raises
    :class:`NormalizationError` (carrying the :class:`NormalizationErrorRecord`)
    when the resource has an unmapped type, is missing a mandatory field, or the
    produced resource fails schema validation.
    """
    normalized, error = _normalize_one(native_resource, provider)
    if error is not None:
        raise NormalizationError(error)
    assert normalized is not None  # for type-checkers
    return normalized


def normalize_all(
    native_resources: list[Any], provider: str
) -> tuple[list[dict[str, Any]], list[NormalizationErrorRecord]]:
    """Batch-normalize native resources for a single provider.

    Returns ``(normalized_list, errors_list)``. Each successfully normalized
    resource is appended to ``normalized_list``; each excluded resource records a
    :class:`NormalizationErrorRecord` in ``errors_list`` (unmapped-type,
    missing-field, or schema-validation). One resource's failure never aborts the
    batch, so a caller can see every excluded resource and its reason
    (Requirement 4 AC5–AC7).
    """
    normalized_list: list[dict[str, Any]] = []
    errors_list: list[NormalizationErrorRecord] = []
    for native in native_resources:
        result, error = _normalize_one(native, provider)
        if error is not None:
            errors_list.append(error)
        else:
            assert result is not None
            normalized_list.append(result)
    return normalized_list, errors_list

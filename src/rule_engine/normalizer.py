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

PROVIDERS: tuple[str, ...] = ("aws", "azure", "gcp", "oci", "generic")

# The nine neutral resource types (Inventory Schema enum, design section 4c).
NEUTRAL_RESOURCE_TYPES: tuple[str, ...] = (
    "boundary",
    "network_boundary",
    "serverless_fn",
    "object_store",
    "managed_sql",
    "message_queue",
    "secrets_store",
    "managed_k8s",
    "llm_platform",
)

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

# neutral_type -> {provider -> [native aliases...]}
_NATIVE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "boundary": {
        "aws": ("account", "aws::organizations::account", "aws_account"),
        "azure": ("subscription", "azurerm_subscription"),
        "gcp": ("project", "google_project", "cloudresourcemanager.project"),
        "oci": ("tenancy", "compartment", "oci_identity_compartment"),
        "generic": ("environment", "boundary"),
    },
    "network_boundary": {
        "aws": ("vpc", "aws::ec2::vpc", "aws_vpc"),
        "azure": ("vnet", "virtualnetwork", "virtual_network", "azurerm_virtual_network"),
        "gcp": ("vpc", "google_compute_network", "compute.network"),
        "oci": ("vcn", "virtual_cloud_network", "oci_core_vcn"),
        "generic": ("network", "network_boundary"),
    },
    "serverless_fn": {
        "aws": ("lambda", "aws::lambda::function", "aws_lambda_function"),
        "azure": ("functions", "function_app", "functionapp", "azurerm_function_app"),
        "gcp": ("cloud_functions", "cloudfunctions.function", "google_cloudfunctions_function"),
        "oci": ("functions", "oci_functions_function", "fnfunction"),
        "generic": ("function", "serverless_fn"),
    },
    "object_store": {
        "aws": ("s3", "aws::s3::bucket", "aws_s3_bucket", "bucket"),
        "azure": ("blob_storage", "blobstorage", "storage_account", "storageaccount",
                  "azurerm_storage_account"),
        "gcp": ("cloud_storage", "storage.bucket", "google_storage_bucket", "gcs"),
        "oci": ("object_storage", "oci_objectstorage_bucket", "bucket"),
        "generic": ("object_store",),
    },
    "managed_sql": {
        "aws": ("rds", "aws::rds::dbinstance", "aws_db_instance", "db_instance"),
        "azure": ("azure_sql_db", "sql_database", "sqldatabase", "azurerm_sql_database",
                  "azurerm_mssql_database"),
        "gcp": ("cloud_sql", "sqladmin.instance", "google_sql_database_instance"),
        "oci": ("autonomous_database", "db_system", "dbsystem",
                "oci_database_autonomous_database"),
        "generic": ("managed_sql",),
    },
    "message_queue": {
        "aws": ("sqs", "aws::sqs::queue", "aws_sqs_queue", "queue"),
        "azure": ("service_bus", "servicebus", "servicebus_queue",
                  "azurerm_servicebus_queue"),
        "gcp": ("pubsub", "pub_sub", "pubsub.topic", "google_pubsub_topic"),
        "oci": ("streaming", "queue", "oci_streaming_stream", "oci_queue_queue"),
        "generic": ("message_queue",),
    },
    "secrets_store": {
        "aws": ("secrets_manager", "aws::secretsmanager::secret",
                "aws_secretsmanager_secret"),
        "azure": ("key_vault", "keyvault", "azurerm_key_vault"),
        "gcp": ("secret_manager", "secretmanager.secret", "google_secret_manager_secret"),
        "oci": ("vault", "oci_kms_vault"),
        "generic": ("secrets_store",),
    },
    "managed_k8s": {
        "aws": ("eks", "aws::eks::cluster", "aws_eks_cluster"),
        "azure": ("aks", "kubernetes_service", "azurerm_kubernetes_cluster"),
        "gcp": ("gke", "container.cluster", "google_container_cluster"),
        "oci": ("oke", "container_engine", "oci_containerengine_cluster"),
        "generic": ("managed_kubernetes", "managed_k8s"),
    },
    "llm_platform": {
        "aws": ("bedrock", "aws::bedrock::model", "aws_bedrock"),
        "azure": ("azure_openai", "cognitive_services", "openai",
                  "azurerm_cognitive_account"),
        "gcp": ("vertex_ai", "vertexai", "aiplatform", "google_vertex_ai"),
        "oci": ("generative_ai", "genai", "oci_generative_ai"),
        "generic": ("llm_platform",),
    },
}


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
# Any object key whose (lower-cased) name contains one of these substrings is a
# secret-bearing field and is dropped during canonicalization (design section 4c
# step 1; secret-safety). This keeps secret values, key material, and
# SecureString contents out of the hashed bytes.
_SECRET_KEY_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "privatekey",
    "securestring",
    "apikey",
    "api_key",
    "access_key",
    "accesskey",
    "secret_key",
    "secretkey",
    "session_token",
)


def _is_secret_key(key: str) -> bool:
    """Return True when ``key`` names a secret-bearing field to drop."""
    low = str(key).lower()
    if low in ("key", "keys"):
        # Bare "key" is ambiguous (e.g. an object-store key/path); the design's
        # secret heuristic targets credential material, so treat only compound
        # names such as ``private_key``/``secret_key`` as secrets. A bare "key"
        # is retained.
        return False
    return any(sub in low for sub in _SECRET_KEY_SUBSTRINGS)


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

# Common native field aliases for each sourced Normalized field. The native
# resource is expected to be a mapping; the first present, non-empty alias wins.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "native_type": ("native_type", "type", "resource_type", "kind"),
    "id": ("id", "arn", "resource_id", "self_link", "ocid", "uid"),
    "name": ("name", "display_name", "resource_name"),
    "boundary": ("boundary", "boundary_id", "account", "account_id", "subscription",
                 "subscription_id", "project", "project_id", "tenancy", "compartment",
                 "compartment_id"),
    "region": ("region", "location", "availability_domain", "zone"),
    "tags": ("tags", "labels"),
}


def _extract(native: dict[str, Any], field: str) -> Any:
    """Return the first present value among ``field``'s aliases, else ``None``."""
    for alias in _FIELD_ALIASES[field]:
        if alias in native:
            return native[alias]
    return None


def _resource_ident(native: dict[str, Any]) -> str:
    """Best-effort identifier string for error messages."""
    nt = _extract(native, "native_type")
    ident = _extract(native, "id") or _extract(native, "name")
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

    ident = _resource_ident(native_resource)

    # --- resource_type mapping (AC3 / AC5) --------------------------------- #
    native_type = _extract(native_resource, "native_type")
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

    # id: schema permits an empty string, but must be present. Default to "".
    raw_id = _extract(native_resource, "id")
    normalized["id"] = "" if raw_id is None else str(raw_id)

    # name / boundary / region: must be present and non-empty (schema minLength 1).
    for field in ("name", "boundary", "region"):
        raw = _extract(native_resource, field)
        if raw is None or str(raw) == "":
            return None, NormalizationErrorRecord(
                kind="missing-field",
                resource=ident,
                detail=f"missing mandatory field {field!r}",
                field=field,
            )
        normalized[field] = str(raw)

    # tags: default to {} when absent; coerce lists/maps to {str: str}.
    tags = _coerce_tags(_extract(native_resource, "tags"))
    if tags is None:
        return None, NormalizationErrorRecord(
            kind="missing-field",
            resource=ident,
            detail="field 'tags' has an unsupported shape (expected map or key/value list)",
            field="tags",
        )
    normalized["tags"] = tags

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

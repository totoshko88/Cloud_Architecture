"""Diagram & Inventory Rule Engine — Inventory Collector.

This module implements the provider-neutral **Inventory Collector**
(Requirement 3; design "Inventory & Delta Pipeline"; steering
``.kiro/steering/inventory-standards.md``). Inventory collection is strictly
**read-only**: no provider state is ever created, updated, or deleted.

Public interface::

    collect(provider, boundary_id, region, *, output_root=None,
            enumerators=None, ...) -> {"snapshot_folder": str, "manifest": dict}

Because there is no live cloud in this environment, the collector is designed
around an injectable **enumerator** abstraction. An *enumerator* is a read-only
enumeration verb: a callable bound to a provider verb name (for example
``list_buckets``) that returns resource metadata for a single service domain.
Enumerators are grouped by *service domain* (``compute``, ``storage``,
``network``, ...) so the collector can write one JSON file per domain.

The collector enforces the read-only contract before calling any enumerator:

* Each enumerator's verb name MUST match one of the provider's read-only verb
  patterns (aws ``list*``/``describe*``/``get*``; azure ``az … list``/``show``;
  gcp ``gcloud … list``/``describe``; oci ``oci … list``/``get``). A verb that
  does not match is **never called**.
* Any verb that looks state-mutating (``create``/``put``/``update``/
  ``delete``/``remove``/``set`` and equivalents) is rejected and never called.
* Any verb that returns a secret value or mints a credential
  (``get_secret_value``, ``get_session_token``, ``az keyvault secret show``,
  ``az storage account keys list``, ``oci secrets secret-bundle get``, …) is
  rejected and never called, even though it is "read-only" (v1.6.1).
* Any verb carrying a shell metacharacter (``;``, ``&``, ``|``, a redirect, an
  expansion) is rejected and never called (v1.6.1).
* The count of executed state-mutating verbs per run is guaranteed to be zero
  and is recorded on the manifest (``mutating_verbs_executed: 0``).

On a single-service enumeration failure the collector records ``{service,
reason}`` in a failures list (surfaced in the manifest and in a ``failures``
domain file) and continues with the remaining services (Requirement 3.9).

Cost/billing data is collected only through the profile's declared cost
endpoint, supplied via ``cost_endpoint`` (Requirement 3.10).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from rule_engine import secret_safety
from rule_engine.constants import PROVIDERS as _PROVIDERS
from rule_engine.identity import content_identity, native_identity


# ---------------------------------------------------------------------------
# Provider read-only verb contracts (inventory-standards.md §1, provider-profiles)
# ---------------------------------------------------------------------------

# Valid providers come from rule_engine.constants (single source of truth).

# Per-provider read-only enumeration verb patterns. A verb name must match one
# of these to be eligible for execution. ``generic`` uses manual entry /
# Terraform-state import, so any injected verb is allowed (there are no live
# provider calls); state-mutating and secret-returning names are still rejected
# below.
#
# aws (v1.6.1): the prefix is ``list``/``describe``/``get`` in snake or Pascal
# case, and the character after it must be a real word boundary — end of name,
# ``_``/``-``, or the capital letter that starts the next camelCase word. The
# pre-1.6.1 patterns applied ``re.IGNORECASE`` to the whole expression, which
# made the boundary class ``[_A-Z]`` match *any* letter: ``listen`` and
# ``getanddeletebucket`` were accepted as read-only verbs. The flag is gone: the
# two accepted spellings of each prefix are listed explicitly, so the boundary
# stays case-sensitive. Kebab case (``describe-instances``, the form the
# inventory-standards §6 examples use) is accepted too.
_READ_ONLY_VERB_PATTERNS: Dict[str, Tuple[re.Pattern[str], ...]] = {
    "aws": (
        re.compile(r"^(?:list|List)(?:$|[_-]|[A-Z])"),
        re.compile(r"^(?:describe|Describe)(?:$|[_-]|[A-Z])"),
        re.compile(r"^(?:get|Get)(?:$|[_-]|[A-Z])"),
    ),
    # azure: "az … list" / "az … show" — the trailing sub-command is list/show.
    "azure": (
        re.compile(r"(^|[ _.])list$", re.IGNORECASE),
        re.compile(r"(^|[ _.])show$", re.IGNORECASE),
    ),
    # gcp: "gcloud … list" / "gcloud … describe".
    "gcp": (
        re.compile(r"(^|[ _.])list$", re.IGNORECASE),
        re.compile(r"(^|[ _.])describe$", re.IGNORECASE),
    ),
    # oci: "oci … list" / "oci … get".
    "oci": (
        re.compile(r"(^|[ _.])list$", re.IGNORECASE),
        re.compile(r"(^|[ _.])get$", re.IGNORECASE),
    ),
    # generic: manual entry / Terraform-state import — no live verb constraint.
    "generic": (re.compile(r".*"),),
}

# Tokens that mark a verb as state-mutating. A verb whose name contains any of
# these (as a whole word / camel- or snake-cased segment) is never executed.
_MUTATING_TOKENS = (
    "create",
    "put",
    "update",
    "delete",
    "remove",
    "set",
    "modify",
    "add",
    "attach",
    "detach",
    "start",
    "stop",
    "terminate",
    "destroy",
    "write",
    "patch",
    "enable",
    "disable",
    "revoke",
    "grant",
    "reset",
    "rotate",
)

# A verb-name segment is a maximal run of letters/digits, split on camelCase and
# non-alphanumeric separators.
_SEGMENT_RE = re.compile(r"[A-Za-z][a-z0-9]*|[A-Z]+(?![a-z])|[0-9]+")

# Shell metacharacters (v1.6.1). A verb is an operation name or a CLI phrase,
# never a command line: a ``;``/``&``/``|`` chains a second command, a ``<``/``>``
# redirect reads or writes a file, and a backtick or ``$`` expands one. None of
# them belongs in a read-only enumeration verb, so any of them rejects the verb
# outright — defence in depth for any caller that ever hands a verb to a shell.
_SHELL_META_RE = re.compile(r"[;&|<>`$\\\n\r]")

# Secret-returning and credential-minting operations (v1.6.1). These are
# *read-only* in the provider's own sense — they create, update and delete
# nothing — so the read-only patterns above admit them. But what they return is
# a secret value or a usable credential, which inventory-standards §7 forbids in
# any snapshot, and redaction cannot reliably undo that afterwards (an Azure
# ``keys list`` result carries the key under a benign ``value`` field). They are
# therefore rejected before execution, whatever the provider patterns say.
#
# Each pattern matches the verb *normalised* by :func:`_normalised_verb` — its
# camelCase / snake / kebab / space segments lowercased and joined with ``_`` —
# so ``GetSecretValue``, ``get_secret_value`` and ``get-secret-value`` are one
# name. The list is deliberately specific: metadata operations on the same
# services (``list_secrets``, ``describe_secret``, ``describe_parameters``,
# ``get_account_password_policy``, ``get_credential_report``,
# ``az keyvault secret list``) stay allowed.
#
# Each entry is ``(pattern, providers)``; ``providers`` is ``None`` when the
# pattern holds for every provider. Some shapes mean "secret" in one CLI and
# "metadata" in another: ``az storage account keys list`` returns the account
# keys, while ``gcloud kms keys list`` and ``oci kms management key list`` list
# key *metadata* (inventory-standards §6 puts them in the secrets.json floor).
# Those patterns are scoped to the provider whose command they describe.
_ALL = None
_AZURE = frozenset({"azure"})
_SECRET_VERB_PATTERNS: Tuple[Tuple[re.Pattern[str], Optional[frozenset]], ...] = (
    # Secrets Manager GetSecretValue / BatchGetSecretValue.
    (re.compile(r"(?:^|_)secret_value(?:_|$)"), _ALL),
    # OCI ``secrets secret-bundle get`` (returns the secret content).
    (re.compile(r"(?:^|_)secret_bundle(?:_|$)"), _ALL),
    # Azure ``keyvault secret show`` (returns the secret value).
    (re.compile(r"(?:^|_)secret_show$"), _ALL),
    # GCP ``secrets versions access`` (returns the secret payload).
    (re.compile(r"(?:^|_)versions_access$"), _ALL),
    # ``get-access-token`` / ``print-access-token`` (mints a bearer token).
    (re.compile(r"(?:^|_)access_token(?:_|$)"), _ALL),
    # ECR get-login-password, EC2 GetPasswordData, GetRandomPassword, Lightsail
    # GetRelationalDatabaseMasterUserPassword. The IAM account password *policy*
    # is metadata and stays allowed.
    (re.compile(r"(?:^|_)password(?!_policy)(?:_|$)"), _ALL),
    # Redshift GetClusterCredentials, SSO GetRoleCredentials, Cognito
    # GetCredentialsForIdentity, ``get-credentials`` (kubeconfig with a token).
    # Anchored on ``get``: IAM ListServiceSpecificCredentials is metadata.
    (re.compile(r"(?:^|_)get_(?:[a-z0-9]+_)*credentials(?:_|$)"), _ALL),
    # Lightsail GetInstanceAccessDetails (temporary SSH key material).
    (re.compile(r"(?:^|_)get_instance_access_details$"), _ALL),
    # STS GetSessionToken / GetFederationToken, ECR / CodeArtifact
    # GetAuthorizationToken, Cognito GetOpenIdToken: every ``get…token``.
    (re.compile(r"^get_(?:[a-z0-9]+_)*tokens?$"), _ALL),
    # SSM GetParameter / GetParameters / GetParametersByPath / GetParameterHistory
    # (a String parameter is returned in clear, a SecureString with its value).
    # DescribeParameters is metadata and stays allowed.
    (re.compile(r"^get_parameters?(?:_|$)"), _ALL),
    # S3 GetObject / OCI ``os object get``: object *content*, not metadata.
    (re.compile(r"^get_object$"), _ALL),
    (re.compile(r"(?:^|_)object_get$"), _ALL),
    # Azure ``show-connection-string`` (a connection string embeds the key).
    (re.compile(r"(?:^|_)connection_strings?(?:_|$)"), _ALL),
    # Azure ``acr credential show`` / ``… credential list`` (registry passwords).
    # ``az ad sp|app credential list`` returns key ids only and stays allowed.
    (re.compile(r"(?:^|_)acr_credential_(?:show|list)$"), _AZURE),
    # Azure ``… deployment list-publishing-credentials|profiles`` (passwords).
    (re.compile(r"(?:^|_)list_publishing_(?:credentials|profiles)$"), _AZURE),
    # Azure ``… keys list`` / ``… key show`` / ``admin-key show`` (storage,
    # Cosmos DB, Cognitive Services, Search, SignalR, Functions keys). Key Vault
    # ``key list`` / ``key show`` return key identifiers and public material only,
    # so they stay allowed.
    (re.compile(r"(?:^|(?<!keyvault)_)keys?_(?:list|show)$"), _AZURE),
    # Azure ``config appsettings list`` (app settings routinely hold secrets).
    (re.compile(r"(?:^|_)appsettings_list$"), _AZURE),
)


# ---------------------------------------------------------------------------
# Secret-safety redaction (inventory-standards.md §7; secret-safety)
# ---------------------------------------------------------------------------

# Secret detection lives in one place now (design §5, R3.6): the shared
# :mod:`rule_engine.secret_safety` vocabulary. ``redact_secrets`` is a thin alias
# of :func:`secret_safety.redact`, so the Collector, Normalizer and Linter cannot
# disagree about what a secret is. The marker lists, content regexes and pair
# helpers that used to live here were moved to ``secret_safety`` in task 3.1.
REDACTED = secret_safety.REDACTED

#: Recursively strip secret values from resource metadata. Alias of
#: :func:`secret_safety.redact` — applies the shared key-name, value-content and
#: pair-name rules and returns a redacted copy, never mutating the input.
redact_secrets = secret_safety.redact


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Enumerator:
    """A single read-only enumeration verb bound to a service domain.

    Attributes
    ----------
    service:
        The service-domain name (e.g. ``"compute"``, ``"storage"``,
        ``"network"``). Enumerators sharing a service are written to the same
        ``<service>.json`` file.
    verb:
        The provider verb name (e.g. ``"list_buckets"``, ``"describe_vpcs"``).
        Validated against the provider's read-only patterns before execution.
    fn:
        A zero-argument-ish callable invoked as ``fn(boundary_id=..., region=...)``
        (extra keyword arguments are tolerated). It returns an iterable of
        resource-metadata mappings for the service. It MUST NOT mutate provider
        state.
    """

    service: str
    verb: str
    fn: Callable[..., Any]


@dataclass
class CollectionResult:
    """The result of a collection run."""

    snapshot_folder: str
    manifest: Dict[str, Any]
    failures: List[Dict[str, str]] = field(default_factory=list)
    mutating_verbs_executed: int = 0
    rejected_verbs: List[Dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_folder": self.snapshot_folder,
            "manifest": self.manifest,
        }


class ProviderError(ValueError):
    """Raised when the requested provider is not a known profile."""


# ---------------------------------------------------------------------------
# Verb classification
# ---------------------------------------------------------------------------


def _verb_segments(verb: str) -> List[str]:
    """Split a verb name into lowercase alphanumeric segments."""
    # Take only the terminal command word for CLI-style verbs like
    # "az storage account list" as well as the full name for camel/snake verbs.
    return [seg.lower() for seg in _SEGMENT_RE.findall(verb)]


def is_mutating_verb(verb: str) -> bool:
    """Return True when ``verb`` looks like a state-mutating operation."""
    segments = set(_verb_segments(verb))
    return any(token in segments for token in _MUTATING_TOKENS)


def _normalised_verb(verb: str) -> str:
    """Return ``verb``'s segments lowercased and joined with ``_``.

    ``GetSecretValue``, ``get_secret_value``, ``get-secret-value`` and the CLI
    phrase ``az keyvault secret show`` all reduce to one comparable form, which
    is what :data:`_SECRET_VERB_PATTERNS` is written against."""
    return "_".join(_verb_segments(verb))


def has_shell_metacharacters(verb: str) -> bool:
    """Return True when ``verb`` carries a shell metacharacter (v1.6.1)."""
    return bool(_SHELL_META_RE.search(verb))


def is_secret_verb(verb: str, provider: Optional[str] = None) -> bool:
    """Return True when ``verb`` returns a secret value or mints a credential.

    Such operations are read-only in the provider's sense but violate
    secret-safety (inventory-standards §7), so they are never executed
    (v1.6.1). See :data:`_SECRET_VERB_PATTERNS` for the list and its rationale.

    ``provider`` scopes the provider-specific patterns (an Azure ``keys list``
    returns account keys; a GCP ``kms keys list`` lists key metadata). With no
    provider — or ``generic``, which has no live verbs to scope by — every
    pattern applies, the conservative reading.
    """
    normalised = _normalised_verb(verb)
    scoped = provider not in (None, "generic")
    return any(
        pattern.search(normalised)
        for pattern, providers in _SECRET_VERB_PATTERNS
        if providers is None or not scoped or provider in providers
    )


def rejection_reason(provider: str, verb: str) -> Optional[str]:
    """Return why ``verb`` may not run for ``provider``, or ``None`` if it may.

    The checks run in order of severity, so a verb that is both chained and
    mutating is reported for the chaining: shell metacharacters, then a
    state-mutating name, then a secret-returning / credential-minting operation,
    then a name that matches none of the provider's read-only patterns.
    """
    if has_shell_metacharacters(verb):
        return "shell metacharacter in verb rejected"
    if is_mutating_verb(verb):
        return "state-mutating verb rejected"
    if is_secret_verb(verb, provider):
        return "secret-returning or credential-minting verb rejected (secret-safety)"
    patterns = _READ_ONLY_VERB_PATTERNS.get(provider)
    if patterns is None or not any(p.search(verb) for p in patterns):
        return "verb does not match provider read-only patterns"
    return None


def is_read_only_verb(provider: str, verb: str) -> bool:
    """Return True when ``verb`` is a permitted read-only verb for ``provider``.

    A verb is permitted only when it carries no shell metacharacter, does not
    look state-mutating, does not return a secret or mint a credential, and
    matches one of the provider's read-only patterns (:func:`rejection_reason`).
    """
    return rejection_reason(provider, verb) is None


# ---------------------------------------------------------------------------
# Snapshot naming (inventory-standards.md §3)
# ---------------------------------------------------------------------------


def snapshot_folder_name(
    provider: str, boundary_id: str, region: str, started_at: datetime
) -> str:
    """Build the mandated snapshot folder name.

    ``inventory-<provider>-<boundary-id>-<region>-<YYYY-MM-DD_HHMM>`` where the
    timestamp is the UTC collection start.
    """
    ts = started_at.astimezone(timezone.utc).strftime("%Y-%m-%d_%H%M")
    return f"inventory-{provider}-{boundary_id}-{region}-{ts}"


# ---------------------------------------------------------------------------
# Manifest rendering (inventory-standards.md §4)
# ---------------------------------------------------------------------------

_MANIFEST_FIELDS = (
    "provider",
    "boundary_id",
    "region_set",
    "caller_identity",
    "tool_versions",
    "file_count",
    "delta_instructions",
)


def _render_manifest_md(manifest: Mapping[str, Any]) -> str:
    """Render ``00-MANIFEST.md`` from the manifest mapping.

    Every one of the seven required fields is emitted as a row; the caller is
    responsible for ensuring each value is non-empty.
    """
    lines = ["# Inventory Snapshot Manifest", "", "| Field | Value |", "| --- | --- |"]
    for key in _MANIFEST_FIELDS:
        value = manifest.get(key, "")
        if isinstance(value, (list, tuple)):
            rendered = ", ".join(str(v) for v in value)
        elif isinstance(value, Mapping):
            rendered = ", ".join(f"{k}={v}" for k, v in value.items())
        else:
            rendered = str(value)
        lines.append(f"| {key} | {rendered} |")

    # Surface non-fatal failures in the human-readable manifest as well.
    failures = manifest.get("failures") or []
    if failures:
        lines += ["", "## Enumeration failures (non-fatal)", "", "| Service | Reason |", "| --- | --- |"]
        for fail in failures:
            lines.append(f"| {fail.get('service', '')} | {fail.get('reason', '')} |")

    # v1.6.1: a rejected verb is never executed, so its service gets no domain
    # file. Without this section the snapshot gave no sign a domain was skipped
    # — the silent omission inventory-standards §6 forbids.
    rejected = manifest.get("rejected_verbs") or []
    if rejected:
        lines += [
            "",
            "## Rejected verbs (not executed)",
            "",
            "| Service | Verb | Reason |",
            "| --- | --- | --- |",
        ]
        for rej in rejected:
            lines.append(
                f"| {rej.get('service', '')} | {rej.get('verb', '')} | {rej.get('reason', '')} |"
            )

    # A same-identity duplicate is written under a hashed subfolder rather than
    # overwriting the first resource; surface each one so the snapshot is honest
    # about the collision (design §"Collector safety").
    duplicates = manifest.get("duplicates") or []
    if duplicates:
        lines += [
            "",
            "## Duplicate identities (hashed subfolders)",
            "",
            "| Service | Identity | Subfolder |",
            "| --- | --- | --- |",
        ]
        for dup in duplicates:
            lines.append(
                f"| {dup.get('service', '')} | {dup.get('identity', '')} | {dup.get('dirname', '')} |"
            )

    lines.append("")
    return "\n".join(lines)


def _slug(text: str) -> str:
    """Filesystem-safe slug for a resource subfolder name."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-")
    return slug or "resource"


def _resource_identity(resource: Mapping[str, Any], provider: str) -> str:
    """Return a stable identity for a resource (design §7, R5.5).

    Prefers the provider's native identity key (``native_identity``), falls back
    to the resource's ``name``, and finally to a content digest
    (``content_identity``) for a resource with no native identity key. The
    pre-1.7 ``"resource"`` catch-all — which collided every identity-less
    resource into one folder — is gone: an identity-less resource now gets a
    unique, reproducible digest instead.
    """
    native = native_identity(resource, provider)
    if native:
        return native
    name = resource.get("name")
    if isinstance(name, str) and name:
        return name
    return content_identity(resource)


# ---------------------------------------------------------------------------
# Input validation and collision-free snapshot layout (design §"Collector
# safety"; R5.4–R5.7)
# ---------------------------------------------------------------------------

#: Characters permitted in a ``boundary_id`` or ``region``. Note ``.`` is
#: allowed, so the regex alone does not stop ``..``; ``_validate_target`` also
#: resolves the target path and confirms it stays inside ``output_root``.
BOUNDARY_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


class CollectorInputError(ValueError):
    """Raised when a Collector input is unsafe (bad boundary/region or escaping
    path). Raised *before* any filesystem write, so ``output_root`` is left
    byte-for-byte unchanged (R5.6)."""


def _validate_target(root: Path, boundary_id: str, region: str, folder: str) -> Path:
    """Validate inputs and the target path before any filesystem call (R5.6).

    Raises :class:`CollectorInputError` when ``boundary_id`` or ``region`` carry
    a character outside :data:`BOUNDARY_RE`, or when ``(root / folder)`` resolves
    outside ``root`` (catching a ``..`` traversal the regex lets through via
    ``.``). Returns the resolved snapshot directory when the inputs are safe.
    """
    if not BOUNDARY_RE.match(boundary_id):
        raise CollectorInputError(
            f"unsafe boundary_id {boundary_id!r}: must match {BOUNDARY_RE.pattern}"
        )
    if not BOUNDARY_RE.match(region):
        raise CollectorInputError(
            f"unsafe region {region!r}: must match {BOUNDARY_RE.pattern}"
        )
    resolved_root = root.resolve()
    target = (root / folder).resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise CollectorInputError(
            f"snapshot path {target} escapes output_root {resolved_root}"
        )
    return target


def _allocate_snapshot_dir(root: Path, folder: str) -> Path:
    """Create and return a fresh snapshot directory, never merging an old one.

    Tries ``folder``, then ``folder-2``, ``folder-3``, … creating each with
    ``mkdir(exist_ok=False)`` so two runs (or two concurrent collectors) can
    never share a folder and an existing snapshot is never written into (R5.7).
    """
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / folder
    suffix = 2
    while True:
        try:
            candidate.mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = root / f"{folder}-{suffix}"
            suffix += 1


#: Maximum length of a resource subfolder name (design §"Collector safety").
_RESOURCE_DIRNAME_MAX = 100


def _resource_dirname(
    service: str,
    identity: str,
    taken: Dict[str, str],
    resource: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return a collision-free ``<slug(service)>-<slug(identity)>`` folder name.

    Truncated to :data:`_RESOURCE_DIRNAME_MAX` characters. A ``-<sha8>`` suffix
    (8 hex of ``sha256(identity)``) is appended when the plain name is already
    taken *by a different identity*, or when slugging was lossy (the slug does
    not round-trip the identity, so two distinct identities could otherwise
    collide). A **same-identity** duplicate (the same ``identity`` appearing
    again in the same service) is placed under
    ``-<sha256(identity + canonical json)[:8]>`` so it never overwrites the
    first resource's ``resource.json``; the caller lists it under the manifest's
    ``duplicates``.

    ``taken`` maps an already-allocated dirname to the identity that owns it and
    is updated in place, so ``write_text`` never targets an existing
    ``resource.json``.
    """
    base = f"{_slug(service)}-{_slug(identity)}"
    id_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    lossy = _slug(identity) != identity

    def _fit(name: str) -> str:
        return name[:_RESOURCE_DIRNAME_MAX]

    plain = _fit(base)
    owner = taken.get(plain)
    if owner == identity:
        # Same identity, same service → a duplicate. Give it a subfolder keyed
        # on the resource content so two identical-identity resources differ.
        canonical = json.dumps(
            resource if resource is not None else {},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        dup_hash = hashlib.sha256(
            (identity + canonical).encode("utf-8")
        ).hexdigest()[:8]
        suffixed = _fit(f"{base[: _RESOURCE_DIRNAME_MAX - 9]}-{dup_hash}")
        # In the (astronomically unlikely) event the duplicate hash also
        # collides, walk further hashes until a free name is found.
        n = 2
        candidate = suffixed
        while candidate in taken:
            candidate = _fit(f"{base[: _RESOURCE_DIRNAME_MAX - 9]}-{dup_hash}{n}")
            n += 1
        taken[candidate] = identity
        return candidate
    if owner is None and not lossy:
        taken[plain] = identity
        return plain
    # Different identity already owns the plain name, or slugging was lossy:
    # disambiguate with the identity hash.
    suffixed = _fit(f"{base[: _RESOURCE_DIRNAME_MAX - 9]}-{id_hash}")
    n = 2
    candidate = suffixed
    while candidate in taken and taken[candidate] != identity:
        candidate = _fit(f"{base[: _RESOURCE_DIRNAME_MAX - 9]}-{id_hash}{n}")
        n += 1
    taken[candidate] = identity
    return candidate


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def collect(
    provider: str,
    boundary_id: str,
    region: str,
    *,
    output_root: Optional[str | Path] = None,
    enumerators: Optional[Sequence[Enumerator | Mapping[str, Any]]] = None,
    caller_identity: str = "read-only-inventory-collector",
    tool_versions: Optional[Mapping[str, str]] = None,
    region_set: Optional[Sequence[str]] = None,
    cost_endpoint: Optional[str] = None,
    collect_cost: bool = False,
    started_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Collect a read-only inventory Snapshot for one provider boundary.

    Parameters
    ----------
    provider:
        One of ``aws``, ``azure``, ``gcp``, ``oci``, ``generic``.
    boundary_id:
        The Boundary identifier being enumerated (account/subscription/...).
    region:
        The region string used in the snapshot folder name.
    output_root:
        Directory under which the snapshot folder is created. Defaults to the
        current working directory. Tests inject a ``tmp_path`` here.
    enumerators:
        The read-only enumeration verbs to run, each an :class:`Enumerator` or a
        mapping with ``service``/``verb``/``fn`` keys. A verb that fails the
        read-only contract is rejected and never called.
    caller_identity:
        The read-only identity that performed collection (manifest field).
    tool_versions:
        CLI/SDK versions used (manifest field). Defaults to a package-version
        marker so the field is always non-empty.
    region_set:
        Regions covered by the snapshot (manifest field). Defaults to
        ``[region]``.
    cost_endpoint:
        The profile's declared cost/billing endpoint. Cost data is collected
        ONLY through this endpoint; ``collect_cost=True`` with no endpoint is a
        no-op that records the gap.
    collect_cost:
        Whether to record the declared cost endpoint usage.
    started_at:
        UTC collection start timestamp; defaults to ``datetime.now(timezone.utc)``.

    Returns
    -------
    dict
        ``{"snapshot_folder": <path str>, "manifest": <manifest dict>}``.
    """
    if provider not in _PROVIDERS:
        raise ProviderError(
            f"unknown provider {provider!r}; expected one of {_PROVIDERS}"
        )

    start = started_at or datetime.now(timezone.utc)
    root = Path(output_root) if output_root is not None else Path.cwd()

    folder_name = snapshot_folder_name(provider, boundary_id, region, start)
    # Validate boundary_id/region and the target path BEFORE any filesystem call,
    # so an unsafe input leaves output_root byte-for-byte unchanged (R5.6).
    _validate_target(root, boundary_id, region, folder_name)
    # Allocate a fresh snapshot folder (folder, folder-2, …); an existing
    # snapshot is never merged into (R5.7).
    snapshot_dir = _allocate_snapshot_dir(root, folder_name)
    resources_dir = snapshot_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Normalize enumerators to Enumerator instances.
    norm_enumerators: List[Enumerator] = []
    for enum in enumerators or ():
        if isinstance(enum, Enumerator):
            norm_enumerators.append(enum)
        elif isinstance(enum, Mapping):
            norm_enumerators.append(
                Enumerator(
                    service=enum["service"], verb=enum["verb"], fn=enum["fn"]
                )
            )
        else:  # pragma: no cover - defensive
            raise TypeError(
                "each enumerator must be an Enumerator or a mapping with "
                "service/verb/fn keys"
            )

    failures: List[Dict[str, str]] = []
    rejected: List[Dict[str, str]] = []
    mutating_executed = 0  # invariant: stays zero — mutating verbs never run

    # service -> list of redacted resource metadata dicts
    service_resources: Dict[str, List[Dict[str, Any]]] = {}

    for enum in norm_enumerators:
        # Read-only enforcement: reject anything not matching the profile's
        # read-only patterns, and never call a state-mutating, secret-returning,
        # or shell-chained verb (rejection_reason names which rule fired).
        reason = rejection_reason(provider, enum.verb)
        if reason is not None:
            rejected.append({"service": enum.service, "verb": enum.verb, "reason": reason})
            continue

        service_resources.setdefault(enum.service, [])
        try:
            raw = enum.fn(boundary_id=boundary_id, region=region)
        except Exception as exc:  # noqa: BLE001 - non-fatal per-service failure
            failures.append(
                {"service": enum.service, "verb": enum.verb, "reason": str(exc) or repr(exc)}
            )
            continue

        for resource in raw or ():
            if not isinstance(resource, Mapping):
                # Wrap non-mapping metadata so it can still be recorded safely.
                resource = {"value": resource}
            safe = redact_secrets(dict(resource))
            service_resources[enum.service].append(safe)

    # Write one JSON file per service domain at the snapshot root.
    for service, resources in service_resources.items():
        domain_path = snapshot_dir / f"{_slug(service)}.json"
        domain_path.write_text(
            json.dumps({"service": service, "resources": resources}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # Write one subfolder per enumerated resource under resources/. Names are
    # allocated collision-free by _resource_dirname (≤100 chars, hashed on a
    # collision or a lossy slug), so a write never targets an existing
    # resource.json. A same-identity duplicate is written under a hashed
    # subfolder and recorded in the manifest's ``duplicates`` list (R5.5).
    taken: Dict[str, str] = {}
    duplicates: List[Dict[str, str]] = []
    for service, resources in service_resources.items():
        seen_identities: set = set()
        for resource in resources:
            identity = _resource_identity(resource, provider)
            is_duplicate = identity in seen_identities
            seen_identities.add(identity)
            dirname = _resource_dirname(service, identity, taken, resource=resource)
            if is_duplicate:
                duplicates.append(
                    {"service": service, "identity": identity, "dirname": dirname}
                )
            sub = resources_dir / dirname
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "resource.json").write_text(
                json.dumps(resource, indent=2, sort_keys=True), encoding="utf-8"
            )

    # Cost/billing: only via the profile's declared cost endpoint. Decided BEFORE
    # failures.json is written (v1.6.1): the "no declared cost endpoint" failure
    # used to be appended after the file was already on disk, so it reached the
    # manifest but never failures.json.
    cost_note: Optional[str] = None
    if collect_cost:
        if cost_endpoint:
            cost_note = f"cost data via declared endpoint: {cost_endpoint}"
        else:
            cost_note = "cost collection requested but no declared cost endpoint; skipped"
            failures.append(
                {"service": "cost", "verb": "cost-endpoint", "reason": "no declared cost endpoint in profile"}
            )

    # Failure reasons are exception text, and provider SDK errors routinely echo
    # the request parameters that caused them (a password in a rejected
    # connection string, a token in a signed URL). failures.json is a snapshot
    # file like any other, so it goes through the same redaction (v1.6.1; it was
    # written verbatim before).
    failures = redact_secrets(failures)

    # Record non-fatal failures in a dedicated domain file, if any.
    if failures:
        (snapshot_dir / "failures.json").write_text(
            json.dumps({"failures": failures}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # Build the manifest with all seven required, non-empty fields.
    resolved_tool_versions = dict(tool_versions or {}) or {"rule-engine": "0.0.0"}
    resolved_region_set = list(region_set) if region_set else [region]

    # file_count: everything written under the snapshot folder.
    file_count = sum(1 for p in snapshot_dir.rglob("*") if p.is_file())
    # Add one for 00-MANIFEST.md, which is written after this count.
    file_count += 1

    manifest: Dict[str, Any] = {
        "provider": provider,
        "boundary_id": boundary_id,
        "region_set": resolved_region_set,
        "caller_identity": caller_identity,
        "tool_versions": resolved_tool_versions,
        "file_count": file_count,
        "delta_instructions": (
            "Re-run collect() with the same provider/boundary_id/region, then run "
            "compute_delta(current_snapshot, previous_snapshot) matching on "
            "(provider, resource_type, identity) to produce the versioned document."
        ),
        # Non-required, informational fields:
        "mutating_verbs_executed": mutating_executed,
        "failures": failures,
        "rejected_verbs": rejected,
    }
    if duplicates:
        manifest["duplicates"] = duplicates
    if cost_note is not None:
        manifest["cost"] = cost_note

    # Secret-safety (§7) covers EVERY snapshot file, and 00-MANIFEST.md is one:
    # a credentialed caller_identity or a cost endpoint carrying an inline token
    # must not land in the manifest verbatim. Run the manifest through the same
    # redaction as resource metadata before rendering.
    manifest = redact_secrets(manifest)

    # Write 00-MANIFEST.md at the snapshot root.
    (snapshot_dir / "00-MANIFEST.md").write_text(
        _render_manifest_md(manifest), encoding="utf-8"
    )

    result = CollectionResult(
        snapshot_folder=str(snapshot_dir),
        manifest=manifest,
        failures=failures,
        mutating_verbs_executed=mutating_executed,
        rejected_verbs=rejected,
    )
    return result.as_dict()


__all__ = [
    "collect",
    "Enumerator",
    "CollectionResult",
    "ProviderError",
    "CollectorInputError",
    "BOUNDARY_RE",
    "redact_secrets",
    "is_mutating_verb",
    "is_read_only_verb",
    "is_secret_verb",
    "has_shell_metacharacters",
    "rejection_reason",
    "snapshot_folder_name",
    "REDACTED",
]

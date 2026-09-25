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
* The count of executed state-mutating verbs per run is guaranteed to be zero
  and is recorded on the manifest (``mutating_verbs_executed: 0``).

On a single-service enumeration failure the collector records ``{service,
reason}`` in a failures list (surfaced in the manifest and in a ``failures``
domain file) and continues with the remaining services (Requirement 3.9).

Cost/billing data is collected only through the profile's declared cost
endpoint, supplied via ``cost_endpoint`` (Requirement 3.10).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from rule_engine.constants import PROVIDERS as _PROVIDERS


# ---------------------------------------------------------------------------
# Provider read-only verb contracts (inventory-standards.md §1, provider-profiles)
# ---------------------------------------------------------------------------

# Valid providers come from rule_engine.constants (single source of truth).

# Per-provider read-only enumeration verb patterns. A verb name must match one
# of these (case-insensitive) to be eligible for execution. ``generic`` uses
# manual entry / Terraform-state import, so any injected verb is allowed (there
# are no live provider calls); state-mutating names are still rejected below.
_READ_ONLY_VERB_PATTERNS: Dict[str, Tuple[re.Pattern[str], ...]] = {
    "aws": (
        re.compile(r"^list($|[_A-Z].*)", re.IGNORECASE),
        re.compile(r"^describe($|[_A-Z].*)", re.IGNORECASE),
        re.compile(r"^get($|[_A-Z].*)", re.IGNORECASE),
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


# ---------------------------------------------------------------------------
# Secret-safety redaction (inventory-standards.md §7; secret-safety)
# ---------------------------------------------------------------------------

# Key-name substrings that mark a value as secret material. Matching is
# case-insensitive against the *key name*, so the corresponding *value* is
# dropped before any snapshot file is written.
_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "securestring",
    "privatekey",
    "private_key",
    "credential",
    "token",
    "apikey",
    "api_key",
    "accesskey",
    "access_key",
    "sessiontoken",
    "session_token",
    "certificate",
    "keymaterial",
    "key_material",
)

# Redaction placeholder written in place of a stripped secret value. Contains no
# secret material, so a snapshot file carrying this string is still secret-free.
REDACTED = "[REDACTED]"


# Content patterns that mark a *value* as secret material even when it sits
# under a benign key name (e.g. ``{"note": "-----BEGIN PRIVATE KEY-----..."}``,
# a SecureString payload, or an inline ``password=...`` assignment). This closes
# the gap where key-name redaction alone leaks a secret carried in the value
# (inventory-standards §7 secret-safety). Matching is case-insensitive and
# deliberately conservative — anchored markers, not broad words — so ordinary
# metadata (a region, an ARN, a description) is not over-redacted.
_SECRET_CONTENT_RE = re.compile(
    r"""
    -----BEGIN[ ][A-Z ]*PRIVATE[ ]KEY-----   # PEM private-key block
    | -----BEGIN[ ]OPENSSH[ ]PRIVATE[ ]KEY-----
    | \bsecurestring\b                        # SSM SecureString payload marker
    | \b(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|
        session[_-]?token|client[_-]?secret)\s*[:=]\s*\S   # inline assignment
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _key_is_secret(key: str) -> bool:
    lowered = key.lower()
    # ``key``/``keys`` alone, or any ``*_key`` name, is key material. A bare
    # trailing "key" in a compound word (e.g. "monkey", "sortkey") is NOT a
    # secret on its own — only the exact/boundary forms count, plus the explicit
    # marker substrings below (``privatekey``/``apikey``/…).
    if lowered in {"key", "keys"} or lowered.endswith("_key"):
        return True
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _value_is_secret(value: str) -> bool:
    """Return True when a string *value* carries embedded secret material.

    Catches a secret hiding under a benign key — the case key-name redaction
    misses — using the conservative anchored :data:`_SECRET_CONTENT_RE`."""
    return bool(_SECRET_CONTENT_RE.search(value))


def _decode_bytes(value: bytes) -> str | None:
    """Best-effort UTF-8 decode of a byte value for the content scan (else None)."""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def redact_secrets(value: Any) -> Any:
    """Recursively strip secret values from resource metadata.

    Two complementary redactions are applied, so a snapshot file never carries
    secret material (inventory-standards §7):

    * **by key name** — any mapping entry whose *key* matches a secret marker
      (``password``/``secret``/``key``/``token``/``securestring`` and friends)
      has its value replaced with :data:`REDACTED`;
    * **by value content** — any *string value* that embeds a secret pattern (a
      PEM/OpenSSH private-key block, a ``SecureString`` payload, or an inline
      ``password=``/``token=`` assignment) is replaced with :data:`REDACTED`
      even when its key name is benign.

    Nested mappings and sequences are walked recursively; non-secret metadata is
    retained unchanged. Never mutates the input, returning a redacted copy.
    """
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _key_is_secret(k):
                result[k] = REDACTED
            else:
                result[k] = redact_secrets(v)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and _value_is_secret(value):
        return REDACTED
    if isinstance(value, bytes):
        decoded = _decode_bytes(value)
        if decoded is not None and _value_is_secret(decoded):
            return REDACTED
    return value


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


def is_read_only_verb(provider: str, verb: str) -> bool:
    """Return True when ``verb`` is a permitted read-only verb for ``provider``.

    A verb is permitted only when it matches one of the provider's read-only
    patterns AND does not look state-mutating.
    """
    if is_mutating_verb(verb):
        return False
    patterns = _READ_ONLY_VERB_PATTERNS.get(provider)
    if patterns is None:
        return False
    return any(p.search(verb) for p in patterns)


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

    lines.append("")
    return "\n".join(lines)


def _slug(text: str) -> str:
    """Filesystem-safe slug for a resource subfolder name."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-")
    return slug or "resource"


def _resource_identity(resource: Mapping[str, Any]) -> str:
    """Pick an identity for a resource: ``id`` when present else ``name``."""
    for key in ("id", "name", "resource_id", "arn"):
        val = resource.get(key)
        if val:
            return str(val)
    return "resource"


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
    snapshot_dir = root / folder_name
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
        # read-only patterns, and never call state-mutating verbs.
        if not is_read_only_verb(provider, enum.verb):
            reason = (
                "state-mutating verb rejected"
                if is_mutating_verb(enum.verb)
                else "verb does not match provider read-only patterns"
            )
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

    # Write one subfolder per enumerated resource under resources/.
    for service, resources in service_resources.items():
        for resource in resources:
            identity = _resource_identity(resource)
            sub = resources_dir / f"{_slug(service)}-{_slug(identity)}"
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "resource.json").write_text(
                json.dumps(resource, indent=2, sort_keys=True), encoding="utf-8"
            )

    # Record non-fatal failures in a dedicated domain file, if any.
    if failures:
        (snapshot_dir / "failures.json").write_text(
            json.dumps({"failures": failures}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # Cost/billing: only via the profile's declared cost endpoint.
    cost_note: Optional[str] = None
    if collect_cost:
        if cost_endpoint:
            cost_note = f"cost data via declared endpoint: {cost_endpoint}"
        else:
            cost_note = "cost collection requested but no declared cost endpoint; skipped"
            failures.append(
                {"service": "cost", "verb": "cost-endpoint", "reason": "no declared cost endpoint in profile"}
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
    "redact_secrets",
    "is_mutating_verb",
    "is_read_only_verb",
    "snapshot_folder_name",
    "REDACTED",
]

"""Delta Engine — compares two Snapshots and classifies each resource.

This module implements the Rule Engine Delta Engine (design section 4e). It
matches Normalized Resources across a current and a (optional) previous Snapshot
on the identity tuple ``(provider, resource_type, boundary, region, identity)``
and classifies each resource as ``added``, ``changed``, ``removed``, or
``unchanged``. An identity that occurs more than once in either Snapshot is
instead reported as ``duplicate`` — an explicit, honest record rather than a
silent last-writer-wins overwrite (Requirement 5 AC8). The resulting
:class:`DeltaRecord` list feeds both the versioned Markdown document and the
diagram Change Markers (Requirement 5 AC8).

Responsibilities (Requirement 5):

- **AC1** — match resources on ``(provider, resource_type, boundary, region,
  identity)`` where ``identity`` is ``id`` when ``id`` is present and non-empty,
  otherwise ``name``.
- **AC2** — present in current, absent in previous → ``added`` (🆕).
- **AC3** — present in both, ``config_digest`` values differ → ``changed`` (🔄).
- **AC4** — present in previous, absent in current → ``removed`` (red styling).
- **AC5** — present in both, ``config_digest`` values equal → ``unchanged``
  (no marker).
- **AC6** — no previous Snapshot → classify every current resource ``added``.
- **AC7** — a missing or malformed Snapshot → raise :class:`SnapshotInputError`
  and produce no classification.
- **AC8** — ``boundary`` and ``region`` are part of the identity, and an
  identity that occurs more than once in a Snapshot is reported ``duplicate``
  (with a ``detail`` naming the snapshot and count) rather than silently
  overwritten. ``marker_for(DUPLICATE)`` is ``""`` (a duplicate is not drawn).

A Snapshot is a ``list`` of Normalized Resources (dicts carrying ``provider``,
``resource_type``, ``boundary``, ``region``, ``id`` / ``name``, and
``config_digest``; see :mod:`rule_engine.normalizer` and
``schemas/inventory.schema.json``).

The batch entry point is :func:`compute_delta`. Helper :func:`marker_for`
returns the Change Marker for a classification so callers can drive both the
versioned document and the diagram Change Markers from one source of truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "CLASSIFICATIONS",
    "ADDED",
    "CHANGED",
    "REMOVED",
    "UNCHANGED",
    "DUPLICATE",
    "MARKER_ADDED",
    "MARKER_CHANGED",
    "MARKER_REMOVED",
    "MARKER_UNCHANGED",
    "MARKER_DUPLICATE",
    "Identity",
    "DeltaRecord",
    "SnapshotInputError",
    "marker_for",
    "identity_of",
    "compute_delta",
]

# --------------------------------------------------------------------------- #
# Classifications and change markers
# --------------------------------------------------------------------------- #

ADDED = "added"
CHANGED = "changed"
REMOVED = "removed"
UNCHANGED = "unchanged"
DUPLICATE = "duplicate"

#: The exhaustive, mutually-exclusive classification set (design section 4e).
#: ``duplicate`` is a fifth, honest classification for an identity that occurs
#: more than once in a Snapshot — it is neither added/changed/removed/unchanged
#: because either answer would be a guess.
CLASSIFICATIONS: tuple[str, ...] = (ADDED, CHANGED, REMOVED, UNCHANGED, DUPLICATE)

# Change markers (Requirement 5 AC2/AC3/AC4/AC5, design section 4e):
#   🆕 added, 🔄 changed, "red" removed/blocked, "" (none) unchanged, "" duplicate.
MARKER_ADDED = "🆕"
MARKER_CHANGED = "🔄"
MARKER_REMOVED = "red"
MARKER_UNCHANGED = ""
#: A duplicate is reported in the document (Troubleshooting) but never drawn on
#: the diagram, so its Change Marker is the empty string.
MARKER_DUPLICATE = ""

_MARKERS: dict[str, str] = {
    ADDED: MARKER_ADDED,
    CHANGED: MARKER_CHANGED,
    REMOVED: MARKER_REMOVED,
    UNCHANGED: MARKER_UNCHANGED,
    DUPLICATE: MARKER_DUPLICATE,
}

# Fields every snapshot entry must expose to be matchable/classifiable. Since
# 1.7 ``boundary`` and ``region`` are part of the identity (Requirement 5 AC8),
# so their absence is a malformed-snapshot error exactly like a missing
# ``provider``.
_IDENTITY_FIELDS: tuple[str, ...] = ("provider", "resource_type", "boundary", "region")


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class SnapshotInputError(ValueError):
    """Raised when a supplied Snapshot is missing or malformed (AC7).

    A Snapshot is malformed when it is not a list, or when any entry is not a
    mapping, is missing ``provider`` / ``resource_type`` / ``boundary`` /
    ``region``, or has neither a non-empty ``id`` nor a non-empty ``name`` to
    form an identity.

    The ``snapshot`` attribute names the affected Snapshot (``"current"`` or
    ``"previous"``) so a caller can identify which input was rejected. When a
    :class:`SnapshotInputError` is raised, no delta classification is produced.
    """

    def __init__(self, snapshot: str, detail: str) -> None:
        self.snapshot = snapshot
        self.detail = detail
        super().__init__(f"snapshot-input error [{snapshot}]: {detail}")


# --------------------------------------------------------------------------- #
# Identity tuple + Delta Record model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Identity:
    """The match key for a Normalized Resource (Requirement 5 AC1, AC8).

    ``identity_key`` is the resource ``id`` when present and non-empty, otherwise
    its ``name``. Two resources match across snapshots exactly when their
    ``(provider, resource_type, boundary, region, identity_key)`` tuples are
    equal. ``boundary`` and ``region`` are part of the identity so that two
    resources sharing a name in different accounts/regions do not collide.
    """

    provider: str
    resource_type: str
    boundary: str
    region: str
    identity_key: str

    def as_tuple(self) -> tuple[str, str, str, str, str]:
        """Return the identity as a plain tuple.

        ``(provider, resource_type, boundary, region, identity_key)``.
        """
        return (
            self.provider,
            self.resource_type,
            self.boundary,
            self.region,
            self.identity_key,
        )


@dataclass(frozen=True)
class DeltaRecord:
    """A single classification result for one matched identity (design 4e).

    Attributes
    ----------
    identity:
        The :class:`Identity` match key.
    classification:
        Exactly one of :data:`CLASSIFICATIONS`
        (``added``/``changed``/``removed``/``unchanged``/``duplicate``).
    change_marker:
        The Change Marker for the classification: 🆕 added, 🔄 changed, ``"red"``
        removed, ``""`` unchanged, ``""`` duplicate. Always consistent with
        ``classification`` (it is derived via :func:`marker_for`).
    prev_config_digest:
        The ``config_digest`` from the previous Snapshot, or ``None`` when the
        resource is absent from the previous Snapshot (added, or no previous
        Snapshot). ``None`` for a ``duplicate`` record.
    curr_config_digest:
        The ``config_digest`` from the current Snapshot, or ``None`` when the
        resource is absent from the current Snapshot (removed). ``None`` for a
        ``duplicate`` record.
    detail:
        A human-readable note. For a ``duplicate`` record it names the snapshot
        and the number of entries, e.g. ``"current: 2 entries"``. Empty for the
        four ordinary classifications.
    """

    identity: Identity
    classification: str
    change_marker: str = field(default="")
    prev_config_digest: str | None = None
    curr_config_digest: str | None = None
    detail: str = field(default="")

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON-shaped mapping used by design section 4e."""
        return {
            "identity": {
                "provider": self.identity.provider,
                "resource_type": self.identity.resource_type,
                "boundary": self.identity.boundary,
                "region": self.identity.region,
                "identity_key": self.identity.identity_key,
            },
            "classification": self.classification,
            "change_marker": self.change_marker,
            "prev_config_digest": self.prev_config_digest,
            "curr_config_digest": self.curr_config_digest,
            "detail": self.detail,
        }


# The identity tuple type, used throughout as the index/dedup key.
_IdentityTuple = tuple[str, str, str, str, str]


# --------------------------------------------------------------------------- #
# Helpers — marker + identity
# --------------------------------------------------------------------------- #


def marker_for(classification: str) -> str:
    """Return the Change Marker for ``classification``.

    Single source of truth for the classification → marker mapping so both the
    versioned Markdown document and the diagram Change Markers stay consistent
    (Requirement 5 AC8). ``marker_for(DUPLICATE)`` is ``""`` — a duplicate is
    reported in the document but never drawn. Raises :class:`ValueError` for an
    unknown classification.
    """
    try:
        return _MARKERS[classification]
    except KeyError:
        raise ValueError(
            f"unknown classification {classification!r}; "
            f"expected one of {', '.join(CLASSIFICATIONS)}"
        ) from None


def identity_of(resource: Any, *, snapshot: str) -> Identity:
    """Extract the :class:`Identity` for a Normalized Resource (Requirement 5 AC1).

    ``identity_key`` is ``id`` when present and non-empty, otherwise ``name``.

    Raises :class:`SnapshotInputError` (naming ``snapshot``) when ``resource`` is
    not a mapping, is missing ``provider`` / ``resource_type`` / ``boundary`` /
    ``region``, or has neither a non-empty ``id`` nor a non-empty ``name``.
    """
    if not isinstance(resource, dict):
        raise SnapshotInputError(
            snapshot,
            f"resource entry must be a mapping, got {type(resource).__name__}",
        )

    for key in _IDENTITY_FIELDS:
        value = resource.get(key)
        if value is None or str(value) == "":
            raise SnapshotInputError(
                snapshot,
                f"resource entry missing mandatory identity field {key!r}",
            )

    raw_id = resource.get("id")
    id_str = "" if raw_id is None else str(raw_id)
    if id_str != "":
        identity_key = id_str
    else:
        raw_name = resource.get("name")
        name_str = "" if raw_name is None else str(raw_name)
        if name_str == "":
            raise SnapshotInputError(
                snapshot,
                "resource entry has neither a non-empty 'id' nor a non-empty 'name'",
            )
        identity_key = name_str

    return Identity(
        provider=str(resource["provider"]),
        resource_type=str(resource["resource_type"]),
        boundary=str(resource["boundary"]),
        region=str(resource["region"]),
        identity_key=identity_key,
    )


def _index_snapshot(
    snapshot: Any, *, name: str
) -> tuple[dict[_IdentityTuple, dict[str, Any]], dict[_IdentityTuple, int]]:
    """Validate and index a Snapshot by identity tuple.

    Returns ``(index, duplicates)`` where ``index`` maps
    ``identity_tuple -> first resource seen`` and ``duplicates`` maps
    ``identity_tuple -> total count`` for every identity that occurs more than
    once. A repeated identity is **not** silently overwritten (the pre-1.7
    last-writer-wins branch, which dropped a resource from the delta with only a
    log warning, is removed): the collision is surfaced as a ``duplicate`` record
    by :func:`compute_delta`.

    Raises :class:`SnapshotInputError` (naming ``name``) when the Snapshot is not
    a list or an entry is malformed (Requirement 5 AC7). No classification is
    produced when this raises.
    """
    if not isinstance(snapshot, list):
        raise SnapshotInputError(
            name, f"snapshot must be a list, got {type(snapshot).__name__}"
        )
    index: dict[_IdentityTuple, dict[str, Any]] = {}
    counts: dict[_IdentityTuple, int] = {}
    for entry in snapshot:
        identity = identity_of(entry, snapshot=name)
        key = identity.as_tuple()
        counts[key] = counts.get(key, 0) + 1
        # Keep the first resource seen for each identity so a duplicate does not
        # overwrite it; the duplicate is reported explicitly, not merged.
        if key not in index:
            index[key] = entry  # type: ignore[assignment]
    duplicates = {key: n for key, n in counts.items() if n > 1}
    return index, duplicates


def _digest_of(resource: dict[str, Any] | None) -> str | None:
    """Return the ``config_digest`` of ``resource``, or ``None`` when absent."""
    if resource is None:
        return None
    value = resource.get("config_digest")
    return None if value is None else str(value)


# --------------------------------------------------------------------------- #
# Delta computation
# --------------------------------------------------------------------------- #


def compute_delta(
    current_snapshot: Any, previous_snapshot: Any = None
) -> list[DeltaRecord]:
    """Compare ``current_snapshot`` against ``previous_snapshot``.

    Returns a list of :class:`DeltaRecord`, one per distinct identity present in
    either Snapshot, each classified exactly one of ``added`` / ``changed`` /
    ``removed`` / ``unchanged`` / ``duplicate`` with the matching Change Marker.

    Matching is on the identity tuple
    ``(provider, resource_type, boundary, region, identity)`` where ``identity``
    is ``id`` when present and non-empty, otherwise ``name`` (Requirement 5 AC1,
    AC8). Classification rules:

    - occurs more than once in either Snapshot → ``duplicate`` / ``""`` (AC8).
      Exactly one ``duplicate`` record is emitted per repeated identity, carrying
      a ``detail`` naming the snapshot and count; the identity is **not** also
      classified added/changed/removed/unchanged, because either answer would be
      a guess.
    - present in current, absent in previous → ``added`` / 🆕 (AC2)
    - present in both, digests differ → ``changed`` / 🔄 (AC3)
    - present in previous, absent in current → ``removed`` / red (AC4)
    - present in both, digests equal → ``unchanged`` / none (AC5)

    When ``previous_snapshot`` is ``None`` every non-duplicate current resource is
    classified ``added`` (Requirement 5 AC6).

    Raises :class:`SnapshotInputError` (and produces no classification) when
    either Snapshot is missing or malformed — including a missing ``boundary`` or
    ``region`` on any entry (Requirement 5 AC7, AC8). ``None`` for
    ``previous_snapshot`` means "no previous Snapshot" and is not an error; an
    explicitly malformed value (e.g. a non-list) is.
    """
    current_index, current_dups = _index_snapshot(current_snapshot, name="current")

    # No previous snapshot: every current resource is added (AC6), except
    # duplicated identities, which are reported as duplicate (AC8).
    if previous_snapshot is None:
        records: list[DeltaRecord] = []
        for key, resource in current_index.items():
            if key in current_dups:
                records.append(_duplicate_record(key, {"current": current_dups[key]}))
                continue
            records.append(
                DeltaRecord(
                    identity=_identity_from_tuple(key),
                    classification=ADDED,
                    change_marker=MARKER_ADDED,
                    prev_config_digest=None,
                    curr_config_digest=_digest_of(resource),
                )
            )
        return records

    previous_index, previous_dups = _index_snapshot(previous_snapshot, name="previous")

    # An identity duplicated in either snapshot is reported once as duplicate and
    # not otherwise classified (AC8).
    duplicate_keys = set(current_dups) | set(previous_dups)

    records = []

    # Current resources: added (absent in previous) or changed/unchanged.
    for key, curr_resource in current_index.items():
        if key in duplicate_keys:
            continue
        curr_digest = _digest_of(curr_resource)
        if key not in previous_index:
            classification = ADDED
            prev_digest = None
        else:
            prev_digest = _digest_of(previous_index[key])
            classification = UNCHANGED if prev_digest == curr_digest else CHANGED
        records.append(
            DeltaRecord(
                identity=_identity_from_tuple(key),
                classification=classification,
                change_marker=marker_for(classification),
                prev_config_digest=prev_digest,
                curr_config_digest=curr_digest,
            )
        )

    # Previous-only resources: removed (absent in current) (AC4).
    for key, prev_resource in previous_index.items():
        if key in duplicate_keys or key in current_index:
            continue
        records.append(
            DeltaRecord(
                identity=_identity_from_tuple(key),
                classification=REMOVED,
                change_marker=MARKER_REMOVED,
                prev_config_digest=_digest_of(prev_resource),
                curr_config_digest=None,
            )
        )

    # Exactly one duplicate record per repeated identity, with a detail naming
    # every snapshot the identity is duplicated in and its count there (AC8).
    for key in duplicate_keys:
        per_snapshot: dict[str, int] = {}
        if key in current_dups:
            per_snapshot["current"] = current_dups[key]
        if key in previous_dups:
            per_snapshot["previous"] = previous_dups[key]
        records.append(_duplicate_record(key, per_snapshot))

    return records


def _duplicate_record(
    key: _IdentityTuple, per_snapshot: dict[str, int]
) -> DeltaRecord:
    """Build the single ``duplicate`` :class:`DeltaRecord` for ``key`` (AC8).

    ``per_snapshot`` maps each snapshot the identity is duplicated in (``current``
    / ``previous``) to its occurrence count there; the ``detail`` renders it as
    ``"<snapshot>: <count> entries"`` joined by ``"; "`` in a stable order.
    """
    detail = "; ".join(
        f"{snap}: {per_snapshot[snap]} entries"
        for snap in ("current", "previous")
        if snap in per_snapshot
    )
    return DeltaRecord(
        identity=_identity_from_tuple(key),
        classification=DUPLICATE,
        change_marker=MARKER_DUPLICATE,
        prev_config_digest=None,
        curr_config_digest=None,
        detail=detail,
    )


def _identity_from_tuple(key: _IdentityTuple) -> Identity:
    """Rebuild an :class:`Identity` from an identity tuple."""
    provider, resource_type, boundary, region, identity_key = key
    return Identity(
        provider=provider,
        resource_type=resource_type,
        boundary=boundary,
        region=region,
        identity_key=identity_key,
    )

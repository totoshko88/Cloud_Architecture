"""Delta Engine — compares two Snapshots and classifies each resource.

This module implements the Rule Engine Delta Engine (design section 4e). It
matches Normalized Resources across a current and a (optional) previous Snapshot
on the identity tuple ``(provider, resource_type, identity)`` and classifies each
resource as ``added``, ``changed``, ``removed``, or ``unchanged``. The resulting
:class:`DeltaRecord` list feeds both the versioned Markdown document and the
diagram Change Markers (Requirement 5 AC8).

Responsibilities (Requirement 5):

- **AC1** — match resources on ``(provider, resource_type, identity)`` where
  ``identity`` is ``id`` when ``id`` is present and non-empty, otherwise ``name``.
- **AC2** — present in current, absent in previous → ``added`` (🆕).
- **AC3** — present in both, ``config_digest`` values differ → ``changed`` (🔄).
- **AC4** — present in previous, absent in current → ``removed`` (red styling).
- **AC5** — present in both, ``config_digest`` values equal → ``unchanged``
  (no marker).
- **AC6** — no previous Snapshot → classify every current resource ``added``.
- **AC7** — a missing or malformed Snapshot → raise :class:`SnapshotInputError`
  and produce no classification.

A Snapshot is a ``list`` of Normalized Resources (dicts carrying ``provider``,
``resource_type``, ``id`` / ``name``, and ``config_digest``; see
:mod:`rule_engine.normalizer` and ``schemas/inventory.schema.json``).

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
    "MARKER_ADDED",
    "MARKER_CHANGED",
    "MARKER_REMOVED",
    "MARKER_UNCHANGED",
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

#: The exhaustive, mutually-exclusive classification set (design section 4e).
CLASSIFICATIONS: tuple[str, ...] = (ADDED, CHANGED, REMOVED, UNCHANGED)

# Change markers (Requirement 5 AC2/AC3/AC4/AC5, design section 4e):
#   🆕 added, 🔄 changed, "red" removed/blocked, "" (none) unchanged.
MARKER_ADDED = "🆕"
MARKER_CHANGED = "🔄"
MARKER_REMOVED = "red"
MARKER_UNCHANGED = ""

_MARKERS: dict[str, str] = {
    ADDED: MARKER_ADDED,
    CHANGED: MARKER_CHANGED,
    REMOVED: MARKER_REMOVED,
    UNCHANGED: MARKER_UNCHANGED,
}

# Fields every snapshot entry must expose to be matchable/classifiable.
_IDENTITY_FIELDS: tuple[str, ...] = ("provider", "resource_type")


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class SnapshotInputError(ValueError):
    """Raised when a supplied Snapshot is missing or malformed (AC7).

    A Snapshot is malformed when it is not a list, or when any entry is not a
    mapping, is missing ``provider`` / ``resource_type``, or has neither a
    non-empty ``id`` nor a non-empty ``name`` to form an identity.

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
    """The match key for a Normalized Resource (Requirement 5 AC1).

    ``identity_key`` is the resource ``id`` when present and non-empty, otherwise
    its ``name``. Two resources match across snapshots exactly when their
    ``(provider, resource_type, identity_key)`` tuples are equal.
    """

    provider: str
    resource_type: str
    identity_key: str

    def as_tuple(self) -> tuple[str, str, str]:
        """Return the identity as a plain ``(provider, resource_type, key)`` tuple."""
        return (self.provider, self.resource_type, self.identity_key)


@dataclass(frozen=True)
class DeltaRecord:
    """A single classification result for one matched identity (design 4e).

    Attributes
    ----------
    identity:
        The :class:`Identity` match key.
    classification:
        Exactly one of :data:`CLASSIFICATIONS`
        (``added``/``changed``/``removed``/``unchanged``).
    change_marker:
        The Change Marker for the classification: 🆕 added, 🔄 changed, ``"red"``
        removed, ``""`` unchanged. Always consistent with ``classification`` (it
        is derived via :func:`marker_for`).
    prev_config_digest:
        The ``config_digest`` from the previous Snapshot, or ``None`` when the
        resource is absent from the previous Snapshot (added, or no previous
        Snapshot).
    curr_config_digest:
        The ``config_digest`` from the current Snapshot, or ``None`` when the
        resource is absent from the current Snapshot (removed).
    """

    identity: Identity
    classification: str
    change_marker: str = field(default="")
    prev_config_digest: str | None = None
    curr_config_digest: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON-shaped mapping used by design section 4e."""
        return {
            "identity": {
                "provider": self.identity.provider,
                "resource_type": self.identity.resource_type,
                "identity_key": self.identity.identity_key,
            },
            "classification": self.classification,
            "change_marker": self.change_marker,
            "prev_config_digest": self.prev_config_digest,
            "curr_config_digest": self.curr_config_digest,
        }


# --------------------------------------------------------------------------- #
# Helpers — marker + identity
# --------------------------------------------------------------------------- #


def marker_for(classification: str) -> str:
    """Return the Change Marker for ``classification``.

    Single source of truth for the classification → marker mapping so both the
    versioned Markdown document and the diagram Change Markers stay consistent
    (Requirement 5 AC8). Raises :class:`ValueError` for an unknown classification.
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
    not a mapping, is missing ``provider`` / ``resource_type``, or has neither a
    non-empty ``id`` nor a non-empty ``name``.
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
        identity_key=identity_key,
    )


def _index_snapshot(
    snapshot: Any, *, name: str
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Validate and index a Snapshot by identity tuple.

    Returns ``{identity_tuple -> resource}``. Raises :class:`SnapshotInputError`
    (naming ``name``) when the Snapshot is not a list or an entry is malformed
    (Requirement 5 AC7). No classification is produced when this raises.
    """
    if not isinstance(snapshot, list):
        raise SnapshotInputError(
            name, f"snapshot must be a list, got {type(snapshot).__name__}"
        )
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in snapshot:
        identity = identity_of(entry, snapshot=name)
        key = identity.as_tuple()
        if key in index:
            # Two resources sharing (provider, resource_type, identity) — e.g.
            # duplicate ids, or two resources both keyed by the same name — would
            # otherwise SILENTLY overwrite one another, dropping a resource from
            # the delta with no trace. Surface the collision so the input can be
            # fixed; last-writer-wins is retained for backward compatibility.
            logger.warning(
                "duplicate identity %s in %s snapshot: a second resource with the "
                "same (provider, resource_type, identity) overwrites the first in "
                "the delta index",
                key, name,
            )
        index[key] = entry  # type: ignore[assignment]
    return index


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
    ``removed`` / ``unchanged`` with the matching Change Marker.

    Matching is on the identity tuple ``(provider, resource_type, identity)``
    where ``identity`` is ``id`` when present and non-empty, otherwise ``name``
    (Requirement 5 AC1). Classification rules:

    - present in current, absent in previous → ``added`` / 🆕 (AC2)
    - present in both, digests differ → ``changed`` / 🔄 (AC3)
    - present in previous, absent in current → ``removed`` / red (AC4)
    - present in both, digests equal → ``unchanged`` / none (AC5)

    When ``previous_snapshot`` is ``None`` every current resource is classified
    ``added`` (Requirement 5 AC6).

    Raises :class:`SnapshotInputError` (and produces no classification) when
    either Snapshot is missing or malformed (Requirement 5 AC7). ``None`` for
    ``previous_snapshot`` means "no previous Snapshot" and is not an error; an
    explicitly malformed value (e.g. a non-list) is.
    """
    current_index = _index_snapshot(current_snapshot, name="current")

    # No previous snapshot: every current resource is added (AC6).
    if previous_snapshot is None:
        return [
            DeltaRecord(
                identity=_identity_from_tuple(key),
                classification=ADDED,
                change_marker=MARKER_ADDED,
                prev_config_digest=None,
                curr_config_digest=_digest_of(resource),
            )
            for key, resource in current_index.items()
        ]

    previous_index = _index_snapshot(previous_snapshot, name="previous")

    records: list[DeltaRecord] = []

    # Current resources: added (absent in previous) or changed/unchanged.
    for key, curr_resource in current_index.items():
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
        if key in current_index:
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

    return records


def _identity_from_tuple(key: tuple[str, str, str]) -> Identity:
    """Rebuild an :class:`Identity` from an identity tuple."""
    provider, resource_type, identity_key = key
    return Identity(
        provider=provider,
        resource_type=resource_type,
        identity_key=identity_key,
    )

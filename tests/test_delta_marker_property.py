"""Property-based tests for the Delta Engine Change Markers (task 7.19).

Feature: multicloud-diagram-inventory, Property 14: Change markers match classification

Property 14 — Change markers match classification
(Validates: Requirements 5.2, 5.3, 5.4):

*For every* :class:`DeltaRecord` returned by :func:`compute_delta`, the record's
``change_marker`` is consistent with its ``classification``:

- ``added``     → ``🆕`` (:data:`MARKER_ADDED`)   (Requirement 5.2)
- ``changed``   → ``🔄`` (:data:`MARKER_CHANGED`) (Requirement 5.3)
- ``removed``   → ``red`` (:data:`MARKER_REMOVED`) (Requirement 5.4)
- ``unchanged`` → ``""`` (:data:`MARKER_UNCHANGED`)

Equivalently, ``record.change_marker == marker_for(record.classification)`` and
the marker equals the exact literal expected for that classification.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.delta import (
    ADDED,
    CHANGED,
    MARKER_ADDED,
    MARKER_CHANGED,
    MARKER_REMOVED,
    MARKER_UNCHANGED,
    REMOVED,
    UNCHANGED,
    compute_delta,
    marker_for,
)

# Exact literal each classification must resolve to (Requirements 5.2-5.4).
_EXPECTED_MARKER: dict[str, str] = {
    ADDED: MARKER_ADDED,
    CHANGED: MARKER_CHANGED,
    REMOVED: MARKER_REMOVED,
    UNCHANGED: MARKER_UNCHANGED,
}


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

_providers = st.sampled_from(["aws", "azure", "gcp", "oci", "generic"])
_resource_types = st.sampled_from(
    [
        "boundary",
        "network_boundary",
        "serverless_fn",
        "object_store",
        "managed_sql",
        "message_queue",
        "secrets_store",
        "managed_k8s",
        "llm_platform",
    ]
)
_identity_keys = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=10
)
_digests = st.sampled_from(["digest-a", "digest-b", "digest-c", "digest-d"])


@st.composite
def _resource(draw: Any) -> dict[str, Any]:
    """A single Normalized Resource carrying identity + config_digest fields."""
    return {
        "provider": draw(_providers),
        "resource_type": draw(_resource_types),
        "id": draw(_identity_keys),
        "config_digest": draw(_digests),
    }


def _dedupe_by_identity(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one resource per ``(provider, resource_type, id)`` identity tuple.

    ``compute_delta`` indexes each Snapshot by identity, so duplicates within a
    single Snapshot collapse. Deduping the generated input keeps the Snapshot a
    faithful list-of-distinct-resources and avoids incidental last-wins noise.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for r in resources:
        key = (r["provider"], r["resource_type"], r["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


_snapshot = st.lists(_resource(), max_size=8).map(_dedupe_by_identity)


# --------------------------------------------------------------------------- #
# Properties
# --------------------------------------------------------------------------- #


@settings(max_examples=200)
@given(current=_snapshot, previous=_snapshot)
def test_change_marker_matches_classification(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> None:
    """Every DeltaRecord's change_marker matches its classification.

    Feature: multicloud-diagram-inventory, Property 14: Change markers match classification
    Validates: Requirements 5.2, 5.3, 5.4
    """
    records = compute_delta(current, previous)

    for record in records:
        # Consistent with the single source of truth (marker_for).
        assert record.change_marker == marker_for(record.classification), (
            f"marker {record.change_marker!r} inconsistent with "
            f"classification {record.classification!r}"
        )
        # And equal to the exact literal expected for that classification.
        assert record.change_marker == _EXPECTED_MARKER[record.classification], (
            f"classification {record.classification!r} expected marker "
            f"{_EXPECTED_MARKER[record.classification]!r}, "
            f"got {record.change_marker!r}"
        )


@settings(max_examples=100)
@given(current=_snapshot)
def test_change_marker_matches_classification_no_previous(
    current: list[dict[str, Any]],
) -> None:
    """With no previous Snapshot every record is added → 🆕 (Requirement 5.2).

    Feature: multicloud-diagram-inventory, Property 14: Change markers match classification
    Validates: Requirements 5.2, 5.3, 5.4
    """
    records = compute_delta(current, None)

    for record in records:
        assert record.classification == ADDED
        assert record.change_marker == marker_for(record.classification)
        assert record.change_marker == MARKER_ADDED

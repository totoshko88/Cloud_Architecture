"""Property-based tests for the Delta Engine classification partition (task 7.18).

Feature: multicloud-diagram-inventory, Property 13: Classification partitions the identity set

Property 13 — Classification partitions the identity set
(Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5):

*For any* pair of a current and a previous Snapshot, ``compute_delta`` produces
exactly one :class:`DeltaRecord` per distinct identity in the union of both
snapshots. Every record's ``classification`` is one of :data:`CLASSIFICATIONS`
(``added`` / ``changed`` / ``removed`` / ``unchanged``). The four classification
sets are pairwise disjoint and their union equals the full identity set — the
classification is exhaustive and mutually exclusive (a partition).

Identity is the tuple ``(provider, resource_type, identity_key)`` where
``identity_key`` is ``id`` when present and non-empty, otherwise ``name``
(Requirement 5.1). Ground-truth classification for each identity:

- present only in current                     -> ``added``     (Requirement 5.2)
- present in both, differing ``config_digest`` -> ``changed``   (Requirement 5.3)
- present only in previous                    -> ``removed``   (Requirement 5.4)
- present in both, equal ``config_digest``     -> ``unchanged`` (Requirement 5.5)
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.delta import CLASSIFICATIONS, compute_delta, identity_of

# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

# A small, closed alphabet keeps identity collisions between the current and
# previous snapshots common enough to exercise the changed/unchanged branches.
_providers = st.sampled_from(["aws", "azure", "gcp", "oci", "generic"])
_resource_types = st.sampled_from(
    ["object_store", "serverless_fn", "managed_sql", "message_queue"]
)
_ids = st.sampled_from(["id-1", "id-2", "id-3"])
_names = st.sampled_from(["name-a", "name-b", "name-c"])
_digests = st.sampled_from(["digest-x", "digest-y", "digest-z"])


@st.composite
def _resources(draw: st.DrawFn) -> dict[str, Any]:
    """A valid Normalized Resource with an ``id`` and/or a ``name``.

    At least one of ``id`` / ``name`` is always non-empty so ``identity_of``
    never raises. ``config_digest`` is always present so the changed/unchanged
    distinction is well defined.
    """
    resource: dict[str, Any] = {
        "provider": draw(_providers),
        "resource_type": draw(_resource_types),
        "config_digest": draw(_digests),
    }
    # Choose which identity fields are present: id-only, name-only, or both.
    which = draw(st.sampled_from(["id", "name", "both"]))
    if which in ("id", "both"):
        resource["id"] = draw(_ids)
    if which in ("name", "both"):
        resource["name"] = draw(_names)
    return resource


def _snapshots() -> st.SearchStrategy[list[dict[str, Any]]]:
    """A snapshot: a list of valid Normalized Resources (possibly empty)."""
    return st.lists(_resources(), max_size=8)


def _index_by_identity(
    snapshot: list[dict[str, Any]], *, name: str
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Index a snapshot by its identity tuple, mirroring compute_delta's dedup.

    A later entry with the same identity overwrites an earlier one, matching the
    engine's own dict-indexing behaviour so the ground truth agrees on digests.
    """
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for resource in snapshot:
        index[identity_of(resource, snapshot=name).as_tuple()] = resource
    return index


# --------------------------------------------------------------------------- #
# Property
# --------------------------------------------------------------------------- #


@settings(max_examples=200)
@given(current=_snapshots(), previous=_snapshots())
def test_classification_partitions_the_identity_set(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> None:
    """compute_delta yields one correctly-classified record per union identity.

    Feature: multicloud-diagram-inventory, Property 13: Classification partitions the identity set
    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
    """
    curr_index = _index_by_identity(current, name="current")
    prev_index = _index_by_identity(previous, name="previous")
    expected_identities = set(curr_index) | set(prev_index)

    records = compute_delta(current, previous)

    record_identities = [r.identity.as_tuple() for r in records]

    # Exactly one record per distinct identity: no duplicates, none missing.
    assert len(record_identities) == len(set(record_identities)), (
        "each identity must appear in exactly one DeltaRecord (no duplicates)"
    )
    assert set(record_identities) == expected_identities, (
        "the set of classified identities must equal the union of both snapshots"
    )

    # Every classification is drawn from the exhaustive set, and each record's
    # ground-truth classification is correct — establishing the four sets are
    # pairwise disjoint (each identity maps to exactly one) and exhaustive.
    for record in records:
        key = record.identity.as_tuple()
        assert record.classification in CLASSIFICATIONS, (
            f"classification {record.classification!r} not in {CLASSIFICATIONS}"
        )

        in_curr = key in curr_index
        in_prev = key in prev_index

        if in_curr and not in_prev:
            expected = "added"
        elif in_prev and not in_curr:
            expected = "removed"
        else:  # in both
            same_digest = (
                curr_index[key].get("config_digest")
                == prev_index[key].get("config_digest")
            )
            expected = "unchanged" if same_digest else "changed"

        assert record.classification == expected, (
            f"identity {key} classified {record.classification!r}, "
            f"expected {expected!r}"
        )

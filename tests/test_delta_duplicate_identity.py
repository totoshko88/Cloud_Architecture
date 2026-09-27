"""Regression test: the Delta Engine reports a duplicate identity explicitly.

Two resources sharing ``(provider, resource_type, boundary, region, identity)``
would otherwise silently overwrite one another in the delta index, dropping a
resource from the delta with no trace. Since 1.7 ``_index_snapshot`` no longer
does last-writer-wins with a log warning: ``compute_delta`` emits exactly one
``duplicate`` :class:`DeltaRecord` per repeated identity, carrying a ``detail``
naming the snapshot and the count, and does not otherwise classify it
(Requirement 5 AC8). See collector/asset-index reviews (P1).
"""

from __future__ import annotations

from rule_engine.delta import (
    ADDED,
    CLASSIFICATIONS,
    DUPLICATE,
    MARKER_DUPLICATE,
    compute_delta,
    marker_for,
)


def _res(rid: str, digest: str) -> dict:
    return {
        "provider": "aws",
        "resource_type": "object_store",
        "boundary": "123456789012",
        "region": "us-east-1",
        "id": rid,
        "name": rid,
        "config_digest": digest,
    }


def test_duplicate_is_in_the_classification_set_with_empty_marker() -> None:
    """``duplicate`` is a first-class classification whose marker is empty."""
    assert DUPLICATE in CLASSIFICATIONS
    assert marker_for(DUPLICATE) == ""
    assert MARKER_DUPLICATE == ""


def test_duplicate_identity_emits_one_duplicate_record() -> None:
    """A repeated identity yields exactly one ``duplicate`` record, not a guess."""
    dup = [_res("bucket-1", "a" * 64), _res("bucket-1", "b" * 64)]
    records = compute_delta(dup, None)

    # Exactly one record for the identity, classified duplicate (no
    # last-writer-wins, no added/changed/removed/unchanged guess).
    assert len(records) == 1
    record = records[0]
    assert record.classification == DUPLICATE
    assert record.change_marker == ""
    # The detail names the snapshot and the count.
    assert record.detail == "current: 2 entries"
    # A duplicate carries no digest — neither answer would be honest.
    assert record.prev_config_digest is None
    assert record.curr_config_digest is None
    # Identity includes boundary and region.
    assert record.identity.boundary == "123456789012"
    assert record.identity.region == "us-east-1"


def test_duplicate_across_both_snapshots_reports_each_snapshot() -> None:
    """A duplicate in both snapshots names both in the detail, once."""
    current = [_res("bucket-1", "a" * 64), _res("bucket-1", "b" * 64)]
    previous = [
        _res("bucket-1", "c" * 64),
        _res("bucket-1", "d" * 64),
        _res("bucket-1", "e" * 64),
    ]
    records = compute_delta(current, previous)

    dups = [r for r in records if r.classification == DUPLICATE]
    assert len(dups) == 1
    assert dups[0].detail == "current: 2 entries; previous: 3 entries"


def test_distinct_identities_are_not_duplicates() -> None:
    """Distinct identities are classified normally, none as duplicate."""
    distinct = [_res("bucket-1", "a" * 64), _res("bucket-2", "b" * 64)]
    records = compute_delta(distinct, None)

    assert len(records) == 2
    assert all(r.classification == ADDED for r in records)
    assert not any(r.classification == DUPLICATE for r in records)

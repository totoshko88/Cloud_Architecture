"""Regression test: the Delta Engine warns on a duplicate identity tuple.

Two resources sharing ``(provider, resource_type, identity)`` would otherwise
silently overwrite one another in the delta index, dropping a resource from the
delta with no trace. ``_index_snapshot`` now emits a WARNING (last-writer-wins
is retained for backward compatibility). See collector/asset-index reviews (P1).
"""

from __future__ import annotations

import logging

from rule_engine.delta import compute_delta


def _res(rid: str, digest: str) -> dict:
    return {
        "provider": "aws",
        "resource_type": "object_store",
        "id": rid,
        "name": rid,
        "config_digest": digest,
    }


def test_duplicate_identity_in_snapshot_warns(caplog) -> None:
    dup = [_res("bucket-1", "a" * 64), _res("bucket-1", "b" * 64)]
    with caplog.at_level(logging.WARNING, logger="rule_engine.delta"):
        records = compute_delta(dup, None)
    # Last-writer-wins keeps one record for the identity (backward compatible).
    assert len(records) == 1
    # And the collision is surfaced, not silent.
    assert any("duplicate identity" in r.message for r in caplog.records)


def test_distinct_identities_do_not_warn(caplog) -> None:
    distinct = [_res("bucket-1", "a" * 64), _res("bucket-2", "b" * 64)]
    with caplog.at_level(logging.WARNING, logger="rule_engine.delta"):
        records = compute_delta(distinct, None)
    assert len(records) == 2
    assert not any("duplicate identity" in r.message for r in caplog.records)

"""Property-based test for the Delta Engine "no previous snapshot" rule (task 7.20).

Feature: multicloud-diagram-inventory, Property 15: No previous snapshot implies all added

Property 15 — No previous snapshot implies all added
(Validates: Requirements 5.6):
When no previous Snapshot is supplied (``previous_snapshot=None``),
:func:`rule_engine.delta.compute_delta` classifies every current resource as
``added`` and marks each with the 🆕 Change Marker. There is exactly one
:class:`~rule_engine.delta.DeltaRecord` per distinct identity in the current
Snapshot.

The generator builds a current Snapshot as a list of valid Normalized Resources
(each carrying ``provider``, ``resource_type``, an ``id`` / ``name`` identity, and
a ``config_digest``). Identity collisions are avoided so that "distinct identity"
counts are well defined. Both call forms are exercised: the explicit
``compute_delta(current, None)`` and the default ``compute_delta(current)``.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.delta import (
    ADDED,
    MARKER_ADDED,
    compute_delta,
    identity_of,
)
from rule_engine.normalizer import NEUTRAL_RESOURCE_TYPES, PROVIDERS

# Non-empty printable text for identity keys (id/name) and provider/type fields.
_nonempty_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=30,
)

# config_digest is treated as an opaque string by the Delta Engine.
_digest_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=0,
    max_size=40,
)


@st.composite
def normalized_resource(draw: st.DrawFn) -> dict:
    """Generate one valid Normalized Resource matchable by the Delta Engine.

    ``identity`` is ``id`` when non-empty, otherwise ``name``. To keep both
    branches exercised, sometimes ``id`` is empty (forcing the ``name`` branch)
    and sometimes populated.
    """
    provider = draw(st.sampled_from(PROVIDERS))
    resource_type = draw(st.sampled_from(NEUTRAL_RESOURCE_TYPES))
    use_id = draw(st.booleans())
    resource = {
        "provider": provider,
        "resource_type": resource_type,
        "id": draw(_nonempty_text) if use_id else "",
        "name": draw(_nonempty_text),
        "config_digest": draw(_digest_text),
    }
    return resource


@st.composite
def current_snapshot(draw: st.DrawFn) -> list[dict]:
    """Generate a current Snapshot with distinct identity tuples.

    Duplicate identities are dropped so that "exactly one record per distinct
    identity" is a well-defined, checkable property (a duplicate identity would
    otherwise collapse to a single record).
    """
    resources = draw(st.lists(normalized_resource(), min_size=0, max_size=12))
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for resource in resources:
        key = identity_of(resource, snapshot="current").as_tuple()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resource)
    return unique


@settings(max_examples=200)
@given(current=current_snapshot())
def test_no_previous_snapshot_classifies_all_added(current: list[dict]) -> None:
    """Every record is ``added``/🆕 with exactly one per distinct identity.

    Feature: multicloud-diagram-inventory, Property 15: No previous snapshot implies all added
    Validates: Requirements 5.6
    """
    expected_identities = {
        identity_of(resource, snapshot="current").as_tuple() for resource in current
    }

    for previous in (None,):  # explicit-None call form
        records = compute_delta(current, previous)

        # Every record is classified added with the 🆕 marker.
        for record in records:
            assert record.classification == ADDED
            assert record.change_marker == MARKER_ADDED

        # Exactly one record per distinct identity in the current snapshot.
        record_identities = [record.identity.as_tuple() for record in records]
        assert len(record_identities) == len(current)
        assert set(record_identities) == expected_identities
        # No duplicate identity records.
        assert len(record_identities) == len(set(record_identities))


@settings(max_examples=100)
@given(current=current_snapshot())
def test_default_previous_argument_matches_explicit_none(current: list[dict]) -> None:
    """``compute_delta(current)`` matches ``compute_delta(current, None)``.

    The default value of ``previous_snapshot`` is ``None``, so the default call
    form must classify every current resource as ``added`` identically.

    Feature: multicloud-diagram-inventory, Property 15: No previous snapshot implies all added
    Validates: Requirements 5.6
    """
    default_records = compute_delta(current)
    explicit_records = compute_delta(current, None)

    def as_dicts(records: list) -> list[dict]:
        return sorted((r.as_dict() for r in records), key=lambda d: str(d["identity"]))

    assert as_dicts(default_records) == as_dicts(explicit_records)

    for record in default_records:
        assert record.classification == ADDED
        assert record.change_marker == MARKER_ADDED

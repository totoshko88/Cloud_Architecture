"""Property-based test for unmapped-type exclusion in the Normalizer (task 7.15).

Feature: multicloud-diagram-inventory, Property 11: Unmapped resources are excluded with an error

Property 11 (design.md) — Unmapped resources are excluded with an error
(**Validates: Requirements 4.5**):

    For any native provider resource with no defined Normalized Resource Type
    mapping, the Normalizer excludes the resource from the normalized output and
    records an unmapped-type error.

This test generates native resources whose ``native_type`` has no mapping for
the chosen provider (a string that :func:`resolve_resource_type` returns
``None`` for), while every other mandatory field (``id``/``name``/``boundary``/
``region``/``tags``) is populated. It asserts:

- :func:`normalize` raises :class:`NormalizationError` whose
  ``record.kind == "unmapped-type"``; and
- :func:`normalize_all` excludes the resource from ``normalized_list`` and
  records an ``unmapped-type`` error in ``errors_list``; and
- for a mix of one mapped + one unmapped resource, the mapped one is emitted and
  the unmapped one is excluded and errored.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.normalizer import (
    PROVIDERS,
    NormalizationError,
    TYPE_MAPPING,
    normalize,
    normalize_all,
    resolve_resource_type,
)

# Non-empty text for the mandatory sourced fields (name/boundary/region/id).
_NON_EMPTY_TEXT = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    min_size=1,
    max_size=24,
).filter(lambda s: s.strip() != "")

# String tags map with 0..3 entries (a supported tags shape).
_TAGS = st.dictionaries(
    keys=st.text(min_size=1, max_size=8),
    values=st.text(max_size=8),
    max_size=3,
)


@st.composite
def _unmapped_native_type(draw: st.DrawFn, provider: str) -> str:
    """Draw a non-empty native_type string that is UNMAPPED for ``provider``.

    Rejects any string that resolves to a neutral resource_type (i.e. any of the
    provider's known native aliases or neutral-type names), so the produced
    native_type is guaranteed to have no defined mapping.
    """
    candidate = draw(
        st.text(
            alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
            min_size=1,
            max_size=32,
        ).filter(lambda s: s.strip() != "")
    )
    # Guard against the (astronomically unlikely) case the generated string
    # happens to normalize to a known alias for this provider.
    if resolve_resource_type(candidate, provider) is not None:
        candidate = candidate + "_zzz_unmapped_qxv"
    return candidate


@st.composite
def _unmapped_resource(draw: st.DrawFn, provider: str) -> dict:
    """Draw a fully-populated native resource whose native_type is unmapped."""
    return {
        "native_type": draw(_unmapped_native_type(provider)),
        "id": draw(_NON_EMPTY_TEXT),
        "name": draw(_NON_EMPTY_TEXT),
        "boundary": draw(_NON_EMPTY_TEXT),
        "region": draw(_NON_EMPTY_TEXT),
        "tags": draw(_TAGS),
    }


def _one_mapped_native_type(provider: str) -> str:
    """Return a native_type string known to map for ``provider``.

    Uses the first alias key from the provider's TYPE_MAPPING so the mapped
    resource is guaranteed to resolve to a neutral resource_type.
    """
    alias = sorted(TYPE_MAPPING[provider].keys())[0]
    assert resolve_resource_type(alias, provider) is not None
    return alias


@settings(max_examples=150)
@given(data=st.data(), provider=st.sampled_from(PROVIDERS))
def test_normalize_raises_unmapped_type_error(
    data: st.DataObject, provider: str
) -> None:
    """normalize() raises NormalizationError(kind='unmapped-type') for unmapped types.

    Feature: multicloud-diagram-inventory, Property 11: Unmapped resources are excluded with an error
    Validates: Requirements 4.5
    """
    native = data.draw(_unmapped_resource(provider))

    # Sanity: the drawn native_type really is unmapped for this provider.
    assert resolve_resource_type(native["native_type"], provider) is None

    with pytest.raises(NormalizationError) as exc_info:
        normalize(native, provider)

    assert exc_info.value.record.kind == "unmapped-type"


@settings(max_examples=150)
@given(data=st.data(), provider=st.sampled_from(PROVIDERS))
def test_normalize_all_excludes_and_errors_unmapped(
    data: st.DataObject, provider: str
) -> None:
    """normalize_all() excludes an unmapped resource and records an unmapped-type error.

    Feature: multicloud-diagram-inventory, Property 11: Unmapped resources are excluded with an error
    Validates: Requirements 4.5
    """
    native = data.draw(_unmapped_resource(provider))

    normalized_list, errors_list = normalize_all([native], provider)

    # Excluded from output.
    assert normalized_list == []
    # Exactly one unmapped-type error recorded.
    assert len(errors_list) == 1
    assert errors_list[0].kind == "unmapped-type"


@settings(max_examples=150)
@given(data=st.data(), provider=st.sampled_from(PROVIDERS))
def test_normalize_all_mixed_mapped_and_unmapped(
    data: st.DataObject, provider: str
) -> None:
    """A mapped resource is emitted; an unmapped one is excluded and errored.

    Feature: multicloud-diagram-inventory, Property 11: Unmapped resources are excluded with an error
    Validates: Requirements 4.5
    """
    mapped = {
        "native_type": _one_mapped_native_type(provider),
        "id": data.draw(_NON_EMPTY_TEXT),
        "name": data.draw(_NON_EMPTY_TEXT),
        "boundary": data.draw(_NON_EMPTY_TEXT),
        "region": data.draw(_NON_EMPTY_TEXT),
        "tags": data.draw(_TAGS),
    }
    unmapped = data.draw(_unmapped_resource(provider))

    normalized_list, errors_list = normalize_all([mapped, unmapped], provider)

    # The mapped resource is emitted (exactly one), the unmapped one excluded.
    assert len(normalized_list) == 1
    assert normalized_list[0]["native_type"] == mapped["native_type"]
    assert normalized_list[0]["provider"] == provider

    # The unmapped resource is recorded as an unmapped-type error.
    unmapped_errors = [e for e in errors_list if e.kind == "unmapped-type"]
    assert len(unmapped_errors) == 1

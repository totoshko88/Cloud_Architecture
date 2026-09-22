"""Property-based test for Icon Resolver container styles (task 7.6).

Feature: multicloud-diagram-inventory, Property 5: Exactly one container style per boundary and per network boundary

Property 5 (design.md): for each Provider Profile, ``resolve_container`` returns
exactly one concrete container group style for the ``boundary`` kind and exactly
one for the ``network_boundary`` kind. Requirement 2 AC6 states the Icon Resolver
returns exactly one concrete container group style for each Provider's Boundary
and exactly one for its Network Boundary.

**Validates: Requirements 2.6**

The test samples over the full product of ``PROVIDERS`` × ``CONTAINER_KINDS`` so
every (provider, kind) combination is exercised. For each pair it asserts that
``resolve_container`` returns a dict carrying exactly one non-empty
``style_string`` and no other keys. It also cross-checks each provider's on-disk
mapping ``containers`` table against the resolver: the table must declare exactly
the two container kinds ``{boundary, network_boundary}`` — one style per kind,
no more and no fewer — so "exactly one style per kind" is guaranteed structurally
as well as behaviorally.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import (
    CONTAINER_KINDS,
    PROVIDERS,
    load_mapping,
    resolve_container,
)

# Full cross product of every provider and every container kind. Sampling from
# this list guarantees each (provider, kind) combination is reachable.
_PROVIDER_KIND_PAIRS: list[tuple[str, str]] = [
    (provider, kind) for provider in PROVIDERS for kind in CONTAINER_KINDS
]

assert _PROVIDER_KIND_PAIRS, "expected a non-empty provider × kind product"


@settings(max_examples=100)
@given(pair=st.sampled_from(_PROVIDER_KIND_PAIRS))
def test_exactly_one_container_style_per_kind(pair: tuple[str, str]) -> None:
    """resolve_container returns exactly one non-empty style per (provider, kind).

    Feature: multicloud-diagram-inventory, Property 5: Exactly one container style per boundary and per network boundary
    Validates: Requirements 2.6
    """
    provider, kind = pair

    result = resolve_container(kind, provider)

    # Exactly one style entry: the returned dict carries precisely the single
    # ``style_string`` key and nothing else.
    assert isinstance(result, dict)
    assert set(result.keys()) == {"style_string"}, (
        f"{provider}/{kind}: expected exactly one key 'style_string', "
        f"got keys {sorted(result.keys())}"
    )

    style_string = result["style_string"]
    assert isinstance(style_string, str) and style_string != "", (
        f"{provider}/{kind}: expected a non-empty style_string, "
        f"got {style_string!r}"
    )


@settings(max_examples=100)
@given(provider=st.sampled_from(PROVIDERS))
def test_containers_table_declares_exactly_the_two_kinds(provider: str) -> None:
    """Each provider's ``containers`` map holds exactly {boundary, network_boundary}.

    One style per kind, no more and no fewer — the structural guarantee behind
    "exactly one container style per boundary and per network boundary".

    Feature: multicloud-diagram-inventory, Property 5: Exactly one container style per boundary and per network boundary
    Validates: Requirements 2.6
    """
    data = load_mapping(provider)
    containers = data.get("containers") or {}

    assert isinstance(containers, dict), f"{provider}: containers is not a mapping"
    assert set(containers.keys()) == set(CONTAINER_KINDS), (
        f"{provider}: containers must declare exactly {set(CONTAINER_KINDS)}, "
        f"got {set(containers.keys())}"
    )

    # And each declared kind resolves to exactly one non-empty style, so the
    # per-kind style is present and singular.
    for kind in CONTAINER_KINDS:
        resolved = resolve_container(kind, provider)
        assert set(resolved.keys()) == {"style_string"}
        assert resolved["style_string"], f"{provider}/{kind}: empty style_string"


if __name__ == "__main__":  # pragma: no cover
    import pytest

    pytest.main([__file__, "-v"])

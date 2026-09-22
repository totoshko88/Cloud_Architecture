"""Property-based tests for the Icon Resolver (task 7.2).

Feature: multicloud-diagram-inventory, Property 1: Resolve is total over the mapped domain

Property 1 — Resolve is total over the mapped domain (Validates: Requirements 2.1):
For any Provider and any Normalized Resource Type that is present in that
provider's icon mapping, ``resolve_icon`` returns a dict carrying a non-empty
draw.io ``style_string`` and a non-empty ``brand_hex`` — it never raises.

The "mapped domain" for a provider is derived from the actual mapping file
contents: the union of the ``resources`` table keys and the two structural
container kinds present under ``containers``. This accounts for the AWS layout,
which keeps ``boundary`` / ``network_boundary`` only under ``containers`` while
the other profiles also list them under ``resources``. ``resolve_icon`` handles
both layouts by falling back from ``resources`` to ``containers`` for the two
structural types, so both are part of the resolvable domain.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import (
    CONTAINER_KINDS,
    PROVIDERS,
    load_mapping,
    resolve_icon,
)


def _mapped_domain() -> list[tuple[str, str]]:
    """Build (provider, resource_type) pairs from the real mapping contents.

    For each provider, the resolvable domain is the union of the ``resources``
    table keys and any of the two structural container kinds declared under
    ``containers`` (the AWS structural-types-in-containers layout).
    """
    pairs: list[tuple[str, str]] = []
    for provider in PROVIDERS:
        data = load_mapping(provider)
        resources = data.get("resources") or {}
        containers = data.get("containers") or {}
        domain = set(resources.keys())
        for kind in CONTAINER_KINDS:
            if kind in containers:
                domain.add(kind)
        for resource_type in sorted(domain):
            pairs.append((provider, resource_type))
    return pairs


# Sampled from the actual mapped domain across all five provider profiles.
_DOMAIN_PAIRS = _mapped_domain()


@settings(max_examples=200)
@given(pair=st.sampled_from(_DOMAIN_PAIRS))
def test_resolve_is_total_over_mapped_domain(pair: tuple[str, str]) -> None:
    """resolve_icon is total over every (provider, mapped-type) pair.

    Feature: multicloud-diagram-inventory, Property 1: Resolve is total over the mapped domain
    Validates: Requirements 2.1
    """
    provider, resource_type = pair

    # Must never raise for a type present in the provider's mapping.
    result = resolve_icon(resource_type, provider)

    assert isinstance(result, dict)

    style_string = result.get("style_string")
    assert isinstance(style_string, str) and style_string != "", (
        f"{provider}/{resource_type}: expected non-empty style_string, "
        f"got {style_string!r}"
    )

    brand_hex = result.get("brand_hex")
    assert isinstance(brand_hex, str) and brand_hex != "", (
        f"{provider}/{resource_type}: expected non-empty brand_hex, "
        f"got {brand_hex!r}"
    )


def test_mapped_domain_is_non_empty() -> None:
    """Sanity guard: the sampled domain covers every provider and is non-empty."""
    assert _DOMAIN_PAIRS, "expected a non-empty mapped domain"
    covered = {provider for provider, _ in _DOMAIN_PAIRS}
    assert covered == set(PROVIDERS), (
        f"expected all providers covered, missing {set(PROVIDERS) - covered}"
    )

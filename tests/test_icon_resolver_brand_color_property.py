"""Property-based tests for the Icon Resolver brand color format (task 7.3).

Feature: multicloud-diagram-inventory, Property 2: Brand color is always #RRGGBB

Property 2 — Brand color is always #RRGGBB (Validates: Requirements 2.2):
For any Provider and any Normalized Resource Type present in that provider's
icon mapping, ``resolve_icon`` returns a ``brand_hex`` that matches the regular
expression ``^#[0-9A-Fa-f]{6}$`` — a single ``#`` followed by exactly six
hexadecimal digits.

The resolvable domain for a provider is derived from the actual mapping file
contents: the union of the ``resources`` table keys and the two structural
container kinds present under ``containers``. This mirrors the domain-building
pattern in ``test_icon_resolver_properties.py`` and accounts for the AWS layout,
which keeps ``boundary`` / ``network_boundary`` only under ``containers`` while
the other profiles also list them under ``resources``.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import (
    CONTAINER_KINDS,
    PROVIDERS,
    load_mapping,
    resolve_icon,
)

# A brand color must be a single ``#`` followed by exactly six hex digits.
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


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
def test_brand_color_is_always_rrggbb(pair: tuple[str, str]) -> None:
    """resolve_icon's brand_hex always matches ^#[0-9A-Fa-f]{6}$.

    Feature: multicloud-diagram-inventory, Property 2: Brand color is always #RRGGBB
    Validates: Requirements 2.2
    """
    provider, resource_type = pair

    result = resolve_icon(resource_type, provider)

    brand_hex = result.get("brand_hex")
    assert isinstance(brand_hex, str) and _HEX_COLOR_RE.match(brand_hex), (
        f"{provider}/{resource_type}: expected brand_hex matching "
        f"^#[0-9A-Fa-f]{{6}}$, got {brand_hex!r}"
    )


def test_mapped_domain_is_non_empty() -> None:
    """Sanity guard: the sampled domain covers every provider and is non-empty."""
    assert _DOMAIN_PAIRS, "expected a non-empty mapped domain"
    covered = {provider for provider, _ in _DOMAIN_PAIRS}
    assert covered == set(PROVIDERS), (
        f"expected all providers covered, missing {set(PROVIDERS) - covered}"
    )

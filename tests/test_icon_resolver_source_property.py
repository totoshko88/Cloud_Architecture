"""Property-based test for the Icon Resolver icon source (task 7.5).

Feature: multicloud-diagram-inventory, Property 4: Non-AWS icon source is exactly one of two values

Property 4 (design.md): For any mapped Normalized Resource Type resolved for
provider ``azure``, ``gcp``, or ``oci``, the returned icon reference source is
exactly one of ``custom`` or ``builtin``. This reflects Requirement 2 AC5: for a
non-AWS cloud provider the Icon Resolver returns a style string and indicates the
icon reference source as exactly one of two values — a custom draw.io shape
library imported from unpacked assets, or a built-in library.

**Validates: Requirements 2.5**

The resolvable domain is built from the actual mapping file contents. For each of
the three non-AWS cloud providers, the domain is the union of the ``resources``
table keys and any of the two structural container kinds (``boundary`` /
``network_boundary``) declared under ``containers`` — mirroring the resolver's
documented lookup order (``resources`` first, then a fallback to ``containers``
for the two structural types).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rule_engine.icon_resolver import (
    CONTAINER_KINDS,
    ICON_SOURCES,
    load_mapping,
    resolve_icon,
)

# The non-AWS cloud providers covered by Requirement 2 AC5 (the vendor-neutral
# ``generic`` profile is out of scope for this property).
NON_AWS_CLOUD_PROVIDERS: tuple[str, ...] = ("azure", "gcp", "oci")

# Exactly the two permitted icon-source values.
ALLOWED_SOURCES: frozenset[str] = frozenset({"custom", "builtin"})


def _mapped_domain() -> list[tuple[str, str]]:
    """Build (provider, resource_type) pairs from the real mapping contents.

    For each non-AWS cloud provider, the resolvable domain is the union of the
    ``resources`` table keys and any of the two structural container kinds
    declared under ``containers``.
    """
    pairs: list[tuple[str, str]] = []
    for provider in NON_AWS_CLOUD_PROVIDERS:
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


# Sampled from the actual mapped domain across azure / gcp / oci.
_DOMAIN_PAIRS = _mapped_domain()


@settings(max_examples=200)
@given(pair=st.sampled_from(_DOMAIN_PAIRS))
def test_non_aws_icon_source_is_one_of_two_values(pair: tuple[str, str]) -> None:
    """resolve_icon returns icon_source in {'custom', 'builtin'} for non-AWS clouds.

    Feature: multicloud-diagram-inventory, Property 4: Non-AWS icon source is exactly one of two values
    Validates: Requirements 2.5
    """
    provider, resource_type = pair

    result = resolve_icon(resource_type, provider)

    icon_source = result.get("icon_source")
    assert icon_source in ALLOWED_SOURCES, (
        f"{provider}/{resource_type}: expected icon_source in "
        f"{sorted(ALLOWED_SOURCES)}, got {icon_source!r}"
    )


def test_domain_covers_non_aws_clouds_and_allowed_sources_match_resolver() -> None:
    """Sanity guard: the sampled domain covers azure/gcp/oci and the allowed set.

    Ensures the domain is non-empty, spans all three non-AWS cloud providers, and
    that the two permitted values line up with the resolver's own ICON_SOURCES.
    """
    assert _DOMAIN_PAIRS, "expected a non-empty mapped domain"
    covered = {provider for provider, _ in _DOMAIN_PAIRS}
    assert covered == set(NON_AWS_CLOUD_PROVIDERS), (
        f"expected azure/gcp/oci covered, missing "
        f"{set(NON_AWS_CLOUD_PROVIDERS) - covered}"
    )
    assert ALLOWED_SOURCES == set(ICON_SOURCES), (
        f"expected allowed sources {sorted(ALLOWED_SOURCES)} to equal resolver "
        f"ICON_SOURCES {sorted(ICON_SOURCES)}"
    )

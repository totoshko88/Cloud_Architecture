"""Property-based test for the Icon Resolver (task 7.8).

Feature: multicloud-diagram-inventory, Property 7: Unresolved types never yield a placeholder

Property 7 — Unresolved types never yield a placeholder (Validates: Requirements 2.8):
For any valid Provider and any Normalized Resource Type that is *absent* from
that provider's mapped domain, ``resolve_icon`` raises ``UnresolvedTypeError``.
It never returns a dict, style string, or placeholder icon, the error names both
the offending resource type and the provider, and the inputs are left unchanged.

The "mapped domain" for a provider is the union of the ``resources`` table keys
and the two structural container kinds present under ``containers`` (the AWS
layout keeps ``boundary`` / ``network_boundary`` only under ``containers``). Since
1.11.0 (WS10, the render->index bridge) ``resolve_icon`` also resolves a type
whose EXACT slug matches an official asset in the per-slug index, so the
genuinely-unresolvable domain additionally excludes every bridge-resolvable slug
(exact-slug only, never a look-alike — Property 11). Generated candidate types
are filtered against both, so each example is a type that NOTHING resolves —
neither the curated mapping nor the exact-slug bridge — and must raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from rule_engine import asset_index
from rule_engine.asset_index import normalize_slug
from rule_engine.icon_resolver import (
    CONTAINER_KINDS,
    PROVIDERS,
    UnresolvedTypeError,
    load_mapping,
    resolve_icon,
)


def _mapped_domain(provider: str) -> set[str]:
    """Return the set of resolvable Normalized Resource Types for ``provider``."""
    data = load_mapping(provider)
    resources = data.get("resources") or {}
    containers = data.get("containers") or {}
    domain = set(resources.keys())
    for kind in CONTAINER_KINDS:
        if kind in containers:
            domain.add(kind)
    return domain


def _bridge_slugs(provider: str) -> set[str]:
    """Return the slugs the 1.11.0 render->index bridge can resolve for ``provider``.

    ``icon_resolver.resolve_icon`` falls back to
    ``asset_index.bridge_resolve_style`` when the curated mapping has no entry:
    an EXACT-slug match against the per-slug asset index (the committed
    full-packs table if present, else the on-disk pack index) resolves a
    standard-but-unmapped service to its official icon instead of raising
    (WS10, Property 11 — exact slug only, never a look-alike).

    So a resource type whose normalized slug is in this set is NOT unresolvable
    and must be excluded from the property, exactly as a curated-mapping type is.
    The set is DERIVED from the same index the engine reads
    (``asset_index._committed_packs`` / ``index_provider`` over
    ``_BRIDGE_PACKS`` / ``_PACK_PREFIX``), so it tracks the bridge automatically
    rather than hardcoding a list.
    """
    pack_keys = asset_index._BRIDGE_PACKS.get(provider)
    if not pack_keys:  # oci is a shape library — no per-service file bridge
        return set()
    committed = asset_index._committed_packs()
    slugs: set[str] = set()
    for pack_key in pack_keys:
        table = committed.get(pack_key)
        if isinstance(table, dict):
            slugs.update(table.keys())
            continue
        # Fallback: build the pack index from disk, exactly as _exact_asset does
        # when the committed index carries no per-slug `packs` table.
        rel = asset_index._PACK_PREFIX.get(pack_key)
        if not rel:
            continue
        root = Path.cwd() / rel
        try:
            index = asset_index.index_provider(pack_key, str(root))
        except (FileNotFoundError, OSError, ValueError):
            continue
        slugs.update(index.keys())
    return slugs


#: Precompute the mapped domain per provider so generated candidates can be
#: filtered against the real mapping contents.
_MAPPED_DOMAIN = {provider: _mapped_domain(provider) for provider in PROVIDERS}

#: Precompute the bridge-resolvable slugs per provider (1.11.0 WS10). A generated
#: type is genuinely unresolvable only when it is absent from BOTH the curated
#: domain and this set.
_BRIDGE_SLUGS = {provider: _bridge_slugs(provider) for provider in PROVIDERS}


@settings(max_examples=200)
@given(
    provider=st.sampled_from(PROVIDERS),
    resource_type=st.text(),
)
def test_unresolved_types_never_yield_a_placeholder(
    provider: str, resource_type: str
) -> None:
    """An unmapped type raises UnresolvedTypeError with no style/placeholder.

    Feature: multicloud-diagram-inventory, Property 7: Unresolved types never yield a placeholder
    Validates: Requirements 2.8
    """
    # Only exercise types that are genuinely unresolvable: absent from the
    # curated mapping domain AND not resolvable by the render->index bridge
    # (whose EXACT-slug match would legitimately return an official icon — WS10,
    # Property 11 — so such a type is mapped, not a placeholder).
    assume(resource_type not in _MAPPED_DOMAIN[provider])
    assume(
        normalize_slug(resource_type, strip_vendor=True)
        not in _BRIDGE_SLUGS[provider]
    )

    original_type = resource_type
    original_provider = provider

    with pytest.raises(UnresolvedTypeError) as excinfo:
        resolve_icon(resource_type, provider)

    err = excinfo.value

    # The error names both the offending type and the provider (Requirement 2.8).
    assert err.resource_type == resource_type
    assert err.provider == provider
    message = str(err)
    assert repr(resource_type) in message
    assert repr(provider) in message

    # No style string / placeholder is ever emitted — the call raised, so there
    # is no return value at all.
    assert not isinstance(err, dict)

    # Inputs are left unchanged.
    assert resource_type == original_type
    assert provider == original_provider


def test_domain_is_non_empty_per_provider() -> None:
    """Sanity guard: every provider has a non-empty mapped domain."""
    for provider in PROVIDERS:
        assert _MAPPED_DOMAIN[provider], f"expected non-empty domain for {provider}"

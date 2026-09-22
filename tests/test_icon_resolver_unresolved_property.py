"""Property-based test for the Icon Resolver (task 7.8).

Feature: multicloud-diagram-inventory, Property 7: Unresolved types never yield a placeholder

Property 7 — Unresolved types never yield a placeholder (Validates: Requirements 2.8):
For any valid Provider and any Normalized Resource Type that is *absent* from
that provider's mapped domain, ``resolve_icon`` raises ``UnresolvedTypeError``.
It never returns a dict, style string, or placeholder icon, the error names both
the offending resource type and the provider, and the inputs are left unchanged.

The "mapped domain" for a provider is the union of the ``resources`` table keys
and the two structural container kinds present under ``containers`` (the AWS
layout keeps ``boundary`` / ``network_boundary`` only under ``containers``).
Generated candidate types are filtered to exclude every member of that domain,
so each example is genuinely unmapped.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

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


#: Precompute the mapped domain per provider so generated candidates can be
#: filtered against the real mapping contents.
_MAPPED_DOMAIN = {provider: _mapped_domain(provider) for provider in PROVIDERS}


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
    # Only exercise types that are genuinely absent from the provider's domain.
    assume(resource_type not in _MAPPED_DOMAIN[provider])

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

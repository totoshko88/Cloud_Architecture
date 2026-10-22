"""WS7 (1.11.0) — access diagram type: icon coverage for principal/policy/resource."""

from __future__ import annotations

import pytest

from rule_engine import icon_resolver as ir
from rule_engine.constants import RESOURCE_TYPES
from rule_engine.layout.base import ROLE_SCOPE

_ACCESS_NODE_ROLES = ("principal", "policy", "resource")
_PROVIDERS = ("aws", "azure", "gcp", "oci")


@pytest.mark.parametrize("provider", _PROVIDERS)
@pytest.mark.parametrize("role", _ACCESS_NODE_ROLES)
def test_access_role_resolves_to_a_style_for_every_provider(role, provider):
    res = ir.resolve_icon(role, provider)
    assert res and res.get("style_string"), f"{role}/{provider} did not resolve"


def test_access_roles_are_global_scoped():
    # IAM is account-wide, so the three node roles are global (not regional/network).
    for r in _ACCESS_NODE_ROLES:
        assert ROLE_SCOPE.get(r) == "global", f"{r} scope={ROLE_SCOPE.get(r)}"


def test_access_roles_are_extended_only():
    # The 16-value core invariant holds — access roles never enter RESOURCE_TYPES.
    for r in _ACCESS_NODE_ROLES:
        assert r not in RESOURCE_TYPES
    assert len(RESOURCE_TYPES) == 16


def test_trust_boundary_is_a_container_kind_not_a_node_role():
    from rule_engine.constants import CONTAINER_KINDS
    assert "trust_boundary" in CONTAINER_KINDS
    # a trust boundary is a scope, not a drawable service node
    assert "trust_boundary" not in RESOURCE_TYPES

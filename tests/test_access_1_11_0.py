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


# --------------------------------------------------------------------------- #
# WS7.3 — access-aggregation lint rule (Req 7 AC3, class-aware severity).
# --------------------------------------------------------------------------- #

from rule_engine.linter import Artifact, lint  # noqa: E402


def _access_art(diagram_class, n_nodes, diagram_type="access"):
    return Artifact(
        kind="diagram", is_drawio=True, source_format="drawio",
        node_names=[f"n{i}" for i in range(n_nodes)],
        diagram_class=diagram_class, diagram_type=diagram_type,
    )


def _agg(a):
    return [f for f in lint(a)["findings"] if f["rule"] == "access-aggregation"]


def test_access_over_cap_flow_is_warning():
    # 15 > node_cap 12 on a flow access diagram -> WARNING.
    assert [f["severity"] for f in _agg(_access_art("flow", 15))] == ["WARNING"]


def test_access_over_cap_landscape_is_error():
    # the same overflow on a landscape access diagram escalates to ERROR.
    assert [f["severity"] for f in _agg(_access_art("landscape", 15))] == ["ERROR"]


def test_access_under_cap_is_clean():
    assert _agg(_access_art("flow", 10)) == []
    assert _agg(_access_art("flow", 12)) == []   # exactly at the cap is fine


def test_non_access_diagram_is_not_evaluated():
    # a network / plain diagram with many nodes never trips access-aggregation.
    assert _agg(_access_art("flow", 20, diagram_type="network")) == []
    assert _agg(_access_art("flow", 20, diagram_type=None)) == []

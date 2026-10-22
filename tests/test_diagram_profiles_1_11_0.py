"""WS6 (1.11.0) — data-defined diagram-type profile tests."""

from __future__ import annotations

from rule_engine.diagram_profiles import TypeProfile, load_type_profile


def test_unknown_and_empty_resolve_to_none():
    assert load_type_profile(None) is None
    assert load_type_profile("") is None
    assert load_type_profile("does-not-exist") is None


def test_network_profile_fields():
    p = load_type_profile("network")
    assert isinstance(p, TypeProfile)
    assert p.name == "network"
    assert p.base_class == "landscape"      # Req 6 AC1
    assert p.axis == "left-right"
    assert p.lint_profile == "network"
    assert "security_group" in p.special_containers
    # the 5 WS6 network roles are declared allowed
    for r in ("transit_gateway", "vpn_gateway", "direct_connect",
              "route_table", "network_firewall"):
        assert r in p.allowed_roles


def test_profile_whitespace_type_is_trimmed():
    assert load_type_profile("  network  ") is not None


def test_type_profile_is_frozen():
    p = load_type_profile("network")
    try:
        p.base_class = "flow"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("TypeProfile must be frozen")


# --------------------------------------------------------------------------- #
# WS6 — the `network` lint_profile is wired into the linter (Req 6 AC1).
#
# The linter recognizes a Network_Diagram through the profile's `lint_profile`
# field, not a hardcoded type list, so the data file is the source of truth and
# the network-scoped rules (ip-range, node-inside-nonmember-boundary) activate
# for the type. Behaviour for non-network diagrams stays byte-inert.
# --------------------------------------------------------------------------- #

from rule_engine.linter import (  # noqa: E402
    Artifact,
    _is_network_diagram,
    _network_lint_profile,
    lint,
)


def _diagram(diagram_type=None, diagram_class="flow", node_names=()):
    return Artifact(
        kind="diagram",
        is_drawio=True,
        source_format="drawio",
        node_names=list(node_names),
        diagram_class=diagram_class,
        diagram_type=diagram_type,
    )


def _ip_range(a):
    return [f for f in lint(a)["findings"] if f["rule"] == "ip-range"]


def test_network_type_recognized_via_lint_profile():
    # A flow-CLASS diagram whose TYPE carries lint_profile=network is a
    # Network_Diagram purely through the profile — not through diagram_class.
    a = _diagram(diagram_type="network", diagram_class="flow")
    assert _network_lint_profile(a) is True
    assert _is_network_diagram(a) is True


def test_non_network_type_is_not_recognized():
    # An application/flow type resolves to no network profile -> byte-inert.
    a = _diagram(diagram_type="context", diagram_class="flow")
    assert _network_lint_profile(a) is False
    assert _is_network_diagram(a) is False


def test_ip_range_activates_for_network_type():
    # The network-scoped rule fires on a genuinely public IP for the network
    # type, and stays silent on a flow/application type with the same text.
    net = _diagram(diagram_type="network", node_names=["edge 8.8.8.8"])
    flow = _diagram(diagram_type="context", node_names=["edge 8.8.8.8"])
    assert [f["severity"] for f in _ip_range(net)] == ["WARNING"]
    assert _ip_range(flow) == []


def test_documentation_ip_not_flagged_for_network_type():
    # RFC5737 TEST-NET-3 is a documentation range — never flagged, even for a
    # network-profile diagram. Proves the profile only scopes the rule, it does
    # not change what the rule considers an offender.
    net = _diagram(diagram_type="network", node_names=["edge 203.0.113.9"])
    assert _ip_range(net) == []


def test_empty_type_is_byte_inert():
    assert _network_lint_profile(_diagram(diagram_type=None)) is False
    assert _network_lint_profile(_diagram(diagram_type="")) is False


# --------------------------------------------------------------------------- #
# WS7 — the `access` diagram-type profile (Req 7 AC1).
# --------------------------------------------------------------------------- #


def test_access_profile_fields():
    p = load_type_profile("access")
    assert isinstance(p, TypeProfile)
    assert p.name == "access"
    assert p.base_class == "flow"           # a readable chain, not a landscape
    assert p.axis == "left-right"           # principal -> policy -> resource
    assert p.node_cap == 12                  # Req 7 AC3 cap
    assert p.aggregation_key == "principal"  # Req 7 AC1 mandatory aggregation key
    assert p.lint_profile == "access"
    assert "trust_boundary" in p.special_containers
    assert set(p.allowed_roles) == {"principal", "policy", "resource", "trust_boundary"}


def test_network_profile_has_no_aggregation_key():
    # aggregation_key is access-only; the network profile leaves it None.
    assert load_type_profile("network").aggregation_key is None

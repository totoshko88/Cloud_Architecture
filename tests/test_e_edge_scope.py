"""1.13.0 E-EDGE: the ``edge-service-in-subnet`` scope-placement case.

A VPC-edge device (internet / NAT / VPN / transit gateway, egress-only IGW) is
``"network"``-scoped — it must live inside the Network Boundary — but it attaches
to the VPC and routes across its boundary, so it belongs at the VPC *edge*,
OUTSIDE every subnet. :func:`rule_engine.layout.base.is_vpc_edge` identifies the
subset, and ``check_scope_placement`` gains a new reason
``edge-service-in-subnet:<node>`` for an edge device drawn inside a
``subnet`` / ``public_subnet`` container.

Additive and default-inert: ``is_vpc_edge`` defaults to "never an edge device",
so the four existing scope-placement cases and every shipped golden are
unaffected (locked by ``test_scope_placement_1_11_0.py``'s corpus-inert test).
"""

from __future__ import annotations

from rule_engine import icon_resolver
from rule_engine.geometry import Box, DiagramGeometry, check_scope_placement
from rule_engine.icon_refs import IconRef
from rule_engine.layout.base import is_vpc_edge
from rule_engine.linter import Artifact, lint


def _aws_containers():
    return {"aws": icon_resolver.load_mapping("aws")["containers"]}


def _cstyle(kind: str) -> str:
    return icon_resolver.resolve_container(kind, "aws")["style_string"]


def _vpc_with_subnet_geo():
    """account ⊃ region ⊃ vpc ⊃ public_subnet, real AWS container styles."""
    g = DiagramGeometry()
    g.containers = {
        "acct": Box("acct", 0, 0, 2000, 2000),
        "region": Box("region", 100, 100, 1600, 1600),
        "vpc": Box("vpc", 200, 200, 1200, 1200),
        "pub": Box("pub", 300, 300, 400, 400),
    }
    g.container_styles = {
        "acct": _cstyle("boundary"),
        "region": _cstyle("region"),
        "vpc": _cstyle("network_boundary"),
        "pub": _cstyle("public_subnet"),
    }
    return g


def _vpc_with_private_subnet_geo():
    """account ⊃ region ⊃ vpc ⊃ (private) subnet, real AWS container styles."""
    g = DiagramGeometry()
    g.containers = {
        "acct": Box("acct", 0, 0, 2000, 2000),
        "region": Box("region", 100, 100, 1600, 1600),
        "vpc": Box("vpc", 200, 200, 1200, 1200),
        "priv": Box("priv", 300, 300, 400, 400),
    }
    g.container_styles = {
        "acct": _cstyle("boundary"),
        "region": _cstyle("region"),
        "vpc": _cstyle("network_boundary"),
        "priv": _cstyle("subnet"),
    }
    return g


# --------------------------------------------------------------------------- #
# The predicate.
# --------------------------------------------------------------------------- #


def test_is_vpc_edge_predicate():
    for r in (
        "internet_gateway",
        "nat_gateway",
        "vpn_gateway",
        "transit_gateway",
        "egress_only_igw",
    ):
        assert is_vpc_edge(r), r
    for r in ("managed_sql", "compute_instance", "object_store", "vpc", "waf"):
        assert not is_vpc_edge(r), r


# --------------------------------------------------------------------------- #
# The three required cases (pure geometry call).
# --------------------------------------------------------------------------- #


def test_nat_inside_public_subnet_is_allowed():
    """(a) a NAT gateway inside a PUBLIC subnet is the canonical AWS pattern ->
    allowed (owner decision, 1.13.0): the rule no longer fires for a
    ``public_subnet`` box."""
    g = _vpc_with_subnet_geo()
    g.nodes["nat"] = Box("nat", 330, 330, 78, 78)  # inside pub subnet
    out = check_scope_placement(
        g,
        lambda n: "network",  # VPC-edge devices stay network-scoped
        lambda n: False,
        ["aws"],
        _aws_containers(),
        is_vpc_edge=lambda n: n == "nat",
    )
    assert out == []


def test_nat_inside_private_subnet_flags():
    """(a2) a NAT gateway inside a PRIVATE subnet is still a placement defect ->
    edge-service-in-subnet (a NAT must sit in a public subnet / at the VPC
    edge, never in a private subnet)."""
    g = _vpc_with_private_subnet_geo()
    g.nodes["nat"] = Box("nat", 330, 330, 78, 78)  # inside private subnet
    out = dict(
        check_scope_placement(
            g,
            lambda n: "network",
            lambda n: False,
            ["aws"],
            _aws_containers(),
            is_vpc_edge=lambda n: n == "nat",
        )
    )
    assert out.get("nat") == "edge-service-in-subnet:nat"


def test_nat_at_vpc_edge_is_clean():
    """(b) a NAT at the VPC edge (in the VPC, not in any subnet) -> clean."""
    g = _vpc_with_subnet_geo()
    # placed inside the VPC but clear of the subnet box (pub is 300..700).
    g.nodes["nat"] = Box("nat", 800, 800, 78, 78)
    out = check_scope_placement(
        g,
        lambda n: "network",
        lambda n: False,
        ["aws"],
        _aws_containers(),
        is_vpc_edge=lambda n: n == "nat",
    )
    assert out == []


def test_igw_at_vpc_edge_is_clean():
    """(c) an IGW at the VPC edge -> clean."""
    g = _vpc_with_subnet_geo()
    g.nodes["igw"] = Box("igw", 900, 900, 78, 78)  # inside the VPC, not subnet
    out = check_scope_placement(
        g,
        lambda n: "network",
        lambda n: False,
        ["aws"],
        _aws_containers(),
        is_vpc_edge=lambda n: n == "igw",
    )
    assert out == []


def test_existing_four_cases_unaffected_for_non_edge_node():
    """A non-edge node inside a subnet is never flagged by the new case; the
    predicate defaulting to False keeps the four existing reasons intact."""
    g = _vpc_with_subnet_geo()
    # a network-scoped compute instance inside the subnet: is_vpc_edge False ->
    # no edge-service-in-subnet, and (role-derived network, not explicit) no
    # other case either.
    g.nodes["ec2"] = Box("ec2", 330, 330, 78, 78)
    out = check_scope_placement(
        g,
        lambda n: "network",
        lambda n: False,
        ["aws"],
        _aws_containers(),
        # default is_vpc_edge (None) -> never an edge device.
    )
    assert out == []


# --------------------------------------------------------------------------- #
# End-to-end through the linter: ERROR on a network diagram, WARNING otherwise.
# --------------------------------------------------------------------------- #


# The committed icon-index NAT-gateway asset whose signature reverse-maps to the
# ``nat_gateway`` role (``res_amazon-vpc_nat-gateway_48``).
_NAT_ICON = (
    "assets/vendor/aws-icons/Resource-Icons_07312026/"
    "Res_Networking-Content-Delivery/Res_Amazon-VPC_NAT-Gateway_48.svg"
)


def _nat_ref(cell_id: str) -> IconRef:
    return IconRef(cell_id, "image", _NAT_ICON)


def test_edge_service_in_subnet_severity():
    g = _vpc_with_private_subnet_geo()
    g.nodes["nat"] = Box("nat", 330, 330, 78, 78)
    g.node_styles["nat"] = f"image;image={_NAT_ICON};"
    base = dict(
        kind="diagram",
        node_names=[],
        geometry=g,
        icon_refs=[_nat_ref("nat")],
        title_cell="aws x — a / b | 2026-10-23 | v1",
    )
    net = lint(Artifact(diagram_type="network", **base))
    sp = [f for f in net["findings"] if f["rule"] == "scope-placement"]
    assert len(sp) == 1 and sp[0]["severity"] == "ERROR", sp
    assert "edge-service-in-subnet:nat" in sp[0]["reason"]

    flow = lint(Artifact(diagram_type="flow", **base))
    sp = [f for f in flow["findings"] if f["rule"] == "scope-placement"]
    assert len(sp) == 1 and sp[0]["severity"] == "WARNING", sp


def test_edge_service_in_public_subnet_is_clean_e2e():
    """A NAT gateway inside a PUBLIC subnet raises no scope-placement finding
    end-to-end (the canonical AWS pattern — owner decision, 1.13.0)."""
    g = _vpc_with_subnet_geo()  # pub = public_subnet
    g.nodes["nat"] = Box("nat", 330, 330, 78, 78)
    g.node_styles["nat"] = f"image;image={_NAT_ICON};"
    base = dict(
        kind="diagram",
        node_names=[],
        geometry=g,
        icon_refs=[_nat_ref("nat")],
        title_cell="aws x — a / b | 2026-10-23 | v1",
    )
    net = lint(Artifact(diagram_type="network", **base))
    sp = [f for f in net["findings"] if f["rule"] == "scope-placement"]
    assert sp == [], sp

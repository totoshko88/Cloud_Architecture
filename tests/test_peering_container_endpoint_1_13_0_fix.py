"""1.13.0 fix (task item 8): a peering that starts or ends on a CONTAINER
materializes a ``vpc_peering`` node too.

Before, ``materialize_peerings`` skipped any peering edge with a container
endpoint, so a VPC-to-peer peering declared on the VPC box stayed a bare line
even with ``peering_as_node=True``. Now a ``vpc`` / ``peer_account`` /
``external_cloud`` container endpoint is accepted: the pcx joins the external
band, the leg touching the container keeps the container id (WS10
boundary-edge routing), and every leg is labelled.
"""
from __future__ import annotations

from dataclasses import replace

from rule_engine.layout import DiagramSpec, layout, materialize_peerings
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec
from rule_engine.linter import Artifact, Edge, _check_edge_label


def _spec(source: str = "vpc-a", target: str = "peer", marker: str = "1") -> DiagramSpec:
    nodes = (
        NodeSpec(id="lambda", role="serverless_fn", lane="workers", region="a",
                 slot=0, scope="network", container="vpc-a"),
        NodeSpec(id="peer", role="compute_instance", lane="on-premises", region="",
                 slot=0, container="peer-ext"),
    )
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ContainerSpec(id="peer-ext", kind="external_cloud", region="", parent=None,
                      label_key="peer"),
    )
    edges = (EdgeSpec(id="p1", source=source, target=target, marker=marker, peering=True),)
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. VPC peering"), title="aws t — 1 / r | 2026-10-19 | v1",
        peering_as_node=True,
    )


def _legs(m):
    return {e.id: e for e in m.edges if e.id.startswith("p1-")}


def test_peering_from_a_vpc_container_materializes_a_pcx():
    m = materialize_peerings(_spec())
    (pcx,) = [n for n in m.nodes if n.role == "vpc_peering"]
    assert pcx.id == "p1-pcx" and pcx.container == "peer-ext"
    legs = _legs(m)
    assert set(legs) == {"p1-a", "p1-b"}
    assert legs["p1-a"].source == "vpc-a" and legs["p1-a"].target == "p1-pcx"
    assert legs["p1-b"].source == "p1-pcx" and legs["p1-b"].target == "peer"
    assert legs["p1-a"].marker == "1" and legs["p1-b"].marker == "peering"
    assert not any(e.peering for e in m.edges)


def test_layout_routes_the_container_leg_from_the_box():
    placed = layout(_spec(), strict=False)
    assert "p1-pcx" in placed.nodes
    by_id = {pe.spec.id: pe for pe in placed.edges}
    assert by_id["p1-a"].spec.source == "vpc-a"
    assert by_id["p1-a"].points  # routed on the container face
    assert "p1-b" in by_id


def test_peering_legs_satisfy_edge_label():
    m = materialize_peerings(_spec(marker=""))
    legs = _legs(m)
    assert legs["p1-a"].marker == "peering"
    art = Artifact(kind="diagram", node_names=["a"], edges=[
        Edge(source=e.source, target=e.target, label=e.marker, id=e.id) for e in legs.values()
    ])
    assert _check_edge_label(art) is False


def test_container_to_container_peering_uses_the_between_lane():
    spec = _spec(source="vpc-a", target="peer-ext")
    # an external box with no node member: drop the peer node
    spec = replace(spec, nodes=spec.nodes[:1])
    m = materialize_peerings(spec)
    (pcx,) = [n for n in m.nodes if n.role == "vpc_peering"]
    assert pcx.container is None and pcx.region == ""
    legs = _legs(m)
    assert legs["p1-a"].source == "vpc-a" and legs["p1-b"].target == "peer-ext"


def test_materialization_is_idempotent():
    m = materialize_peerings(_spec())
    assert materialize_peerings(m) is m


def test_node_to_node_peering_is_unchanged_except_labels():
    m = materialize_peerings(_spec(source="lambda"))
    (pcx,) = [n for n in m.nodes if n.role == "vpc_peering"]
    assert pcx.container == "peer-ext" and pcx.lane == "on-premises"
    legs = _legs(m)
    assert legs["p1-a"].source == "lambda" and legs["p1-b"].target == "peer"
    assert (legs["p1-a"].marker, legs["p1-b"].marker) == ("1", "peering")

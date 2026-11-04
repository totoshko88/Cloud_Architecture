"""1.13.0 phase 3 (item 5): container-endpoint peering rough edges (F8-F10, F18).

Two peerings from ONE VPC container to TWO single-node peer boxes must:

* build without ``SpecError: duplicate slot`` for the pcx nodes (F8, item 5a);
* get DISTINCT exits on the shared source face (F9, item 5b);
* draw leg ``-b`` correctly to the peer box / its anchor member (F10, item 5c);
* count as ONE connected component in ``graph-islands`` (F18, item 5d);
* render a labelled marker when ``peering=True`` carries one (F19/G23, item 5e),
  and expose a pinned-build helper (``peering_legs``).
"""
from __future__ import annotations

from rule_engine.layout import DiagramSpec, layout, materialize_peerings
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec


def _two_peer_spec() -> DiagramSpec:
    nodes = (
        NodeSpec(id="lambda", role="serverless_fn", lane="workers", region="a",
                 slot=0, scope="network", container="vpc-a"),
        NodeSpec(id="peer1", role="compute_instance", lane="on-premises", region="",
                 slot=0, container="peer1-ext"),
        NodeSpec(id="peer2", role="compute_instance", lane="on-premises", region="",
                 slot=0, container="peer2-ext"),
    )
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None,
                      label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct",
                      label_key="vpc"),
        ContainerSpec(id="peer1-ext", kind="external_cloud", region="", parent=None,
                      label_key="peer"),
        ContainerSpec(id="peer2-ext", kind="external_cloud", region="", parent=None,
                      label_key="peer"),
    )
    edges = (
        EdgeSpec(id="p1", source="vpc-a", target="peer1", marker="1", peering=True),
        EdgeSpec(id="p2", source="vpc-a", target="peer2", marker="2", peering=True),
    )
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. peer one", "2. peer two"),
        title="aws t — 1 / r | 2026-10-19 | v1",
        peering_as_node=True,
    )


def test_two_peerings_one_vpc_two_boxes_materialize_without_duplicate_slot():
    m = materialize_peerings(_two_peer_spec())
    pcx = sorted(n.id for n in m.nodes if n.role == "vpc_peering")
    assert pcx == ["p1-pcx", "p2-pcx"]
    # each pcx joins its own peer box
    by_id = {n.id: n for n in m.nodes}
    assert by_id["p1-pcx"].container == "peer1-ext"
    assert by_id["p2-pcx"].container == "peer2-ext"


def test_two_peerings_build_through_layout():
    placed = layout(_two_peer_spec(), strict=False)
    assert "p1-pcx" in placed.nodes and "p2-pcx" in placed.nodes


def test_two_peering_legs_get_distinct_exits():
    placed = layout(_two_peer_spec(), strict=False)
    by_id = {pe.spec.id: pe for pe in placed.edges}
    # both -a legs leave the same VPC container face; their exit contacts differ
    a1 = by_id["p1-a"]
    a2 = by_id["p2-a"]
    assert a1.exit != a2.exit, (a1.exit, a2.exit)


def _islands_drawio() -> str:
    # Account box (outer), a VPC box inside it holding `lambda`, and a peer box
    # to the right holding `peer`. One labelled leg runs from the VPC container
    # face to `peer`. Without the 5d fix the peer is an island.
    return """<mxGraphModel gridSize="10"><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="boundary-acct" value="Account" style="rounded=0;dashed=1;fillColor=none;strokeColor=#CD2264;verticalAlign=top;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="360" height="300" as="geometry"/></mxCell>
<mxCell id="boundary-vpc" value="VPC" style="rounded=0;dashed=1;fillColor=none;strokeColor=#8C4FFF;verticalAlign=top;" vertex="1" parent="boundary-acct"><mxGeometry x="60" y="100" width="200" height="180" as="geometry"/></mxCell>
<mxCell id="lambda" value="Lambda" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;" vertex="1" parent="boundary-vpc"><mxGeometry x="20" y="30" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="boundary-peerbox" value="Peer" style="rounded=0;dashed=1;fillColor=none;strokeColor=#666666;verticalAlign=top;" vertex="1" parent="1"><mxGeometry x="520" y="100" width="180" height="140" as="geometry"/></mxCell>
<mxCell id="peer" value="Peer host" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.ec2;" vertex="1" parent="boundary-peerbox"><mxGeometry x="20" y="20" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="leg" value="peering" style="edgeStyle=orthogonalEdgeStyle;" edge="1" parent="1" source="boundary-vpc" target="peer"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel>"""


def test_leg_b_to_an_external_member_targets_the_node_not_the_box():
    # When the external box HAS a member, the pcx joins the box and leg -b runs
    # pcx → the member node (a node endpoint), never the box border (F10).
    m = materialize_peerings(_two_peer_spec())
    legs = {e.id: e for e in m.edges if e.id.endswith("-b")}
    assert legs["p1-b"].target == "peer1"
    assert legs["p2-b"].target == "peer2"


def test_peering_legs_helper_renders_labelled_legs():
    from rule_engine.diagram_layout import peering_legs
    a, b = peering_legs("boundary-vpc", "pcx1", "peer", edge_id="px", marker="")
    assert (a.id, a.source, a.target, a.marker) == ("px-a", "boundary-vpc", "pcx1", "peering")
    assert (b.id, b.source, b.target, b.marker) == ("px-b", "pcx1", "peer", "peering")
    assert a.dashed and b.dashed and not a.peering and not b.peering


def test_graph_islands_treats_container_leg_as_connecting_members():
    from rule_engine import geometry as geo
    from rule_engine.drawio_model import parse_drawio

    g = geo.build_geometry(parse_drawio(_islands_drawio(), path="t.drawio")[0])
    comps = geo.graph_components(g)
    assert len(comps) == 1, comps
    assert sorted(comps[0]) == ["lambda", "peer"]

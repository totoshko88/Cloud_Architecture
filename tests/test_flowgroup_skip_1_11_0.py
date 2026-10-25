"""WS2 (1.11.0) — ``flowgroup-*`` decorative-box skip in BOTH parsers.

A flow-group box (``flow_group_cells``) is a decorative grey context box drawn
BEHIND its member nodes. It is not a service node, not a Boundary container, and
not Flow/Legend furniture. Both the geometry parser (``geometry.build_geometry``)
and the CLI parser (``cli._parse_drawio_page``) must skip ``flowgroup-*`` cell
ids so that:

  * no ``flowgroup-*`` id appears in ``geo.nodes`` (it is not a node), and
  * an intra-group member edge that geometrically crosses the group box produces
    NO ``edge-routing`` ``straight-through-flowgroup-*`` / ``knee-through-flowgroup-*``
    ERROR.

This fix lived only in the INSTALLED package before 1.11.0, so a reinstall wiped
it; this test pins it into the repo SOURCE and keeps the two parsers in lockstep.
"""

from __future__ import annotations

from rule_engine import geometry as g
from rule_engine.cli import _parse_drawio_page
from rule_engine.drawio_model import parse_drawio


def _wrap(body: str) -> str:
    return (
        '<mxfile><diagram id="d" name="d"><mxGraphModel gridSize="10"><root>'
        '<mxCell id="0" /><mxCell id="1" parent="0" />'
        f"{body}"
        "</root></mxGraphModel></diagram></mxfile>"
    )


# Two member nodes on one row; a decorative group box wrapping both; and an
# edge between them whose straight run passes THROUGH the group box.
_BODY = (
    # decorative flow-group box behind the two members (fillColor=none, grey)
    '<mxCell id="flowgroup-0" value="Workers" '
    'style="rounded=0;dashed=1;strokeColor=#9AA5B1;fillColor=none;html=1" '
    'vertex="1" parent="1">'
    '<mxGeometry x="60" y="60" width="360" height="160" as="geometry"/></mxCell>'
    # two member nodes inside the box
    '<mxCell id="a" value="worker-a" style="rounded=0;html=1" vertex="1" parent="1">'
    '<mxGeometry x="100" y="100" width="80" height="80" as="geometry"/></mxCell>'
    '<mxCell id="b" value="worker-b" style="rounded=0;html=1" vertex="1" parent="1">'
    '<mxGeometry x="300" y="100" width="80" height="80" as="geometry"/></mxCell>'
    # edge a -> b whose straight horizontal run lies inside the group box
    '<mxCell id="e1" value="1" edge="1" parent="1" source="a" target="b" '
    'style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;html=1">'
    '<mxGeometry relative="1" as="geometry"/></mxCell>'
)


def test_flowgroup_box_absent_from_geometry_nodes():
    geo = g.build_geometry(parse_drawio(_wrap(_BODY), path="t.drawio")[0])
    assert "flowgroup-0" not in geo.nodes
    assert {"a", "b"} <= set(geo.nodes)


def test_intra_group_edge_does_not_trip_edge_routing_through_flowgroup():
    geo = g.build_geometry(parse_drawio(_wrap(_BODY), path="t.drawio")[0])
    findings = g.check_edge_routing(geo)
    # no finding may reference the flow-group box as a pierced node
    assert not any("flowgroup-" in reason for _eid, reason in findings), findings


def test_cli_parser_skips_flowgroup_from_node_names():
    pages = parse_drawio(_wrap(_BODY), path="t.drawio")
    art = _parse_drawio_page("t.drawio", pages[0], _wrap(_BODY))
    assert "Workers" not in art.node_names
    assert sorted(art.node_names) == ["worker-a", "worker-b"]

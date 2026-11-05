"""1.13.0 fix (ITEM 9): decorative flow / band groups are obstacles.

A ``flowgroup-*`` / ``bandgroup-*`` box stays out of the node and container
sets, but its caption strip and frame are now judged: an edge along its caption
is ``edge-crosses-container-label`` (offender ``group:<id>``) and a marker on its
frame is ``marker-on-group-border``.
"""
from __future__ import annotations

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import Artifact, lint

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"


def _group_geo():
    g = DiagramGeometry()
    g.group_boxes["flowgroup-0"] = Box("flowgroup-0", 300, 100, 400, 200)
    g.group_labels["flowgroup-0"] = "Ingestion pipeline"
    g.group_styles["flowgroup-0"] = dl._FLOW_GROUP_STYLE
    g.nodes["a"] = Box("a", 40, 160, 78, 78)
    g.nodes["b"] = Box("b", 900, 160, 78, 78)
    return g


def test_edge_along_group_caption_is_flagged():
    g = _group_geo()
    # a -> b runs horizontally at y=110, along the group's 22px caption strip.
    g.edges.append(EdgeGeom(id="e1", source="a", target="b", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5),
                            points=[(200, 199), (200, 110), (800, 110), (800, 199)]))
    assert ("e1", "group:flowgroup-0") in geo.check_edge_crosses_container_label(g)


def test_member_edge_clean_approach_is_exempt():
    # 1.13.0 phase 3 (item 6, F1): the exemption is scoped to the member's own
    # final APPROACH leg. A member edge that drops straight into the group from
    # above (its only caption-band segment is the vertical entry drop) is still
    # exempt — the entry leg must cross the band to reach its member.
    g = _group_geo()
    g.nodes["m"] = Box("m", 400, 160, 78, 78)   # a member inside the group
    g.edges.append(EdgeGeom(id="e1", source="a", target="m", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.5, 0.0),
                            points=[(200, 199), (200, 90), (439, 90)]))
    assert geo.check_edge_crosses_container_label(g) == []


def test_marker_on_group_frame():
    g = DiagramGeometry()
    g.nodes["a"] = Box("a", 40, 160, 78, 78)
    g.nodes["b"] = Box("b", 400, 160, 78, 78)
    g.edges.append(EdgeGeom(id="e2", source="a", target="b", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5), label="1"))
    (mx, my), = geo.marker_anchors(g).values()
    # A group whose left frame sits 8px right of the marker: flagged.
    g.group_boxes["flowgroup-0"] = Box("flowgroup-0", mx + 8, my - 50, 200, 200)
    g.group_labels["flowgroup-0"] = "G"
    hits = geo.check_marker_on_group_border(g)
    assert hits == [("e2", "flowgroup-0.left")]
    art = Artifact(kind="diagram", node_names=["a", "b"], geometry=g)
    rules = {f["rule"]: f for f in lint(art)["findings"]}
    assert rules["marker-on-group-border"]["severity"] == "WARNING"
    # 17px away: clear of MARKER_BORDER_CLEARANCE (16px).
    g.group_boxes["flowgroup-0"] = Box("flowgroup-0", mx + 17, my - 50, 200, 200)
    assert geo.check_marker_on_group_border(g) == []


def _built():
    nodes = [dl.Node("a", "a", 120, 120, render=_ICON)]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[], nodes=nodes,
        edges=[], flow_lines=["Flow"], legend_x=900, page_w=1200, page_h=600,
        flow_groups=(("A very long functional group caption", ("a",)),),
    )


def test_group_is_never_a_node_or_container():
    g = geo.build_geometry(parse_drawio(_built(), path="t.drawio")[0])
    assert "flowgroup-0" not in g.nodes and "flowgroup-0" not in g.containers
    assert "flowgroup-0" in g.group_boxes
    assert g.group_labels["flowgroup-0"] == "A very long functional group caption"
    assert geo.check_geometric_containment(g) == []


def test_flow_group_cells_widen_to_caption():
    label = "A very long functional group caption"
    nodes = [dl.Node("a", "a", 120, 120, render=_ICON)]
    cells = dl.flow_group_cells(((label, ("a",)),), nodes)
    import re
    w = int(re.search(r'width="(\d+)"', cells).group(1))
    assert w >= len(label) * 7.0 + dl._FLOW_GROUP_SPACING_LEFT + 2 * dl._FLOW_GROUP_PAD
    # A short caption keeps the member bbox width.
    cells = dl.flow_group_cells((("G", ("a",)),), nodes)
    assert int(re.search(r'width="(\d+)"', cells).group(1)) == dl.ICON_SIZE + 2 * dl._FLOW_GROUP_PAD

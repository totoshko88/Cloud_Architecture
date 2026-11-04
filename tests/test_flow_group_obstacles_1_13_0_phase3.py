"""1.13.0 phase 3 (item 6, F1): a MEMBER edge that runs along a flow-group
caption is now flagged.

Phase 1 exempted any edge with an endpoint inside the group, so 06 e8 (lti ->
Atlas) and 07 e7 (through the "Async" caption) linted clean while visibly
striking the group caption. The exemption is now scoped to the member's own
final approach leg; a long run along the caption band is a finding.
"""
from __future__ import annotations

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine import diagram_layout as dl


def _group_geo():
    g = DiagramGeometry()
    g.group_boxes["flowgroup-0"] = Box("flowgroup-0", 300, 100, 400, 200)
    g.group_labels["flowgroup-0"] = "Async messaging"
    g.group_styles["flowgroup-0"] = dl._FLOW_GROUP_STYLE
    g.nodes["a"] = Box("a", 40, 160, 78, 78)     # outside, left
    g.nodes["m"] = Box("m", 600, 160, 78, 78)    # member inside the group
    return g


def test_member_edge_running_along_caption_is_flagged():
    g = _group_geo()
    # a -> m runs along y=110 (inside the 22px caption band 100..122) for ~400px
    # before dropping into m: the member exemption must NOT hide this.
    g.edges.append(EdgeGeom(id="e8", source="a", target="m", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5),
                            points=[(200, 199), (200, 110), (580, 110), (580, 199)]))
    hits = geo.check_edge_crosses_container_label(g)
    assert ("e8", "group:flowgroup-0") in hits


def test_member_edge_dropping_in_from_above_is_exempt():
    g = _group_geo()
    # the only caption-band segment is the vertical entry drop into m (top entry)
    g.edges.append(EdgeGeom(id="e1", source="a", target="m", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.5, 0.0),
                            points=[(200, 199), (200, 90), (639, 90)]))
    assert geo.check_edge_crosses_container_label(g) == []


def test_non_member_edge_along_caption_still_flagged():
    g = _group_geo()
    g.nodes["b"] = Box("b", 900, 160, 78, 78)    # also outside
    g.edges.append(EdgeGeom(id="e6", source="a", target="b", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5),
                            points=[(200, 199), (200, 110), (800, 110), (800, 199)]))
    assert ("e6", "group:flowgroup-0") in geo.check_edge_crosses_container_label(g)

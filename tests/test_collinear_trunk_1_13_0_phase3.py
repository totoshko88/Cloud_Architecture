"""1.13.0 phase 3 (item 11, F16): a fan-out / fan-in trunk whose two legs sit
on ONE face is exempt from ``collinear-edges`` even when the legs never meet.

``exit-thirds`` / ``entry-thirds`` force two same-source (same-target) legs onto
distinct bands of a face, so they run parallel but never share a contact point.
Pre-1.13.0 the trunk exemption required a shared meeting point, so the 08
trunks (IGW fan-out, NAT fan-in, RDS fan-in, CloudFront origins) were flagged.
"""
from __future__ import annotations

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom


def _geo():
    g = DiagramGeometry()
    g.nodes["src"] = Box("src", 100, 100, 78, 78)
    g.nodes["t1"] = Box("t1", 100, 400, 78, 78)
    g.nodes["t2"] = Box("t2", 300, 400, 78, 78)
    return g


def test_same_source_face_trunk_without_meeting_point_is_exempt():
    g = _geo()
    # two legs leaving src's bottom face on DISTINCT bands (0.25 / 0.75), each a
    # long parallel vertical run two grid steps apart — they never meet.
    g.edges.append(EdgeGeom(id="a", source="src", target="t1", orthogonal=True,
                            exit=(0.25, 1.0), entry=(0.5, 0.0),
                            points=[(120, 180), (120, 390)]))
    g.edges.append(EdgeGeom(id="b", source="src", target="t2", orthogonal=True,
                            exit=(0.75, 1.0), entry=(0.5, 0.0),
                            points=[(140, 180), (140, 390)]))
    assert geo.collinear_edge_pairs(g) == set()


def test_different_source_parallel_legs_are_still_flagged():
    g = _geo()
    g.nodes["src2"] = Box("src2", 300, 100, 78, 78)
    g.edges.append(EdgeGeom(id="a", source="src", target="t1", orthogonal=True,
                            exit=(0.5, 1.0), entry=(0.5, 0.0),
                            points=[(130, 180), (130, 390)]))
    g.edges.append(EdgeGeom(id="b", source="src2", target="t2", orthogonal=True,
                            exit=(0.5, 1.0), entry=(0.5, 0.0),
                            points=[(140, 180), (140, 390)]))
    assert ("a", "b") in geo.collinear_edge_pairs(g)


def test_same_face_trunk_helper():
    g = _geo()
    ea = EdgeGeom(id="a", source="src", target="t1", orthogonal=True,
                  exit=(0.25, 1.0), entry=(0.5, 0.0))
    eb = EdgeGeom(id="b", source="src", target="t2", orthogonal=True,
                  exit=(0.75, 1.0), entry=(0.5, 0.0))
    assert geo._same_face_trunk(ea, eb, {"src"}) is True
    # different faces: not a same-face trunk
    ec = EdgeGeom(id="c", source="src", target="t2", orthogonal=True,
                  exit=(1.0, 0.5), entry=(0.5, 0.0))
    assert geo._same_face_trunk(ea, ec, {"src"}) is False

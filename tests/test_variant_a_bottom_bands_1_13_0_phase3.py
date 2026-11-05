"""1.13.0 phase 3 (item 10): post-solver Variant A fix-up for a LONE straight
bottom drop that strikes its own caption.

Phase 1 only tried a corner-contact exit on an OVERLOADED source (its right
face already full) and only when the global ``_CORNER_EXIT_FALLBACK`` flag was
on (off by default). A lone straight bottom drop from a NON-overloaded source
whose side corridor cannot clear the caption (03 e10, 09 e2) was left masked.
The fix-up now offers the corner exit for that case too, kept only under the
existing no-worse guard, so a golden is never worsened.
"""
from __future__ import annotations

from rule_engine import caption_routing as cr
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom


def _lone_drop_geo():
    g = DiagramGeometry()
    # source with a wide caption; a single bottom-centre exit straight down.
    g.nodes["s"] = Box("s", 200, 100, 78, 78)
    g.node_labels["s"] = "A Very Wide Source Caption Name"
    g.nodes["t"] = Box("t", 200, 400, 78, 78)
    g.node_labels["t"] = "t"
    g.edges.append(EdgeGeom(id="e1", source="s", target="t", orthogonal=True,
                            exit=(0.5, 1.0), entry=(0.5, 0.0),
                            points=[(239, 400)]))
    return g


def test_lone_bottom_drop_is_recognised():
    g = _lone_drop_geo()
    e = g.edges[0]
    assert cr._lone_bottom_drop(g, e) is True


def test_a_turning_bottom_edge_is_not_a_lone_drop():
    g = _lone_drop_geo()
    e = g.edges[0]
    # a left turn in the route: not a straight single-column drop.
    turned = EdgeGeom(id="e1", source="s", target="t", orthogonal=True,
                      exit=(0.5, 1.0), entry=(0.5, 0.0),
                      points=[(239, 300), (100, 300), (100, 400)])
    g.edges[0] = turned
    assert cr._lone_bottom_drop(g, turned) is False


def test_a_second_bottom_exit_disqualifies_the_lone_case():
    g = _lone_drop_geo()
    g.nodes["u"] = Box("u", 200, 400, 78, 78)
    g.edges.append(EdgeGeom(id="e2", source="s", target="u", orthogonal=True,
                            exit=(0.25, 1.0), entry=(0.5, 0.0), points=[(220, 400)]))
    assert cr._lone_bottom_drop(g, g.edges[0]) is False

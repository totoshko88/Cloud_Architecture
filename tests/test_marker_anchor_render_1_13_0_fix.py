"""1.13.0 fix (task item 2): the marker position lint judges is the position
draw.io renders.

draw.io draws an edge label whose ``mxGeometry`` carries no ``x`` at the route
midpoint, and a label at signed ``x`` at arc fraction ``(x + 1) / 2``. Before
this fix lint anchored an UNPINNED marker on a long route near its source while
draw.io drew it at the midpoint. Now:

* ``geometry.marker_anchor`` resolves an unpinned marker to the midpoint;
* ``build_diagram`` writes the near-source position into the file
  (``orthogonalise.pin_long_marker_anchors_text``), so render and lint agree.
"""
from __future__ import annotations

import re

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.drawio_model import parse_drawio
from rule_engine.orthogonalise import pin_long_marker_anchors_text

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _long_build() -> str:
    # a right face at x=178, b left face at x=898: a straight 720px route.
    nodes = [
        dl.Node(id="a", label="a", x=100, y=200, render=_ICON),
        dl.Node(id="b", label="b", x=898 - 0, y=200, render=_ICON),
    ]
    edges = [dl.Edge(id="e1", source="a", target="b", marker="1")]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=["Flow", "1. step"],
        legend_x=1100, page_w=1500, page_h=500,
    )


def _edge_cell(text: str, eid: str) -> str:
    m = re.search(r'<mxCell id="' + eid + r'"[^>]*edge="1".*?</mxCell>', text, re.S)
    assert m, eid
    return m.group(0)


def _arc_point(poly, x: float):
    """draw.io semantics: a label at signed ``x`` sits at arc fraction (x+1)/2."""
    seg = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(poly, poly[1:])]
    target = (x + 1.0) / 2.0 * sum(seg)
    run = 0.0
    for (a, b), ln in zip(zip(poly, poly[1:]), seg):
        if run + ln >= target:
            f = (target - run) / ln
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        run += ln
    return poly[-1]


def test_long_marker_is_pinned_in_the_file_and_lint_reads_that_position():
    text = _long_build()
    cell = _edge_cell(text, "e1")
    m = re.search(r'<mxGeometry\b[^>]*\bx="([-0-9.]+)"', cell)
    assert m, "the long marker's position must be written into its mxGeometry"
    x = float(m.group(1))
    g = _geo(text)
    (e,) = [e for e in g.edges if e.id == "e1"]
    poly = geo.edge_polyline(g, e)
    assert sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(poly, poly[1:])) > geo.LONG_EDGE_MARKER_LEN
    ax, ay = geo.marker_anchors(g)["e1"]
    rx, ry = _arc_point(poly, x)
    assert abs(ax - rx) < 1e-6 and abs(ay - ry) < 1e-6
    # near the source, not at the midpoint
    assert ax < (poly[0][0] + poly[-1][0]) / 2.0


def test_hand_written_file_without_x_anchors_at_the_midpoint():
    text = _long_build()
    stripped = re.sub(r'(<mxGeometry)\s+x="[-0-9.]+"', r"\1", text)
    g = _geo(stripped)
    (e,) = [e for e in g.edges if e.id == "e1"]
    assert e.label_pos is None
    poly = geo.edge_polyline(g, e)
    assert geo.marker_anchors(g)["e1"] == _arc_point(poly, 0.0)


def test_pin_is_idempotent_and_short_routes_stay_unpinned():
    text = _long_build()
    assert pin_long_marker_anchors_text(text) == text
    nodes = [
        dl.Node(id="a", label="a", x=100, y=200, render=_ICON),
        dl.Node(id="b", label="b", x=320, y=200, render=_ICON),
    ]
    short = dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=[dl.Edge(id="e1", source="a", target="b", marker="1")],
        flow_lines=["Flow", "1. step"], legend_x=600, page_w=900, page_h=500,
    )
    assert 'x="' not in _edge_cell(short, "e1").split("<mxGeometry", 1)[1].split(">", 1)[0]


def test_arc_fraction_semantics():
    poly = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
    assert _arc_point(poly, -1.0) == (0.0, 0.0)
    assert _arc_point(poly, 0.0) == (100.0, 0.0)
    assert _arc_point(poly, 0.5) == (100.0, 50.0)
    for x in (-0.6, 0.0, 0.3):
        assert geo.marker_anchor(poly, x) == _arc_point(poly, x)

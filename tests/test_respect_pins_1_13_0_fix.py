"""1.13.0 fix (task item 15): ``build_diagram(respect_pins=...)``.

An input edge with explicit ``points`` is *pinned*. Before this fix the
finishing passes (caption-safe, crossing repair, collinear shift) re-routed
pinned edges silently. Now the default still may, but logs and reports every
pinned edge it moved; ``respect_pins=True`` freezes them (they stay obstacles).
"""
from __future__ import annotations

import logging
import re

from rule_engine import diagram_layout as dl

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"
#: A bottom drop out of ``a`` that strikes its own caption ("alpha service").
_PINS = ((140.0, 290.0), (360.0, 290.0))


def _build(points=_PINS, **kw) -> str:
    nodes = [
        dl.Node(id="a", label="alpha service", x=100, y=100, render=_ICON),
        dl.Node(id="b", label="b", x=320, y=400, render=_ICON),
    ]
    edges = [dl.Edge(id="e1", source="a", target="b", marker="1",
                     exit=(0.5, 1.0), entry=(0.5, 0.0), points=points)]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=["Flow", "1. a to b"],
        legend_x=700, page_w=1100, page_h=700, **kw,
    )


def _points(text: str, eid: str = "e1"):
    cell = re.search(r'<mxCell id="' + eid + r'".*?</mxCell>', text, re.S).group(0)
    return tuple((float(x), float(y)) for x, y in
                 re.findall(r'<mxPoint x="([-0-9.]+)" y="([-0-9.]+)"', cell))


def test_default_reroutes_the_pinned_edge_and_reports_it(caplog):
    report: list = []
    with caplog.at_level(logging.WARNING, logger="rule_engine.diagram_layout"):
        text = _build(respect_pins=False, reroute_report=report)
    assert report == ["e1"]
    assert any("rerouted edges with explicit points" in r.getMessage()
               and "e1" in r.getMessage() for r in caplog.records)
    assert _points(text) != _PINS


def test_respect_pins_keeps_the_points_byte_identical(caplog):
    report: list = []
    with caplog.at_level(logging.WARNING, logger="rule_engine.diagram_layout"):
        text = _build(respect_pins=True, reroute_report=report)
    assert _points(text) == _PINS
    assert report == []
    assert not caplog.records


def test_pinned_ids_empty_marks_engine_routed_edges(caplog):
    """Integration (1.13.0): layout()-routed edges carry points too; a builder
    passing ``pinned_ids=()`` gets the same document and no false warning."""
    report: list = []
    with caplog.at_level(logging.WARNING, logger="rule_engine.diagram_layout"):
        text = _build(pinned_ids=(), reroute_report=report)
    assert report == []
    assert not caplog.records
    assert text == _build(respect_pins=False)


def test_new_keywords_default_to_the_old_output():
    assert _build() == _build(respect_pins=False, membership=None)
    # an unpinned diagram is unaffected by respect_pins
    assert _build(points=()) == _build(points=(), respect_pins=True)

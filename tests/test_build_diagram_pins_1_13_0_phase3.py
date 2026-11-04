"""1.13.0 phase 3, P0 item 3: ``build_diagram`` pin handling.

(a) under ``respect_pins=True`` a legal pin is kept verbatim (a short approach
lane is not stretched); the default stays ``False``;
(b) the reroute message names only real hand pins, never engine seeds;
(c) the per-edge no-worse guard puts a better pin back.
"""
from __future__ import annotations

import logging
import re

from rule_engine import diagram_layout as dl

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t \u2014 123456789012 / us-east-1 | 2026-10-19 | v1"


def _doc(points, exit_=(1.0, 0.5), entry=(0.0, 0.5), b=(500, 100), **kw):
    nodes = [
        dl.Node(id="a", label="a", x=100, y=100, render=_ICON),
        dl.Node(id="b", label="b", x=b[0], y=b[1], render=_ICON),
    ]
    edges = [dl.Edge(id="e1", source="a", target="b", marker="1",
                     exit=exit_, entry=entry, points=points)]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=["Flow", "1. a to b"],
        legend_x=800, page_w=1200, page_h=700, **kw,
    )


def _points(text, eid="e1"):
    cell = re.search(r'<mxCell id="' + eid + r'".*?</mxCell>', text, re.S).group(0)
    return tuple((float(x), float(y)) for x, y in
                 re.findall(r'<mxPoint x="([-0-9.]+)" y="([-0-9.]+)"', cell))


# a (100,100) right contact (178,140); b (500,300) left contact (500,340).
# The pinned entry lane is x=480: 20px before the entry face.
_SHORT = ((200.0, 140.0), (200.0, 340.0))
_PIN20 = ((190.0, 140.0), (190.0, 340.0), )


def test_legal_pin_with_short_approach_survives():
    pts = ((200.0, 140.0), (480.0, 140.0), (480.0, 340.0))
    text = _doc(pts, b=(500, 300), respect_pins=True)
    # the redundant first waypoint collapses; the 20px entry lane is kept
    assert _points(text) == pts[1:]
    assert _points(_doc(pts, b=(500, 300), respect_pins=False)) != pts[1:]  # stretched


def test_default_still_reroutes_and_does_not_call_unnamed_points_hand_pins(caplog):
    """The default stays respect_pins=False (an Edge cannot tell a hand pin
    from a layout() seed); the warning for unnamed points says so."""
    pts = ((140.0, 290.0), (360.0, 290.0))
    with caplog.at_level(logging.WARNING, logger="rule_engine.diagram_layout"):
        text = _doc(pts, exit_=(0.5, 1.0), entry=(0.5, 0.0), b=(320, 400))
    assert _points(text) != pts
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs and all("hand-pinned edges" not in m for m in msgs)
    assert any("layout() seeds" in m for m in msgs)


def test_named_pins_get_the_hand_pinned_message(caplog):
    pts = ((140.0, 290.0), (360.0, 290.0))
    with caplog.at_level(logging.WARNING, logger="rule_engine.diagram_layout"):
        _doc(pts, exit_=(0.5, 1.0), entry=(0.5, 0.0), b=(320, 400), pinned_ids=("e1",))
    assert any("rerouted hand-pinned edges: e1" in r.getMessage() for r in caplog.records)


def test_illegal_pin_is_still_repaired():
    # diagonal leg: not axis-aligned, so not a legal pin
    pts = ((250.0, 200.0),)
    out = _points(_doc(pts, b=(500, 300), respect_pins=True))
    xs_ys = list(out)
    assert out != pts
    for (x0, y0), (x1, y1) in zip(xs_ys, xs_ys[1:]):
        assert x0 == x1 or y0 == y1


def test_pinned_ids_empty_keeps_rerouting_and_logs_no_hand_pin(caplog):
    pts = ((140.0, 290.0), (360.0, 290.0))
    report: list = []
    with caplog.at_level(logging.WARNING, logger="rule_engine.diagram_layout"):
        _doc(pts, exit_=(0.5, 1.0), entry=(0.5, 0.0), b=(320, 400),
             pinned_ids=(), reroute_report=report)
    assert report == []
    assert not [r for r in caplog.records if "hand-pinned" in r.getMessage()]


def test_message_names_only_real_pins(caplog):
    nodes = [dl.Node(id=i, label=i, x=x, y=y, render=_ICON)
             for i, x, y in (("a", 100, 100), ("b", 320, 400),
                             ("c", 700, 100), ("d", 920, 400))]
    edges = [
        dl.Edge(id="e1", source="a", target="b", marker="1", exit=(0.5, 1.0),
                entry=(0.5, 0.0), points=((140.0, 290.0), (360.0, 290.0))),
        dl.Edge(id="e2", source="c", target="d", marker="2", exit=(0.5, 1.0),
                entry=(0.5, 0.0), points=((740.0, 290.0), (960.0, 290.0))),
    ]
    report: list = []
    with caplog.at_level(logging.DEBUG, logger="rule_engine.diagram_layout"):
        dl.build_diagram(
            diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
            nodes=nodes, edges=edges, flow_lines=["Flow", "1. x", "2. y"],
            legend_x=1100, page_w=1500, page_h=700,
            respect_pins=False, pinned_ids=("e1",), reroute_report=report)
    assert "e2" not in report
    warn = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert all("e2" not in m for m in warn)


def test_deterministic():
    pts = ((200.0, 140.0), (480.0, 140.0), (480.0, 340.0))
    assert _doc(pts, b=(500, 300)) == _doc(pts, b=(500, 300))
    p2 = ((140.0, 290.0), (360.0, 290.0))
    a = _doc(p2, exit_=(0.5, 1.0), entry=(0.5, 0.0), b=(320, 400), respect_pins=False)
    b = _doc(p2, exit_=(0.5, 1.0), entry=(0.5, 0.0), b=(320, 400), respect_pins=False)
    assert a == b


def test_per_edge_guard_restores_a_strictly_better_pin(monkeypatch):
    """A plan that moves a pinned edge is undone for that edge when the pin
    scores strictly better; a worse pin is replaced (the plan stays)."""
    p2 = ((140.0, 290.0), (360.0, 290.0))
    kw = dict(exit_=(0.5, 1.0), entry=(0.5, 0.0), b=(320, 400), respect_pins=False)
    plain = _points(_doc(p2, **kw))
    assert plain != p2                       # the plan moves the pin

    def pin_is_better(text):
        return (0, 0, 0, 0, 0) if _points(text) == p2 else (1, 0, 0, 0, 0)

    def pin_is_worse(text):
        return (1, 0, 0, 0, 0) if _points(text) == p2 else (0, 0, 0, 0, 0)

    monkeypatch.setattr(dl, "_pin_guard_score", pin_is_better)
    assert _points(_doc(p2, **kw)) == p2     # reverted to the pin
    monkeypatch.setattr(dl, "_pin_guard_score", pin_is_worse)
    assert _points(_doc(p2, **kw)) == plain  # plan kept
    monkeypatch.setattr(dl, "_pin_guard_score", pin_is_better)
    monkeypatch.setattr(dl, "_PIN_GUARD_MAX", 0)
    assert _points(_doc(p2, **kw)) == plain  # guard skipped above the cap

"""1.13.0 fix (ITEM 18): border clearances match what a reader sees.

* ``marker-on-container-border`` uses ``MARKER_BORDER_CLEARANCE`` = badge
  radius 10 + 6 = 16px (strict), not one grid step;
* ``edge-on-container-border`` flags a long parallel leg strictly closer than
  one grid step (was 4px); exactly one grid step is the sanctioned lane.
"""
from __future__ import annotations

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.layout import routers


def test_constants():
    assert geo.MARKER_BADGE_RADIUS == 10.0
    assert geo.MARKER_BORDER_CLEARANCE == 16.0
    assert geo._BORDER_RIDE_TOL == geo.GRID - 0.5
    assert routers._BORDER_CLEAR_TOL == geo._BORDER_RIDE_TOL


def _marker_geo(offset):
    g = DiagramGeometry()
    g.nodes["a"] = Box("a", 40, 160, 78, 78)
    g.nodes["b"] = Box("b", 400, 160, 78, 78)
    g.edges.append(EdgeGeom(id="e1", source="a", target="b", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5), label="1"))
    (mx, my), = geo.marker_anchors(g).values()
    g.containers["c"] = Box("c", mx + offset, my - 100, 300, 300)
    return g


def test_marker_12px_from_border_flagged_17px_not():
    assert geo.check_marker_on_container_border(_marker_geo(12)) == [("e1", "c.left")]
    assert geo.check_marker_on_container_border(_marker_geo(17)) == []


def test_engine_slides_a_marker_past_the_new_clearance():
    g = _marker_geo(12)
    moved = geo.resolve_marker_collisions(g)
    assert "e1" in moved


def _leg_geo(x_leg, border_x=500.0):
    g = DiagramGeometry()
    g.nodes["s"] = Box("s", 100, 100, 78, 78)
    g.nodes["t"] = Box("t", 100, 500, 78, 78)
    g.containers["c"] = Box("c", border_x, 50, 300, 700)
    g.edges.append(EdgeGeom(id="e1", source="s", target="t", orthogonal=True,
                            exit=(1.0, 0.5), entry=(1.0, 0.5),
                            points=[(x_leg, 139), (x_leg, 539)]))
    return g


def test_leg_6px_inside_border_flagged_10px_not():
    assert geo.check_edge_on_container_border(_leg_geo(506)) == [("e1", "c.left")]
    assert geo.check_edge_on_container_border(_leg_geo(510)) == []
    assert geo.check_edge_on_container_border(_leg_geo(490)) == []


def test_nudge_keeps_an_inside_leg_inside():
    src, tgt = Box("s", 600, 100, 78, 78), Box("t", 600, 500, 78, 78)
    c = Box("c", 500, 50, 300, 700)
    pts = routers.nudge_off_container_borders(
        (678, 139), [(508, 139), (508, 539)], (600, 539), src, tgt, {"c": c})
    assert all(x >= c.x + geo.GRID for x, _y in pts)


def test_solver_keeps_the_frozen_reach_and_caption_model():
    """rule_violations (the scored objective) does not count a 6px ride the lint
    reports, and scores captions with the frozen pre-1.13.0 band model."""
    g = _leg_geo(506)
    _errors, warnings = geo.rule_violations(g)
    assert not [w for w in warnings if w[0] == "edge-on-container-border"]
    box = Box("c", 0, 0, 178, 400)
    label, style = "x" * 30, "spacingLeft=110"
    band, _ = geo.container_caption_geom(label, style, box, solver=True)
    assert band.w == 178                           # capped, 40 + 30 x 7.5
    band, _ = geo.container_caption_geom(label, style, box)
    assert band.w == 110 + 4 + 210                 # lint: uncapped, style-aware


def test_marker_on_a_one_grid_step_lane_slides_off_the_leg():
    """A long leg one grid step outside a border keeps every point within 16px
    of it: phase 3 searches past k=4 / up to the slide limit to leave the leg."""
    g = DiagramGeometry()
    g.nodes["q"] = Box("q", 692, 601, 78, 78)
    g.nodes["u"] = Box("u", 910, 121, 78, 78)
    g.containers["acct"] = Box("acct", 220, 60, 580, 680)
    g.edges.append(EdgeGeom(id="e9", source="q", target="u", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5), label="9",
                            points=[(810, 640), (810, 160)]))
    assert geo.check_marker_on_container_border(g)
    moved = geo.resolve_marker_collisions(g)
    g.edges[0].label_pos = moved["e9"]
    assert geo.check_marker_on_container_border(g) == []

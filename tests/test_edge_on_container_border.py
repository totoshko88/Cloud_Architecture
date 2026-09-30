"""Tests for the ``edge-on-container-border`` rule and its router cure (1.10.4).

Root cause: a vertical corridor is a whole-``GRID`` multiple, but a Boundary
container's right/bottom edge is **not** grid-aligned (it wraps a 78px icon plus
padding, ending at e.g. 728). A corridor allocated at ``source_right + GRID``
lands ~2px past that border and reads as riding it. The ``CorridorAllocator``
avoids other edges, not borders, so nothing prevented it before.

Two layers are tested:
1. ``geometry.check_edge_on_container_border`` — the detector / lint gate.
2. ``routers.nudge_off_container_borders`` — the finishing pass that steps a
   border-riding leg one grid line into the gap.
"""

from __future__ import annotations

from pathlib import Path

from rule_engine.geometry import (
    Box,
    DiagramGeometry,
    EdgeGeom,
    build_geometry,
    check_edge_on_container_border,
)
from rule_engine.drawio_model import parse_drawio
from rule_engine.layout.routers import nudge_off_container_borders


def _geo_with_leg(points, *, region_right=728):
    """A source inside a region and a target below it, joined by ``points``.

    The region's right edge sits at ``region_right`` (non-grid-aligned, like a
    real box wrapping a 78px icon + 30 pad)."""
    return DiagramGeometry(
        nodes={
            "hub": Box("hub", 620, 240, 78, 78),
            "obj": Box("obj", 620, 560, 78, 78),
        },
        containers={
            "boundary-region-a": Box("boundary-region-a", 60, 120, region_right - 60, 738),
        },
        edges=[
            EdgeGeom(id="e", source="hub", target="obj", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.5, 0.0), points=points),
        ],
    )


def test_vertical_leg_two_px_off_a_region_border_is_flagged():
    """A long vertical drop at x=730 beside a region right edge at 728 rides it."""
    g = _geo_with_leg([(730, 280), (730, 520), (660, 520)])
    hits = check_edge_on_container_border(g)
    assert hits == [("e", "boundary-region-a.right")]


def test_a_leg_a_clean_grid_step_clear_is_not_flagged():
    """The same drop at x=740 (a grid step past the 728 border) is clean."""
    g = _geo_with_leg([(740, 280), (740, 520), (660, 520)])
    assert check_edge_on_container_border(g) == []


def test_a_short_leg_on_a_border_is_not_flagged():
    """A stub shorter than one STAIR_STEP is not a long run and is ignored."""
    g = _geo_with_leg([(730, 280), (730, 300), (660, 300)])
    assert check_edge_on_container_border(g) == []


def test_a_perpendicular_crossing_is_not_flagged():
    """A horizontal leg crossing the vertical border (not parallel to it) is
    a legitimate crossing, never a ride."""
    # A horizontal run at y=400 from x=660 to x=900 crosses the region's right
    # (vertical) edge at 728 perpendicularly — not judged against a vertical border.
    g = DiagramGeometry(
        nodes={"a": Box("a", 620, 361, 78, 78), "b": Box("b", 900, 361, 78, 78)},
        containers={"boundary-region-a": Box("boundary-region-a", 60, 120, 668, 738)},
        edges=[EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                        exit=(1.0, 0.5), entry=(0.0, 0.5), points=[])],
    )
    assert check_edge_on_container_border(g) == []


def test_nudge_moves_both_ends_of_a_riding_leg_off_the_border():
    """The router pass steps the whole vertical leg one grid line clear (730→740),
    moving BOTH shared waypoints so the route stays orthogonal; the contacts and
    the far waypoint are untouched."""
    containers = {
        "boundary-region-a": Box("boundary-region-a", 60, 120, 668, 738),  # right=728
    }
    src = Box("hub", 620, 240, 78, 78)
    tgt = Box("obj", 620, 560, 78, 78)
    out = nudge_off_container_borders(
        (698.0, 280.0), [(730.0, 280.0), (730.0, 520.0), (660.0, 520.0)],
        (660.0, 560.0), src, tgt, containers,
    )
    assert out == [(740, 280.0), (740, 520.0), (660.0, 520.0)]


def test_nudge_is_a_noop_when_no_leg_rides_a_border():
    """A route already clear of every border comes back unchanged (byte-stable)."""
    containers = {"boundary-region-a": Box("boundary-region-a", 60, 120, 668, 738)}
    src = Box("hub", 620, 240, 78, 78)
    tgt = Box("obj", 620, 560, 78, 78)
    pts = [(760.0, 280.0), (760.0, 520.0), (660.0, 520.0)]
    out = nudge_off_container_borders(
        (698.0, 280.0), list(pts), (660.0, 560.0), src, tgt, containers,
    )
    assert out == [tuple(p) for p in pts]


def test_every_shipped_diagram_has_no_border_riding_leg():
    """The whole committed corpus is clean of this defect after the engine cure."""
    root = Path(__file__).resolve().parents[1] / "examples"
    offenders = {}
    for drawio in sorted(root.rglob("*.drawio")):
        geo = build_geometry(parse_drawio(drawio.read_text(encoding="utf-8"),
                                          path=str(drawio))[0])
        hits = check_edge_on_container_border(geo)
        if hits:
            offenders[str(drawio.relative_to(root))] = hits
    assert offenders == {}, f"border-riding legs remain: {offenders}"

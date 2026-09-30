"""Regression tests for the OCI GenAI hub fan-out routing fixes (1.10.4).

Two defects the reviewer flagged on ``examples/oci/01-oci-genai-stack.drawio``:

1. **Edges 7 (hub→sql) and 8 (hub→obj) crossed.** Both left the hub's bottom
   face, and the marker-ordered exit-band spread put the low-marker back-edge
   (7, target far left) on the centre and pushed the straight-down edge (8) to
   the left band, so 8's bottom-left stub crossed 7's centre-then-left run. The
   fix orders the bottom-face bands by the TARGET's direction (a leftward target
   takes the bottom-left band, a straight-down target the centre), so every stub
   diverges to its own side.

2. **Edge 9 (hub→sec) had an extra corner before entering Vault.** The repair
   loop bumped its drop corridor to separate it from edge 4, leaving a short
   zig-zag into the target's top. The fix straightens a top-entry spine's
   approach into a single corner when the settled geometry stays oracle-clean.
"""

from __future__ import annotations

from pathlib import Path

from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import build_geometry

_OCI = Path(__file__).resolve().parents[1] / "examples" / "oci" / "01-oci-genai-stack.drawio"


def _geo():
    return build_geometry(parse_drawio(_OCI.read_text(encoding="utf-8"), path=str(_OCI))[0])


def _polyline(geo, edge):
    s, t = geo.nodes[edge.source], geo.nodes[edge.target]
    return (
        [(s.x + edge.exit[0] * s.w, s.y + edge.exit[1] * s.h)]
        + [(x, y) for x, y in edge.points]
        + [(t.x + edge.entry[0] * t.w, t.y + edge.entry[1] * t.h)]
    )


def _segments(poly):
    return list(zip(poly, poly[1:]))


def _segments_cross(a, b):
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-9:
        return False
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    return 0 < t < 1 and 0 < u < 1


def test_hub_to_obj_and_hub_to_sql_do_not_cross():
    """The straight-down (hub→obj) and back-edge-left (hub→sql) fan-out branches
    diverge to their own bottom bands and never cross (the 7×8 defect)."""
    geo = _geo()
    obj = next(e for e in geo.edges if e.source == "hub" and e.target == "obj")
    sql = next(e for e in geo.edges if e.source == "hub" and e.target == "sql")
    p_obj, p_sql = _polyline(geo, obj), _polyline(geo, sql)
    for sa in _segments(p_obj):
        for sb in _segments(p_sql):
            assert not _segments_cross(sa, sb), (
                f"hub→obj crosses hub→sql: {p_obj} x {p_sql}"
            )


def test_hub_to_obj_is_a_straight_bottom_drop():
    """hub→obj (target directly below) keeps the bottom-CENTRE and drops straight
    with no interior waypoints."""
    geo = _geo()
    obj = next(e for e in geo.edges if e.source == "hub" and e.target == "obj")
    assert obj.exit[1] is not None and obj.exit[1] >= 1.0, f"not a bottom exit: {obj.exit}"
    assert abs(obj.exit[0] - 0.5) < 0.05, f"not bottom-centre: {obj.exit}"
    assert obj.points == [], f"straight drop should have no waypoints: {obj.points}"


def test_hub_to_sql_leaves_the_bottom_left_band():
    """hub→sql (target far left) leaves the bottom-LEFT band so it diverges left
    immediately rather than crossing the centre drop."""
    geo = _geo()
    sql = next(e for e in geo.edges if e.source == "hub" and e.target == "sql")
    assert sql.exit[1] is not None and sql.exit[1] >= 1.0, f"not a bottom exit: {sql.exit}"
    assert sql.exit[0] is not None and sql.exit[0] < 0.5, f"not bottom-left: {sql.exit}"


def test_hub_to_sec_approach_has_no_extra_corner():
    """hub→sec (the Vault edge) reaches its target's top with a single corner —
    drop in the corridor, step across, drop straight in — not a stair of short
    jogs (the extra-corner defect). At most two interior waypoints."""
    geo = _geo()
    sec = next(e for e in geo.edges if e.source == "hub" and e.target == "sec")
    # Clean approach: exit-right stub, corridor drop, one step across to the
    # contact column, then the pinned top drop — 3 interior waypoints. The kink
    # had 5 (an extra short step-drop-step before the contact).
    assert len(sec.points) <= 3, f"approach has an extra corner: {sec.points}"
    # The last leg drops straight into the top face: the final waypoint shares the
    # entry's x (a clean vertical drop), so there is no last-grid-step jog.
    if sec.points and sec.entry[1] is not None and sec.entry[1] <= 0.0:
        t = geo.nodes["sec"]
        entry_x = t.x + sec.entry[0] * t.w
        assert abs(sec.points[-1][0] - entry_x) < 1.0, (
            f"final leg not a straight drop into the top: {sec.points[-1]} vs x={entry_x}"
        )

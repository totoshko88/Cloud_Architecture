"""Regression tests for the OCI GenAI hub fan-out routing (1.10.4 → 1.10.6).

Hub fan-out routing invariants for ``examples/oci/01-oci-genai-stack.drawio``.

These began as regression guards for two 1.10.4 reviewer defects (a 7×8 bottom-
face crossing and an extra corner before Vault). **Re-baselined at 1.10.6.** The
1.10.4/1.10.5 ``genai_pipeline_spec`` carried a per-provider reorder that pinned
Vault (``sec``) directly below the hub; 1.10.6 removes that hack because the
engine now places every unanchored regional node beside its neighbours on its own
(``layout.base._place_loose_regional``). With the hack gone the engine puts
``sec`` directly to the **right** of the hub (a clean straight level hop,
``hub→sec``) and the object store ``obj`` directly **below** it (a clean straight
bottom drop, ``hub→obj``), with ``hub→sql`` the bottom-left back-edge. The
invariants are unchanged in spirit — the three branches never cross, and the
targets that sit directly adjacent are reached by one straight segment — only
which edge plays which role moved again, this time to the engine's own choice.
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


def test_hub_fanout_branches_do_not_cross():
    """The three hub fan-out branches (hub→sec straight-down, hub→sql back-edge
    left, hub→obj right-face) diverge to their own bands and never cross. Since
    the Vault-raise reorder (sec directly below the hub), the straight-down
    branch is hub→sec, and hub→obj takes the right face — but the no-crossing
    invariant holds for every pair regardless of which target is which."""
    geo = _geo()
    edges = [e for e in geo.edges if e.source == "hub" and e.target in ("sec", "sql", "obj")]
    polys = {e.target: _polyline(geo, e) for e in edges}
    import itertools
    for a, b in itertools.combinations(polys, 2):
        for sa in _segments(polys[a]):
            for sb in _segments(polys[b]):
                assert not _segments_cross(sa, sb), (
                    f"hub→{a} crosses hub→{b}: {polys[a]} x {polys[b]}"
                )


def test_hub_to_obj_is_a_straight_bottom_drop():
    """1.10.6: the engine places ``obj`` (object store) directly below the hub, so
    hub→obj keeps the bottom-CENTRE and drops straight with no interior waypoints
    — the clean short vertical a directly-below target should have."""
    geo = _geo()
    obj = next(e for e in geo.edges if e.source == "hub" and e.target == "obj")
    assert obj.exit[1] is not None and obj.exit[1] >= 1.0, f"not a bottom exit: {obj.exit}"
    assert abs(obj.exit[0] - 0.5) < 0.05, f"not bottom-centre: {obj.exit}"
    assert obj.points == [], f"straight drop should have no waypoints: {obj.points}"


def test_hub_to_sec_is_a_straight_level_hop():
    """1.10.6: the engine places ``sec`` (Vault) directly to the RIGHT of the hub
    on the same row, so hub→sec is a straight level hop — exit the right face,
    enter the left face, no interior waypoints."""
    geo = _geo()
    sec = next(e for e in geo.edges if e.source == "hub" and e.target == "sec")
    assert sec.exit[0] is not None and sec.exit[0] >= 1.0, f"not a right exit: {sec.exit}"
    assert sec.entry[0] is not None and sec.entry[0] <= 0.0, f"not a left entry: {sec.entry}"
    assert sec.points == [], f"straight level hop should have no waypoints: {sec.points}"


def test_hub_to_sql_leaves_the_bottom_left_band():
    """hub→sql (target far left) leaves the bottom-LEFT band so it diverges left
    immediately rather than crossing the centre drop."""
    geo = _geo()
    sql = next(e for e in geo.edges if e.source == "hub" and e.target == "sql")
    assert sql.exit[1] is not None and sql.exit[1] >= 1.0, f"not a bottom exit: {sql.exit}"
    assert sql.exit[0] is not None and sql.exit[0] < 0.5, f"not bottom-left: {sql.exit}"

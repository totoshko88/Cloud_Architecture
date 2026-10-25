"""SYS-B (G36) — order the same-side exit spread by TARGET DIRECTION, not marker.

The owner's rule R3 ("exit nearer the target") means that when two edges leave
ONE source on ONE shared face, which edge keeps the centre and which takes which
quarter must follow where each target sits — so the upper-target edge gets the
upper band and the two stubs never cross, *regardless of marker order*. The
engine already did this on the bottom face (pipeline step 2a-bottom) and ranked
the right face by route lane (``_exit_band_rank``, step 2b4); SYS-B generalises
it via the shared :func:`~rule_engine.layout.routers.exit_direction_key` so the
generic same-side spread and the right-face same-rank tiebreak are both ordered
by direction.

These guard owner comments 01 (9/10), 02-swap (8/9), 07 (3/4), 09 (2/9, 17/16,
11/18): "swap the two exit points so they do not cross."
"""
from __future__ import annotations

from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec
from rule_engine.layout.routers import exit_direction_key
from rule_engine.layout.place import place_and_size

ACCOUNT = (ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),)


def _reverse_marker_spec() -> DiagramSpec:
    """One source fanning out to two targets on the SAME (right) face, declared
    in REVERSE marker order: the LOWER-marker edge (e1) goes to the LOWER target
    and the HIGHER-marker edge (e2) to the UPPER target. A marker-ordered spread
    would hand e1 the centre/upper band and push e2 below, crossing; a
    direction-ordered spread must hand the UPPER-target edge (e2) the upper band.
    """
    nodes = (
        NodeSpec(id="hub", role="serverless_fn", lane="workers", region="", slot=1),
        NodeSpec(id="upper", role="object_store", lane="data", region="", slot=0),
        NodeSpec(id="lower", role="managed_sql", lane="data", region="", slot=2),
    )
    edges = (
        EdgeSpec(id="e1", source="hub", target="lower", marker="1"),
        EdgeSpec(id="e2", source="hub", target="upper", marker="2"),
    )
    return DiagramSpec(
        diagram_id="sys-b", diagram_name="sys-b", axis="left-right",
        nodes=nodes, edges=edges, containers=ACCOUNT,
        flow_lines=("Flow", "1. lower", "2. upper"),
        title="aws sys-b — 000000000000 / eu-central-1 | 2026-10-23 | v1",
        order="manual",  # keep the declared reverse-marker order so we test the spread, not the ordering pass
    )


def _polyline(placed, pe):
    s = placed.nodes[pe.spec.source]
    t = placed.nodes[pe.spec.target]
    return (
        [(s.x + pe.exit[0] * s.w, s.y + pe.exit[1] * s.h)]
        + [(float(x), float(y)) for x, y in pe.points]
        + [(t.x + pe.entry[0] * t.w, t.y + pe.entry[1] * t.h)]
    )


def _segments_cross(a, b):
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-9:
        return False
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    return 0 < t < 1 and 0 < u < 1


def _crosses(pa, pb) -> bool:
    segs_a = list(zip(pa, pa[1:]))
    segs_b = list(zip(pb, pb[1:]))
    return any(_segments_cross(sa, sb) for sa in segs_a for sb in segs_b)


# --------------------------------------------------------------------------- #
# The shared ranking key orders by the target's along-face centre, not marker.
# --------------------------------------------------------------------------- #

def test_exit_direction_key_orders_right_face_by_target_y():
    spec = _reverse_marker_spec()
    placed, _containers = place_and_size(spec)
    by_id = {e.id: e for e in spec.edges}
    # On a right/left face the key is the target's centre-y, so the UPPER target
    # (e2) sorts BEFORE the LOWER target (e1) despite the higher marker.
    k_upper = exit_direction_key(by_id["e2"], placed, "right")
    k_lower = exit_direction_key(by_id["e1"], placed, "right")
    assert k_upper < k_lower


def test_exit_direction_key_orders_bottom_face_by_target_x():
    spec = _reverse_marker_spec()
    placed, _containers = place_and_size(spec)
    by_id = {e.id: e for e in spec.edges}
    # On a top/bottom face the key is the target's centre-x (not its centre-y),
    # so the band on a bottom face follows the target's horizontal direction.
    lower = placed["lower"]
    assert exit_direction_key(by_id["e1"], placed, "bottom") == lower.x + lower.w / 2.0


# --------------------------------------------------------------------------- #
# End-to-end: the two same-face exits come out UNCROSSED.
# --------------------------------------------------------------------------- #

def test_reverse_marker_same_face_exits_do_not_cross():
    placed = layout(_reverse_marker_spec())
    edges = {pe.spec.id: pe for pe in placed.edges}
    pa = _polyline(placed, edges["e1"])
    pb = _polyline(placed, edges["e2"])
    assert not _crosses(pa, pb), "SYS-B: the reverse-marker same-face exits must not cross"


def test_upper_target_edge_takes_the_upper_exit_band():
    """The edge to the UPPER target (e2) must leave from an exit band at or above
    the edge to the LOWER target (e1) — the direction-ordered spread, not marker
    order which would invert them."""
    placed = layout(_reverse_marker_spec())
    edges = {pe.spec.id: pe for pe in placed.edges}
    e_upper = edges["e2"]
    e_lower = edges["e1"]
    # Both leave the right face (exitX ~ 1.0); the band is exitY. The upper
    # target's edge must have the smaller (higher-on-canvas) exitY.
    assert e_upper.exit[1] <= e_lower.exit[1]

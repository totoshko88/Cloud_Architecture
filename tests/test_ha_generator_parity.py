"""Cross-provider geometry parity for the HA multi-region golden pair.

The declarative layout engine computes one shared geometry for both HA diagrams
(the ``flow`` summary and the ``landscape`` as-built); each provider generator
applies only a :class:`ProviderSkin` (icons + labels + container styles) on top.
So the four providers' summaries must share byte-identical node boxes, container
boxes, and edge exit/entry/waypoints — and likewise for the four landscapes —
with only icons and labels differing (Requirement 11.2, 11.3).

This test builds all four skins' summary and landscape via ``build_summary`` /
``build_landscape``, parses each with ``rule_engine.geometry.build_geometry``,
and asserts the parsed geometry is equal across providers per class.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "src"))
sys.path.insert(0, os.path.join(HERE, "scripts"))

from rule_engine import geometry as geo  # noqa: E402
from ha_multiregion_common import build_summary, build_landscape  # noqa: E402

PROVIDERS = ("aws", "azure", "gcp", "oci")


def _skin(provider: str):
    """Load the per-provider ``SKIN`` from its build_*_ha_example.py script."""
    mod = importlib.import_module(f"build_{provider}_ha_example")
    return mod.SKIN


def _node_boxes(g: geo.DiagramGeometry):
    return {nid: (b.x, b.y, b.w, b.h) for nid, b in g.nodes.items()}


def _container_boxes(g: geo.DiagramGeometry):
    return {cid: (b.x, b.y, b.w, b.h) for cid, b in g.containers.items()}


def _edge_geoms(g: geo.DiagramGeometry):
    return {
        e.id: (e.source, e.target, e.exit, e.entry, tuple(e.points))
        for e in g.edges
    }


def _geometry_triple(text: str):
    g = geo.build_geometry(text)
    return _node_boxes(g), _container_boxes(g), _edge_geoms(g)


@pytest.mark.parametrize("builder", [build_summary, build_landscape],
                         ids=["summary", "landscape"])
def test_ha_geometry_identical_across_providers(builder):
    """Node boxes, container boxes, and edge contact points/waypoints are
    identical across all four providers for a given diagram class."""
    triples = {p: _geometry_triple(builder(_skin(p))) for p in PROVIDERS}

    ref_provider = PROVIDERS[0]
    ref_nodes, ref_containers, ref_edges = triples[ref_provider]

    for p in PROVIDERS[1:]:
        nodes, containers, edges = triples[p]
        assert nodes == ref_nodes, f"node geometry differs: {p} vs {ref_provider}"
        assert containers == ref_containers, (
            f"container geometry differs: {p} vs {ref_provider}"
        )
        assert edges == ref_edges, f"edge geometry differs: {p} vs {ref_provider}"


def test_ha_parity_has_expected_shape():
    """Sanity: the parsed geometry actually carries the pair's node/edge counts,
    so the parity assertion above is comparing real geometry, not empty maps."""
    sg = geo.build_geometry(build_summary(_skin("aws")))
    lg = geo.build_geometry(build_landscape(_skin("aws")))
    assert len(sg.nodes) == 9
    assert len(sg.edges) == 9
    assert len(lg.nodes) == 34
    assert len(lg.edges) == 12
    # both region frames present in the summary; account+vpc+az in the landscape.
    assert set(sg.containers) == {"nb_a", "nb_b"}
    assert "boundary-account" in lg.containers


# --------------------------------------------------------------------------- #
# Structural-shape parity check (Requirement 12.6).
#
# The parity test above proves the four providers share byte-identical geometry.
# This block adds a durable, test-time *structural predicate* (not a new linter
# rule) that asserts the generated ``landscape`` reproduces the reference's
# structural shape, independent of exact byte coordinates (Req 12.6):
#
#   * peer AZ boxes are STACKED — shared x-range, disjoint y-range, az-2 below
#     az-1 (Req 12.1), and EQUAL WIDTH across all four AZs (Req 12.2);
#   * VPC service-row nodes (lb/queue/fn/secrets) form a distinct tier ABOVE the
#     first AZ band and sit inside the VPC, and no AZ box contains a service-row
#     node (Req 12.3);
#   * every node and container origin is non-negative and on-grid, with
#     min(x) == min(y) == CONTAINER_PAD (Req 12.4).
#
# It runs per provider so the invariant is explicit for each skin, even though
# geometry parity (above) already guarantees the four are identical.
# --------------------------------------------------------------------------- #

from rule_engine.diagram_layout import CONTAINER_PAD, GRID  # noqa: E402
from rule_engine.geometry import LABEL_BAND  # noqa: E402
from rule_engine.layout_engine import TITLE_BAND  # noqa: E402

# The two VPC service rows (declared members of the VPC directly, not an AZ).
_SERVICE_ROW = {
    "a": ("lb_a", "queue_a", "fn_a", "sec_a"),
    "b": ("lb_b", "queue_b", "fn_b", "sec_b"),
}
_AZ_BY_REGION = {
    "a": ("boundary-az-a1", "boundary-az-a2"),
    "b": ("boundary-az-b1", "boundary-az-b2"),
}
_VPC_BY_REGION = {"a": "boundary-vpc-a", "b": "boundary-vpc-b"}
_ALL_AZ = ("boundary-az-a1", "boundary-az-a2", "boundary-az-b1", "boundary-az-b2")


def _assert_landscape_shape(g: geo.DiagramGeometry) -> None:
    """Assert the Req-12 structural invariants on a parsed landscape geometry."""
    # --- AZ boxes stacked (shared x-range) and az-2 below az-1 (disjoint y). ---
    for region, (az1_id, az2_id) in _AZ_BY_REGION.items():
        az1, az2 = g.containers[az1_id], g.containers[az2_id]
        assert az1.x == az2.x, f"{region}: AZ boxes not x-aligned ({az1.x} vs {az2.x})"
        assert az1.w == az2.w, f"{region}: AZ boxes not equal width ({az1.w} vs {az2.w})"
        # az-2 sits fully below az-1 (disjoint y-range, stacked vertically N–S).
        assert az2.y >= az1.bottom, (
            f"{region}: az-2 (y={az2.y}) not below az-1 bottom ({az1.bottom})"
        )

    # --- Equal width across ALL four AZ boxes (Req 12.2 peer-band rule). ---
    widths = {aid: g.containers[aid].w for aid in _ALL_AZ}
    assert len(set(widths.values())) == 1, f"AZ widths differ: {widths}"

    # --- VPC service row is a distinct tier ABOVE the first AZ and inside VPC. ---
    for region, node_ids in _SERVICE_ROW.items():
        vpc = g.containers[_VPC_BY_REGION[region]]
        first_az = g.containers[_AZ_BY_REGION[region][0]]
        for nid in node_ids:
            n = g.nodes[nid]
            fp = n.footprint(LABEL_BAND)
            # footprint bottom above the first AZ box's top (distinct tier).
            assert fp.bottom <= first_az.y, (
                f"{nid} footprint bottom ({fp.bottom}) not above first AZ top "
                f"({first_az.y})"
            )
            # and inside the VPC box on every side.
            assert (
                n.x >= vpc.x and n.y >= vpc.y
                and fp.right <= vpc.right and fp.bottom <= vpc.bottom
            ), f"{nid} not inside VPC {_VPC_BY_REGION[region]}"

    # --- Within-band HORIZONTAL ordering (Req 12.6, the regression guard). ---
    # Each tier band reads left→right, NOT stacked in one column. This is the
    # exact defect the structural predicate previously missed: the VPC service
    # row (lb/queue/worker/secrets) and each AZ main row (app/cache/db/obj) must
    # spread across distinct columns on a shared row, not collapse into a single
    # column of same-x nodes. Assert both: one shared y (a row) and strictly
    # increasing, distinct x (columns) in lane order.
    def _assert_horizontal_row(node_ids, label):
        boxes = [g.nodes[nid] for nid in node_ids]
        ys = {b.y for b in boxes}
        assert len(ys) == 1, f"{label} is not one row (distinct y: {sorted(ys)})"
        xs = [b.x for b in boxes]
        assert len(set(xs)) == len(xs), f"{label} columns collapse (x: {xs})"
        assert xs == sorted(xs), f"{label} not left→right ordered (x: {xs})"

    for region, node_ids in _SERVICE_ROW.items():
        _assert_horizontal_row(node_ids, f"service row {region}")
    # AZ-1 main row (sub=0 nodes): app → cache → db → obj, left→right.
    _AZ1_MAIN = {
        "a": ("app_a1", "cache_a1", "db_a1", "obj_a1"),
        "b": ("app_b1", "cache_b1", "db_b1", "obj_b1"),
    }
    for region, node_ids in _AZ1_MAIN.items():
        _assert_horizontal_row(node_ids, f"az-1 main row {region}")

    # --- Edge contact rules (directional contract; the routing regression guard). ---
    # Every edge must exit a CONTRACT-LEGAL face: the RIGHT (fx >= 0.5) OR the
    # BOTTOM (fy == 1). v1.5.1 (variant A) lets a SOURCE fan-out route its
    # straight-down branch out the bottom — a clean vertical drop into a
    # directly-below target, exactly like the compact summary — instead of
    # cramming every branch onto the right face and looping the vertical one. A
    # bottom exit is legal under the directional contract (`edge-direction`
    # admits exitX>=0.5 OR exitY==1), so the guard now accepts either face and
    # only rejects the true defects: a LEFT exit (fx < 0.5, not on the bottom) or
    # a TOP exit (fy == 0).
    for e in g.edges:
        ex, ey = e.exit
        if ex is None and ey is None:
            continue  # floated (none in the landscape); direction rule owns it
        exits_right = ex is not None and ex >= 0.5
        exits_bottom = ey is not None and ey >= 1.0
        assert exits_right or exits_bottom, (
            f"edge {e.id} exits neither right nor bottom (exit={e.exit})"
        )
        # A top exit is never valid (a stub up crosses the row above).
        assert not (ey is not None and ey <= 0.0), f"edge {e.id} exits the top"
    # The three cross-region hops enter a CONTRACT-LEGAL near face — the target's
    # TOP (entryY==0) OR its LEFT (entryX==0). v1.5.1 routes a hop whose target
    # has a clear left approach in the inter-row gap + LEFT entry (the reviewer's
    # l11 route), avoiding an over-row corridor on the target AZ's caption; a hop
    # to a target with a left neighbour still enters from the TOP (Rule C). Both
    # are valid; the defect the guard rejects is a right/bottom entry.
    _CROSS_REGION = {"l2", "l10", "l11"}
    for e in g.edges:
        if e.id in _CROSS_REGION:
            nx, ny = e.entry
            enters_top = ny is not None and ny <= 0.0
            enters_left = nx is not None and nx <= 0.0
            assert enters_top or enters_left, (
                f"cross-region edge {e.id} does not enter from the top or left "
                f"(entry={e.entry})"
            )

    # --- No edge polyline segment crosses an UNRELATED icon (defect: edge 4
    #     drawn through app-az2). check_edge_routing only samples waypoint-FREE
    #     edges, so this samples every real segment (contact point → waypoints →
    #     contact point) against every non-endpoint node box, catching a routed
    #     edge that cuts a glyph it does not connect. ---
    from rule_engine.geometry import segment_crosses_box as _seg_x
    for e in g.edges:
        if e.source not in g.nodes or e.target not in g.nodes:
            continue
        s, t = g.nodes[e.source], g.nodes[e.target]
        sx = (s.x + (e.exit[0] if e.exit[0] is not None else 1.0) * s.w,
              s.y + (e.exit[1] if e.exit[1] is not None else 0.5) * s.h)
        tx = (t.x + (e.entry[0] if e.entry[0] is not None else 0.0) * t.w,
              t.y + (e.entry[1] if e.entry[1] is not None else 0.5) * t.h)
        polyline = [sx] + list(e.points) + [tx]
        for other, nb in g.nodes.items():
            if other in (e.source, e.target):
                continue
            for p, q in zip(polyline, polyline[1:]):
                assert not _seg_x(p, q, nb), (
                    f"edge {e.id} ({e.source}->{e.target}) crosses unrelated icon {other}"
                )

    # --- No edge crosses an unrelated node's LABEL BAND (Rule F). A corridor one
    #     grid step under an icon would run through the service caption beneath
    #     it; every horizontal corridor must clear the label band. Uses the same
    #     check the linter runs (edge-crosses-label). ---
    from rule_engine.geometry import check_edge_crosses_label as _crosses_label
    assert _crosses_label(g) == [], (
        f"edges cross a service label band: {_crosses_label(g)}"
    )

    # --- No edge crosses a CONTAINER's top caption band (v1.5.1). A cross-region
    #     corridor along a VPC top edge would slice its ``vpc-...`` label (edge 2);
    #     a fan-out side corridor down a wide AZ box must clear its short caption
    #     (edge 4). Uses the same check the linter runs. ---
    from rule_engine.geometry import check_edge_crosses_container_label as _crosses_clabel
    assert _crosses_clabel(g) == [], (
        f"edges cross a container caption band: {_crosses_clabel(g)}"
    )

    # --- Corridor step-out: no vertical/horizontal run sits glued to an icon
    #     edge; the first turn is >= one grid step off the source glyph. Sampled
    #     as: the first waypoint of any routed edge is >= GRID off the source box
    #     on the axis it steps out along. ---
    for e in g.edges:
        if not e.points or e.source not in g.nodes:
            continue
        s = g.nodes[e.source]
        fx, fy = e.points[0]
        # A right exit steps out along x: the first waypoint x must clear the
        # source's right edge by >= one GRID step (the padding fix).
        if e.exit[0] is not None and e.exit[0] >= 1.0:
            assert fx >= s.x + s.w + GRID - 0.001, (
                f"edge {e.id} first turn is glued to the source icon "
                f"(x={fx}, source right={s.x + s.w})"
            )

    # --- No AZ box contains any service-row node. ---
    service_nodes = [nid for ids in _SERVICE_ROW.values() for nid in ids]
    for aid in _ALL_AZ:
        az = g.containers[aid]
        for nid in service_nodes:
            n = g.nodes[nid]
            inside = (
                n.x >= az.x and n.y >= az.y
                and n.x + n.w <= az.right and n.y + n.h <= az.bottom
            )
            assert not inside, f"service-row node {nid} sits inside AZ box {aid}"

    # --- Non-negative, on-grid origins; min(x)==CONTAINER_PAD, min(y) reserves
    #     the title band (CONTAINER_PAD + TITLE_BAND) above the top container. ---
    origins = [(b.x, b.y) for b in g.nodes.values()]
    origins += [(b.x, b.y) for b in g.containers.values()]
    for x, y in origins:
        assert x >= 0 and y >= 0, f"negative origin ({x}, {y})"
        assert x % GRID == 0 and y % GRID == 0, f"off-grid origin ({x}, {y})"
    assert min(x for x, _ in origins) == CONTAINER_PAD, "min x != CONTAINER_PAD"
    assert min(y for _, y in origins) == CONTAINER_PAD + TITLE_BAND, "min y != title band"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_landscape_reproduces_reference_shape(provider):
    """The generated landscape reproduces the reference's structural shape for
    every provider: stacked equal-width AZs, a distinct VPC service-row tier
    above the zones, and non-negative on-grid origins (Requirement 12.6)."""
    g = geo.build_geometry(build_landscape(_skin(provider)))
    _assert_landscape_shape(g)

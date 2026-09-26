"""Unit tests for the declarative lane-grid layout engine scaffold.

Task 1 scope only: the coordinate-free declaration model, the canonical lane
table, and ``_validate_spec``. Covers a valid spec passing plus the three
rejection paths (unknown lane, duplicate slot, dangling edge), each naming the
offending field.

Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.4
"""

from __future__ import annotations

import dataclasses

import pytest

from rule_engine import layout_engine as le
from rule_engine.layout_engine import (
    ContainerSpec,
    DiagramSpec,
    EdgeSpec,
    NodeSpec,
    SpecError,
    _validate_spec,
)


def _valid_spec() -> DiagramSpec:
    return DiagramSpec(
        diagram_id="diag-1",
        diagram_name="test",
        axis="north-south",
        nodes=(
            NodeSpec(id="user", role="actor", lane="actors", region="", slot=0),
            NodeSpec(id="alb", role="lb", lane="edge", region="", slot=0),
            NodeSpec(id="fn-a", role="serverless_fn", lane="workers", region="a", slot=0),
            NodeSpec(id="fn-b", role="serverless_fn", lane="workers", region="b", slot=0),
        ),
        edges=(
            EdgeSpec(id="e1", source="user", target="alb", marker="1"),
            EdgeSpec(id="e2", source="alb", target="fn-a", marker="2"),
        ),
        containers=(
            ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
            ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ),
        flow_lines=("Flow", "1. user calls the load balancer"),
        title="test | 2025-01-15 | v1",
    )


def test_canonical_constants_imported_not_redefined():
    # Constants come straight from diagram_layout (Req 3.1) — same objects.
    from rule_engine import diagram_layout as dl

    assert le.ICON_SIZE == dl.ICON_SIZE
    assert le.GRID == dl.GRID
    assert le.COL_STEP == dl.COL_STEP
    assert le.ROW_STEP == dl.ROW_STEP
    assert le.CONTAINER_PAD == dl.CONTAINER_PAD


def test_lane_table_is_the_eight_canonical_lanes_in_order():
    assert le.LANES == (
        "actors", "edge", "router", "async",
        "workers", "platform", "data", "on-premises",
    )
    assert le.LANE_INDEX["actors"] == 0
    assert le.LANE_INDEX["on-premises"] == 7


def test_declaration_dataclasses_are_frozen_and_have_no_coordinates():
    # Req 1.4: coordinates cannot be expressed in a declaration.
    node = NodeSpec(id="n", role="r", lane="edge", region="", slot=0)
    field_names = {f.name for f in dataclasses.fields(node)}
    assert not (field_names & {"x", "y", "w", "h"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        node.slot = 3  # type: ignore[misc]

    edge = EdgeSpec(id="e", source="a", target="b", marker="1")
    edge_fields = {f.name for f in dataclasses.fields(edge)}
    assert not (edge_fields & {"exit", "entry", "points"})


def test_valid_spec_passes():
    # Should not raise.
    _validate_spec(_valid_spec())


def test_unknown_lane_raises_naming_the_lane():
    spec = _valid_spec()
    bad = dataclasses.replace(spec, nodes=spec.nodes + (
        NodeSpec(id="mystery", role="r", lane="frontend", region="", slot=9),
    ))
    with pytest.raises(SpecError) as ei:
        _validate_spec(bad)
    assert "frontend" in str(ei.value)


def test_duplicate_slot_raises_naming_the_key():
    spec = _valid_spec()
    # Same (lane, region, slot) as the existing "alb" node.
    bad = dataclasses.replace(spec, nodes=spec.nodes + (
        NodeSpec(id="dup", role="r", lane="edge", region="", slot=0),
    ))
    with pytest.raises(SpecError) as ei:
        _validate_spec(bad)
    msg = str(ei.value)
    assert "duplicate slot" in msg
    assert "dup" in msg


def test_dangling_edge_endpoint_raises_naming_the_endpoint():
    spec = _valid_spec()
    bad = dataclasses.replace(spec, edges=spec.edges + (
        EdgeSpec(id="e-bad", source="alb", target="ghost", marker="9"),
    ))
    with pytest.raises(SpecError) as ei:
        _validate_spec(bad)
    msg = str(ei.value)
    assert "e-bad" in msg
    assert "ghost" in msg


# ---------------------------------------------------------------------------
# Task 2: node placement on the lane grid (Req 2.2, 2.3, 2.5, 3.1, 3.2, 3.3, 3.5)
# ---------------------------------------------------------------------------

from rule_engine.geometry import Box, DiagramGeometry, check_node_overlap


def _placement_spec(axis: str) -> DiagramSpec:
    """A spec with region A/B service tiers that mirror each other, plus a
    couple of multi-slot lanes, for exercising placement on either axis."""
    return DiagramSpec(
        diagram_id="place-1",
        diagram_name="placement",
        axis=axis,
        nodes=(
            # region A workers/data tiers, two slots each
            NodeSpec(id="wa0", role="serverless_fn", lane="workers", region="a", slot=0),
            NodeSpec(id="wa1", role="serverless_fn", lane="workers", region="a", slot=1),
            NodeSpec(id="da0", role="managed_sql", lane="data", region="a", slot=0),
            # region B mirror
            NodeSpec(id="wb0", role="serverless_fn", lane="workers", region="b", slot=0),
            NodeSpec(id="wb1", role="serverless_fn", lane="workers", region="b", slot=1),
            NodeSpec(id="db0", role="managed_sql", lane="data", region="b", slot=0),
            # a node with a sub-row offset
            NodeSpec(id="pa0", role="secrets_store", lane="platform", region="a", slot=0, sub=1),
        ),
        edges=(),
        containers=(),
        flow_lines=("Flow",),
        title="placement | 2025-01-15 | v1",
    )


def test_place_nodes_every_origin_is_a_grid_multiple():
    # Req 3.2: every emitted x/y is a whole GRID multiple.
    for axis in ("north-south", "left-right"):
        placed = le.place_nodes(_placement_spec(axis))
        assert placed  # non-empty
        for box in placed.values():
            assert box.x % le.GRID == 0, (axis, box)
            assert box.y % le.GRID == 0, (axis, box)


def test_place_nodes_icon_footprint_is_canonical_icon_size():
    # Req 3.1: node cell is the canonical ICON_SIZE square.
    placed = le.place_nodes(_placement_spec("north-south"))
    for box in placed.values():
        assert box.w == le.ICON_SIZE
        assert box.h == le.ICON_SIZE


def test_place_nodes_region_b_is_region_a_plus_fixed_step_north_south():
    # Req 3.3: region B is a mirror-symmetric copy of region A, offset along the
    # SECONDARY axis so the two peer regions sit side-by-side (x for north-south),
    # identical on the PRIMARY (tier) axis. The step is content-derived — a
    # single, uniform, grid-aligned, positive value across every mirrored pair
    # (region B is region A translated), and never smaller than REGION_GAP so the
    # peers always clear each other.
    placed = le.place_nodes(_placement_spec("north-south"))
    pairs = (("wa0", "wb0"), ("wa1", "wb1"), ("da0", "db0"))
    for a_id, b_id in pairs:
        a, b = placed[a_id], placed[b_id]
        assert b.y == a.y                       # primary axis identical (mirror)
        assert b.x - a.x > 0                    # region B offset to the right
        assert (b.x - a.x) % le.GRID == 0       # step stays on the grid
    # The offset is uniform across every mirrored pair (a translated copy) and at
    # least the minimum peer gap.
    deltas = {placed[b].x - placed[a].x for a, b in pairs}
    assert len(deltas) == 1                     # a single, uniform step
    assert next(iter(deltas)) >= le.REGION_GAP


def test_place_nodes_region_b_is_region_a_plus_fixed_step_left_right():
    # Req 2.3 + 3.3: on the left-right axis the secondary axis is y, so region B
    # sits BELOW region A, offset by a uniform grid-aligned content-derived step,
    # identical on the primary (x) axis.
    placed = le.place_nodes(_placement_spec("left-right"))
    pairs = (("wa0", "wb0"), ("wa1", "wb1"), ("da0", "db0"))
    for a_id, b_id in pairs:
        a, b = placed[a_id], placed[b_id]
        assert b.x == a.x                       # primary axis identical (mirror)
        assert b.y - a.y > 0                    # region B offset below
        assert (b.y - a.y) % le.GRID == 0
    deltas = {placed[b].y - placed[a].y for a, b in pairs}
    assert len(deltas) == 1
    assert next(iter(deltas)) >= le.REGION_GAP


def test_place_nodes_axis_maps_lane_and_slot_to_the_right_axes():
    # Req 2.2: north-south → lane index is the row (y), slot is the column (x).
    ns = le.place_nodes(_placement_spec("north-south"))
    # workers slot 0 vs slot 1 differ on x only (same lane → same row).
    assert ns["wa1"].x - ns["wa0"].x == le.COL_STEP
    assert ns["wa1"].y == ns["wa0"].y
    # workers lane vs data lane differ on y only (same slot → same column).
    assert ns["da0"].y - ns["wa0"].y == (le.LANE_INDEX["data"] - le.LANE_INDEX["workers"]) * le.ROW_STEP
    assert ns["da0"].x == ns["wa0"].x

    # Req 2.3: left-right → lane index is the column (x), slot is the row (y).
    lr = le.place_nodes(_placement_spec("left-right"))
    assert lr["wa1"].y - lr["wa0"].y == le.ROW_STEP
    assert lr["wa1"].x == lr["wa0"].x
    assert lr["da0"].x - lr["wa0"].x == (le.LANE_INDEX["data"] - le.LANE_INDEX["workers"]) * le.COL_STEP
    assert lr["da0"].y == lr["wa0"].y


def test_place_nodes_sub_offsets_the_secondary_axis():
    # sub nudges the node along the secondary axis by SUB_STEP, still on-grid.
    ns = le.place_nodes(_placement_spec("north-south"))
    # pa0 has sub=1; on north-south the secondary axis is x.
    base_x = le._ORIGIN[0] + 0 * le.COL_STEP  # slot 0
    assert ns["pa0"].x == base_x + le.SUB_STEP
    assert ns["pa0"].x % le.GRID == 0


def test_place_nodes_no_two_footprints_overlap():
    # Req 3.5 / 2.5: no two placed footprints overlap (check_node_overlap clean).
    for axis in ("north-south", "left-right"):
        placed = le.place_nodes(_placement_spec(axis))
        geo = DiagramGeometry(nodes=placed)
        assert check_node_overlap(geo) == [], axis


def test_place_nodes_grid_alignment_clean_via_oracle():
    # Req 3.2 stated through the actual validator the engine will be judged by.
    from rule_engine.geometry import check_grid_alignment

    for axis in ("north-south", "left-right"):
        placed = le.place_nodes(_placement_spec(axis))
        geo = DiagramGeometry(nodes=placed)
        assert check_grid_alignment(geo) == [], axis


def test_place_nodes_is_deterministic():
    # Req 11.1 foundation: same spec → identical placement.
    spec = _placement_spec("north-south")
    a = le.place_nodes(spec)
    b = le.place_nodes(spec)
    assert {k: (v.x, v.y, v.w, v.h) for k, v in a.items()} == {
        k: (v.x, v.y, v.w, v.h) for k, v in b.items()
    }


def test_place_nodes_unknown_axis_raises():
    spec = dataclasses.replace(_placement_spec("north-south"), axis="diagonal")
    with pytest.raises(SpecError) as ei:
        le.place_nodes(spec)
    assert "diagonal" in str(ei.value)


def test_place_nodes_validates_before_placing():
    # An invalid spec (unknown lane) is rejected by place_nodes too.
    spec = _placement_spec("north-south")
    bad = dataclasses.replace(spec, nodes=spec.nodes + (
        NodeSpec(id="mystery", role="r", lane="frontend", region="a", slot=9),
    ))
    with pytest.raises(SpecError):
        le.place_nodes(bad)


# ---------------------------------------------------------------------------
# Task 3: container sizing, equal width, block centring
# (Req 3.4, 4.1, 4.2, 4.3, 4.4, 4.5)
# ---------------------------------------------------------------------------

from rule_engine.geometry import (
    check_container_padding,
    check_container_overlap,
)


def _landscape_spec(axis: str = "north-south", extra_b_slot: bool = False) -> DiagramSpec:
    """A nested account ⊃ vpc ⊃ az spec with two mirror regions.

    Region A and B each carry a ``workers`` tier and a ``data`` tier, wrapped by
    two AZ boxes per region (az-1 = the upper tier, az-2 = the lower), all inside
    the region VPC, all inside the account. When ``extra_b_slot`` is set, region
    B gets one extra worker slot so its raw block is wider than A's — this forces
    the equal-width widening + re-centre paths to actually run.
    """
    nodes = []
    for r in ("a", "b"):
        for s in range(3):
            nodes.append(NodeSpec(id=f"w{r}{s}", role="fn", lane="workers", region=r, slot=s))
        for s in range(2):
            nodes.append(NodeSpec(id=f"d{r}{s}", role="sql", lane="data", region=r, slot=s))
    if extra_b_slot:
        nodes.append(NodeSpec(id="wb3", role="fn", lane="workers", region="b", slot=3))
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
        ContainerSpec(id="vpc-b", kind="vpc", region="b", parent="acct", label_key="vpc"),
        ContainerSpec(id="az-a1", kind="az", region="a", parent="vpc-a", label_key="az"),
        ContainerSpec(id="az-a2", kind="az", region="a", parent="vpc-a", label_key="az"),
        ContainerSpec(id="az-b1", kind="az", region="b", parent="vpc-b", label_key="az"),
        ContainerSpec(id="az-b2", kind="az", region="b", parent="vpc-b", label_key="az"),
    )
    return DiagramSpec(
        diagram_id="ls-1",
        diagram_name="landscape",
        axis=axis,
        nodes=tuple(nodes),
        edges=(),
        containers=containers,
        flow_lines=("Flow",),
        title="landscape | 2025-01-15 | v1",
    )


def _sized(spec: DiagramSpec):
    """Place, size, and centre; return (placed_after_centre, containers)."""
    placed = le.place_nodes(spec)
    containers = le.size_containers(placed, spec)
    placed = le.centre_block_in_vpc(placed, containers, spec)
    return placed, containers


def _geo(placed, containers) -> DiagramGeometry:
    return DiagramGeometry(nodes=placed, containers=containers)


def test_size_containers_padding_clean_via_oracle():
    # Req 4.1: every node's footprint sits >= CONTAINER_PAD inside its container.
    for extra in (False, True):
        placed, containers = _sized(_landscape_spec(extra_b_slot=extra))
        geo = _geo(placed, containers)
        assert check_container_padding(geo, pad=le.CONTAINER_PAD) == [], extra


def test_size_containers_overlap_clean_via_oracle():
    # Req 4.2: sibling containers (vpc-a/vpc-b, az peers) never overlap; parents
    # properly nest their children.
    for extra in (False, True):
        placed, containers = _sized(_landscape_spec(extra_b_slot=extra))
        geo = _geo(placed, containers)
        assert check_container_overlap(geo) == [], extra


def test_size_containers_nesting_is_strict():
    # Req 4.2/4.4: az fully inside vpc, vpc fully inside account, each by >= PAD.
    _, c = _sized(_landscape_spec())

    def _inside(inner, outer, pad):
        return (
            inner.x - outer.x >= pad
            and inner.y - outer.y >= pad
            and outer.right - inner.right >= pad
            and outer.bottom - inner.bottom >= pad
        )

    for az in ("az-a1", "az-a2"):
        assert _inside(c[az], c["vpc-a"], le.CONTAINER_PAD), az
    for az in ("az-b1", "az-b2"):
        assert _inside(c[az], c["vpc-b"], le.CONTAINER_PAD), az
    for vpc in ("vpc-a", "vpc-b"):
        assert _inside(c[vpc], c["acct"], le.CONTAINER_PAD), vpc


def test_size_containers_peer_vpc_widths_equal():
    # Req 4.3: peer VPC bands are the same secondary-axis size, even when one
    # region's raw block is wider.
    for extra in (False, True):
        _, c = _sized(_landscape_spec(extra_b_slot=extra))
        assert c["vpc-a"].w == c["vpc-b"].w, extra


def test_size_containers_peer_az_widths_equal():
    # Req 4.3: matching AZ peers (az-a1/az-b1, az-a2/az-b2) are equal width.
    for extra in (False, True):
        _, c = _sized(_landscape_spec(extra_b_slot=extra))
        assert c["az-a1"].w == c["az-b1"].w, extra
        assert c["az-a2"].w == c["az-b2"].w, extra


def test_size_containers_account_wraps_all_bands_no_trailing_margin():
    # Req 4.5: the account envelope is exactly the child bands' bbox + PAD on
    # every side — no trailing empty margin.
    #
    # v1.6.0: the TOP pad is ``CONTAINER_PAD + CONTAINER_LABEL_BAND``. A draw.io
    # group draws its caption inside its own top edge, so a uniform pad left the
    # caption band and the top padding as the same strip and no corridor could
    # enter the container below its caption. The other three sides keep the bare
    # pad, so "no trailing margin" still holds where it is about trailing space.
    _, c = _sized(_landscape_spec())
    acct = c["acct"]
    bands = [c["vpc-a"], c["vpc-b"]]
    x0 = min(b.x for b in bands)
    y0 = min(b.y for b in bands)
    x1 = max(b.right for b in bands)
    y1 = max(b.bottom for b in bands)
    top_pad = le.CONTAINER_PAD + le.CONTAINER_LABEL_BAND
    assert acct.x == le._snap(x0 - le.CONTAINER_PAD)
    assert acct.y == le._snap(y0 - top_pad)
    assert acct.right == le._snap(x0 - le.CONTAINER_PAD) + le._snap((x1 - x0) + 2 * le.CONTAINER_PAD)
    assert acct.bottom == le._snap(y0 - top_pad) + le._snap((y1 - y0) + top_pad + le.CONTAINER_PAD)


def test_container_top_pad_reserves_the_caption_strip():
    """v1.6.0: every container's top padding clears its own caption band.

    The regression this locks in: with a uniform pad the caption band *was* the
    top padding, so the first content row began exactly where the caption ended
    and no horizontal corridor could enter the container legally — which is why
    four edges on the re-connected landscape ran along the ``vpc-…`` captions.
    """
    _, c = _sized(_landscape_spec())
    placed = le.place_nodes(_landscape_spec())
    for cid in ("acct", "vpc-a", "vpc-b", "az-a1", "az-a2"):
        box = c[cid]
        children = [b for b in list(c.values()) + list(placed.values())
                    if b.id != cid and le._box_contains(box, b)]
        if not children:
            continue
        top_child = min(b.y for b in children)
        assert top_child - box.y >= le.CONTAINER_PAD + le.CONTAINER_LABEL_BAND, (
            f"{cid}: top pad {top_child - box.y} does not reserve the caption strip"
        )


def test_size_containers_footprint_measured_with_label_band():
    # Req 4.1: the container bottom clears the deepest node's FOOTPRINT (icon +
    # LABEL_BAND), not the bare icon box — the label-aware geometry rule.
    _, c = _sized(_landscape_spec())
    placed = le.place_nodes(_landscape_spec())
    # Lowest node in az-a2 (region a, data tier).
    data_a = [placed[f"da{s}"] for s in range(2)]
    lowest_fp_bottom = max(b.footprint(le.LABEL_BAND).bottom for b in data_a)
    # az-a2 bottom must clear that footprint by >= PAD.
    assert c["az-a2"].bottom - lowest_fp_bottom >= le.CONTAINER_PAD


def test_centre_block_in_vpc_equal_left_right_padding_on_grid():
    # Req 3.4: each region's node block is centred in its VPC with equal
    # left/right (secondary-axis) padding, snapped to the grid.
    for extra in (False, True):
        spec = _landscape_spec(extra_b_slot=extra)
        placed, containers = _sized(spec)
        _, secondary = le._container_axes(spec)
        for region, vpc_id in (("a", "vpc-a"), ("b", "vpc-b")):
            members = [n.id for n in spec.nodes if n.region == region]
            fps = [placed[nid].footprint(le.LABEL_BAND) for nid in members]
            low = min(le._extent(f, secondary)[0] for f in fps)
            high = max(le._extent(f, secondary)[0] + le._extent(f, secondary)[1] for f in fps)
            v_low, v_size = le._extent(containers[vpc_id], secondary)
            left_pad = low - v_low
            right_pad = (v_low + v_size) - high
            # Equal padding to within one grid step (the centre delta is grid-rounded).
            assert abs(left_pad - right_pad) <= le.GRID, (region, extra, left_pad, right_pad)
            # Every node origin stays on the grid after the whole-block shift.
            for nid in members:
                assert placed[nid].x % le.GRID == 0
                assert placed[nid].y % le.GRID == 0


def test_centre_block_in_vpc_preserves_relative_geometry():
    # Req 3.4: the whole block shifts together, so internal spacing is intact.
    spec = _landscape_spec(extra_b_slot=True)
    placed_before = le.place_nodes(spec)
    containers = le.size_containers(placed_before, spec)
    placed_after = le.centre_block_in_vpc(placed_before, containers, spec)
    # Pairwise deltas within region a are unchanged by the block shift.
    a_ids = [n.id for n in spec.nodes if n.region == "a"]
    for i in range(len(a_ids)):
        for j in range(i + 1, len(a_ids)):
            p, q = a_ids[i], a_ids[j]
            before = (placed_before[p].x - placed_before[q].x, placed_before[p].y - placed_before[q].y)
            after = (placed_after[p].x - placed_after[q].x, placed_after[p].y - placed_after[q].y)
            assert before == after


def test_size_containers_is_deterministic():
    # Req 11.1 foundation: same spec → identical container boxes.
    spec = _landscape_spec(extra_b_slot=True)
    placed = le.place_nodes(spec)
    a = le.size_containers(placed, spec)
    b = le.size_containers(placed, spec)
    assert {k: (v.x, v.y, v.w, v.h) for k, v in a.items()} == {
        k: (v.x, v.y, v.w, v.h) for k, v in b.items()
    }


def test_size_containers_left_right_axis_equal_peer_size():
    # Req 4.3 on the left-right axis: the secondary (equal-width) axis is y, so
    # peer VPC bands share a common height. (The shipped landscape is
    # north-south; this only asserts the axis-generic equal-size + overlap
    # invariants, not the north-south-specific centring.)
    spec = _landscape_spec(axis="left-right", extra_b_slot=True)
    placed = le.place_nodes(spec)
    containers = le.size_containers(placed, spec)
    # secondary axis is 'y' → peer VPC heights equal, sibling bands disjoint.
    assert containers["vpc-a"].h == containers["vpc-b"].h
    assert check_container_overlap(_geo(placed, containers)) == []


def test_size_containers_empty_region_band_raises():
    # A vpc with no member nodes cannot be sized (fail-honest, names the id).
    spec = DiagramSpec(
        diagram_id="empty",
        diagram_name="empty",
        axis="north-south",
        nodes=(NodeSpec(id="w", role="fn", lane="workers", region="a", slot=0),),
        edges=(),
        containers=(
            ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
            ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct", label_key="vpc"),
            ContainerSpec(id="vpc-b", kind="vpc", region="b", parent="acct", label_key="vpc"),
        ),
        flow_lines=("Flow",),
        title="empty | 2025-01-15 | v1",
    )
    placed = le.place_nodes(spec)
    with pytest.raises(SpecError) as ei:
        le.size_containers(placed, spec)
    assert "vpc-b" in str(ei.value)


# ---------------------------------------------------------------------------
# Task 15: stack availability zones vertically with equal width
# (Req 12.1, 12.2, 12.5)
# ---------------------------------------------------------------------------


def _two_az_spec(region: str = "a") -> DiagramSpec:
    """A single-region VPC with two AZs whose nodes declare AZ membership.

    Both AZs reuse the SAME slot columns (slots 0..1 in the ``workers`` and
    ``data`` lanes) — nothing but the declared AZ membership distinguishes them,
    exactly like the shipped landscape. The engine must therefore stack them
    along the primary (tier) axis, not spread them side-by-side.
    """
    nodes = []
    for az in (1, 2):
        cid = f"az-{region}{az}"
        nodes.append(NodeSpec(id=f"app_{region}{az}", role="fn", lane="workers",
                              region=region, slot=0, container=cid))
        nodes.append(NodeSpec(id=f"api_{region}{az}", role="fn", lane="workers",
                              region=region, slot=1, container=cid))
        nodes.append(NodeSpec(id=f"db_{region}{az}", role="sql", lane="data",
                              region=region, slot=0, container=cid))
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id=f"vpc-{region}", kind="vpc", region=region, parent="acct", label_key="vpc"),
        ContainerSpec(id=f"az-{region}1", kind="az", region=region, parent=f"vpc-{region}", label_key="az"),
        ContainerSpec(id=f"az-{region}2", kind="az", region=region, parent=f"vpc-{region}", label_key="az"),
    )
    return DiagramSpec(
        diagram_id="two-az",
        diagram_name="two-az",
        axis="north-south",
        nodes=tuple(nodes),
        edges=(),
        containers=containers,
        flow_lines=("Flow",),
        title="two-az | 2026-09-23 | v1",
    )


def test_two_az_boxes_are_stacked_not_side_by_side():
    # Req 12.1/12.5: peer AZs of one VPC stack along the primary (tier) axis —
    # az-1 above az-2 for north-south — never side-by-side on the secondary axis.
    spec = _two_az_spec()
    placed, c = _sized(spec)
    a1, a2 = c["az-a1"], c["az-a2"]
    # Shared secondary-axis (x) range.
    assert a1.x == a2.x
    # Disjoint primary-axis (y) ranges, az-2 strictly below az-1.
    assert a2.y >= a1.bottom
    # az-1 is the upper band (north-south: account-edge row at top, descending).
    assert a1.y < a2.y


def test_two_az_boxes_are_equal_width():
    # Req 12.2: peer AZs of one VPC have equal secondary-axis size (width).
    _, c = _sized(_two_az_spec())
    assert c["az-a1"].w == c["az-a2"].w


def test_two_az_stacking_keeps_containers_clean():
    # Req 12.1/12.2: with the AZs stacked+equal-width, the container oracle stays
    # clean — no sibling overlap, and every node keeps its padding inside its box.
    spec = _two_az_spec()
    placed, c = _sized(spec)
    geo = _geo(placed, c)
    assert check_container_overlap(geo) == []
    assert check_container_padding(geo, pad=le.CONTAINER_PAD) == []


def test_two_az_stacking_mirrors_across_regions():
    # Req 12.2: the equal-width contract holds across regions too — all four AZ
    # boxes (both regions × two AZs) share one width, and each region's AZs share
    # that region's x-range.
    from rule_engine.ha_multiregion_spec import LANDSCAPE_SPEC

    pd = le.layout(LANDSCAPE_SPEC)
    c = pd.containers
    a1, a2 = c["boundary-az-a1"], c["boundary-az-a2"]
    b1, b2 = c["boundary-az-b1"], c["boundary-az-b2"]
    # Region A AZs share x-range; region B AZs share x-range.
    assert (a1.x, a1.w) == (a2.x, a2.w)
    assert (b1.x, b1.w) == (b2.x, b2.w)
    # All four AZ boxes have one common width (peer equal-width, mirrored).
    assert a1.w == b1.w == a2.w == b2.w
    # Stacked (a2 below a1, b2 below b1).
    assert a2.y >= a1.bottom and b2.y >= b1.bottom


# ---------------------------------------------------------------------------
# Task 16: VPC service-row tier above the availability zones
# (Req 12.3)
# ---------------------------------------------------------------------------


def _service_row_spec(region: str = "a") -> DiagramSpec:
    """A single-region VPC with a VPC-direct service row above two stacked AZs.

    The service-row nodes declare the VPC itself as their ``container`` (never an
    AZ), so they must form a distinct tier BETWEEN the VPC top border and the
    first AZ band. The AZ nodes declare AZ membership and reuse the same slot
    columns, exactly like the shipped landscape.
    """
    vpc = f"vpc-{region}"
    nodes = [
        # VPC-direct service row (lb / queue / fn / secrets) — container = the VPC.
        NodeSpec(id=f"lb_{region}", role="lb", lane="router", region=region, slot=0, container=vpc),
        NodeSpec(id=f"queue_{region}", role="queue", lane="async", region=region, slot=0, container=vpc),
        NodeSpec(id=f"fn_{region}", role="fn", lane="workers", region=region, slot=0, container=vpc),
        NodeSpec(id=f"sec_{region}", role="sec", lane="platform", region=region, slot=0, container=vpc),
    ]
    for az in (1, 2):
        cid = f"az-{region}{az}"
        nodes.append(NodeSpec(id=f"app_{region}{az}", role="fn", lane="workers",
                              region=region, slot=1, container=cid))
        nodes.append(NodeSpec(id=f"db_{region}{az}", role="sql", lane="data",
                              region=region, slot=0, container=cid))
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id=vpc, kind="vpc", region=region, parent="acct", label_key="vpc"),
        ContainerSpec(id=f"az-{region}1", kind="az", region=region, parent=vpc, label_key="az"),
        ContainerSpec(id=f"az-{region}2", kind="az", region=region, parent=vpc, label_key="az"),
    )
    return DiagramSpec(
        diagram_id="svc-row",
        diagram_name="svc-row",
        axis="north-south",
        nodes=tuple(nodes),
        edges=(),
        containers=containers,
        flow_lines=("Flow",),
        title="svc-row | 2026-09-23 | v1",
    )


def _box_contains(outer: Box, inner: Box) -> bool:
    """True when ``inner`` sits fully within ``outer`` (inclusive edges)."""
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and outer.right >= inner.right
        and outer.bottom >= inner.bottom
    )


def test_service_row_nodes_sit_above_first_az_and_inside_vpc():
    # Req 12.3: every VPC-direct service-row node's footprint sits ABOVE the
    # first AZ box's top and INSIDE the VPC — a distinct tier above the zones.
    spec = _service_row_spec()
    placed, c = _sized(spec)
    vpc = c["vpc-a"]
    first_az_top = min(c["az-a1"].y, c["az-a2"].y)
    for nid in ("lb_a", "queue_a", "fn_a", "sec_a"):
        fp = placed[nid].footprint(le.LABEL_BAND)
        assert fp.bottom <= first_az_top, nid          # above the first AZ band
        assert _box_contains(vpc, fp), nid             # inside the VPC


def test_no_az_box_contains_a_service_row_node():
    # Req 12.3: no AZ box wraps or overlaps a VPC service-row node's footprint —
    # each AZ box is sized from its own AZ children only.
    spec = _service_row_spec()
    placed, c = _sized(spec)
    for nid in ("lb_a", "queue_a", "fn_a", "sec_a"):
        fp = placed[nid].footprint(le.LABEL_BAND)
        for az_id in ("az-a1", "az-a2"):
            assert not _box_contains(c[az_id], fp), (az_id, nid)


def test_landscape_service_row_forms_a_tier_above_the_azs():
    # Req 12.3 on the shipped landscape: in each region every service-row node
    # sits above the first AZ box and inside its VPC, and no AZ box contains one.
    from rule_engine.ha_multiregion_spec import LANDSCAPE_SPEC

    pd = le.layout(LANDSCAPE_SPEC)
    c, n = pd.containers, pd.nodes
    per_region = {
        "a": (["lb_a", "queue_a", "fn_a", "sec_a"],
              "boundary-vpc-a", ["boundary-az-a1", "boundary-az-a2"]),
        "b": (["lb_b", "queue_b", "fn_b", "sec_b"],
              "boundary-vpc-b", ["boundary-az-b1", "boundary-az-b2"]),
    }
    for svc_ids, vpc_id, az_ids in per_region.values():
        vpc = c[vpc_id]
        first_az_top = min(c[a].y for a in az_ids)
        for nid in svc_ids:
            fp = n[nid].footprint(le.LABEL_BAND)
            assert fp.bottom <= first_az_top, nid
            assert _box_contains(vpc, fp), nid
            for a in az_ids:
                assert not _box_contains(c[a], fp), (a, nid)


# ---------------------------------------------------------------------------
# Task 4: contact-point selection (exit/entry ladder) + fan-out spread
# (Req 5.1, 5.2, 5.3, 5.4, 5.5)
# ---------------------------------------------------------------------------

from rule_engine.geometry import (
    EdgeGeom,
    check_edge_direction,
    check_edge_float,
    check_exit_thirds,
)
from rule_engine.layout_engine import (
    MERGE_THRESHOLD,
    OverConnectedError,
    select_contacts,
    spread_contacts,
)


def _two_node_placed(a_xy, b_xy, size=None):
    """Return a ``{id: Box}`` map with a source ``s`` and target ``t``."""
    s = size or le.ICON_SIZE
    ax, ay = a_xy
    bx, by = b_xy
    return {
        "s": Box("s", ax, ay, s, s),
        "t": Box("t", bx, by, s, s),
    }


def _edge(source="s", target="t", eid="e"):
    return EdgeSpec(id=eid, source=source, target=target, marker="1")


def _edge_geom(eid, source, target, exit_pt, entry_pt):
    """Build an EdgeGeom carrying explicit contact points for the oracle."""
    return EdgeGeom(
        id=eid,
        source=source,
        target=target,
        orthogonal=True,
        exit=exit_pt,
        entry=entry_pt,
    )


# --- Exit ladder branches ---------------------------------------------------


def test_select_contacts_right_centre_for_adjacent_same_row_target():
    # Req 5.1 branch 1: target directly opposite on the same row, adjacent.
    placed = _two_node_placed((100, 100), (100 + le.COL_STEP, 100))
    exit_pt, entry_pt = select_contacts(_edge(), placed)
    assert exit_pt == (1.0, 0.5)      # right-centre (straight line)
    assert entry_pt == (0.0, 0.5)     # left-centre


def test_select_contacts_right_centre_for_target_directly_below():
    # Rule A: a target directly below is reached by exiting the RIGHT face (never
    # the bottom — a bottom stub crosses the node's own caption) and descending
    # via a side corridor into the target's TOP.
    placed = _two_node_placed((100, 100), (100, 100 + le.ROW_STEP))
    exit_pt, entry_pt = select_contacts(_edge(), placed)
    assert exit_pt == (1.0, 0.5)      # right-centre (Rule A: never bottom)
    assert entry_pt == (0.5, 0.0)     # top-centre (descends into the target)


def test_select_contacts_single_exit_is_right_CENTRE_regardless_of_target_dir():
    # A single edge always exits the right CENTRE (0.5). The off-centre quarter
    # is applied later, only when 2+ edges share the side (spread_contacts) —
    # select_contacts no longer pre-shifts.
    # Target ABOVE (arrives horizontally) → enter the LEFT-centre.
    placed = _two_node_placed((100, 400), (100 + 3 * le.COL_STEP, 100))
    exit_pt, entry_pt = select_contacts(_edge(), placed)
    assert exit_pt == (1.0, 0.5)
    assert entry_pt == (0.0, 0.5)
    # Target BELOW (arrives descending) → enter the TOP-centre, so the run drops
    # into the lower target rather than running along its row's centre line.
    placed = _two_node_placed((100, 100), (100 + 3 * le.COL_STEP, 400))
    exit_pt, entry_pt = select_contacts(_edge(), placed)
    assert exit_pt == (1.0, 0.5)
    assert entry_pt == (0.5, 0.0)


def test_select_contacts_never_exits_bottom_even_when_obstructed():
    # Rule A holds regardless of obstacles: the exit is always the right face,
    # never a bottom stub. A single edge keeps the right CENTRE.
    placed = _two_node_placed((100, 100), (100, 100 + 2 * le.ROW_STEP))
    placed["obs"] = Box("obs", 100, 100 + le.ROW_STEP, le.ICON_SIZE, le.ICON_SIZE)
    exit_pt, _ = select_contacts(_edge(), placed)
    assert exit_pt[0] == 1.0                    # right face, never bottom
    assert exit_pt == (1.0, 0.5)                # single edge → centre


# --- Every emitted contact obeys the directional contract + is explicit -----


def test_select_contacts_all_branches_pass_direction_and_float_oracles():
    # Req 5.5: exit leans right/bottom, entry leans left/top, both explicit.
    scenarios = [
        _two_node_placed((100, 100), (100 + le.COL_STEP, 100)),            # right-centre
        _two_node_placed((100, 100), (100, 100 + le.ROW_STEP)),            # bottom-centre
        _two_node_placed((100, 400), (100 + 3 * le.COL_STEP, 100)),        # upper third
        _two_node_placed((100, 100), (100 + 3 * le.COL_STEP, 400)),        # lower third
    ]
    for i, placed in enumerate(scenarios):
        exit_pt, entry_pt = select_contacts(_edge(eid=f"e{i}"), placed)
        geo = DiagramGeometry(
            nodes=placed,
            edges=[_edge_geom(f"e{i}", "s", "t", exit_pt, entry_pt)],
        )
        assert check_edge_direction(geo) == [], i
        assert check_edge_float(geo) == [], i


# --- Fan-out spread ---------------------------------------------------------


def test_spread_contacts_single_edge_unchanged():
    edges = [("e0", (1.0, 0.5))]
    assert spread_contacts(edges) == edges


def test_spread_contacts_two_edges_distinct_and_apart():
    edges = [("e0", (1.0, 0.5)), ("e1", (1.0, 0.5))]
    out = spread_contacts(edges)
    ys = sorted(pt[1] for _, pt in out)
    # Distinct, >= merge threshold apart, both stay on the right face (fx=1.0).
    assert ys[1] - ys[0] >= MERGE_THRESHOLD
    assert all(pt[0] == 1.0 for _, pt in out)


def test_spread_contacts_three_edges_pass_check_exit_thirds():
    # Req 5.3: a fan-out of three on one side passes check_exit_thirds.
    placed = {"s": Box("s", 100, 300, le.ICON_SIZE, le.ICON_SIZE)}
    raw = [("e0", (1.0, 0.5)), ("e1", (1.0, 0.5)), ("e2", (1.0, 0.5))]
    out = spread_contacts(raw)
    # Build a geometry with three edges leaving s on the right, at the spread ys.
    edges = [_edge_geom(eid, "s", f"t{i}", pt, (0.0, 0.5)) for i, (eid, pt) in enumerate(out)]
    for i, (eid, pt) in enumerate(out):
        placed[f"t{i}"] = Box(f"t{i}", 800, 100 + i * 160, le.ICON_SIZE, le.ICON_SIZE)
    geo = DiagramGeometry(nodes=placed, edges=edges)
    assert check_exit_thirds(geo) == []


def test_spread_contacts_straight_line_edge_keeps_the_centre():
    # Req 5.3: an edge whose exit is the centre (straight-line) stays on 0.5.
    edges = [("e0", (1.0, 0.5)), ("e1", (1.0, 0.5)), ("e2", (1.0, 0.5))]
    out = dict(spread_contacts(edges))
    # At least one edge keeps the centre band; here e0 (first centre) is pinned.
    assert any(abs(pt[1] - 0.5) < 1e-9 for pt in out.values())


def test_spread_contacts_preserves_bottom_face_band_axis():
    # A bottom-face fan-out spreads along fx (fy stays at 1.0).
    edges = [("e0", (0.5, 1.0)), ("e1", (0.5, 1.0))]
    out = spread_contacts(edges)
    xs = sorted(pt[0] for _, pt in out)
    assert xs[1] - xs[0] >= MERGE_THRESHOLD
    assert all(pt[1] == 1.0 for _, pt in out)


def test_spread_contacts_fourth_same_side_edge_raises():
    # Req 5.4: a fourth edge on one side is over-connected → raise.
    edges = [("e0", (1.0, 0.5)), ("e1", (1.0, 0.5)),
             ("e2", (1.0, 0.5)), ("e3", (1.0, 0.5))]
    with pytest.raises(OverConnectedError) as ei:
        spread_contacts(edges)
    assert "right" in str(ei.value)


def test_spread_contacts_three_edges_all_pass_direction_and_float():
    # Req 5.5: the spread contacts still obey the directional contract + explicit.
    raw = [("e0", (1.0, 0.5)), ("e1", (1.0, 0.5)), ("e2", (1.0, 0.5))]
    out = spread_contacts(raw)
    placed = {"s": Box("s", 100, 300, le.ICON_SIZE, le.ICON_SIZE)}
    edges = []
    for i, (eid, pt) in enumerate(out):
        placed[f"t{i}"] = Box(f"t{i}", 800, 100 + i * 160, le.ICON_SIZE, le.ICON_SIZE)
        edges.append(_edge_geom(eid, "s", f"t{i}", pt, (0.0, 0.5)))
    geo = DiagramGeometry(nodes=placed, edges=edges)
    assert check_edge_direction(geo) == []
    assert check_edge_float(geo) == []


# ---------------------------------------------------------------------------
# Task 5: corridor allocator (Req 6.1, 6.2, 6.3, 6.4)
# ---------------------------------------------------------------------------

from rule_engine.geometry import check_corridor_sharing
from rule_engine.layout_engine import (
    CorridorAllocator,
    CorridorExhaustedError,
)


def test_corridor_lines_are_grid_aligned_and_inside_the_gap():
    # Req 6.2: every corridor line is a whole GRID multiple, strictly inside the
    # gap. A column gap between x=100 and x=100+COL_STEP is inset one GRID off the
    # left glyph → (100+ICON_SIZE+GRID, 320) so the first lane clears the icon.
    alloc = CorridorAllocator()
    low, high = alloc.column_gap(100, 100 + le.COL_STEP)
    assert (low, high) == (100 + le.ICON_SIZE + le.GRID, 100 + le.COL_STEP)
    cap = alloc.register_gap("col:0-1", low, high)
    assert cap >= 2
    lines = [alloc.allocate("col:0-1", low, high) for _ in range(cap)]
    for ln in lines:
        assert ln % le.GRID == 0          # whole GRID multiple (Req 6.2)
        assert low < ln < high            # strictly inside the gap


def test_distinct_requests_get_distinct_grid_aligned_lines():
    # Req 6.1: each edge segment in a shared gap gets its own line, >= 1 GRID apart.
    alloc = CorridorAllocator()
    low, high = alloc.column_gap(0, 0 + le.COL_STEP)
    a = alloc.allocate("col:0-1", low, high)
    b = alloc.allocate("col:0-1", low, high)
    c = alloc.allocate("col:0-1", low, high)
    lines = [a, b, c]
    assert len(set(lines)) == 3                       # all distinct
    ordered = sorted(lines)
    assert all(y - x >= le.GRID for x, y in zip(ordered, ordered[1:]))


def test_lines_handed_out_low_to_high_deterministically():
    # Req 11.1: same request sequence -> same assignment, low->high order.
    low, high = CorridorAllocator.column_gap(0, le.COL_STEP)
    a1 = CorridorAllocator()
    seq_a = [a1.allocate("g", low, high) for _ in range(3)]
    a2 = CorridorAllocator()
    seq_b = [a2.allocate("g", low, high) for _ in range(3)]
    assert seq_a == seq_b                 # deterministic
    assert seq_a == sorted(seq_a)         # ascending (low->high)


def test_separate_gaps_have_independent_occupancy():
    alloc = CorridorAllocator()
    low1, high1 = alloc.column_gap(0, le.COL_STEP)
    low2, high2 = alloc.column_gap(1000, 1000 + le.COL_STEP)
    a = alloc.allocate("col:0-1", low1, high1)
    b = alloc.allocate("col:9-10", low2, high2)
    # Different gaps track occupancy independently; the first gap still has room.
    assert alloc.capacity("col:0-1") >= 1
    assert alloc.capacity("col:9-10") >= 1


def test_row_gap_allocates_grid_aligned_horizontal_corridors():
    # Req 6.1/6.2 on the inter-row axis (over/under-row corridors).
    alloc = CorridorAllocator()
    low, high = alloc.row_gap(200, 200 + le.ROW_STEP)
    # The gap low is inset by one GRID off the icon edge so the first lane clears
    # the glyph (the step-out padding fix).
    assert (low, high) == (200 + le.ICON_SIZE + le.GRID, 200 + le.ROW_STEP)
    y0 = alloc.allocate("row:edge-router", low, high)
    y1 = alloc.allocate("row:edge-router", low, high)
    assert y0 % le.GRID == 0 and y1 % le.GRID == 0
    assert abs(y1 - y0) >= le.GRID


def test_two_unrelated_long_edges_on_allocated_lines_pass_check_corridor_sharing():
    # Req 6.3: two unrelated long edges routed through distinct allocated
    # corridor lines pass the real check_corridor_sharing oracle.
    alloc = CorridorAllocator()
    # A wide inter-column gap so it holds >= 2 corridor lines with room to spare.
    low, high = 100, 100 + 4 * le.GRID
    xa = alloc.allocate("col:mid", low, high)
    xb = alloc.allocate("col:mid", low, high)
    assert xa != xb

    # Four source/target nodes: edges e_a and e_b are UNRELATED (no shared
    # endpoint). Each runs a long VERTICAL segment down its own allocated x line.
    size = le.ICON_SIZE
    nodes = {
        "sa": Box("sa", 0, 100, size, size),
        "ta": Box("ta", 500, 700, size, size),
        "sb": Box("sb", 0, 900, size, size),
        "tb": Box("tb", 500, 1500, size, size),
    }
    # Each edge: exit right of source, drop the long vertical run on its own
    # allocated corridor x, then into the target. The vertical extents overlap in
    # y, so sharing an x line WOULD collide — distinct lines keep them clean.
    edge_a = EdgeGeom(
        id="e_a", source="sa", target="ta", orthogonal=True,
        exit=(1.0, 0.5), entry=(0.0, 0.5),
        points=[(xa, 100 + size / 2), (xa, 700 + size / 2)],
    )
    edge_b = EdgeGeom(
        id="e_b", source="sb", target="tb", orthogonal=True,
        exit=(1.0, 0.5), entry=(0.0, 0.5),
        points=[(xb, 900 + size / 2), (xb, 1500 + size / 2)],
    )
    geo = DiagramGeometry(nodes=nodes, edges=[edge_a, edge_b])
    assert check_corridor_sharing(geo) == []


def test_two_unrelated_edges_sharing_one_line_are_flagged_control():
    # Control: the same two unrelated edges DO collide when forced onto one x
    # line — proves the previous test's clean result is due to distinct lines,
    # not a toothless oracle.
    size = le.ICON_SIZE
    shared_x = 150
    nodes = {
        "sa": Box("sa", 0, 100, size, size),
        "ta": Box("ta", 500, 700, size, size),
        "sb": Box("sb", 0, 300, size, size),
        "tb": Box("tb", 500, 900, size, size),
    }
    edge_a = EdgeGeom(
        id="e_a", source="sa", target="ta", orthogonal=True,
        exit=(1.0, 0.5), entry=(0.0, 0.5),
        points=[(shared_x, 100 + size / 2), (shared_x, 700 + size / 2)],
    )
    edge_b = EdgeGeom(
        id="e_b", source="sb", target="tb", orthogonal=True,
        exit=(1.0, 0.5), entry=(0.0, 0.5),
        points=[(shared_x, 300 + size / 2), (shared_x, 900 + size / 2)],
    )
    geo = DiagramGeometry(nodes=nodes, edges=[edge_a, edge_b])
    assert check_corridor_sharing(geo) == [("e_a", "e_b")]


def test_exhausting_a_gap_raises_the_widen_signal():
    # Req 6.4: when a gap runs out of grid-aligned lines, allocate raises the
    # "needs widen" signal (CorridorExhaustedError), naming the gap.
    alloc = CorridorAllocator()
    # A narrow gap holding exactly one interior grid line: (100, 100+2*GRID) ->
    # only 100+GRID is strictly inside.
    low, high = 100, 100 + 2 * le.GRID
    cap = alloc.register_gap("tight", low, high)
    assert cap == 1
    first = alloc.allocate("tight", low, high)
    assert first == 100 + le.GRID
    with pytest.raises(CorridorExhaustedError) as ei:
        alloc.allocate("tight", low, high)
    assert "tight" in str(ei.value)


def test_a_gap_with_no_interior_grid_line_is_immediately_exhausted():
    # A gap narrower than one GRID step has zero corridor lines -> widen at once.
    alloc = CorridorAllocator()
    low, high = 101, 109                  # no whole-GRID multiple strictly inside
    assert alloc.register_gap("razor", low, high) == 0
    with pytest.raises(CorridorExhaustedError):
        alloc.allocate("razor", low, high)


def test_widen_repair_refreshes_free_lines_preserving_taken():
    # After the "needs widen" signal, re-registering the gap wider adds new free
    # lines while the already-handed-out line stays taken (repair-loop contract).
    alloc = CorridorAllocator()
    low, high = 100, 100 + 2 * le.GRID     # capacity 1
    taken = alloc.allocate("g", low, high)
    with pytest.raises(CorridorExhaustedError):
        alloc.allocate("g", low, high)
    # Widen the gap by one COL_STEP and retry.
    new_low, new_high = 100, 100 + 5 * le.GRID
    cap = alloc.register_gap("g", new_low, new_high)
    assert cap >= 1
    nxt = alloc.allocate("g", new_low, new_high)
    assert nxt != taken                    # the widened line is a fresh one
    assert nxt % le.GRID == 0


# ---------------------------------------------------------------------------
# Task 6: edge classifier and per-class routers (Req 7.1–7.8)
# ---------------------------------------------------------------------------

from rule_engine.geometry import check_edge_routing, segment_crosses_box
from rule_engine.layout_engine import (
    CROSS_REGION_SPAN,
    EDGE_KINDS,
    UnclassifiableEdgeError,
    classify_edge,
    route_back_edge,
    route_cross_region,
    route_edge,
    route_fan_out_row,
    route_spine,
    route_straight,
)

_S = le.ICON_SIZE
_C = le.COL_STEP
_R = le.ROW_STEP


def _placed(*boxes):
    return {b.id: b for b in boxes}


def _spec_edge(source, target, eid="e"):
    return EdgeSpec(id=eid, source=source, target=target, marker="1")


def _routed_geo(edge, exit_pt, entry_pt, waypoints, placed):
    """Build a DiagramGeometry from a routed edge so the oracle can judge it."""
    return DiagramGeometry(
        nodes=placed,
        edges=[
            EdgeGeom(
                id=edge.id,
                source=edge.source,
                target=edge.target,
                orthogonal=True,
                exit=exit_pt,
                entry=entry_pt,
                points=waypoints,
            )
        ],
    )


def _first_wp_moves_both_axes(src, exit_pt, waypoints):
    """True when the first waypoint changes BOTH axes off the exit point."""
    ex = src.x + exit_pt[0] * src.w
    ey = src.y + exit_pt[1] * src.h
    return bool(waypoints) and waypoints[0][0] != ex and waypoints[0][1] != ey


# --- classifier -------------------------------------------------------------


def test_classify_straight_same_row_adjacent():
    placed = _placed(Box("s", 100, 100, _S, _S), Box("t", 100 + _C, 100, _S, _S))
    assert classify_edge(_spec_edge("s", "t"), placed) == "straight"


def test_classify_spine_tier_hop_within_region():
    # Different row, next column to the right → a tier hop (spine).
    placed = _placed(Box("s", 100, 100, _S, _S), Box("t", 100 + _C, 100 + _R, _S, _S))
    assert classify_edge(_spec_edge("s", "t"), placed) == "spine"


def test_classify_fan_out_row_same_row_non_adjacent():
    # Same row, to the right, nearer than a region block → fan-out-row.
    placed = _placed(Box("s", 100, 100, _S, _S), Box("t", 100 + 2 * _C, 100, _S, _S))
    assert classify_edge(_spec_edge("s", "t"), placed) == "fan-out-row"


def test_classify_cross_region_far_same_tier():
    # A whole region block to the right at the same tier → cross-region.
    placed = _placed(
        Box("s", 100, 400, _S, _S),
        Box("t", 100 + CROSS_REGION_SPAN, 400, _S, _S),
    )
    assert classify_edge(_spec_edge("s", "t"), placed) == "cross-region"


def test_classify_back_edge_target_left_of_source():
    placed = _placed(
        Box("s", 100 + 3 * _C, 100, _S, _S),
        Box("t", 100, 100 + _R, _S, _S),
    )
    assert classify_edge(_spec_edge("s", "t"), placed) == "back-edge"


def test_classify_kind_hint_overrides_derivation():
    # A valid kind_hint wins over the geometric derivation (design.md).
    placed = _placed(Box("s", 100, 100, _S, _S), Box("t", 100 + _C, 100, _S, _S))
    edge = EdgeSpec(id="e", source="s", target="t", marker="1", kind_hint="spine")
    assert classify_edge(edge, placed) == "spine"


def test_classify_unknown_kind_hint_raises():
    placed = _placed(Box("s", 100, 100, _S, _S), Box("t", 100 + _C, 100, _S, _S))
    edge = EdgeSpec(id="e", source="s", target="t", marker="1", kind_hint="teleport")
    with pytest.raises(UnclassifiableEdgeError) as ei:
        classify_edge(edge, placed)
    assert "teleport" in str(ei.value)


def test_classify_unclassifiable_edge_raises_fail_honest():
    # Coincident boxes (dx=0, dy=0) match no class → raise, never guess (Req 7.1).
    placed = _placed(Box("s", 100, 100, _S, _S), Box("t", 100, 100, _S, _S))
    with pytest.raises(UnclassifiableEdgeError) as ei:
        classify_edge(_spec_edge("s", "t"), placed)
    assert "e" in str(ei.value) and EDGE_KINDS[0] in str(ei.value)


# --- per-class router shape + no-obstacle-crossing --------------------------


def test_route_straight_emits_single_centred_segment():
    # Req 7.2: a straight edge needs no interior waypoint (the pinned exit/entry
    # already draw the single centred segment), and crosses nothing.
    src = Box("s", 100, 100, _S, _S)
    tgt = Box("t", 100 + _C, 100, _S, _S)
    placed = _placed(src, tgt)
    edge = _spec_edge("s", "t")
    exit_pt, entry_pt = select_contacts(edge, placed)
    wps = route_straight(edge, exit_pt, entry_pt, CorridorAllocator(), [src, tgt])
    assert wps == []
    geo = _routed_geo(edge, exit_pt, entry_pt, wps, placed)
    assert check_edge_routing(geo) == []


def test_route_spine_uses_side_corridor_and_crosses_no_obstacle():
    # Req 7.3: exit right, drop in a side corridor beside the column, enter top.
    src = Box("s", 100, 100, _S, _S)
    tgt = Box("t", 100 + _C, 100 + _R, _S, _S)
    placed = _placed(src, tgt)
    edge = _spec_edge("s", "t")
    exit_pt, entry_pt = select_contacts(edge, placed)
    wps = route_spine(edge, exit_pt, entry_pt, CorridorAllocator(), [src, tgt])
    assert wps  # spine emits interior waypoints
    assert _first_wp_moves_both_axes(src, exit_pt, wps)  # no axis collapse (Req 7.7)
    geo = _routed_geo(edge, exit_pt, entry_pt, wps, placed)
    assert check_edge_routing(geo) == []


def test_route_fan_out_row_owns_below_row_lane_and_turns_up_before_target():
    # Req 7.4: own below-row lane, turn up in the gap just before the target;
    # crosses no intervening icon (an obstacle sits on the row between s and t).
    src = Box("s", 100, 100, _S, _S)
    mid = Box("m", 100 + _C, 100, _S, _S)   # intervening same-row icon
    tgt = Box("t", 100 + 2 * _C, 100, _S, _S)
    placed = _placed(src, mid, tgt)
    edge = _spec_edge("s", "t")
    exit_pt, entry_pt = select_contacts(edge, placed)
    wps = route_fan_out_row(edge, exit_pt, entry_pt, CorridorAllocator(), [src, mid, tgt])
    assert wps
    assert _first_wp_moves_both_axes(src, exit_pt, wps)
    geo = _routed_geo(edge, exit_pt, entry_pt, wps, placed)
    assert check_edge_routing(geo) == []       # does not cut the mid icon


def test_route_cross_region_rises_into_over_row_corridor_and_crosses_nothing():
    # Req 7.5: step out, own over-row corridor, across, enter target top.
    src = Box("s", 100, 400, _S, _S)
    tgt = Box("t", 100 + CROSS_REGION_SPAN, 400, _S, _S)
    placed = _placed(src, tgt)
    edge = _spec_edge("s", "t")
    exit_pt, entry_pt = select_contacts(edge, placed)
    wps = route_cross_region(edge, exit_pt, entry_pt, CorridorAllocator(), [src, tgt])
    assert wps
    assert _first_wp_moves_both_axes(src, exit_pt, wps)
    geo = _routed_geo(edge, exit_pt, entry_pt, wps, placed)
    assert check_edge_routing(geo) == []


def test_route_back_edge_exits_right_and_enters_left():
    # Req 7.6: target left of source → exit right, loop corridor, enter left.
    src = Box("s", 100 + 3 * _C, 100, _S, _S)
    tgt = Box("t", 100, 100 + _R, _S, _S)
    placed = _placed(src, tgt)
    edge = _spec_edge("s", "t")
    exit_pt, entry_pt = select_contacts(edge, placed)
    # exit leans right, entry leans left (never exit the side it enters).
    assert exit_pt[0] >= 0.5
    assert entry_pt[0] <= 0.5
    wps = route_back_edge(edge, exit_pt, entry_pt, CorridorAllocator(), [src, tgt])
    assert wps
    assert _first_wp_moves_both_axes(src, exit_pt, wps)
    geo = _routed_geo(edge, exit_pt, entry_pt, wps, placed)
    assert check_edge_routing(geo) == []


# --- dispatch + waypoints land on the grid ----------------------------------


def test_route_edge_dispatches_by_class_and_matches_direct_router():
    # route_edge classifies then dispatches to the matching route_<kind>.
    src = Box("s", 100, 100, _S, _S)
    tgt = Box("t", 100 + _C, 100 + _R, _S, _S)   # spine
    placed = _placed(src, tgt)
    edge = _spec_edge("s", "t")
    exit_pt, entry_pt = select_contacts(edge, placed)
    alloc = CorridorAllocator()
    via_dispatch = route_edge(edge, exit_pt, entry_pt, alloc, [src, tgt])
    direct = route_spine(edge, exit_pt, entry_pt, CorridorAllocator(), [src, tgt])
    assert via_dispatch == direct


def test_route_edge_unclassifiable_raises():
    # route_edge never guesses a route for an unclassifiable edge (Req 7.1).
    src = Box("s", 100, 100, _S, _S)
    tgt = Box("t", 100, 100, _S, _S)
    edge = _spec_edge("s", "t")
    with pytest.raises(UnclassifiableEdgeError):
        route_edge(edge, (1.0, 0.5), (0.0, 0.5), CorridorAllocator(), [src, tgt])


def test_routed_waypoints_are_grid_aligned():
    # Req 11.4: every emitted waypoint coordinate is a whole GRID multiple.
    src = Box("s", 100, 100, _S, _S)
    tgt = Box("t", 100 + _C, 100 + _R, _S, _S)
    edge = _spec_edge("s", "t")
    exit_pt, entry_pt = select_contacts(edge, _placed(src, tgt))
    wps = route_spine(edge, exit_pt, entry_pt, CorridorAllocator(), [src, tgt])
    for x, y in wps:
        assert x % le.GRID == 0 and y % le.GRID == 0


def test_router_obstacle_test_is_the_same_predicate_as_the_oracle():
    # The router reuses geometry.segment_crosses_box — the exact predicate
    # check_edge_routing samples with — so router and oracle agree (Req 7.7).
    box = Box("o", 200, 200, _S, _S)
    # A segment through the box centre is a crossing; one well clear is not.
    assert segment_crosses_box((200, 200 + _S / 2), (400, 200 + _S / 2), box)
    assert not segment_crosses_box((200, 0), (400, 0), box)


def test_segment_sampling_catches_thin_obstacle_on_a_long_run():
    """A 78px icon sitting in the middle of a multi-thousand-pixel horizontal
    run must be detected. The old fixed 61-sample density spaced samples wider
    than the icon on such a run, missing it (false-negative crossing); the
    fixed-step sampling keeps the density constant so it is caught."""
    box = Box("far", 1700, 500 - _S / 2, _S, _S)  # centred on y=500
    # A 3400px run straight through the box centre.
    assert segment_crosses_box((0, 500), (3400, 500), box)
    # A parallel run one row above (clears the box) is not a crossing.
    assert not segment_crosses_box((0, 300), (3400, 300), box)


# ---------------------------------------------------------------------------
# Task 7 — right-margin Flow/Legend placement (Req 8)
# ---------------------------------------------------------------------------

from rule_engine.layout_engine import place_legend, LEGEND_W


def _boxes_overlap(a: Box, b: Box) -> bool:
    """True when two rectangles intersect (touching edges do NOT overlap)."""
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


def _legend_boxes(legend_x: int, legend_w: int, flow_lines) -> list:
    """Build the two placed Flow/Legend boxes the way ``build_diagram`` does.

    Reuses ``build_diagram``'s own wrap-aware ``_text_h`` height for the pinned
    narrow width, and the standard right-margin y offsets, so the boxes match
    what actually ships to the assembler."""
    from rule_engine import diagram_layout as dl

    def _chars_per_line(width: int) -> int:
        return max(1, int((width - 2 * dl.GRID) / 5.6))

    def _text_h(lines, width):
        cpl = _chars_per_line(width)
        visual = sum(max(1, -(-len(s) // cpl)) for s in lines)
        return visual * 16 + 2 * dl.GRID

    flow_y, legend_y = 120, 460
    flow_h = _text_h(list(flow_lines), legend_w)
    legend_h = _text_h(list(dl.STANDARD_LEGEND_LINES), legend_w)
    return [
        Box("flow-legend", legend_x, flow_y, legend_w, flow_h),
        Box("legend", legend_x, legend_y, legend_w, legend_h),
    ]


def test_place_legend_x_is_past_the_account_box():
    # Req 8.1: legend_x = account.right + CONTAINER_PAD, at least one pad step
    # past the outermost container's right edge.
    _, containers = _sized(_landscape_spec(extra_b_slot=True))
    acct = containers["acct"]
    legend_x, legend_w = place_legend(acct, ("Flow", "1. step"))
    assert legend_x == le._snap(acct.right + le.CONTAINER_PAD)
    assert legend_x >= acct.right + le.CONTAINER_PAD
    assert legend_w == LEGEND_W


def test_place_legend_width_is_pinned_narrow():
    # Req 8.2: the width is a fixed narrow value (blocks wrap taller, not wider).
    _, containers = _sized(_landscape_spec())
    _, legend_w = place_legend(containers["acct"], ("Flow",))
    assert legend_w == LEGEND_W
    assert legend_w % le.GRID == 0


def test_place_legend_returns_grid_aligned_integers():
    # Req 11.4: emitted coordinates are whole GRID multiples.
    _, containers = _sized(_landscape_spec(extra_b_slot=True))
    legend_x, legend_w = place_legend(containers["acct"], ("Flow",))
    assert isinstance(legend_x, int) and isinstance(legend_w, int)
    assert legend_x % le.GRID == 0 and legend_w % le.GRID == 0


def test_place_legend_blocks_do_not_overlap_any_node_or_container():
    # Req 8.3: the Flow/Legend blocks overlap no node box and no container box.
    for extra in (False, True):
        spec = _landscape_spec(extra_b_slot=extra)
        placed, containers = _sized(spec)
        legend_x, legend_w = place_legend(containers["acct"], spec.flow_lines)
        legend_boxes = _legend_boxes(legend_x, legend_w, spec.flow_lines)
        for lb in legend_boxes:
            for nid, nb in placed.items():
                assert not _boxes_overlap(lb, nb), (extra, lb.id, nid)
            for cid, cb in containers.items():
                assert not _boxes_overlap(lb, cb), (extra, lb.id, cid)


def test_place_legend_blocks_do_not_overlap_each_other():
    # Req 8.3: the Flow and Legend blocks do not overlap each other.
    _, containers = _sized(_landscape_spec(extra_b_slot=True))
    legend_x, legend_w = place_legend(containers["acct"], ("Flow", "1. a", "2. b"))
    flow_box, legend_box = _legend_boxes(
        legend_x, legend_w, ("Flow", "1. a", "2. b")
    )
    assert not _boxes_overlap(flow_box, legend_box)


def test_place_legend_is_deterministic():
    # Req 11.1 foundation: same account box → identical placement.
    _, containers = _sized(_landscape_spec(extra_b_slot=True))
    acct = containers["acct"]
    assert place_legend(acct, ("Flow",)) == place_legend(acct, ("Flow",))


# ---------------------------------------------------------------------------
# Task 8: oracle adapter and repair loop (Req 9.1, 9.2, 9.3, 9.4, 11.1, 11.4)
# ---------------------------------------------------------------------------

from rule_engine.layout_engine import (
    MAX_REPAIR_ITERS,
    LayoutError,
    PlacedDiagram,
    PlacedEdge,
    _place_and_route,
    _repair,
    _run_oracle,
    layout,
)


def test_layout_colliding_candidate_repaired_to_zero_blocking():
    # Req 9.1/9.2: a candidate with a deliberate container-padding collision is
    # repaired (grow the container) until the oracle reports zero blocking
    # findings.
    spec = _landscape_spec()
    cand = _place_and_route(spec)

    # Deliberately shrink a leaf AZ container so its border clips its child
    # nodes' footprints (a blocking container-padding finding on landscape).
    az = cand.containers["az-a2"]
    shrunk = le.Box(az.id, az.x + 2 * le.GRID, az.y + 2 * le.GRID,
                    az.w - 4 * le.GRID, az.h - 4 * le.GRID)
    broken = PlacedDiagram(
        spec=cand.spec,
        nodes=cand.nodes,
        containers={**cand.containers, "az-a2": shrunk},
        edges=cand.edges,
        legend_x=cand.legend_x,
        legend_w=cand.legend_w,
    )

    before = _run_oracle(broken)
    assert not before.clean                      # the collision is detected
    assert any(r == "container-padding" for r, _ in before.blocking)

    # Drive the bounded repair loop by hand until clean.
    repaired = broken
    findings = before
    for _ in range(MAX_REPAIR_ITERS):
        if findings.clean:
            break
        repaired = _repair(repaired, findings)
        findings = _run_oracle(repaired)
    assert findings.clean                          # zero blocking findings (Req 9.3)


def test_layout_unfixable_candidate_raises():
    # Req 9.3: a candidate with a blocking finding the engine knows no repair for
    # (two node footprints overlapping) fails with a LayoutError, rather than
    # nudging forever.
    spec = _landscape_spec()
    cand = _place_and_route(spec)

    # Force two nodes onto the same origin → their footprints overlap
    # (node-overlap is blocking and unfixable).
    victim = list(cand.nodes)[1]
    anchor = cand.nodes[list(cand.nodes)[0]]
    clashed = dict(cand.nodes)
    clashed[victim] = le.Box(victim, anchor.x, anchor.y, anchor.w, anchor.h)
    broken = PlacedDiagram(
        spec=cand.spec,
        nodes=clashed,
        containers=cand.containers,
        edges=cand.edges,
        legend_x=cand.legend_x,
        legend_w=cand.legend_w,
    )

    findings = _run_oracle(broken)
    assert not findings.clean
    with pytest.raises(LayoutError):
        _repair(broken, findings)


def test_layout_is_deterministic_same_spec_identical_output_twice():
    # Req 11.1/11.4: layout(spec) is a pure function — same spec → identical
    # placed geometry (nodes, containers, edge contacts + waypoints, legend).
    spec = _landscape_spec(extra_b_slot=True)
    a = layout(spec)
    b = layout(spec)

    def _snapshot(pd: PlacedDiagram):
        return (
            {k: (v.x, v.y, v.w, v.h) for k, v in sorted(pd.nodes.items())},
            {k: (v.x, v.y, v.w, v.h) for k, v in sorted(pd.containers.items())},
            [
                (pe.spec.id, pe.exit, pe.entry, tuple(pe.points))
                for pe in pd.edges
            ],
            (pd.legend_x, pd.legend_w),
        )

    assert _snapshot(a) == _snapshot(b)
    # And every emitted coordinate is a whole GRID multiple (Req 11.4).
    for box in list(a.nodes.values()) + list(a.containers.values()):
        assert box.x % le.GRID == 0 and box.y % le.GRID == 0


# ---------------------------------------------------------------------------
# Task 11: the HA multi-region declarations (summary + landscape)
# (Req 1.5, 2.5)
# ---------------------------------------------------------------------------

from rule_engine.ha_multiregion_spec import LANDSCAPE_SPEC, SUMMARY_SPEC


def test_summary_spec_passes_validate():
    # Req 1.5 / 2.5: the coordinate-free summary declaration is well-formed —
    # known lanes, unique (lane, region, slot) keys, no dangling edges.
    _validate_spec(SUMMARY_SPEC)


def test_landscape_spec_passes_validate():
    # Req 1.5 / 2.5: the coordinate-free landscape declaration is well-formed.
    _validate_spec(LANDSCAPE_SPEC)


def test_ha_specs_encode_the_shipped_topology():
    # The declarations must express the SAME topology the coordinate tables in
    # scripts/ha_multiregion_common.py do: 9-node summary with edges s1..s9 over
    # two region frames, and 34-node landscape with edges l1..l12 over
    # account ⊃ vpc ⊃ az containers.
    assert len(SUMMARY_SPEC.nodes) == 9
    assert {e.id for e in SUMMARY_SPEC.edges} == {f"s{i}" for i in range(1, 10)}
    assert {c.id for c in SUMMARY_SPEC.containers} == {"nb_a", "nb_b"}
    # The summary is a compact north-south flow: regions side-by-side, the flow
    # reading DOWN each region column (matching the hand-drawn summary reference).
    assert SUMMARY_SPEC.axis == "north-south"
    assert SUMMARY_SPEC.compact is True

    assert len(LANDSCAPE_SPEC.nodes) == 34
    # v1.6.0: l1..l21. The original l1..l12 left 20 of the 34 nodes with no
    # incident edge at all (the 2026-09-25 audit's headline finding), so
    # ``node-connectivity`` could not ship as a rule. Nine edges were added for the
    # account edge tier and the primary region; the passive region's mirror peers
    # carry the ``standby`` overlay marker instead of duplicated edges.
    assert {e.id for e in LANDSCAPE_SPEC.edges} == {f"l{i}" for i in range(1, 22)}
    assert LANDSCAPE_SPEC.axis == "north-south"
    # Every node is either an edge endpoint or declares an overlay marker — the
    # contract ``node-connectivity`` enforces, asserted here on the SPEC so a
    # future node added without either is caught before any geometry is built.
    endpoints = {e.source for e in LANDSCAPE_SPEC.edges} | {
        e.target for e in LANDSCAPE_SPEC.edges
    }
    unexplained = [
        n.id for n in LANDSCAPE_SPEC.nodes
        if n.id not in endpoints and not n.overlay
    ]
    assert unexplained == [], (
        f"landscape nodes with neither an edge nor an overlay marker: {unexplained}"
    )
    standby = sorted(n.id for n in LANDSCAPE_SPEC.nodes if n.overlay == "standby")
    assert standby == [
        "api_b1", "api_b2", "app_b2", "cache_b1", "cache_b2", "db_b2",
        "fn_b", "mon_b", "obj_b2", "queue_b", "sec_b",
    ], "the standby set is the passive region's unconnected mirror peers"
    # account ⊃ 2 vpc ⊃ 4 az.
    kinds = sorted(c.kind for c in LANDSCAPE_SPEC.containers)
    assert kinds == ["account", "az", "az", "az", "az", "vpc", "vpc"]


def test_ha_specs_declare_no_coordinates():
    # Req 1.5: the declarations carry role/lane/region/slot for nodes and
    # source/target for edges — never x/y/exit/entry/points.
    import dataclasses as _dc

    for spec in (SUMMARY_SPEC, LANDSCAPE_SPEC):
        for node in spec.nodes:
            names = {f.name for f in _dc.fields(node)}
            assert not (names & {"x", "y", "w", "h"})
        for edge in spec.edges:
            names = {f.name for f in _dc.fields(edge)}
            assert not (names & {"exit", "entry", "points"})

# ---------------------------------------------------------------------------
# Task 17: normalise the layout origin to non-negative coordinates
# (Req 12.4)
# ---------------------------------------------------------------------------


def _accepted_before_normalise(spec: DiagramSpec) -> le.PlacedDiagram:
    """Reproduce the repair-accepted candidate BEFORE the final normalise pass.

    Mirrors ``layout`` exactly (place → route → bounded repair) but returns the
    accepted candidate without the ``_normalise_origin`` translation, so a test
    can compare pre- vs post-normalise geometry.
    """
    candidate = le._place_and_route(spec)
    findings = le._run_oracle(candidate)
    for _ in range(le.MAX_REPAIR_ITERS):
        if findings.clean:
            return candidate
        candidate = le._repair(candidate, findings)
        findings = le._run_oracle(candidate)
    assert findings.clean, findings.first_unresolved
    return candidate


def _all_origin_boxes(pd: le.PlacedDiagram):
    return list(pd.nodes.values()) + list(pd.containers.values())


def test_normalise_origins_are_non_negative_and_at_container_pad():
    # Req 12.4: after layout, every node and container origin is non-negative,
    # the layout's minimum x is exactly CONTAINER_PAD from the left, and its
    # minimum y is CONTAINER_PAD + TITLE_BAND — a title band is reserved above the
    # top container so the diagram title never overlaps the container border.
    for spec in (SUMMARY_SPEC, LANDSCAPE_SPEC):
        pd = le.layout(spec)
        boxes = _all_origin_boxes(pd)
        assert all(b.x >= 0 and b.y >= 0 for b in boxes), spec.diagram_id
        assert min(b.x for b in boxes) == le.CONTAINER_PAD, spec.diagram_id
        assert min(b.y for b in boxes) == le.CONTAINER_PAD + le.TITLE_BAND, spec.diagram_id


def test_normalise_keeps_all_edge_waypoints_non_negative():
    # Req 12.4: the shift never pulls an edge waypoint off the top/left of canvas.
    for spec in (SUMMARY_SPEC, LANDSCAPE_SPEC):
        pd = le.layout(spec)
        for pe in pd.edges:
            for px, py in pe.points:
                assert px >= 0 and py >= 0, (spec.diagram_id, pe.spec.id, px, py)


def test_normalise_origins_stay_grid_aligned():
    # Req 12.4 / 11.4: a pure grid-aligned translation keeps every origin on-grid.
    for spec in (SUMMARY_SPEC, LANDSCAPE_SPEC):
        pd = le.layout(spec)
        for b in _all_origin_boxes(pd):
            assert b.x % le.GRID == 0 and b.y % le.GRID == 0, (spec.diagram_id, b.id)
        for pe in pd.edges:
            for px, py in pe.points:
                assert px % le.GRID == 0 and py % le.GRID == 0, (spec.diagram_id, pe.spec.id)


def test_normalise_is_a_pure_translation_preserving_relative_geometry():
    # Req 12.4: normalisation shifts the WHOLE layout by one delta, so the
    # relative offset between any two boxes is identical before vs after, and the
    # oracle result is unchanged (clean → clean).
    for spec in (SUMMARY_SPEC, LANDSCAPE_SPEC):
        before = _accepted_before_normalise(spec)
        after = le._normalise_origin(before)

        # Same set of node/container ids on both sides.
        assert set(before.nodes) == set(after.nodes)
        assert set(before.containers) == set(after.containers)

        # One uniform delta recovers every node origin (and it recovers the
        # containers and waypoints too — pure translation).
        ids = sorted(before.nodes)
        dxs = {after.nodes[i].x - before.nodes[i].x for i in ids}
        dys = {after.nodes[i].y - before.nodes[i].y for i in ids}
        assert len(dxs) == 1 and len(dys) == 1, spec.diagram_id
        dx, dy = dxs.pop(), dys.pop()

        for cid, b in before.containers.items():
            assert after.containers[cid].x - b.x == dx, (spec.diagram_id, cid)
            assert after.containers[cid].y - b.y == dy, (spec.diagram_id, cid)
            # Size is unchanged (translation touches origin only).
            assert (after.containers[cid].w, after.containers[cid].h) == (b.w, b.h)

        for pe_b, pe_a in zip(before.edges, after.edges):
            for (bx, by), (ax, ay) in zip(pe_b.points, pe_a.points):
                assert (ax - bx, ay - by) == (dx, dy), (spec.diagram_id, pe_b.spec.id)
            # Contact-point fractions are unit-square faces, not absolute coords.
            assert pe_a.exit == pe_b.exit and pe_a.entry == pe_b.entry

        # legend_x is an absolute x → shifts by dx only.
        assert after.legend_x - before.legend_x == dx, spec.diagram_id

        # The oracle sees the same (clean) result on both.
        assert le._run_oracle(before).clean
        assert le._run_oracle(after).clean


def test_normalise_is_idempotent_and_no_op_when_already_at_pad():
    # A layout already anchored at its margins is unchanged by a second pass with
    # the SAME margins (layout() reserves a title band above the top container).
    margins = (le.CONTAINER_PAD, le.CONTAINER_PAD + le.TITLE_BAND)
    for spec in (SUMMARY_SPEC, LANDSCAPE_SPEC):
        once = le.layout(spec)
        twice = le._normalise_origin(once, margins)
        assert {i: (b.x, b.y) for i, b in twice.nodes.items()} == {
            i: (b.x, b.y) for i, b in once.nodes.items()
        }, spec.diagram_id
        assert {i: (b.x, b.y) for i, b in twice.containers.items()} == {
            i: (b.x, b.y) for i, b in once.containers.items()
        }, spec.diagram_id


def test_layout_is_deterministic_through_normalisation():
    # Req 11.1: same spec → identical normalised geometry twice.
    for spec in (SUMMARY_SPEC, LANDSCAPE_SPEC):
        a = le.layout(spec)
        b = le.layout(spec)
        assert {i: (x.x, x.y) for i, x in a.nodes.items()} == {
            i: (x.x, x.y) for i, x in b.nodes.items()
        }, spec.diagram_id
        assert {i: (x.x, x.y, x.w, x.h) for i, x in a.containers.items()} == {
            i: (x.x, x.y, x.w, x.h) for i, x in b.containers.items()
        }, spec.diagram_id
        assert [pe.points for pe in a.edges] == [pe.points for pe in b.edges], spec.diagram_id

"""Tests for the 1.13.0 opt-in horizontal "regional band" placement, the
captioned band-group container, and the height-aware raster export.

All three are additive and default-inert: a spec that sets no ``band`` /
``band_groups`` lays out exactly as in 1.12.0, and a raster already within its
height budget exports at the same scale. The golden-safety anchor remains
``tests/test_golden_examples.py``; these tests only exercise the NEW branches.
"""

from __future__ import annotations

import pytest

from rule_engine.diagram_layout import ICON_SIZE, band_group_cells, Node
from rule_engine.layout import layout
from rule_engine.layout.base import COL_STEP, ROW_STEP
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec


# --------------------------------------------------------------------------- #
# Spec builder: account ⊃ region ⊃ vpc ⊃ subnet, with a south band.
# --------------------------------------------------------------------------- #
def _band_spec(band_members, *, band="south", band_row=0, groups=()):
    """A minimal North–South landscape: one VPC-attached compute node in a
    private subnet, plus ``band_members`` region-direct nodes carrying ``band``.
    """
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None,
                      label_key="account"),
        ContainerSpec(id="region", kind="region", region="a", parent="acct",
                      label_key="region"),
        ContainerSpec(id="vpc", kind="vpc", region="a", parent="region",
                      label_key="vpc"),
        ContainerSpec(id="sub", kind="subnet", region="a", parent="vpc",
                      label_key="sub"),
    )
    nodes = [
        NodeSpec(id="compute", role="compute_instance", lane="workers",
                 region="a", slot=0, container="sub", scope="network"),
    ]
    for i, mid in enumerate(band_members):
        nodes.append(NodeSpec(
            id=mid, role="object_store", lane="data", region="a", slot=i,
            container="region", scope="regional", band=band, band_row=band_row,
        ))
    return DiagramSpec(
        diagram_id="band-test", diagram_name="band-test", axis="north-south",
        nodes=tuple(nodes),
        edges=(EdgeSpec(id="e1", source="compute", target=band_members[0],
                        marker="1"),) if band_members else (),
        containers=containers, flow_lines=("Flow",), title="band test",
        band_groups=groups,
    )


def _placed(spec):
    return layout(spec, strict=False)


# --------------------------------------------------------------------------- #
# 1. South band lays out HORIZONTALLY (left→right), not in one column.
# --------------------------------------------------------------------------- #
def test_south_band_is_horizontal_row():
    spec = _band_spec(["b0", "b1", "b2", "b3"])
    placed = _placed(spec)
    xs = [placed.nodes[f"b{i}"].x for i in range(4)]
    ys = [placed.nodes[f"b{i}"].y for i in range(4)]
    # Distinct, strictly increasing x (a row), and all on one y (one row).
    assert xs == sorted(xs)
    assert len(set(xs)) == 4, f"band nodes collapsed into a column: {xs}"
    assert len(set(ys)) == 1, f"band row is not level: {ys}"
    # Spaced by the column step.
    assert xs[1] - xs[0] == COL_STEP


def test_south_band_sits_below_the_vpc():
    spec = _band_spec(["b0", "b1"])
    placed = _placed(spec)
    compute_bottom = placed.nodes["compute"].y + ICON_SIZE
    assert placed.nodes["b0"].y > compute_bottom, (
        "south band must sit below the VPC compute node")


# --------------------------------------------------------------------------- #
# 2. The band WRAPS to a new row when wider than the band width budget.
# --------------------------------------------------------------------------- #
def test_south_band_wraps_when_too_wide():
    # 10 members on a 4-column-wide VPC must wrap onto multiple rows.
    members = [f"b{i}" for i in range(10)]
    spec = _band_spec(members)
    placed = _placed(spec)
    ys = sorted({placed.nodes[m].y for m in members})
    assert len(ys) >= 2, "a 10-node band on a narrow VPC must wrap to >1 row"
    # The first row holds at most the width budget (>=4) nodes.
    first_row_y = min(placed.nodes[m].y for m in members)
    first_row = [m for m in members if placed.nodes[m].y == first_row_y]
    assert 4 <= len(first_row) <= 6


# --------------------------------------------------------------------------- #
# 3. account-south places the band BELOW the Region, inside the Account.
# --------------------------------------------------------------------------- #
def test_account_south_sits_below_the_region_inside_account():
    spec = _band_spec(["c0", "c1", "c2"], band="account-south")
    placed = _placed(spec)
    region = placed.containers["region"]
    acct = placed.containers["acct"]
    c0 = placed.nodes["c0"]
    # Band is below the Region box, but still within the Account box.
    assert c0.y >= region.bottom - ICON_SIZE, (
        "account-south band must sit at or below the Region bottom")
    assert acct.y <= c0.y and c0.y + ICON_SIZE <= acct.bottom, (
        "account-south band must stay inside the Account box")


# --------------------------------------------------------------------------- #
# 4. A declared band group keeps its members CONTIGUOUS in the row.
# --------------------------------------------------------------------------- #
def test_band_group_members_are_contiguous():
    members = ["g0", "x0", "g1", "x1"]  # declared interleaved
    groups = (("Group A", ("g0", "g1")),)
    spec = _band_spec(members, groups=groups)
    placed = _placed(spec)
    # In x-order, g0 and g1 must be adjacent (contiguous), not split by an x.
    order = sorted(members, key=lambda m: placed.nodes[m].x)
    gi = [i for i, m in enumerate(order) if m in ("g0", "g1")]
    assert gi[1] - gi[0] == 1, f"group members not contiguous: {order}"


# --------------------------------------------------------------------------- #
# 5. Default-inert: a spec with NO band is unchanged (columnar).
# --------------------------------------------------------------------------- #
def test_no_band_is_columnar_as_before():
    # Two region-direct nodes with NO band → same x (one regional column).
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None,
                      label_key="account"),
        ContainerSpec(id="region", kind="region", region="a", parent="acct",
                      label_key="region"),
        ContainerSpec(id="vpc", kind="vpc", region="a", parent="region",
                      label_key="vpc"),
        ContainerSpec(id="sub", kind="subnet", region="a", parent="vpc",
                      label_key="sub"),
    )
    nodes = (
        NodeSpec(id="compute", role="compute_instance", lane="workers",
                 region="a", slot=0, container="sub", scope="network"),
        NodeSpec(id="r0", role="object_store", lane="data", region="a", slot=0,
                 container="region", scope="regional", overlay="supporting"),
        NodeSpec(id="r1", role="dynamodb", lane="async", region="a", slot=1,
                 container="region", scope="regional", overlay="supporting"),
    )
    spec = DiagramSpec(
        diagram_id="nb", diagram_name="nb", axis="north-south", nodes=nodes,
        edges=(), containers=containers, flow_lines=("Flow",), title="nb")
    placed = layout(spec, strict=False)
    # The two loose regional nodes stack in the regional column (same x).
    assert placed.nodes["r0"].x == placed.nodes["r1"].x


# --------------------------------------------------------------------------- #
# 6. band_group_cells emits a captioned box sized to show the FULL caption.
# --------------------------------------------------------------------------- #
def test_band_group_cell_fits_full_caption():
    # Two adjacent small icons; a long caption must widen the box past them.
    nodes = [
        Node(id="n0", label="A", x=100, y=100, render="x"),
        Node(id="n1", label="B", x=100 + COL_STEP, y=100, render="x"),
    ]
    caption = "Security, observability & resilience (regional)"
    xml = band_group_cells((("Security, observability & resilience (regional)",
                             ("n0", "n1")),), nodes)
    assert "bandgroup-0" in xml
    assert caption in xml or "Security" in xml
    # Extract the width; it must exceed the two-icon member bbox.
    import re
    m = re.search(r'width="(\d+)"', xml)
    assert m is not None
    width = int(m.group(1))
    member_bbox = COL_STEP + ICON_SIZE
    assert width >= len(caption) * 6, (
        f"band group box {width}px too narrow for its caption")
    assert width > member_bbox


def test_band_group_cells_empty_is_byte_inert():
    assert band_group_cells((), []) == ""


# --------------------------------------------------------------------------- #
# 7. Height-aware export: a tall-but-narrow canvas fits the HEIGHT budget.
# --------------------------------------------------------------------------- #
def test_compute_scale_fits_height_budget(tmp_path):
    from rule_engine import export_raster as er

    # Monkeypatch the canvas measurement: a narrow (1000px) but very tall
    # (7200px) landscape. Width fit alone would keep scale ~1.0; the height
    # fit must pull it to (3600-16)/7200 ≈ 0.498 → clamped to the 0.5 floor
    # boundary; use 6000px tall so the fit is ~0.597, above the floor.
    src = tmp_path / "x.drawio"
    src.write_text("<mxfile></mxfile>", encoding="utf-8")
    comp = tmp_path / "x.diagram.md"
    comp.write_text("---\ndiagram_class: landscape\n---\n", encoding="utf-8")

    er._canvas_width_orig = er._canvas_width
    er._canvas_height_orig = er._canvas_height
    try:
        er._canvas_width = lambda s: 1000.0
        er._canvas_height = lambda s: 6000.0
        scale, width = er.compute_scale(src)
    finally:
        er._canvas_width = er._canvas_width_orig
        er._canvas_height = er._canvas_height_orig

    border = int(er.EXPORT_BORDER) * 2
    expected = (er.LANDSCAPE_MAX_HEIGHT - border) / 6000.0
    assert scale == pytest.approx(expected, rel=1e-6), (
        f"height fit not applied: scale={scale}, expected {expected}")
    # And the exported height is within budget.
    assert 6000.0 * scale <= er.LANDSCAPE_MAX_HEIGHT - border + 1


def test_compute_scale_within_height_budget_is_unchanged(tmp_path):
    from rule_engine import export_raster as er

    src = tmp_path / "y.drawio"
    src.write_text("<mxfile></mxfile>", encoding="utf-8")
    comp = tmp_path / "y.diagram.md"
    comp.write_text("---\ndiagram_class: landscape\n---\n", encoding="utf-8")

    er._canvas_width_orig = er._canvas_width
    er._canvas_height_orig = er._canvas_height
    try:
        # A short, moderately-wide landscape: within both budgets → no downscale.
        er._canvas_width = lambda s: 2000.0
        er._canvas_height = lambda s: 1500.0
        scale, _ = er.compute_scale(src)
    finally:
        er._canvas_width = er._canvas_width_orig
        er._canvas_height = er._canvas_height_orig

    # Width fit (3584/2000 ≈ 1.79) is capped at 1.5; height never binds.
    assert scale == pytest.approx(er.MAX_EXPORT_SCALE, rel=1e-6)

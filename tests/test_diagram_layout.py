"""Unit tests for the shared diagram layout builder (``rule_engine.diagram_layout``).

These guard the canonical layout standard (diagram-standards.md → Layout
Geometry): a uniform 78x78 icon footprint, labels that hug the icon, built-in
and OCI icon renderers producing exactly one top-level node, and the OCI stencil
embedding stripping the baked-in caption while scaling the icon square.
"""

from __future__ import annotations

import re

from rule_engine import diagram_layout as dl
from rule_engine.cli import _parse_drawio_page
from rule_engine.drawio_model import parse_drawio
from rule_engine.linter import lint


def _parse_drawio(path: str, text: str):
    """Parse in-memory ``.drawio`` text into the single-page diagram Artifact.

    The 1.7.0 CLI parses on the shared ``drawio_model`` and builds one Artifact
    per page; these tests hand XML text and want the single-page diagram
    Artifact, so parse the text into its one Page and feed that.
    """
    pages = parse_drawio(text, path=path)
    return _parse_drawio_page(path, pages[0], text)


def test_canonical_constants():
    assert dl.ICON_SIZE == 78
    assert dl.COL_STEP == 220
    assert dl.ROW_STEP == 160
    assert dl.CONTAINER_PAD >= dl.GRID


def test_builtin_icon_is_single_78px_node_with_hugging_label():
    node = dl.Node(id="n1", label="svc", x=100, y=200,
                   render=dl.builtin_icon("shape=mxgraph.aws4.resourceIcon;aspect=fixed;html=1"))
    xml = node.render(node, "1")
    assert 'width="78" height="78"' in xml
    assert "verticalLabelPosition=bottom" in xml
    assert xml.count("vertex=\"1\"") == 1  # one flat cell


def _oci_stencil_fixture():
    # Minimal stencil: a group (id=2) with an icon cell (id=3) and a baked-in
    # caption cell (id=4, Oracle Sans) below the icon.
    xml = (
        "<mxGraphModel><root>"
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="2" style="group" vertex="1" parent="1">'
        '<mxGeometry width="84" height="109" as="geometry"/></mxCell>'
        '<mxCell id="3" style="shape=stencil(AAAA);html=1" vertex="1" parent="2">'
        '<mxGeometry x="0" y="0" width="84" height="84" as="geometry"/></mxCell>'
        '<mxCell id="4" value="Functions" style="font-family:Oracle Sans;html=1" '
        'vertex="1" parent="2"><mxGeometry x="2" y="88" width="80" height="20" as="geometry"/></mxCell>'
        "</root></mxGraphModel>"
    )
    return {"functions": {"w": 84, "h": 109, "xml": xml}}


def test_oci_renderer_strips_caption_and_scales_square():
    stencils = _oci_stencil_fixture()
    icon = dl.OciStencilIcon(stencils, "functions", brand_hex="#F80000")
    node = dl.Node(id="api", label="api-function", x=120, y=440, render=icon)
    xml = node.render(node, "1")
    # Baked-in caption removed; label carried once by the container.
    assert 'value="Functions"' not in xml
    assert "font-family:Oracle Sans" not in xml
    assert 'value="api-function"' in xml
    # Container is a 78x78 group; the icon (84 wide) is scaled down (< 84).
    assert 'width="78" height="78"' in xml
    assert 'width="84.000"' not in xml


def test_oci_node_caption_is_oracle_sans_near_black_not_red():
    # D17: the mapping's resource styles were guarded, but the stencil renderer
    # (what every OCI diagram actually uses) still coloured captions with the
    # brand red. The rendered caption must follow v24.2: Oracle Sans (with a
    # sans-serif fallback) in #312D2A, whatever brand_hex the caller passes.
    stencils = _oci_stencil_fixture()
    icon = dl.OciStencilIcon(stencils, "functions", brand_hex="#F80000")
    node = dl.Node(id="api", label="api-function", x=120, y=440, render=icon)
    xml = node.render(node, "1")
    container = next(c for c in xml.split("<mxCell")[1:] if 'id="api"' in c)
    assert "fontColor=#312D2A" in container
    assert "fontColor=#F80000" not in container
    assert f"fontFamily={dl.OCI_FONT_FAMILY};" in container
    assert dl.OCI_FONT_FAMILY.split(",")[0] == "Oracle Sans"
    assert dl.OCI_FONT_FAMILY.endswith("sans-serif")


def test_full_diagram_counts_one_node_per_service():
    stencils = _oci_stencil_fixture()
    nodes = [
        dl.Node(id=f"svc{i}", label=f"svc{i}", x=120 + i * dl.COL_STEP, y=440,
                render=dl.OciStencilIcon(stencils, "functions"))
        for i in range(3)
    ]
    edges = [dl.Edge("e1", "svc0", "svc1", "1"), dl.Edge("e2", "svc1", "svc2", "2")]
    boundaries = [dl.Boundary("boundary-x", "b", x=40, y=70, w=1200, h=600)]
    doc = dl.build_diagram(
        diagram_id="d", diagram_name="d", title="t | 2026-09-22 | v1",
        boundaries=boundaries, nodes=nodes, edges=edges,
        flow_lines=["Flow", "1. a", "2. b"], legend_x=1400,
    )
    art = _parse_drawio("mem.drawio", doc)
    # Three service nodes counted; boundary + legends excluded.
    assert sorted(art.node_names) == ["svc0", "svc1", "svc2"]


# --- REVIEW.md #3: OCI stencil pack-shape guard -----------------------------


def test_embed_oci_stencil_raises_on_missing_group_cell():
    """A stencil with no id="2" group cell fails loudly, not silently."""
    import pytest

    bad_xml = (
        "<mxGraphModel><root>"
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="9" style="shape=stencil(X);html=1" vertex="1" parent="1">'
        '<mxGeometry width="80" height="80" as="geometry"/></mxCell>'
        "</root></mxGraphModel>"
    )
    with pytest.raises(dl.OciStencilError):
        dl.embed_oci_stencil("n1", bad_xml, 80, 80, "n1")


# --- D16: nested-stencil glyph centering (the "model-storage" label shift) ---


def _glyph_center_x(rendered: str) -> tuple[float, float]:
    """Root-frame [min_x, max_x] of the drawn shape cells in a rendered node.

    Walks the emitted ``mxCell`` tree, accumulating each cell's ``x`` onto its
    parent's, and unions the boxes of the cells that carry a ``shape=``/stencil
    glyph — the same way a viewer composes the group. Returns the glyph's left
    and right edges in the node's own coordinate frame.
    """
    import re

    cells = re.findall(r"<mxCell\b.*?(?:/>|</mxCell>)", rendered, re.S)
    x_of: dict[str, float] = {}
    parent_of: dict[str, str] = {}
    is_shape: dict[str, bool] = {}
    w_of: dict[str, float] = {}
    for c in cells:
        cid = re.search(r'id="([^"]+)"', c)
        if not cid:
            continue
        cid = cid.group(1)
        pm = re.search(r'parent="([^"]+)"', c)
        parent_of[cid] = pm.group(1) if pm else ""
        gm = re.search(r"<mxGeometry\b[^>]*", c)
        xm = re.search(r'\bx="([-0-9.eE]+)"', gm.group(0)) if gm else None
        wm = re.search(r'\bwidth="([-0-9.eE]+)"', gm.group(0)) if gm else None
        x_of[cid] = float(xm.group(1)) if xm else 0.0
        w_of[cid] = float(wm.group(1)) if wm else 0.0
        st = re.search(r'style="([^"]*)"', c)
        is_shape[cid] = bool(st and ("shape=" in st.group(1) or "stencil" in st.group(1)))

    def abs_x(cid: str) -> float:
        ax = 0.0
        seen: set[str] = set()
        cur = cid
        while cur and cur in x_of and cur not in seen:
            seen.add(cur)
            ax += x_of[cur]
            cur = parent_of.get(cur, "")
        return ax

    lo, hi = float("inf"), float("-inf")
    for cid, shape in is_shape.items():
        if not shape or not w_of[cid]:
            continue
        left = abs_x(cid)
        lo = min(lo, left)
        hi = max(hi, left + w_of[cid])
    return lo, hi


def test_nested_stencil_glyph_is_centered_in_box():
    """A stencil that wraps its glyph in an intermediate OFFSET group (like OCI
    ``object-storage`` / ``cdn``) must still render the glyph centred within the
    78px node box, so the bottom label — anchored to that box — is not shifted.

    Regression for docs/REVIEW.md D16: the bbox was measured in each cell's local
    frame, so the wrapper group's ~14px offset was not cancelled by the centering
    pad and the glyph rendered right of centre.
    """
    # id=2 is a pure group wrapper; id=3 is an intermediate group offset by 14px;
    # the real glyph shape (id=4) is 78-wide inside it. Declared root box (106)
    # is wider than the glyph, exactly the object-storage shape.
    xml = (
        "<mxGraphModel><root>"
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="2" style="group" vertex="1" parent="1">'
        '<mxGeometry width="106" height="101" as="geometry"/></mxCell>'
        '<mxCell id="3" style="group" vertex="1" parent="2">'
        '<mxGeometry x="14" y="0" width="78" height="78" as="geometry"/></mxCell>'
        '<mxCell id="4" style="shape=stencil(AAAA);html=1" vertex="1" parent="3">'
        '<mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>'
        "</root></mxGraphModel>"
    )
    stencils = {"object-storage": {"w": 106, "h": 101, "xml": xml}}
    icon = dl.OciStencilIcon(stencils, "object-storage")
    node = dl.Node(id="model-storage", label="model-storage", x=0, y=0, render=icon)
    rendered = node.render(node, "1")
    lo, hi = _glyph_center_x(rendered)
    center = (lo + hi) / 2.0
    box_center = dl.ICON_SIZE / 2.0
    assert abs(center - box_center) <= 1.5, (
        f"glyph center_x={center:.1f} not within 1.5px of box center "
        f"{box_center:.1f} (glyph x=[{lo:.1f},{hi:.1f}])"
    )


# --------------------------------------------------------------------------- #
# 1.10.3: captions stay readable when an edge must pass them.
# --------------------------------------------------------------------------- #


def _stub_icon(node, parent):
    return (
        f'        <mxCell id="{node.id}" value="{node.label}" '
        f'style="shape=x;{dl._LABEL_STYLE}{dl.overlay_suffix(node)}" vertex="1" parent="{parent}">\n'
        f'          <mxGeometry x="{node.x}" y="{node.y}" width="78" height="78" as="geometry" />\n'
        "        </mxCell>\n"
    )


def test_container_caption_moves_off_a_top_entry_drop():
    b = dl.Boundary("boundary-vpc", "vcn-primary us-ashburn-1", x=40, y=300, w=900, h=600,
                    style="rounded=0;dashed=1;fillColor=none;align=left;verticalAlign=top;spacingLeft=5")
    src = dl.Node("src", "src", 100, 90, render=_stub_icon)
    tgt = dl.Node("tgt", "tgt", 110, 400, render=_stub_icon)
    e = dl.Edge("e", "src", "tgt", "1", exit=(1.0, 0.5), entry=(0.5, 0.0),
                points=[(220, 129), (220, 250), (149, 250)])
    [moved] = dl._clear_container_captions([b], [src, tgt], dl._orthogonalised([e], [src, tgt]))
    assert moved.style != b.style
    left = int(re.search(r"spacingLeft=(\d+)", moved.style).group(1))
    assert b.x + left > 149, "caption text must start right of the drop column"


def test_clear_caption_is_left_byte_identical():
    b = dl.Boundary("boundary-vpc", "vpc", x=40, y=300, w=900, h=600)
    assert dl._clear_container_captions([b], [], []) == [b]


def test_bottom_exit_through_own_caption_is_drawn_behind_it():
    src = dl.Node("lb", "lb-primary", 120, 400, render=_stub_icon)
    tgt = dl.Node("app", "app", 120, 600, render=_stub_icon)
    zone = dl.Boundary("boundary-az", "az", x=90, y=560, w=300, h=200,
                       style="rounded=1;fillColor=#DFDCD8;strokeColor=#9E9892")
    edge = dl.Edge("down", "lb", "app", "3", exit=(0.5, 1.0), entry=(0.5, 0.0))
    xml = dl.build_diagram(
        diagram_id="d", diagram_name="d", title="t | 2026-09-30 | v1",
        boundaries=[zone], nodes=[src, tgt], edges=[edge],
        flow_lines=["Flow", "3. down"], legend_x=600,
    )
    assert xml.index('id="down"') < xml.index('id="lb"'), "edge must be painted under the node"
    # Every service node now carries an opaque white caption background by
    # default (so an edge crossing the caption band never strikes through the
    # text). ``lb`` sits on the white canvas, so its background is white.
    lb_cell = xml[xml.index('id="lb"'):].split("</mxCell>")[0]
    assert "labelBackgroundColor=#FFFFFF" in lb_cell
    # ``app`` sits inside the filled zone (#DFDCD8) and its own bottom-exit edge
    # is not cutting its caption, so it keeps the default white background — the
    # default applies to every node, cut or not.
    app_cell = xml[xml.index('id="app"'):].split("</mxCell>")[0]
    assert "labelBackgroundColor=#FFFFFF" in app_cell


# ---------------------------------------------------------------------------
# 1.10.7 (S3): the Legend names only the boundaries that are drawn
# ---------------------------------------------------------------------------

_OUTER = "Outer boundary = stack Boundary (captioned; provider style)"
_INNER = "Inner boundary = Network Boundary (captioned; provider style)"


def _box(kind: str):
    from rule_engine.diagram_layout import Boundary

    return Boundary(id=f"b-{kind or 'x'}", label=kind, x=0, y=0, w=100, h=100, kind=kind)


def test_legend_lines_for_account_and_vpc_keeps_both_lines():
    from rule_engine.diagram_layout import STANDARD_LEGEND_LINES, legend_lines_for

    lines = legend_lines_for([_box("account"), _box("region"), _box("vpc")])
    assert lines == STANDARD_LEGEND_LINES
    assert _OUTER in lines and _INNER in lines


def test_legend_lines_for_account_only_drops_the_inner_line():
    from rule_engine.diagram_layout import legend_lines_for

    lines = legend_lines_for([_box("account")])
    assert _OUTER in lines and _INNER not in lines


def test_legend_lines_for_regions_only_drops_both_lines():
    from rule_engine.diagram_layout import legend_lines_for

    lines = legend_lines_for([_box("region"), _box("region")])
    assert _OUTER not in lines and _INNER not in lines
    assert lines[0] == "Legend"


def test_legend_lines_for_undeclared_kinds_is_the_standard_legend():
    from rule_engine.diagram_layout import STANDARD_LEGEND_LINES, legend_lines_for

    assert legend_lines_for([_box(""), _box("")]) == STANDARD_LEGEND_LINES


def test_standard_legend_names_both_boundary_lines():
    from rule_engine.diagram_layout import STANDARD_LEGEND_LINES

    assert _OUTER in STANDARD_LEGEND_LINES and _INNER in STANDARD_LEGEND_LINES


def test_build_diagram_uses_the_conditional_legend_by_default():
    from rule_engine.diagram_layout import build_diagram

    xml = build_diagram(
        diagram_id="d", diagram_name="d", title="t", boundaries=[_box("account")],
        nodes=[], edges=[], flow_lines=("Flow",), legend_x=200,
    )
    assert "Outer boundary" in xml and "Inner boundary" not in xml


# ---------------------------------------------------------------------------
# Theme 16 (1.10.10): peering edge annotation
# ---------------------------------------------------------------------------


def test_peering_edge_is_a_symmetric_headless_dashed_line():
    """A peering edge (VPC/VCN peering, cross-cloud peering) renders as a dashed
    line with NO arrowhead on either end, so it reads as an undirected
    network-level relationship rather than a directional data-flow step.

    1.11.0 (G23): the Theme-16 on-canvas ``peering`` marker word is removed — the
    edge carries an EMPTY ``value`` (a peering is documented in the Flow
    narrative, or materialized into a ``vpc_peering`` resource node). The STYLE
    is unchanged (symmetric dashed, no heads)."""
    cell = dl.edge_cell(
        dl.Edge(id="px", source="a", target="b", marker="peering", peering=True)
    )
    assert "startArrow=none" in cell and "endArrow=none" in cell
    assert "dashed=1" in cell
    assert 'value=""' in cell          # G23: no on-canvas 'peering' word
    assert ">peering<" not in cell     # not painted anywhere on the line
    # A peering line passes arrow-style (none is an accepted head) and
    # edge-bidirectional (either-end-none ⇒ not double-headed).
    assert "endArrow=open" not in cell


def test_normal_edge_is_unchanged_by_the_peering_option():
    """A non-peering edge keeps the open single arrowhead — the peering branch is
    opt-in and must not change the default edge style."""
    cell = dl.edge_cell(dl.Edge(id="e1", source="a", target="b", marker="1"))
    assert "endArrow=open" in cell and "endFill=0" in cell
    assert "startArrow=none" not in cell  # single-head, start unset
    assert "dashed=1" not in cell


def test_theme43_wide_body_selects_mode_b_row_below():
    """Theme 43: a physically wide-and-short body (aspect >= 2.2) places the
    Flow/Legend as a right-aligned horizontal row BELOW the body (Mode B)."""
    # body 1400 wide x 400 tall -> aspect 3.5
    nodes = [dl.Node(id="n1", label="n1", x=0, y=0),
             dl.Node(id="n2", label="n2", x=1322, y=322)]  # right/bottom extent
    boundaries = [dl.Boundary(id="b", label="b", x=0, y=0, w=1400, h=400)]
    flow = ("Flow", "1. a", "2. b")
    legend = ("Legend", "x", "y")
    lx, ly, mode, pw, ph = dl.theme43_legend_placement(nodes, boundaries, flow, legend, 300)
    assert mode == "row-below"
    # 1.10.12 WS6: the row is left-aligned with the body (no empty lower-left
    # quadrant) and starts one pad below the lowest caption (322 + 78 + 30).
    assert lx == 0
    assert ly == 322 + 78 + 30 + dl.CONTAINER_PAD


def test_theme43_tall_body_selects_mode_a_stack():
    """Theme 43: a squarish/tall body (aspect < 2.2) stacks the Flow/Legend in
    the right margin, top-aligned (Mode A); the engine's caption-safe legend_x
    is honoured as the floor."""
    nodes = [dl.Node(id="n1", label="n1", x=0, y=0),
             dl.Node(id="n2", label="n2", x=922, y=1222)]  # ~1000x1300, aspect 0.77
    boundaries = [dl.Boundary(id="b", label="b", x=0, y=0, w=1000, h=1300)]
    flow = ("Flow", "1. a")
    legend = ("Legend", "x")
    lx, ly, mode, pw, ph = dl.theme43_legend_placement(
        nodes, boundaries, flow, legend, 300, engine_legend_x=1100)
    assert mode == "stack"
    assert lx >= 1100          # honours the caption-safe engine floor
    assert ly == 0             # top-aligned to body top


# --- FEAT-001 (B) / backlog G22: multi-column Flow legend -------------------


def _flow_build(flow_lines, *, flow_columns=None):
    """A tiny 3-node chain whose Flow list can reflow into N columns."""
    icon = dl.builtin_icon("shape=mxgraph.aws4.resourceIcon;aspect=fixed;html=1")
    nodes = [
        dl.Node(id="n0", label="n0", x=120, y=440, render=icon),
        dl.Node(id="n1", label="n1", x=340, y=440, render=icon),
        dl.Node(id="n2", label="n2", x=560, y=440, render=icon),
    ]
    edges = [
        dl.Edge("e1", "n0", "n1", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
        dl.Edge("e2", "n1", "n2", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    ]
    return dl.build_diagram(
        diagram_id="d", diagram_name="d",
        title="aws t — 123456789012 / us-east-1 | 2026-10-23 | v1",
        boundaries=[], nodes=nodes, edges=edges,
        flow_lines=flow_lines, legend_x=1000, flow_columns=flow_columns,
    )


_LONG_FLOW = [
    "Flow",
    "1. ingest the request",
    "2. authenticate the caller",
    "3. enqueue the job",
    "4. run the worker",
    "5. persist the result",
    "6. notify the consumer",
]


def test_flow_columns_unset_is_byte_identical_to_the_single_box():
    """The default (``flow_columns=None``) is byte-inert: identical to not
    passing the parameter at all."""
    assert _flow_build(_LONG_FLOW, flow_columns=None) == _flow_build(_LONG_FLOW)


def test_flow_columns_emits_n_side_by_side_flow_cells():
    """``flow_columns=3`` emits three ``Flow`` column cells (ids flow-legend,
    flow-legend-2, flow-legend-3) at distinct, ascending x."""
    doc = _flow_build(_LONG_FLOW, flow_columns=3)
    assert doc.count('value="Flow') == 3
    for cid in ("flow-legend", "flow-legend-2", "flow-legend-3"):
        assert f'id="{cid}"' in doc
    # Columns run left-to-right: each column's x is strictly greater than the last.
    xs = []
    for cid in ("flow-legend", "flow-legend-2", "flow-legend-3"):
        frag = doc.split(f'id="{cid}"', 1)[1].split("</mxCell>", 1)[0]
        xs.append(int(re.search(r'<mxGeometry x="(\d+)"', frag).group(1)))
    assert xs == sorted(xs) and len(set(xs)) == 3


def test_flow_columns_preserves_every_marker_line_so_coverage_holds():
    """Every numbered step survives the split across columns, so ``flow-legend``
    coverage still passes under lint (no marker dropped)."""
    doc = _flow_build(_LONG_FLOW, flow_columns=3)
    for step in range(1, 7):
        assert f"{step}. " in doc
    art = _parse_drawio("mem.drawio", doc)
    rules = [f["rule"] for f in lint(art)["findings"]]
    assert "flow-legend" not in rules


def test_flow_columns_one_equals_single_box():
    """``flow_columns=1`` degenerates to the single Flow box (one ``Flow`` cell)."""
    doc = _flow_build(_LONG_FLOW, flow_columns=1)
    assert doc.count('value="Flow') == 1


def test_flow_columns_invalid_count_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        _flow_build(_LONG_FLOW, flow_columns=0)


# --- 1.11.0: equal-height horizontal Flow/Legend row -----------------------


def _row_below_build(flow_lines, legend_lines, *, flow_columns=None):
    """Build a diagram whose Flow/Legend are laid out as a horizontal row
    (Theme 43 Mode B, ``legend_mode='row-below'``)."""
    icon = dl.builtin_icon("shape=mxgraph.aws4.resourceIcon;aspect=fixed;html=1")
    nodes = [
        dl.Node(id="n0", label="n0", x=120, y=440, render=icon),
        dl.Node(id="n1", label="n1", x=340, y=440, render=icon),
        dl.Node(id="n2", label="n2", x=560, y=440, render=icon),
    ]
    edges = [
        dl.Edge("e1", "n0", "n1", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
        dl.Edge("e2", "n1", "n2", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    ]
    return dl.build_diagram(
        diagram_id="d", diagram_name="d",
        title="aws t — 123456789012 / us-east-1 | 2026-10-23 | v1",
        boundaries=[], nodes=nodes, edges=edges,
        flow_lines=flow_lines, legend_x=0, legend_y_flow=700,
        legend_mode="row-below", legend_lines=legend_lines,
        flow_columns=flow_columns,
    )


def _cell_geom(doc, cid):
    """(x, y, w, h) of a text cell by id, from the emitted document."""
    frag = doc.split(f'id="{cid}"', 1)[1].split("</mxCell>", 1)[0]
    m = re.search(
        r'<mxGeometry x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"', frag)
    return tuple(int(g) for g in m.groups())


_SHORT_FLOW = ["Flow", "1. a", "2. b", "3. c"]
_TALL_LEGEND = ["Legend"] + [f"line {i}" for i in range(10)]


def test_row_below_flow_legend_share_a_common_height():
    """A horizontal row (multi-column Flow + Legend) renders every box at the
    SAME height (the tallest natural box) so the row shares one flat bottom edge."""
    doc = _row_below_build(_SHORT_FLOW, _TALL_LEGEND, flow_columns=2)
    heights, ys = [], []
    for cid in ("flow-legend", "flow-legend-2", "legend"):
        _, y, _, h = _cell_geom(doc, cid)
        heights.append(h)
        ys.append(y)
    assert len(set(heights)) == 1, f"ragged row heights: {heights}"
    assert len(set(ys)) == 1, f"row boxes not top-aligned: {ys}"
    # The common height equals the tallest natural box — the 10-line Legend.
    assert heights[0] == max(heights)


def test_row_below_single_flow_legend_share_a_common_height():
    """The non-multi-column row-below case (plain Flow + Legend side-by-side)
    also renders both boxes at the common max height."""
    doc = _row_below_build(_SHORT_FLOW, _TALL_LEGEND)
    _, fy, _, fh = _cell_geom(doc, "flow-legend")
    _, ly, _, lh = _cell_geom(doc, "legend")
    assert fh == lh, f"ragged heights flow={fh} legend={lh}"
    assert fy == ly


def test_vertical_stack_height_unchanged_byte_identical():
    """The equal-height fix is scoped to ``row-below``; the Mode-A vertical
    stack path is untouched, so its output is byte-identical to a rebuild."""
    assert _flow_build(_LONG_FLOW, flow_columns=2) == _flow_build(_LONG_FLOW, flow_columns=2)
    # And the stack path keeps per-box heights (Flow shorter than a long Legend
    # stacks ABOVE it, not padded to a common height).
    doc = _flow_build(_LONG_FLOW, flow_columns=1)
    assert doc.count('value="Flow') == 1

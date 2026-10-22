"""WS2 (1.11.0) — flow logical-group box tests."""

from __future__ import annotations

import re

from rule_engine import diagram_layout as dl
from rule_engine.layout.model import DiagramSpec


def _node(nid, x, y, label="svc"):
    return dl.Node(id=nid, label=label, x=x, y=y,
                   render=dl.builtin_icon("shape=mxgraph.aws4.resourceIcon;html=1"))


def test_spec_defaults_are_byte_inert():
    assert DiagramSpec.__dataclass_fields__["flow_groups"].default == ()
    assert DiagramSpec.__dataclass_fields__["flow_steps"].default == "box"


def test_empty_groups_emit_nothing():
    assert dl.flow_group_cells((), [_node("a", 0, 0)]) == ""


def test_group_box_encloses_its_members():
    nodes = [_node("a", 100, 100), _node("b", 300, 100)]
    cells = dl.flow_group_cells((("Ingestion", ("a", "b")),), nodes)
    assert "flowgroup-0" in cells and "Ingestion" in cells
    m = re.search(r'x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"', cells)
    x, y, w, h = map(int, m.groups())
    # left edge is left of the leftmost member icon, right edge past the rightmost
    assert x <= 100
    assert x + w >= 300 + dl.ICON_SIZE


def test_absent_members_are_skipped_and_empty_group_draws_nothing():
    nodes = [_node("a", 0, 0)]
    # group names only a missing node -> nothing
    assert dl.flow_group_cells((("Ghost", ("zzz",)),), nodes) == ""
    # group with one present + one missing -> still a box around the present one
    cells = dl.flow_group_cells((("Mixed", ("a", "zzz")),), nodes)
    assert "flowgroup-0" in cells


def test_group_style_is_light_grey_no_fill():
    cells = dl.flow_group_cells((("G", ("a",)),), [_node("a", 0, 0)])
    assert "strokeColor=#9AA5B1" in cells and "fillColor=none" in cells


def _mini_diagram(flow_steps):
    b = [dl.Boundary(id="bx", label="acct", x=40, y=40, w=400, h=300)]
    n = [_node("a", 80, 80)]
    return dl.build_diagram(
        diagram_id="d", diagram_name="d", title="t", boundaries=b, nodes=n,
        edges=[], flow_lines=("1. a to b", "2. b to c"), legend_x=500,
        flow_steps=flow_steps,
    )


def test_flow_steps_box_has_flow_cell_document_omits_it():
    box = _mini_diagram("box")
    doc = _mini_diagram("document")
    assert 'id="flow-legend"' in box
    assert 'id="flow-legend"' not in doc
    # the Legend stays on-canvas in both
    assert 'id="legend"' in box and 'id="legend"' in doc


def test_proposer_clusters_adjacent_same_lane_and_drops_singletons():
    from rule_engine.advise_cli import propose_flow_groups
    from rule_engine.layout.model import DiagramSpec, NodeSpec
    spec = DiagramSpec(
        diagram_id="p", diagram_name="p", axis="left-right",
        nodes=(
            NodeSpec(id="x0", role="lb", lane="edge", region="", slot=0),
            NodeSpec(id="x1", role="lb", lane="edge", region="", slot=1),
            NodeSpec(id="w0", role="serverless_fn", lane="workers", region="", slot=0),
        ),
        edges=(), containers=(), flow_lines=(), title="p",
    )
    props = propose_flow_groups(spec)
    # x0+x1 cluster (adjacent slots, same lane); w0 singleton dropped
    assert len(props) == 1
    assert props[0]["members"] == ["x0", "x1"]


def test_proposer_caps_run_at_max_size():
    from rule_engine.advise_cli import propose_flow_groups
    from rule_engine.layout.model import DiagramSpec, NodeSpec
    nodes = tuple(
        NodeSpec(id=f"n{i}", role="serverless_fn", lane="workers", region="", slot=i)
        for i in range(5)
    )
    spec = DiagramSpec(diagram_id="p", diagram_name="p", axis="left-right",
                       nodes=nodes, edges=(), containers=(), flow_lines=(), title="p")
    props = propose_flow_groups(spec, max_size=4)
    # a 5-run splits into a 4-group + the remainder (which, being <2, is dropped)
    assert all(len(g["members"]) <= 4 for g in props)


# --------------------------------------------------------------------------- #
# WS2.4 — flow_steps="panel" (full-height furniture strip) + A4 soft target.
# --------------------------------------------------------------------------- #


def _flow_h(text):
    m = re.search(r'id="flow-legend".*?height="(\d+)"', text, re.S)
    return int(m.group(1)) if m else None


def _assemble(flow_steps, page_h=950, legend_y_flow=40):
    return dl._assemble_document(
        diagram_id="d", diagram_name="d", title="t", boundaries=[], nodes=[],
        routed=[], flow_lines=["Flow", "1. a", "2. b"], legend_x=900,
        legend_y_flow=legend_y_flow, legend_y_legend=200, legend_w=None,
        legend_lines=["Legend", "x"], legend_mode="stack", page_w=1850,
        page_h=page_h, flow_steps=flow_steps,
    )


def test_box_and_document_are_byte_identical_regardless_of_panel_code():
    # box keeps the tight Flow box; document suppresses it. Neither changes.
    box = _assemble("box")
    assert 'id="flow-legend"' in box
    assert box == _assemble("box")
    doc = _assemble("document")
    assert 'id="flow-legend"' not in doc  # Legend takes the top slot


def test_panel_stretches_the_flow_box_to_full_height():
    box_h = _flow_h(_assemble("box"))
    panel_h = _flow_h(_assemble("panel", page_h=950, legend_y_flow=40))
    # panel height = page_h - legend_y_flow - CONTAINER_PAD = 950 - 40 - 30
    assert panel_h == 950 - 40 - dl.CONTAINER_PAD
    assert panel_h > box_h  # a full-height strip, not the tight box


def test_panel_never_shorter_than_the_text():
    # A tiny page cannot shrink the strip below the natural text height.
    tiny = _flow_h(_assemble("panel", page_h=60, legend_y_flow=40))
    box_h = _flow_h(_assemble("box"))
    assert tiny == box_h


def test_unknown_flow_steps_is_rejected():
    import pytest
    with pytest.raises(ValueError, match="unknown flow_steps"):
        dl.build_diagram(
            diagram_id="d", diagram_name="d", title="t", boundaries=[],
            nodes=[], edges=[], flow_lines=["Flow"], legend_x=900,
            legend_y_flow=40, legend_y_legend=200, legend_w=None,
            legend_lines=["Legend"], page_w=1850, page_h=950,
            flow_steps="strip",
        )


# --- A4 soft target in compute_scale -------------------------------------- #

import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from rule_engine import export_raster as er  # noqa: E402


def _canvas(width_px):
    d = tempfile.mkdtemp()
    p = Path(d) / "x.drawio"
    p.write_text(
        f'<mxfile><diagram id="x" name="x"><mxGraphModel pageWidth="2600" '
        f'pageHeight="900"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'<mxCell id="n" value="n" style="rounded=0" vertex="1" parent="1">'
        f'<mxGeometry x="0" y="0" width="{width_px}" height="40" as="geometry"/>'
        f'</mxCell></root></mxGraphModel></diagram></mxfile>',
        encoding="utf-8",
    )
    return p


def test_a4_does_not_inflate_a_small_canvas():
    s = _canvas(300)
    # default caps at MAX; A4 must not push it higher (A4 only ever pulls down)
    assert er.compute_scale(s, diagram_class="flow") == \
        er.compute_scale(s, diagram_class="flow", paper="a4")


def test_a4_pulls_a_medium_canvas_down_toward_a4_width():
    s = _canvas(1400)
    default, _ = er.compute_scale(s, diagram_class="flow")
    a4, _ = er.compute_scale(s, diagram_class="flow", paper="a4")
    assert a4 < default  # pulled down toward A4
    assert a4 >= er.MIN_EXPORT_SCALE


def test_a4_never_drops_below_the_legibility_floor():
    s = _canvas(2400)  # A4 fit would be < floor
    a4, _ = er.compute_scale(s, diagram_class="flow", paper="a4")
    assert a4 == er.MIN_EXPORT_SCALE


def test_a4_default_path_is_unchanged_without_opt_in():
    s = _canvas(1400)
    assert er.compute_scale(s, diagram_class="flow") == \
        er.compute_scale(s, diagram_class="flow", paper=None)

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

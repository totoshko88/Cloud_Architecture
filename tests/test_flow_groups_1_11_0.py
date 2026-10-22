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

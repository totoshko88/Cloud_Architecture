"""1.10.12 WS1 (defect C14): ``pageWidth`` / ``pageHeight`` cover the content.

A caller's page size is an estimate made before the Flow/Legend boxes were
sized and the edges routed. SEP 05 shipped ``pageHeight="602"`` over a content
bottom of 750, and SEP 09 ``1410`` over 1578. ``build_diagram`` now measures the
finished document with the linter's own parser (``geometry.content_bbox``) and
raises each page axis, never lowers it, to the content edge plus one pad.
"""
from __future__ import annotations

import re

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.drawio_model import parse_drawio

_ICON = dl.builtin_icon("shape=mxgraph.aws4.resourceIcon;aspect=fixed;html=1")


def _doc(page_w: int, page_h: int) -> str:
    nodes = [
        dl.Node(id="a", label="svc-a", x=40, y=80, render=_ICON),
        dl.Node(id="b", label="svc-b", x=260, y=80, render=_ICON),
    ]
    return dl.build_diagram(
        diagram_id="d", diagram_name="d", title="t | 2026-10-19 | v1",
        boundaries=[], nodes=nodes, edges=[dl.Edge("e1", "a", "b", "1")],
        flow_lines=["Flow"] + [f"{i}. step {i}" for i in range(1, 30)],
        legend_x=500, legend_y_flow=80, page_w=page_w, page_h=page_h,
    )


def _page(doc: str):
    m = re.search(r'pageWidth="(\d+)" pageHeight="(\d+)"', doc)
    return int(m.group(1)), int(m.group(2))


def _bbox(doc: str):
    return geo.content_bbox(geo.build_geometry(parse_drawio(doc.encode(), path="m")[0]))


def test_short_page_grows_to_cover_the_content() -> None:
    doc = _doc(page_w=300, page_h=200)
    bb = _bbox(doc)
    w, h = _page(doc)
    assert w >= bb.right and h >= bb.bottom
    # Grown to the content edge plus one pad, on the grid.
    assert w % dl.GRID == 0 and h % dl.GRID == 0
    assert w - bb.right <= dl.CONTAINER_PAD + dl.GRID
    assert h - bb.bottom <= dl.CONTAINER_PAD + dl.GRID


def test_covering_page_is_left_unchanged() -> None:
    assert _page(_doc(page_w=4000, page_h=3000)) == (4000, 3000)


def test_only_the_short_axis_grows() -> None:
    w, h = _page(_doc(page_w=4000, page_h=200))
    assert w == 4000
    assert h > 200

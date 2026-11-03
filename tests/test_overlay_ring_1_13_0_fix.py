"""1.13.0 fix (task item 5): an overlay outline actually renders.

``dashed=1`` on an ``image;`` cell has no stroke to dash, and an aws4
``resourceIcon``'s ``strokeColor`` is the glyph colour (recolouring is
forbidden), so the builder draws a separate ``overlayring-<id>`` ring cell
around each standby / supporting / unconfirmed node. The ring is the shape
channel only: it is never a node, a Boundary or a service vertex, the node keeps
its ``overlay=<term>`` token and fillColor, and a standby label ends in
``-standby``.
"""
from __future__ import annotations

import re
from pathlib import Path

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.icon_refs import service_vertices
from rule_engine.linter import lint
from rule_engine.verify_icon import verify_drawio

_LAMBDA = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_FUNC = dl.image_icon("img/lib/azure2/compute/Function_Apps.svg")
_TITLE = "azure t — sub-1 / westeurope | 2026-10-19 | v1"
_REPO = Path(__file__).resolve().parent.parent


def _build() -> str:
    acct = dl.Boundary(id="boundary-acct", label="sub-1", x=60, y=60, w=760, h=260,
                       stroke="#0078D4")
    nodes = [
        dl.Node(id="a", label="api", x=120, y=150, render=_LAMBDA),
        dl.Node(id="s", label="api", x=340, y=150, render=_FUNC, overlay="standby"),
        dl.Node(id="m", label="monitor", x=560, y=150, render=_LAMBDA, overlay="supporting"),
    ]
    edges = [dl.Edge(id="e1", source="a", target="s", marker="1")]
    legend = list(dl.legend_lines_for([])) + list(dl.overlay_legend_lines(nodes))
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[acct],
        nodes=nodes, edges=edges, flow_lines=["Flow", "1. a calls the standby"],
        legend_x=900, legend_lines=legend, page_w=1400, page_h=500,
    )


def _cell(text: str, cid: str) -> str:
    m = re.search(r'<mxCell id="' + re.escape(cid) + r'".*?</mxCell>', text, re.S)
    assert m, cid
    return m.group(0)


def test_standby_image_node_gets_a_dashed_ring_and_a_standby_label():
    text = _build()
    ring = _cell(text, "overlayring-s")
    assert "dashPattern=6 4" in ring and "fillColor=none" in ring
    assert 'parent="boundary-acct"' in ring
    # ring = icon box inflated by 4px, relative to the same host origin
    assert 'x="276" y="86" width="86" height="86"' in ring
    node = _cell(text, "s")
    assert 'value="api-standby"' in node
    assert "overlay=standby" in node


def test_supporting_node_gets_a_dotted_ring_and_keeps_its_fill():
    text = _build()
    ring = _cell(text, "overlayring-m")
    assert "dashPattern=1 3" in ring
    node = _cell(text, "m")
    assert "fillColor=#ED7100" in node and "overlay=supporting" in node
    assert 'value="monitor"' in node  # only standby gets a label suffix
    assert "overlayring-a" not in text


def test_ring_is_not_a_node_boundary_or_service_vertex(tmp_path):
    text = _build()
    page = parse_drawio(text, path="t.drawio")[0]
    g = geo.build_geometry(page)
    assert set(g.nodes) == {"a", "s", "m"}
    assert not any(c.startswith("overlayring-") for c in g.containers)
    assert all(not c.id.startswith("overlayring-") for c in service_vertices(page))
    path = tmp_path / "01-t.drawio"
    path.write_text(text, encoding="utf-8")
    (art,) = parse_artifacts(str(path))
    assert sorted(art.node_names) == ["api", "api-standby", "monitor"]
    rules = {f["rule"] for f in lint(art)["findings"]}
    # the supporting node has no edge; its overlay still exempts it
    assert "node-connectivity" not in rules
    assert "container-padding" not in rules and "node-overlap" not in rules


def test_verify_icon_strict_is_clean(tmp_path):
    path = tmp_path / "01-t.drawio"
    path.write_text(_build(), encoding="utf-8")
    report = verify_drawio(str(path), workspace_root=str(_REPO))
    assert report["unresolved"] == 0 and report["unverified"] == 0
    assert report["service_vertices"] == 3

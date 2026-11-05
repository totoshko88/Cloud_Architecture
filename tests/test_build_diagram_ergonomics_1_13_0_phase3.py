"""1.13.0 phase 3 (item 14): build_diagram ergonomics.

* ``Callout`` cell type: a padded ``overlay=callout`` text cell, not a node.
* custom ``render=`` callable keeps the ``scope=`` / ``external=1`` tokens.
* document-mode Legend lands under the short index, not the full step list.
"""
from __future__ import annotations

from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.drawio_model import parse_drawio

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"


def _build(nodes, **kw):
    kw.setdefault("flow_lines", ["Flow"])
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=[], legend_x=900,
        page_w=1200, page_h=600, **kw,
    )


def test_callout_is_a_padded_overlay_cell_not_a_node():
    nodes = [dl.Node("a", "svc", 120, 120, render=_ICON)]
    xml = _build(nodes, callouts=[dl.Callout("c1", "VPC-attached Lambda", 400, 120)])
    assert 'id="c1"' in xml and "overlay=callout" in xml
    assert "spacingLeft=" in xml  # standard text-box padding
    g = geo.build_geometry(parse_drawio(xml, path="t.drawio")[0])
    assert "c1" not in g.nodes  # a callout is a text cell, not a node


def test_callouts_default_is_byte_identical():
    nodes = [dl.Node("a", "svc", 120, 120, render=_ICON)]
    assert _build(nodes) == _build(nodes, callouts=[])


def test_custom_renderer_keeps_scope_and_external_tokens():
    def custom(node, parent_id):
        # a bespoke renderer that does NOT call overlay_suffix
        return (f'        <mxCell id="{node.id}" value="{node.label}" '
                f'style="rounded=1;fillColor=#eee;" vertex="1" parent="{parent_id}">\n'
                f'          <mxGeometry x="{node.x}" y="{node.y}" width="78" height="78" as="geometry" />\n'
                "        </mxCell>\n")
    nodes = [dl.Node("a", "svc", 120, 120, render=custom, scope="regional", external=True)]
    xml = _build(nodes)
    assert "scope=regional" in xml
    assert "external=1" in xml


def test_document_mode_legend_lands_under_the_index_not_the_step_list():
    nodes = [dl.Node("a", "svc", 120, 120, render=_ICON)]
    flow = ["Flow"] + [f"{i}. step {i}" for i in range(1, 25)]  # 24 steps
    # caller passes a large legend_y_legend sized for the 24-step list.
    xml = _build(nodes, flow_lines=flow, flow_steps="document", legend_y_legend=1600)
    import re
    # the Legend cell's y must be near the short index, not ~1600.
    m = re.search(r'id="legend"[^>]*>\s*<mxGeometry x="\d+" y="(\d+)"', xml)
    assert m is not None
    assert int(m.group(1)) < 600, m.group(1)

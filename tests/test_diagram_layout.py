"""Unit tests for the shared diagram layout builder (``rule_engine.diagram_layout``).

These guard the canonical layout standard (diagram-standards.md → Layout
Geometry): a uniform 78x78 icon footprint, labels that hug the icon, built-in
and OCI icon renderers producing exactly one top-level node, and the OCI stencil
embedding stripping the baked-in caption while scaling the icon square.
"""

from __future__ import annotations

from rule_engine import diagram_layout as dl
from rule_engine.cli import _parse_drawio


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
    # Caption removed; label carried once by the container.
    assert "Oracle Sans" not in xml
    assert 'value="api-function"' in xml
    # Container is a 78x78 group; the icon (84 wide) is scaled down (< 84).
    assert 'width="78" height="78"' in xml
    assert 'width="84.000"' not in xml


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

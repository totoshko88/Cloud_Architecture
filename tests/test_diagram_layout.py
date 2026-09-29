"""Unit tests for the shared diagram layout builder (``rule_engine.diagram_layout``).

These guard the canonical layout standard (diagram-standards.md → Layout
Geometry): a uniform 78x78 icon footprint, labels that hug the icon, built-in
and OCI icon renderers producing exactly one top-level node, and the OCI stencil
embedding stripping the baked-in caption while scaling the icon square.
"""

from __future__ import annotations

from rule_engine import diagram_layout as dl
from rule_engine.cli import _parse_drawio_page
from rule_engine.drawio_model import parse_drawio


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

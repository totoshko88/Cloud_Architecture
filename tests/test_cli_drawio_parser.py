"""Unit tests for the ``.drawio`` parser in :mod:`rule_engine.cli`.

These guard the *top-level node* counting rule: when a node embeds a provider
glyph as a nested stencil group (as the OCI golden example does, because OCI
ships no built-in draw.io library), the glyph's many ``vertex`` sub-cells are
that node's internal geometry — not separate diagram nodes. The parser must
count only vertices parented to the root layer or a Boundary container, so a
diagram with richly embedded glyphs still reports its true node count and does
not spuriously trip ``node-count`` / ``node-quote``.
"""

from __future__ import annotations

from rule_engine.cli import parse_artifact, _parse_drawio
from rule_engine.linter import lint


def _wrap(body: str) -> str:
    return (
        '<mxfile><diagram id="d" name="d"><mxGraphModel><root>'
        '<mxCell id="0" /><mxCell id="1" parent="0" />'
        f"{body}"
        "</root></mxGraphModel></diagram></mxfile>"
    )


def test_top_level_nodes_counted_glyph_subcells_ignored():
    """A node with an embedded glyph group counts as ONE node, not many."""
    # One real top-level node with two nested glyph sub-cells (vertices).
    body = (
        '<mxCell id="svc" value="api-function" style="group;html=1" '
        'vertex="1" parent="1"><mxGeometry x="40" y="40" width="80" height="80" as="geometry"/></mxCell>'
        '<mxCell id="svc-g1" style="shape=stencil(AAAA);html=1" vertex="1" parent="svc">'
        '<mxGeometry width="80" height="80" as="geometry"/></mxCell>'
        '<mxCell id="svc-g2" style="shape=stencil(BBBB);html=1" vertex="1" parent="svc-g1">'
        '<mxGeometry x="4" y="4" width="40" height="40" as="geometry"/></mxCell>'
    )
    art = _parse_drawio("mem.drawio", _wrap(body))
    assert art.node_names == ["api-function"]
    assert len(art.node_names) == 1


def test_boundary_container_children_are_nodes():
    """Vertices parented to a Boundary container are top-level nodes."""
    body = (
        '<mxCell id="boundary-vpc" value="vpc" style="dashed=1;fillColor=none" '
        'vertex="1" parent="1"><mxGeometry width="400" height="300" as="geometry"/></mxCell>'
        '<mxCell id="a" value="Api" style="rounded=1" vertex="1" parent="boundary-vpc">'
        '<mxGeometry width="60" height="40" as="geometry"/></mxCell>'
        '<mxCell id="b" value="Db" style="rounded=1" vertex="1" parent="1">'
        '<mxGeometry width="60" height="40" as="geometry"/></mxCell>'
    )
    art = _parse_drawio("mem.drawio", _wrap(body))
    # The two service nodes count; the boundary container itself does not.
    assert sorted(art.node_names) == ["Api", "Db"]


def test_embedded_glyph_diagram_does_not_trip_node_count():
    """A 13-glyph-subcell node stays under the 12-node cap (one real node)."""
    subcells = "".join(
        f'<mxCell id="g{i}" style="shape=stencil(X);html=1" vertex="1" parent="svc">'
        f'<mxGeometry width="10" height="10" as="geometry"/></mxCell>'
        for i in range(20)
    )
    body = (
        '<mxCell id="svc" value="only-node" style="group;html=1" vertex="1" parent="1">'
        '<mxGeometry width="80" height="80" as="geometry"/></mxCell>'
        f"{subcells}"
    )
    art = _parse_drawio("mem.drawio", _wrap(body))
    assert len(art.node_names) == 1
    result = lint(art)
    rules = {f["rule"] for f in result["findings"]}
    assert "node-count" not in rules
    assert "node-quote" not in rules

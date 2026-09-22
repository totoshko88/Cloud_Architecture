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


# --- REVIEW.md C2: icon-resolved fires on real placeholder styles -----------


def test_icon_resolved_fires_on_placeholder_style():
    """A node with shape=none / empty style is unresolved -> icon-resolved ERROR."""
    body = (
        '<mxCell id="ok" value="s3" style="shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.s3" '
        'vertex="1" parent="1"><mxGeometry width="78" height="78" as="geometry"/></mxCell>'
        '<mxCell id="ph" value="ph" style="shape=none" '
        'vertex="1" parent="1"><mxGeometry width="78" height="78" as="geometry"/></mxCell>'
    )
    art = _parse_drawio("mem.drawio", _wrap(body))
    result = lint(art)
    rules = {f["rule"] for f in result["findings"]}
    assert "icon-resolved" in rules


def test_generic_shapeless_box_is_resolved():
    """The generic profile's fill/stroke box (no shape=) is a resolved icon."""
    body = (
        '<mxCell id="g" value="store" '
        'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000" '
        'vertex="1" parent="1"><mxGeometry width="78" height="78" as="geometry"/></mxCell>'
    )
    art = _parse_drawio("mem.drawio", _wrap(body))
    result = lint(art)
    rules = {f["rule"] for f in result["findings"]}
    assert "icon-resolved" not in rules


# --- REVIEW.md C4: AWS group container is not counted as a node -------------


def test_aws_group_boundary_not_counted_as_node():
    """A mxgraph.aws4.group container (dashed=0) is a boundary, not a node."""
    body = (
        '<mxCell id="boundary-account" value="Account" '
        'style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;dashed=0;'
        'fillColor=none;strokeColor=#232F3E" vertex="1" parent="1">'
        '<mxGeometry width="800" height="400" as="geometry"/></mxCell>'
        '<mxCell id="n1" value="svc" style="shape=mxgraph.aws4.resourceIcon" '
        'vertex="1" parent="boundary-account">'
        '<mxGeometry width="78" height="78" as="geometry"/></mxCell>'
    )
    art = _parse_drawio("mem.drawio", _wrap(body))
    # Only the service node counts; the group container does not.
    assert art.node_names == ["svc"]

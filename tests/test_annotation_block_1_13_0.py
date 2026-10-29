"""1.13.0 (feedback G): a first-class annotation / non-service labelled block
that may terminate an edge.

The feedback (Philips, IHTC) noted that an element with no official provider
glyph (Bedrock Guardrails, the MCP Connect Service) had to be drawn as a
``text;``-prefixed rectangle. A text cell is correctly excluded from
``node-count`` and ``verify-icon --strict``, but an edge whose endpoint is a
text cell resolved to no placeable box, so ``check_structural_integrity`` fired
``edge-unresolved-source/target`` and such a hop could not be drawn at all — the
two labelled rectangles had to carry NO graph edges, their relationship conveyed
only by the numbered Flow text.

The ``role="annotation"`` node closes that gap: it renders as a dashed titled
box marked ``kiroAnnotation=1`` (a ``text;`` cell, so node-count / verify-icon
still skip it) AND is recorded in ``DiagramGeometry.annotations`` so it is a
placeable edge endpoint. It is kept OUT of ``geo.nodes`` so routing-pierce /
geometric-containment / node-connectivity never treat it as a service node.

Additive + default-inert: the renderer/geometry branches fire only on
``role="annotation"`` / the ``kiroAnnotation=1`` marker, and no shipped golden
uses either, so ``regen_examples.py --check`` is byte-identical.
"""

from __future__ import annotations

from rule_engine import draw_cli as dc
from rule_engine import geometry as geo
from rule_engine.diagram_layout import build_diagram, legend_lines_for
from rule_engine.drawio_model import parse_drawio
from rule_engine.icon_refs import service_vertices
from rule_engine.layout_engine import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec


def _spec():
    """A service node whose edge TERMINATES on an annotation block."""
    return DiagramSpec(
        diagram_id="g", diagram_name="g", axis="left-right",
        nodes=(
            NodeSpec(id="agent", role="lambda", lane="workers", region="", slot=0),
            NodeSpec(id="guardrails", role="annotation", lane="platform",
                     region="", slot=0),
        ),
        edges=(EdgeSpec(id="e1", source="agent", target="guardrails",
                        marker="1"),),
        containers=(ContainerSpec(id="acct", kind="account", region="",
                                  parent=None, label_key="account"),),
        flow_lines=("Flow", "1. Agent calls Bedrock Guardrails"),
        title="g | 2025-01-15 | v1",
    )


def _render(spec):
    placed = layout(spec)
    renderers = dc._skin_renderers("aws", spec.nodes)
    nodes = dc._nodes_from(placed, renderers)
    edges = dc._edges_from(placed)
    boundaries = dc._boundaries_from(placed, "aws", {})
    pw, ph = dc._page_size(placed)
    xml = build_diagram(
        diagram_id=spec.diagram_id, diagram_name=spec.diagram_name,
        title=spec.title, boundaries=boundaries, nodes=nodes, edges=edges,
        flow_lines=spec.flow_lines, legend_lines=legend_lines_for(boundaries),
        legend_x=placed.legend_x, legend_w=placed.legend_w, page_w=pw, page_h=ph,
    )
    return placed, xml


def test_annotation_is_a_placed_edge_endpoint_no_edge_unresolved():
    placed, xml = _render(_spec())
    # It is a real placed box (routable endpoint).
    assert "guardrails" in placed.nodes
    g = geo.build_geometry(parse_drawio(xml, path="<t>.drawio")[0])
    # Recorded as an annotation, NOT a service node.
    assert "guardrails" in g.annotations
    assert "guardrails" not in g.nodes
    # The edge to it resolves — no structural-integrity edge-unresolved.
    si = geo.check_structural_integrity(g)
    assert si == [], f"unexpected structural-integrity findings: {si}"


def test_annotation_renders_as_a_text_kiro_marked_cell():
    _, xml = _render(_spec())
    # The cell is a text; cell carrying the annotation marker.
    assert 'id="guardrails"' in xml
    import re
    m = re.search(r'id="guardrails"[^>]*style="([^"]*)"', xml)
    assert m is not None
    style = m.group(1)
    assert style.startswith("text;"), style
    assert "kiroAnnotation=1" in style, style


def test_annotation_is_not_counted_or_icon_verified():
    _, xml = _render(_spec())
    page = parse_drawio(xml, path="<t>.drawio")[0]
    sv = [c.id for c in service_vertices(page)]
    # node-count AND verify-icon --strict both read service_vertices; the
    # annotation must be absent from it, the service node present.
    assert "guardrails" not in sv, "annotation wrongly counted as a service node"
    assert "agent" in sv


def test_plain_text_furniture_is_still_not_a_legal_endpoint():
    # A non-marked text box (Flow / Legend furniture) must NOT become a placeable
    # endpoint — only the kiroAnnotation marker opts a text cell in.
    xml = (
        '<mxfile><diagram><mxGraphModel><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="note" value="Flow" style="text;html=1;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="200" height="80" as="geometry"/></mxCell>'
        '<mxCell id="svc" value="svc" style="shape=image;image=x.svg;" vertex="1" parent="1">'
        '<mxGeometry x="400" y="0" width="48" height="48" as="geometry"/></mxCell>'
        '<mxCell id="e1" style="endArrow=block;" edge="1" parent="1" source="svc" target="note">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>'
        '</root></mxGraphModel></diagram></mxfile>'
    )
    g = geo.build_geometry(parse_drawio(xml, path="<t>.drawio")[0])
    assert "note" not in g.annotations
    si = dict(geo.check_structural_integrity(g))
    # The edge to the unmarked furniture IS unresolved (the marker is required).
    assert si.get("e1") == "edge-unresolved-target:note"

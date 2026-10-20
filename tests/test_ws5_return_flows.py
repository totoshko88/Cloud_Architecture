"""1.10.12 WS5: return flows, dropped steps, islands (defects C2, C3, C13).

Pinned here on small synthetic diagrams:

* **return bus** — a leftward / response edge whose ordinary loop runs between
  content rows (and so cuts the forward flow) moves to a lane OUTSIDE every
  content row it spans: in the scored layout search (``return-bus-*`` variants,
  judged like a face swap) and in the final crossing-repair pass;
* **lint** — ``flow-step-undrawn`` reports a numbered Flow step no edge draws
  (unless the line says ``(not drawn)``); ``graph-islands`` reports a landscape
  whose connected nodes split into several components;
* **supporting overlay** — an ops / observability node marked
  ``overlay=supporting`` is exempt from ``node-connectivity`` and
  ``graph-islands``, and must be documented in the Legend.
"""
from __future__ import annotations

from dataclasses import replace

from rule_engine import crossing_repair as cr
from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box
from rule_engine.layout import routers, variants
from rule_engine.layout.corridors import CorridorAllocator
from rule_engine.layout.model import EdgeSpec
from rule_engine.linter import lint

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-20 | v1"


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _build(nodes, edges, flow=None, legend_lines=None, **kw):
    flow = flow if flow is not None else ["Flow"] + [f"{e.marker}. step" for e in edges]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=flow, legend_x=900,
        legend_lines=legend_lines, page_w=1200, page_h=900, **kw,
    )


def _findings(tmp_path, text, rule, diagram_class=None):
    path = tmp_path / "01-t.drawio"
    path.write_text(text, encoding="utf-8")
    out = []
    for art in parse_artifacts(str(path)):
        if diagram_class:
            art = replace(art, diagram_class=diagram_class)
        out += [f for f in lint(art)["findings"] if f["rule"] == rule]
    return out


def _crossings(g) -> int:
    return sum(n for *_ab, n in cr.crossing_pairs(g))


# --------------------------------------------------------------------------- #
# Return bus
# --------------------------------------------------------------------------- #


def _reply_case():
    """A forward edge A -> X drops through the gap between the two rows; the
    reply D -> T loops back BETWEEN the rows (the ordinary back-edge corridor)
    and cuts that drop (SEP 05 ``e7`` in miniature)."""
    nodes = [dl.Node("a", "A", 100, 120, render=_ICON),
             dl.Node("t", "T", 100, 280, render=_ICON),
             dl.Node("d", "D", 540, 280, render=_ICON),
             dl.Node("x", "X", 320, 440, render=_ICON)]
    edges = [
        dl.Edge("e1", "a", "x", "1", exit=(1.0, 0.5128205128205128), entry=(0.0, 0.5128205128205128),
                points=((210, 160), (210, 480))),
        dl.Edge("e2", "d", "t", "2", exit=(1.0, 0.5128205128205128), entry=(0.0, 0.5128205128205128),
                points=((640, 320), (640, 370), (80, 370), (80, 320))),
    ]
    return nodes, edges


def test_repair_moves_a_reply_onto_the_return_bus():
    nodes, edges = _reply_case()
    before = _geo(_build(nodes, edges, caption_safe=False))
    assert _crossings(before) == 1
    after = _geo(_build(nodes, edges))
    assert _crossings(after) == 0
    e2 = next(e for e in after.edges if e.id == "e2")
    poly = geo.edge_polyline(after, e2)
    lanes = [p[1] for p, q in zip(poly, poly[1:]) if abs(p[1] - q[1]) < 1 and abs(p[0] - q[0]) > 100]
    top = min(b.y for b in after.nodes.values())
    low = max(b.bottom for b in after.nodes.values()) + geo.LABEL_BAND
    # The long run sits outside every content row: above the top row or below
    # the lowest caption, never between the rows.
    assert lanes and all(y < top or y > low for y in lanes), lanes
    assert e2.exit[0] >= 1.0 and (e2.entry[0] <= 0.0 or e2.entry[1] <= 0.0)
    assert geo.check_edge_direction(after) == []
    assert geo.check_edge_approach(after) == []


def test_bus_shapes_only_for_return_edges():
    nodes, edges = _reply_case()
    g = _geo(_build(nodes, edges, caption_safe=False))
    by_id = {e.id: e for e in g.edges}
    assert cr.is_return_edge(g, by_id["e2"]) and cr.bus_shapes(g, by_id["e2"])
    assert not cr.is_return_edge(g, by_id["e1"]) and cr.bus_shapes(g, by_id["e1"]) == []


def _boxes():
    return {
        "a": Box("a", 100, 120, 78, 78),
        "t": Box("t", 100, 280, 78, 78),
        "d": Box("d", 540, 280, 78, 78),
        "x": Box("x", 320, 440, 78, 78),
    }


def test_return_bus_variants_are_offered_for_a_return_edge_only():
    placed = _boxes()
    back = EdgeSpec(id="r", source="d", target="t", marker="2")
    fwd = EdgeSpec(id="f", source="a", target="x", marker="1")
    vs = variants.generate(back, placed, {}, "back-edge")
    bus = [v for v in vs if v.plan in (variants.RoutePlan.RETURN_BUS_ABOVE,
                                       variants.RoutePlan.RETURN_BUS_BELOW)]
    assert {v.id for v in bus} == {"r/return-bus-above-top", "r/return-bus-above-left",
                                   "r/return-bus-below-left"}
    assert all(v.face_swap for v in bus)          # judged on strictly fewer crossings
    assert all(v.exit[0] >= 1.0 for v in bus)     # right exit (Variant A)
    # Not part of the routing-order key, and never for a forward edge.
    assert not any(v.plan.name.startswith("RETURN_BUS")
                   for v in variants.generate(back, placed, {}, "back-edge", faces=False))
    assert not any(v.plan.name.startswith("RETURN_BUS")
                   for v in variants.generate(fwd, placed, {}, "cross-region"))


def test_router_lays_the_bus_outside_the_content_rows():
    placed = _boxes()
    obstacles = list(placed.values())
    back = EdgeSpec(id="r", source="d", target="t", marker="2")
    for bus, entry in (("above", (0.5, 0.0)), ("above", (0.0, 0.5)), ("below", (0.0, 0.5))):
        pts = routers.route_back_edge(back, (1.0, 0.5), entry, CorridorAllocator(),
                                      obstacles, {}, bus=bus)
        ys = [p[1] for p in pts]
        if bus == "above":
            assert min(ys) < 120, (bus, entry, pts)   # above the topmost row (A)
        else:
            assert max(ys) > 518, (bus, entry, pts)   # below the lowest row (X)
        assert pts[0][0] > 618                        # rises in the gap right of D


# --------------------------------------------------------------------------- #
# flow-step-undrawn
# --------------------------------------------------------------------------- #


def _two_nodes():
    return [dl.Node("a", "A", 100, 120, render=_ICON),
            dl.Node("b", "B", 320, 120, render=_ICON)]


def test_flow_step_undrawn_reports_a_step_with_no_edge(tmp_path):
    edges = [dl.Edge("e1", "a", "b", "1", exit=(1.0, 0.5), entry=(0.0, 0.5))]
    text = _build(_two_nodes(), edges, flow=["Flow", "1. a to b", "2. b replies to a", "3. b logs"])
    hits = _findings(tmp_path, text, "flow-step-undrawn")
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert hits[0]["reason"] == "undrawn-steps:2,3"
    assert list(hits[0]["offenders"]) == ["step-2", "step-3"]


def test_flow_step_marked_not_drawn_is_exempt(tmp_path):
    edges = [dl.Edge("e1", "a", "b", "1", exit=(1.0, 0.5), entry=(0.0, 0.5))]
    text = _build(_two_nodes(), edges,
                  flow=["Flow", "Ingress (1-2)", "1. a to b", "2. b audits a (not drawn)"])
    assert _findings(tmp_path, text, "flow-step-undrawn") == []


# --------------------------------------------------------------------------- #
# graph-islands
# --------------------------------------------------------------------------- #


def _islands_case(link=False, supporting=False):
    nodes = [dl.Node("a", "A", 100, 120, render=_ICON),
             dl.Node("b", "B", 320, 120, render=_ICON),
             dl.Node("c", "C", 100, 320, render=_ICON),
             dl.Node("d", "D", 320, 320, render=_ICON)]
    edges = [dl.Edge("e1", "a", "b", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
             dl.Edge("e2", "c", "d", "2", exit=(1.0, 0.5), entry=(0.0, 0.5))]
    if link:
        edges.append(dl.Edge("e3", "b", "d", "3", exit=(0.5, 1.0), entry=(0.5, 0.0)))
    legend = None
    if supporting:
        nodes.append(dl.Node("mon", "Monitoring", 540, 320, render=_ICON, overlay="supporting"))
        legend = list(dl.STANDARD_LEGEND_LINES) + list(dl.overlay_legend_lines(nodes))
    return nodes, edges, legend


def test_graph_islands_reports_a_split_landscape(tmp_path):
    nodes, edges, _ = _islands_case()
    text = _build(nodes, edges)
    hits = _findings(tmp_path, text, "graph-islands", diagram_class="landscape")
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert hits[0]["reason"] == "islands:2"
    assert sorted(hits[0]["offenders"]) == ["c", "d"]
    # A flow is not judged (a narrative view may hold two short paths).
    assert _findings(tmp_path, text, "graph-islands") == []


def test_graph_islands_is_silent_once_connected(tmp_path):
    nodes, edges, _ = _islands_case(link=True)
    assert _findings(tmp_path, _build(nodes, edges), "graph-islands",
                     diagram_class="landscape") == []


# --------------------------------------------------------------------------- #
# supporting overlay
# --------------------------------------------------------------------------- #


def test_supporting_overlay_is_a_sanctioned_connectivity_exemption(tmp_path):
    nodes, edges, legend = _islands_case(link=True, supporting=True)
    text = _build(nodes, edges, legend_lines=legend)
    assert "overlay=supporting" in text and "dashPattern=1 3" in text
    g = _geo(text)
    assert g.overlay_nodes.get("mon") == "supporting"
    assert geo.check_node_connectivity(g) == []
    assert geo.graph_components(g) == [["a", "b", "c", "d"]]
    assert _findings(tmp_path, text, "node-connectivity", diagram_class="landscape") == []
    assert _findings(tmp_path, text, "graph-islands", diagram_class="landscape") == []
    assert _findings(tmp_path, text, "overlay-legend-coverage") == []


def test_supporting_overlay_must_be_documented_in_the_legend(tmp_path):
    nodes, edges, _legend = _islands_case(link=True, supporting=True)
    text = _build(nodes, edges)          # standard Legend: no ``supporting`` line
    hits = _findings(tmp_path, text, "overlay-legend-coverage")
    assert len(hits) == 1 and "supporting" in hits[0]["offenders"]


def test_unmarked_edgeless_node_still_trips_connectivity(tmp_path):
    nodes, edges, _ = _islands_case(link=True)
    nodes.append(dl.Node("mon", "Monitoring", 540, 320, render=_ICON))
    hits = _findings(tmp_path, _build(nodes, edges), "node-connectivity")
    assert len(hits) == 1 and "mon" in hits[0]["offenders"]

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


def _nest_case():
    """Two replies from ``s`` to targets stacked in one column (SEP 05 ``e3`` /
    ``e7`` in miniature): ``hi`` on the top row, ``lo`` one row below it. The
    reply to ``lo`` has to detour past ``hi``, so it reaches farther."""
    placed = {
        "hi": Box("hi", 100, 280, 78, 78),
        "lo": Box("lo", 100, 440, 78, 78),
        "mid": Box("mid", 320, 280, 78, 78),
        "s": Box("s", 540, 280, 78, 78),
    }
    edges = (EdgeSpec(id="r1", source="s", target="hi", marker="1"),
             EdgeSpec(id="r2", source="s", target="lo", marker="2"))
    return placed, edges


def _spec(edges, placed):
    from rule_engine.layout.model import DiagramSpec, NodeSpec
    nodes = tuple(NodeSpec(id=n, role="serverless_fn", lane="edge", region="", slot=i)
                  for i, n in enumerate(placed))
    return DiagramSpec(diagram_id="t", diagram_name="t", axis="left-right",
                       nodes=nodes, edges=edges, containers=(), flow_lines=("Flow",),
                       title=_TITLE)


def test_return_bus_nesting_ranks_the_farther_reply_outermost():
    placed, edges = _nest_case()
    nest = routers.decide_return_bus_nesting(
        _spec(edges, placed), placed, {"r1": (1.0, 0.5), "r2": (1.0, 0.5)})
    # Upper bus: the reply to the LOWER target detours past the upper one, so
    # it is the outer run (rank 0); the lower bus mirrors it.
    assert nest["r2"]["above"] == (0, 2) and nest["r1"]["above"] == (1, 2)
    assert nest["r1"]["below"] == (0, 2) and nest["r2"]["below"] == (1, 2)
    # Two merged centre exits are spread so the runs leave in nesting order:
    # the outer run's stub passes beyond the inner rise, so on the upper bus
    # the inner run (r1) takes the upper band, and on the lower bus the outer
    # run (r1 there) does.
    assert variants._bus_exit_band(nest["r1"], "above") < variants._bus_exit_band(nest["r2"], "above")
    assert variants._bus_exit_band(nest["r1"], "below") < variants._bus_exit_band(nest["r2"], "below")
    # A single reply per source is not ranked.
    assert routers.decide_return_bus_nesting(_spec(edges[:1], placed), placed) == {}


def _lay_nested(order):
    placed, edges = _nest_case()
    nest = routers.decide_return_bus_nesting(_spec(edges, placed), placed)
    alloc = CorridorAllocator()
    alloc.bus_rank = nest
    by_id = {e.id: e for e in edges}
    out = {}
    for eid in order:
        exit_pt = (1.0, variants._bus_exit_band(nest[eid], "above"))
        pts = routers.route_back_edge(by_id[eid], exit_pt, (0.5, 0.0), alloc,
                                      list(placed.values()), {}, bus="above")
        s, t = placed["s"], placed[by_id[eid].target]
        out[eid] = [routers._contact_point(s, exit_pt)] + list(pts) + [
            routers._contact_point(t, (0.5, 0.0))]
    return out


def test_nested_bus_runs_do_not_depend_on_routing_order_and_never_cross():
    a, b = _lay_nested(("r1", "r2")), _lay_nested(("r2", "r1"))
    assert a == b                                   # rank, not routing order
    r1, r2 = a["r1"], a["r2"]
    lane = {k: min(p[1] for p in v) for k, v in a.items()}
    rise = {k: v[1][0] for k, v in a.items()}
    assert lane["r2"] < lane["r1"]                  # outer lane farther from the rows
    assert rise["r2"] > rise["r1"]                  # outer rise farther from the source
    assert not any(geo.segments_cross(p, q) for p in zip(r1, r1[1:]) for q in zip(r2, r2[1:]))


def _sep05_text() -> str:
    import importlib.util
    from pathlib import Path
    path = (Path(__file__).parent / "fixtures" / "sep" / "scripts"
            / "build_flow_sandbox_lifecycle.py")
    spec = importlib.util.spec_from_file_location("_sep05_builder", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._build()


def test_sep05_replies_nest_on_the_upper_bus_with_no_crossing():
    """WS5 review F1: SEP 05 ``e3`` (Syndicate -> activation-queue) and ``e7``
    (Syndicate -> deletion-notification-queue) both ride the upper bus. ``e7``
    reaches farther left (it detours past activation-queue), so it is the
    outer run: higher lane, rise column farther right, lower exit band. Before
    the fix the lanes came out of routing order and ``e3``'s drop cut ``e7``'s
    lane (one crossing)."""
    g = _geo(_sep05_text())
    assert cr.crossing_pairs(g) == []
    polys = {e.id: geo.edge_polyline(g, e) for e in g.edges if e.id in ("e3", "e7")}

    def long_lane(poly):
        return min(p[1] for p, q in zip(poly, poly[1:])
                   if abs(p[1] - q[1]) < 1 and abs(p[0] - q[0]) > 300)

    def rise_x(poly):
        return next(p[0] for p, q in zip(poly, poly[1:]) if abs(p[0] - q[0]) < 1)

    assert long_lane(polys["e7"]) < long_lane(polys["e3"])
    assert rise_x(polys["e7"]) > rise_x(polys["e3"])
    exits = {e.id: e.exit for e in g.edges if e.id in ("e3", "e7")}
    assert exits["e7"][1] > exits["e3"][1]


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

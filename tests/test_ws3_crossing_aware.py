"""1.10.12 WS3: crossing-aware contact selection (defect C7).

Pinned here on small synthetic diagrams:

* **final crossing-repair pass** — ``build_diagram`` re-routes an edge of a
  crossing pair onto another legal face (SEP 09 ``e3``: a back-edge into the
  target's LEFT face, where another edge already arrives, moves to the TOP
  face) and swaps two converging corridors nested the wrong way (SEP 01
  ``e4`` / ``e5``), keeping a move only when crossings drop and nothing is
  added;
* **lint** — ``edge-crossing-avoidable`` reports the crossing a single legal
  face swap removes, and stays silent once the engine has removed it;
* **scored search** — ``variants.generate`` offers the other entry face for a
  back-edge (``face_swap``), but not to the routing-order key;
* **converging turns** — fan-outs into one target's left face are nested by
  source distance, not declared order.
"""
from __future__ import annotations

from rule_engine import crossing_repair as cr
from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box
from rule_engine.layout import routers, variants
from rule_engine.layout.model import EdgeSpec
from rule_engine.linter import lint

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _build(nodes, edges, legend_x=900, **kw):
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=["Flow"] + [f"{e.marker}. step" for e in edges],
        legend_x=legend_x, page_w=1200, page_h=900, **kw,
    )


def _crossings(g) -> int:
    return sum(n for *_ab, n in cr.crossing_pairs(g))


def _back_edge_case():
    """SEP 09 e1 / e3: Students -> CloudFront, and Route 53 -> CloudFront back
    into the LEFT face below e1, so its drop cuts e1."""
    nodes = [dl.Node("actor", "Students", 120, 120, render=_ICON),
             dl.Node("cf", "CloudFront", 340, 120, render=_ICON),
             dl.Node("dns", "Route 53", 560, 120, render=_ICON)]
    edges = [
        dl.Edge("e1", "actor", "cf", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
        dl.Edge("e3", "dns", "cf", "3", exit=(1.0, 0.5), entry=(0.0, 0.7692307692307693),
                points=((670, 159), (670, 90), (270, 90), (270, 180))),
    ]
    return nodes, edges


def test_back_edge_moves_to_the_top_face_without_a_crossing():
    nodes, edges = _back_edge_case()
    before = _geo(_build(nodes, edges, caption_safe=False))
    assert _crossings(before) == 1
    after = _geo(_build(nodes, edges))
    assert _crossings(after) == 0
    e3 = next(e for e in after.edges if e.id == "e3")
    assert e3.entry[1] <= 0.0, e3.entry                 # CloudFront's TOP face
    assert e3.exit[0] >= 1.0, e3.exit                   # still leaves the right face
    assert geo.check_edge_direction(after) == []
    assert geo.check_edge_approach(after) == []
    assert geo.check_edge_crosses_own_label(after) == []
    assert cr.avoidable_crossings(after) == (0, [])


def test_lint_reports_the_avoidable_crossing(tmp_path):
    nodes, edges = _back_edge_case()
    hits = {}
    for name, kw in (("01-raw", {"caption_safe": False}), ("02-fixed", {})):
        path = tmp_path / f"{name}.drawio"
        path.write_text(_build(nodes, edges, **kw), encoding="utf-8")
        hits[name] = [f for art in parse_artifacts(str(path)) for f in lint(art)["findings"]
                      if f["rule"] == "edge-crossing-avoidable"]
    raw, fixed = hits["01-raw"], hits["02-fixed"]
    assert len(raw) == 1 and raw[0]["severity"] == "WARNING"
    assert raw[0]["reason"] == "avoidable:1/1"
    assert "e3" in raw[0]["offenders"]
    assert fixed == []


def test_converging_corridors_nested_by_source_position_are_swapped():
    """SEP 01 e4 / e5: two sources below a target's left face; the farther
    source (e5) turned FARTHER from the target, so the two approaches crossed
    twice. Swapping the two corridors removes both crossings."""
    nodes = [dl.Node("hub", "hub", 440, 420, render=_ICON),
             dl.Node("lms", "lms", 40, 560, render=_ICON),
             dl.Node("kc", "keycloak", 40, 730, render=_ICON)]
    edges = [
        dl.Edge("e4", "lms", "hub", "4", exit=(1.0, 0.38461538461538464), entry=(0.0, 0.5128205128205128),
                points=((340, 590), (340, 460))),
        dl.Edge("e5", "kc", "hub", "5", exit=(1.0, 0.2564102564102564), entry=(0.0, 0.8974358974358975),
                points=((320, 750), (320, 490))),
    ]
    before = _geo(_build(nodes, edges, caption_safe=False))
    assert _crossings(before) == 2
    after = _geo(_build(nodes, edges))
    assert _crossings(after) == 0
    e4 = next(e for e in after.edges if e.id == "e4")
    e5 = next(e for e in after.edges if e.id == "e5")
    # The farther source now turns nearer the target.
    assert max(x for x, _ in e5.points) > max(x for x, _ in e4.points)
    assert geo.check_edge_direction(after) == []


def test_repair_keeps_a_clean_diagram_unchanged():
    nodes, edges = _back_edge_case()
    fixed = _build(nodes, edges)
    g = _geo(fixed)
    plan = cr.plan_crossing_repair(g)
    assert plan.routes == {}


def _boxes(**xy):
    return {k: Box(k, x, y, 78, 78) for k, (x, y) in xy.items()}


def test_back_edge_gets_a_face_swap_variant_but_not_in_the_order_key():
    placed = _boxes(cf=(340, 120), dns=(560, 120))
    edge = EdgeSpec(id="e3", source="dns", target="cf", marker="3")
    seed = {"e3": ((1.0, 0.5), (0.0, 0.5))}
    vs = variants.generate(edge, placed, {}, "back-edge", seed)
    # The WS5 return-bus family is judged like a face swap too (``face_swap``)
    # and offers both entry faces; the WS3 face family is the rest.
    faces = [v for v in vs if v.face_swap and "/return-bus-" not in v.id]
    assert faces, [v.id for v in vs]
    assert all(v.entry == (0.5, 0.0) for v in faces)     # the other face: TOP
    assert all(v.rank > max(w.rank for w in vs if not w.face_swap) for v in faces)
    assert vs[0].plan is variants.RoutePlan.RULE_BASED
    plain = variants.generate(edge, placed, {}, "back-edge", seed, faces=False)
    assert not any(v.face_swap for v in plain)
    assert [v.id for v in plain] == [v.id for v in vs if not v.face_swap]


def test_converging_turns_are_ranked_by_source_distance():
    placed = _boxes(hub=(440, 420), far=(40, 730), near=(40, 560))
    # Declared order: the FARTHER source first (the backwards case).
    edges = (EdgeSpec(id="a", source="far", target="hub", marker="1"),
             EdgeSpec(id="b", source="near", target="hub", marker="2"))

    class _Spec:
        pass

    spec = _Spec()
    spec.edges = edges
    entries = {"a": (0.0, 0.75), "b": (0.0, 0.5)}
    assert routers.classify_edge(edges[0], placed) == "fan-out-row"
    ranks = routers.decide_converging_turns(spec, placed, entries)
    assert ranks == {"b": 0, "a": 1}                   # farther source turns nearer

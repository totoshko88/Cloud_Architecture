"""WS8 (1.10.12, defect C5): two unrelated edges never read as one line.

Pinned here on a small synthetic diagram and on the SEP 03 / 08 regression
fixtures:

* **collinear-shift pass** — ``build_diagram`` re-routes one of two unrelated
  edges that share a grid line (parallel legs under two grid steps apart with
  overlapping extents), so the two lines separate; the move is kept only when
  the collinear-pair count drops and no crossing, back-edge or caption strike
  is added;
* **lint** — ``collinear-edges`` reports the pair that reads as one line, and
  stays silent once the engine has separated it;
* **acceptance** — the SEP 03 (coordinate-free) fixture, rebuilt through the
  engine, carries **zero** collinear pairs and SEP 08 at most its recorded
  residual pair, with no more crossings or back-edges than the same diagram
  built with the WS8 pass disabled.
"""
from __future__ import annotations

import pytest

import importlib.util
from pathlib import Path

from rule_engine import collinear_repair as col
from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.caption_routing import CaptionPlan
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.linter import lint

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-10-19 | v1"

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sep" / "scripts"


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _build(nodes, edges, legend_x=1000, **kw):
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=["Flow"] + [f"{e.marker}. step" for e in edges],
        legend_x=legend_x, page_w=1300, page_h=700, **kw,
    )


def _collinear(g) -> list:
    return sorted(col.collinear_pairs(g))


def _crossings(g) -> int:
    polys = {e.id: p for e in g.edges if len(p := geo.edge_polyline(g, e)) >= 2}
    ids = sorted(polys)
    return sum(
        1
        for i, a in enumerate(ids)
        for b in ids[i + 1:]
        for s1 in zip(polys[a], polys[a][1:])
        for s2 in zip(polys[b], polys[b][1:])
        if geo.segments_cross(s1, s2)
    )


def _back_edges(g) -> int:
    return sum(
        1
        for e in g.edges
        if (s := g.nodes.get(e.source)) and (t := g.nodes.get(e.target))
        and t.center()[0] < s.center()[0] - geo.GRID
    )


def _collinear_case():
    """Two unrelated edges whose explicit waypoints share a horizontal
    corridor ten pixels apart (one grid step, under the two-step merge floor),
    so their long runs read as a single line."""
    nodes = [dl.Node("a", "a", 120, 120, render=_ICON),
             dl.Node("b", "b", 760, 120, render=_ICON),
             dl.Node("c", "c", 120, 320, render=_ICON),
             dl.Node("d", "d", 760, 320, render=_ICON)]
    edges = [
        dl.Edge("e1", "a", "b", "1", exit=(1.0, 0.5), entry=(0.0, 0.5),
                points=((260, 230), (620, 230))),
        dl.Edge("e2", "c", "d", "2", exit=(1.0, 0.5), entry=(0.0, 0.5),
                points=((260, 240), (620, 240))),
    ]
    return nodes, edges


# --------------------------------------------------------------------------- #
# The router shift
# --------------------------------------------------------------------------- #


def test_collinear_pair_is_separated_by_the_pass():
    nodes, edges = _collinear_case()
    before = _geo(_build(nodes, edges, caption_safe=False))
    assert _collinear(before) == [("e1", "e2")]
    after = _geo(_build(nodes, edges))
    assert _collinear(after) == []
    # Nothing else worsened.
    assert _crossings(after) <= _crossings(before)
    assert _back_edges(after) <= _back_edges(before)
    assert geo.check_edge_direction(after) == []
    assert geo.check_edge_approach(after) == []
    assert geo.check_edge_crosses_own_label(after) == []


def test_pass_moves_exactly_one_edge_of_the_pair():
    nodes, edges = _collinear_case()
    before = _geo(_build(nodes, edges, caption_safe=False))
    plan, work = col.plan_collinear_shift_geo(before)
    assert set(plan.routes) and set(plan.routes) <= {"e1", "e2"}
    assert len(plan.routes) == 1
    assert col.collinear_pairs(work) == []


def test_pass_keeps_a_clean_diagram_unchanged():
    nodes, edges = _collinear_case()
    fixed = _geo(_build(nodes, edges))          # already separated
    assert col.collinear_pairs(fixed) == []
    plan = col.plan_collinear_shift(fixed)
    assert plan.routes == {}


def test_pass_never_adds_a_crossing_or_a_finding():
    nodes, edges = _collinear_case()
    before = _geo(_build(nodes, edges, caption_safe=False))
    base = col._Base(before, len(geo.collinear_edge_pairs(before)))
    _plan, work = col.plan_collinear_shift_geo(before)
    sc = col._cr._score(work)
    b = base.score
    assert sc.collinear < b.collinear
    assert sc.crossings <= b.crossings
    assert sc.errors <= b.errors and sc.warnings <= b.warnings
    assert sc.own <= b.own and sc.vis <= b.vis


# --------------------------------------------------------------------------- #
# The lint rule
# --------------------------------------------------------------------------- #


def test_lint_reports_the_collinear_pair(tmp_path):
    nodes, edges = _collinear_case()
    hits = {}
    for name, kw in (("01-raw", {"caption_safe": False}), ("02-fixed", {})):
        path = tmp_path / f"{name}.drawio"
        path.write_text(_build(nodes, edges, **kw), encoding="utf-8")
        hits[name] = [f for art in parse_artifacts(str(path)) for f in lint(art)["findings"]
                      if f["rule"] == "collinear-edges"]
    raw, fixed = hits["01-raw"], hits["02-fixed"]
    assert len(raw) == 1 and raw[0]["severity"] == "WARNING"
    # 1.13.0 collinear kinds: besides the side-by-side corridor runs, the two
    # edges' vertical legs at x=260 sit end-to-end on one line 10px apart, so
    # the pair's (most severe) kind is ``end-to-end-merge`` (WARNING on flow).
    assert raw[0]["reason"] == "end-to-end-merge:1"
    assert set(raw[0]["offenders"]) == {"e1", "e2"}
    assert fixed == []


def test_lint_is_silent_when_no_pair_is_collinear(tmp_path):
    nodes, edges = _collinear_case()
    path = tmp_path / "clean.drawio"
    path.write_text(_build(nodes, edges), encoding="utf-8")
    findings = [f for art in parse_artifacts(str(path)) for f in lint(art)["findings"]]
    assert [f for f in findings if f["rule"] == "collinear-edges"] == []


# --------------------------------------------------------------------------- #
# Acceptance on the SEP fixtures (built through the engine)
# --------------------------------------------------------------------------- #


def _load_builder(name: str):
    path = _FIXTURES / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _without_ws8(build):
    """Build with the WS8 collinear pass disabled, to measure the before state."""
    orig = col.plan_collinear_shift_geo

    def off(g):
        return CaptionPlan({}, {}, 0.0), g

    col.plan_collinear_shift_geo = off
    try:
        return build()
    finally:
        col.plan_collinear_shift_geo = orig


#: Collinear pairs left after the WS8 pass, per SEP fixture (FEAT-005, 1.13.0).
#: SEP 03 is the coordinate-free spec the WS8 acceptance was written against
#: (``build_03_coordfree.py``; the synced SEPARCH 03 is hand-pinned, so it
#: exercises no layout); it still reaches zero (one pair, e12/e2, without WS8).
#: SEP 08 is the synced SEPARCH builder, which now materialises each VPC peering
#: into a node with two legs (G23): WS8 separates three of the four pairs it
#: makes (e10-a/e5, e5/e6, e6/e8-a); the remaining one, e5 (RDS -> interface
#: endpoint) beside the e9-a peering leg, has no legal re-route that keeps the
#: crossing count (X 1) and back-edges (2), so it is recorded as the bound.
_SEP_COLLINEAR_BOUND = {
    "build_03_coordfree.py": [],
    "build_08_network_crossaccount.py": [("e5", "e9-a")],
}


@pytest.mark.slow
@pytest.mark.sep
def test_sep_03_and_08_reach_zero_collinear_pairs():
    for script, bound in _SEP_COLLINEAR_BOUND.items():
        module = _load_builder(script)
        on = _geo(module._build())
        off = _geo(_without_ws8(module._build))
        assert set(_collinear(on)) <= set(bound), (script, _collinear(on))
        assert len(_collinear(on)) < len(_collinear(off)) or not _collinear(off), script
        # WS8 must not buy the separation with a crossing or a back-edge.
        assert _crossings(on) <= _crossings(off), script
        assert _back_edges(on) <= _back_edges(off), script

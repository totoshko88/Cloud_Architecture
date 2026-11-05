"""1.13.0 fix (FEAT-004, items 11a / 11b): the finishing work budget and the
no-worse guard that replaced the G33 node-count gate.

* **budget** — ``caption_routing._admissible`` spends one unit of a per-run
  budget inside a planning run (caption-safe ``_plan_once``, crossing repair,
  collinear shift) and rejects every candidate once it is spent; outside a run
  (lint, metrics) it is never budgeted. A search for an edge on an OVERLOADED
  source face is capped at ``_OVERLOADED_BUDGET`` while the corner-exit
  fallback is off.
* **guard** — ``build_diagram`` plans every diagram (the >= 20-node gate is
  gone) and keeps the plan only when the re-assembled document has no more
  ``rule_violations`` errors, crossings or ``container-overlap`` findings than
  before; otherwise it tries crossing + collinear alone, else keeps the
  ``layout()`` geometry.
* **timing** — the SEP 02 flow fixture (11 nodes; 95 s+ before) builds in
  under 15 s.
"""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

import pytest

from rule_engine import caption_routing as cr
from rule_engine import crossing_repair as xr
from rule_engine import diagram_layout as dl
from rule_engine import geometry as geo
from rule_engine.drawio_model import parse_drawio

_ICON = dl.builtin_icon(
    "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;"
    "fillColor=#ED7100;strokeColor=#ffffff;aspect=fixed;html=1"
)
_TITLE = "aws t — 123456789012 / us-east-1 | 2026-11-03 | v1"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sep" / "scripts"


def _geo(text: str):
    return geo.build_geometry(parse_drawio(text, path="t.drawio")[0])


def _build(nodes, edges, legend_x=900, **kw):
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title=_TITLE, boundaries=[],
        nodes=nodes, edges=edges, flow_lines=["Flow"] + [f"{e.marker}. step" for e in edges],
        legend_x=legend_x, page_w=1400, page_h=1100, **kw,
    )


def _crossings(g) -> int:
    return geo.edge_crossing_stats(g)[0]


def _score(g):
    errors, _ = geo.rule_violations(g)
    return len(errors), _crossings(g), len(geo.check_container_overlap(g))


def _dense_case():
    """20+ nodes: the WS3 back-edge crossing (Route 53 -> CloudFront entering
    the LEFT face under Students -> CloudFront) plus a grid of idle nodes, so
    the diagram is at the former G33 gate."""
    nodes = [dl.Node("actor", "Students", 120, 120, render=_ICON),
             dl.Node("cf", "CloudFront", 340, 120, render=_ICON),
             dl.Node("dns", "Route 53", 560, 120, render=_ICON)]
    nodes += [dl.Node(f"n{i}", f"n{i}", 120 + 220 * (i % 5), 400 + 160 * (i // 5), render=_ICON)
              for i in range(18)]
    edges = [
        dl.Edge("e1", "actor", "cf", "1", exit=(1.0, 0.5), entry=(0.0, 0.5)),
        dl.Edge("e3", "dns", "cf", "3", exit=(1.0, 0.5), entry=(0.0, 0.7692307692307693),
                points=((670, 159), (670, 90), (270, 90), (270, 180))),
    ]
    return nodes, edges


# --------------------------------------------------------------------------- #
# The work budget
# --------------------------------------------------------------------------- #
def test_admissible_is_unbudgeted_outside_a_planning_run():
    assert cr._ADMISSIBLE_LEFT[0] is None
    assert not cr.admissible_budget_spent()


def test_admissible_budget_rejects_once_spent(monkeypatch):
    nodes, edges = _dense_case()
    g = _geo(_build(nodes, edges, caption_safe=False))
    e = next(o for o in g.edges if o.id == "e3")
    ctx = cr._ctx(g, e, {e.id}, False)
    poly = geo.edge_polyline(g, e)
    unbudgeted = cr._admissible(g, e, poly, e.exit, e.entry, ctx)
    with cr.admissible_budget(1):
        assert cr._admissible(g, e, poly, e.exit, e.entry, ctx) == unbudgeted
        assert cr.admissible_budget_spent()
        assert cr._admissible(g, e, poly, e.exit, e.entry, ctx) is None
    assert cr._ADMISSIBLE_LEFT[0] is None          # restored after the run
    assert cr._admissible(g, e, poly, e.exit, e.entry, ctx) == unbudgeted


def test_sub_budget_charges_the_run():
    with cr.admissible_budget(100):
        with cr._sub_budget(10):
            assert cr._ADMISSIBLE_LEFT[0] == 10
            cr._ADMISSIBLE_LEFT[0] -= 4             # the search spends 4
        assert cr._ADMISSIBLE_LEFT[0] == 96
        with cr._sub_budget(None):                  # no cap: the run's budget
            assert cr._ADMISSIBLE_LEFT[0] == 96


def test_overloaded_cap_follows_the_corner_fallback(monkeypatch):
    assert cr._overloaded_cap() == cr._OVERLOADED_BUDGET
    monkeypatch.setattr(cr, "_CORNER_EXIT_FALLBACK", [True])
    assert cr._overloaded_cap() is None


def test_spent_budget_leaves_the_route_unchanged(monkeypatch):
    """A crossing repair whose budget is spent before it starts plans nothing:
    the remaining edges keep their route."""
    nodes, edges = _dense_case()
    g = _geo(_build(nodes, edges, caption_safe=False))
    with cr.admissible_budget(0):
        plan, _work = xr.plan_crossing_repair_geo(g)
    assert plan.routes == {}
    with cr.admissible_budget():
        plan, _work = xr.plan_crossing_repair_geo(g)
    assert set(plan.routes) == {"e3"}


# --------------------------------------------------------------------------- #
# The no-worse guard
# --------------------------------------------------------------------------- #
def test_dense_diagram_gets_crossing_repair_and_never_gets_worse():
    nodes, edges = _dense_case()
    assert len(nodes) >= 20
    before = _geo(_build(nodes, edges, caption_safe=False))
    after = _geo(_build(nodes, edges))
    assert _crossings(before) == 1
    assert _crossings(after) == 0                   # repair applied on a dense diagram
    assert all(a <= b for a, b in zip(_score(after), _score(before)))


def test_guard_drops_a_plan_that_makes_the_diagram_worse(monkeypatch):
    """A plan that routes e1 straight through an unrelated icon (an
    ``edge-routing`` error) is rejected by the guard, and so is its
    crossing-only retry: the layout geometry is kept."""
    nodes, edges = _dense_case()
    bad = cr.CaptionPlan(
        routes={"e1": ((1.0, 0.5), (0.0, 0.5), ((180, 159), (180, 439), (300, 439), (300, 159)))},
        containers={}, text_dx=0.0)
    calls = []

    def fake(text, frozen=frozenset(), passes=dl._FINISH_PASSES):
        calls.append(tuple(passes))
        return bad

    monkeypatch.setattr(dl, "_plan_from_text", fake)
    unfinished = _build(nodes, edges, caption_safe=False)
    assert _build(nodes, edges) == unfinished
    assert calls == [dl._FINISH_PASSES, dl._FINISH_PASSES[1:]]


def test_no_worse_compares_every_component():
    assert dl._no_worse((0, 1, 0), (0, 1, 0))
    assert dl._no_worse((0, 0, 0), (1, 2, 0))
    assert not dl._no_worse((1, 0, 0), (0, 5, 0))   # a new error
    assert not dl._no_worse((0, 2, 0), (0, 1, 0))   # a new crossing
    assert not dl._no_worse((0, 0, 1), (0, 0, 0))   # a new container overlap
    assert not dl._no_worse(None, (0, 0, 0))        # unparsable candidate


def test_explicit_caption_plan_is_still_honoured(monkeypatch):
    nodes, edges = _dense_case()
    plan = dl.caption_safe_plan(boundaries=[], nodes=nodes, edges=edges,
                                flow_lines=["Flow", "1. a", "3. b"], legend_x=900)
    monkeypatch.setattr(dl, "_finishing_score", lambda text: pytest.fail("guarded"))
    _build(nodes, edges, caption_plan=plan)


# --------------------------------------------------------------------------- #
# Timing: the SEP 02 flow fixture
# --------------------------------------------------------------------------- #
@pytest.mark.sep
def test_sep_02_summary_builds_under_15s():
    """SEP 02 (9 nodes, layout() + build_diagram) took 95-260 s in 1.13.0
    before FEAT-004 (1.6M+ ``_admissible`` calls, all on the overloaded
    Lambda-core face). Measured as process CPU time, so a parallel test run
    sharing the machine does not count against it."""
    from rule_engine.icon_resolver import _load_mapping_cached

    path = _FIXTURES / "build_02_sep_summary.py"
    cwd = os.getcwd()
    os.chdir(_FIXTURES.parent)
    _load_mapping_cached.cache_clear()
    try:
        spec = importlib.util.spec_from_file_location("build_02_sep_summary_feat004", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        wall0, cpu0 = time.perf_counter(), time.process_time()
        text = module.build()
        wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
    finally:
        os.chdir(cwd)
        _load_mapping_cached.cache_clear()
    assert cpu < 15.0, f"SEP 02 build took {cpu:.1f}s CPU ({wall:.1f}s wall)"
    g = _geo(text)
    assert geo.rule_violations(g)[0] == ()

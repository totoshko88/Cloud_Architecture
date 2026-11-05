"""Crossing repair must never INTRODUCE an end-to-end merge (1.13.0 phase 3 verify).

The ``collinear`` COUNT cap in ``crossing_repair._accept`` let a crossing-fixing
move trade one plan-start collinear pair for a DIFFERENT one while the total
count stayed within the cap. When the new pair is an ``end-to-end-merge`` — two
unrelated edges whose facing ends read as ONE continuous line (an ERROR on a
landscape) — the later collinear-shift pass cannot undo it from the boxed-in
geometry, so the diagram ships the merge.

This was exposed by the item-11 (F16) trunk-exemption widening, which changed
``caption_routing._score.collinear`` and so the move crossing repair chose on the
SEP 03 coordinate-free landscape (``e13`` apigw->rds landing collinear with
``e4`` lambda->sqs, an end-to-end merge base 1.13.0 did not produce). The guard
rejects a trial that introduces an end-to-end merge absent from the move's start;
it may still re-use one already there, and trunk / pass-through pairs (which the
collinear-shift pass does clear) are untouched, so SEP 08's trunk moves still
apply.

Pinned here on geometry built directly (no finishing passes) and on the SEP 03
fixture rebuilt through the engine.
"""
from __future__ import annotations

from pathlib import Path
import importlib.util

import pytest

from rule_engine import crossing_repair as cr
from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.drawio_model import parse_drawio

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sep" / "scripts"


def _merge_geo() -> DiagramGeometry:
    """Two unrelated edges end to end on one line (an ``end-to-end-merge``),
    modelled on ``test_collinear_kinds_1_13_0_fix``: e1 runs along y=139 then
    drops into b; e2 drops out of c and continues along y=139 — no shared
    endpoint, facing ends within the collinear gap."""
    g = DiagramGeometry()
    for nid, x, y in (("a", 0, 100), ("b", 261, 300), ("c", 301, -100), ("d", 600, 100)):
        g.nodes[nid] = Box(nid, x, y, 78, 78)
    g.edges.append(EdgeGeom(id="e1", source="a", target="b", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.5, 0.0), points=[(300, 139)]))
    g.edges.append(EdgeGeom(id="e2", source="c", target="d", orthogonal=True,
                            exit=(0.5, 1.0), entry=(0.0, 0.5), points=[(340, 139)]))
    return g


def _clean_geo() -> DiagramGeometry:
    """The same four nodes, but e1 and e2 well separated — no merge."""
    g = DiagramGeometry()
    for nid, x, y in (("a", 0, 100), ("b", 261, 300), ("c", 301, -100), ("d", 600, 100)):
        g.nodes[nid] = Box(nid, x, y, 78, 78)
    g.edges.append(EdgeGeom(id="e1", source="a", target="b", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5), points=[(200, 139)]))
    g.edges.append(EdgeGeom(id="e2", source="c", target="d", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.0, 0.5), points=[(480, 420)]))
    return g


# --------------------------------------------------------------------------- #
# _end_to_end_merges helper
# --------------------------------------------------------------------------- #


def test_end_to_end_merges_extracts_only_that_kind():
    g = _merge_geo()
    finds = geo.collinear_edge_findings(g)
    want = frozenset((a, b) for a, b, k in finds if k == "end-to-end-merge")
    assert want                                              # the fixture has one
    assert cr._end_to_end_merges(g) == want
    # An end-to-end merge is two UNRELATED edges (no shared endpoint), so it is
    # never a fan-out/fan-in trunk the collinear exemption could hide.
    ea = {e.id: (e.source, e.target) for e in g.edges}
    for a, b in want:
        assert not (set(ea[a]) & set(ea[b])), (a, b, ea)


def test_end_to_end_merges_empty_on_a_clean_diagram():
    g = _clean_geo()
    assert ("e1", "e2") not in cr._end_to_end_merges(g)


# --------------------------------------------------------------------------- #
# _accept rejects a trial that introduces a NEW end-to-end merge
# --------------------------------------------------------------------------- #


def _permissive_base(start: DiagramGeometry, monkeypatch) -> cr._Base:
    """A _Base whose scalar score is strictly worse than any trial and whose
    finding set is empty, so the ONLY gates left in ``_accept`` are the merge
    gate and the (empty) finding gate."""
    base = cr._Base(start, collinear_cap=99)
    Score = base.score.__class__
    n = len(base.score.__dataclass_fields__)
    base.score = Score(*([5] * n))                          # worse than the stub
    base.findings = frozenset()
    monkeypatch.setattr(cr._cr, "_score", lambda g: Score(*([0] * n)))
    monkeypatch.setattr(cr._cr, "_violations", lambda g: ((), ()))
    return base


def test_accept_rejects_a_trial_that_introduces_a_new_merge(monkeypatch):
    base = _permissive_base(_clean_geo(), monkeypatch)
    assert base.merges == frozenset() or ("e1", "e2") not in base.merges
    trial = _merge_geo()
    assert cr._end_to_end_merges(trial) - base.merges       # a NEW merge exists
    assert cr._accept(trial, base) is None                  # ... so it is rejected


def test_accept_admits_the_trial_when_the_merge_is_already_in_the_base(monkeypatch):
    base = _permissive_base(_merge_geo(), monkeypatch)       # base ALREADY merges
    assert cr._end_to_end_merges(_merge_geo()) <= base.merges
    trial = _merge_geo()
    assert cr._end_to_end_merges(trial) - base.merges == frozenset()
    assert cr._accept(trial, base) is not None              # guard inert -> admitted


# --------------------------------------------------------------------------- #
# SEP 03 regression: the coordinate-free landscape carries no end-to-end merge
# --------------------------------------------------------------------------- #


def _load(name: str):
    path = _FIXTURES / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.slow
@pytest.mark.sep
def test_sep_03_coordfree_has_no_end_to_end_merge():
    mod = _load("build_03_coordfree.py")
    g = geo.build_geometry(parse_drawio(mod._build(), path="t.drawio")[0])
    merges = [f for f in geo.collinear_edge_findings(g) if f[2] == "end-to-end-merge"]
    assert merges == [], merges
    from rule_engine import collinear_repair as col
    assert col.collinear_pairs(g) == []                     # the WS8 target

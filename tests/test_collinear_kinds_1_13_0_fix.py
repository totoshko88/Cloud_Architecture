"""1.13.0 fix (ITEM 19): collinear kinds and supporting data edges.

* ``end-to-end-merge`` — two unrelated edges end to end on one line (ERROR on a
  landscape);
* ``pass-through-illusion`` — an in-edge and an out-edge meeting at a node on one
  line (no longer exempt as a trunk junction);
* a real fan-out trunk (both edges leave the node) stays exempt;
* ``supporting-data-edges`` — an ``overlay=supporting`` node on a numbered edge.
"""
from __future__ import annotations

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import Artifact, Severity, lint


def _e(eid, s, t, pts, label=""):
    # Contacts floated: edge_polyline then uses the node centres... pin faces.
    return EdgeGeom(id=eid, source=s, target=t, orthogonal=True,
                    exit=(1.0, 0.5), entry=(0.0, 0.5), points=pts, label=label)


def _hits(g, cls):
    art = Artifact(kind="diagram", node_names=sorted(g.nodes), geometry=g, diagram_class=cls)
    return [f for f in lint(art)["findings"] if f["rule"] == "collinear-edges"]


def test_end_to_end_merge_is_error_on_landscape():
    g = DiagramGeometry()
    for nid, x, y in (("a", 0, 100), ("b", 261, 300), ("c", 301, -100), ("d", 600, 100)):
        g.nodes[nid] = Box(nid, x, y, 78, 78)
    # e1 runs along y=139 from 78 to 300 then drops into b; e2 drops out of c
    # and continues along y=139 from 340 to 600: two unrelated edges end to end.
    g.edges.append(EdgeGeom(id="e1", source="a", target="b", orthogonal=True,
                            exit=(1.0, 0.5), entry=(0.5, 0.0), points=[(300, 139)]))
    g.edges.append(EdgeGeom(id="e2", source="c", target="d", orthogonal=True,
                            exit=(0.5, 1.0), entry=(0.0, 0.5), points=[(340, 139)]))
    found = geo.collinear_edge_findings(g)
    assert ("e1", "e2", "end-to-end-merge") in found
    land = _hits(g, "landscape")
    assert any(f["reason"].startswith("end-to-end-merge") and f["severity"] == Severity.ERROR.value
               for f in land), land
    flow = _hits(g, "flow")
    assert all(f["severity"] == Severity.WARNING.value for f in flow), flow


def test_pass_through_illusion():
    g = DiagramGeometry()
    g.nodes["a"] = Box("a", 0, 100, 78, 78)
    g.nodes["n"] = Box("n", 400, 400, 78, 78)
    g.nodes["b"] = Box("b", 800, 100, 78, 78)
    # a -> n and n -> b share the point (300, 200) on one horizontal line.
    g.edges.append(_e("in", "a", "n", [(300, 139), (300, 200), (200, 200)]))
    g.edges.append(_e("out", "n", "b", [(300, 200), (600, 200), (600, 139)]))
    found = geo.collinear_edge_findings(g)
    assert ("in", "out", "pass-through-illusion") in found


def test_fan_out_trunk_is_exempt():
    g = DiagramGeometry()
    g.nodes["n"] = Box("n", 0, 100, 78, 78)
    g.nodes["a"] = Box("a", 600, 0, 78, 78)
    g.nodes["b"] = Box("b", 600, 300, 78, 78)
    g.edges.append(_e("e1", "n", "a", [(200, 139), (200, 39)]))
    g.edges.append(_e("e2", "n", "b", [(200, 139), (200, 339)]))
    assert geo.collinear_edge_findings(g) == []
    assert geo.collinear_edge_pairs(g) == set()


def test_supporting_node_on_numbered_edge():
    g = DiagramGeometry()
    g.nodes["mon"] = Box("mon", 0, 0, 78, 78)
    g.nodes["app"] = Box("app", 300, 0, 78, 78)
    g.overlay_nodes["mon"] = "supporting"
    g.edges.append(_e("e1", "app", "mon", [], label="3"))
    art = Artifact(kind="diagram", node_names=["mon", "app"], geometry=g)
    hits = [f for f in lint(art)["findings"] if f["rule"] == "supporting-data-edges"]
    assert len(hits) == 1 and hits[0]["offenders"] == ["mon", "e1"]
    assert hits[0]["reason"] == "supporting-carries-data-edges"
    g.edges[0] = _e("e1", "app", "mon", [], label="")
    hits = [f for f in lint(art)["findings"] if f["rule"] == "supporting-data-edges"]
    assert hits == []  # a word label is flagged since phase 3 (test_lint_truth_1_13_0_phase3)

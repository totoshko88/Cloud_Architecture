"""1.13.0 phase 3, P0 items 1, 2, 4: lint truth."""
from __future__ import annotations

from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import Artifact, lint


def _edge(eid, s, t, label, pts=()):
    return EdgeGeom(id=eid, source=s, target=t, orthogonal=True,
                    exit=(1.0, 0.5), entry=(0.0, 0.5), points=list(pts), label=label)


def _supporting(cls, label):
    g = DiagramGeometry()
    g.nodes["mon"] = Box("mon", 0, 0, 78, 78)
    g.nodes["app"] = Box("app", 300, 0, 78, 78)
    g.overlay_nodes["mon"] = "supporting"
    if label is not None:
        g.edges.append(_edge("e1", "app", "mon", label))
    art = Artifact(kind="diagram", node_names=["mon", "app"], geometry=g, diagram_class=cls)
    return [f for f in lint(art)["findings"] if f["rule"] == "supporting-data-edges"]


def test_supporting_numbered_edge_error_on_landscape_warning_on_flow():
    land = _supporting("landscape", "3")
    assert land and land[0]["severity"] == "ERROR"
    assert land[0]["reason"] == "supporting-carries-data-edges"
    flow = _supporting("flow", "3")
    assert flow and flow[0]["severity"] == "WARNING"


def test_supporting_word_labelled_edge_is_flagged():
    hits = _supporting("landscape", "writes metrics")
    assert hits and hits[0]["severity"] == "ERROR"
    assert hits[0]["reason"] == "supporting-carries-labelled-edge"


def test_supporting_clean_cases():
    assert _supporting("landscape", None) == []
    assert _supporting("landscape", "peering") == []
    assert _supporting("landscape", "") == []

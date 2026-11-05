"""1.13.0: ``edge-label`` and ``flow-legend`` name their offenders."""

from __future__ import annotations

from rule_engine.linter import Artifact, Edge, RuleHit, _check_edge_label, _check_flow_legend


def _diagram(edges, flow=None) -> Artifact:
    return Artifact(kind="diagram", path="x.drawio", edges=edges, flow_legend_lines=flow)


def test_edge_label_offenders_are_edge_ids():
    hit = _check_edge_label(_diagram([
        Edge(source="a", target="b", label="1", id="e1"),
        Edge(source="a", target="c", label="", id="e3"),
        Edge(source="b", target="c", label=None, id="e2"),
    ]))
    assert isinstance(hit, RuleHit)
    assert hit.offenders == ("e2", "e3")
    assert hit.reason == "empty-label:2"


def test_edge_label_falls_back_to_endpoints():
    hit = _check_edge_label(_diagram([{"source": "a", "target": "b", "label": " "}]))
    assert hit and hit.offenders == ("a->b",)


def test_edge_label_clean_is_false():
    assert _check_edge_label(_diagram([Edge(source="a", target="b", label="x", id="e1")])) is False


def test_flow_legend_uncovered_markers():
    edges = [Edge(source="a", target="b", label=str(n), id=f"e{n}") for n in (1, 2, 3)]
    hit = _check_flow_legend(_diagram(edges, ["Flow", "1. start"]))
    assert hit and hit.offenders == ("marker-2", "marker-3")
    assert hit.reason == "uncovered-markers:2,3"


def test_flow_legend_no_flow_cell():
    edges = [Edge(source="a", target="b", label=str(n), id=f"e{n}") for n in (1, 2)]
    hit = _check_flow_legend(_diagram(edges, []))
    assert hit and hit.offenders == ("marker-1", "marker-2")
    assert hit.reason == "no-flow-cell"


def test_flow_legend_covered_is_false():
    edges = [Edge(source="a", target="b", label="1", id="e1")]
    assert _check_flow_legend(_diagram(edges, ["Flow", "1. go"])) is False

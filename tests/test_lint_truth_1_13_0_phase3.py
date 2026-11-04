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


# ---- item 2: own-source self-pierce (08 IGW -> EKS shape) -------------------

def _routing(exit_, pts, entry=(0.0, 0.5), cls="flow"):
    g = DiagramGeometry()
    g.nodes["igw"] = Box("igw", 370, 530, 78, 78)
    g.nodes["eks"] = Box("eks", 40, 750, 78, 78)
    g.edges.append(EdgeGeom(id="e13", source="igw", target="eks", orthogonal=True,
                            exit=exit_, entry=entry, points=list(pts), label="13"))
    art = Artifact(kind="diagram", node_names=["igw", "eks"], geometry=g, diagram_class=cls)
    return [f for f in lint(art)["findings"] if f["rule"] == "edge-routing"]


def test_exit_leg_back_through_own_source_is_error_on_both_classes():
    for cls in ("flow", "landscape"):
        hits = _routing((1.0, 0.5), [(20, 569), (20, 789)], cls=cls)
        assert hits and hits[0]["severity"] == "ERROR", hits
        assert hits[0]["reason"] == "pierces-source-igw"


def test_normal_exits_are_clean():
    # right exit heading right, then down and left via a corridor
    ok = _routing((1.0, 0.5), [(480, 569), (480, 700), (20, 700), (20, 789)], entry=(0.0, 0.5))
    assert not [f for f in ok if f["reason"].startswith("pierces-source")]
    # bottom exit going down
    ok = _routing((0.5, 1.0), [(409, 700), (20, 700), (20, 789)])
    assert not [f for f in ok if f["reason"].startswith("pierces-source")]
    # corner contact is not judged
    ok = _routing((1.0, 0.0), [(360, 530), (360, 700), (20, 700), (20, 789)])
    assert not [f for f in ok if f["reason"].startswith("pierces-source")]


def test_target_wrong_side_still_pierces_target():
    # left entry approached from the right: the final leg runs through eks
    hits = _routing((1.0, 0.5), [(480, 569), (480, 789), (100, 789)])
    assert hits and hits[0]["reason"] == "pierces-target-eks"
    assert hits[0]["severity"] == "ERROR"


# ---- item 4: companion prose marker check -----------------------------------

import textwrap

from rule_engine import cli as _cli

_COMPANION = textwrap.dedent("""\
    ---
    id: x
    ---
    # Title

    ## Overview

    The Atlas writers (10) feed the store, see marker 7 and step 3.
    A unit like `(99)` in code and 2024 are ignored.

    ```
    step 55
    ```

    ## Flow

    1. a
    2. b
    3. c
    7. g
    """)


def test_cited_markers_from_prose(tmp_path):
    (tmp_path / "d.diagram.md").write_text(_COMPANION)
    assert _cli._companion_cited_markers(str(tmp_path / "d.drawio")) == [3, 7, 10]
    assert _cli._companion_cited_markers(str(tmp_path / "none.drawio")) is None


def _art(cited, labels=("1", "2", "3", "7"), flow=("Flow", "1. a", "2. b", "3. c", "7. g")):
    g = DiagramGeometry()
    g.nodes["a"] = Box("a", 0, 0, 78, 78)
    g.nodes["b"] = Box("b", 300, 0, 78, 78)
    for i, lab in enumerate(labels):
        g.edges.append(_edge(f"e{i}", "a", "b", lab))
    from rule_engine.linter import Edge
    art = Artifact(kind="diagram", node_names=["a", "b"], geometry=g,
                   edges=[Edge(source="a", target="b", label=lab, id=f"e{i}")
                          for i, lab in enumerate(labels)],
                   flow_legend_lines=list(flow), companion_cited_markers=cited)
    return [f for f in lint(art)["findings"] if f["rule"] == "companion-marker-ref"]


def test_unknown_marker_is_a_warning():
    hits = _art([3, 7, 10])
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert hits[0]["reason"] == "unknown-marker:10"
    assert hits[0]["offenders"] == ["marker-10"]


def test_known_markers_and_no_flow_are_clean():
    assert _art([1, 3, 7]) == []
    assert _art([10], labels=("flow",), flow=()) == []   # no numeric markers
    assert _art(None) == []

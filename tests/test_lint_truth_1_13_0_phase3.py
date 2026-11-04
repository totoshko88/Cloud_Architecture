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

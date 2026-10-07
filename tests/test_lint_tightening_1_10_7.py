"""Lint tightening for hotfix 1.10.7 (M6).

The 1.10.0 quick run shipped a summary and a landscape that linted clean while
showing an account box with a large empty zone, lines striking out wide service
names, a flow-marker printed across a caption and a landscape where every edge
crossed another. Four lint-only changes close those gaps:

* ``container-dead-space`` judges an OUTER Boundary at 2.5 (inner stays 5.0);
* ``edge-crosses-label`` sizes each unrelated caption from its text width;
* ``marker-label-collision`` (new, WARNING) flags a marker on a caption;
* ``edge-crossing-excess`` is an ERROR on a landscape above 0.5 x E crossings.

None of them changes :func:`geometry.rule_violations` (the layout engine's
scored objective); ``make examples-check`` proves the engine goldens hold.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import Artifact, lint

REPO_ROOT = Path(__file__).resolve().parents[1]
QUICK = REPO_ROOT / "tests" / "fixtures" / "drawio" / "quick-1.10.0"
SUMMARY = QUICK / "01-quick-partner-data-summary.drawio"
LANDSCAPE = QUICK / "02-quick-partner-data-landscape.drawio"
CORPUS = sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"), recursive=True))

TIGHTENED = (
    "container-dead-space",
    "edge-crosses-label",
    "marker-label-collision",
    "edge-crossing-excess",
)


def _lint(path):
    out = []
    for art in parse_artifacts(str(path)):
        out += lint(art)["findings"]
    return out


def _one(findings, rule):
    hits = [f for f in findings if f["rule"] == rule]
    assert len(hits) == 1, (rule, hits)
    return hits[0]


# --------------------------------------------------------------------------- #
# The quick summary (flow)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def summary():
    return _lint(SUMMARY)


@pytest.fixture(scope="module")
def landscape():
    arts = parse_artifacts(str(LANDSCAPE))
    assert [a.diagram_class for a in arts] == ["landscape"]
    return _lint(LANDSCAPE)


def test_summary_outer_dead_space(summary):
    f = _one(summary, "container-dead-space")
    assert f["severity"] == "WARNING"
    assert f["reason"] == "outer-dead-space"
    assert f["offenders"] == ["boundary-account"]


def test_summary_wide_caption_crossings(summary):
    f = _one(summary, "edge-crosses-label")
    assert f["severity"] == "WARNING"
    assert {"e3", "src_partner", "e4", "alerts"} <= set(f["offenders"])


def test_summary_marker_on_caption(summary):
    f = _one(summary, "marker-label-collision")
    assert f["severity"] == "WARNING"
    assert f["reason"] == "marker-on-caption"
    assert f["offenders"] == ["e4", "alerts"]


def test_summary_flow_crossings_stay_below_cap(summary):
    assert not [f for f in summary if f["rule"] == "edge-crossing-excess"]


# --------------------------------------------------------------------------- #
# The quick landscape
# --------------------------------------------------------------------------- #


def test_landscape_crossing_hard_cap_is_an_error(landscape):
    f = _one(landscape, "edge-crossing-excess")
    assert f["severity"] == "ERROR"
    assert f["reason"] == "crossings-over-hard-cap:28/28"


def test_landscape_outer_dead_space(landscape):
    f = _one(landscape, "container-dead-space")
    assert f["reason"] == "outer-dead-space"
    assert "boundary-account" in f["offenders"]


def test_landscape_wide_caption_crossing(landscape):
    f = _one(landscape, "edge-crosses-label")
    assert "e28" in f["offenders"]


# --------------------------------------------------------------------------- #
# Synthetic crossing severities: flow WARNING vs landscape ERROR
# --------------------------------------------------------------------------- #


def _crossing_grid(n: int) -> DiagramGeometry:
    """``n`` horizontal edges crossed by ``n`` vertical edges: n*n crossings on
    2n edges, so the ratio is n/2 (> 0.5 for n >= 2)."""
    nodes = {}
    edges = []
    for i in range(n):
        y = 200 + 100 * i
        nodes[f"l{i}"] = Box(f"l{i}", 0, y, 40, 40)
        nodes[f"r{i}"] = Box(f"r{i}", 1000, y, 40, 40)
        edges.append(EdgeGeom(f"h{i}", f"l{i}", f"r{i}", True, (1.0, 0.5), (0.0, 0.5)))
        x = 300 + 100 * i
        nodes[f"t{i}"] = Box(f"t{i}", x, 0, 40, 40)
        nodes[f"b{i}"] = Box(f"b{i}", x, 1000, 40, 40)
        edges.append(EdgeGeom(f"v{i}", f"t{i}", f"b{i}", True, (0.5, 1.0), (0.5, 0.0)))
    return DiagramGeometry(nodes=nodes, edges=edges)


def _crossing_finding(diagram_class: str, g: DiagramGeometry):
    res = lint(Artifact(kind="diagram", node_names=list(g.nodes), geometry=g,
                        diagram_class=diagram_class))
    hits = [f for f in res["findings"] if f["rule"] == "edge-crossing-excess"]
    return hits[0] if hits else None


def test_synthetic_crossings_flow_is_warning_landscape_is_error():
    g = _crossing_grid(3)  # 9 crossings on 6 edges
    crossings, n_edges, _ = geo.edge_crossing_stats(g)
    assert (crossings, n_edges) == (9, 6)
    flow = _crossing_finding("flow", g)
    assert flow["severity"] == "WARNING" and flow["reason"] == "crossings-over-cap:9/6"
    land = _crossing_finding("landscape", g)
    assert land["severity"] == "ERROR" and land["reason"] == "crossings-over-hard-cap:9/6"


def test_synthetic_landscape_between_caps_is_warning():
    # 1 horizontal edge crossed by 1 vertical one plus 2 free edges: 1 crossing
    # on 4 edges -> not above ceil(0.25*4)=1 -> clean; add a second crossing on
    # the same 4 edges -> 2 > 1 (soft cap) but 2 <= 0.5*4 (hard cap) -> WARNING.
    g = _crossing_grid(1)
    g.nodes.update({"x0": Box("x0", 2000, 0, 40, 40), "x1": Box("x1", 2200, 0, 40, 40)})
    g.edges.append(EdgeGeom("free", "x0", "x1", True, (1.0, 0.5), (0.0, 0.5)))
    g.nodes.update({"y0": Box("y0", 500, 0, 40, 40), "y1": Box("y1", 500, 1000, 40, 40)})
    g.edges.append(EdgeGeom("v_extra", "y0", "y1", True, (0.5, 1.0), (0.5, 0.0)))
    crossings, n_edges, _ = geo.edge_crossing_stats(g)
    assert (crossings, n_edges) == (2, 4)
    land = _crossing_finding("landscape", g)
    assert land["severity"] == "WARNING"
    assert land["reason"] == "crossings-over-cap:2/4"


def test_no_crossings_no_finding():
    assert _crossing_finding("landscape", _crossing_grid(0)) is None


# --------------------------------------------------------------------------- #
# Caption-width band / marker helpers
# --------------------------------------------------------------------------- #


def test_node_caption_box_is_text_wide_and_centred():
    icon = Box("n", 100, 100, 78, 78)
    cap = geo.node_caption_box(icon, "partner-central-sync")  # 20 chars -> 140px
    assert cap.w == 140.0 and cap.y == icon.bottom and cap.h == geo.LABEL_BAND
    assert cap.x + cap.w / 2 == icon.x + icon.w / 2
    assert geo.node_caption_box(icon, "s3").w == 78.0  # never narrower than the icon
    two = geo.node_caption_box(icon, "a<br>b<br/>c")
    assert two.h == 48.0  # three lines x 16px


def test_caption_width_is_lint_only():
    # An edge passing 40px left of a 78px icon clears the icon-width band but
    # cuts the overhang of its 20-char caption: only caption_width=True sees it.
    a, b = Box("a", 0, 0, 40, 40), Box("b", 0, 400, 40, 40)
    n = Box("n", 100, 200, 78, 78)
    g = DiagramGeometry(
        nodes={"a": a, "b": b, "n": n},
        edges=[EdgeGeom("e", "a", "b", True, (1.0, 0.5), (1.0, 0.5),
                        points=[(80, 20), (80, 420)])],
        node_labels={"n": "partner-central-sync"},
    )
    assert geo.check_edge_crosses_label(g) == []
    assert geo.check_edge_crosses_label(g, caption_width=True) == [("e", "n")]
    errors, warnings = geo.rule_violations(g)
    assert not [w for w in warnings if w[0] == "edge-crosses-label"]


def test_marker_label_collision_unit():
    a, b = Box("a", 0, 0, 40, 40), Box("b", 400, 0, 40, 40)
    n = Box("n", 181, -60, 78, 78)  # caption band y 18..48 straddles the route y=20
    g = DiagramGeometry(
        nodes={"a": a, "b": b, "n": n},
        edges=[EdgeGeom("e", "a", "b", True, (1.0, 0.5), (0.0, 0.5), label="3")],
        node_labels={"n": "alerts"},
    )
    assert geo.check_marker_label_collision(g) == [("e", "n")]
    g.edges[0].label = "not-a-marker"
    assert geo.check_marker_label_collision(g) == []


# --------------------------------------------------------------------------- #
# The shipped corpus raises none of the tightened findings
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: str(Path(p).relative_to(REPO_ROOT)))
def test_corpus_has_no_tightened_finding(path):
    found = [f for f in _lint(path) if f["rule"] in TIGHTENED]
    assert found == [], found

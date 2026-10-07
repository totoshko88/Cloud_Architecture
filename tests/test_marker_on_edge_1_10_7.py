"""Flow-marker vs foreign-edge hygiene (release 1.10.7, docs/REVIEW.md D37).

In the quick summary the ``Amazon Quick -> Quick users`` run (``e9``) went left
across the account straight through the ``Athena -> Quick`` drop (``e8``) and
printed its line through ``e8``'s marker ``8``. Marker de-collision only ever
compared markers with markers. This pins the three pieces of the fix:

* the detector ``geometry.check_marker_on_edge`` (strict one-grid-step
  clearance, so the sanctioned 10px parallel corridor is NOT flagged);
* phase 2 of ``geometry.resolve_marker_collisions``, which slides the marker
  along its OWN edge to a clear spot, applied by ``build_diagram`` through
  ``orthogonalise.marker_hygiene_text``;
* the lint report: ``marker-collision`` reason ``marker-on-edge-<id>`` (WARNING).

Fixtures are small inline ``.drawio`` models in the ``test_edge_hygiene_1_10_5``
style (helpers copied, not imported).
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rule_engine import diagram_layout as dl
from rule_engine import geometry as g
from rule_engine import orthogonalise
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.linter import Severity, _check_marker_collision, lint
from rule_engine.orthogonalise import edge_hygiene_text, marker_hygiene_text

REPO_ROOT = Path(__file__).resolve().parents[1]
QUICK_SUMMARY = (
    REPO_ROOT / "tests" / "fixtures" / "drawio" / "quick-1.10.0"
    / "01-quick-partner-data-summary.drawio"
)
CORPUS = sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"), recursive=True))


# --------------------------------------------------------------------------- #
# Fixture builders (copied from tests/test_edge_hygiene_1_10_5.py)
# --------------------------------------------------------------------------- #


def _model(cells: str, grid: int = 10) -> str:
    return (
        f'<mxGraphModel gridSize="{grid}"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        f"{cells}</root></mxGraphModel>"
    )


def _node(nid: str, x: int, y: int, w: int = 80, h: int = 80) -> str:
    return (
        f'<mxCell id="{nid}" value="{nid}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )


def _edge(eid: str, src: str, tgt: str, style: str, *, value: str = "", points: str = "") -> str:
    inner = f'<Array as="points">{points}</Array>' if points else ""
    return (
        f'<mxCell id="{eid}" value="{value}" edge="1" parent="1" '
        f'source="{src}" target="{tgt}" style="{style}">'
        f'<mxGeometry relative="1" as="geometry">{inner}</mxGeometry></mxCell>'
    )


def _pts(*xy) -> str:
    return "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in xy)


def _geo(xml: str) -> g.DiagramGeometry:
    return g.build_geometry(parse_drawio(xml, path="fixture.drawio")[0])


class _FakeDiagram:
    """Minimal diagram Artifact stand-in the geometry predicates accept."""

    kind = "diagram"

    def __init__(self, xml: str) -> None:
        self.geometry = _geo(xml)


_DOWN = "exitX=0.5;exitY=1;entryX=0.5;entryY=0;"
_RIGHT = "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"

# The quick-summary shape: athena drops 80px into quick (e8, marker at
# (730, 560)); quick's e9 leaves right, rises to y=560 and runs left across
# e8's marker to the top of users.
_ON_EDGE = _model(
    _node("athena", 690, 440) + _node("quick", 690, 600) + _node("users", 30, 600)
    + _edge("e8", "athena", "quick", _DOWN, value="8")
    + _edge(
        "e9", "quick", "users", "exitX=1;exitY=0.5;entryX=0.5;entryY=0;",
        value="9", points=_pts((810, 640), (810, 560), (70, 560)),
    )
)


def _anchor_clearance(geo: g.DiagramGeometry, eid: str) -> float:
    p = g.marker_anchors(geo)[eid]
    return g._dist_to_foreign_edges(p, eid, g._edge_polylines(geo))[0]


# --------------------------------------------------------------------------- #
# (a)-(d) detector and phase-2 slide
# --------------------------------------------------------------------------- #


def test_marker_on_foreign_edge_detected():
    geo = _geo(_ON_EDGE)
    assert g.marker_anchors(geo)["e8"] == pytest.approx((730.0, 560.0))
    assert g.check_marker_on_edge(geo) == [("e8", "e9")]


def test_marker_slides_off_foreign_edge_and_is_idempotent():
    moved = g.resolve_marker_collisions(_geo(_ON_EDGE))
    assert set(moved) == {"e8"}
    new, changed = marker_hygiene_text(_ON_EDGE)
    assert changed == ["e8"]
    geo2 = _geo(new)
    assert g.check_marker_on_edge(geo2) == []
    assert _anchor_clearance(geo2, "e8") >= g.MARKER_EDGE_CLEARANCE
    # Not parked on a caption either (athena's caption sits 520..550).
    assert g.check_marker_label_collision(geo2) == []
    # Idempotent through both entry points.
    assert marker_hygiene_text(new) == (new, [])
    assert edge_hygiene_text(new)[1] == []


def test_marker_slide_is_also_applied_by_edge_hygiene():
    new, changed = edge_hygiene_text(_ON_EDGE)
    assert "e8" in changed
    assert g.check_marker_on_edge(_geo(new)) == []


def test_parallel_run_one_grid_step_away_is_not_flagged():
    # e1's marker at (140, 40); e2 runs parallel at y=50 — exactly one grid step.
    xml = _model(
        _node("A", 0, 0) + _node("B", 200, 0) + _node("C", 0, 10) + _node("D", 200, 10)
        + _edge("e1", "A", "B", _RIGHT, value="1")
        + _edge("e2", "C", "D", _RIGHT)
    )
    geo = _geo(xml)
    assert g.check_marker_on_edge(geo) == []
    assert g.resolve_marker_collisions(geo) == {}
    assert marker_hygiene_text(xml) == (xml, [])


def test_parallel_run_under_one_grid_step_is_flagged():
    xml = _model(
        _node("A", 0, 0) + _node("B", 200, 0) + _node("C", 0, 9) + _node("D", 200, 9)
        + _edge("e1", "A", "B", _RIGHT, value="1")
        + _edge("e2", "C", "D", _RIGHT)
    )
    assert g.check_marker_on_edge(_geo(xml)) == [("e1", "e2")]


def test_marker_vs_marker_behaviour_unchanged():
    xml = _model(
        _node("A", 0, 0) + _node("B", 200, 0) + _node("C", 0, 20) + _node("D", 200, 20)
        + _edge("e1", "A", "B", _RIGHT, value="1")
        + _edge("e2", "C", "D", _RIGHT, value="2")
    )
    assert g.resolve_marker_collisions(_geo(xml)) == {"e1": -0.2, "e2": 0.2}


def test_marker_without_clear_candidate_stays_put():
    # e2 retraces e1's whole line, so no spot along e1 clears it.
    xml = _model(
        _node("A", 0, 0) + _node("B", 200, 0)
        + _edge("e1", "A", "B", _RIGHT, value="1")
        + _edge("e2", "A", "B", _RIGHT)
    )
    geo = _geo(xml)
    assert g.check_marker_on_edge(geo) == [("e1", "e2")]
    assert g.resolve_marker_collisions(geo) == {}


# --------------------------------------------------------------------------- #
# (e)-(f) build_diagram applies the marker pass
# --------------------------------------------------------------------------- #

_ICON = dl.builtin_icon("shape=mxgraph.aws4.resourceIcon;aspect=fixed;html=1")


def _build(edges):
    nodes = [
        dl.Node("athena", "Athena", 690, 440, render=_ICON),
        dl.Node("quick", "Quick", 690, 600, render=_ICON),
        dl.Node("users", "Users", 30, 600, render=_ICON),
    ]
    return dl.build_diagram(
        diagram_id="t", diagram_name="t", title="aws t — 123456789012 / us-east-1 | 2026-10-07 | v1",
        boundaries=[], nodes=nodes, edges=edges, flow_lines=["Flow", "8. a", "9. b"],
        legend_x=1000,
    )


_BUILD_EDGES = [
    dl.Edge("e8", "athena", "quick", "8", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    dl.Edge(
        "e9", "quick", "users", "9", exit=(1.0, 0.5), entry=(0.5, 0.0),
        points=((810, 639), (810, 560), (69, 560)),
    ),
]


def test_build_diagram_slides_marker_off_foreign_edge(monkeypatch):
    raw = _build(_BUILD_EDGES)
    assert g.check_marker_on_edge(_geo(raw)) == []
    assert '<mxCell id="e8"' in raw
    e8 = raw.split('<mxCell id="e8"', 1)[1].split("</mxCell>", 1)[0]
    assert 'relative="1"' in e8 and ' x="' in e8
    # Without the pass the same build would print e9's line through marker 8.
    monkeypatch.setattr(orthogonalise, "marker_hygiene_text", lambda t: (t, []))
    unpatched = _build(_BUILD_EDGES)
    assert g.check_marker_on_edge(_geo(unpatched)) == [("e8", "e9")]


def test_build_diagram_is_byte_identical_when_nothing_collides(monkeypatch):
    clean = [dl.Edge("e8", "athena", "quick", "8", exit=(0.5, 1.0), entry=(0.5, 0.0))]
    with_pass = _build(clean)
    monkeypatch.setattr(orthogonalise, "marker_hygiene_text", lambda t: (t, []))
    assert _build(clean) == with_pass


# --------------------------------------------------------------------------- #
# (g)-(i) lint: marker-collision reason marker-on-edge-<id>
# --------------------------------------------------------------------------- #


def test_lint_reports_marker_on_edge():
    hit = _check_marker_collision(_FakeDiagram(_ON_EDGE))
    assert not isinstance(hit, list)
    assert hit.reason == "marker-on-edge-e9"
    assert list(hit.offenders) == ["e8", "e9"]
    assert hit.severity in (None, Severity.WARNING)


def test_lint_reports_both_kinds_as_two_hits():
    xml = _model(
        _node("A", 0, 0) + _node("B", 200, 0)
        + _edge("e1", "A", "B", _RIGHT, value="1")
        + _edge("e2", "A", "B", _RIGHT, value="2")
    )
    hits = _check_marker_collision(_FakeDiagram(xml))
    assert isinstance(hits, list)
    assert [h.reason for h in hits] == ["markers-overprint", "marker-on-edge-e2"]


def test_quick_1_10_0_summary_reports_marker_on_edge():
    findings = []
    for art in parse_artifacts(str(QUICK_SUMMARY)):
        findings += lint(art)["findings"]
    hits = [f for f in findings if f["rule"] == "marker-collision"]
    assert hits, findings
    assert any(str(f.get("reason", "")).startswith("marker-on-edge-") for f in hits)
    assert all(f["severity"] == "WARNING" for f in hits)


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: str(Path(p).relative_to(REPO_ROOT)))
def test_corpus_has_no_marker_collision(path):
    for art in parse_artifacts(path):
        rules = [f["rule"] for f in lint(art)["findings"]]
        assert "marker-collision" not in rules

"""``legend-placement`` → ``overlaps-node-<id>`` (hotfix 1.10.7 follow-up, D36).

The quick summary drew its Flow box over an external consumer (``users``)
placed right of the account. Nothing flagged it: ``legend-placement`` judged
only containers, ``node-overlap`` skips text cells and ``edge-crosses-legend``
is a WARNING that fires only when an edge runs through the box. The rule now
reports a Flow/Legend box that overlaps any node's icon or caption, as an ERROR
on both classes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.geometry import Box, DiagramGeometry
from rule_engine.linter import RULE_LEGEND_PLACEMENT, Artifact, lint

REPO = Path(__file__).resolve().parents[1]
FIXTURE = (
    REPO / "tests" / "fixtures" / "drawio" / "legend-overlaps-node"
    / "01-legend-overlaps-node.drawio"
)


def _legend_findings(result):
    return [f for f in result["findings"] if f["rule"] == RULE_LEGEND_PLACEMENT]


def _node_geo(node=(900, 200), label="", containers=None):
    """A Legend box at x=1000..1280, y=100..400 and one 78px node ``n1``."""
    nx, ny = node
    return DiagramGeometry(
        nodes={"n1": Box("n1", nx, ny, 78, 78)},
        node_labels={"n1": label},
        containers=containers or {},
        text_boxes={"legend": Box("legend", 1000, 100, 280, 300)},
        text_headings={"legend": "Legend"},
    )


# (1) the anonymised quick-summary render ------------------------------------
def test_fixture_box_over_a_node_is_an_error():
    findings = []
    for art in parse_artifacts(str(FIXTURE)):
        result = lint(art)
        assert result["eligible_for_publication"] is False
        findings += _legend_findings(result)
    node_hits = [f for f in findings if f["reason"].startswith("overlaps-node-")]
    assert len(node_hits) == 1
    hit = node_hits[0]
    assert hit["severity"] == "ERROR"
    assert hit["reason"] == "overlaps-node-users"
    assert "users" in hit["offenders"]
    assert "123456789012" in FIXTURE.read_text(encoding="utf-8")


# (2) no containers at all: the node check still runs -------------------------
def test_node_under_the_box_is_flagged_without_containers():
    assert geo.check_legend_placement(_node_geo(node=(1050, 200))) == [
        ("legend", "overlaps-node-n1")
    ]


# (3) icon clear, wide caption reaching under the box -------------------------
def test_wide_caption_under_the_box_is_flagged():
    # Icon 900..978 is left of the box (x=1000); a 30-char caption is 210px wide,
    # centred on the icon (939 ± 105 → right edge 1044), so it reaches under it.
    g = _node_geo(node=(900, 200), label="x" * 30)
    assert geo.check_legend_placement(g) == [("legend", "overlaps-node-n1")]
    # The same icon with a short caption is clear.
    assert geo.check_legend_placement(_node_geo(node=(900, 200), label="fn")) == []


# (4) one grid step clear of the footprint -----------------------------------
def test_box_ten_px_right_of_the_footprint_is_clean():
    g = _node_geo(node=(912, 200))  # icon right = 990, box x = 1000
    assert geo.check_legend_placement(g) == []


# (5) ERROR on both classes -------------------------------------------------
@pytest.mark.parametrize("diagram_class", ["flow", "landscape"])
def test_overlap_is_an_error_on_both_classes(diagram_class):
    art = Artifact(
        kind="diagram", is_drawio=True,
        geometry=_node_geo(node=(1050, 200)), diagram_class=diagram_class,
    )
    result = lint(art)
    hits = _legend_findings(result)
    assert [(h["severity"], h["reason"]) for h in hits] == [("ERROR", "overlaps-node-n1")]
    assert hits[0]["offenders"] == ["legend", "n1"]
    assert result["eligible_for_publication"] is False


# (6) the shipped corpus never hides a node ---------------------------------
_CORPUS = sorted(
    list((REPO / "examples").rglob("*.drawio"))
    + list((REPO / "tests" / "fixtures" / "drawio" / "quick-1.10.0").glob("*.drawio"))
)


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: str(p.relative_to(REPO)))
def test_corpus_has_no_box_over_a_node(path):
    for art in parse_artifacts(str(path)):
        reasons = [f["reason"] for f in _legend_findings(lint(art))]
        assert not [r for r in reasons if r.startswith("overlaps-node-")], reasons


# (7) the container-only conditions stay WARNING ----------------------------
def test_container_only_finding_stays_a_warning():
    g = DiagramGeometry(
        containers={"account": Box("account", 560, 100, 800, 600)},
        text_boxes={"legend": Box("legend", 40, 880, 470, 160)},
        text_headings={"legend": "Legend"},
    )
    hits = _legend_findings(lint(Artifact(kind="diagram", is_drawio=True, geometry=g)))
    assert [(h["severity"], h["reason"]) for h in hits] == [
        ("WARNING", "left-of-diagram-body")
    ]


def test_node_and_container_findings_are_separate_hits():
    # A box over both a node and the cloud: the node hit is ERROR, the
    # container hit keeps the rule default.
    g = _node_geo(node=(1050, 200), containers={"account": Box("account", 600, 50, 600, 500)})
    hits = _legend_findings(lint(Artifact(kind="diagram", is_drawio=True, geometry=g)))
    assert sorted((h["severity"], h["reason"]) for h in hits) == [
        ("ERROR", "overlaps-node-n1"),
        ("WARNING", "left-of-diagram-body"),
    ]

"""Tests for the ``marker-on-container-border`` rule (FEAT-001 item E).

A numbered flow-marker whose rendered anchor (:func:`geometry.marker_anchors`)
falls within one grid step of a Boundary container border overprints the
account / VPC frame — the defect the 01 / 01b review surfaced (marker ``9``
smeared on the SEP account box border). The rule is the container-border sibling
of ``marker-label-collision`` (a marker on a node caption) and ``marker-on-icon``
(a marker on a node glyph), modelled on ``edge-on-container-border`` — but it is
the marker's anchor **point**, not a long edge leg, that rides the border.

Three layers are pinned:
1. ``geometry.check_marker_on_container_border`` — the detector.
2. the linter wrapper + ``RuleSpec`` — a crafted model raises the WARNING,
   a clear marker does not, and the rule is **not** in ``rule_violations``.
3. the shipped corpus gains no finding.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rule_engine.geometry import (
    Box,
    DiagramGeometry,
    EdgeGeom,
    build_geometry,
    check_marker_on_container_border,
    marker_anchors,
    rule_violations,
)
from rule_engine.drawio_model import parse_drawio
from rule_engine.linter import (
    RULE_MARKER_ON_CONTAINER_BORDER,
    RULE_SEVERITIES,
    Severity,
    _check_marker_on_container_border,
    lint,
)
from rule_engine.cli import parse_artifacts

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"), recursive=True))


def _geo_with_border_at(border_x: float, *, label: str = "9") -> DiagramGeometry:
    """A right→left edge whose marker midpoint lands at x=600; a container whose
    right edge sits at ``border_x`` so the marker rides it when ``border_x≈600``.

    Node ``a`` right face at x=478, node ``b`` left face at x=722; the midpoint
    of the single straight segment is x=600, y=400 (both faces at y=0.5)."""
    return DiagramGeometry(
        nodes={
            "a": Box("a", 400, 361, 78, 78),
            "b": Box("b", 722, 361, 78, 78),
        },
        containers={
            # left edge at 60; right edge at border_x; spans the marker's y.
            "boundary-account": Box("boundary-account", 60, 120, border_x - 60, 560),
        },
        edges=[
            EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label=label),
        ],
    )


class _FakeDiagram:
    """Minimal diagram Artifact stand-in the linter wrapper accepts."""

    kind = "diagram"

    def __init__(self, geo: DiagramGeometry) -> None:
        self.geometry = geo


def test_marker_anchor_lands_at_segment_midpoint():
    g = _geo_with_border_at(600)
    assert marker_anchors(g)["e"] == pytest.approx((600.0, 400.0))


def test_marker_on_a_container_border_is_flagged():
    """A marker whose anchor sits on the account box right edge rides it."""
    g = _geo_with_border_at(600)
    assert check_marker_on_container_border(g) == [("e", "boundary-account.right")]


def test_marker_within_one_grid_step_is_flagged():
    """One grid step off the border (anchor 600 vs border 608) still reads as on it."""
    g = _geo_with_border_at(608)
    assert check_marker_on_container_border(g) == [("e", "boundary-account.right")]


def test_marker_a_clear_two_grid_steps_off_the_border_is_not_flagged():
    """Border a comfortable two grid steps from the anchor (620 vs 600) is clean."""
    g = _geo_with_border_at(620)
    assert check_marker_on_container_border(g) == []


def test_marker_off_the_end_of_a_border_is_not_flagged():
    """A border coincident in x but whose y-extent does not reach the anchor
    (anchor y=400, border y-span 120..300) is not flagged — the marker is beside
    the border, not on it."""
    g = DiagramGeometry(
        nodes={"a": Box("a", 400, 361, 78, 78), "b": Box("b", 722, 361, 78, 78)},
        containers={"boundary-account": Box("boundary-account", 60, 120, 540, 180)},
        edges=[EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                        exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="9")],
    )
    assert check_marker_on_container_border(g) == []


def test_non_numeric_edge_label_carries_no_marker():
    """An edge whose label is prose (not a bare integer) has no marker anchor,
    so it can never trip the rule."""
    g = _geo_with_border_at(600, label="validate licence")
    assert marker_anchors(g) == {}
    assert check_marker_on_container_border(g) == []


def test_linter_wrapper_reports_warning():
    hit = _check_marker_on_container_border(_FakeDiagram(_geo_with_border_at(600)))
    assert hit is not False
    assert not isinstance(hit, list)
    assert hit.reason == "marker-on-border"
    assert list(hit.offenders) == ["e", "boundary-account.right"]
    assert RULE_SEVERITIES[RULE_MARKER_ON_CONTAINER_BORDER] is Severity.WARNING


def test_linter_wrapper_is_false_when_clear():
    assert _check_marker_on_container_border(_FakeDiagram(_geo_with_border_at(620))) is False


def test_phase3_nudge_slides_a_marker_off_a_container_border():
    """FEAT-002 / backlog G30: ``resolve_marker_collisions`` phase 3 slides a
    marker whose anchor rides a Boundary container border along its OWN edge to
    a clear spot. A build-time pass (``build_diagram`` → ``marker_hygiene_text``),
    so new diagrams never ship a marker on a frame; the detector/rule stay the
    gate for a hand-authored or not-yet-rebuilt source."""
    from rule_engine.geometry import resolve_marker_collisions

    geo = _geo_with_border_at(600)
    assert check_marker_on_container_border(geo) == [("e", "boundary-account.right")]
    moved = resolve_marker_collisions(geo)
    assert "e" in moved, "the border-riding marker must be nudged"
    # Apply the nudge and confirm the finding clears.
    for e in geo.edges:
        if e.id in moved:
            e.label_pos = moved[e.id]
    assert check_marker_on_container_border(geo) == []


def test_phase3_leaves_a_clear_marker_untouched():
    """A marker already clear of every border is not moved (idempotent)."""
    from rule_engine.geometry import resolve_marker_collisions

    geo = _geo_with_border_at(620)  # border a comfortable 2 grid steps off
    assert check_marker_on_container_border(geo) == []
    assert resolve_marker_collisions(geo) == {}


def test_rule_is_lint_only_not_in_rule_violations():
    """Like the other marker-* rules, this one is lint-only — it must NOT appear
    in the solver oracle (``rule_violations``), even on a geometry that trips it."""
    errors, warnings = rule_violations(_geo_with_border_at(600))
    joined = {r for r, _ in errors} | {r for r, _ in warnings}
    assert "marker-on-container-border" not in joined


# Two shipped goldens genuinely carry a marker on a Boundary border, so the rule
# reports a real WARNING on them — the marker IS a readability defect there.
# Both are WARNING (non-blocking: ``test_golden_examples`` still passes), and the
# finding stays VISIBLE on the COMMITTED bytes. FEAT-002 added the off-border
# nudge (``resolve_marker_collisions`` phase 3, backlog G30) so a FRESH build no
# longer parks a marker on a frame — but it only takes effect at build time, and
# these two goldens are NOT regenerated this wave, so their committed bytes (and
# this finding) are unchanged. They are tolerated by id, not by weakening the
# detector or removing the rule; regenerating either golden would clear its
# finding:
#   * gcp/01-gcp-vertex-pipeline — e2 anchor 2px off boundary-vpc-a.right
#   * oci/01-oci-genai-stack     — e1 anchor on boundary-region-a.top
_KNOWN_MARKER_ON_BORDER = {
    "examples/gcp/01-gcp-vertex-pipeline.drawio",
    "examples/oci/01-oci-genai-stack.drawio",
}


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: str(Path(p).relative_to(REPO_ROOT)))
def test_corpus_marker_on_container_border(path):
    """Every shipped diagram is clean of the finding EXCEPT the two documented
    real cases, which stay visible as WARNINGs (never blocking)."""
    rel = str(Path(path).relative_to(REPO_ROOT))
    for art in parse_artifacts(path):
        findings = lint(art)["findings"]
        rules = [f["rule"] for f in findings]
        on_border = [f for f in findings if f["rule"] == RULE_MARKER_ON_CONTAINER_BORDER]
        if rel in _KNOWN_MARKER_ON_BORDER:
            # The finding is expected here, and it must be a non-blocking WARNING.
            assert on_border, f"expected a known marker-on-border WARNING on {rel}"
            assert all(f["severity"] == "WARNING" for f in on_border)
        else:
            assert RULE_MARKER_ON_CONTAINER_BORDER not in rules

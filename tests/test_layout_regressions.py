"""Layout regressions from the 1.10.0 quick run (hotfix 1.10.7, M3/M4).

The anonymised quick specs (:mod:`tests.quick_regression_specs`) are a live
serverless account the 1.10.6 engine could not lay out (``LayoutError`` on the
landscape). They pin four things:

* ``layout()`` returns a diagram for the summary and the landscape, the same
  bytes every run (M3, degrade instead of raise);
* the account box wraps only in-account nodes — no actors / on-premises
  footprint inside it;
* the rendered summary lints with zero ERROR, a ``#CD2264`` account and an
  outer dead-space ratio under 2.5 (M4 compaction);
* the M7-conformant landscape meets the landscape crossing hard cap
  (<= 0.5 x E), the outer dead-space ceiling and zero ERROR — NOT met in
  1.10.7 (known limitation G12, pinned ``xfail(strict=True)`` until D2/D4 land
  in 1.11; the linter blocking it is the intended fail-closed behaviour);
* the Flow/Legend boxes clear every node footprint (icon + caption),
  including an external consumer drawn right of the account — the quick
  summary's ``users`` was drawn under the Flow box (1.10.7 follow-up, D36).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.layout import layout
from rule_engine.layout.repair import _serialize_candidate
from rule_engine.linter import lint
from tests import quick_regression_specs as Q

FIXTURES = Q.REPO_ROOT / "tests" / "fixtures" / "drawio" / "quick-1.10.0"
SUMMARY_MD = FIXTURES / "01-quick-partner-data-summary.diagram.md"
LANDSCAPE_MD = FIXTURES / "02-quick-partner-data-landscape.diagram.md"
BLOCKING = {"ERROR", "CRITICAL"}


def _geometry(xml: str):
    return geo.build_geometry(parse_drawio(xml, path="<regression>.drawio")[0])


def _outer_dead_space(xml: str) -> float:
    ratios = dict(geo.check_container_dead_space(_geometry(xml), threshold=0, outer_threshold=None))
    return ratios["boundary-account"]


def _write_pair(tmp: Path, drawio_name: str, xml: str, companion: Path) -> Path:
    path = tmp / f"{drawio_name}.drawio"
    path.write_text(xml, encoding="utf-8")
    shutil.copy(companion, tmp / f"{drawio_name}.diagram.md")
    return path


def _findings(path: Path):
    out = []
    for art in parse_artifacts(str(path)):
        out += lint(art)["findings"]
    return out


@pytest.fixture(scope="module")
def placed():
    return {
        "summary": layout(Q.SUMMARY),
        "landscape": layout(Q.LANDSCAPE),
        "conformant": layout(Q.LANDSCAPE_CONFORMANT),
    }


_SPECS = {"summary": Q.SUMMARY, "landscape": Q.LANDSCAPE, "conformant": Q.LANDSCAPE_CONFORMANT}


# (a) --------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["summary", "landscape"])
def test_quick_spec_lays_out_deterministically(placed, name):
    first = _serialize_candidate(placed[name])
    second = _serialize_candidate(layout(_SPECS[name]))
    assert first == second


# (b) --------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["summary", "landscape", "conformant"])
def test_account_box_encloses_no_external_node(placed, name):
    acct = placed[name].containers["boundary-account"]
    for node in _SPECS[name].nodes:
        if node.lane not in Q.EXTERNAL_LANES:
            continue
        fp = placed[name].nodes[node.id].footprint(geo.LABEL_BAND)
        overlaps = (acct.x < fp.right and fp.x < acct.right
                    and acct.y < fp.bottom and fp.y < acct.bottom)
        assert not overlaps, f"{node.id} ({node.lane}) is drawn inside the account box"


# (c) --------------------------------------------------------------------- #
def test_quick_summary_lints_clean_with_a_tight_red_account(tmp_path):
    xml = Q.render(Q.SUMMARY, Q.SUMMARY_LABELS, Q.SUMMARY_TITLE)
    path = _write_pair(tmp_path, "01-quick-partner-data-summary", xml, SUMMARY_MD)
    findings = _findings(path)
    assert [f for f in findings if f["severity"] in BLOCKING] == []
    assert [f for f in findings if f["rule"] == "container-style"] == []
    assert 'id="boundary-account"' in xml and "strokeColor=#CD2264" in xml
    assert _outer_dead_space(xml) < geo.OUTER_DEAD_SPACE_RATIO


# (d) --------------------------------------------------------------------- #
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known limitation of 1.10.7 (REVIEW.md G12): measured crossings 23/25 = "
        "0.92*E against <= 0.5*E, outer dead-space 3.45 against < 2.5, 2 ERRORs "
        "(edge-crossing-excess crossings-over-hard-cap:23/25, edge-routing "
        "knee-through-dlq). Ten nodes share one platform row; needs D2 (functional "
        "group containers) and D4 (slot search), both 1.11. The linter blocking "
        "this landscape is the intended fail-closed behaviour; do not relax the "
        "thresholds or rewrite the spec to pass."
    ),
)
def test_conformant_landscape_meets_the_landscape_gates(tmp_path):
    summary = Q.render(Q.SUMMARY, Q.SUMMARY_LABELS, Q.SUMMARY_TITLE)
    _write_pair(tmp_path, "01-quick-partner-data-summary", summary, SUMMARY_MD)
    xml = Q.render(Q.LANDSCAPE_CONFORMANT, Q.LANDSCAPE_LABELS, Q.LANDSCAPE_TITLE)
    path = _write_pair(tmp_path, "02-quick-partner-data-landscape", xml, LANDSCAPE_MD)
    assert [a.diagram_class for a in parse_artifacts(str(path))] == ["landscape"]
    crossings, edges, _pairs = geo.edge_crossing_stats(_geometry(xml))
    assert crossings <= geo.HARD_CROSSING_RATIO * edges, f"{crossings}/{edges}"
    assert _outer_dead_space(xml) < geo.OUTER_DEAD_SPACE_RATIO
    assert [f for f in _findings(path) if f["severity"] in BLOCKING] == []


# (e) --------------------------------------------------------------------- #
def test_original_landscape_degrades_instead_of_raising(placed):
    """The as-declared landscape is not expected to be clean (its slot order
    and lanes were tuned for a different layout); it must lay out, and it is
    reported as degraded rather than raised."""
    result = placed["landscape"]
    assert result.degraded is True
    assert isinstance(result.layout_warnings, tuple)


# (f) --------------------------------------------------------------------- #
_RENDER = {
    "summary": (Q.SUMMARY, Q.SUMMARY_LABELS, Q.SUMMARY_TITLE),
    "landscape": (Q.LANDSCAPE, Q.LANDSCAPE_LABELS, Q.LANDSCAPE_TITLE),
    "conformant": (Q.LANDSCAPE_CONFORMANT, Q.LANDSCAPE_LABELS, Q.LANDSCAPE_TITLE),
}


def _intersects(a, b) -> bool:
    return a.x < b.right and b.x < a.right and a.y < b.bottom and b.y < a.bottom


@pytest.mark.parametrize("name", ["summary", "landscape", "conformant"])
def test_flow_and_legend_clear_every_node(name):
    g = _geometry(Q.render(*_RENDER[name]))
    furniture = {
        cid: box for cid, box in g.text_boxes.items()
        if g.text_headings.get(cid, "").strip().lower() in geo.LEGEND_HEADINGS
    }
    assert len(furniture) == 2, sorted(furniture)
    for nid, icon in g.nodes.items():
        caption = geo.node_caption_box(icon, g.node_labels.get(nid, ""))
        for cid, box in furniture.items():
            assert not _intersects(box, icon), f"{cid} is drawn over the {nid} icon"
            assert not _intersects(box, caption), f"{cid} is drawn over the {nid} caption"


def test_quick_summary_has_no_edge_crossing_legend(tmp_path):
    xml = Q.render(Q.SUMMARY, Q.SUMMARY_LABELS, Q.SUMMARY_TITLE)
    path = _write_pair(tmp_path, "01-quick-partner-data-summary", xml, SUMMARY_MD)
    rules = {f["rule"] for f in _findings(path)}
    assert "edge-crosses-legend" not in rules
    assert "legend-placement" not in rules

"""1.10.12 WS7 (defect C12): edge legs drawn ON an unrelated icon are flagged.

The SEP 06 v3 repro (``atlas sub=2``) routes ``e8`` (``lti -> atlas``) along
``y = 360`` from ``x = 580`` to ``1390``. S3 sits at ``x 1130..1208``,
``y 360..438``, so the 810px horizontal leg lies exactly on S3's top border and
through both S3 entry contacts. ``segment_crosses_box`` shrinks every box by a
2px inset (a graze is not a crossing), which also hid this ride, so
``edge-routing`` stayed silent. WS7 adds :func:`geometry.segment_rides_box_border`
to the straight and knee checks, under the same ``*-through-*`` reasons (ERROR),
and a ``marker-on-icon`` reason to ``marker-label-collision``.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from rule_engine import geometry as geo
from rule_engine.cli import parse_artifacts
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import lint

REPO_ROOT = Path(__file__).resolve().parents[1]
REPRO = REPO_ROOT / "tests" / "fixtures" / "sep" / "repro"
REPRO_SUB2 = REPRO / "06v3-atlas-sub2.drawio"
REPRO_V3 = REPRO / "06v3-flow-task-verification.drawio"
CORPUS = sorted(glob.glob(str(REPO_ROOT / "examples" / "**" / "*.drawio"), recursive=True))
SEP = sorted(glob.glob(str(REPO_ROOT / "tests" / "fixtures" / "sep" / "*.drawio")))


def _geometry(path: Path) -> DiagramGeometry:
    return geo.build_geometry(parse_drawio(path.read_bytes(), path=str(path))[0])


def _lint(path):
    out = []
    for art in parse_artifacts(str(path)):
        out += lint(art)["findings"]
    return out


# --------------------------------------------------------------------------- #
# The repro
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", [REPRO_SUB2, REPRO_V3], ids=lambda p: p.name)
def test_repro_e8_is_knee_through_s3(path: Path) -> None:
    hits = geo.check_edge_routing(_geometry(path))
    assert ("e8", "knee-through-s3") in hits, hits


def test_repro_e8_leg_lies_on_s3_top_border() -> None:
    """The defect is a ride, not an inset crossing: the 2px-inset test alone
    stays silent on the very leg the ride test catches."""
    g = _geometry(REPRO_SUB2)
    s3 = g.nodes["s3"]
    leg = ((580.0, 360.0), (1390.0, 360.0))
    assert s3.y == 360.0
    assert not geo.segment_crosses_box(*leg, s3)
    assert geo.segment_rides_box_border(*leg, s3)


def test_repro_lints_edge_routing_error() -> None:
    hits = [f for f in _lint(REPRO_SUB2) if f["rule"] == "edge-routing"]
    assert hits, "edge-routing not reported on the WS7 repro"
    (f,) = hits
    assert f["severity"] == "ERROR"
    assert f["reason"].startswith("knee-through-s3")
    assert "e8" in f["offenders"]


# --------------------------------------------------------------------------- #
# segment_rides_box_border unit
# --------------------------------------------------------------------------- #

_BOX = Box("n", 100, 100, 78, 78)  # x 100..178, y 100..178


@pytest.mark.parametrize("leg, expected", [
    (((0, 100), (300, 100)), True),      # exactly on the top border
    (((0, 99), (300, 99)), True),        # 1px outside: stroke still overlaps
    (((0, 98), (300, 98)), False),       # 2px outside: a near-miss
    (((0, 102), (300, 102)), True),      # 2px inside (the inset blind strip)
    (((0, 178), (300, 178)), True),      # bottom border
    (((178, 0), (178, 300)), True),      # vertical leg on the right border
    (((100, 0), (100, 300)), True),      # vertical leg on the left border
    (((0, 100), (105, 100)), False),     # touches the corner by 5px only
    (((0, 100), (110, 100)), True),      # one full grid step along the border
    (((0, 139), (300, 139)), False),     # through the middle: crosses, not rides
    (((0, 100), (300, 200)), False),     # diagonal legs never ride
])
def test_segment_rides_box_border(leg, expected) -> None:
    assert geo.segment_rides_box_border(*leg, _BOX) is expected


def test_border_ride_on_own_endpoint_is_exempt() -> None:
    """An edge entering its own target's top face is not a ride."""
    a, b = Box("a", 0, 0, 78, 78), Box("b", 300, 200, 78, 78)
    e = EdgeGeom("e", "a", "b", True, (1.0, 0.5), (0.5, 0.0),
                 points=[(339, 39), (339, 200)])
    assert geo.check_edge_routing(DiagramGeometry(nodes={"a": a, "b": b}, edges=[e])) == []


def test_waypoint_free_edge_on_a_border_is_straight_through() -> None:
    a, b = Box("a", 0, 100, 78, 78), Box("b", 400, 100, 78, 78)
    n = Box("n", 200, 139, 78, 78)  # top border on the edge's y = 139
    e = EdgeGeom("e", "a", "b", True, (1.0, 0.5), (0.0, 0.5))
    g = DiagramGeometry(nodes={"a": a, "b": b, "n": n}, edges=[e])
    assert geo.check_edge_routing(g) == [("e", "straight-through-n")]


@pytest.mark.parametrize("path", CORPUS + SEP, ids=lambda p: Path(p).name)
def test_no_border_ride_in_corpus_or_sep_fixtures(path: str) -> None:
    """Goldens and the SEP 01-09 fixtures stay free of icon crossings."""
    hits = [h for h in geo.check_edge_routing(_geometry(Path(path))) if "through-" in h[1]]
    assert hits == []


# --------------------------------------------------------------------------- #
# marker-on-icon
# --------------------------------------------------------------------------- #


def _marker_geo(label_pos):
    a, b = Box("a", 0, 0, 78, 78), Box("b", 400, 0, 78, 78)
    return DiagramGeometry(
        nodes={"a": a, "b": b},
        edges=[EdgeGeom("e", "a", "b", True, (1.0, 0.5), (0.0, 0.5),
                        label="3", label_pos=label_pos)],
    )


def test_marker_icon_collision_unit() -> None:
    # Midpoint (239, 39): in the gap, clear of both icons.
    assert geo.check_marker_icon_collision(_marker_geo(None)) == []
    # Source end (78, 39): the number prints on the source glyph.
    assert geo.check_marker_icon_collision(_marker_geo(-1.0)) == [("e", "a")]
    # Target end (400, 39): on the target glyph.
    assert geo.check_marker_icon_collision(_marker_geo(1.0)) == [("e", "b")]


_MARKER_DRAWIO = """<mxfile><diagram name="d"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="a" value="a" style="shape=cylinder3;verticalLabelPosition=bottom;verticalAlign=top;" vertex="1" parent="1">
<mxGeometry x="0" y="0" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="b" value="b" style="shape=cylinder3;verticalLabelPosition=bottom;verticalAlign=top;" vertex="1" parent="1">
<mxGeometry x="400" y="0" width="78" height="78" as="geometry"/></mxCell>
<mxCell id="e" value="3" style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;endArrow=open;endFill=0;" edge="1" parent="1" source="a" target="b">
<mxGeometry x="-1" relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>
"""


def test_lint_reports_marker_on_icon(tmp_path: Path) -> None:
    src = tmp_path / "01-marker.drawio"
    src.write_text(_MARKER_DRAWIO, encoding="utf-8")
    hits = [f for f in _lint(src) if f["rule"] == "marker-label-collision"]
    reasons = {f["reason"] for f in hits}
    assert "marker-on-icon" in reasons, hits
    (f,) = [h for h in hits if h["reason"] == "marker-on-icon"]
    assert f["severity"] == "WARNING"
    assert f["offenders"] == ["e", "a"]

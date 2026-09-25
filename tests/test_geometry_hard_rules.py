"""Tests for the v1.3.x hard diagram-generation rules.

These pin the audit-derived rules added after building the HA multi-region
landscape pair:

- **label-aware footprint** — ``container-padding`` and ``node-overlap`` measure
  the icon **plus** its caption band, not the bare 78x78 icon, so a label that
  crowds a boundary or the row below is caught;
- **container-overlap** — sibling (non-nested) boundaries must not overlap;
- **edge-direction** — every edge with explicit contact points exits its source
  right/bottom and enters its target left/top;
- both new rules are WARNING for ``flow`` and ERROR for ``landscape``;
- the four golden HA landscapes are clean under all of them (no false positives).

The geometry checks are exercised directly on synthetic
:class:`rule_engine.geometry.DiagramGeometry` inputs, and the class-aware
severities through the linter on a parsed golden example.
"""

from __future__ import annotations

import glob
import os

from rule_engine import cli as _cli
from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom, LABEL_BAND
from rule_engine.linter import (
    Artifact,
    Severity,
    lint,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sev(result, rule):
    return next((f["severity"] for f in result["findings"] if f["rule"] == rule), None)


# --------------------------------------------------------------------------- #
# label-aware footprint
# --------------------------------------------------------------------------- #


def test_footprint_grows_box_downward_by_label_band():
    b = Box("n", 100, 100, 78, 78)
    f = b.footprint()
    assert f.h == 78 + LABEL_BAND
    assert f.x == b.x and f.y == b.y and f.w == b.w


def test_node_overlap_is_label_aware():
    """Two icons that clear each other (78 tall, 90 apart) still collide once the
    ~30px label band is counted."""
    g = DiagramGeometry(
        nodes={
            "a": Box("a", 0, 0, 78, 78),
            "b": Box("b", 0, 90, 78, 78),  # 12px icon gap, < LABEL_BAND
        }
    )
    assert ("a", "b") in geo.check_node_overlap(g)
    # Icon-only test (label_band=0) does not see the collision.
    assert geo.check_node_overlap(g, label_band=0) == []


def test_container_padding_is_label_aware():
    """A node whose icon clears the border but whose label reaches it is flagged."""
    g = DiagramGeometry(
        nodes={"n": Box("n", 40, 40, 78, 78)},
        containers={"c": Box("c", 0, 0, 158, 140)},  # icon fits w/ pad; label (to 148) overflows bottom
    )
    findings = geo.check_container_padding(g)
    assert any(f[0] == "n" and f[1] == "c" for f in findings)


# --------------------------------------------------------------------------- #
# container-overlap
# --------------------------------------------------------------------------- #


def test_sibling_container_overlap_flagged():
    g = DiagramGeometry(
        containers={
            "vpc-a": Box("vpc-a", 0, 0, 500, 400),
            "vpc-b": Box("vpc-b", 450, 0, 500, 400),  # overlaps 450..500
        }
    )
    assert ("vpc-a", "vpc-b") in geo.check_container_overlap(g)


def test_proper_nesting_not_flagged():
    g = DiagramGeometry(
        containers={
            "account": Box("account", 0, 0, 1000, 800),
            "vpc": Box("vpc", 50, 50, 400, 400),  # fully inside account
            "az": Box("az", 70, 70, 200, 200),    # fully inside vpc
        }
    )
    assert geo.check_container_overlap(g) == []


def test_disjoint_siblings_not_flagged():
    g = DiagramGeometry(
        containers={
            "vpc-a": Box("vpc-a", 0, 0, 400, 400),
            "vpc-b": Box("vpc-b", 500, 0, 400, 400),  # clear gap
        }
    )
    assert geo.check_container_overlap(g) == []


# --------------------------------------------------------------------------- #
# edge-direction
# --------------------------------------------------------------------------- #


def _edge_id(eid, src, tgt, exit_, entry):
    return EdgeGeom(id=eid, source=src, target=tgt, orthogonal=True, exit=exit_, entry=entry)


def _edge(src, tgt, exit_, entry):
    return EdgeGeom(id="e", source=src, target=tgt, orthogonal=True, exit=exit_, entry=entry)


def test_left_exit_flagged():
    g = DiagramGeometry(edges=[_edge("a", "b", (0.0, 0.5), (0.5, 0.0))])
    assert geo.check_edge_direction(g)  # exit-not-right-or-bottom


def test_right_entry_flagged():
    g = DiagramGeometry(edges=[_edge("a", "b", (1.0, 0.5), (1.0, 0.5))])
    assert geo.check_edge_direction(g)  # enter-not-left-or-top


def test_right_exit_left_entry_clean():
    g = DiagramGeometry(edges=[_edge("a", "b", (1.0, 0.5), (0.0, 0.5))])
    assert geo.check_edge_direction(g) == []


def test_bottom_exit_top_entry_clean():
    g = DiagramGeometry(edges=[_edge("a", "b", (0.5, 1.0), (0.5, 0.0))])
    assert geo.check_edge_direction(g) == []


def test_top_right_corner_exit_clean():
    """A corner exit aimed up-and-right (exitX high) is allowed."""
    g = DiagramGeometry(edges=[_edge("a", "b", (0.9, 0.25), (0.0, 0.5))])
    assert geo.check_edge_direction(g) == []


def test_single_axis_exit_on_right_face_not_flagged():
    """An exit that pins only exitX on the right face (exitY unset) is valid and
    must not be flagged for the unset complementary axis (contract relaxation)."""
    g = DiagramGeometry(edges=[_edge("a", "b", (1.0, None), (0.0, 0.5))])
    assert geo.check_edge_direction(g) == []


def test_single_axis_entry_on_left_face_not_flagged():
    g = DiagramGeometry(edges=[_edge("a", "b", (1.0, 0.5), (0.0, None))])
    assert geo.check_edge_direction(g) == []


def test_single_axis_left_exit_still_flagged():
    """A pinned left-edge exit (exitX < 0.5, exitY unset) is still a defect."""
    g = DiagramGeometry(edges=[_edge("a", "b", (0.0, None), (0.0, 0.5))])
    assert geo.check_edge_direction(g)  # exit-not-right-or-bottom


def test_single_axis_bottom_entry_still_flagged():
    """A pinned bottom-edge entry (entryY == 1, entryX unset) is still a defect."""
    g = DiagramGeometry(edges=[_edge("a", "b", (1.0, 0.5), (None, 1.0))])
    assert geo.check_edge_direction(g)  # enter-not-left-or-top


def test_grid_alignment_tolerates_float_noise():
    """A coordinate carrying sub-pixel float drift is judged against its rounded
    integer origin, not the raw float (no false misalignment)."""
    g = DiagramGeometry(nodes={"n": Box("n", 219.9999999, 160.0000001, 78, 78)})
    assert geo.check_grid_alignment(g) == []


def test_grid_alignment_flags_genuine_off_grid():
    g = DiagramGeometry(nodes={"n": Box("n", 225, 160, 78, 78)})
    assert geo.check_grid_alignment(g) == ["n"]


# --------------------------------------------------------------------------- #
# class-aware severity through the linter
# --------------------------------------------------------------------------- #


def _geo_with_overlap():
    return DiagramGeometry(
        containers={
            "vpc-a": Box("vpc-a", 0, 0, 500, 400),
            "vpc-b": Box("vpc-b", 450, 0, 500, 400),
        }
    )


def test_container_overlap_error_for_landscape():
    art = Artifact(
        kind="diagram", diagram_class="landscape", node_names=["n"],
        summary_of="01-x-summary", geometry=_geo_with_overlap(),
    )
    assert _sev(lint(art), "container-overlap") == Severity.ERROR.value


def test_container_overlap_warning_for_flow():
    art = Artifact(kind="diagram", node_names=["n"], geometry=_geo_with_overlap())
    assert _sev(lint(art), "container-overlap") == Severity.WARNING.value


def test_edge_direction_error_for_landscape():
    g = DiagramGeometry(edges=[_edge("a", "b", (0.0, 0.5), (0.5, 0.0))])
    art = Artifact(
        kind="diagram", diagram_class="landscape", node_names=["n"],
        summary_of="01-x-summary", geometry=g,
    )
    assert _sev(lint(art), "edge-direction") == Severity.ERROR.value


def test_edge_direction_warning_for_flow():
    g = DiagramGeometry(edges=[_edge("a", "b", (0.0, 0.5), (0.5, 0.0))])
    art = Artifact(kind="diagram", node_names=["n"], geometry=g)
    assert _sev(lint(art), "edge-direction") == Severity.WARNING.value


# --------------------------------------------------------------------------- #
# golden examples are clean under the new rules (no false positives)
# --------------------------------------------------------------------------- #


def test_golden_landscapes_clean_under_new_rules():
    landscapes = glob.glob(
        os.path.join(HERE, "examples", "**", "*ha-multiregion-landscape.drawio"),
        recursive=True,
    )
    assert landscapes, "expected the four HA landscape golden examples"
    for path in landscapes:
        g = _cli.parse_artifact(path).geometry
        assert g is not None, path
        assert geo.check_container_overlap(g) == [], path
        assert geo.check_edge_direction(g) == [], path
        assert geo.check_node_overlap(g) == [], path
        assert geo.check_container_padding(g) == [], path
        assert geo.check_exit_thirds(g) == [], path


# --------------------------------------------------------------------------- #
# exit-thirds (label-safe fan-out: centred / even-thirds, max 3 per side)
# --------------------------------------------------------------------------- #


def test_exit_thirds_single_exit_any_position_clean():
    """One edge on a side is fine wherever it sits."""
    g = DiagramGeometry(edges=[_edge("a", "b", (1.0, 0.42), (0.0, 0.5))])
    assert geo.check_exit_thirds(g) == []


def test_exit_thirds_two_right_exits_even_clean():
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "b", (1.0, 0.25), (0.0, 0.5)),
        _edge_id("e2", "a", "c", (1.0, 0.75), (0.0, 0.5)),
    ])
    assert geo.check_exit_thirds(g) == []


def test_exit_thirds_three_right_exits_even_clean():
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "b", (1.0, 0.25), (0.0, 0.5)),
        _edge_id("e2", "a", "c", (1.0, 0.5), (0.0, 0.5)),
        _edge_id("e3", "a", "d", (1.0, 0.75), (0.0, 0.5)),
    ])
    assert geo.check_exit_thirds(g) == []


def test_exit_thirds_distinct_non_canonical_two_exits_clean():
    """Two distinct exits need not be exactly 0.25/0.75 — 0.33/0.66 is fine
    (the rule now only requires they not merge, not a rigid grid)."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "b", (1.0, 0.33), (0.0, 0.5)),
        _edge_id("e2", "a", "c", (1.0, 0.66), (0.0, 0.5)),
    ])
    assert geo.check_exit_thirds(g) == []


def test_exit_thirds_merging_two_exits_flagged():
    """Two exits closer than min_sep read as one doubled line — flagged."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "b", (1.0, 0.5), (0.0, 0.5)),
        _edge_id("e2", "a", "c", (1.0, 0.6), (0.0, 0.5)),
    ])
    hits = geo.check_exit_thirds(g)
    assert any("merge" in reason for _, reason in hits)


def test_exit_thirds_centre_plus_spread_clean():
    """A straight-line edge on the centre (0.5) plus two spread around it is the
    sanctioned exit-priority shape and must pass."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "b", (1.0, 0.2), (0.0, 0.5)),
        _edge_id("e2", "a", "c", (1.0, 0.5), (0.0, 0.5)),
        _edge_id("e3", "a", "d", (1.0, 0.8), (0.0, 0.5)),
    ])
    assert geo.check_exit_thirds(g) == []


def test_exit_thirds_over_connected_side_flagged():
    """A fourth exit on one side is over-connected regardless of spacing."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "b", (1.0, 0.2), (0.0, 0.5)),
        _edge_id("e2", "a", "c", (1.0, 0.4), (0.0, 0.5)),
        _edge_id("e3", "a", "d", (1.0, 0.6), (0.0, 0.5)),
        _edge_id("e4", "a", "e", (1.0, 0.8), (0.0, 0.5)),
    ])
    hits = geo.check_exit_thirds(g)
    assert any("over-connected" in reason for _, reason in hits)


def test_exit_thirds_ignores_floating_exit():
    """An edge with no declared exit point is not judged."""
    g = DiagramGeometry(edges=[_edge_id("e1", "a", "b", (None, None), (0.0, 0.5))])
    assert geo.check_exit_thirds(g) == []


# --------------------------------------------------------------------------- #
# text-padding
# --------------------------------------------------------------------------- #


def test_text_padding_flags_unpadded_box():
    xml = '<mxCell id="t" style="text;html=1;fillColor=#FFFFFF;strokeColor=#000000" vertex="1"></mxCell>'
    assert geo.check_text_padding(xml)  # missing spacing* on a filled+stroked box


def test_text_padding_clean_when_padded():
    xml = ('<mxCell id="t" style="text;html=1;fillColor=#FFFFFF;strokeColor=#000000;'
           'spacingLeft=10;spacingRight=10;spacingTop=10;spacingBottom=10" vertex="1"></mxCell>')
    assert geo.check_text_padding(xml) == []


def test_text_padding_exempts_borderless_title():
    # A title/free label with no concrete fill+stroke has no visible box to pad.
    xml = '<mxCell id="title" style="text;html=1;fontSize=16;fontStyle=1" vertex="1"></mxCell>'
    assert geo.check_text_padding(xml) == []


# --------------------------------------------------------------------------- #
# edge-float (no explicit contact points)
# --------------------------------------------------------------------------- #


def test_edge_float_flags_missing_contacts():
    g = DiagramGeometry(edges=[EdgeGeom("e", "a", "b", True, (None, None), (None, None))])
    assert geo.check_edge_float(g) == ["e"]


def test_edge_float_clean_with_contacts():
    g = DiagramGeometry(edges=[EdgeGeom("e", "a", "b", True, (1.0, 0.5), (0.0, 0.5))])
    assert geo.check_edge_float(g) == []


def test_edge_float_error_for_landscape():
    g = DiagramGeometry(edges=[EdgeGeom("e", "a", "b", True, (None, None), (None, None))])
    art = Artifact(kind="diagram", diagram_class="landscape", node_names=["n"],
                   summary_of="01-x-summary", geometry=g)
    assert _sev(lint(art), "edge-float") == Severity.ERROR.value


# --------------------------------------------------------------------------- #
# corridor-sharing
# --------------------------------------------------------------------------- #


def test_corridor_sharing_flags_two_unrelated_long_edges_on_one_lane():
    # Two edges from different sources both run horizontally at y=500 over an
    # overlapping x-range.
    g = DiagramGeometry(
        nodes={
            "a": Box("a", 0, 480, 78, 78), "b": Box("b", 600, 480, 78, 78),
            "c": Box("c", 0, 800, 78, 78), "d": Box("d", 600, 800, 78, 78),
        },
        edges=[
            EdgeGeom("e1", "a", "b", True, (1.0, 0.5), (0.0, 0.5), points=[(100, 500), (600, 500)]),
            EdgeGeom("e2", "c", "d", True, (1.0, 0.5), (0.0, 0.5), points=[(150, 500), (650, 500)]),
        ],
    )
    assert ("e1", "e2") in geo.check_corridor_sharing(g)


def test_corridor_sharing_exempts_shared_trunk_same_source():
    # Two edges from the SAME source sharing a stub is a legitimate fan-out trunk.
    g = DiagramGeometry(
        nodes={"s": Box("s", 0, 480, 78, 78), "l": Box("l", -400, 800, 78, 78),
               "r": Box("r", 600, 800, 78, 78)},
        edges=[
            EdgeGeom("e1", "s", "l", True, (0.5, 1.0), (0.5, 0.0), points=[(39, 600), (-361, 600)]),
            EdgeGeom("e2", "s", "r", True, (0.5, 1.0), (0.5, 0.0), points=[(39, 600), (639, 600)]),
        ],
    )
    assert geo.check_corridor_sharing(g) == []


def test_golden_landscapes_clean_corridor_and_float():
    landscapes = glob.glob(
        os.path.join(HERE, "examples", "**", "*ha-multiregion-landscape.drawio"),
        recursive=True,
    )
    for path in landscapes:
        g = _cli.parse_artifact(path).geometry
        assert geo.check_corridor_sharing(g) == [], path
        assert geo.check_edge_float(g) == [], path


def test_golden_landscapes_eligible_for_publication():
    landscapes = glob.glob(
        os.path.join(HERE, "examples", "**", "*ha-multiregion-landscape.drawio"),
        recursive=True,
    )
    for path in landscapes:
        art = _cli.parse_artifact(path)
        result = lint(art)
        # Only the relaxed node-count WARNING is expected; nothing blocking.
        assert result["eligible_for_publication"] is True, (path, result["findings"])

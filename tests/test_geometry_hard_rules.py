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
# nested container-in-container padding (v1.5.2)
#
# Regression for the audit finding: a VPC boundary sharing an edge with its
# Account boundary (zero padding) was never evaluated, because
# ``check_container_padding`` only measured nodes-in-containers, never a nested
# container against its parent. The parser confirmed both cells are containers,
# yet the linter reported the diagram clean.
# --------------------------------------------------------------------------- #


def test_nested_container_shared_edge_is_flagged():
    """A child boundary whose right edge coincides with its parent's right edge
    (the exact 01-aws-web VPC⊂Account defect) has zero padding and is flagged."""
    g = DiagramGeometry(
        containers={
            # Account right = 250+798 = 1048.
            "acct": Box("acct", 250, 220, 798, 288),
            # VPC right = 690+358 = 1048 — shares Account's right edge → 0 pad.
            "vpc": Box("vpc", 690, 280, 358, 198),
        }
    )
    findings = geo.check_container_padding(g)
    assert ("vpc", "acct", 0.0) in findings


def test_nested_container_with_ample_padding_is_clean():
    """The fixed geometry — Account widened so the VPC clears it by >=30px on
    every side (top measured past the parent caption band) — is clean."""
    g = DiagramGeometry(
        containers={
            # Account widened: right = 250+828 = 1078, bottom = 508.
            "acct": Box("acct", 250, 220, 828, 288),
            # VPC right = 1048 (30 from 1078), bottom = 478 (30 from 508),
            # left = 440, top gap = 60 (>= 30 pad + 30 caption band).
            "vpc": Box("vpc", 690, 280, 358, 198),
        }
    )
    assert geo.check_container_padding(g) == []


def test_nested_container_top_flush_is_flagged():
    """A child whose top sits < one grid step below the parent's top border is
    flagged even though left/right/bottom clear by >= 100 — the four sides are
    measured symmetrically against the pad floor, exactly as a node is."""
    g = DiagramGeometry(
        containers={
            "acct": Box("acct", 0, 0, 1000, 800),
            "vpc": Box("vpc", 100, 5, 400, 400),  # top gap 5 < pad(10)
        }
    )
    findings = geo.check_container_padding(g)
    assert any(f[0] == "vpc" and f[1] == "acct" for f in findings)


def test_triple_nest_measured_against_immediate_parent():
    """Account ⊃ VPC ⊃ AZ: the AZ is measured against the VPC (its tightest
    enclosing parent), not the Account, so a well-padded triple nest is clean."""
    g = DiagramGeometry(
        containers={
            "acct": Box("acct", 0, 0, 1200, 900),
            "vpc": Box("vpc", 60, 60, 900, 600),   # clears acct by 60 on top/left
            "az": Box("az", 120, 120, 600, 400),   # clears vpc by 60 on top/left
        }
    )
    assert geo.check_container_padding(g) == []


# --------------------------------------------------------------------------- #
# node spilled past a container border (v1.5.3)
#
# Regression for the 01-aws-eu-central-1 defect: EC2-az-c and S3 shared the
# VPC's x-band but were drawn BELOW the VPC's bottom edge. The pre-1.5.3 check
# required box overlap on BOTH axes for a straddle, so a node overlapping only
# the x-axis while sitting entirely below the container was neither "inside" nor
# "straddle" — the linter reported the diagram clean. Spill detection closes it,
# while staying narrow enough not to flag housed nodes or external actors.
# --------------------------------------------------------------------------- #


def test_orphan_node_spilled_below_container_is_flagged():
    """A node in the container's x-band, sitting just below its bottom edge and
    housed by no container, is flagged as spilled out."""
    g = DiagramGeometry(
        nodes={"ec2c": Box("ec2c", 100, 420, 78, 78)},  # bottom (w/ label) ~528
        containers={"vpc": Box("vpc", 60, 60, 400, 330)},  # vpc bottom = 390
    )
    findings = geo.check_container_padding(g)
    assert any(f[0] == "ec2c" and f[1] == "vpc" for f in findings)


def test_orphan_node_spilled_above_container_is_flagged():
    """The mirror case: a node in the x-band sitting just above the top edge."""
    g = DiagramGeometry(
        nodes={"n": Box("n", 100, 20, 78, 78)},          # bottom ~128
        containers={"vpc": Box("vpc", 60, 200, 400, 330)},  # vpc top = 200
    )
    findings = geo.check_container_padding(g)
    assert any(f[0] == "n" and f[1] == "vpc" for f in findings)


def test_housed_node_sharing_a_neighbours_band_is_not_flagged():
    """A node fully inside its OWN container (az-a2) must not be flagged as
    spilled out of a sibling container (az-a1) whose x-band it shares one
    row-step away — the landscape false-positive this rule must avoid."""
    g = DiagramGeometry(
        nodes={"db": Box("db", 120, 780, 78, 78)},  # fully inside az-a2 below
        containers={
            "az-a1": Box("az-a1", 90, 390, 800, 328),   # ends at y=718
            "az-a2": Box("az-a2", 90, 750, 800, 328),   # houses db (750..1078)
        },
    )
    assert geo.check_container_padding(g) == []


def test_external_actor_left_of_boundary_is_not_flagged():
    """An external actor drawn just to the LEFT of a boundary (in its y-band,
    within one step) is a legitimate placement (actors sit outside the cloud
    boundary) — horizontal spill is deliberately not flagged."""
    g = DiagramGeometry(
        nodes={"user": Box("user", 80, 440, 60, 60)},   # right = 140
        containers={"boundary": Box("boundary", 200, 70, 1160, 800)},  # left = 200
    )
    assert geo.check_container_padding(g) == []


def test_disjoint_node_far_below_container_is_not_flagged():
    """A node in the x-band but MORE than one row-step below the border is
    unrelated (not a spill of this container)."""
    g = DiagramGeometry(
        nodes={"n": Box("n", 100, 700, 78, 78)},         # top 700, > 160 below 390
        containers={"vpc": Box("vpc", 60, 60, 400, 330)},  # bottom = 390
    )
    assert geo.check_container_padding(g) == []


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


# --------------------------------------------------------------------------- #
# entry-thirds (v1.5.1) — arrivals on one target face must stay distinct
# --------------------------------------------------------------------------- #


def test_entry_thirds_two_identical_left_entries_flagged():
    """Two edges arriving on one target's LEFT face at the same point read as one
    doubled line — the buggy AWS example's two EC2->RDS edges at (0,0.5)."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "rds", (1.0, 0.5), (0.0, 0.5)),
        _edge_id("e2", "b", "rds", (1.0, 0.5), (0.0, 0.5)),
    ])
    hits = geo.check_entry_thirds(g)
    assert any(node == "rds" and "merge" in reason for node, reason in hits)


def test_entry_thirds_two_distinct_left_entries_clean():
    """Distinct entries on one face (0.33/0.66) do not merge — clean."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "rds", (1.0, 0.5), (0.0, 0.33)),
        _edge_id("e2", "b", "rds", (1.0, 0.5), (0.0, 0.66)),
    ])
    assert geo.check_entry_thirds(g) == []


def test_entry_thirds_single_entry_clean():
    """One arrival on a face is always fine."""
    g = DiagramGeometry(edges=[_edge_id("e1", "a", "rds", (1.0, 0.5), (0.0, 0.5))])
    assert geo.check_entry_thirds(g) == []


def test_entry_thirds_over_connected_face_flagged():
    """A fourth arrival on one face is over-connected."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "t", (1.0, 0.5), (0.0, 0.2)),
        _edge_id("e2", "b", "t", (1.0, 0.5), (0.0, 0.4)),
        _edge_id("e3", "c", "t", (1.0, 0.5), (0.0, 0.6)),
        _edge_id("e4", "d", "t", (1.0, 0.5), (0.0, 0.8)),
    ])
    hits = geo.check_entry_thirds(g)
    assert any("over-connected" in reason for _, reason in hits)


def test_entry_thirds_landscape_is_error_flow_is_warning():
    """entry-thirds is WARNING for flow, ERROR for landscape (routing-family
    escalation, matching edge-direction/edge-float)."""
    g = DiagramGeometry(edges=[
        _edge_id("e1", "a", "rds", (1.0, 0.5), (0.0, 0.5)),
        _edge_id("e2", "b", "rds", (1.0, 0.5), (0.0, 0.5)),
    ])
    flow = Artifact(kind="diagram", node_names=["rds"], geometry=g, diagram_class="flow")
    land = Artifact(kind="diagram", node_names=["rds"], geometry=g, diagram_class="landscape")
    assert _sev(lint(flow), "entry-thirds") == Severity.WARNING.value
    assert _sev(lint(land), "entry-thirds") == Severity.ERROR.value


# --------------------------------------------------------------------------- #
# edge-routing (v1.5.1) — an edge must not pierce its own target's icon
# --------------------------------------------------------------------------- #


def _box(id_, x, y):
    return Box(id_, x, y, 78, 78)


def test_edge_routing_pierces_target_top_entry_from_below_flagged():
    """A TOP entry approached from a corridor BELOW the icon pierces the target
    glyph — the buggy ALB->S3 edge (enters the icon instead of from the top)."""
    tgt = _box("s3", 320, 620)
    src = _box("alb", 520, 320)
    # Final waypoint sits below the icon (y=690), entry pinned to top-centre.
    e = EdgeGeom(
        id="e7", source="alb", target="s3", orthogonal=True,
        exit=(0.5, 1.0), entry=(0.5, 0.0),
        points=[(559.0, 690.0), (359.0, 690.0)],
    )
    g = DiagramGeometry(nodes={"s3": tgt, "alb": src}, edges=[e])
    hits = geo.check_edge_routing(g)
    assert any(reason == "pierces-target-s3" for _eid, reason in hits)


def test_edge_routing_top_entry_from_above_clean():
    """The same top entry approached correctly from ABOVE is clean."""
    tgt = _box("s3", 320, 620)
    src = _box("alb", 320, 320)
    e = EdgeGeom(
        id="e", source="alb", target="s3", orthogonal=True,
        exit=(0.5, 1.0), entry=(0.5, 0.0),
        points=[(359.0, 560.0)],  # above the icon top (y=620)
    )
    g = DiagramGeometry(nodes={"s3": tgt, "alb": src}, edges=[e])
    assert geo.check_edge_routing(g) == []


def test_edge_routing_pierce_is_error_in_linter():
    """A target pierce escalates edge-routing to ERROR (blocks publication)."""
    tgt = _box("s3", 320, 620)
    src = _box("alb", 520, 320)
    e = EdgeGeom(
        id="e7", source="alb", target="s3", orthogonal=True,
        exit=(0.5, 1.0), entry=(0.5, 0.0),
        points=[(559.0, 690.0), (359.0, 690.0)],
    )
    g = DiagramGeometry(nodes={"s3": tgt, "alb": src}, edges=[e])
    art = Artifact(kind="diagram", node_names=["s3", "alb"], geometry=g)
    assert _sev(lint(art), "edge-routing") == Severity.ERROR.value


# --------------------------------------------------------------------------- #
# edge-routing (v1.5.4) — a WAYPOINTED orthogonal edge whose real KNEE path cuts
# an unrelated icon. Before 1.5.4 any waypointed edge was trusted entirely on the
# crossing criterion, so the devoxx e8 horizontal stub through RDS linted clean.
# --------------------------------------------------------------------------- #


def test_edge_routing_knee_through_unrelated_node_flagged():
    """The devoxx e8 defect: EC2->S3 exits the RIGHT face at y=215.6, first
    waypoint is up-and-right, so draw.io draws a horizontal-first knee — a
    horizontal leg at y=215.6 that slices the RDS icon before turning up. The raw
    diagonal between the exit and the waypoint stepped over RDS; the knee path
    does not."""
    ec2a = Box("ec2a", 720, 200, 78, 78)
    rds = Box("rds", 940, 200, 78, 78)       # unrelated node in the corridor
    s3 = Box("s3", 1160, 360, 78, 78)
    e = EdgeGeom(
        id="e8", source="ec2a", target="s3", orthogonal=True,
        exit=(1.0, 0.2), entry=(0.5, 0.0),
        points=[(1078.0, 140.0), (1199.0, 140.0)],
    )
    g = DiagramGeometry(nodes={"ec2a": ec2a, "rds": rds, "s3": s3}, edges=[e])
    hits = geo.check_edge_routing(g)
    assert any(reason == "knee-through-rds" for _eid, reason in hits), hits


def test_edge_routing_knee_through_is_error_in_linter():
    """A knee crossing an unrelated icon escalates edge-routing to ERROR (it is a
    ``through-`` reason), blocking publication on any class."""
    ec2a = Box("ec2a", 720, 200, 78, 78)
    rds = Box("rds", 940, 200, 78, 78)
    s3 = Box("s3", 1160, 360, 78, 78)
    e = EdgeGeom(
        id="e8", source="ec2a", target="s3", orthogonal=True,
        exit=(1.0, 0.2), entry=(0.5, 0.0),
        points=[(1078.0, 140.0), (1199.0, 140.0)],
    )
    g = DiagramGeometry(nodes={"ec2a": ec2a, "rds": rds, "s3": s3}, edges=[e])
    art = Artifact(kind="diagram", node_names=["ec2a", "rds", "s3"], geometry=g)
    assert _sev(lint(art), "edge-routing") == Severity.ERROR.value


def test_edge_routing_knee_clear_of_node_clean():
    """The same EC2->S3 edge routed so its FIRST leg clears RDS: the exit stub
    rises ABOVE the RDS row before turning right (waypoint x sits at the exit's x
    so the horizontal leg runs at y=140, above RDS). No knee cuts an icon."""
    ec2a = Box("ec2a", 720, 200, 78, 78)
    rds = Box("rds", 940, 200, 78, 78)
    s3 = Box("s3", 1160, 360, 78, 78)
    e = EdgeGeom(
        id="e8", source="ec2a", target="s3", orthogonal=True,
        exit=(1.0, 0.2), entry=(0.5, 0.0),
        # first waypoint shares the exit's x-column intent: the horizontal-first
        # knee from (798,215.6) to (798,140)... a leg already aligned in x runs
        # vertically up the gap just right of EC2a, clear of RDS at x=940.
        points=[(838.0, 140.0), (1199.0, 140.0)],
    )
    g = DiagramGeometry(nodes={"ec2a": ec2a, "rds": rds, "s3": s3}, edges=[e])
    assert geo.check_edge_routing(g) == []


def test_edge_routing_waypointed_axis_aligned_legs_clean():
    """A waypointed edge whose legs are already axis-aligned (no diagonal knee)
    is not expanded and not flagged when it clears every unrelated icon."""
    a = Box("a", 100, 100, 78, 78)
    b = Box("b", 500, 300, 78, 78)
    other = Box("other", 100, 300, 78, 78)   # not in either leg's corridor
    e = EdgeGeom(
        id="e", source="a", target="b", orthogonal=True,
        exit=(1.0, 0.5), entry=(0.0, 0.5),
        points=[(300.0, 139.0), (300.0, 339.0)],  # right, down, right — clean
    )
    g = DiagramGeometry(nodes={"a": a, "b": b, "other": other}, edges=[e])
    assert geo.check_edge_routing(g) == []


# --------------------------------------------------------------------------- #
# edge-crosses-container-label (v1.5.1) — a corridor must clear a VPC caption
# --------------------------------------------------------------------------- #


def _container(cid, x, y, w, h):
    return Box(cid, x, y, w, h)


def test_container_label_flags_run_through_vpc_caption():
    """A horizontal corridor along a VPC's top edge slices its caption."""
    g = DiagramGeometry(
        nodes={
            "src": Box("src", 100, 90, 78, 78),   # outside the VPC (above)
            "tgt": Box("tgt", 1300, 250, 78, 78),  # inside the VPC
        },
        containers={"vpc": _container("vpc", 1240, 220, 860, 900)},
        container_labels={"vpc": "vpc-passive us-west-2"},
        edges=[
            EdgeGeom(
                id="e", source="src", target="tgt", orthogonal=True,
                exit=(1.0, 0.5), entry=(0.5, 0.0),
                # corridor runs at y=230, INSIDE the VPC top caption band (220..250)
                points=[(450.0, 230.0), (1340.0, 230.0)],
            )
        ],
    )
    hits = geo.check_edge_crosses_container_label(g)
    assert any(cid == "vpc" for _eid, cid in hits)


def test_container_label_clear_run_above_vpc_top_is_ok():
    """The same run lifted ABOVE the VPC top edge (y=210) clears the caption."""
    g = DiagramGeometry(
        nodes={
            "src": Box("src", 100, 90, 78, 78),
            "tgt": Box("tgt", 1300, 250, 78, 78),
        },
        containers={"vpc": _container("vpc", 1240, 220, 860, 900)},
        container_labels={"vpc": "vpc-passive us-west-2"},
        edges=[
            EdgeGeom(
                id="e", source="src", target="tgt", orthogonal=True,
                exit=(1.0, 0.5), entry=(0.5, 0.0),
                points=[(450.0, 210.0), (1340.0, 210.0)],  # above the VPC top
            )
        ],
    )
    assert geo.check_edge_crosses_container_label(g) == []


def test_container_label_short_caption_not_flagged_on_right_corridor():
    """A vertical corridor on the RIGHT of a wide AZ box clears a SHORT caption
    ('az-a1'), so it is not flagged (per-caption width, not full box width)."""
    g = DiagramGeometry(
        nodes={
            "src": Box("src", 120, 250, 78, 78),   # above the AZ
            "tgt": Box("tgt", 120, 780, 78, 78),   # below the AZ
        },
        containers={"az": _container("az", 90, 390, 800, 328)},
        container_labels={"az": "az-a1"},
        edges=[
            EdgeGeom(
                id="e", source="src", target="tgt", orthogonal=True,
                exit=(1.0, 0.5), entry=(0.5, 0.0),
                # corridor at x=210 — right of the short 'az-a1' caption (~x<170)
                points=[(210.0, 290.0), (210.0, 770.0), (160.0, 770.0)],
            )
        ],
    )
    assert geo.check_edge_crosses_container_label(g) == []


def test_container_label_lint_rule_is_warning():
    from rule_engine.linter import RULE_EDGE_CROSSES_CONTAINER_LABEL, RULE_SEVERITIES, Severity
    assert RULE_SEVERITIES[RULE_EDGE_CROSSES_CONTAINER_LABEL] == Severity.WARNING


def test_all_golden_landscapes_clear_container_labels():
    """Every shipped HA landscape keeps its edges clear of container captions."""
    import glob
    for path in sorted(glob.glob(os.path.join(HERE, "examples", "*", "02-*-landscape.drawio"))):
        g = geo.build_geometry(open(path, encoding="utf-8").read())
        assert geo.check_edge_crosses_container_label(g) == [], path


# --------------------------------------------------------------------------- #
# adaptive corridor routing (v1.5.1) — generalising the reviewer's hand-route
# --------------------------------------------------------------------------- #


def test_free_left_corridor_used_for_same_column_tier_skip():
    """A spine to a same-column target past an intermediate node routes down the
    LEFT gap and enters the target's LEFT face (edge 4: lb->app-az2), not a
    right corridor looping back-left."""
    import sys, os as _os
    sys.path.insert(0, _os.path.join(HERE, "src"))
    sys.path.insert(0, _os.path.join(HERE, "scripts"))
    from ha_multiregion_common import build_landscape
    import importlib
    skin = importlib.import_module("build_aws_ha_example").SKIN
    g = geo.build_geometry(build_landscape(skin))
    l4 = next(e for e in g.edges if e.id == "l4")
    # Enters app_a2 from the LEFT (entryX == 0), exits the source bottom.
    assert l4.entry[0] is not None and l4.entry[0] <= 0.0, f"l4 entry {l4.entry}"
    assert l4.exit[1] is not None and l4.exit[1] >= 1.0, f"l4 exit {l4.exit}"
    # The vertical corridor runs LEFT of the source column (x < lb_a.x).
    lb_a = g.nodes["lb_a"]
    xs = [p[0] for p in l4.points]
    assert min(xs) < lb_a.x, f"l4 corridor not left of the column: {l4.points}"
    # And it crosses no unrelated icon (app_a1 sits in the column between them).
    from rule_engine.geometry import segment_crosses_box as _sx
    poly = [(g.nodes["lb_a"].x + l4.exit[0] * 78, g.nodes["lb_a"].y + l4.exit[1] * 78)] \
        + list(l4.points) \
        + [(g.nodes["app_a2"].x + l4.entry[0] * 78, g.nodes["app_a2"].y + l4.entry[1] * 78)]
    app_a1 = g.nodes["app_a1"]
    assert not any(_sx(p, q, app_a1) for p, q in zip(poly, poly[1:])), "l4 crosses app_a1"


def test_cross_region_uses_inter_row_corridor_and_left_entry():
    """A cross-region hop whose target has a free left approach routes in the
    inter-row gap and enters the target's LEFT face (edge 11: obj_a1->obj_b1),
    clearing the target AZ's top caption."""
    import sys, os as _os
    sys.path.insert(0, _os.path.join(HERE, "src"))
    sys.path.insert(0, _os.path.join(HERE, "scripts"))
    from ha_multiregion_common import build_landscape
    import importlib
    skin = importlib.import_module("build_aws_ha_example").SKIN
    g = geo.build_geometry(build_landscape(skin))
    l11 = next(e for e in g.edges if e.id == "l11")
    assert l11.entry[0] is not None and l11.entry[0] <= 0.0, f"l11 entry {l11.entry}"
    # No part of l11 crosses the az-b1 container caption band.
    assert ("l11", "boundary-az-b1") not in geo.check_edge_crosses_container_label(g)
    # And l11 does not pierce its own target.
    assert not any(r.startswith("pierces") for _e, r in geo.check_edge_routing(g))


# --------------------------------------------------------------------------- #
# fan-out crossing fixes (v1.5.1): bottom-LEFT left-corridor branch; overflow
# valve spilling the farthest right fan-out edge onto the bottom face.
# --------------------------------------------------------------------------- #


def _aws_landscape_geo():
    import sys, os as _os
    sys.path.insert(0, _os.path.join(HERE, "src"))
    sys.path.insert(0, _os.path.join(HERE, "scripts"))
    from ha_multiregion_common import build_landscape
    import importlib
    skin = importlib.import_module("build_aws_ha_example").SKIN
    return geo.build_geometry(build_landscape(skin))


def _seg_list(g, e):
    s, t = g.nodes[e.source], g.nodes[e.target]
    sx = (s.x + (e.exit[0] if e.exit[0] is not None else 1.0) * s.w,
          s.y + (e.exit[1] if e.exit[1] is not None else 0.5) * s.h)
    tx = (t.x + (e.entry[0] if e.entry[0] is not None else 0.0) * t.w,
          t.y + (e.entry[1] if e.entry[1] is not None else 0.5) * t.h)
    p = [sx] + list(e.points) + [tx]
    return list(zip(p, p[1:]))


def _seg_intersect(a, b):
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    def rng(u, v):
        return (min(u, v), max(u, v))
    ax, ay = rng(x1, x2), rng(y1, y2)
    bx, by = rng(x3, x4), rng(y3, y4)
    return (max(ax[0], bx[0]) <= min(ax[1], bx[1])
            and max(ay[0], by[0]) <= min(ay[1], by[1]))


def test_fanout_source_branches_do_not_cross():
    """lb->app-az1/az2 (l3/l4) and app->cache/db/obj (l6/l5/l8) fan-outs have no
    pairwise segment crossings on the AWS landscape (v1.5.1 #1 + #2)."""
    import itertools
    g = _aws_landscape_geo()
    E = {e.id: e for e in g.edges}
    for a, b in itertools.combinations(("l3", "l4", "l5", "l6", "l8"), 2):
        crosses = sum(
            1 for sa in _seg_list(g, E[a]) for sb in _seg_list(g, E[b])
            if _seg_intersect(sa, sb)
        )
        assert crosses == 0, f"{a}x{b} crosses ({crosses})"


def test_left_corridor_branch_exits_bottom_left():
    """The left-corridor fan-out branch (l4) exits the source bottom-LEFT
    (exitX < 0.5) so it does not cross the centre straight-down branch (l3)."""
    g = _aws_landscape_geo()
    l4 = next(e for e in g.edges if e.id == "l4")
    assert l4.exit[1] is not None and l4.exit[1] >= 1.0, f"l4 not a bottom exit: {l4.exit}"
    assert l4.exit[0] is not None and l4.exit[0] < 0.5, f"l4 not bottom-LEFT: {l4.exit}"


def test_overflow_valve_spills_farthest_fanout_to_bottom():
    """app_a1 has 3 right fan-out targets (cache/db/obj); the farthest (obj, l8)
    spills onto the BOTTOM face, leaving <=2 exits on the right (v1.5.1 #2)."""
    g = _aws_landscape_geo()
    l8 = next(e for e in g.edges if e.id == "l8")
    assert l8.exit[1] is not None and l8.exit[1] >= 1.0, f"l8 not spilled to bottom: {l8.exit}"
    # The two kept right-face edges (l5 db, l6 cache) still exit right.
    for eid in ("l5", "l6"):
        e = next(x for x in g.edges if x.id == eid)
        assert e.exit[0] is not None and e.exit[0] >= 0.5, f"{eid} not right: {e.exit}"
    # All contract-legal + no crossings already covered by the check above.
    assert geo.check_edge_direction(g) == []

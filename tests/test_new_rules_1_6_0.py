"""Regression tests for the three rules added in v1.6.0.

* ``legend-placement`` — the Flow/Legend furniture must sit in the right margin.
  Unenforced before 1.6.0: a clean-room install parked both blocks in the LEFT
  margin under the external user and linted completely clean, while every shipped
  golden (built through ``diagram_layout.build_diagram``) puts them on the right.
* ``flow-legend`` — documented in ``diagram-lint.md`` from the first ruleset but
  never implemented. The generator always emitted the Flow cell, so the gap only
  bit a hand-authored diagram.
* ``node-connectivity`` — the 2026-09-25 audit's headline finding: every HA
  landscape drew 34 nodes joined by 12 edges, leaving 20 nodes unconnected.
"""

from __future__ import annotations

from rule_engine import geometry as geo
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom
from rule_engine.linter import (
    RULE_FLOW_LEGEND,
    RULE_LEGEND_PLACEMENT,
    RULE_NODE_CONNECTIVITY,
    Artifact,
    Edge,
    RULE_SEVERITIES,
    Severity,
    lint,
)


def _rules(result):
    return {f["rule"] for f in result["findings"]}


# =========================================================================== #
# legend-placement
# =========================================================================== #


#: Mirrors the real clean-room geometry: an Account box at x=560..1360 with the
#: Flow/Legend blocks 470 wide, so a left-margin placement (x=40, right=510) sits
#: clear of the container and produces the placement finding ALONE — exactly the
#: defect that shipped, with no overlap confusing the assertion.
def _legend_geo(flow_x: int, legend_x: int, container=(560, 100, 800, 600)):
    cx, cy, cw, ch = container
    return DiagramGeometry(
        containers={"account": Box("account", cx, cy, cw, ch)},
        text_boxes={
            "flow-legend": Box("flow-legend", flow_x, 700, 470, 160),
            "legend": Box("legend", legend_x, 880, 470, 160),
        },
        text_headings={"flow-legend": "Flow", "legend": "Legend"},
    )


def test_legend_in_the_right_margin_is_clean():
    """Container right edge is 1360; a box at 1370 clears it by one grid step."""
    assert geo.check_legend_placement(_legend_geo(1370, 1370)) == []


def test_legend_in_the_left_margin_is_flagged():
    """The clean-room defect: both blocks parked left of the diagram body."""
    findings = geo.check_legend_placement(_legend_geo(40, 40))
    assert findings == [
        ("flow-legend", "left-of-diagram-body"),
        ("legend", "left-of-diagram-body"),
    ]


def test_legend_flush_against_the_container_is_flagged():
    """Sitting exactly at the container's right edge leaves no margin."""
    findings = geo.check_legend_placement(_legend_geo(1360, 1360))
    assert [r for _, r in findings] == ["left-of-diagram-body"] * 2


def test_legend_overlapping_a_container_names_the_container():
    """A box drawn on top of the cloud reports which boundary it covers."""
    g = DiagramGeometry(
        containers={"vpc": Box("vpc", 100, 100, 800, 600)},
        text_boxes={"legend": Box("legend", 400, 200, 300, 160)},
        text_headings={"legend": "Legend"},
    )
    findings = geo.check_legend_placement(g)
    assert ("legend", "overlaps-vpc") in findings


def test_only_flow_and_legend_boxes_are_judged():
    """An arbitrary note box is not the Flow/Legend furniture and is ignored."""
    g = DiagramGeometry(
        containers={"account": Box("account", 100, 100, 800, 600)},
        text_boxes={"note": Box("note", 40, 120, 300, 160)},
        text_headings={"note": "Deployment notes"},
    )
    assert geo.check_legend_placement(g) == []


def test_diagram_with_no_containers_is_skipped():
    """No boundary body means there is no right margin to reserve against."""
    g = DiagramGeometry(
        text_boxes={"legend": Box("legend", 40, 120, 300, 160)},
        text_headings={"legend": "Legend"},
    )
    assert geo.check_legend_placement(g) == []


def test_legend_placement_is_case_insensitive_on_the_heading():
    g = _legend_geo(40, 40)
    g.text_headings = {"flow-legend": "flow", "legend": "LEGEND"}
    assert len(geo.check_legend_placement(g)) == 2


def test_a_left_margin_box_overlapping_the_cloud_reports_both_reasons():
    """When the misplaced furniture also covers a boundary, both the margin and
    the overlap are named so the author knows the full extent of the defect."""
    g = _legend_geo(40, 40, container=(100, 100, 800, 900))
    reasons = sorted(r for _, r in geo.check_legend_placement(g))
    assert reasons == [
        "left-of-diagram-body",
        "left-of-diagram-body",
        "overlaps-account",
        "overlaps-account",
    ]


def test_legend_placement_rule_is_a_warning():
    assert RULE_SEVERITIES[RULE_LEGEND_PLACEMENT] is Severity.WARNING


def test_legend_placement_surfaces_through_the_linter():
    art = Artifact(kind="diagram", is_drawio=True, geometry=_legend_geo(40, 40))
    assert RULE_LEGEND_PLACEMENT in _rules(lint(art))


def test_legend_placement_does_not_block_publication():
    art = Artifact(kind="diagram", is_drawio=True, geometry=_legend_geo(40, 40))
    assert lint(art)["eligible_for_publication"] is True


# =========================================================================== #
# flow-legend
# =========================================================================== #


_FLOW_OK = ["Flow", "1. User resolves DNS", "2. CDN forwards to the ALB"]


def _numbered(*labels):
    return [Edge(source="a", target="b", label=lbl) for lbl in labels]


def test_numeric_markers_with_a_covering_flow_legend_is_clean():
    art = Artifact(kind="diagram", edges=_numbered("1", "2"),
                   flow_legend_lines=_FLOW_OK)
    assert RULE_FLOW_LEGEND not in _rules(lint(art))


def test_numeric_markers_with_no_flow_cell_is_flagged():
    """Numbered edges but the Flow cell is absent entirely."""
    art = Artifact(kind="diagram", edges=_numbered("1", "2"),
                   flow_legend_lines=[])
    assert RULE_FLOW_LEGEND in _rules(lint(art))


def test_flow_legend_missing_one_marker_is_flagged():
    """Marker 3 is used on an edge but has no ``3.`` line."""
    art = Artifact(kind="diagram", edges=_numbered("1", "2", "3"),
                   flow_legend_lines=_FLOW_OK)
    assert RULE_FLOW_LEGEND in _rules(lint(art))


def test_prose_edge_labels_are_unaffected():
    """A diagram using descriptive labels instead of numeric markers never trips
    the rule, even with no Flow cell."""
    art = Artifact(
        kind="diagram",
        edges=_numbered("reads from", "writes to"),
        flow_legend_lines=[],
    )
    assert RULE_FLOW_LEGEND not in _rules(lint(art))


def test_unparsed_flow_legend_is_skipped_not_assumed_failed():
    """A programmatic artifact carries ``None`` (not parsed); the rule skips."""
    art = Artifact(kind="diagram", edges=_numbered("1", "2"),
                   flow_legend_lines=None)
    assert RULE_FLOW_LEGEND not in _rules(lint(art))


def test_flow_legend_accepts_a_parenthesis_separator():
    art = Artifact(
        kind="diagram",
        edges=_numbered("1", "2"),
        flow_legend_lines=["Flow", "1) first step", "2) second step"],
    )
    assert RULE_FLOW_LEGEND not in _rules(lint(art))


def test_flow_legend_ignores_an_unlabelled_edge():
    """An edge with no label is ``edge-label``'s problem, not this rule's."""
    art = Artifact(
        kind="diagram",
        edges=[Edge(source="a", target="b", label=None), Edge(label="1")],
        flow_legend_lines=["Flow", "1. only step"],
    )
    assert RULE_FLOW_LEGEND not in _rules(lint(art))


def test_flow_legend_rule_is_a_warning():
    assert RULE_SEVERITIES[RULE_FLOW_LEGEND] is Severity.WARNING


# =========================================================================== #
# node-connectivity
# =========================================================================== #


def _connectivity_geo(node_ids, edges, overlay=None):
    return DiagramGeometry(
        nodes={nid: Box(nid, 0, 0, 78, 78) for nid in node_ids},
        edges=[
            EdgeGeom(id=f"e{i}", source=s, target=t, orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5))
            for i, (s, t) in enumerate(edges)
        ],
        containers={"vpc": Box("vpc", -50, -50, 900, 900)},
        overlay_nodes=dict(overlay or {}),
    )


def test_fully_connected_diagram_is_clean():
    g = _connectivity_geo(["lb", "app", "db"], [("lb", "app"), ("app", "db")])
    assert geo.check_node_connectivity(g) == []


def test_floating_node_is_flagged():
    g = _connectivity_geo(["lb", "app", "cache"], [("lb", "app")])
    assert geo.check_node_connectivity(g) == ["cache"]


def test_every_floating_node_is_reported_sorted():
    g = _connectivity_geo(["lb", "app", "queue", "cache"], [("lb", "app")])
    assert geo.check_node_connectivity(g) == ["cache", "queue"]


def test_overlay_marked_node_is_exempt():
    """A ``standby`` passive peer declares why it carries no edges, so it is
    legitimately unconnected (the sanctioned mirror-tier pattern)."""
    g = _connectivity_geo(
        ["lb", "app", "app_passive"],
        [("lb", "app")],
        overlay={"app_passive": "standby"},
    )
    assert geo.check_node_connectivity(g) == []


def test_an_overlay_marker_does_not_exempt_an_unmarked_sibling():
    g = _connectivity_geo(
        ["lb", "app", "app_passive", "cache_passive"],
        [("lb", "app")],
        overlay={"app_passive": "standby"},
    )
    assert geo.check_node_connectivity(g) == ["cache_passive"]


def test_boundary_containers_are_not_counted():
    """Containers are a grouping device, never a participant — and they are
    already absent from ``geo.nodes``."""
    g = _connectivity_geo(["app"], [("lb", "app")])
    assert "vpc" not in geo.check_node_connectivity(g)


def test_a_node_reached_only_as_an_edge_target_is_connected():
    g = _connectivity_geo(["lb", "app"], [("lb", "app")])
    assert geo.check_node_connectivity(g) == []


def test_empty_diagram_is_clean():
    assert geo.check_node_connectivity(DiagramGeometry()) == []


def test_node_connectivity_rule_is_a_warning_on_both_classes():
    assert RULE_SEVERITIES[RULE_NODE_CONNECTIVITY] is Severity.WARNING
    g = _connectivity_geo(["lb", "app", "cache"], [("lb", "app")])
    for cls in ("flow", "landscape"):
        art = Artifact(kind="diagram", is_drawio=True, geometry=g,
                       diagram_class=cls, summary_of="01-summary")
        findings = {f["rule"]: f["severity"] for f in lint(art)["findings"]}
        assert findings.get(RULE_NODE_CONNECTIVITY) == Severity.WARNING.value


def test_node_connectivity_surfaces_through_the_linter():
    g = _connectivity_geo(["lb", "app", "cache"], [("lb", "app")])
    art = Artifact(kind="diagram", is_drawio=True, geometry=g)
    assert RULE_NODE_CONNECTIVITY in _rules(lint(art))


# =========================================================================== #
# overlay_nodes parsing (the exemption's input)
# =========================================================================== #


_DRAWIO_WITH_OVERLAY = """<mxfile><diagram><mxGraphModel><root>
  <mxCell id="0" /><mxCell id="1" parent="0" />
  <mxCell id="app" value="app" style="shape=mxgraph.aws4.resourceIcon;" vertex="1" parent="1">
    <mxGeometry x="100" y="100" width="78" height="78" as="geometry" />
  </mxCell>
  <mxCell id="app_passive" value="app-passive" style="shape=mxgraph.aws4.resourceIcon;dashed=1;overlay=standby;" vertex="1" parent="1">
    <mxGeometry x="300" y="100" width="78" height="78" as="geometry" />
  </mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def test_build_geometry_records_the_overlay_term_per_node():
    g = geo.build_geometry(_DRAWIO_WITH_OVERLAY)
    assert g.overlay_nodes == {"app_passive": "standby"}
    assert set(g.nodes) == {"app", "app_passive"}


def test_overlay_marked_node_is_exempt_end_to_end():
    """Parsed from real XML: only the unmarked node is reported."""
    g = geo.build_geometry(_DRAWIO_WITH_OVERLAY)
    assert geo.check_node_connectivity(g) == ["app"]


# =========================================================================== #
# text-box geometry capture (legend-placement's input)
# =========================================================================== #


_DRAWIO_WITH_TEXT = """<mxfile><diagram><mxGraphModel><root>
  <mxCell id="0" /><mxCell id="1" parent="0" />
  <mxCell id="account" value="Account 1" style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;dashed=1;" vertex="1" parent="1">
    <mxGeometry x="100" y="100" width="800" height="600" as="geometry" />
  </mxCell>
  <mxCell id="flow-legend" value="Flow&#10;1. first step" style="text;fillColor=#FFFFFF;strokeColor=#000000;" vertex="1" parent="1">
    <mxGeometry x="40" y="750" width="300" height="60" as="geometry" />
  </mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def test_text_cells_are_captured_separately_from_nodes():
    """A text cell must never be counted as a node, but its box is still needed
    to judge the right margin."""
    g = geo.build_geometry(_DRAWIO_WITH_TEXT)
    assert "flow-legend" not in g.nodes
    assert g.text_boxes["flow-legend"].x == 40
    assert g.text_headings["flow-legend"] == "Flow"


def test_left_margin_flow_cell_is_flagged_end_to_end():
    g = geo.build_geometry(_DRAWIO_WITH_TEXT)
    assert geo.check_legend_placement(g) == [
        ("flow-legend", "left-of-diagram-body")
    ]


# =========================================================================== #
# edge-approach + route orthogonalisation (v1.6.0)
#
# An orthogonalEdgeStyle edge never draws a diagonal: draw.io inserts its OWN
# corner between two unaligned points and picks the direction. So an unaligned
# waypoint is not a diagonal on screen — it is a corner the author did not
# specify, which is how an edge ends up grazing a glyph or sliding along a
# container border while every waypoint looks deliberate. Measured across the
# shipped corpus before v1.6.0, 30 routed edges had such a leg.
#
# The three cases below are taken verbatim from a reviewer's hand-edit of the AWS
# HA landscape, which is what surfaced the pattern.
# =========================================================================== #

_RIGHT = frozenset({"right"})
_LEFT = frozenset({"left"})
_TOP = frozenset({"top"})
_BOTTOM = frozenset({"bottom"})


def test_diagonal_first_leg_is_pulled_level_with_the_exit():
    """Reviewer edit 1 (``dns -> lb_b``): the corridor's first waypoint sat 30px
    below the exit, so the opening leg was diagonal. It is pulled level."""
    out = geo.orthogonalise_route(
        (420, 140), [(450, 170), (450, 270)], (1300, 270), _RIGHT, _LEFT
    )
    assert out[0] == (450, 140)


def test_overshoot_at_the_target_collapses_to_one_run():
    """Reviewer edit 1, other end: the route dropped to y=410 and came back up to
    the entry at 380. The backtrack collapses into a single run."""
    out = geo.orthogonalise_route(
        (420, 140), [(450, 140), (450, 270), (1290, 270), (1290, 410)],
        (1300, 380), _RIGHT, _LEFT,
    )
    assert out[-1] == (1290, 380)
    assert (1290, 410) not in out


def test_horizontal_leg_into_a_top_entry_gets_an_approach_lane():
    """Reviewer edit 3 (``fn_a -> api_a1``): the final leg ran ALONG the target's
    top border into a top-centre entry, so the arrow slid across the glyph's edge.
    An approach lane one grid step above the node is inserted and the turn moves
    there, so the last leg drops straight in."""
    out = geo.orthogonalise_route(
        (640, 360), [(710, 360), (710, 320), (200, 320), (200, 700)],
        (160, 700), _RIGHT, _TOP,
    )
    assert out[-2:] == [(200, 690), (160, 690)]


def test_approach_lane_side_comes_from_the_face_not_the_route():
    """A top entry is met from ABOVE even when the incoming run is level with the
    node's top border — the degenerate case that decided the lane by comparing the
    neighbour's y to the contact's and put the lane BELOW the node."""
    out = geo.orthogonalise_route(
        (400, 700), [(300, 700)], (160, 700), _RIGHT, _TOP
    )
    assert all(y < 700 for _x, y in out), f"lane must sit above the entry: {out}"


def test_bottom_exit_leaves_vertically():
    g_out = geo.orthogonalise_route(
        (900, 280), [(860, 320), (860, 720)], (880, 720), _BOTTOM, _LEFT
    )
    poly = [(900, 280)] + g_out + [(880, 720)]
    assert geo.leg_axis(poly[0], poly[1]) == "V"
    assert all(geo.leg_axis(a, b) != "D" for a, b in zip(poly, poly[1:]))


def test_an_already_aligned_route_is_unchanged():
    pts = [(450, 140), (450, 270), (1290, 270), (1290, 380)]
    assert geo.orthogonalise_route(
        (420, 140), pts, (1300, 380), _RIGHT, _LEFT
    ) == pts


def test_orthogonalise_is_idempotent():
    once = geo.orthogonalise_route(
        (640, 360), [(710, 360), (710, 320), (200, 320), (200, 700)],
        (160, 700), _RIGHT, _TOP,
    )
    twice = geo.orthogonalise_route((640, 360), once, (160, 700), _RIGHT, _TOP)
    assert once == twice


def test_every_leg_is_axis_aligned_after_the_rewrite():
    out = geo.orthogonalise_route(
        (200, 160), [(230, 170), (230, 250), (490, 250), (490, 170)],
        (560, 160), _RIGHT, _LEFT,
    )
    poly = [(200, 160)] + out + [(560, 160)]
    assert all(geo.leg_axis(a, b) in ("H", "V") for a, b in zip(poly, poly[1:]))


def test_corner_contact_accepts_either_axis():
    """A contact on two faces (a corner) constrains nothing."""
    assert geo.required_leg_axis(frozenset({"right", "top"})) is None
    assert geo.required_leg_axis(_RIGHT) == "H"
    assert geo.required_leg_axis(_TOP) == "V"
    assert geo.required_leg_axis(frozenset()) is None


def test_grid_resolve_keeps_the_contact_on_its_face():
    """The face coordinate is never snapped. A 64px icon at x=540 has its right
    edge at 604; rounding that to 600 would move the contact INSIDE the glyph and
    silently break the directional contract."""
    box = Box("n", 540, 440, 64, 64)
    (ax, ay), (fx, fy) = geo.grid_resolve_contact(box, (1.0, 0.25))
    assert ax == 604, "the right-face x must stay on the face"
    assert fx == 1.0
    assert ay % 10 == 0, "the along-face y must land on the grid"
    assert "right" in geo.contact_faces(fx, fy)


def test_grid_resolve_snaps_the_along_face_coordinate():
    box = Box("n", 880, 440, 78, 78)
    _abs, (fx, fy) = geo.grid_resolve_contact(box, (1.0, 0.25))
    assert 880 + fx * 78 == 958          # right face preserved
    assert (440 + fy * 78) % 10 == 0     # y snapped (459.5 -> 460)


def test_grid_resolve_band_pin_snaps_both_axes():
    """A pin on no face has no face coordinate to protect."""
    box = Box("n", 100, 100, 78, 78)
    (ax, ay), _frac = geo.grid_resolve_contact(box, (0.5, 0.5))
    assert ax % 10 == 0 and ay % 10 == 0


# --- the lint rule --------------------------------------------------------- #


def _approach_geo(exit_frac, entry_frac, points):
    return DiagramGeometry(
        nodes={
            "a": Box("a", 100, 100, 78, 78),
            "b": Box("b", 600, 400, 78, 78),
        },
        edges=[EdgeGeom(id="e1", source="a", target="b", orthogonal=True,
                        exit=exit_frac, entry=entry_frac, points=points)],
    )


def test_rule_flags_a_diagonal_leg():
    g = _approach_geo((1.0, 0.5), (0.0, 0.5), [(300, 200)])
    reasons = [r for _i, r in geo.check_edge_approach(g)]
    assert "diagonal-leg" in reasons


def test_rule_flags_an_exit_leg_missing_its_face():
    """A right-face exit met by a vertical leg."""
    g = _approach_geo((1.0, 0.5), (0.0, 0.5), [(178, 300), (600, 300)])
    reasons = [r for _i, r in geo.check_edge_approach(g)]
    assert any(r.startswith("exit-leg-V") for r in reasons)


def test_rule_flags_an_entry_leg_missing_its_face():
    """A top-face entry met by a horizontal leg along the border."""
    g = _approach_geo((1.0, 0.5), (0.5, 0.0), [(300, 139), (300, 400), (500, 400)])
    reasons = [r for _i, r in geo.check_edge_approach(g)]
    assert any(r.startswith("entry-leg-H") for r in reasons)


def test_rule_is_clean_on_an_aligned_route():
    g = _approach_geo((1.0, 0.5), (0.0, 0.5), [(300, 139), (300, 439)])
    assert geo.check_edge_approach(g) == []


def test_rule_skips_a_straight_edge_with_no_waypoints():
    g = _approach_geo((1.0, 0.5), (0.0, 0.5), [])
    assert geo.check_edge_approach(g) == []


def test_rule_skips_a_floating_contact():
    g = _approach_geo((None, None), (0.0, 0.5), [(300, 200)])
    assert geo.check_edge_approach(g) == []


def test_rule_severity_and_linter_wiring():
    from rule_engine.linter import RULE_EDGE_APPROACH
    assert RULE_SEVERITIES[RULE_EDGE_APPROACH] is Severity.WARNING
    g = _approach_geo((1.0, 0.5), (0.0, 0.5), [(300, 200)])
    art = Artifact(kind="diagram", is_drawio=True, geometry=g)
    result = lint(art)
    assert RULE_EDGE_APPROACH in _rules(result)
    assert result["eligible_for_publication"] is True

"""1.13.0 phase 3 item 17 — lint residuals.

Three residuals from the phase-2 05-08 feedback (F3, F5, F19):

1. ``edge-label`` names its offenders and fires on a materialised ``*-a`` / ``*-b``
   peering leg whose label is empty (it has no exemption — the legs are labelled
   now, so a labelled leg passes and an empty one is reported by id).
2. a NON-numeric text edge label (a ``peering`` leg label, a descriptive label)
   that rides a Boundary container border is flagged under
   ``marker-on-container-border`` (F3: 08's ``peering`` label on the account
   border), the text sibling of the numeric marker case.
3. ``legend-boundary-coverage`` is extended beyond Outer / Inner boundary lines:
   a Legend naming a Region / Availability Zone / Subnet that is not drawn is
   flagged (F5: 08's "Account > Region > VPC" with no Region box).
"""
from __future__ import annotations

from rule_engine.geometry import (
    Box,
    DiagramGeometry,
    EdgeGeom,
    check_legend_boundary_coverage,
    check_text_label_on_container_border,
    text_label_boxes,
)
from rule_engine.linter import _check_edge_label


# --- 1. edge-label offenders + materialised peering legs ------------------

class _Edge:
    def __init__(self, id, source, target, label):
        self.id, self.source, self.target, self.label = id, source, target, label


class _DiagramArtifact:
    kind = "diagram"
    diagram_class = "flow"

    def __init__(self, edges, node_names=("a", "b")):
        self.edges = edges
        self.node_names = node_names


def test_edge_label_fires_on_empty_peering_leg_and_names_it():
    edges = [
        _Edge("vpc-peer-a", "boundary-vpc", "pcx", "1"),     # labelled
        _Edge("vpc-peer-b", "pcx", "atlas", ""),             # empty -> offender
    ]
    hit = _check_edge_label(_DiagramArtifact(edges))
    assert hit, "an empty *-b leg must fire edge-label"
    assert "vpc-peer-b" in hit.offenders
    assert "vpc-peer-a" not in hit.offenders


def test_edge_label_clean_when_every_leg_labelled():
    edges = [
        _Edge("vpc-peer-a", "boundary-vpc", "pcx", "1"),
        _Edge("vpc-peer-b", "pcx", "atlas", "peering"),
    ]
    assert _check_edge_label(_DiagramArtifact(edges)) is False


# --- 2. text edge label on a container border -----------------------------

def _geo_text_label_at(mid_x: float) -> DiagramGeometry:
    """A straight edge labelled 'peering' whose midpoint lands at ``mid_x`` on
    y=400; a container whose right edge sits at x=600 so the label rides it when
    ``mid_x≈600``."""
    g = DiagramGeometry(
        nodes={
            "a": Box("a", 400, 361, 78, 78),   # right face x=478
            "b": Box("b", 722, 361, 78, 78),   # left face x=722
        },
        containers={
            "boundary-account": Box("boundary-account", 60, 120, 540, 560),  # right=600
        },
        edges=[
            EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="peering"),
        ],
    )
    return g


def test_text_label_box_centred_on_midpoint():
    g = _geo_text_label_at(600)
    box = text_label_boxes(g)["e"]
    # midpoint of the single straight segment is x=600, y=400.
    assert abs((box.x + box.right) / 2.0 - 600.0) < 0.5
    assert abs((box.y + box.bottom) / 2.0 - 400.0) < 0.5


def test_text_label_on_container_border_is_flagged():
    g = _geo_text_label_at(600)
    findings = check_text_label_on_container_border(g)
    assert ("e", "boundary-account.right") in findings


def test_numeric_marker_is_not_a_text_label():
    g = _geo_text_label_at(600)
    g.edges[0].label = "1"  # numeric marker — handled by the marker rule, not here
    assert check_text_label_on_container_border(g) == []


# --- 3. legend-boundary-coverage region / AZ / subnet ---------------------

def _geo_account_only() -> DiagramGeometry:
    """An account box with a VPC nested inside it (outer + inner), but NO region
    / AZ / subnet container."""
    return DiagramGeometry(
        nodes={"svc": Box("svc", 200, 300, 78, 78)},
        containers={
            "account": Box("account", 60, 120, 900, 500),
            "vpc": Box("vpc", 120, 200, 700, 380),
        },
        edges=[],
    )


def test_legend_names_undrawn_region_is_flagged():
    g = _geo_account_only()
    legend = [
        "Outer boundary = Account",
        "Inner boundary = VPC",
        "Account > Region > VPC",   # names Region, which is NOT drawn
    ]
    # drawn kinds: account + vpc only (no region)
    drawn_kinds = {"account", "vpc"}
    offenders = check_legend_boundary_coverage(g, legend, drawn_kinds)
    assert "Account > Region > VPC" in offenders


def test_legend_region_line_clean_when_region_drawn():
    g = _geo_account_only()
    legend = ["Account > Region > VPC"]
    drawn_kinds = {"account", "region", "vpc"}
    assert check_legend_boundary_coverage(g, legend, drawn_kinds) == []


def test_legend_region_extension_inert_without_drawn_kinds():
    # Precision-first: no classification available (drawn_kinds=None) -> only the
    # structural outer/inner check runs; a Region mention is not judged.
    g = _geo_account_only()
    legend = ["Account > Region > VPC"]
    assert check_legend_boundary_coverage(g, legend, None) == []


def test_legend_subnet_and_az_named_but_not_drawn():
    g = _geo_account_only()
    legend = [
        "Subnet = private subnet",
        "Availability Zone = AZ-a",
    ]
    drawn_kinds = {"account", "vpc"}
    offenders = check_legend_boundary_coverage(g, legend, drawn_kinds)
    assert "Subnet = private subnet" in offenders
    assert "Availability Zone = AZ-a" in offenders


def test_legend_outer_inner_still_structural():
    # The existing structural outer/inner check is unchanged.
    g = _geo_account_only()
    # account-only (no nested): remove the vpc so inner is not drawn
    g2 = DiagramGeometry(
        nodes={"svc": Box("svc", 200, 300, 78, 78)},
        containers={"account": Box("account", 60, 120, 900, 500)},
        edges=[],
    )
    legend = ["Outer boundary = Account", "Inner boundary = VPC"]
    offenders = check_legend_boundary_coverage(g2, legend, {"account"})
    assert "Inner boundary = VPC" in offenders
    assert "Outer boundary = Account" not in offenders

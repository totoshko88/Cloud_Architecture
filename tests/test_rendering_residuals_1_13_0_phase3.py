"""1.13.0 phase 3 item 16 — rendering residuals.

Residuals from the phase-2 diagram feedback (09-13 A, 12 E) that shipped:

1. ``standby`` label suffix is not doubled: a node the author already captioned
   ``… standby`` must stay ``RDS standby``, not become ``RDS standby-standby``.
2. ``PlacedDiagram.layout_warnings`` lists only findings present in the FINAL
   placed geometry (the 12 ``container-padding: ('p-apigw','trust-box')`` noise
   on a result the linter passes clean is gone).
3. a numbered flow-marker is kept OFF a Boundary container caption, and
   ``marker-on-container-caption`` flags one that lands there.

The external_cloud / peer_account leaf caption-strip resize is NOT shipped (it
moved SEP 09 geometry); see the note below and the CHANGELOG.
"""
from __future__ import annotations

from dataclasses import replace

from rule_engine.diagram_layout import Node, _overlay_labelled
from rule_engine.geometry import (
    Box,
    DiagramGeometry,
    EdgeGeom,
    check_marker_on_container_caption,
    marker_anchors,
    resolve_marker_collisions,
    rule_violations,
)
from rule_engine.linter import (
    RULE_MARKER_ON_CONTAINER_CAPTION,
    RULE_SEVERITIES,
    Severity,
    _check_marker_on_container_caption,
)


# --- 1. standby suffix is not doubled -------------------------------------

def _standby(label: str) -> str:
    n = Node(id="r", label=label, x=0, y=0, overlay="standby")
    return _overlay_labelled([n])[0].label


def test_standby_suffix_added_once_to_a_bare_label():
    assert _standby("RDS") == "RDS-standby"


def test_standby_suffix_idempotent_on_hyphenated_label():
    assert _standby("RDS-standby") == "RDS-standby"


def test_standby_suffix_not_doubled_on_spaced_word():
    # The 10 feedback case: author wrote "RDS standby"; must not double it.
    assert _standby("RDS standby") == "RDS standby"
    assert _standby("RDS Standby") == "RDS Standby"


def test_standby_suffix_added_when_standby_is_not_the_last_word():
    assert _standby("Aurora standby replica") == "Aurora standby replica-standby"


# --- 4. markers off the container caption ---------------------------------

def _geo_with_caption_marker(ax: int, bx: int) -> DiagramGeometry:
    """A straight edge (y=140) between a node at ``ax`` and one at ``bx``; its
    marker midpoint lands at ``(ax+78+bx)/2``. The container's left-aligned
    caption occupies the strip just inside its top edge (x 100..310, y 120..150
    for the caption below)."""
    g = DiagramGeometry(
        nodes={
            "a": Box("a", ax, 101, 78, 78),
            "b": Box("b", bx, 101, 78, 78),
        },
        containers={
            "vpc": Box("vpc", 100, 120, 900, 400),
        },
        edges=[
            EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="3"),
        ],
    )
    g.container_labels["vpc"] = "private-app 1a (10.0.1.0/24)"
    # A left-aligned dashed boundary style (so the caption band is left-aligned).
    g.container_styles["vpc"] = (
        "rounded=0;dashed=1;fillColor=none;align=left;verticalAlign=top;"
        "spacingLeft=10;fontSize=12"
    )
    return g


def test_marker_on_container_caption_is_flagged():
    # midpoint x = (20+78 + 452)/2 = 275, inside the left-aligned caption band
    # (x 100..310, y 120..150).
    g = _geo_with_caption_marker(20, 452)
    ax, ay = marker_anchors(g)["e"]
    assert ay == 140.0 and 100 <= ax <= 310
    findings = check_marker_on_container_caption(g)
    assert ("e", "vpc") in findings


def test_marker_clear_of_caption_is_not_flagged():
    g = _geo_with_caption_marker(20, 452)
    # Move the edge's y below the caption band entirely.
    g = replace(
        g,
        nodes={"a": Box("a", 20, 361, 78, 78), "b": Box("b", 452, 361, 78, 78)},
    )
    assert marker_anchors(g)["e"][1] == 400.0
    assert check_marker_on_container_caption(g) == []


def test_marker_on_container_caption_not_in_solver_oracle():
    # Lint-only, like every other marker-* rule.
    g = _geo_with_caption_marker(20, 452)
    rv = rule_violations(g)
    assert all("marker-on-container-caption" not in str(r) for r in rv)


def test_marker_on_container_caption_base_severity_is_warning():
    # Base severity WARNING; escalated to ERROR on network/component/flow by the
    # check wrapper (same as marker-on-container-border).
    assert RULE_SEVERITIES[RULE_MARKER_ON_CONTAINER_CAPTION] is Severity.WARNING


def test_resolve_marker_collisions_slides_a_marker_off_a_caption():
    g = _geo_with_caption_marker(20, 452)
    # Precondition: the marker is on the caption.
    assert check_marker_on_container_caption(g) != []
    moved = resolve_marker_collisions(g)
    assert "e" in moved, "the marker should be slid off the caption"
    g2 = replace(
        g,
        edges=[replace(e, label_pos=moved[e.id]) if e.id in moved else e
               for e in g.edges],
    )
    assert check_marker_on_container_caption(g2) == []


# --- 2. external-band leaf caption strip ----------------------------------

def _leaf_spec(caption: str):
    from rule_engine.layout import DiagramSpec
    from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec
    containers = (
        ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
        ContainerSpec(id="ext", kind="external_cloud", region="", parent=None, label_key="external_cloud"),
    )
    nodes = (
        NodeSpec(id="svc", role="compute_instance", lane="data", region="a", slot=0, container="vpc-a"),
        NodeSpec(id="peer", role="saas", lane="actors", region="", slot=0, container="ext", external=True),
    )
    edges = (EdgeSpec(id="e0", source="peer", target="svc", marker="1"),)
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. call"),
        title="aws t — 0 / eu | 2026-10-28 | v1", order="manual",
        container_captions=(("ext", caption),),
    )


# NOTE (item 16, external-band leaf caption strip): NOT shipped. Reducing the
# external_cloud / peer_account leaf's top strip from the 60px corridor to the
# caption band moved SEP 09 geometry enough to route an edge through the
# ``batch`` icon (a new ``edge-routing: knee-through-batch`` blocker). Per the
# plan ("If this moves goldens, report not done") it is reported not done in the
# CHANGELOG Notes; the single-member workaround (``sub=1``) remains.


# --- 3. layout_warnings reflect the FINAL geometry ------------------------

def test_degraded_finish_revalidates_on_final_geometry():
    """A layout() result the linter passes clean carries no layout_warnings —
    a finding a rejected candidate had but the final geometry does not is not
    reported (the 12 container-padding noise)."""
    from rule_engine.layout import layout
    p = layout(_leaf_spec("Atlas peer (10.0.9.0/24)"), strict=False)
    # The returned diagram is clean, so warnings must be empty and not degraded.
    assert p.layout_warnings == ()
    assert p.degraded is False

"""Tests for ITEM C (1.11.0, audit E-08): robust + blocking long-edge marker.

Three pieces of behaviour are pinned:

1. **Near-source long-edge default anchor** — :func:`geometry.marker_anchor`
   anchors an UNPINNED marker on a LONG route near its source (a fixed
   arc-length offset, :data:`geometry.LONG_EDGE_MARKER_OFFSET`) instead of at
   the geometric midpoint, which on a long run can land in dead space / on a
   border / on a caption. A SHORT route, or a route whose ``label_pos`` is
   explicitly pinned (including ``0.0``), keeps the exact midpoint behaviour, so
   no short-edge / pinned golden shifts.

2. **Extended de-collision (phases 2–3, NOT a new phase 4)** —
   :func:`geometry.resolve_marker_collisions` now seeds from the near-source
   anchor and its existing phases 2 (off node icon / caption / foreign edge) and
   3 (off container border) pull an overlapping badge into open space.

3. **Blocking severity** — ``marker-on-container-border`` and
   ``marker-label-collision`` are **ERROR** on a network / component / flow
   diagram (the kinds a reviewer reads a numbered flow off), **WARNING** on a
   landscape inventory / other classes.
"""

from __future__ import annotations

from rule_engine.geometry import (
    Box,
    DiagramGeometry,
    EdgeGeom,
    LONG_EDGE_MARKER_LEN,
    LONG_EDGE_MARKER_OFFSET,
    check_marker_on_container_border,
    marker_anchor,
    marker_anchors,
    resolve_marker_collisions,
)
from rule_engine.linter import (
    RULE_MARKER_LABEL_COLLISION,
    RULE_MARKER_ON_CONTAINER_BORDER,
    Artifact,
    _is_network_component_or_flow,
    lint,
)


# --------------------------------------------------------------------------- #
# 1. Near-source long-edge default anchor
# --------------------------------------------------------------------------- #


def test_long_unpinned_marker_anchors_near_source():
    """A straight horizontal run from x=100 to x=900 (length 800 > the long
    threshold) anchors its unpinned marker at the near-source offset, not the
    x=500 midpoint."""
    poly = [(100.0, 400.0), (900.0, 400.0)]
    assert 800.0 > LONG_EDGE_MARKER_LEN
    anchor = marker_anchor(poly, None)
    assert anchor is not None
    # near-source: x = 100 + LONG_EDGE_MARKER_OFFSET, well short of the midpoint.
    assert anchor[0] == 100.0 + LONG_EDGE_MARKER_OFFSET
    assert anchor[0] < 500.0  # not the midpoint


def test_short_unpinned_marker_keeps_the_midpoint():
    """A short run (length below the long threshold) is unchanged — midpoint."""
    poly = [(100.0, 400.0), (300.0, 400.0)]  # length 200, short
    assert 200.0 <= LONG_EDGE_MARKER_LEN
    assert marker_anchor(poly, None) == (200.0, 400.0)  # midpoint, as before


def test_pinned_long_marker_is_unchanged():
    """An explicitly pinned ``label_pos`` (even ``0.0``) keeps the exact pinned
    point, so no pinned-marker golden shifts."""
    poly = [(100.0, 400.0), (900.0, 400.0)]  # long
    assert marker_anchor(poly, 0.0) == (500.0, 400.0)  # pinned midpoint, unchanged
    # a pin toward the target end is honoured verbatim too.
    assert marker_anchor(poly, 1.0) == (900.0, 400.0)


def test_near_source_cap_does_not_pass_the_midpoint():
    """On a route only a little over the long threshold the offset is capped at
    half the length, so the marker never passes the midpoint."""
    # length = LONG_EDGE_MARKER_LEN + 20, so 0.5*len < LONG_EDGE_MARKER_OFFSET.
    length = LONG_EDGE_MARKER_LEN + 20.0
    poly = [(0.0, 0.0), (length, 0.0)]
    anchor = marker_anchor(poly, None)
    assert anchor is not None
    assert anchor[0] == min(0.5 * length, LONG_EDGE_MARKER_OFFSET)
    assert anchor[0] <= 0.5 * length  # never past the midpoint


# --------------------------------------------------------------------------- #
# 2. Extended de-collision (phases 2–3) seeds from the near-source anchor
# --------------------------------------------------------------------------- #


def _long_edge_marker_on_border() -> DiagramGeometry:
    """A long straight right→left edge whose NEAR-SOURCE anchor lands on a
    container's right border, so the extended de-collision must slide it off.

    Source ``a`` right face at x=478; target ``b`` left face far to the right so
    the run is long. The near-source anchor sits at x = 478 + OFFSET; place the
    container's right edge there so the marker rides it."""
    src_right = 478.0
    anchor_x = src_right + LONG_EDGE_MARKER_OFFSET
    tgt_left = src_right + 3.0 * LONG_EDGE_MARKER_OFFSET  # ensures a long run
    return DiagramGeometry(
        nodes={
            "a": Box("a", 400, 361, 78, 78),
            "b": Box("b", tgt_left, 361, 78, 78),
        },
        containers={
            "boundary-account": Box("boundary-account", 60, 120, anchor_x - 60, 560),
        },
        edges=[
            EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="9"),
        ],
    )


def test_near_source_seed_lands_on_the_border_before_decollision():
    """Sanity: with no de-collision the unpinned marker's rendered anchor rides
    the container border (the defect the extended pass must clear)."""
    geo = _long_edge_marker_on_border()
    assert check_marker_on_container_border(geo) == [("e", "boundary-account.right")]


def test_marker_decollision_moves_colliding_badge():
    """The extended phases 2–3 (seeded from the near-source anchor) slide the
    border-riding badge off the frame; applying the nudge clears the finding."""
    geo = _long_edge_marker_on_border()
    moved = resolve_marker_collisions(geo)
    assert "e" in moved, "the border-riding marker must be nudged"
    for e in geo.edges:
        if e.id in moved:
            e.label_pos = moved[e.id]
    assert check_marker_on_container_border(geo) == []


def test_decollision_is_idempotent_on_a_clear_long_marker():
    """A long unpinned marker already clear of every border / caption is left at
    its near-source default — ``resolve_marker_collisions`` returns ``{}``."""
    length = 3.0 * LONG_EDGE_MARKER_OFFSET
    geo = DiagramGeometry(
        nodes={
            "a": Box("a", 100, 361, 78, 78),
            "b": Box("b", 100 + length, 361, 78, 78),
        },
        containers={},  # no borders to ride
        edges=[
            EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="7"),
        ],
    )
    assert resolve_marker_collisions(geo) == {}


# --------------------------------------------------------------------------- #
# 3. Blocking severity by diagram class
# --------------------------------------------------------------------------- #


def _geo_marker_on_border() -> DiagramGeometry:
    """A short straight run whose pinned midpoint anchor rides a container
    border — used to drive the lint severity assertions directly (the anchor is
    deterministic and does not depend on the de-collision pass)."""
    return DiagramGeometry(
        nodes={"a": Box("a", 400, 361, 78, 78), "b": Box("b", 722, 361, 78, 78)},
        containers={"boundary-account": Box("boundary-account", 60, 120, 540, 560)},
        edges=[EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                        exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="9")],
    )


def test_marker_on_border_lands_at_midpoint():
    """The short-run fixture's marker rides the border at its midpoint x=600."""
    geo = _geo_marker_on_border()
    assert marker_anchors(geo)["e"][0] == 600.0
    assert check_marker_on_container_border(geo) == [("e", "boundary-account.right")]


def _severity_of(result, rule) -> str | None:
    for f in result["findings"]:
        if f["rule"] == rule:
            return f["severity"]
    return None


def test_marker_on_border_is_error_on_a_network_diagram():
    art = Artifact(
        kind="diagram", node_names=["a", "b"],
        diagram_type="network", geometry=_geo_marker_on_border(),
    )
    assert _is_network_component_or_flow(art)
    result = lint(art)
    assert _severity_of(result, RULE_MARKER_ON_CONTAINER_BORDER) == "ERROR"
    assert not result["eligible_for_publication"]


def test_marker_on_border_is_error_on_a_component_diagram():
    art = Artifact(
        kind="diagram", node_names=["a", "b"],
        diagram_type="component", geometry=_geo_marker_on_border(),
    )
    assert _is_network_component_or_flow(art)
    assert _severity_of(lint(art), RULE_MARKER_ON_CONTAINER_BORDER) == "ERROR"


def test_marker_on_border_is_error_on_a_flow_diagram():
    art = Artifact(
        kind="diagram", node_names=["a", "b"],
        diagram_class="flow", geometry=_geo_marker_on_border(),
    )
    assert _is_network_component_or_flow(art)
    assert _severity_of(lint(art), RULE_MARKER_ON_CONTAINER_BORDER) == "ERROR"


def test_marker_on_border_is_warning_on_a_landscape():
    art = Artifact(
        kind="diagram", node_names=["a", "b"],
        diagram_class="landscape", summary_of="01-x-summary",
        geometry=_geo_marker_on_border(),
    )
    assert not _is_network_component_or_flow(art)
    result = lint(art)
    assert _severity_of(result, RULE_MARKER_ON_CONTAINER_BORDER) == "WARNING"


def _geo_marker_on_caption() -> DiagramGeometry:
    """A marker whose anchor falls inside a node's caption rectangle (the
    ``marker-label-collision`` defect), used for the severity-by-class check."""
    # straight run a→b (right face x=478, left face x=1000); midpoint at
    # x=739,y=400. Node c's icon sits at x=700,y=322 so its bottom is y=400 and
    # its caption band (below the icon, icon-width) spans x 700..778, y 400..~430
    # — the midpoint falls inside it, overprinting the "alerts" caption.
    return DiagramGeometry(
        nodes={
            "a": Box("a", 400, 361, 78, 78),
            "b": Box("b", 1000, 361, 78, 78),
            "c": Box("c", 700, 322, 78, 78),
        },
        edges=[EdgeGeom(id="e", source="a", target="b", orthogonal=True,
                        exit=(1.0, 0.5), entry=(0.0, 0.5), points=[], label="4",
                        label_pos=0.0)],
        node_labels={"c": "alerts"},
    )


def test_marker_label_collision_is_error_on_flow_warning_on_landscape():
    geo = _geo_marker_on_caption()
    flow = Artifact(kind="diagram", node_names=["a", "b", "c"],
                    diagram_class="flow", geometry=geo)
    land = Artifact(kind="diagram", node_names=["a", "b", "c"],
                    diagram_class="landscape", summary_of="01-x-summary",
                    geometry=_geo_marker_on_caption())
    assert _severity_of(lint(flow), RULE_MARKER_LABEL_COLLISION) == "ERROR"
    assert _severity_of(lint(land), RULE_MARKER_LABEL_COLLISION) == "WARNING"

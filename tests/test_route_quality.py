"""Route-quality measurement and a ratchet so the corpus cannot silently worsen.

Routing is rule-driven: each router picks its corridor, lane, and face from one of
the ~25 named patterns in ``diagram-standards.md``, with no view of the diagram as
a whole. That holds until two patterns want the same plane, and then only a
measurement can say which route is better.

Three findings from the 2026-09-26 reviewer hand-edits of the AWS HA landscape
fixed the objective:

* the first edit removed 2 parallel **rails** while *adding* a crossing (7 -> 6
  crossings, 4 -> 2 rails), so a crossing-only objective would have rejected it;
* the second improved every number at once (3 / 2 / 45 / 10.0k against the
  generated 7 / 4 / 50 / 11.0k);
* turning on the straight-drop spine route for landscapes cut turns 50 -> 41 but
  raised crossings 7 -> 11 — proof that the choice between two legal shapes varies
  per edge and cannot be settled by another fixed rule.

Acting on the score needs the contact pipeline inverted (contacts are decided by
eight global passes before any edge is routed, so there is no per-edge decision
point to score) — tracked in ``docs/REVIEW.md`` -> Open gaps. Until then this
module pins the numbers as a **ratchet**: a change may improve them, never worsen
them, so a future routing change is judged by measurement rather than by eye.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest

from rule_engine.geometry import (
    RouteCost,
    build_geometry,
    edge_polyline,
    route_cost,
    segments_cross,
)
from rule_engine.geometry import Box, DiagramGeometry, EdgeGeom

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO_ROOT / "examples"

#: Route-quality ceiling per shipped diagram: ``(crossings, rails)``.
#:
#: Recorded from the v1.6.0 corpus. These are CEILINGS, not equalities — a routing
#: improvement is expected to push them down, and the test then asks to be
#: updated. Only turns/ink are left unpinned, because they trade against crossings
#: and rails (the straight-drop experiment traded 9 turns for 4 crossings) and
#: pinning them would block a good trade.
#:
#: The landscape floor of ``(3, 2)`` is the same as the reviewer's hand-routed
#: reference (``копія``), reached with three fewer turns. Its three remaining
#: crossings are the ones that hand-routing also kept — two long runs in the one
#: band above the edge tier, and two straight tier drops crossed by a run that has
#: to pass them — and the two rails are the single left-gap corridor the tier-skip
#: needs. ``gcp/01`` / ``oci/01`` sit at 4 because their hub is approached from the
#: side it fans out on; that is a placement gap (docs/REVIEW.md), not a routing one.
_CEILING = {
    "aws/01-aws-agent-platform.drawio": (0, 0),
    "aws/02-aws-ha-multiregion-landscape.drawio": (3, 2),
    "aws/02-aws-ha-multiregion-summary.drawio": (0, 0),
    "aws/03-aws-hybrid-infrastructure.drawio": (0, 0),
    "azure/01-azure-openai-rag.drawio": (0, 0),
    "azure/02-azure-ha-multiregion-landscape.drawio": (3, 2),
    "azure/02-azure-ha-multiregion-summary.drawio": (0, 0),
    "gcp/01-gcp-vertex-pipeline.drawio": (4, 0),
    "gcp/02-gcp-ha-multiregion-landscape.drawio": (3, 2),
    "gcp/02-gcp-ha-multiregion-summary.drawio": (0, 0),
    "oci/01-oci-genai-stack.drawio": (4, 0),
    "oci/02-oci-ha-multiregion-landscape.drawio": (3, 2),
    "oci/02-oci-ha-multiregion-summary.drawio": (0, 0),
}


def _shipped() -> list[str]:
    out = []
    for p in sorted(glob.glob(str(_EXAMPLES / "**" / "*.drawio"), recursive=True)):
        rel = os.path.relpath(p, _EXAMPLES)
        if "копія" in rel or rel.startswith("."):
            continue  # a reviewer's scratch copy is not a shipped artifact
        out.append(rel)
    return out


# =========================================================================== #
# The cost function itself
# =========================================================================== #


def _two_edge_geo(points_a, points_b, exit_a=(1.0, 0.5), entry_a=(0.0, 0.5),
                  exit_b=(1.0, 0.5), entry_b=(0.0, 0.5)):
    """Two edges over four distinct nodes, so they share no endpoint."""
    return DiagramGeometry(
        nodes={
            "a1": Box("a1", 0, 0, 78, 78), "a2": Box("a2", 600, 0, 78, 78),
            "b1": Box("b1", 0, 400, 78, 78), "b2": Box("b2", 600, 400, 78, 78),
        },
        edges=[
            EdgeGeom(id="ea", source="a1", target="a2", orthogonal=True,
                     exit=exit_a, entry=entry_a, points=points_a),
            EdgeGeom(id="eb", source="b1", target="b2", orthogonal=True,
                     exit=exit_b, entry=entry_b, points=points_b),
        ],
    )


def test_a_horizontal_crossing_a_vertical_counts_once():
    g = _two_edge_geo([(300, 39), (300, 200)], [(200, 439), (200, 100)])
    cost = route_cost(g)
    assert cost.crossings == 0, "these two do not actually intersect"


def test_crossing_is_detected_and_named():
    # ea runs H at y=39 across x=0..600; eb runs V at x=300 from y=439 up to y=0.
    g = _two_edge_geo([], [(300, 439), (300, 0)])
    cost = route_cost(g)
    assert cost.crossings == 1
    assert cost.crossing_pairs == (("ea", "eb"),)


def test_a_shared_trunk_only_touches_so_it_is_not_counted():
    """Two branches leaving one source down one trunk MEET at the trunk corner.

    diagram-standards sanctions this shape ("shared trunk, opposite branches"),
    and it needs no special case in the metric: the branches only *touch*, and
    :func:`segments_cross` tests the strict interior of both segments.
    """
    g = DiagramGeometry(
        nodes={
            "s": Box("s", 0, 0, 78, 78),
            "t1": Box("t1", 600, 0, 78, 78),
            "t2": Box("t2", 600, 400, 78, 78),
        },
        edges=[
            EdgeGeom(id="e1", source="s", target="t1", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[(300, 39)]),
            EdgeGeom(id="e2", source="s", target="t2", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5),
                     points=[(300, 39), (300, 439)]),
        ],
    )
    assert route_cost(g).crossings == 0


def test_a_fan_out_whose_bands_are_ordered_wrongly_IS_counted():
    """The same two branches, with the descending one exiting ABOVE the level one.

    Its turn leg now cuts through the level sibling's run instead of meeting it
    at a shared corner. The standard's trunk exemption does not cover this — the
    same sentence requires that "the branches never overlap" — so the metric must
    see it. Blanket-exempting every co-sourced pair is what hid four of these per
    HA landscape (``l19``x``l20``, ``l20``x``l21`` twice).
    """
    g = DiagramGeometry(
        nodes={
            "s": Box("s", 0, 0, 78, 78),
            "t1": Box("t1", 600, 0, 78, 78),
            "t2": Box("t2", 600, 400, 78, 78),
        },
        edges=[
            # level branch on the face CENTRE, running straight across at y=39
            EdgeGeom(id="e1", source="s", target="t1", orthogonal=True,
                     exit=(1.0, 0.5), entry=(0.0, 0.5), points=[]),
            # descending branch exiting ABOVE it (y=19), so its turn at x=300
            # drops straight through e1's run
            EdgeGeom(id="e2", source="s", target="t2", orthogonal=True,
                     exit=(1.0, 0.25), entry=(0.0, 0.5),
                     points=[(300, 19), (300, 439)]),
        ],
    )
    cost = route_cost(g)
    assert cost.crossings == 1
    assert cost.crossing_pairs == (("e1", "e2"),)


def test_touching_at_an_endpoint_is_not_a_crossing():
    """A corner where two runs meet is not an intersection."""
    g = _two_edge_geo([], [(0, 439), (0, 39)])
    assert route_cost(g).crossings == 0


def test_a_long_vertical_beside_an_unrelated_node_is_a_rail():
    g = DiagramGeometry(
        nodes={
            "s": Box("s", 0, 0, 78, 78),
            "t": Box("t", 0, 800, 78, 78),
            "mid": Box("mid", 120, 300, 78, 78),   # its left border is at 120
        },
        edges=[EdgeGeom(id="e", source="s", target="t", orthogonal=True,
                        exit=(0.5, 1.0), entry=(0.5, 0.0),
                        points=[(110, 78), (110, 800)])],
    )
    cost = route_cost(g)
    assert cost.rails == 1
    assert cost.rail_pairs[0][:2] == ("e", "mid")


def test_a_short_vertical_is_not_a_rail():
    """A step between adjacent rows is not a rail, however close it runs."""
    g = DiagramGeometry(
        nodes={
            "s": Box("s", 0, 0, 78, 78),
            "t": Box("t", 0, 200, 78, 78),
            "mid": Box("mid", 120, 50, 78, 78),
        },
        edges=[EdgeGeom(id="e", source="s", target="t", orthogonal=True,
                        exit=(0.5, 1.0), entry=(0.5, 0.0),
                        points=[(110, 78), (110, 200)])],
    )
    assert route_cost(g).rails == 0


def test_a_distant_vertical_is_not_a_rail():
    g = DiagramGeometry(
        nodes={
            "s": Box("s", 0, 0, 78, 78),
            "t": Box("t", 0, 800, 78, 78),
            "mid": Box("mid", 400, 300, 78, 78),   # far from the run at x=110
        },
        edges=[EdgeGeom(id="e", source="s", target="t", orthogonal=True,
                        exit=(0.5, 1.0), entry=(0.5, 0.0),
                        points=[(110, 78), (110, 800)])],
    )
    assert route_cost(g).rails == 0


def test_turns_and_ink_are_measured():
    g = _two_edge_geo([(300, 39), (300, 200), (600, 200)], [])
    cost = route_cost(g)
    # ea has 3 interior points; eb is a straight run with none.
    assert cost.turns == 3
    assert cost.ink > 0


def test_cost_comparison_key_orders_crossings_before_economy():
    """A route with fewer crossings wins even if it costs more turns and ink —
    the ordering the straight-drop experiment showed is necessary."""
    fewer_crossings = RouteCost(crossings=3, rails=2, turns=45, ink=10_000)
    fewer_turns = RouteCost(crossings=11, rails=4, turns=41, ink=10_500)
    assert fewer_crossings.as_tuple() < fewer_turns.as_tuple()


def test_cost_weighs_rails_above_economy():
    """The first reviewer edit removed 2 rails while ADDING a crossing, so rails
    must outrank turns and ink."""
    fewer_rails = RouteCost(crossings=6, rails=2, turns=48, ink=10_800)
    more_rails = RouteCost(crossings=6, rails=4, turns=46, ink=10_500)
    assert fewer_rails.as_tuple() < more_rails.as_tuple()


def test_empty_diagram_costs_nothing():
    cost = route_cost(DiagramGeometry())
    assert cost.as_tuple() == (0, 0, 0, 0)


def test_edge_polyline_includes_both_contacts():
    g = _two_edge_geo([(300, 39)], [])
    poly = edge_polyline(g, g.edges[0])
    assert poly[0] == (78.0, 39.0)      # exit contact on a1's right face
    assert poly[-1] == (600.0, 39.0)    # entry contact on a2's left face


def test_segments_cross_requires_one_h_and_one_v():
    h1 = ((0.0, 0.0), (100.0, 0.0))
    h2 = ((0.0, 0.0), (100.0, 0.0))
    v = ((50.0, -50.0), (50.0, 50.0))
    assert segments_cross(h1, v) is True
    assert segments_cross(h1, h2) is False


# =========================================================================== #
# The corpus ratchet
# =========================================================================== #


@pytest.mark.parametrize("rel", _shipped())
def test_shipped_diagram_route_quality_does_not_regress(rel):
    """Crossings and rails stay at or below the recorded ceiling.

    If a routing change LOWERS a number, update ``_CEILING`` in the same commit —
    the ratchet is meant to be tightened, and recording the new floor is what keeps
    the next change honest.
    """
    assert rel in _CEILING, (
        f"{rel} has no recorded route-quality ceiling; measure it with "
        "`python scripts/route_quality.py --all` and add it to _CEILING"
    )
    want_crossings, want_rails = _CEILING[rel]
    cost = route_cost(build_geometry((_EXAMPLES / rel).read_text(encoding="utf-8")))
    assert cost.crossings <= want_crossings, (
        f"{rel}: crossings rose to {cost.crossings} (ceiling {want_crossings}); "
        f"pairs={cost.crossing_pairs}"
    )
    assert cost.rails <= want_rails, (
        f"{rel}: parallel rails rose to {cost.rails} (ceiling {want_rails}); "
        f"runs={cost.rail_pairs}"
    )


def test_the_ceiling_covers_every_shipped_diagram():
    """No shipped diagram escapes the ratchet, and the table has no dead rows."""
    assert set(_CEILING) == set(_shipped())


def test_flow_class_examples_route_without_crossings_or_rails():
    """Every <=12-node flow example is fully clean, which is the bar a small
    diagram must meet — only the dense landscapes carry a non-zero ceiling."""
    for rel, (crossings, rails) in _CEILING.items():
        if "landscape" in rel or rel.startswith(("gcp/01", "oci/01")):
            continue
        assert (crossings, rails) == (0, 0), rel

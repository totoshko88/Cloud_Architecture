"""Theme 36 (1.10.11): per-spec ``col_step`` / ``row_step`` / ``sub_step``
grid-spacing override.

The lane/slot grid steps were fixed module constants (``COL_STEP=220``,
``ROW_STEP=160``, ``SUB_STEP=80``); neither ``layout()`` nor ``DiagramSpec``
exposed them, so the densest fans could not "spread wider" without hand-placed
geometry. This suite proves the new coordinate-free lever:

* ``resolve_spacing`` validates a provided value (whole ``GRID`` multiple AND
  ``>=`` the canonical floor) and defaults every unset field to its constant;
* a widened ``col_step`` / ``row_step`` scales **placement** (node pitch) AND
  **routing** (the corridors between nodes) in lockstep — the desync guard;
* the override never *increases* the crossing count on a dense fan and the
  widened build lints clean;
* an unset override is byte-identical to the pre-Theme-36 engine (the shipped
  corpus proof lives in ``regen_examples.py --check``; here we assert the
  ``None`` default path resolves to the canonical constants and lays out
  identically to an all-``None`` spec).
"""

from __future__ import annotations

import pytest

from rule_engine import geometry as g
from rule_engine.layout import base as lb
from rule_engine.layout import layout
from rule_engine.layout_engine import (
    ContainerSpec,
    DiagramSpec,
    EdgeSpec,
    NodeSpec,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _oracle_geometry(placed):
    from rule_engine.drawio_model import parse_drawio
    from rule_engine.geometry import build_geometry
    from rule_engine.layout.repair import _serialize_candidate

    return build_geometry(parse_drawio(_serialize_candidate(placed), path="<t>.drawio")[0])


def _fan_spec(**spacing) -> DiagramSpec:
    """A dense left→right fan: one source feeding four targets on four slots of
    one lane, plus a tail. The four same-lane targets step out along the
    SECONDARY axis (``col_step`` on a left→right diagram is the slot step is x?
    no — on left→right the primary axis is x and the secondary/slot axis is y),
    so widening the step visibly spreads them. ``**spacing`` is forwarded to the
    ``DiagramSpec`` spacing fields (``col_step`` / ``row_step`` / ``sub_step``).
    """
    nodes = [
        NodeSpec(id="src", role="lb", lane="edge", region="", slot=0),
    ]
    # four workers on four slots of the workers lane — a fan the source feeds
    for i in range(4):
        nodes.append(
            NodeSpec(id=f"w{i}", role="serverless_fn", lane="workers", region="", slot=i)
        )
    nodes.append(NodeSpec(id="sink", role="object_store", lane="data", region="", slot=0))
    edges = [EdgeSpec(id=f"f{i}", source="src", target=f"w{i}", marker=str(i + 1)) for i in range(4)]
    edges += [EdgeSpec(id=f"d{i}", source=f"w{i}", target="sink", marker=str(i + 5)) for i in range(4)]
    return DiagramSpec(
        diagram_id="fan",
        diagram_name="fan",
        axis="left-right",
        nodes=tuple(nodes),
        edges=tuple(edges),
        containers=(
            ContainerSpec(id="acct", kind="account", region="", parent=None,
                          label_key="account"),
        ),
        flow_lines=("Flow",),
        title="fan | 2025-01-15 | v1",
        **spacing,
    )


# --------------------------------------------------------------------------- #
# resolve_spacing validator
# --------------------------------------------------------------------------- #


def test_resolve_spacing_none_when_unset():
    # The common path: no field set → None, so every accessor keeps its constant.
    assert lb.resolve_spacing(_fan_spec()) is None


def test_resolve_spacing_fills_unset_with_constants():
    # A set col_step; unset row/sub take their canonical floor.
    assert lb.resolve_spacing(_fan_spec(col_step=440)) == (440, lb.ROW_STEP, lb.SUB_STEP)
    assert lb.resolve_spacing(_fan_spec(row_step=320)) == (lb.COL_STEP, 320, lb.SUB_STEP)
    assert lb.resolve_spacing(_fan_spec(col_step=440, row_step=320, sub_step=160)) == (440, 320, 160)


@pytest.mark.parametrize("field,value", [
    ("col_step", 225),   # not a whole GRID (10) multiple
    ("row_step", 165),   # not a whole GRID multiple
    ("sub_step", 85),    # not a whole GRID multiple
])
def test_resolve_spacing_rejects_non_grid_multiple(field, value):
    with pytest.raises(ValueError, match="whole GRID"):
        lb.resolve_spacing(_fan_spec(**{field: value}))


@pytest.mark.parametrize("field,value,floor", [
    ("col_step", 210, 220),  # below the COL_STEP floor
    ("row_step", 150, 160),  # below the ROW_STEP floor
    ("sub_step", 70, 80),    # below the SUB_STEP floor
])
def test_resolve_spacing_rejects_below_floor(field, value, floor):
    with pytest.raises(ValueError, match="floor"):
        lb.resolve_spacing(_fan_spec(**{field: value}))


def test_resolve_spacing_rejects_non_int():
    with pytest.raises(ValueError, match="int"):
        lb.resolve_spacing(_fan_spec(col_step=440.0))
    with pytest.raises(ValueError, match="int"):
        lb.resolve_spacing(_fan_spec(col_step=True))


def test_accessors_default_to_canonical_outside_a_scope():
    # No active layout() scope → accessors read the module constants.
    assert (lb.col_step(), lb.row_step(), lb.sub_step()) == (lb.COL_STEP, lb.ROW_STEP, lb.SUB_STEP)
    assert lb.region_gap() == 2 * lb.COL_STEP
    assert lb.region_step() == 3 * lb.COL_STEP


def test_spacing_scope_binds_and_resets():
    assert lb._SPACING.get() is None
    with lb._spacing_scope((440, 320, 160)):
        assert (lb.col_step(), lb.row_step(), lb.sub_step()) == (440, 320, 160)
        assert lb.region_gap() == 2 * 440
        # nested scope shields and restores
        with lb._spacing_scope(None):
            assert (lb.col_step(), lb.row_step()) == (lb.COL_STEP, lb.ROW_STEP)
        assert lb.col_step() == 440
    assert lb._SPACING.get() is None


# --------------------------------------------------------------------------- #
# The lever: placement + routing scale in lockstep
# --------------------------------------------------------------------------- #


def _slot_pitch_y(placed) -> int:
    """Secondary-axis (y, on a left→right diagram) pitch between adjacent fan
    workers w0..w3 — the distance a one-slot step produces."""
    ys = [placed.nodes[f"w{i}"].y for i in range(4)]
    diffs = {b - a for a, b in zip(ys, ys[1:])}
    assert len(diffs) == 1, f"fan workers are not evenly pitched: {ys}"
    return diffs.pop()


def test_col_step_default_build_matches_explicit_none():
    # col_step=None (unset) ≡ not passing it at all: byte-identical placement.
    a = layout(_fan_spec())
    b = layout(_fan_spec(col_step=None, row_step=None, sub_step=None))
    assert {k: (v.x, v.y) for k, v in a.nodes.items()} == {k: (v.x, v.y) for k, v in b.nodes.items()}


def test_row_step_widens_the_slot_pitch():
    # On a left→right diagram the slot (secondary) axis is y, stepped by ROW_STEP.
    base = layout(_fan_spec())
    wide = layout(_fan_spec(row_step=320))  # 2× ROW_STEP (160)
    base_pitch = _slot_pitch_y(base)
    wide_pitch = _slot_pitch_y(wide)
    assert base_pitch > 0
    # The pitch scales with the step: doubling row_step roughly doubles the gap.
    assert wide_pitch > base_pitch
    assert wide_pitch == base_pitch * 2


def test_routing_scales_with_placement_no_desync():
    # The desync guard: if placement widens but routing does not, corridors
    # misjudge adjacency silently. Prove the routed waypoints track the wider
    # grid — the overall routed-edge extent grows with the step, and the widened
    # build stays a well-formed (non-degraded) candidate the router could route.
    base = layout(_fan_spec(row_step=320))
    wide = layout(_fan_spec(row_step=320, col_step=440))  # widen the primary (x) axis too

    def _x_extent(placed):
        xs = [b.x for b in placed.nodes.values()] + [b.x + b.w for b in placed.nodes.values()]
        return max(xs) - min(xs)

    # Widening col_step (the x/primary step on left→right) spreads the chain.
    assert _x_extent(wide) > _x_extent(base)
    # Both builds are structurally valid (the router did not desync into an
    # over-connected / unroutable candidate).
    assert not base.degraded
    assert not wide.degraded
    # Routing tracked the wider grid: the routed waypoints span a WIDER x-range
    # in the widened build (a desync would leave corridors at the old pitch while
    # the nodes moved, so the routed extent would NOT grow with the nodes).
    def _route_x_span(placed):
        xs = [p[0] for e in placed.edges for p in e.points]
        return (max(xs) - min(xs)) if xs else 0

    assert _route_x_span(wide) > _route_x_span(base)


def test_wider_grid_never_increases_crossings_on_a_dense_fan():
    # The owner's recurring ask: spread the services wider so the lines don't
    # overlap. A wider grid must NEVER make the crossing picture worse — the base
    # placement is always a candidate, so the widened build can only match or beat
    # it. (This fan's 4→1 sink convergence is topologically crossing-heavy, so the
    # count does not reach zero; the invariant under test is non-regression, which
    # is the engine's actual guarantee for the lever.)
    base = layout(_fan_spec())
    wide = layout(_fan_spec(col_step=440, row_step=320))

    base_cross = g.route_cost(_oracle_geometry(base)).crossings
    wide_cross = g.route_cost(_oracle_geometry(wide)).crossings
    assert wide_cross <= base_cross
    assert not wide.degraded


def test_grid_alignment_preserved_under_a_widened_step():
    # A widened (whole-GRID-multiple) step keeps every node on the canonical grid.
    wide = layout(_fan_spec(col_step=440, row_step=320, sub_step=160))
    for nid, b in wide.nodes.items():
        assert b.x % g.GRID == 0, (nid, b.x)
        assert b.y % g.GRID == 0, (nid, b.y)


def _reversed_interleave_spec(**spacing) -> DiagramSpec:
    """A spacing-SENSITIVE fan: a source feeds four workers, and each worker
    feeds a data node whose slot is the REVERSE of the worker's — so the
    worker→data legs run through a shared corridor and cross when the lanes sit
    too close. Widening the grid gives those legs room, which is exactly the
    owner's "spread the services wider so the lines don't overlap" ask.
    """
    n = 4
    nodes = [NodeSpec(id="src", role="lb", lane="edge", region="", slot=0)]
    nodes += [NodeSpec(id=f"w{i}", role="serverless_fn", lane="workers", region="", slot=i) for i in range(n)]
    nodes += [NodeSpec(id=f"d{i}", role="object_store", lane="data", region="", slot=n - 1 - i) for i in range(n)]
    edges = [EdgeSpec(id=f"f{i}", source="src", target=f"w{i}", marker=str(i + 1)) for i in range(n)]
    edges += [EdgeSpec(id=f"g{i}", source=f"w{i}", target=f"d{i}", marker=str(i + 5)) for i in range(n)]
    return DiagramSpec(
        diagram_id="rev", diagram_name="rev", axis="left-right",
        nodes=tuple(nodes), edges=tuple(edges),
        containers=(ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),),
        flow_lines=("Flow",), title="rev | 2025-01-15 | v1", **spacing,
    )


def test_widening_the_grid_reduces_crossings_on_a_tight_fan():
    # Step 4 of the Theme 36 brief, in miniature: on a spacing-sensitive fan the
    # default grid forces the worker→data legs to overlap; a wider col_step gives
    # them room and the crossing count drops. This proves the lever reaches the
    # ROUTER (not just placement) — a desync would leave the corridors at the old
    # pitch and the count unchanged.
    base = layout(_reversed_interleave_spec())
    wide = layout(_reversed_interleave_spec(col_step=440))
    base_cross = g.route_cost(_oracle_geometry(base)).crossings
    wide_cross = g.route_cost(_oracle_geometry(wide)).crossings
    assert wide_cross < base_cross, (base_cross, wide_cross)


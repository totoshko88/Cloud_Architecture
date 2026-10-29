"""L3 (1.13.0): lift-over shape for the up-climbing branch of a single-hub fan-out.

The up-climbing branch of a single-hub N-way fan-out (its target sits a row or
more ABOVE the source, while the siblings descend) climbs amongst the siblings'
nested turn columns and cuts their left-approach legs — the crossing the
finishing crossing-repair pass cannot clear (ENGINE-TODO L3). The fix is a
scored ``LIFT_OVER`` route variant: the climber rises in the pre-fan gap column
(left of every sibling turn column) and runs across a lane ABOVE the whole fan
into the target. The solver commits it only when the whole-diagram ``route_cost``
scores strictly fewer crossings, with the rule-based route always rank 0, so
every shipped golden with no up-climbing fan-out branch stays byte-identical.

Pinned here on synthetic fixtures only (no product-diagram edits):

* **router shape** — ``route_fan_out_row(..., lift_over=True)`` rises in the
  pre-fan column and runs on a lane above every node in the x-span, where the
  default below-row lane climbs through the fan;
* **variant generation** — ``variants.generate`` offers ``lift-over`` for an
  up-climbing ``fan-out-row`` edge and NOT for a descending sibling, with the
  rule-based variant always rank 0;
* **solver** — a synthetic fan-out whose up-climb crossing the lift-over removes
  loses a crossing through the real ``layout()`` scored path, and a fan-out with
  no up-climb is byte-identical with the variant present.
"""
from __future__ import annotations

from rule_engine import crossing_repair as cr
from rule_engine import geometry as geo
from rule_engine.drawio_model import parse_drawio
from rule_engine.geometry import Box
from rule_engine.layout import layout, routers, variants
from rule_engine.layout.corridors import CorridorAllocator
from rule_engine.layout.model import (
    ContainerSpec,
    DiagramSpec,
    EdgeSpec,
    NodeSpec,
)
from rule_engine.layout.repair import _serialize_candidate


# --------------------------------------------------------------------------- #
# Router shape: the lift-over rises in the pre-fan column, above the whole fan.
# --------------------------------------------------------------------------- #
def _fan_boxes():
    """A hub (left) fanning to a column of stores (right). ``rds`` sits ABOVE
    the hub row (the climber); the rest descend."""
    return {
        "hub": Box("hub", 200, 520, 78, 78),
        "rds": Box("rds", 900, 180, 78, 78),
        "s3": Box("s3", 900, 340, 78, 78),
        "ddb": Box("ddb", 900, 500, 78, 78),
        "sqs": Box("sqs", 900, 660, 78, 78),
        "es": Box("es", 900, 820, 78, 78),
    }


def test_lift_over_rises_in_a_pre_fan_column_above_the_whole_fan():
    placed = _fan_boxes()
    obstacles = list(placed.values())
    e = EdgeSpec(id="e_rds", source="hub", target="rds", marker="1")
    normal = routers.route_fan_out_row(
        e, (1.0, 0.5), (0.0, 0.5), CorridorAllocator(), obstacles, None, None, False)
    lift = routers.route_fan_out_row(
        e, (1.0, 0.5), (0.0, 0.5), CorridorAllocator(), obstacles, None, None, True)
    # The normal fan-out runs a below-row lane and climbs the target column from
    # below; the lift-over runs a lane ABOVE every node (topmost node top = 180).
    top = min(b.y for b in obstacles)
    normal_lane = min(y for _x, y in normal)
    lift_lane = min(y for _x, y in lift)
    assert lift_lane < top, (lift_lane, top)          # above the whole fan
    assert lift_lane < normal_lane                     # higher than the default lane
    # The rise column sits left of every sibling's turn column (left of the
    # target column), i.e. the step-out gap right of the source.
    rise_x = lift[0][0]
    assert rise_x < placed["rds"].x                    # left of the target column
    assert rise_x < placed["hub"].right + 2 * routers.col_step()


# --------------------------------------------------------------------------- #
# Variant generation: offered for the climber, not for a descending sibling.
# --------------------------------------------------------------------------- #
def test_up_climb_fan_out_gets_a_lift_over_variant_rule_based_still_rank_0():
    placed = _fan_boxes()
    e = EdgeSpec(id="e_rds", source="hub", target="rds", marker="1")
    assert routers.classify_edge(e, placed) == "fan-out-row"
    seed = {"e_rds": ((1.0, 0.5), (0.0, 0.5))}
    vs = variants.generate(e, placed, {}, "fan-out-row", seed)
    assert vs[0].plan is variants.RoutePlan.RULE_BASED      # rule-based rank 0
    assert any(v.plan is variants.RoutePlan.LIFT_OVER for v in vs)
    lift = next(v for v in vs if v.plan is variants.RoutePlan.LIFT_OVER)
    assert lift.exit[0] >= 1.0                              # right-face exit
    assert lift.entry[0] <= 0.0 or lift.entry[1] <= 0.0     # left/top entry (legal)


def test_descending_sibling_gets_no_lift_over_variant():
    placed = _fan_boxes()
    e = EdgeSpec(id="e_es", source="hub", target="es", marker="5")   # target below
    vs = variants.generate(e, placed, {}, routers.classify_edge(e, placed),
                           {"e_es": ((1.0, 0.5), (0.0, 0.5))})
    assert not any(v.plan is variants.RoutePlan.LIFT_OVER for v in vs)


def test_lift_over_variant_is_contract_legal_by_construction():
    """Its exit stays right and its entry stays left/top, so it can add no
    ``edge-direction`` finding regardless of selection."""
    placed = _fan_boxes()
    e = EdgeSpec(id="e_rds", source="hub", target="rds", marker="1")
    vs = variants.generate(e, placed, {}, "fan-out-row",
                           {"e_rds": ((1.0, 0.5), (0.0, 0.5))})
    for v in vs:
        assert variants._exit_is_contract_legal(v.exit), v.id
        assert variants._entry_is_contract_legal(v.entry), v.id


# --------------------------------------------------------------------------- #
# Solver end-to-end: the lift-over removes an up-climb crossing; inert without one.
# --------------------------------------------------------------------------- #
def _fan_spec(stores):
    """Hub in the ``workers`` lane; ``stores`` = ``(id, slot, role)`` in the
    ``data`` lane (a column to the right). A store whose slot is above the hub's
    row climbs; the rest descend."""
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="region", kind="region", region="a", parent="acct", label_key="region"),
    )
    nodes = [NodeSpec(id="hub", role="serverless_fn", lane="workers", region="a",
                      slot=2, container="region", scope="regional")]
    for sid, slot, role in stores:
        nodes.append(NodeSpec(id=sid, role=role, lane="data", region="a",
                              slot=slot, container="region", scope="regional"))
    edges = tuple(EdgeSpec(id=f"e_{s}", source="hub", target=s, marker=str(i + 1))
                  for i, (s, _slot, _role) in enumerate(stores))
    return DiagramSpec(diagram_id="l3", diagram_name="l3", axis="left-right",
                       nodes=tuple(nodes), edges=edges, containers=containers,
                       flow_lines=("Flow",), title="l3")


def _crossings(spec) -> int:
    placed = layout(spec, strict=False)
    g = geo.build_geometry(parse_drawio(_serialize_candidate(placed),
                                        path="l3.drawio")[0])
    return sum(n for *_ab, n in cr.crossing_pairs(g))


def _without_lift_over(fn):
    orig = variants._lift_over_variant
    variants._lift_over_variant = lambda *a, **k: []
    try:
        return fn()
    finally:
        variants._lift_over_variant = orig


def test_lift_over_removes_an_up_climb_crossing_through_the_solver():
    # Two climbers (slots 0,1 above the hub row) + two descenders (slots 3,4):
    # the up-climb branch crosses the siblings, and the lift-over removes one.
    spec = _fan_spec([("rds", 0, "dynamodb"), ("s3", 1, "object_store"),
                      ("ddb", 3, "dynamodb"), ("sqs", 4, "message_queue")])
    with_lift = _crossings(spec)
    without_lift = _without_lift_over(lambda: _crossings(spec))
    assert with_lift < without_lift, (with_lift, without_lift)


def test_fan_out_with_no_up_climb_is_byte_identical_with_the_variant():
    # All targets at/below the hub row: no up-climb, so the lift-over variant is
    # never offered and the committed geometry is identical with or without it.
    spec = _fan_spec([("rds", 2, "dynamodb"), ("s3", 3, "object_store"),
                      ("ddb", 4, "dynamodb")])
    placed_with = layout(spec, strict=False)
    with_text = _serialize_candidate(placed_with)
    without_text = _without_lift_over(
        lambda: _serialize_candidate(layout(spec, strict=False)))
    assert with_text == without_text

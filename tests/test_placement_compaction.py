"""Account-only compaction (hotfix 1.10.7, M4).

A spec with an ``account`` container and no ``region`` container (a serverless
account, everything ``rule-engine-draw`` emits) used to place lanes at their
absolute index and nodes at their declared slot, so an empty lane left an empty
row band in the account box and a slot gap an empty column. Such a spec now
compacts: occupied lanes on consecutive steps, each lane's slots on consecutive
columns. External lanes (actors / on-premises) stay clear of the account border.
A spec that declares a region container keeps absolute placement.
"""

from __future__ import annotations

from rule_engine.diagram_layout import COL_STEP, ROW_STEP
from rule_engine.geometry import LABEL_BAND, _SPILL_REACH
from rule_engine.layout import layout
from rule_engine.layout.base import LANE_INDEX
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec
from rule_engine.layout.place import place_nodes

ACCOUNT = ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account")
REGION = ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region")

# router / (async empty) / workers {0, 3} / data
_NODES = (
    ("sched", "router", 0),
    ("fn_a", "workers", 0),
    ("fn_b", "workers", 3),
    ("bucket", "data", 0),
)
_EDGES = (("sched", "fn_a"), ("fn_a", "fn_b"), ("fn_b", "bucket"))


def _spec(*, region: str = "", containers=(ACCOUNT,), extra_nodes=(), extra_edges=()):
    nodes = tuple(
        NodeSpec(id=i, role="fn", lane=lane, region=region, slot=slot)
        for i, lane, slot in _NODES + tuple(extra_nodes)
    )
    edges = tuple(
        EdgeSpec(id=f"e{k}", source=a, target=b, marker=str(k))
        for k, (a, b) in enumerate(_EDGES + tuple(extra_edges), 1)
    )
    flow = ("Flow",) + tuple(f"{k}. step" for k in range(1, len(edges) + 1))
    return DiagramSpec("compact", "compact", "north-south", nodes, edges,
                       tuple(containers), flow, "compact")


def test_account_only_compacts_lanes_and_slots():
    placed = place_nodes(_spec())
    ys = sorted({b.y for b in placed.values()})
    # router, workers, data on consecutive rows — the empty async lane is gone.
    assert [y - ys[0] for y in ys] == [0, ROW_STEP, 2 * ROW_STEP]
    # workers slots {0, 3} sit one column apart.
    assert placed["fn_b"].x - placed["fn_a"].x == COL_STEP
    assert placed["fn_b"].y == placed["fn_a"].y


def test_account_only_left_right_compacts_too():
    spec = _spec()
    spec = DiagramSpec(spec.diagram_id, spec.diagram_name, "left-right", spec.nodes,
                       spec.edges, spec.containers, spec.flow_lines, spec.title)
    placed = place_nodes(spec)
    xs = sorted({b.x for b in placed.values()})
    assert [x - xs[0] for x in xs] == [0, COL_STEP, 2 * COL_STEP]
    assert placed["fn_b"].y - placed["fn_a"].y == ROW_STEP


def test_region_spec_keeps_absolute_placement():
    """With a region container the pre-1.10.7 formula holds: lane index → row,
    declared slot → column."""
    placed = place_nodes(_spec(region="a", containers=(ACCOUNT, REGION)))
    origin = placed["sched"]
    for nid, lane, slot in _NODES:
        b = placed[nid]
        assert b.y - origin.y == (LANE_INDEX[lane] - LANE_INDEX["router"]) * ROW_STEP, nid
        assert b.x - origin.x == slot * COL_STEP, nid


def test_external_rows_stay_clear_of_the_account_border():
    """An actors row above and an on-premises row below an account-only
    North–South diagram keep their footprint outside the account box and more
    than the spill reach away from its border (no straddle, no spill)."""
    spec = _spec(
        extra_nodes=(("user", "actors", 0), ("dc", "on-premises", 0)),
        extra_edges=(("user", "sched"), ("bucket", "dc")),
    )
    placed = layout(spec, strict=True)
    acct = placed.containers["account"]
    user = placed.nodes["user"].footprint(LABEL_BAND)
    dc = placed.nodes["dc"].footprint(LABEL_BAND)
    assert acct.y - user.bottom > _SPILL_REACH
    assert dc.y - acct.bottom > _SPILL_REACH
    assert placed.layout_warnings == ()

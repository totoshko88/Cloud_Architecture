"""1.10.12 WS4 — automatic flow-aware ordering (defect class C6).

Covers the default-on ordering (``layout()`` reorders unpinned slots / re-lanes
a left→right sink / flips ``vpc_side`` only when the finished diagram is
better), the two opt-outs (``order="manual"``, ``NodeSpec.pinned`` and a
non-zero ``sub``), the decision-3 guard (never more back-edges or crossings
than the declared order) and the ``rule-engine-advise`` entry point.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from rule_engine.advise_cli import main as advise_main, spec_from_mapping, spec_to_mapping
from rule_engine.layout import layout
from rule_engine.layout.base import SpecError
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec
from rule_engine.layout.ordering import (
    back_edges_of,
    is_pinned,
    measure_finished,
    search_candidates,
    _positions,
)
from rule_engine.layout.place import place_nodes

ACCOUNT = (ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),)


def _flow_spec(**over) -> DiagramSpec:
    """The SEP 02 shape: SQS declared in the async lane, left of the Lambda that
    feeds it — a back-edge no slot order can fix in a left→right flow."""
    nodes = (
        NodeSpec(id="client", role="client", lane="actors", region="", slot=0),
        NodeSpec(id="api", role="api_gateway", lane="edge", region="", slot=0),
        NodeSpec(id="sqs", role="message_queue", lane="async", region="", slot=0),
        NodeSpec(id="fn", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="llm", role="llm_platform", lane="platform", region="", slot=0),
        NodeSpec(id="s3", role="object_store", lane="data", region="", slot=0),
    )
    edges = (
        EdgeSpec(id="e1", source="client", target="api", marker="1"),
        EdgeSpec(id="e2", source="api", target="fn", marker="2"),
        EdgeSpec(id="e3", source="fn", target="sqs", marker="3", dashed=True),
        EdgeSpec(id="e4", source="fn", target="llm", marker="4"),
        EdgeSpec(id="e5", source="fn", target="s3", marker="5"),
    )
    spec = DiagramSpec(
        diagram_id="ws4-flow", diagram_name="ws4-flow", axis="left-right",
        nodes=nodes, edges=edges, containers=ACCOUNT,
        flow_lines=("Flow",) + tuple(f"{i}. step {i}" for i in range(1, 6)),
        title="aws ws4 — 000000000000 / eu-central-1 | 2026-10-20 | v1", compact=True,
    )
    return dataclasses.replace(spec, **over)


def _back(placed) -> int:
    return len(back_edges_of(placed.spec, placed.nodes))


# --------------------------------------------------------------------------- #
# Default on: the back-edge is removed, and the guard holds
# --------------------------------------------------------------------------- #

def test_auto_order_relanes_sink_behind_its_producer():
    placed = layout(_flow_spec())
    lanes = {n.id: n.lane for n in placed.spec.nodes}
    assert lanes["sqs"] == "platform"  # the first occupied lane after its producer
    assert _back(placed) == 0
    assert any(l.startswith("relane sqs") for l in placed.order_report)
    assert any("auto-order: applied" in l for l in placed.order_report)


def test_auto_order_never_worse_than_declared_order():
    spec = _flow_spec()
    auto = layout(spec)
    manual = layout(dataclasses.replace(spec, order="manual"))
    b_auto, x_auto = measure_finished(auto)[:2]
    b_man, x_man = measure_finished(manual)[:2]
    assert b_auto <= b_man and x_auto <= x_man
    assert (b_auto, x_auto) < (b_man, x_man)


# --------------------------------------------------------------------------- #
# Opt-outs: order: manual, and explicit pins
# --------------------------------------------------------------------------- #

def test_order_manual_opts_out_entirely():
    spec = _flow_spec(order="manual")
    placed = layout(spec)
    assert placed.spec.nodes == spec.nodes  # nothing reordered or re-laned
    assert placed.order_report == ()
    assert _back(placed) == 1


def test_pinned_node_keeps_its_lane_and_slot():
    spec = _flow_spec()
    nodes = tuple(dataclasses.replace(n, pinned=True) if n.id == "sqs" else n for n in spec.nodes)
    placed = layout(dataclasses.replace(spec, nodes=nodes))
    sqs = next(n for n in placed.spec.nodes if n.id == "sqs")
    assert (sqs.lane, sqs.slot) == ("async", 0)


def test_sub_nudge_counts_as_a_pin():
    assert is_pinned(NodeSpec(id="a", role="r", lane="data", region="", slot=0, sub=1))
    assert is_pinned(NodeSpec(id="a", role="r", lane="data", region="", slot=0, pinned=True))
    assert not is_pinned(NodeSpec(id="a", role="r", lane="data", region="", slot=0))


def _row_spec(pin_dns: bool = False) -> DiagramSpec:
    """A North–South external row with Route 53 declared right of the CloudFront
    it resolves to (the SEP 09 ``e3`` back-edge)."""
    nodes = (
        NodeSpec(id="cdn", role="cdn", lane="actors", region="", slot=0),
        NodeSpec(id="dns", role="dns", lane="actors", region="", slot=1, pinned=pin_dns),
        NodeSpec(id="app", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="log", role="object_store", lane="workers", region="", slot=1),
    )
    edges = (
        EdgeSpec(id="e1", source="dns", target="cdn", marker="1"),
        EdgeSpec(id="e2", source="cdn", target="app", marker="2"),
        EdgeSpec(id="e3", source="dns", target="log", marker="3", dashed=True),
    )
    return DiagramSpec(
        diagram_id="ws4-row", diagram_name="ws4-row", axis="north-south",
        nodes=nodes, edges=edges, containers=ACCOUNT,
        flow_lines=("Flow", "1. resolve", "2. serve", "3. log"),
        title="aws ws4 — 000000000000 / eu-central-1 | 2026-10-20 | v1",
    )


def test_slot_reorder_removes_a_back_edge_in_a_row():
    placed = layout(_row_spec())
    slots = {n.id: n.slot for n in placed.spec.nodes}
    assert slots["dns"] < slots["cdn"]
    assert _back(placed) == 0


def test_explicit_slot_pin_is_respected():
    spec = _row_spec(pin_dns=True)
    placed = layout(spec)
    assert placed.spec.nodes == spec.nodes
    assert search_candidates(spec)[1:] == []  # no unpinned order to try


def test_over_budget_declared_order_is_kept(monkeypatch):
    """Past the finishing-measurement budget the declared order is kept."""
    from rule_engine.layout import ordering

    monkeypatch.setattr(ordering, "FINISH_BUDGET", -1)
    spec = _flow_spec()
    placed = layout(spec)
    assert placed.spec.nodes == spec.nodes
    assert any("skipped" in l and "budget" in l for l in placed.order_report)


# --------------------------------------------------------------------------- #
# vpc_side
# --------------------------------------------------------------------------- #

def _region_spec(vpc_side: str) -> DiagramSpec:
    containers = (
        ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
        ContainerSpec(id="region-a", kind="region", region="a", parent="account", label_key="region"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="region-a", label_key="vpc"),
    )
    nodes = (
        NodeSpec(id="users", role="client", lane="actors", region="", slot=0),
        NodeSpec(id="api", role="api_gateway", lane="router", region="a", slot=0, container="region-a"),
        NodeSpec(id="fn", role="serverless_fn", lane="workers", region="a", slot=0, container="region-a"),
        NodeSpec(id="db", role="managed_sql", lane="data", region="a", slot=0, container="vpc-a"),
    )
    edges = (
        EdgeSpec(id="e0", source="users", target="api", marker="1"),
        EdgeSpec(id="e1", source="api", target="fn", marker="2"),
        EdgeSpec(id="e2", source="api", target="db", marker="3"),
    )
    return DiagramSpec(
        diagram_id="ws4-vpc", diagram_name="ws4-vpc", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. call", "2. invoke", "3. persist"),
        title="aws ws4 — 000000000000 / eu-central-1 | 2026-10-20 | v1",
        vpc_side=vpc_side,
    )


def test_vpc_side_right_puts_the_network_block_after_its_feeder():
    left = place_nodes(_region_spec("left"))
    right = place_nodes(_region_spec("right"))
    assert left["db"].x < left["api"].x          # default: VPC left of the regional column
    assert right["db"].x > right["api"].x        # flipped: VPC right of its feeder
    assert right["api"].x == left["api"].x       # the regional block keeps its x
    assert place_nodes(_region_spec("auto")) == left


def test_vpc_side_auto_is_chosen_by_edge_direction():
    spec = _region_spec("auto")
    assert back_edges_of(spec, _positions(spec)) == ["e2"]
    ranked = search_candidates(spec)
    assert any(s.vpc_side == "right" for s, _k in ranked[1:])


@pytest.mark.parametrize("field,value", [("order", "sideways"), ("vpc_side", "up")])
def test_invalid_switch_values_raise(field, value):
    with pytest.raises(SpecError):
        place_nodes(dataclasses.replace(_flow_spec(), **{field: value}))


# --------------------------------------------------------------------------- #
# rule-engine-advise
# --------------------------------------------------------------------------- #

def test_spec_mapping_round_trip():
    spec = _flow_spec(node_labels=(("fn", "Lambda"),))
    assert spec_from_mapping(spec_to_mapping(spec)) == spec


def test_advise_reports_changes_and_reasons(tmp_path, capsys):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec_to_mapping(_flow_spec())), encoding="utf-8")
    assert advise_main([str(path), "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)[0]
    assert rec["diagram_id"] == "ws4-flow"
    assert any(l.startswith("relane sqs") for l in rec["report"])
    assert "why: removes back-edge(s) e3 (fn -> sqs)" in rec["report"]
    assert any("back-edges 1 -> 0" in l for l in rec["report"])


def test_advise_manual_spec_reports_opt_out(tmp_path, capsys):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec_to_mapping(_flow_spec(order="manual"))), encoding="utf-8")
    assert advise_main([str(path)]) == 0
    assert "skipped (order: manual)" in capsys.readouterr().out


def test_advise_bad_spec_exits_2(tmp_path, capsys):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"nodes": [{"bogus": 1}]}), encoding="utf-8")
    assert advise_main([str(path)]) == 2


def test_flow_forward_spec_skips_the_search():
    """Review B1: a declared order without back-edges is returned at once (only
    an order with FEWER back-edges is ever laid out), so ``layout()`` on a
    flow-forward spec costs what it did before WS4."""
    spec = _flow_spec(order="auto")
    fwd = dataclasses.replace(spec, edges=tuple(e for e in spec.edges if e.id != "e3"))
    assert back_edges_of(fwd, _positions(fwd)) == []
    assert search_candidates(fwd) == [(fwd, search_candidates(fwd)[0][1])]
    assert len(search_candidates(fwd)) == 1


def test_marker_on_own_caption_slides_clear():
    """Review M1 (SEP 08): a short drop under its source's caption printed its
    number on the service name; phase 2 of the marker slide now moves a marker
    off a node icon or caption too (and stays off when phase 2 is disabled)."""
    from rule_engine import geometry as g
    from rule_engine.drawio_model import parse_drawio

    style = ("edgeStyle=orthogonalEdgeStyle;exitX=0.5;exitY=1;exitPerimeter=0;"
             "entryX=0.5;entryY=0;")
    cells = "".join(
        f'<mxCell id="{n}" value="{n}" vertex="1" parent="1">'
        f'<mxGeometry x="0" y="{y}" width="80" height="80" as="geometry"/></mxCell>'
        for n, y in (("a", 0), ("b", 130))
    ) + (f'<mxCell id="e1" value="1" edge="1" parent="1" source="a" target="b" '
         f'style="{style}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    xml = ('<mxGraphModel gridSize="10"><root><mxCell id="0"/>'
           f'<mxCell id="1" parent="0"/>{cells}</root></mxGraphModel>')
    geo = g.build_geometry(parse_drawio(xml, path="m.drawio")[0])
    assert g.check_marker_label_collision(geo) == [("e1", "a")]
    moved = g.resolve_marker_collisions(geo)
    assert set(moved) == {"e1"}
    slid = dataclasses.replace(geo, edges=[dataclasses.replace(e, label_pos=moved[e.id])
                                           for e in geo.edges])
    assert g.check_marker_label_collision(slid) == []
    assert g.check_marker_icon_collision(slid) == []
    assert g.resolve_marker_collisions(geo, clearance=0.0) == {}

"""1.13.0 E-PCX: the pcx-id on a two-line peering node caption.

Wave-7 (G38) added :attr:`EdgeSpec.peering_label` — the short peer name a
materialized ``vpc_peering`` node carries. E-PCX additionally surfaces the raw
``pcx-…`` connection id on a SECOND caption line, because a ~21-char pcx-id on a
single line would trip ``node-label-length``. The additive triplet
``EdgeSpec.peering_id`` / ``DiagramSpec.peering_ids`` /
:func:`rule_engine.layout.peering.peering_id_for` mirrors the existing
``peering_label`` triplet exactly, so an edge with no ``peering_id`` contributes
no entry (single-line fallback, byte-identical).
"""

from __future__ import annotations

from rule_engine.layout import (
    DiagramSpec,
    materialize_peerings,
    peering_id_for,
    peering_label_for,
)
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec
from rule_engine.linter import Artifact, lint


def _spec(with_id: bool = True) -> DiagramSpec:
    nodes = (
        NodeSpec(id="lambda", role="serverless_fn", lane="workers", region="a",
                 slot=0, scope="network", container="vpc-a"),
        NodeSpec(id="peer", role="compute_instance", lane="on-premises",
                 region="", slot=0, container="peer-ext"),
    )
    containers = (
        ContainerSpec(id="acct", kind="account", region="", parent=None,
                      label_key="account"),
        ContainerSpec(id="vpc-a", kind="vpc", region="a", parent="acct",
                      label_key="vpc"),
        ContainerSpec(id="peer-ext", kind="external_cloud", region="",
                      parent=None, label_key="peer"),
    )
    edges = (
        EdgeSpec(
            id="p1", source="lambda", target="peer", marker="peering",
            peering=True, peering_label="Atlas peering",
            peering_id="pcx-0e257b23d337fda0b" if with_id else None,
        ),
    )
    return DiagramSpec(
        diagram_id="t", diagram_name="t", axis="north-south",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. VPC peering"),
        title="aws t — 1 / r | 2026-10-23 | v1",
        peering_as_node=True,
    )


def test_peering_id_surfaced_on_materialized_spec():
    placed = materialize_peerings(_spec(with_id=True))
    assert peering_label_for(placed, "p1-pcx") == "Atlas peering"
    assert peering_id_for(placed, "p1-pcx") == "pcx-0e257b23d337fda0b"
    # And the two-line caption a renderer builds is under node-label-length.
    label = f"{peering_label_for(placed, 'p1-pcx')}\n{peering_id_for(placed, 'p1-pcx')}"
    assert label == "Atlas peering\npcx-0e257b23d337fda0b"


def test_two_line_caption_does_not_trip_node_label_length():
    placed = materialize_peerings(_spec(with_id=True))
    name = peering_label_for(placed, "p1-pcx")
    pid = peering_id_for(placed, "p1-pcx")
    label = f"{name}\n{pid}"
    # Feed the two-line label to the linter as a service-node name. decoded:
    # "Atlas peering pcx-0e257b23d337fda0b" = 3 words, 35 chars -> under both caps.
    art = Artifact(
        kind="diagram",
        node_names=[label],
        title_cell="aws x — a / b | 2026-10-23 | v1",
        diagram_type="network",
    )
    hits = [f for f in lint(art)["findings"] if f["rule"] == "node-label-length"]
    assert hits == [], hits


def test_no_peering_id_is_single_line_fallback():
    placed = materialize_peerings(_spec(with_id=False))
    # No id -> no peering_ids entry -> single-line (peering_id_for is None).
    assert peering_id_for(placed, "p1-pcx") is None
    assert placed.peering_ids == ()
    # The label still carries (G38 unaffected).
    assert peering_label_for(placed, "p1-pcx") == "Atlas peering"

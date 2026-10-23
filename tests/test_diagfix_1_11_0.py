"""1.11.0 diagram-fix engine changes ENG-R1 / R2 / R3 (SEP 02 feedback).

R1 — co-directional same-face exits spread across distinct thirds (not corners):
     two edges that spill onto the same (bottom) face leave from distinct bands
     (0.25/0.5/0.75), never the 0.0/1.0 corners the corner-exit fallback used.
R2 — an edge that crosses a node's caption masks that caption with an opaque
     ``labelBackgroundColor`` regardless of the node's host boundary, so the
     line passes BEHIND the legible service name.
R3 — a decorative flow-group box renders at the very back (before every edge),
     so an edge turning across it is drawn OVER the box border.
"""

from __future__ import annotations

import re

from rule_engine import caption_routing as cr
from rule_engine import diagram_layout as dl
from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec


# --------------------------------------------------------------------------- #
# R1 — co-directional exits leave distinct thirds, not corners.
# --------------------------------------------------------------------------- #

def _sep_summary_spec() -> DiagramSpec:
    """The SEP-02 shape: a Lambda hub that fans out five edges, two of which
    spill onto the bottom face (the s3 / atlas pair the owner flagged)."""
    nodes = (
        NodeSpec(id="client", role="client", lane="actors", region="", slot=0),
        NodeSpec(id="rest-apis", role="api_gateway", lane="edge", region="", slot=0),
        NodeSpec(id="socket-api", role="api_gateway", lane="edge", region="", slot=1),
        NodeSpec(id="lambda-core", role="serverless_fn", lane="workers", region="", slot=0),
        NodeSpec(id="sqs", role="message_queue", lane="async", region="", slot=0),
        NodeSpec(id="batch", role="serverless_fn", lane="workers", region="", slot=1),
        NodeSpec(id="bedrock", role="llm_platform", lane="platform", region="", slot=0),
        NodeSpec(id="s3", role="object_store", lane="data", region="", slot=0),
        NodeSpec(id="atlas", role="managed_sql", lane="on-premises", region="", slot=0),
    )
    edges = (
        EdgeSpec(id="e1", source="client", target="rest-apis", marker="1"),
        EdgeSpec(id="e2", source="client", target="socket-api", marker="2", dashed=True),
        EdgeSpec(id="e3", source="rest-apis", target="lambda-core", marker="3"),
        EdgeSpec(id="e4", source="socket-api", target="lambda-core", marker="4"),
        EdgeSpec(id="e5", source="lambda-core", target="sqs", marker="5", dashed=True),
        EdgeSpec(id="e6", source="lambda-core", target="batch", marker="6"),
        EdgeSpec(id="e7", source="lambda-core", target="bedrock", marker="7"),
        EdgeSpec(id="e8", source="lambda-core", target="s3", marker="8"),
        EdgeSpec(id="e9", source="lambda-core", target="atlas", marker="9"),
    )
    containers = (ContainerSpec(id="account", kind="account", region="",
                                parent=None, label_key="account"),)
    return DiagramSpec(
        diagram_id="02", diagram_name="sep", axis="left-right",
        nodes=nodes, edges=edges, containers=containers,
        flow_lines=("Flow", "1. a"), title="t",
    )


def test_r1_codirectional_bottom_exits_leave_distinct_thirds():
    placed = layout(_sep_summary_spec())
    by_id = {e.spec.id: e for e in placed.edges}
    e8, e9 = by_id["e8"], by_id["e9"]
    # both spill onto the BOTTOM face (fy ~ 1.0)
    assert e8.exit[1] >= 1.0 - 1e-6 and e9.exit[1] >= 1.0 - 1e-6
    # their along-face band (exitX) is NEITHER a corner (0.0 / 1.0) ...
    for e in (e8, e9):
        assert 0.05 < e.exit[0] < 0.95, (e.id, e.exit)
    # ... NOR equal to each other (distinct thirds)
    assert abs(e8.exit[0] - e9.exit[0]) >= 0.2, (e8.exit, e9.exit)


def test_r1_corner_exit_fallback_is_off_by_default():
    assert cr._CORNER_EXIT_FALLBACK[0] is False


# --------------------------------------------------------------------------- #
# R2 — an edge that crosses a caption masks it, regardless of the host boundary.
# --------------------------------------------------------------------------- #

def _node(nid, x, y, label):
    return dl.Node(id=nid, label=label, x=x, y=y,
                   render=dl.builtin_icon("shape=mxgraph.aws4.resourceIcon;html=1"))


def test_r2_edge_crossing_caption_masks_it_with_opaque_background():
    # Two nodes on one row; an edge from a's bottom that drops THROUGH b's
    # caption band (b sits directly below a). b is on the root layer (no host
    # boundary), the case the old host/slot guard failed to mask.
    a = _node("a", 100, 100, "Alpha")
    b = _node("b", 100, 300, "Bravo service node")
    edge = dl.Edge(id="e1", source="a", target="b", marker="1",
                   exit=(0.5, 1.0), entry=(0.5, 0.0), points=())
    doc = dl._assemble_document(
        diagram_id="d", diagram_name="d", title="t", boundaries=[],
        nodes=[a, b], routed=[edge], flow_lines=["Flow"], legend_x=600,
        legend_y_flow=40, legend_y_legend=200, legend_w=None,
        legend_lines=["Legend"], legend_mode="stack", page_w=900, page_h=600,
    )
    # b's caption is crossed by the edge's vertical drop -> opaque mask set
    mb = re.search(r'id="b"[^>]*style="([^"]*)"', doc)
    assert mb is not None
    assert "labelBackgroundColor=#FFFFFF" in mb.group(1), mb.group(1)


def test_r2_only_crossed_captions_are_masked():
    # An edge a->b runs in a below-row corridor whose horizontal leg passes
    # through the caption band of an UNRELATED node c (c sits between them, one
    # row down). _edge_slots must mask c (the crossed UNRELATED caption, the R2
    # case the old host/slot guard missed) and never b (untouched).
    a = _node("a", 100, 100, "Alpha")
    b = _node("b", 700, 100, "Bravo")
    c = _node("c", 400, 100, "Charlie service node")   # caption band ~y 178..208
    # route a->b dipping down through c's caption band then back up
    edge = dl.Edge(id="e1", source="a", target="b", marker="1",
                   exit=(1.0, 0.5), entry=(0.0, 0.5),
                   points=((178, 195), (640, 195), (640, 139)))
    _slots, masked = dl._edge_slots([], [a, b, c], [edge])
    assert "c" in masked           # unrelated crossed caption is masked
    assert "b" not in masked       # untouched caption is not masked (byte-inert)


# --------------------------------------------------------------------------- #
# R3 — the decorative flow-group box renders at the very back (before edges).
# --------------------------------------------------------------------------- #

def test_r3_flow_group_box_emits_before_every_edge_and_boundary():
    a = _node("a", 120, 120, "Alpha")
    b = _node("b", 340, 120, "Bravo")
    bnd = dl.Boundary(id="acct", label="acct", x=40, y=40, w=500, h=300)
    edge = dl.Edge(id="e1", source="a", target="b", marker="1",
                   exit=(1.0, 0.5), entry=(0.0, 0.5), points=())
    doc = dl._assemble_document(
        diagram_id="d", diagram_name="d", title="t", boundaries=[bnd],
        nodes=[a, b], routed=[edge], flow_lines=["Flow"], legend_x=700,
        legend_y_flow=40, legend_y_legend=200, legend_w=None,
        legend_lines=["Legend"], legend_mode="stack", page_w=1000, page_h=500,
        flow_groups=(("Workers", ("a", "b")),),
    )
    i_group = doc.index('id="flowgroup-0"')
    i_edge = doc.index('id="e1"')
    i_bnd = doc.index('id="acct"')
    i_node = doc.index('id="a"')
    assert i_group < i_edge, "flow-group box must paint before every edge"
    assert i_group < i_bnd, "flow-group box must paint before every boundary"
    assert i_group < i_node, "flow-group box must paint before every node"


def test_r3_no_flow_groups_is_byte_inert():
    a = _node("a", 120, 120, "Alpha")
    kwargs = dict(
        diagram_id="d", diagram_name="d", title="t", boundaries=[],
        nodes=[a], routed=[], flow_lines=["Flow"], legend_x=400,
        legend_y_flow=40, legend_y_legend=200, legend_w=None,
        legend_lines=["Legend"], legend_mode="stack", page_w=700, page_h=400,
    )
    assert dl._assemble_document(**kwargs) == dl._assemble_document(**kwargs)
    assert "flowgroup-" not in dl._assemble_document(**kwargs)

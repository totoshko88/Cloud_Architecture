#!/usr/bin/env python3
"""Build the 07-flow-support-syndi triple (.drawio + .diagram.md) via the layout engine.

Coordinate-free: a hand-authored DiagramSpec (the SEP Syndi student-support loop)
is handed to layout() + build_diagram(), exactly like build_02_sep_summary.py.
No coordinates are placed by hand.

Flow (authoritative: live SEP account 870325637521, eu-central-1 + guide §7.2.6):
  Student asks for help in the Syndicate UI chat; Syndi (AI first-line support on
  the external Syndicate Server) answers, escalating to humans when needed.

  1. Student -> socket-api (WebSocket API GW) -> socket-handler (Lambda).
  2. socket-handler puts the request on se-support-request-queue (SQS). Verified:
     this queue has NO Lambda ESM in SEP -- it is consumed by Syndicate Server.
  3. Syndicate Server (Syndi) -- external EC2 OUTSIDE the account boundary --
     consumes it; Syndi is the AI first-line agent.
  4. Student attachments go to the S3 se-support-request-attachments bucket.
  5. Syndi may call DIAL AI (ai-proxy.lab.epam.com, external) for the model.
  6. Syndi's resolved response returns via se-support-response-queue (SQS) ->
     se-syndi-request-processor (Lambda; CONFIRMED event-source mapping).
  7. syndi-request-processor pushes the response to the student's active WebSocket
     connection via socket-api, closing the loop in the UI chat.

Externals (Syndicate Server/Syndi, DIAL AI) are drawn in the on-premises lane =>
OUTSIDE the account boundary, as neutral/generic boxes (no faked AWS icon).
The SQS<->Syndi edges cross the boundary (correct). The two-way request/response
is modelled as TWO single-ended edges, never one double-headed arrow.
"""
from __future__ import annotations

from pathlib import Path

from rule_engine.diagram_layout import (
    Boundary,
    CONTAINER_PAD,
    Edge,
    ICON_SIZE,
    Node,
    build_diagram,
    image_icon,
)
from rule_engine.icon_resolver import resolve_container, resolve_icon
from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

HERE = Path(__file__).resolve().parent
BASENAME = "07-flow-support-syndi"
TITLE = "aws SEP Syndi support — 870325637521 / eu-central-1 | 2026-10-17 | v5"

# Neutral external-system box (honest "external / non-AWS system" leaf; no faked
# AWS icon). Matches the 01-sep-context external boxes. RE gap: no sanctioned
# external_system role yet (RULE-ENGINE-FEEDBACK Theme 1).
EXTERNAL_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "fontSize=12;fontColor=#000000;verticalAlign=middle;align=center"
)

# --- node declarations (coordinate-free) ---------------------------------- #
# lane order: actors -> edge -> router -> async -> workers -> platform -> data -> on-premises
NODES = (
    NodeSpec(id="student", role="client", lane="actors", region="", slot=0),
    NodeSpec(id="socket-api", role="api_gateway", lane="edge", region="", slot=0),
    NodeSpec(id="socket-handler", role="serverless_fn", lane="router", region="", slot=0),
    NodeSpec(id="req-queue", role="message_queue", lane="async", region="", slot=0),
    # resp-queue + processor pulled onto FULL rows (sub removed) and attachments
    # dropped to a sub-row (sub=2): the reply trio e7 (syndi->resp-queue),
    # e8 (resp-queue->processor), e9 (processor->socket-api) was bunched in one
    # half-row corridor around the processor glyph, so markers 7/8/9 grazed the
    # processor label (edge-crosses-label[e7,processor]) and overprinted. Giving
    # resp-queue/processor their own rows spreads the reply legs vertically and
    # drops attachments out of e5's band -- clears edge-crosses-label AND the
    # marker overprint, and cuts crossings 5->4. (owner's lever: spread wider.)
    NodeSpec(id="resp-queue", role="message_queue", lane="async", region="", slot=1),
    NodeSpec(id="processor", role="serverless_fn", lane="workers", region="", slot=0),
    NodeSpec(id="attachments", role="object_store", lane="data", region="", slot=0, sub=2),
    # Externals: on-premises lane => OUTSIDE the account boundary.
    NodeSpec(id="syndi", role="external", lane="on-premises", region="", slot=0),
    NodeSpec(id="dial", role="external", lane="on-premises", region="", slot=1, sub=1),
)

# Two-way request/response as TWO single-ended edges (never a double head):
#   request leg  (SEP -> Syndicate):   req-queue -> syndi
#   response leg (Syndicate -> SEP):   syndi -> resp-queue
EDGES = (
    EdgeSpec(id="e1", source="student", target="socket-api", marker="1"),
    EdgeSpec(id="e2", source="socket-api", target="socket-handler", marker="2"),
    EdgeSpec(id="e3", source="socket-handler", target="req-queue", marker="3", dashed=True),
    EdgeSpec(id="e4", source="socket-handler", target="attachments", marker="4"),
    EdgeSpec(id="e5", source="req-queue", target="syndi", marker="5", dashed=True),
    EdgeSpec(id="e6", source="syndi", target="dial", marker="6"),
    EdgeSpec(id="e7", source="syndi", target="resp-queue", marker="7", dashed=True),
    # e8 (resp-queue -> processor, "8. processor consumes response (ESM)")
    # FOLDED into the Flow legend (Theme 36 edge-folding, owner request
    # 2026-10-16). e8 is a dashed secondary queue flow that hopped row 2 -> row 1
    # through the gap where e4 (y=240) and e7 (y=250) run their horizontals, so
    # its x=820 vertical crossed BOTH (e4xe8 @ 820,240 and e7xe8 @ 820,250) with
    # e8's own marker sitting on the crossing. Folding e8 removes both under-cap
    # crossings (edge-crossing-excess 3/8 -> under cap). Marker 8 keeps its
    # legend line, so the ESM-consume step is still named.
    # EdgeSpec(id="e8", source="resp-queue", target="processor", marker="8", dashed=True),
    # e9 (processor -> socket-api, "9. processor pushes reply to WebSocket")
    # FOLDED into the Flow legend (Theme 36 edge-folding, 1.10.11). This leftward
    # return-to-WebSocket back-edge raked across the whole left->right flow and
    # was the diagram's most crossing-toxic edge; folding it CLEARS
    # edge-crossing-excess entirely (4/9 -> under cap) and the diagram stays lint
    # [OK] with no new findings. Marker 9 keeps its legend line, so the step is
    # still named; socket-api still carries e1/e2 and processor still carries e8,
    # so no node is orphaned.
    # EdgeSpec(id="e9", source="processor", target="socket-api", marker="9"),
)

CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
)

# Short display labels (<=4 words / <=40 chars for service nodes).
LABELS = {
    "student": "Student",
    "socket-api": "socket-api (WebSocket)",
    "socket-handler": "socket-handler",
    "req-queue": "support-request-queue",
    "resp-queue": "support-response-queue",
    "processor": "syndi-request-processor",
    "attachments": "support-request-attachments",
    "syndi": "Syndicate Server / Syndi",
    "dial": "DIAL AI (external)",
}

FLOW_LINES = (
    "Flow",
    "1. Student support msg over WebSocket",
    "2. socket-api invokes socket-handler",
    "3. Handler enqueues on request-queue",
    "4. Attachments stored in S3 bucket",
    "5. Syndi consumes request (no SEP Lambda)",
    "6. Syndi calls DIAL AI; may escalate",
    "7. Syndi replies on response-queue",
    "8. processor consumes response (ESM)",
    "9. processor pushes reply to WebSocket",
)


def _renderer_for(node_id: str, role: str):
    # Owner feedback 2026-10-17 (e): the Syndicate Server is an EC2 host drawn as
    # its own node -> render the real EC2 service icon (compute_instance), not a
    # neutral box. It KEEPS NodeSpec role="external" so it stays in the
    # on-premises lane (outside the account boundary); only the glyph changes.
    # The EC2 icon names the real resource type, which is Icon-Fidelity clean.
    # (DIAL AI stays neutral — it is an external non-AWS AI proxy, NOT Bedrock.)
    if node_id == "syndi":
        style = resolve_icon("compute_instance", "aws")["style_string"]
        img = style.split("image=", 1)[1]
        return image_icon(img)
    if role == "external":
        return _raw_renderer(EXTERNAL_STYLE)
    style = resolve_icon(role, "aws")["style_string"]
    if style.startswith("image;") or "image=assets" in style:
        img = style.split("image=", 1)[1]
        return image_icon(img)
    return _raw_renderer(style)


def _raw_renderer(style_string: str):
    def render(node: Node, parent_id: str) -> str:
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style_string}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


def build() -> str:
    spec = DiagramSpec(
        diagram_id="aws-sep-syndi-support",
        diagram_name=BASENAME,
        axis="left-right",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=FLOW_LINES,
        title=TITLE,
        compact=True,
        node_labels=tuple(LABELS.items()),
        # Theme 36 (regen4): the spacing lever (DiagramSpec.row_step/col_step,
        # 1.10.11) was TESTED on this spec and REJECTED — it does not merely fail
        # to help, it BLOCKS publication. The baseline (edge-folding only) lints
        # [OK] with just dead-space + aspect-ratio WARNINGs; row_step=200 (the
        # only lever 07 can afford — col_step busts the 1600 flow budget) pushed
        # edge e7 (syndi->response-queue reply) into a knee that CUTS THROUGH THE
        # attachments S3 icon (edge-routing ERROR knee-through-attachments) and
        # dropped marker 4 onto the processor caption
        # (marker-label-collision[e4,processor]) — a RELOCATED overlap of exactly
        # the kind the owner complained about, now also an ERROR. The processor
        # fan is edge-count-driven, so grid-widening relocates rather than thins
        # it. The honest lever stays EDGE-FOLDING (e9 return-to-WebSocket folded
        # into the Flow legend), which is why no override is set. Verified:
        # regen4 before/after rasters recorded in RULE-ENGINE-FEEDBACK Theme 36
        # (wave 11).
    )
    placed = layout(spec)
    for w in placed.layout_warnings:
        print("layout WARNING:", w)

    renderers = {n.id: _renderer_for(n.id, n.role) for n in spec.nodes}

    nodes = [
        Node(
            id=n.id,
            label=LABELS[n.id],
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=renderers[n.id],
        )
        for n in spec.nodes
        if n.id in placed.nodes
    ]

    acct_style = resolve_container("boundary", "aws")["style_string"]
    boundaries = []
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        boundaries.append(
            Boundary(
                id=c.id,
                label="SEP — 870325637521 / eu-central-1",
                x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
                style=acct_style, kind="account",
            )
        )

    edges = [
        Edge(
            id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
            marker=pe.spec.marker, dashed=pe.spec.dashed,
            exit=pe.exit, entry=pe.entry,
            points=tuple((int(x), int(y)) for x, y in pe.points),
        )
        for pe in placed.edges
    ]

    page_margin = 2 * CONTAINER_PAD

    # Theme 43: aspect-driven Flow/Legend placement. 07 is a wide-and-short flow
    # (aspect ~3.3), so the helper returns Mode B — the two boxes as a right-
    # aligned horizontal row BELOW the body (kept below, not right-of, so the
    # flow raster stays under 1600px). A squarer diagram would get Mode A (right
    # stack). legend_w is sized to content (Theme 33, no narrow pin).
    from rule_engine.diagram_layout import legend_lines_for, theme43_legend_placement
    _legend_lines = legend_lines_for(boundaries)
    legend_w = placed.legend_w
    legend_x, legend_y_flow, legend_mode, page_w, page_h = theme43_legend_placement(
        nodes, boundaries, spec.flow_lines, _legend_lines, legend_w,
    )

    return build_diagram(
        diagram_id="aws-sep-syndi-support",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=spec.flow_lines,
        legend_x=legend_x,
        legend_y_flow=legend_y_flow,
        legend_w=legend_w,
        legend_mode=legend_mode,
        page_w=page_w,
        page_h=page_h,
    )


if __name__ == "__main__":
    text = build()
    out = HERE.parent / f"{BASENAME}.drawio"
    out.write_text(text, encoding="utf-8")
    print("wrote", out)

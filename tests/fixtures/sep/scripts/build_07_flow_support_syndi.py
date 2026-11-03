#!/usr/bin/env python3
"""Build the 07-flow-support-syndi triple (.drawio + .diagram.md) via the layout engine.

Coordinate-free: a hand-authored DiagramSpec (the SEP Syndi student-support loop)
is handed to layout() + build_diagram(), exactly like build_02_sep_summary.py.
No coordinates are placed by hand.

Flow (authoritative: live SEP account 870325637521, eu-central-1 + guide §7.2.6):
  Student asks for help in the Syndicate UI chat; Syndi (AI first-line support on
  the Syndicate Server) answers, escalating to humans when needed.

  1. Student -> socket-api (WebSocket API GW) -> socket-handler (Lambda).
  2. socket-handler puts the request on se-support-request-queue (SQS). Verified:
     this queue has NO Lambda ESM in SEP -- it is consumed by the Syndicate Server.
  3. Syndicate Server (Syndi) -- the EC2 control-plane host INSIDE the SEP account
     (instance-profile syndicate-server, vpc-05cd5663a70d3a65c) -- consumes it;
     Syndi is the AI first-line agent and the control plane for the sandbox orgs.
  4. Student attachments go to the S3 se-support-request-attachments bucket.
  5. Syndi may call DIAL AI (ai-proxy.lab.epam.com, external) for the model.
  6. Syndi's resolved response returns via se-support-response-queue (SQS) ->
     se-syndi-request-processor (Lambda; CONFIRMED event-source mapping).
  7. syndi-request-processor pushes the response to the student's active WebSocket
     connection via socket-api, closing the loop in the UI chat.

Task-4 (owner 2026-10-23): the Syndicate Server is the EC2 control plane INSIDE
the SEP account (verified in compute.json: instance-profile syndicate-server,
vpc-05cd5663a70d3a65c). It is therefore drawn as an account member with the real
EC2 (compute_instance) icon, NOT in the on-premises lane. The deprecated external
"Syndicate task manager" (the MVP-era Jenkins in another account) is GONE from the
diagram per Task-4. DIAL AI stays external (on-premises lane, OUTSIDE the account).
The SQS<->Syndi edges now cross the account boundary from the inside out, which is
correct and expected. The two-way request/response is modelled as TWO single-ended
edges, never one double-headed arrow.
"""
from __future__ import annotations

from pathlib import Path

from rule_engine.diagram_layout import (
    Boundary,
    CONTAINER_PAD,
    Edge,
    ICON_SIZE,
    Node,
    Skin,
    build_diagram,
    image_icon,
)
from rule_engine.icon_resolver import resolve_container, resolve_icon
from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

HERE = Path(__file__).resolve().parent
BASENAME = "07-flow-support-syndi"
TITLE = "aws SEP Syndi support — 870325637521 / eu-central-1 | 2026-10-28 | v13"

# 1.11.0 native skin (see FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

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
    # Routing-cleanup (2026-10-28, owner: "можна поміняти місцями аби 4 вийшло
    # згори. 3 зайва сходинка"). req-queue is restored to the TOP async row
    # (sub=0 -> y=120, same row as socket-handler): now that e4's target
    # (attachments) is the UPPER fan-out leg and e4 routes over the account top
    # band at y=100, req-queue no longer needs the sub=1 drop that the old
    # wave-4 clearance required (that drop existed only because e4 used to exit
    # LOW and skim the Async box top; with e4 now the upper leg that constraint
    # is gone). On the top row, e3 (socket-handler -> req-queue) becomes a SINGLE
    # STRAIGHT horizontal with NO waypoints — the owner's "3 зайва сходинка"
    # (extra jog) is removed — while e4 stays clearly above e3. Verified: e4
    # upper (y=100), e3 straight, lint [OK]. Coordinate-free; no hand coordinates.
    NodeSpec(id="req-queue", role="message_queue", lane="async", region="", slot=0, sub=0),
    # resp-queue + processor pulled onto FULL rows (sub removed) and attachments
    # dropped to a sub-row (sub=2): the reply trio e7 (syndi->resp-queue),
    # e8 (resp-queue->processor), e9 (processor->socket-api) was bunched in one
    # half-row corridor around the processor glyph, so markers 7/8/9 grazed the
    # processor label (edge-crosses-label[e7,processor]) and overprinted. Giving
    # resp-queue/processor their own rows spreads the reply legs vertically and
    # drops attachments out of e5's band -- clears edge-crosses-label AND the
    # marker overprint, and cuts crossings 5->4. (owner's lever: spread wider.)
    # resp-queue stays on its own async sub-row (sub=1 -> y=360) so it is well
    # clear of the top-row req-queue (y=120) and the reply trio spreads
    # vertically. processor stays on the workers lane (sub=1 -> y=200) so e5
    # (req-queue -> syndi) does not knee through the processor glyph. These sub
    # nudges keep the reply legs spread; with the 2026-10-28 routing-cleanup
    # (req-queue back to sub=0, attachments to sub=0) they also leave e3 straight
    # and e4 above e3. Coordinate-free, lint [OK] (only non-blocking dead-space).
    NodeSpec(id="resp-queue", role="message_queue", lane="async", region="", slot=1, sub=1),
    NodeSpec(id="processor", role="serverless_fn", lane="workers", region="", slot=0, sub=1),
    # Routing-cleanup (2026-10-28, owner "можна поміняти місцями аби 4 вийшло
    # згори. 3 зайва сходинка"): e4 (socket-handler->attachments) must route
    # ABOVE e3 (socket-handler->req-queue). The vertical order of two fan-out
    # legs from one source follows the relative row (y) of their targets, so
    # attachments is raised to the TOP of its own `data` lane (sub=0) — above
    # req-queue's row (async lane, sub=1) — giving e4 the upper corridor and e3
    # the lower one, and spreading the two targets far enough apart that e3
    # routes as a single clean stair (no extra jog). Coordinate-free; no pin.
    NodeSpec(id="attachments", role="object_store", lane="data", region="", slot=0, sub=0),
    # Task-4: the Syndicate Server (Syndi) is the EC2 control-plane host INSIDE
    # the SEP account (instance-profile syndicate-server, vpc-05cd5663a70d3a65c).
    # It is therefore an ACCOUNT MEMBER (platform-core lane, no on-premises lane),
    # rendered as the real EC2 compute_instance icon. Its SQS edges now cross the
    # account boundary from the inside out, which is correct. The deprecated
    # external "Syndicate task manager" (MVP Jenkins, another account) is removed.
    NodeSpec(id="syndi", role="compute_instance", lane="platform", region="", slot=0),
    # DIAL AI stays external: on-premises lane => OUTSIDE the account boundary.
    NodeSpec(id="dial", role="external", lane="on-premises", region="", slot=0),
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
    # e8 / e9 RESTORED (FEAT-002 ITEM D, owner: "Syndi-request-processor точно
    # повинна із кимось бути повязана. зараз загублений ресурс"). The
    # se-syndi-request-processor Lambda is the CONFIRMED event-source-mapping
    # consumer of se-support-response-queue, and it pushes the reply back to the
    # student's WebSocket via socket-api. Both edges were folded in wave-1 to cut
    # crossings; they are now back, routed cleanly by coordinate-free levers
    # (resp-queue on its own async sub-row, processor on the workers lane) so the
    # reply trio spreads vertically instead of bunching around the processor glyph.
    EdgeSpec(id="e8", source="resp-queue", target="processor", marker="8", dashed=True),
    EdgeSpec(id="e9", source="processor", target="socket-api", marker="9", dashed=True),
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
    "syndi": "Syndicate Server — Syndi",
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
    # Task-4 (owner 2026-10-23): the Syndicate Server is the EC2 control-plane
    # host INSIDE the SEP account. role="compute_instance" now resolves the real
    # EC2 service icon directly; it is an account member (platform lane), not an
    # external box. (DIAL AI stays external — a non-AWS AI proxy, NOT Bedrock.)
    # Owner feedback 2026-10-21: DIAL AI now renders the real EPAM DIAL brand mark
    # (dial role, mappings/local overlay — the owner-supplied dial.svg), not the
    # neutral box. It KEEPS NodeSpec role="external" so it stays in the
    # on-premises lane (outside the account boundary); only the glyph changes.
    if node_id == "dial":
        style = resolve_icon("dial", "aws")["style_string"]
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

    # Clarify gate (WS5): read-only, byte-inert for the .drawio.
    from rule_engine.layout.clarify import scan_uncertainties, format_assumptions_markdown
    def _rr(role):
        try:
            from rule_engine.icon_resolver import resolve_icon
            resolve_icon(role, "aws")
            return True
        except Exception:
            return False
    ASSUMPTIONS = scan_uncertainties(spec, role_resolves=_rr)
    if ASSUMPTIONS:
        (HERE.parent / f"{BASENAME}.assumptions.txt").write_text(
            format_assumptions_markdown(ASSUMPTIONS), encoding="utf-8")
    print(f"[clarify] {len(ASSUMPTIONS)} assumption(s)")

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
    # FEAT-003: the Syndicate Server EC2 hosts two components (Education
    # Extension + Syndi); this is the Syndi support view. Name the two
    # developer-stated Syndicate Server APIs as legend attributes (callouts): the
    # SS/EE Sandbox Access Management API and the Syndicate Server Reporting API
    # (emails + FreeMarker .ftl templates). The EE sandbox lifecycle is 05.
    SYNDI_API_LEGEND = (
        "Syndicate Server (EC2) hosts Education Extension (lifecycle, see 05) + Syndi (support)",
        "Syndicate Server APIs: SS/EE Sandbox Access Management API; Syndicate Server Reporting API (emails + FreeMarker .ftl)",
    )
    _legend_lines = tuple(legend_lines_for(boundaries)) + SYNDI_API_LEGEND
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
        legend_lines=_legend_lines,
        legend_mode=legend_mode,
        page_w=page_w,
        page_h=page_h,
        skin=NATIVE_SKIN,
        # WS2 flow_groups (1.11.0): decorative context boxes behind the members;
        # the engine now classifies flowgroup-* as furniture (not a node), so
        # intra-group edges no longer trip edge-routing. Node coords unchanged.
        # Task-4: syndi moved INTO the account, so it leaves the On-Premises
        # group; only DIAL AI remains external.
        flow_groups=(("On-Premises", ("dial",)), ("Async", ("req-queue", "resp-queue"))),
    )


if __name__ == "__main__":
    text = build()
    out = HERE.parent / f"{BASENAME}.drawio"
    out.write_text(text, encoding="utf-8")
    print("wrote", out)

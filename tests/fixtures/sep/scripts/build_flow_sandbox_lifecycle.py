#!/usr/bin/env python3
"""Build the SEP sandbox-lifecycle data-flow diagram (05-flow-sandbox-lifecycle).

Coordinate-free: declares a `DiagramSpec` (nodes/edges/containers/flow) and hands
it to the engine's `layout()` + `build_diagram()` pipeline — no hand-placed
geometry. This is a `flow` / `data-flow` view of the Education Extension (EE)
sandbox lifecycle — one of the two logical components of the Syndicate Server
(the other being Syndi, covered by 07) — between SEP (account 870325637521,
eu-central-1) and the in-account Syndicate Server EC2: the FIVE lifecycle SQS
queues allocate, activate, release and clean up a sandbox, notify SEP of
expiration and of resource-limit findings, and se-management-api-handler
persists the result in the external MongoDB Atlas cluster.

FEAT-003 (2026-10-23): the Syndicate Server EC2 (Name=syndicate-server) hosts
TWO logical components on one host — Education Extension (sandbox lifecycle) and
Syndi (student support). 05 is the EE lifecycle view, so the single server node
is captioned "Syndicate Server — Education Extension". It stays ONE node inside
the SEP account (never split into two). The five queue directions below are
developer-stated AND inventory-confirmed against
inventory .../event-source-mappings.json:
  1 allocate REQUEST  SEP -> EE  se-allocation-queue           (NO Lambda ESM — EE-consumed)
  1 allocate RESPONSE  EE -> SEP  se-activation-queue           -> se-management-api-handler (ESM 212fa9f3)
  2 release  REQUEST  SEP -> EE  se-deletion-queue             (NO Lambda ESM — EE-consumed)
  2 expiration NOTIFY  EE -> SEP  se-deletion-notification-queue -> se-management-api-handler (ESM a72b7c05)
  3 resource-limit FINDINGS EE -> SEP se-notification-queue      -> se-management-api-handler (ESM 02afbaa0)

So se-management-api-handler is the SEP-side consumer of the three EE->SEP reply
queues (activation / deletion-notification / notification); the two SEP->EE
request queues (allocation / deletion) have NO Lambda consumer because EE on the
server consumes them.

Lane layout (left -> right, data-flow axis) — the SQS dance is a request/reply
CYCLE, so the queues are split by direction so every queue<->Lambda edge reads
forward (enters Lambda's left face, never pierces it):
  edge     : activation-queue + deletion-notification-queue + notification-queue (EE->SEP returns)
  router   : se-management-api-handler Lambda (regional; inside the account)
  async    : allocation-queue + deletion-queue (SEP->EE sends)
  platform : Syndicate Server — Education Extension (EC2, SEP control plane — INSIDE the account)
  on-prem  : MongoDB Atlas (EXTERNAL)

The Syndicate Server is the SEP-internal control plane (syndicate-server EC2 in
account 870325637521), so it is drawn INSIDE the SEP account boundary (same as
01/06/07/09), in the `platform` lane. Its SQS allocation/deletion/return edges
cross the account boundary inside-out, which is correct. The return queues sit
LEFT of Lambda so each return queue -> Lambda edge enters Lambda's left face
(forward); the send queues sit RIGHT of Lambda so Lambda -> send queue reads
forward too. All five lifecycle queues + the Syndicate Server stay inside the
account; only MongoDB Atlas sits in the EXTERNAL `on-premises` lane (drawn
OUTSIDE the account box). MongoDB Atlas renders its real brand-green leaf; the
Syndicate Server renders the real EC2 service icon (compute_instance) — both
Icon-Fidelity clean.

SQS direction is modelled honestly: SEP->EE queues (allocation, deletion) and
EE->SEP queues (activation, deletion-notification, notification) are each a
single single-ended edge in the real direction of the message flow — never a
double-headed arrow.

Run from the workspace root:
    python3 scripts/build_flow_sandbox_lifecycle.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping

import yaml

from rule_engine.diagram_layout import (
    Boundary,
    Edge,
    ICON_SIZE,
    CONTAINER_PAD,
    Node,
    Skin,
    build_diagram,
    image_icon,
    legend_lines_for,
    overlay_suffix,
)
from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "05-flow-sandbox-lifecycle"
PROVIDER = "aws"
TITLE = "aws SEP sandbox lifecycle — 870325637521 / eu-central-1 | 2026-10-28 | v10"

# 1.11.0 native skin (see FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Skin: role -> draw.io style, read from the WORKSPACE mappings.
# --------------------------------------------------------------------------- #

_MAP = yaml.safe_load((ROOT / "mappings" / "aws-icons.yaml").read_text(encoding="utf-8"))
AWS_STYLES: Dict[str, str] = {
    role: entry["style"]
    for role, entry in (_MAP.get("resources") or {}).items()
    if isinstance(entry, dict) and entry.get("style")
}
AWS_CONTAINERS: Dict[str, str] = {
    kind: entry["style"]
    for kind, entry in (_MAP.get("containers") or {}).items()
    if isinstance(entry, dict) and entry.get("style")
}

# Neutral (non-AWS) styles for external nodes — a grayscale box, NOT a fake AWS
# icon (diagram-standards Icon Fidelity). Syndicate Server is an external EC2
# service; MongoDB Atlas is an external managed DB — both drawn as plain
# grayscale boxes so the diagram does not imply they are SEP-owned AWS icons.
NEUTRAL_SERVER_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#333333;dashed=1;"
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=12"
)
NEUTRAL_DB_STYLE = (
    "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "boundedLbl=1;backgroundOutline=1;size=15;"
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=12"
)


def _image_renderer(role: str):
    img = AWS_STYLES[role].split("image=", 1)[1]
    return image_icon(img)


def _flat_style_renderer(style_string: str):
    def render(node: Node, parent_id: str) -> str:
        style = f"{style_string}{overlay_suffix(node)}"
        return (
            f'        <mxCell id="{node.id}" value="{node.label}" style="{style}" '
            f'vertex="1" parent="{parent_id}">\n'
            f'          <mxGeometry x="{node.x}" y="{node.y}" '
            f'width="{ICON_SIZE}" height="{ICON_SIZE}" as="geometry" />\n'
            f"        </mxCell>\n"
        )

    return render


# --------------------------------------------------------------------------- #
# Spec declaration (coordinate-free).
# --------------------------------------------------------------------------- #

NODE_META: Dict[str, Mapping[str, str]] = {}


def _n(nid, role, lane, slot, caption, kind="aws", sub=0):
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind}
    return NodeSpec(id=nid, role=role, lane=lane, region="", slot=slot, sub=sub)


NODES = (
    # --- SEP cloud nodes (regional; inside the Account, outside any VPC) ----
    # RETURN queues (EE -> SEP), LEFT of Lambda so queue -> Lambda is forward.
    # All three are consumed by se-management-api-handler (ESMs 212fa9f3 /
    # a72b7c05 / 02afbaa0), verified against event-source-mappings.json.
    _n("activ-q", "message_queue", "edge", 0, "activation-queue"),
    _n("deln-q", "message_queue", "edge", 1, "deletion-notification-queue"),
    _n("notif-q", "message_queue", "edge", 2, "notification-queue"),
    # The SEP orchestrator Lambda — the hub between the return and send queues.
    _n("mgmt", "serverless_fn", "router", 0, "se-management-api-handler"),
    # SEND queues (SEP -> EE), RIGHT of Lambda so Lambda -> queue is forward.
    # Neither has a Lambda ESM — EE on the server consumes them directly.
    _n("alloc-q", "message_queue", "async", 0, "allocation-queue"),
    _n("del-q", "message_queue", "async", 1, "deletion-queue"),

    # --- SEP control plane (INSIDE the account), FEAT-003 2026-10-23 ----------
    # The Syndicate Server EC2 (Name=syndicate-server, SEP account 870325637521,
    # private 192.168.130.138) hosts TWO logical components; this diagram is the
    # Education Extension (EE) lifecycle view, so the ONE server node is
    # captioned "Syndicate Server — Education Extension". It is NEVER split into
    # two nodes. It is drawn INSIDE the SEP account boundary (same as
    # 01/06/07/09), NOT in an external On-Premises group. Placed in the
    # `platform` lane (right of the SEND queues it consumes), so e2/e6
    # (send-queue -> EE) read forward and its three return legs loop back to the
    # edge-lane return queues. No `container=` — the engine assigns account
    # membership geometrically and wraps the account envelope around it.
    # kind="ec2" -> compute_instance glyph. MongoDB Atlas stays EXTERNAL (below).
    _n("syndicate", "server", "platform", 0,
       "Syndicate Server — Education Extension", kind="ec2"),
    # MongoDB Atlas: external primary datastore over VPC peering. Dropped to a
    # sub-row (sub=2) so the persist edge (mgmt -> atlas) routes in its own
    # lower corridor instead of sharing a return corridor with the EE->SEP
    # reply legs; the shared corridor made markers overprint.
    _n("atlas", "db", "on-premises", 1, "MongoDB Atlas (external)", kind="db", sub=2),
)

CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None,
                  label_key="account"),
)

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521 / eu-central-1",
}

# Edge declaration — the SQS lifecycle "dance". Each queue is a single-ended
# edge in the real message direction (never a double-headed arrow):
#   SEP -> Server : allocation-queue, deletion-queue
#   Server -> SEP : activation-queue, deletion-notification-queue
EDGES = (
    # 1. SEP sends an allocation request to allocation-queue (SEP -> EE).
    EdgeSpec(id="e1", source="mgmt", target="alloc-q", marker="1", dashed=True),
    # 2. Education Extension consumes allocation-queue (NO Lambda ESM), provisions.
    EdgeSpec(id="e2", source="alloc-q", target="syndicate", marker="2", dashed=True),
    # 3. EE returns the activated sandbox details via activation-queue (EE -> SEP).
    EdgeSpec(id="e3", source="syndicate", target="activ-q", marker="3", dashed=True),
    # 4. se-management-api-handler consumes activation-queue (ESM 212fa9f3).
    EdgeSpec(id="e4", source="activ-q", target="mgmt", marker="4", dashed=True),
    # 5. On release/teardown, SEP sends cleanup to deletion-queue (SEP -> EE).
    EdgeSpec(id="e5", source="mgmt", target="del-q", marker="5", dashed=True),
    # 6. Education Extension consumes deletion-queue (NO Lambda ESM), tears down.
    EdgeSpec(id="e6", source="del-q", target="syndicate", marker="6", dashed=True),
    # 7. EE notifies expiration/auto-cleanup via deletion-notification-queue (EE -> SEP).
    EdgeSpec(id="e7", source="syndicate", target="deln-q", marker="7", dashed=True),
    # 8. se-management-api-handler consumes deletion-notification-queue (ESM a72b7c05).
    EdgeSpec(id="e8", source="deln-q", target="mgmt", marker="8", dashed=True),
    # 9. EE sends resource-limit findings / quota alerts via notification-queue (EE -> SEP).
    #    This is the 5th lifecycle queue, previously missing from 05.
    EdgeSpec(id="e9", source="syndicate", target="notif-q", marker="9", dashed=True),
    # 10. se-management-api-handler consumes notification-queue (ESM 02afbaa0).
    EdgeSpec(id="e10", source="notif-q", target="mgmt", marker="10", dashed=True),
    # 11. se-management-api-handler persists sandbox / application state in MongoDB Atlas.
    EdgeSpec(id="e11", source="mgmt", target="atlas", marker="11"),
)

FLOW = (
    "Flow",
    "1. se-management-api-handler sends an allocation request to allocation-queue (SEP to EE)",
    "2. Education Extension consumes allocation-queue (no Lambda ESM) and provisions the sandbox",
    "3. Education Extension returns the activated sandbox details via activation-queue (EE to SEP)",
    "4. se-management-api-handler consumes activation-queue (ESM 212fa9f3)",
    "5. On release, SEP sends teardown/cleanup to deletion-queue (SEP to EE)",
    "6. Education Extension consumes deletion-queue (no Lambda ESM); AWS Batch in the sandbox accounts cleans them up, driven by the EE; SEP + Batch verify",
    "7. Education Extension notifies expiration/auto-cleanup via deletion-notification-queue (EE to SEP)",
    "8. se-management-api-handler consumes deletion-notification-queue (ESM a72b7c05)",
    "9. Education Extension sends resource-limit findings / quota alerts via notification-queue (EE to SEP)",
    "10. se-management-api-handler consumes notification-queue (ESM 02afbaa0)",
    "11. se-management-api-handler updates sandbox / application state in MongoDB Atlas (over peering)",
)

LEGEND_EXTRA = (
    "Syndicate Server (EC2) hosts Education Extension + Syndi; this is the EE lifecycle view, INSIDE the account",
    "allocation-queue + deletion-queue: SEP -> EE requests, consumed by EE on the server (no Lambda ESM)",
    "activation + deletion-notification + notification queues: EE -> SEP, consumed by se-management-api-handler",
    "AWS Batch in the sandbox accounts performs the cleanup, driven by the Syndicate Server Education Extension (EE); SEP + Batch verify",
    "MongoDB Atlas is EXTERNAL (outside the box); EE drives the sandbox lifecycle via SQS; dashed = asynchronous",
)


def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-sep-sandbox-lifecycle",
        diagram_name=BASENAME,
        axis="left-right",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=FLOW,
        title=TITLE,
        compact=False,
        node_labels=node_labels,
        container_captions=tuple(CONTAINER_CAPTIONS.items()),
        # FEAT-003 (2026-10-23): 05 now draws ALL FIVE EE lifecycle queues with
        # every consume/produce edge (11 edges, no edge-folding) so each queue
        # direction is drawn, not merely named. Previously the 5th queue
        # (notification-queue, EE -> SEP resource-limit findings) was missing and
        # the teardown-confirmation leg was folded into the legend. The spacing
        # lever (row_step/col_step) is NOT set: the request/reply split by
        # direction (returns LEFT of Lambda, sends RIGHT) keeps every queue<->
        # Lambda edge forward, and the engine's 1.11.0 contact-selection routing
        # places the three return legs on their own corridors. No override.
    )


def _renderer_for(nid: str):
    meta = NODE_META[nid]
    if meta["kind"] == "db":
        # 1.10.11: MongoDB Atlas renders the real brand-green leaf
        # (mongodb_atlas role), not the grey neutral cylinder.
        return _image_renderer("mongodb_atlas")
    if meta["kind"] == "ec2":
        # Owner feedback (e): the external Syndicate Server is an EC2 host drawn
        # as its own node -> the real EC2 service icon (compute_instance).
        return _image_renderer("compute_instance")
    if meta["kind"] == "server":
        return _flat_style_renderer(NEUTRAL_SERVER_STYLE)
    return _image_renderer(meta["role"])


def _build() -> str:
    spec = _spec()

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
        (ROOT / f"{BASENAME}.assumptions.txt").write_text(
            format_assumptions_markdown(ASSUMPTIONS), encoding="utf-8")
    print(f"[clarify] {len(ASSUMPTIONS)} assumption(s)")

    placed = layout(spec, strict=False)
    for w in placed.layout_warnings:
        print(f"[layout WARNING] {w}")
    if placed.degraded:
        print("[layout] degraded candidate returned")

    nodes: List[Node] = [
        Node(
            id=n.id,
            label=NODE_META[n.id]["caption"],
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=_renderer_for(n.id),
        )
        for n in spec.nodes
        if n.id in placed.nodes
    ]

    boundaries: List[Boundary] = []
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        boundaries.append(Boundary(
            id=c.id, label=CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=AWS_CONTAINERS["boundary"], kind="account",
        ))

    edges: List[Edge] = [
        Edge(
            id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
            marker=pe.spec.marker, dashed=pe.spec.dashed,
            exit=pe.exit, entry=pe.entry,
            points=tuple((int(x), int(y)) for x, y in pe.points),
        )
        for pe in placed.edges
    ]

    legend_lines = list(legend_lines_for(boundaries)) + list(LEGEND_EXTRA)

    # Theme 43: aspect-driven placement. 05 is squarish (aspect ~1.8) -> Mode A:
    # Flow/Legend stack in the right margin, TOP-aligned to the body top, and the
    # page is sized tight to that stack (removing the bottom dead space the owner
    # flagged).
    from rule_engine.diagram_layout import theme43_legend_placement
    legend_x, legend_y_flow, legend_mode, page_w, page_h = theme43_legend_placement(
        nodes, boundaries, FLOW, legend_lines, placed.legend_w,
        engine_legend_x=placed.legend_x,
    )

    return build_diagram(
        diagram_id="aws-sep-sandbox-lifecycle",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=FLOW,
        legend_x=legend_x,
        legend_y_flow=legend_y_flow,
        legend_w=placed.legend_w,
        legend_lines=legend_lines,
        legend_mode=legend_mode,
        page_w=page_w,
        page_h=page_h,
        skin=NATIVE_SKIN,
        # WS2 flow_groups (1.11.0): decorative context box behind the members;
        # the engine now classifies flowgroup-* as furniture (not a node), so
        # intra-group edges no longer trip edge-routing. Node coords unchanged.
        flow_groups=(("On-Premises", ("atlas",)),),
    )


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the SEP sandbox-lifecycle data-flow diagram (05-flow-sandbox-lifecycle).

Coordinate-free: declares a `DiagramSpec` (nodes/edges/containers/flow) and hands
it to the engine's `layout()` + `build_diagram()` pipeline — no hand-placed
geometry. This is a `flow` / `data-flow` view of the SQS "dance" between SEP
(account 870325637521, eu-central-1) and the external Syndicate Server (EC2):
the four lifecycle SQS queues allocate, activate, delete and confirm-delete a
sandbox AWS account, and management-api-handler persists the result in the
external MongoDB Atlas cluster.

Lane layout (left -> right, data-flow axis) — the SQS dance is a request/reply
CYCLE, so the queues are split by direction so every queue<->Lambda edge reads
forward (enters Lambda's left face, never pierces it):
  edge     : activation-queue + deletion-notification-queue (Server->SEP returns)
  router   : se-management-api-handler Lambda (regional; inside the account)
  async    : allocation-queue + deletion-queue (SEP->Server sends)
  on-prem  : Syndicate Server (EXTERNAL EC2) + MongoDB Atlas (EXTERNAL)

The return queues sit LEFT of Lambda so each return queue -> Lambda edge enters
Lambda's left face (forward); the send queues sit RIGHT of Lambda so Lambda ->
send queue reads forward too. The Server -> return-queue legs loop back as
back-edges (exit right / enter left-top), which is the honest shape of a reply
queue. All four lifecycle queues stay inside the account; the two external nodes
sit in the EXTERNAL `on-premises` lane (drawn OUTSIDE the account box), so the
engine's account envelope wraps ONLY the SEP cloud nodes (Lambda + 4 SQS).
Externals render as neutral grayscale boxes (NOT a fake AWS icon) per
diagram-standards "Icon Fidelity". The SQS<->Syndicate Server edges correctly
cross the account boundary.

SQS direction is modelled honestly: SEP->Server queues (allocation, deletion)
and Server->SEP queues (activation, deletion-notification) are each a single
single-ended edge in the real direction of the message flow — never a
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
TITLE = "aws SEP sandbox lifecycle — 870325637521 / eu-central-1 | 2026-10-17 | v4"

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
    # RETURN queues (Server -> SEP), LEFT of Lambda so queue -> Lambda is forward.
    _n("activ-q", "message_queue", "edge", 0, "activation-queue"),
    _n("deln-q", "message_queue", "edge", 1, "deletion-notification-queue"),
    # The SEP orchestrator Lambda — the hub between the return and send queues.
    _n("mgmt", "serverless_fn", "router", 0, "management-api-handler"),
    # SEND queues (SEP -> Server), RIGHT of Lambda so Lambda -> queue is forward.
    _n("alloc-q", "message_queue", "async", 0, "allocation-queue"),
    _n("del-q", "message_queue", "async", 1, "deletion-queue"),

    # --- EXTERNAL, drawn OUTSIDE the account box (on-premises lane) ---------
    # Syndicate Server: an external EC2 host drawn as its own node -> render the
    # real EC2 service icon (compute_instance), not a neutral box (owner
    # feedback 2026-10-17 e). It stays EXTERNAL (on-premises lane, outside the
    # account box); the EC2 glyph names the real resource type, which is Icon-
    # Fidelity clean. kind="ec2" selects the compute_instance renderer below.
    _n("syndicate", "server", "on-premises", 0, "Syndicate Server (EC2, external)", kind="ec2"),
    # MongoDB Atlas: external primary datastore over VPC peering. Dropped to a
    # sub-row (sub=2) so the persist edge e9 (mgmt -> atlas) routes in its own
    # lower corridor instead of sharing the y=250 return corridor with e7
    # (syndicate -> deletion-notification-queue); the shared corridor made
    # markers 7 and 9 overprint. sub=2 clears corridor-sharing(e7,e9) and drops
    # edge-crossing-excess 6 -> 5, with no new findings (layout already degraded
    # on this spec, unchanged by the move).
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
    # 1. Lambda sends an allocation request to allocation-queue (SEP -> Server).
    EdgeSpec(id="e1", source="mgmt", target="alloc-q", marker="1", dashed=True),
    # 2. Syndicate Server consumes allocation-queue, provisions a sandbox acct.
    EdgeSpec(id="e2", source="alloc-q", target="syndicate", marker="2", dashed=True),
    # 3. Server returns provisioned account data via activation-queue (Server -> SEP).
    EdgeSpec(id="e3", source="syndicate", target="activ-q", marker="3", dashed=True),
    # 4. management-api-handler consumes activation-queue (event-source mapping).
    EdgeSpec(id="e4", source="activ-q", target="mgmt", marker="4", dashed=True),
    # 5. On terminal task / destroy, Lambda sends cleanup to deletion-queue (SEP -> Server).
    EdgeSpec(id="e5", source="mgmt", target="del-q", marker="5", dashed=True),
    # 6. Syndicate Server consumes deletion-queue, runs AWS Nuke.
    EdgeSpec(id="e6", source="del-q", target="syndicate", marker="6", dashed=True),
    # 7. Server confirms teardown via deletion-notification-queue (Server -> SEP).
    # 1.10.12 WS5: drawn again (1.10.11 folded it into the Flow legend, which
    # left step 7 undrawn); the engine lays this reply on the return bus.
    EdgeSpec(id="e7", source="syndicate", target="deln-q", marker="7", dashed=True),
    # 8. management-api-handler consumes deletion-notification-queue (event-source mapping).
    EdgeSpec(id="e8", source="deln-q", target="mgmt", marker="8", dashed=True),
    # 9. Lambda persists sandbox / application state in MongoDB Atlas.
    EdgeSpec(id="e9", source="mgmt", target="atlas", marker="9"),
)

FLOW = (
    "Flow",
    "1. management-api-handler sends an allocation request to allocation-queue (SEP to Server)",
    "2. Syndicate Server consumes allocation-queue and provisions an AWS sandbox account",
    "3. Syndicate Server returns the provisioned account data via activation-queue (Server to SEP)",
    "4. management-api-handler consumes activation-queue (confirmed event-source mapping)",
    "5. On terminal task state or destroy, SEP sends cleanup to deletion-queue (SEP to Server)",
    "6. Syndicate Server consumes deletion-queue and runs AWS Nuke on the sandbox",
    "7. Syndicate Server confirms teardown via deletion-notification-queue (Server to SEP)",
    "8. management-api-handler consumes deletion-notification-queue (confirmed event-source mapping)",
    "9. management-api-handler updates sandbox / application state in MongoDB Atlas (over peering)",
)

LEGEND_EXTRA = (
    "Syndicate Server (EC2) + MongoDB Atlas are EXTERNAL, drawn outside the account box",
    "allocation-queue + deletion-queue: NO Lambda consumer in SEP (consumed by Syndicate Server)",
    "activation-queue + deletion-notification-queue: consumed by se-management-api-handler",
    "Syndicate Server talks to SEP exclusively via SQS; dashed = asynchronous",
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
        # Theme 36 (regen4): the spacing lever (DiagramSpec.row_step/col_step,
        # 1.10.11) was TESTED on this spec and REJECTED by reading the exported
        # PNG. The SQS "dance" is already crossing-minimal after the e7
        # edge-fold (lint [OK]; only canvas-utilization + an e3 container-caption
        # WARNING). Widening to row_step=200/col_step=260 made it WORSE, not
        # wider-and-cleaner: edge e3 (syndicate->activation-queue return) was
        # pushed up onto the top corridor where it STRUCK THROUGH THE TITLE
        # (edge-crosses-title), and marker 9 landed on the deletion-queue caption
        # (marker-label-collision[e9,del-q]) — i.e. the lever RELOCATED a
        # marker-on-caption overlap of exactly the kind the owner complained
        # about. The crossing density of this fan is edge-count-driven, not
        # spacing-driven, so widening the grid does not thin it; it only moves
        # the return legs into worse corridors. The honest lever here stays
        # EDGE-FOLDING (e7 teardown-confirmation folded into the Flow legend),
        # which is why no override is set. Verified: regen4 before/after rasters
        # recorded in RULE-ENGINE-FEEDBACK Theme 36 (wave 11).
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
    )


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

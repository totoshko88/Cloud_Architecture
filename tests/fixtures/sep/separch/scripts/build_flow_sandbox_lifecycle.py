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
CYCLE. v11 (2026-11-03) lays the cycle out so EE -> reply-queue reads FORWARD,
cutting the cycle at the two SEP -> EE send requests (the only back-edges), so
the three EE -> SEP reply legs no longer rake back across the whole account:
  edge     : allocation-queue + deletion-queue (SEP->EE sends)
  router   : Syndicate Server (EE) (EC2, SEP control plane — INSIDE the account)
  async    : activation-queue + deletion-notification-queue + notification-queue (EE->SEP replies)
  workers  : se-management-api-handler Lambda (VPC-attached; inside the account)
  on-prem  : MongoDB Atlas (EXTERNAL SaaS, account 781849312837)

The Syndicate Server is the SEP-internal control plane (syndicate-server EC2 in
account 870325637521), so it is drawn INSIDE the SEP account boundary (same as
01/06/07/09), in the `router` lane BETWEEN the send queues it consumes (left,
e2/e6) and the reply queues it produces (right, e3/e7/e9), so every queue<->EE
edge reads forward (never pierces a face). The Lambda sits RIGHT of the reply
queues so each reply-queue -> Lambda edge is forward too; only the two send
requests (mgmt -> allocation/deletion queue, e1/e5) are back-edges, ridden on a
return bus inside the account. All five lifecycle queues + the Syndicate Server
stay inside the account; only MongoDB Atlas sits in the EXTERNAL `on-premises`
lane (drawn OUTSIDE the account box) as a peered SaaS cluster — NOT an
on-premises data centre. MongoDB Atlas renders its real brand-green leaf; the
Syndicate Server renders the real EC2 service icon (compute_instance) — both
Icon-Fidelity clean.

The review's alternative (reply queues in a second row under Lambda + a return
bus under the row) is NOT used: engine 1.13.0 does not offer the return bus to a
reply whose target sits on a lower row (gap E7), so that layout left e7 crossing
five edges. See .agents/tasks/phase2-feedback-05-08.md.

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
TITLE = "aws SEP sandbox lifecycle — 870325637521 / eu-central-1 | 2026-11-03 | v11"

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
    # v11 (2026-11-03): the request/reply CYCLE is laid out so EE -> reply queue
    # reads FORWARD (left -> right) instead of raking the three reply legs back
    # across the whole account. Lane order left -> right is:
    #   send-q (edge) | EE (router) | reply-q (async) | mgmt (workers) | atlas
    # which cuts the cycle at the two SEP -> EE send requests (e1/e5, mgmt ->
    # send-q) — the only two back-edges, ridden on a return bus inside the
    # account — and makes all three EE -> SEP reply legs (e3/e7/e9) short forward
    # hops. This removes 05-1 (e7's 5 crossings), 05-2 (e7 own-caption cut: the
    # EE node no longer needs a bottom exit under its caption), 05-3 (e9 escaping
    # the account), 05-4 (e3/e9 collinear) and 05-5. The second-row-under-Lambda
    # + return-bus alternative from the review is NOT used because this engine
    # (1.13.0) does not offer the return bus to a reply whose target sits on a
    # lower row (engine gap E7 / phase-1 report "synced 05 e7"); see
    # .agents/tasks/phase2-feedback-05-08.md.

    # --- SEND queues (SEP -> EE), the cycle's left edge (`edge` lane). ---------
    # Neither has a Lambda ESM — EE on the server consumes them directly. They
    # are the targets of the two back-edges (mgmt -> send-q, the return bus).
    _n("alloc-q", "message_queue", "edge", 0, "allocation-queue"),
    _n("del-q", "message_queue", "edge", 1, "deletion-queue"),

    # --- SEP control plane (INSIDE the account), FEAT-003 2026-10-23 ----------
    # The Syndicate Server EC2 (Name=syndicate-server, SEP account 870325637521,
    # private 192.168.130.138) hosts TWO logical components; this diagram is the
    # Education Extension (EE) lifecycle view, so the ONE server node is
    # captioned "Syndicate Server (EE)" (05-10: shortened from the 5-word label;
    # the two-component note lives in the Legend). It is NEVER split into two
    # nodes and is drawn INSIDE the SEP account boundary (same as 01/06/07/09),
    # NOT in an external group. Placed in the `router` lane between the send
    # queues (left, it consumes them: e2/e6) and the reply queues (right, it
    # produces them: e3/e7/e9), so every queue<->EE edge reads forward.
    # kind="ec2" -> compute_instance glyph.
    _n("syndicate", "server", "router", 0,
       "Syndicate Server (EE)", kind="ec2"),

    # --- REPLY queues (EE -> SEP), RIGHT of EE so EE -> queue is forward. ------
    # All three are consumed by se-management-api-handler (ESMs 212fa9f3 /
    # a72b7c05 / 02afbaa0), verified against event-source-mappings.json.
    _n("activ-q", "message_queue", "async", 0, "activation-queue"),
    _n("deln-q", "message_queue", "async", 1, "deletion-notification-queue"),
    _n("notif-q", "message_queue", "async", 2, "notification-queue"),

    # The SEP orchestrator Lambda — consumes the three reply queues (e4/e8/e10)
    # and produces the two send queues (e1/e5, the return bus). VPC-attached
    # (VpcId vpc-05cd5663a70d3a65c); reaches MongoDB Atlas over peering
    # pcx-0e257b23d337fda0b (noted in the Legend, 05-8). Placed in `workers`,
    # just left of the external Atlas it persists to (e11 forward).
    _n("mgmt", "serverless_fn", "workers", 0, "se-management-api-handler"),

    # MongoDB Atlas: EXTERNAL primary datastore in the Atlas-managed peered AWS
    # account 781849312837 (NOT 088595288622 — see INVENTORY-STATE.md §9A
    # pcx-0e257b23d337fda0b), reached over VPC peering. Drawn OUTSIDE the account
    # box in the external `on-premises` lane. 05-6: it is a peered SaaS cluster,
    # not a corporate data centre, so its context group is captioned "External
    # SaaS", never "On-Premises".
    _n("atlas", "db", "on-premises", 1, "MongoDB Atlas (781849312837)", kind="db"),
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

# 05-11: one fact per line, no ";"-merged lines, and no "dashed = asynchronous"
# duplicate (legend_lines_for already defines the dashed line). 05-8: Lambda is
# VPC-attached and reaches Atlas over peering — stated here, not in the node
# label (which would exceed node-label-length). 05-6: the grey context box is
# "External SaaS", a peered SaaS cluster, not a boundary.
LEGEND_EXTRA = (
    "Syndicate Server (EC2) hosts Education Extension + Syndi; this is the EE lifecycle view, INSIDE the account",
    "allocation-queue + deletion-queue: SEP -> EE requests, consumed by EE on the server (no Lambda ESM)",
    "activation + deletion-notification + notification queues: EE -> SEP, consumed by se-management-api-handler",
    "se-management-api-handler is VPC-attached (vpc-05cd5663a70d3a65c); reaches Atlas over peering pcx-0e257b23d337fda0b",
    "AWS Batch in the sandbox accounts performs the cleanup, driven by the EE; SEP + Batch verify",
    "MongoDB Atlas is EXTERNAL SaaS in the peered account 781849312837 (outside the box); EE drives the lifecycle via SQS",
    "Grey rounded box = context group (External SaaS), not a boundary",
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
        # Every edge comes from layout() with the engine's own routed points, so
        # declare them engine-routed (pinned_ids=()) to silence the false
        # "rerouted hand-pinned edges" warning (phase-1 report item 15).
        pinned_ids=(),
        # WS2 flow_groups (1.11.0): decorative context box behind the member.
        # 05-6: Atlas is a peered SaaS cluster (account 781849312837), NOT a
        # corporate data centre, so the context group is captioned "External
        # SaaS" — never "On-Premises". The engine classifies flowgroup-* as
        # furniture (not a node), so intra-group edges do not trip edge-routing.
        flow_groups=(("External SaaS", ("atlas",)),),
    )


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

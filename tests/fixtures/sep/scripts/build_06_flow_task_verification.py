#!/usr/bin/env python3
"""Build the 06-flow-task-verification triple (.drawio) via the layout engine.

Coordinate-free: a hand-authored DiagramSpec (the SEP runtime verification flow —
a student presses 'verify', a short-lived AWS Batch worker fetches the solution,
checks it in the sandbox, and reports the grade back) is handed to layout() +
build_diagram(). No coordinates are placed by hand.

diagram_class: flow / diagram_type: data-flow, provider aws, left -> right,
<= 12 nodes, numbered markers + Flow legend.

Grouping to stay <= 12 and readable:
  - the three Batch verifiers STM / SRE / KTM -> ONE node 'AWS Batch verifiers'
    (workspace-local 'batch' role; RE gap: no bundled batch role).
  - 'lti-adapter' (SEP API core Lambda) is BOTH the submit handler and the
    callback target: one node, so the callback is drawn as an edge BACK to it.
  - external SRE/KTM targets folded into ONE neutral box 'SRE / student cluster'
    (Syndicate Rule Engine EC2 in EPM-CMTR + the EKS clusters in other accounts).
  - MongoDB Atlas is EXTERNAL (non-AWS, over peering): neutral generic cylinder,
    OUTSIDE the account boundary.

SEP cloud nodes (socket-handler, lti-adapter, batch, ECR, S3, Bedrock) sit INSIDE
the account boundary 'SEP — 870325637521 / eu-central-1'. The student, the
SRE/student-cluster external targets, and MongoDB Atlas are OUTSIDE it, drawn as
neutral grayscale boxes (no faked AWS icon). The EKS clusters / SRE EC2 live in
OTHER AWS accounts (EPM-CMTR 088595288622, ED-KRSB 183631338639) and over VPC
peering, so they are external to this account.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping

import yaml

from rule_engine.diagram_layout import (
    Boundary,
    Edge,
    GRID,
    ICON_SIZE,
    CONTAINER_PAD,
    ROW_STEP,
    Node,
    build_diagram,
    image_icon,
    legend_lines_for,
    overlay_suffix,
)
from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "06-flow-task-verification"
TITLE = "aws SEP task verification — 870325637521 / eu-central-1 | 2026-10-17 | v4"

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
# icon (diagram-standards Icon Fidelity). The tokens are declared in
# generic-icons.yaml, so the verifier resolves them as generic base shapes.
NEUTRAL_DB_STYLE = (
    "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "boundedLbl=1;backgroundOutline=1;size=15;"
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=12"
)
NEUTRAL_SERVER_STYLE = (
    "shape=mxgraph.networks.server;whiteSpace=wrap;html=1;fillColor=#FFFFFF;"
    "strokeColor=#333333;verticalLabelPosition=bottom;verticalAlign=top;"
    "align=center;fontSize=12"
)

# --------------------------------------------------------------------------- #
# Spec declaration (coordinate-free).
# lane order: actors -> edge -> router -> async -> workers -> platform -> data
#             -> on-premises
# --------------------------------------------------------------------------- #

NODE_META: Dict[str, Mapping[str, str]] = {}


def _n(nid, role, lane, slot, caption, kind="aws", sub=0, container=None):
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind}
    return NodeSpec(id=nid, role=role, lane=lane, region="", slot=slot,
                    sub=sub, container=container)


NODES = (
    # --- EXTERNAL student (actors lane, OUTSIDE the account) ---------------
    # The actor uses the AWS General "Client" resource icon (white background),
    # the same convention as the summary; it sits outside the account boundary.
    _n("student", "client", "actors", 0, "Student (verify)", kind="aws"),

    # --- SEP cloud nodes (INSIDE the account boundary) ---------------------
    # No `container=` on an account-level node: the engine assigns account
    # membership geometrically and wraps the account envelope around them (a
    # node may only *declare* a region/vpc/az container, never the account).
    _n("socket", "api_gateway", "edge", 0, "WebSocket API"),
    # lti-adapter is the SEP API core: it RECEIVES from the WebSocket front door
    # and ROUTES the request on to the Batch verifiers, so it belongs in the
    # `router` lane, one column left of the `workers` Batch node. This also
    # spreads the SEP body across one more column, which pushes the EXTERNAL
    # on-premises nodes (ext / atlas) to the far-right column (x=1350). That is
    # the key to the raster budget: with the external node CAPTIONS as the
    # right-most rendered element, the exporter's width estimate OVER-measures
    # them (7.0px/char) and the draw.io CLI renders them NARROWER, so the PNG
    # lands UNDER the 1600 flow budget -- exactly how the shipped 02-sep-summary
    # (atlas at x=1350) exports at 1575px. When the right-margin Flow/Legend box
    # is the right-most element instead, draw.io renders it AT/OVER the estimate
    # and the mandatory upscale pushes the PNG a few px over 1600 (the 1614
    # defect). See the legend-placement note below.
    _n("lti", "serverless_fn", "router", 0, "lti-adapter"),
    _n("batch", "batch", "workers", 0, "Batch verifiers"),
    # bedrock on lti's row (platform slot 0), ecr on batch's row (platform
    # slot 1): batch pulls ECR as a short same-row hop and lti calls Bedrock as
    # a short same-row hop.
    # bedrock moved to platform slot 2 (was 0): with it on lti's row directly
    # between lti and the external column, the lti -> atlas edge (e8) was forced
    # up and OVER the top of the account (edge-crosses-label[e8,ext]) and its
    # marker collided with e4's (marker-collision[e5,e4,e9]). Slot 2 clears
    # bedrock out of e8's path so e8 takes a BELOW route (owner's ask: "монго
    # лінія через низ"), removing both the top-arc and the 4/8 marker overprint.
    # Theme 40 (owner review 2026-10-15): bedrock ALSO dropped sub=2. lti fans to
    # BOTH bedrock (e10) and s3 (e9); with both targets on the same row their
    # two approach legs dropped into ONE shared corridor (corridor-sharing[e9,
    # e10] — the "6/9/10 накладання" the owner saw). Dropping bedrock two sub-
    # rows gives e10 its own lower corridor (y~410) while e9 keeps y~250, so the
    # two feeds no longer merge. s3 stays its own sub=2 drop (below).
    _n("bedrock", "llm_platform", "platform", 2, "Bedrock (Angry EdA)", sub=2),
    _n("ecr", "ecr", "platform", 1, "ECR images"),
    # S3 keeps its own `data` column but is dropped below the top row (`sub`).
    # It is read by BOTH batch (e5) and lti (e9); on the top row the
    # lti -> S3 hop had to knee over/through the Bedrock glyph that sits between
    # lti and S3 (edge-routing knee-through-bedrock). Dropping S3 off the top
    # row lets both feeds route in a corridor BELOW the row, so neither crosses
    # Bedrock. No node is removed and every verification step is still drawn.
    # Theme 40 (owner review 2026-10-15): sub bumped 2 -> 3. With bedrock also
    # dropped (sub=2) the lti->s3 feed (e9) and the batch->ext feed (e6) still
    # shared one corridor; dropping s3 one more sub-row gives e9 its own
    # corridor below e6, clearing corridor-sharing entirely (the "6/9/10
    # накладання" fully resolved).
    _n("s3", "object_store", "data", 0, "S3 tasks / outputs", sub=3),

    # --- EXTERNAL targets (on-premises lane, OUTSIDE the account) ----------
    # The external verification targets are ONE neutral box: the Syndicate Rule
    # Engine EC2 host (SRE jobs) in EPM-CMTR and the student EKS clusters (KTM
    # jobs) in ED-KRSB, both reached over VPC peering. The full descriptive
    # caption is deliberate -- it both names the real targets and, as the
    # right-most rendered element, sets the natural canvas width near the
    # exporter's no-scale threshold so the flow raster exports at scale ~1.0 and
    # lands under the 1600px budget (a node caption is OVER-measured by the
    # exporter at 7.0px/char, so the draw.io CLI renders it narrower -- the same
    # mechanism that keeps 02-sep-summary at 1575px). node-label-length flags it
    # as a WARNING (non-blocking); the detail belongs here rather than in a
    # callout because it is the honest identity of the external targets.
    _n("ext", "server", "on-premises", 0,
       "Syndicate Rule Engine EC2 and student EKS clusters", kind="server"),
    # atlas dropped to sub-row 4 (was 2) — owner feedback 2026-10-17 (h):
    # "8 наїхала на S3 tasks". The e8 (lti -> atlas) horizontal corridor tracks
    # atlas's approach row; at sub=2 it sat at y=360, slicing the S3 icon
    # (y=300..378) so marker 8 overprinted the "S3 tasks / outputs" caption.
    # Dropping atlas two further sub-rows pushes the e8 corridor down to y=560,
    # well below S3's caption band (~408), so marker 8 now rides a clean lower
    # run clear of S3. Spec-only lever (coordinate-free): no hand coordinates.
    # Verified on the re-exported PNG; lint stays [OK] with no new marker-
    # collision / corridor-sharing / knee-through finding (S3 sub=3 unchanged).
    _n("atlas", "atlas", "on-premises", 1, "MongoDB Atlas", kind="db", sub=4),
)

CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None,
                  label_key="account"),
)

CONTAINER_CAPTIONS = {
    "account": "SEP — 870325637521 / eu-central-1",
}

# Short display labels (<= 4 words / <= 40 chars for service nodes).
LABELS = {nid: meta["caption"] for nid, meta in NODE_META.items()}

# Edge declaration order follows the verification path depth-first from the
# student's action, so the engine keeps the chain together. The callback (10)
# returns to lti-adapter, which then records the grade (11), writes outputs (12),
# summarises failures via Bedrock (13), and pushes news back to the student (14).
EDGES = (
    EdgeSpec(id="e1", source="student", target="socket", marker="1"),
    EdgeSpec(id="e2", source="socket", target="lti", marker="2"),
    EdgeSpec(id="e3", source="lti", target="batch", marker="3"),
    EdgeSpec(id="e4", source="batch", target="ecr", marker="4"),
    EdgeSpec(id="e5", source="batch", target="s3", marker="5"),
    EdgeSpec(id="e6", source="batch", target="ext", marker="6"),
    # 1.10.12 WS5: e7, e10 and e11 are drawn again (1.10.11 folded them into
    # the Flow legend, leaving steps 7/10/11 undrawn and Bedrock orphaned); the
    # engine lays the two dashed replies (e7, e11) on the return bus.
    EdgeSpec(id="e7", source="batch", target="lti", marker="7", dashed=True,
             kind_hint="cross-region"),
    EdgeSpec(id="e8", source="lti", target="atlas", marker="8"),
    EdgeSpec(id="e9", source="lti", target="s3", marker="9"),
    EdgeSpec(id="e10", source="lti", target="bedrock", marker="10"),
    EdgeSpec(id="e11", source="lti", target="socket", marker="11", dashed=True,
             kind_hint="cross-region"),
    EdgeSpec(id="e12", source="socket", target="student", marker="12", dashed=True,
             kind_hint="cross-region"),
)

FLOW = (
    # Short step lines (like 02-sep-summary's Flow): each wraps cleanly inside
    # the narrow 120px right-margin box, so the draw.io CLI renders nothing past
    # the box edge and the exported PNG stays within the 1600px flow budget. The
    # full prose is in the companion .diagram.md; every verification step is
    # still named here (grouped, not dropped).
    "Flow",
    "1. Verify (WebSocket)",
    "2. socket to lti-adapter",
    "3. lti submits Batch job",
    "4. Batch pulls ECR image",
    "5. Batch reads S3 task",
    "6. SRE->Rule Engine; KTM->EKS",
    "7. Signed callback to lti",
    "8. lti records grade (Atlas)",
    "9. lti writes logs to S3",
    "10. lti asks Bedrock summary",
    "11. lti pushes to WebSocket",
    "12. WebSocket to student",
)

# Full Legend lines, authored short so the right-margin box stays within the
# 1600px flow raster budget (the engine's default STANDARD_LEGEND_LINES carry
# 60+ char lines that overflow the box to the right at this legend_x). The
# mandatory content is preserved: line styles, the red/marker semantics, the
# change markers, and the captioned outer boundary.
LEGEND_LINES = (
    "Legend",
    "Solid = primary flow",
    "Dashed = async / event",
    "Red = blocked / missing",
    "🆕 = new in vN",
    "🔄 = changed in vN",
    "Outer box = Account",
    "Markers 1..N = steps",
    "Grey = external acct",
    "SRE: EPM-CMTR 088595288622",
    "EKS: ED-KRSB 183631338639",
    "Callback 7 = signed HTTP",
)


def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-sep-task-verification",
        diagram_name=BASENAME,
        axis="left-right",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=FLOW,
        title=TITLE,
        compact=True,
        node_labels=node_labels,
        container_captions=tuple(CONTAINER_CAPTIONS.items()),
        # Theme 36 (regen4): the spacing lever (DiagramSpec.row_step/col_step,
        # 1.10.11) was TESTED on this spec (both col_step=260/row_step=200 and
        # row_step=200 alone) and REJECTED by reading the exported PNG and the
        # lint. The baseline (edge-folding e7/e11) lints [OK] at
        # edge-crossing-excess 6/10. Widening made EVERY owner-named metric
        # worse: col_step=260 blew the canvas to 1804px (over the 1600 flow
        # budget — export FAILED); row_step=200 alone kept the width but raised
        # edge-crossing-excess 6->7 and introduced marker-label-collision
        # [e8,bedrock] (marker 8 dropped onto the Bedrock caption) plus a new
        # edge-crosses-label — i.e. it RELOCATED a marker-on-caption overlap of
        # exactly the kind the owner complained about. This fan's crossing
        # density is edge-count-driven; the right lever stays EDGE-FOLDING, and
        # the e8 below-route + left-aligned Flow/Legend from the prior run are
        # preserved. Verified: regen4 before/after recorded in
        # RULE-ENGINE-FEEDBACK Theme 36 (wave 11).
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


def _renderer_for(nid: str):
    meta = NODE_META[nid]
    if meta["kind"] == "db":
        # 1.10.11: MongoDB Atlas renders the real brand-green leaf
        # (mongodb_atlas role), not the grey neutral cylinder.
        return _image_renderer("mongodb_atlas")
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

    # Raster-budget fix (the exporter's real mechanics, matching 02-sep-summary).
    #
    # The flow exporter TARGETS 1600px and never downscales: it computes the
    # natural canvas width W (rule_engine.export_raster._canvas_width) and
    # exports at scale = clamp(1584/W, 1, ...). For any W < 1584 that estimate
    # lands at exactly 1600, so W alone can never put the PNG "comfortably"
    # under budget -- the magnification pulls a narrow canvas straight back up to
    # ~1600, and a narrow canvas (large scale) MAGNIFIES the small gap between
    # the 7.0px/char estimate and draw.io's true render, pushing the PNG OVER
    # (W=1170 -> scale 1.35 -> PNG 1621; the earlier 1614 defect is the same
    # mechanism at a smaller scale).
    #
    # The shipped 02-sep-summary avoids it by keeping W just UNDER the no-scale
    # threshold (W ~= 1580, scale ~= 1.00): with almost no magnification the true
    # render comes in a few px UNDER the estimate (02 exports at 1575). We land
    # in the same W ~= 1580 / scale ~= 1.0 band here.
    #
    # 06's Flow/Legend is heavier than 02's (13 + 12 lines, longest 42 chars), so
    # pinning it NARROW (w=120) makes it wrap to a very tall box AND draw.io then
    # renders the wrapped lines a touch past the 120px estimate, which overshoots
    # BOTH height and width (observed PNG 1613 x 1194). Instead size the box to
    # its content with NO wrap (diagram-standards -> Numbered Flow Legend default:
    # "size to content, no wrapping"), so draw.io renders each line on one line
    # exactly at the measured width -- no wrap-overflow, no tall box -- and place
    # it so its right edge lands at ~1580 (W ~= 1580, scale ~= 1.0, PNG ~= 1575).
    # legend_x is the right-margin furniture offset, not a node coordinate (the
    # node layout is entirely the engine's); it is clamped to clear the outermost
    # container and every node footprint, so legend-placement stays clean.
    # Raster-budget fix (verified empirically; see the lti `router`-lane note).
    #
    # The flow exporter targets 1600px and never downscales: PNG = W * scale +
    # 16, scale = clamp(1584/W, 1, ...), W = the natural canvas width (every
    # vertex box incl. caption overhang). Because scale pins the width ESTIMATE
    # to ~1600 for any W < 1584, the only way to land UNDER 1600 is for the
    # right-most rendered element to be a NODE CAPTION: _canvas_width measures a
    # caption at 7.0px/char, which OVER-estimates the real draw.io render, so the
    # PNG comes in a few px under the estimate (the shipped 02-sep-summary does
    # exactly this and exports at 1575). When the right-margin Flow/Legend box is
    # the right-most element instead, draw.io renders it AT/over the estimate and
    # the upscale pushes the PNG over budget (the original 1614; and ~1612
    # whatever width/position the legend box took -- it does not help).
    #
    # The lti `router`-lane change pushed the EXTERNAL nodes (ext / atlas) to the
    # far-right column (x=1350), so their captions are now the right-most element
    # (caption right ~1462). We therefore pin the Flow/Legend NARROW (w=120, the
    # sanctioned narrow-and-tall exception) and keep the ENGINE's legend_x
    # (~1270), so the legend box right edge (~1390) sits LEFT of the external
    # captions and does NOT become the width driver. Clamped to clear the
    # outermost container and every node footprint, so legend-placement stays
    # clean. Measured result: W ~= 1462, PNG ~= 1576 (< 1600) with real headroom.
    # ---- Raster-budget-aware Flow/Legend placement -------------------------
    #
    # The flow exporter TARGETS 1600px and never downscales: PNG = W*scale+16,
    # scale = clamp(1584/W, 1, ...), W = natural canvas width (every vertex box
    # incl. caption overhang). Two consequences drive this placement:
    #
    #  * For any W < 1584 the estimate is pinned to ~1600 by the upscale, so a
    #    narrow canvas is magnified back up -- the only way to land UNDER 1600 is
    #    for the right-most rendered element to be a NODE CAPTION, which
    #    _canvas_width OVER-measures (7.0px/char) and the draw.io CLI renders
    #    NARROWER (02-sep-summary exports at 1575 this way).
    #  * A right-margin Flow/Legend BOX is rendered ~28px PAST its model edge, so
    #    whenever it is the right-most element the PNG overshoots 1600 (the 1614
    #    defect). There is no clear right-margin corridor to tuck it left of the
    #    external column without a legend-placement overlap.
    #
    # So place the Flow and Legend as two side-by-side boxes BELOW the diagram
    # body, within the body's horizontal span (so they never become the width
    # driver), leaving the EXTERNAL node captions (right-most, over-measured) to
    # set W. `legend-placement` then reports only `left-of-diagram-body`, which
    # is a WARNING (non-blocking) -- the hard gate is width <= 1600 with zero
    # ERROR/CRITICAL, which this satisfies. The lti `router` lane spreads the SEP
    # body so the externals sit at the far-right column (x~1350), putting W near
    # the no-scale threshold so the magnified caption render still lands < 1600.
    # legend_x/legend_y are furniture offsets, not node coordinates (the node
    # layout is entirely the engine's).
    legend_w = 300
    # Theme 43: aspect-driven Flow/Legend placement. 06 is wide-and-short
    # (aspect ~2.5) -> Mode B: the two boxes sit SIDE-BY-SIDE below the body,
    # right-aligned to the body's right edge (supersedes the earlier hand-rolled
    # vertical stack). Kept below (not right-of) so the flow raster stays under
    # 1600px.
    from rule_engine.diagram_layout import theme43_legend_placement
    legend_x, legend_y_flow, legend_mode, page_w, page_h = theme43_legend_placement(
        nodes, boundaries, FLOW, LEGEND_LINES, legend_w,
    )

    return build_diagram(
        diagram_id="aws-sep-task-verification",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=FLOW,
        legend_x=legend_x,
        legend_y_flow=legend_y_flow,
        legend_w=legend_w,
        legend_lines=LEGEND_LINES,
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

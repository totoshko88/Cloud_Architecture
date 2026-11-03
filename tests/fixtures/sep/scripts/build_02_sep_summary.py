#!/usr/bin/env python3
"""Build the 02-sep-summary triple (.drawio + .diagram.md) via the layout engine.

Coordinate-free: a hand-authored DiagramSpec (the <=12-node container-level SHAPE
of SEP) is handed to layout() + build_diagram(), exactly like draw_cli.build_drawio.
No coordinates are placed by hand.

Collapsing families into representative nodes keeps the summary <=12 nodes:
  - 3 API GW -> 'REST APIs' (management+ui) + 'socket-api' (WebSocket)
  - 13 Lambda -> one 'Lambda core (13 fns)' node
  - 14 SQS -> one 'SQS (14 queues)' node
  - 5 Batch CE -> one 'AWS Batch' node (workspace-local 'batch' role; RE gap)
  - MongoDB Atlas -> EXTERNAL node (on-premises lane, OUTSIDE the account),
    neutral/generic cylinder (no faked AWS icon; RE gap).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from rule_engine.diagram_layout import Edge, ICON_SIZE, Node, CONTAINER_PAD, Skin, build_diagram, image_icon
from rule_engine.icon_resolver import resolve_icon
from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

HERE = Path(__file__).resolve().parent
BASENAME = "02-sep-summary"
TITLE = "aws SEP summary — 870325637521 / eu-central-1 | 2026-10-28 | v7"

# 1.11.0 native skin: light furniture border (#B3B3B3), grey edges (#5A6B7B),
# circle marker badges (#1A1A1A disc + white numeral). Opt-in and byte-inert
# at its defaults; enabled here on all nine triples.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

# --- node declarations (coordinate-free) ---------------------------------- #
# lane order: actors -> edge -> router -> async -> workers -> platform -> data -> on-premises
NODES = (
    NodeSpec(id="client", role="client", lane="actors", region="", slot=0),
    # WAF is GLOBAL/edge (syndicate_education_cloudfront_waf, wafv2 global,
    # attached to CloudFront). It sits in the EDGE lane in front of the REST
    # front door, OUTSIDE any VPC/region boundary (02 draws only the account
    # boundary, so the edge lane is not inside a network boundary).
    NodeSpec(id="waf", role="waf", lane="edge", region="", slot=0),
    NodeSpec(id="rest-apis", role="api_gateway", lane="edge", region="", slot=1),
    NodeSpec(id="socket-api", role="api_gateway", lane="edge", region="", slot=2),
    NodeSpec(id="lambda-core", role="serverless_fn", lane="workers", region="", slot=0),
    NodeSpec(id="sqs", role="message_queue", lane="async", region="", slot=0),
    NodeSpec(id="batch", role="batch", lane="workers", region="", slot=1),
    NodeSpec(id="bedrock", role="llm_platform", lane="platform", region="", slot=0),
    NodeSpec(id="s3", role="object_store", lane="data", region="", slot=0),
    # RDS sep-strapi-pg (Postgres, Multi-AZ) — the AWS managed-SQL datastore.
    # Drawn alongside Atlas so the Atlas-vs-RDS datastore split is visible.
    NodeSpec(id="rds", role="managed_sql", lane="data", region="", slot=1),
    # Atlas is EXTERNAL (non-AWS, over VPC peering): on-premises lane => drawn
    # OUTSIDE the account boundary, neutral generic cylinder.
    # wave-10 B4 (owner: "9 вийде лівіше і піде нижче"): Atlas is nudged down
    # half a row (sub=1) so the Lambda->Atlas edge (e9) runs in a LOWER band than
    # the Lambda->S3 edge (e8); the two fan-out edges then nest instead of
    # crossing (S3 up/inner, Atlas lower/outer). A placement nudge (not an edge
    # reorder — reordering the two fan-out edges made the scored solver search
    # pathologically slow on this spec), so the build stays fast.
    NodeSpec(id="atlas", role="managed_sql", lane="on-premises", region="", slot=0, sub=2),
)

EDGES = (
    EdgeSpec(id="e1", source="client", target="rest-apis", marker="1"),
    EdgeSpec(id="e2", source="client", target="socket-api", marker="2", dashed=True),
    # WAF (CloudFront WAF) inspects/protects the REST front door.
    EdgeSpec(id="e3", source="waf", target="rest-apis", marker="3"),
    EdgeSpec(id="e4", source="rest-apis", target="lambda-core", marker="4"),
    EdgeSpec(id="e5", source="socket-api", target="lambda-core", marker="5"),
    EdgeSpec(id="e6", source="lambda-core", target="sqs", marker="6", dashed=True),
    EdgeSpec(id="e7", source="lambda-core", target="batch", marker="7"),
    EdgeSpec(id="e8", source="lambda-core", target="bedrock", marker="8"),
    EdgeSpec(id="e9", source="lambda-core", target="s3", marker="9"),
    # RDS sep-strapi-pg write path (Postgres managed SQL datastore).
    EdgeSpec(id="e10", source="lambda-core", target="rds", marker="10"),
    EdgeSpec(id="e11", source="lambda-core", target="atlas", marker="11"),
)

CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
)

# Short display labels (<=4 words / <=40 chars for service nodes).
LABELS = {
    "client": "Client",
    "waf": "WAF (CloudFront)",
    "rest-apis": "REST APIs",
    "socket-api": "WebSocket API",
    "lambda-core": "Lambda core (13 fns)",
    "sqs": "SQS (14 queues)",
    "batch": "AWS Batch (5 CE)",
    "bedrock": "Bedrock (Angry EdA)",
    "s3": "S3 (25 buckets)",
    "rds": "RDS sep-strapi-pg",
    "atlas": "Atlas (3 DBs)",
}

FLOW_LINES = (
    "Flow",
    "1. Client to REST APIs",
    "2. Client to WebSocket",
    "3. WAF protects REST edge",
    "4. REST to Lambda",
    "5. WebSocket to Lambda",
    "6. Lambda to SQS (async)",
    "7. Lambda submits Batch",
    "8. Lambda to Bedrock",
    "9. Lambda to S3",
    "10. Lambda to RDS sep-strapi-pg",
    "11. Lambda to Atlas",
)


def _renderer_for(role: str):
    if role == "batch":
        style = resolve_icon("batch", "aws")["style_string"]
    elif role == "managed_sql_generic":
        style = resolve_icon("managed_sql", "generic")["style_string"]
    else:
        style = resolve_icon(role, "aws")["style_string"]
    # Both AWS and generic styles carry image=/shape= + label tokens; image_icon
    # handles the assets/vendor embed. For the generic cylinder (shape=cylinder3)
    # image_icon is wrong — use a raw renderer.
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
        diagram_id="aws-sep-summary",
        diagram_name=BASENAME,
        axis="left-right",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=FLOW_LINES,
        title=TITLE,
        compact=True,
        node_labels=tuple(LABELS.items()),
    )
    # Clarify gate (WS5): read-only scan of the spec's silent defaults. Byte-inert
    # for the .drawio — it only surfaces assumptions for the companion.
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

    # Renderers: AWS roles via resolve_icon; atlas via the MongoDB brand leaf
    # (mongodb_atlas role; keeps NodeSpec role="managed_sql" for scope but
    # renders the real brand-green leaf, not the grey generic cylinder).
    role_of = {n.id: n.role for n in spec.nodes}
    renderers = {}
    for n in spec.nodes:
        key = "mongodb_atlas" if n.id == "atlas" else n.role
        renderers[n.id] = _renderer_for(key)

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

    # Account boundary.
    from rule_engine.diagram_layout import Boundary
    from rule_engine.icon_resolver import resolve_container
    boundaries = []
    acct_style = resolve_container("boundary", "aws")["style_string"]
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
    rights = [b.x + b.w for b in placed.containers.values()]
    rights += [b.x + b.w for b in placed.nodes.values()]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [b.y + b.h for b in placed.containers.values()]
    bottoms += [b.y + b.h for b in placed.nodes.values()]
    page_w = int(max(rights, default=800)) + page_margin
    page_h = int(max(bottoms, default=600)) + page_margin

    # Theme 43: aspect-driven Flow/Legend placement. 02 is a wide-and-short
    # summary (aspect ~3.5) -> Mode B (right-aligned horizontal row below the
    # body), which also pulls the long edge-9 run tighter. legend_w sized to
    # content (Theme 33).
    from rule_engine.diagram_layout import legend_lines_for, theme43_legend_placement
    _legend_lines = legend_lines_for(boundaries)
    legend_w = placed.legend_w
    legend_x, legend_y_flow, legend_mode, page_w, page_h = theme43_legend_placement(
        nodes, boundaries, spec.flow_lines, _legend_lines, legend_w,
    )

    return build_diagram(
        diagram_id="aws-sep-summary",
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
        skin=NATIVE_SKIN,
        # WS2 flow_groups (1.11.0): decorative context boxes behind the members;
        # the engine now classifies flowgroup-* as furniture (not a node), so
        # intra-group edges no longer trip edge-routing. Node coords unchanged.
        flow_groups=(("Edge", ("rest-apis", "socket-api")), ("Workers", ("lambda-core", "batch"))),
    )


if __name__ == "__main__":
    text = build()
    out = HERE.parent / f"{BASENAME}.drawio"
    out.write_text(text, encoding="utf-8")
    print("wrote", out)

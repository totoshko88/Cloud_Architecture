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

from rule_engine.diagram_layout import Edge, ICON_SIZE, Node, CONTAINER_PAD, build_diagram, image_icon
from rule_engine.icon_resolver import resolve_icon
from rule_engine.layout import layout
from rule_engine.layout.model import ContainerSpec, DiagramSpec, EdgeSpec, NodeSpec

HERE = Path(__file__).resolve().parent
BASENAME = "02-sep-summary"
TITLE = "aws SEP summary — 870325637521 / eu-central-1 | 2026-10-15 | v3"

# --- node declarations (coordinate-free) ---------------------------------- #
# lane order: actors -> edge -> router -> async -> workers -> platform -> data -> on-premises
NODES = (
    NodeSpec(id="client", role="client", lane="actors", region="", slot=0),
    NodeSpec(id="rest-apis", role="api_gateway", lane="edge", region="", slot=0),
    NodeSpec(id="socket-api", role="api_gateway", lane="edge", region="", slot=1),
    NodeSpec(id="lambda-core", role="serverless_fn", lane="workers", region="", slot=0),
    NodeSpec(id="sqs", role="message_queue", lane="async", region="", slot=0),
    NodeSpec(id="batch", role="batch", lane="workers", region="", slot=1),
    NodeSpec(id="bedrock", role="llm_platform", lane="platform", region="", slot=0),
    NodeSpec(id="s3", role="object_store", lane="data", region="", slot=0),
    # Atlas is EXTERNAL (non-AWS, over VPC peering): on-premises lane => drawn
    # OUTSIDE the account boundary, neutral generic cylinder.
    NodeSpec(id="atlas", role="managed_sql", lane="on-premises", region="", slot=0),
)

EDGES = (
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

CONTAINERS = (
    ContainerSpec(id="account", kind="account", region="", parent=None, label_key="account"),
)

# Short display labels (<=4 words / <=40 chars for service nodes).
LABELS = {
    "client": "Client",
    "rest-apis": "REST APIs",
    "socket-api": "WebSocket API",
    "lambda-core": "Lambda core (13 fns)",
    "sqs": "SQS (14 queues)",
    "batch": "AWS Batch (5 CE)",
    "bedrock": "Bedrock (Angry EdA)",
    "s3": "S3 (25 buckets)",
    "atlas": "Atlas (3 DBs)",
}

FLOW_LINES = (
    "Flow",
    "1. Client to REST APIs",
    "2. Client to WebSocket",
    "3. REST to Lambda",
    "4. WebSocket to Lambda",
    "5. Lambda to SQS (async)",
    "6. Lambda submits Batch",
    "7. Lambda to Bedrock",
    "8. Lambda to S3",
    "9. Lambda to Atlas",
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
    )


if __name__ == "__main__":
    text = build()
    out = HERE.parent / f"{BASENAME}.drawio"
    out.write_text(text, encoding="utf-8")
    print("wrote", out)

#!/usr/bin/env python3
"""Build the SEP production AWS account AS-BUILT landscape (03-sep-account-landscape).

Coordinate-free: declares a `DiagramSpec` (nodes/edges/containers/flow) and hands
it to the engine's `layout()` + `build_diagram()` pipeline — no hand-placed
geometry. Uses the engine's region > vpc nesting (Account > Region eu-central-1 >
se VPC), so RDS (the one VPC-scoped service) sits inside the VPC and the regional
managed services sit in the Region's regional column, outside the VPC — the
service-scope separation the standards require. External, non-AWS nodes (MongoDB
Atlas + the peered accounts) are neutral grayscale boxes in the external lanes,
so the account envelope never wraps them.

Icons resolve from the WORKSPACE `mappings/aws-icons.yaml` (which carries the
`batch` / `ecr` roles added for this run).

Run from the workspace root:
    python3 scripts/build_sep_account_landscape.py
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
BASENAME = "03-sep-account-landscape"
PROVIDER = "aws"
TITLE = "aws SEP as-built — 870325637521 / eu-central-1 | 2026-10-15 | v3"
SUMMARY_OF = "02-sep-summary"

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Skin: role -> draw.io style, read from the WORKSPACE mappings.
# --------------------------------------------------------------------------- #

_MAP = yaml.safe_load((ROOT / "mappings" / "aws-icons.yaml").read_text(encoding="utf-8"))
# Merge the 1.10.11 per-key workspace-local overlay over the bundled mapping
# (same semantics the engine resolver uses), so roles that live only in the
# overlay resolve here too. The overlay wins per key.
_LOCAL = ROOT / "mappings" / "local" / "aws-icons.yaml"
if _LOCAL.exists():
    _local_map = yaml.safe_load(_LOCAL.read_text(encoding="utf-8")) or {}
    for _k, _v in (_local_map.get("resources") or {}).items():
        _MAP.setdefault("resources", {})[_k] = _v
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
# icon (diagram-standards Icon Fidelity). `cylinder3` / `rounded` tokens are
# declared in generic-icons.yaml, so the verifier resolves them as generic base
# shapes.
NEUTRAL_DB_STYLE = (
    "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "boundedLbl=1;backgroundOutline=1;size=15;"
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=12"
)
NEUTRAL_ACCT_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#333333;dashed=1;"
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


def _n(nid, role, lane, region, slot, caption, kind="aws", sub=0, container=None, overlay=None):
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind}
    return NodeSpec(id=nid, role=role, lane=lane, region=region, slot=slot,
                    sub=sub, container=container, overlay=overlay)


NODES = (
    # --- EXTERNAL, drawn OUTSIDE the account box ---------------------------
    _n("dns", "dns", "actors", "", 0, "Route 53 DNS"),
    _n("cloudfront", "cdn", "actors", "", 1, "CloudFront"),
    _n("atlas", "atlas", "actors", "", 2, "MongoDB Atlas", kind="db"),
    _n("cmtr", "acct", "actors", "", 3, "EPM-CMTR acct", kind="acct"),
    _n("cicd", "acct", "actors", "", 4, "CICD acct", kind="acct"),

    # --- VPC-scoped (inside the VPC) ---------------------------------------
    # RDS is the VPC's banded node; its lane anchors where the region band
    # starts, so keep it in an early lane to pull the whole account band up
    # close under the external edge row (shrinks the diagram height).
    _n("rds", "managed_sql", "async", "a", 2, "RDS sep-strapi-pg",
       container="boundary-vpc-a"),

    # --- Regional services (inside Region, OUTSIDE the VPC) ----------------
    _n("apigw", "api_gateway", "router", "a", 0, "API Gateway",
       container="boundary-region-a"),
    _n("lambda", "serverless_fn", "workers", "a", 0, "Lambda",
       container="boundary-region-a"),
    _n("sqs", "message_queue", "async", "a", 0, "SQS",
       container="boundary-region-a"),
    _n("eventbridge", "eventbridge", "async", "a", 1, "EventBridge",
       container="boundary-region-a"),
    _n("batch", "batch", "workers", "a", 1, "AWS Batch",
       container="boundary-region-a"),
    _n("ecr", "ecr", "workers", "a", 2, "ECR",
       container="boundary-region-a"),
    _n("s3", "object_store", "data", "a", 1, "S3",
       container="boundary-region-a"),
    _n("dynamodb", "dynamodb", "data", "a", 2, "DynamoDB CI locks",
       container="boundary-region-a"),
    _n("ssm", "ssm", "platform", "a", 0, "SSM + KMS",
       container="boundary-region-a"),
    _n("bedrock", "llm_platform", "platform", "a", 1, "Bedrock",
       container="boundary-region-a"),
    _n("cloudwatch", "cloudwatch", "platform", "a", 2, "CloudWatch",
       container="boundary-region-a"),
)

CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None,
                  label_key="account"),
    ContainerSpec(id="boundary-region-a", kind="region", region="a",
                  parent="boundary-account", label_key="region_a"),
    ContainerSpec(id="boundary-vpc-a", kind="vpc", region="a",
                  parent="boundary-region-a", label_key="vpc_a"),
)

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521",
    "boundary-region-a": "Region eu-central-1",
    "boundary-vpc-a": "se vpc-05cd5663a70d3a65c (192.168.128.0/20)",
}

# Edge declaration order follows a depth-first walk from the front door, so the
# engine's regional edge-cost placement (_place_loose_regional) keeps each chain
# together. No node carries more than three edges on one face.
EDGES = (
    EdgeSpec(id="e1", source="dns", target="cloudfront", marker="1"),
    EdgeSpec(id="e2", source="cloudfront", target="apigw", marker="2"),
    EdgeSpec(id="e3", source="apigw", target="lambda", marker="3"),
    EdgeSpec(id="e4", source="lambda", target="sqs", marker="4"),
    EdgeSpec(id="e5", source="sqs", target="batch", marker="5", dashed=True),
    EdgeSpec(id="e6", source="batch", target="ecr", marker="6"),
    EdgeSpec(id="e7", source="ecr", target="cicd", marker="7", dashed=True, kind_hint="cross-region"),
    EdgeSpec(id="e8", source="batch", target="cmtr", marker="8", kind_hint="cross-region"),
    EdgeSpec(id="e9", source="batch", target="s3", marker="9"),
    EdgeSpec(id="e10", source="lambda", target="bedrock", marker="10"),
    EdgeSpec(id="e11", source="lambda", target="atlas", marker="11", kind_hint="cross-region"),
    EdgeSpec(id="e12", source="apigw", target="ssm", marker="12"),
    EdgeSpec(id="e13", source="apigw", target="rds", marker="13"),
    EdgeSpec(id="e14", source="eventbridge", target="batch", marker="14", dashed=True),
    EdgeSpec(id="e15", source="eventbridge", target="cloudwatch", marker="15", dashed=True),
    EdgeSpec(id="e16", source="eventbridge", target="dynamodb", marker="16", dashed=True),
)

FLOW = (
    "Flow",
    "1. Route 53 resolves syndicate.education to CloudFront",
    "2. CloudFront / API clients reach the REST + WebSocket API Gateways",
    "3. API Gateway invokes the SEP Lambda handlers",
    "4. Lambda enqueues work on SQS (activation / notification / enrolments)",
    "5. SQS drives AWS Batch jobs (STM / SRE / KTM / ACE / Voiceover)",
    "6. Batch pulls container images from ECR",
    "7. ECR / CI sync with the CICD account over peering (192.168.254.0/24, acct 884218299410)",
    "8. Batch (SRE/KTM) verifies via EPM-CMTR over peering (192.168.190.0/24, acct 088595288622)",
    "9. Batch writes task artifacts / outputs to S3",
    "10. Lambda calls Bedrock (Angry EdA foundation models)",
    "11. Lambda reads/writes the primary datastore MongoDB Atlas over VPC peering (192.168.246.0/24, acct 781849312837)",
    "12. API Gateway authorizer reads the JWT salt from SSM Parameter Store",
    "13. API / Strapi persist content to RDS sep-strapi-pg (Postgres, VPC-scoped)",
    "14. EventBridge rules + schedules trigger Batch job runs",
    "15. EventBridge monitors job runs via CloudWatch alarms (async)",
    "16. EventBridge/CI uses the DynamoDB Terraform state-lock table",
)

LEGEND_EXTRA = (
    "Nesting: Account > Region > VPC (se 192.168.128.0/20); RDS is VPC-scoped",
    "Regional services sit in the Region, outside the VPC (endpoint access)",
    "Grey box = external, non-AWS (MongoDB Atlas) or a peered AWS account",
    "VPC endpoints: S3 + DynamoDB (gateway), ECR dkr + api (interface); NAT egress for the rest",
)


def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-sep-landscape",
        diagram_name=BASENAME,
        axis="north-south",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=FLOW,
        title=TITLE,
        node_labels=node_labels,
        container_captions=tuple(CONTAINER_CAPTIONS.items()),
    )


def _renderer_for(nid: str):
    meta = NODE_META[nid]
    if meta["kind"] == "db":
        # 1.10.11: MongoDB Atlas renders the real brand-green leaf
        # (mongodb_atlas role, upgraded to a file-path image in the workspace
        # mappings/aws-icons.yaml), not the grey neutral cylinder.
        return _image_renderer("mongodb_atlas")
    if meta["kind"] == "acct":
        # 1.10.11 Theme 34: a peered AWS account renders the real AWS
        # Organizations Account icon (peer_account role), not the grey
        # neutral box. The node stays external (outside the account box) —
        # only the glyph changes.
        return _image_renderer("peer_account")
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
            overlay=n.overlay,
        )
        for n in spec.nodes
        if n.id in placed.nodes
    ]

    boundaries: List[Boundary] = []
    kind_of = {c.id: c.kind for c in spec.containers}
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        style_kind = {"account": "boundary", "region": "region", "vpc": "network_boundary"}[kind_of[c.id]]
        boundaries.append(Boundary(
            id=c.id, label=CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=AWS_CONTAINERS[style_kind], kind=kind_of[c.id],
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

    rights = [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [b.y + b.h for b in boundaries] + [n.y + ICON_SIZE for n in nodes]
    page_w = int(max(rights, default=1600)) + _PAGE_MARGIN
    page_h = int(max(bottoms, default=900)) + _PAGE_MARGIN

    legend_lines = list(legend_lines_for(boundaries)) + list(LEGEND_EXTRA)

    return build_diagram(
        diagram_id="aws-sep-landscape",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=FLOW,
        legend_x=placed.legend_x,
        legend_w=placed.legend_w,
        legend_lines=legend_lines,
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

#!/usr/bin/env python3
"""Build the SEP production AWS account AS-BUILT landscape (03-sep-account-landscape).

HAND-PINNED build (v11), in the exact style of
``.build-tools/build_09_crosscloud_landscape.py`` and
``.build-tools/build_01_sep_context.py``: this script declares EXPLICIT
``Node(x=,y=)`` / ``Boundary(x=,y=,w=,h=)`` / ``Edge(exit=,entry=,points=)``
geometry and calls the shared ``build_diagram(...)`` DIRECTLY, skipping
``layout()``.

Why hand-pinned: the owner's model is "09 = augmented 03", so 03 must read like
a de-densified 09 — a two-column compute spine on the LEFT inside the region and
a compact ``se`` VPC box to the RIGHT of the spine holding the four VPC-scoped
nodes in 09's arrangement (Syndicate Server top-right; ECS strapi + RDS adjacent
on the middle row with the short strapi->RDS write; modular-cli lower-left). The
coordinate-free solver could not place the VPC box right of the spine on this
account without splitting the regional columns and blocking on edge-routing /
container-padding, so (per the project rule "never hand-edit the .drawio, change
the script") the geometry is pinned here, NOT hand-edited in XML — identical in
spirit to how 01/09 are authored.

This is a LAYOUT-ONLY conversion from v10: the node/edge/caption/overlay/
icon-role set and the Flow/Legend text are IDENTICAL to the v10 coordinate-free
spec (16-node SEP account set + WAF/CloudFront/DNS edge lane + MongoDB Atlas /
EPM-CMTR / CICD externals). ONLY the POSITIONS change to the owner's pinned
geometry, snapped to the 10-grid.

Containment is STRUCTURAL: ``build_diagram`` emits each node as a child of the
tightest Boundary that geometrically contains its icon box, so every interior
node is a real structural member of its boundary (clears
``geometric-containment``) — the pinned coordinates place each node fully inside
its intended boundary, and the three externals (edge lane + right column) carry
no container so the account envelope never wraps them.

Icon fidelity: AWS SEP services resolve through ``resolve_icon(role,"aws")``;
the ``ecs`` / ``guardduty`` roles fall back to the bundled engine tree (the
top-level ``mappings/aws-icons.yaml`` lacks them). MongoDB Atlas keeps its brand
glyph (``mongodb_atlas``); the peered accounts render the AWS Organizations
Account glyph (``peer_account``). No engine or ``mappings/`` edit.

Run from the workspace root with the rule-engine tool interpreter:
    python3 .build-tools/build_sep_account_landscape.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

import yaml

from rule_engine.diagram_layout import (
    Boundary,
    CONTAINER_PAD,
    Edge,
    ICON_SIZE,
    Node,
    Skin,
    build_diagram,
    image_icon,
    legend_lines_for,
    overlay_suffix,
)

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "03-sep-account-landscape"
PROVIDER = "aws"
TITLE = "aws SEP as-built — 870325637521 / eu-central-1 | 2026-10-28 | v12"
SUMMARY_OF = "02-sep-summary"

# 1.11.0 native skin (see FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Skin: role -> draw.io style, read from the WORKSPACE mappings (same source the
# v10 coordinate-free script used), with the bundled-tree fallback for roles the
# top-level mapping lacks (ecs / guardduty).
# --------------------------------------------------------------------------- #

_MAP = yaml.safe_load((ROOT / "mappings" / "aws-icons.yaml").read_text(encoding="utf-8"))
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


def _bundled_style(role: str) -> str:
    """Resolve a role's style through the bundled engine tree (the 09 pattern).

    03 uses ECS strapi (role ``ecs``) and GuardDuty (``guardduty``), neither
    present in the workspace top-level ``mappings/aws-icons.yaml`` this script
    reads directly; fall back to the engine resolver so those roles get their
    real official icon with no ``mappings/`` edit."""
    from rule_engine.icon_resolver import resolve_icon

    resolved = resolve_icon(role, PROVIDER)
    return resolved["style_string"] if isinstance(resolved, dict) else resolved


def _style_for(role: str) -> str:
    style = AWS_STYLES.get(role)
    if style is None:
        style = AWS_STYLES[role] = _bundled_style(role)
    return style


def _image_renderer(role: str):
    img = _style_for(role).split("image=", 1)[1]
    return image_icon(img)


# --------------------------------------------------------------------------- #
# Node metadata (role / caption / kind) — IDENTICAL to v10, drives icon choice.
# --------------------------------------------------------------------------- #

NODE_META: Dict[str, Mapping[str, str]] = {}


def _meta(nid: str, role: str, caption: str, kind: str = "aws") -> None:
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind}


# Edge lane (OUTSIDE the account) — WAF global/edge + CloudFront + DNS
_meta("waf", "waf", "WAF (global, CloudFront)")
_meta("cloudfront", "cdn", "CloudFront")
_meta("dns", "dns", "Route 53 DNS")

# Region compute spine (region members): col1 governance/messaging + col2 compute
_meta("eventbridge", "eventbridge", "EventBridge")
_meta("sqs", "message_queue", "SQS")
_meta("cloudwatch", "cloudwatch", "CloudWatch")
_meta("dynamodb", "dynamodb", "DynamoDB CiTerraformStateLocks (Terraform state-lock)")
_meta("ssm", "ssm", "SSM + KMS")
_meta("apigw", "api_gateway", "API Gateway")
_meta("lambda", "serverless_fn", "Lambda")
_meta("batch", "batch", "AWS Batch")
_meta("ecr", "ecr", "ECR")
_meta("s3", "object_store", "S3")
_meta("guardduty", "guardduty", "GuardDuty")
_meta("bedrock", "llm_platform", "Bedrock")

# se VPC interior (VPC members)
_meta("syndicate-server", "compute_instance",
      "Syndicate Server (Education Extension + Syndi)")
_meta("strapi", "ecs", "ECS strapi")
_meta("rds", "managed_sql", "RDS sep-strapi-pg")
_meta("modular-cli", "compute_instance", "modular-cli (admin)")

# External right column (OUTSIDE the account)
_meta("atlas", "atlas", "MongoDB Atlas", kind="db")
_meta("cmtr", "acct", "EPM-CMTR acct", kind="acct")
_meta("cicd", "acct", "CICD acct", kind="acct")


def _renderer_for(nid: str):
    meta = NODE_META[nid]
    kind = meta["kind"]
    if kind == "db":
        # MongoDB Atlas renders the real brand-green leaf (mongodb_atlas role).
        return _image_renderer("mongodb_atlas")
    if kind == "acct":
        # A peered AWS account renders the AWS Organizations Account glyph.
        return _image_renderer("peer_account")
    return _image_renderer(meta["role"])


def _node(nid: str, x: int, y: int, overlay: Optional[str] = None) -> Node:
    return Node(
        id=nid,
        label=NODE_META[nid]["caption"],
        x=x,
        y=y,
        render=_renderer_for(nid),
        overlay=overlay,
    )


# --------------------------------------------------------------------------- #
# Pinned geometry (owner reference, grid-snapped) — absolute coordinates.
# Layout: WAF/CloudFront/DNS edge lane at top (y=120, OUTSIDE the account);
# two-column region compute spine on the LEFT (col1 x=350 governance/messaging,
# col2 x=620 compute); compact se VPC box to the RIGHT of the spine; MongoDB
# Atlas / EPM-CMTR / CICD external right column (x=1340).
# --------------------------------------------------------------------------- #

NODES: List[Node] = [
    # ---- edge lane (OUTSIDE the account) ---------------------------------- #
    # Kept at y=120; the account top (y=410) clears their footprint bottom
    # (icon 198 + 30 label band = 228) by >160px (one row-step), so they are
    # not read as spilled out of the account (container-padding vertical-spill),
    # the same role the ext-ingress box plays on 09.
    _node("waf", 350, 120),
    _node("cloudfront", 570, 120),
    _node("dns", 800, 120),
    # ---- region compute spine (region members) --------------------------- #
    # col1 x=350 — governance / messaging
    _node("eventbridge", 350, 530),
    _node("sqs", 350, 690),
    _node("cloudwatch", 350, 850),
    _node("dynamodb", 350, 1010, overlay="supporting"),
    _node("ssm", 350, 1170),
    # col2 x=620 — compute
    _node("apigw", 620, 530),
    _node("lambda", 620, 690),
    _node("batch", 620, 850),
    _node("ecr", 620, 1010),
    _node("s3", 620, 1170),
    _node("guardduty", 620, 1330, overlay="supporting"),
    # bedrock — below the VPC box, in the gap right of S3
    _node("bedrock", 850, 1330),
    # ---- se VPC interior (VPC members) ------------------------------------ #
    _node("syndicate-server", 1070, 690, overlay="supporting"),
    _node("strapi", 850, 850),
    _node("rds", 1070, 850),
    _node("modular-cli", 850, 1010, overlay="supporting"),
    # ---- external right column (OUTSIDE the account) ---------------------- #
    _node("atlas", 1340, 530),
    _node("cmtr", 1340, 760),
    _node("cicd", 1340, 990),
]

# --------------------------------------------------------------------------- #
# Containers (pinned Boundary cells). Styles come from the AWS container map
# (same source v10/09 use), NOT literal owner style strings, so the
# `container-style` lint rule stays green against the provider profile.
# account->boundary, region->region, vpc->network_boundary.
# --------------------------------------------------------------------------- #

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521",
    "boundary-region-a": "Region eu-central-1",
    "boundary-vpc-a": "se vpc-05cd5663a70d3a65c (192.168.128.0/20)",
}

_CONTAINER_GEOM: Tuple[Tuple[str, str, int, int, int, int], ...] = (
    # id, kind, x, y, w, h
    ("boundary-account", "account", 290, 410, 950, 1090),
    ("boundary-region-a", "region", 320, 470, 890, 1000),
    ("boundary-vpc-a", "vpc", 820, 630, 360, 520),
)

_STYLE_FOR_KIND = {
    "account": "boundary",
    "region": "region",
    "vpc": "network_boundary",
}

BOUNDARIES: List[Boundary] = [
    Boundary(
        id=cid,
        label=CONTAINER_CAPTIONS[cid],
        x=x,
        y=y,
        w=w,
        h=h,
        style=AWS_CONTAINERS[_STYLE_FOR_KIND[kind]],
        kind=kind,
    )
    for (cid, kind, x, y, w, h) in _CONTAINER_GEOM
]

# --------------------------------------------------------------------------- #
# Edges (contract-legal: exit right/bottom, enter left/top). Every edge pins
# both contacts (no float). Waypoints absolute, grid-aligned, each leg axis-
# aligned. Node/edge set and markers IDENTICAL to v10 (18 edges, no e19).
# Coordinate anchors (icon 78px): col1 x=350 (centre 389, right 428); col2
# x=620 (centre 659, right 698); VPC cols x=850 / x=1070; externals left x=1340.
# Row centres: y=120->159, 410->449, 570->609, 730->769, 890->929, 1050->1089,
# 1210->1249.
# --------------------------------------------------------------------------- #

_C = 0.5
_Q = 0.25
_T = 0.75

EDGES: List[Edge] = [
    # --- ingress edge band ------------------------------------------------- #
    # e18 waf->cloudfront: waf(350) left of cloudfront(570), same row — straight
    # horizontal, exit waf right, enter cloudfront left.
    Edge("e18", "waf", "cloudfront", "18", exit=(1.0, _C), entry=(0.0, _C)),
    # e1 dns->cloudfront: dns(800) right of cloudfront(570), same row — a
    # back-edge. Exit dns right, rise above the row, run left, drop into
    # cloudfront's TOP face.
    Edge("e1", "dns", "cloudfront", "1", exit=(1.0, _C), entry=(_C, 0.0),
         points=[(890, 159), (890, 90), (609, 90)]),
    # e2 cloudfront->apigw: drop out of cloudfront bottom, step right into
    # apigw's top (apigw top y=530).
    Edge("e2", "cloudfront", "apigw", "2", exit=(_C, 1.0), entry=(_C, 0.0),
         points=[(609, 360), (659, 360)]),
    # --- SEP internal data-flow ------------------------------------------- #
    # e3 apigw->lambda: lambda directly below apigw — straight vertical drop.
    Edge("e3", "apigw", "lambda", "3", exit=(_C, 1.0), entry=(_C, 0.0)),
    # e13 apigw->rds: rds in the VPC (1070,850). Exit apigw right, run to the
    # x=990 corridor (gap between strapi-right 928 and rds-left 1070), drop, and
    # enter rds's TOP face — avoids piercing strapi on rds's left approach.
    Edge("e13", "apigw", "rds", "13", exit=(1.0, _C), entry=(_C, 0.0),
         points=[(990, 569), (990, 850)]),
    # e4 lambda->sqs: sqs is col1 (left). Exit lambda bottom-left, run left at
    # y=820 (below both rows' label bands), rise at x=320, enter sqs LEFT.
    Edge("e4", "lambda", "sqs", "4", exit=(_Q, 1.0), entry=(0.0, _T),
         points=[(640, 820), (320, 820), (320, 740)]),
    # e5 lambda->batch: batch directly below lambda — straight drop (dashed).
    Edge("e5", "lambda", "batch", "5", dashed=True, exit=(_C, 1.0), entry=(_C, 0.0)),
    # e6 batch->ecr: ecr directly below batch — straight drop.
    Edge("e6", "batch", "ecr", "6", exit=(_C, 1.0), entry=(_C, 0.0)),
    # e9 batch->s3: s3 two rows below batch, same col. Exit batch bottom-left,
    # step to x=590 corridor (left of col2), drop to s3 left.
    Edge("e9", "batch", "s3", "9", exit=(_Q, 1.0), entry=(0.0, _C),
         points=[(640, 940), (590, 940), (590, 1209)]),
    # e8 batch->cmtr (EPM-CMTR external, 1340,760 centre 799). Exit batch right,
    # rise to the y=799 corridor, run right to x=1250, enter cmtr LEFT.
    Edge("e8", "batch", "cmtr", "8", exit=(1.0, _C), entry=(0.0, _C),
         points=[(760, 889), (760, 799), (1250, 799)]),
    # e7 ecr->cicd (CICD external, 1340,990 centre 1029, dashed). Exit ecr
    # right, drop into the x=760 gap and run BELOW the VPC box (y=1200, under VPC
    # bottom 1150) to x=1250, then rise into cicd's LEFT face — clears modular-
    # cli and the VPC interior.
    Edge("e7", "ecr", "cicd", "7", dashed=True, exit=(1.0, _C), entry=(0.0, _C),
         points=[(760, 1049), (760, 1200), (1250, 1200), (1250, 1029)]),
    # e10 lambda->bedrock (850,1330 centre 889). Exit lambda right lower band,
    # drop in the x=770 corridor to y=1300, step right into bedrock top. (Kept at
    # x=770: the only grid lanes that clear e7's x=760 collinear band sit at or
    # past x=790, which clips strapi's wide ECS caption — a new edge-crosses-label
    # defect — so the right-side e10/e7/e8 collinear, which the owner did NOT name,
    # is left pre-existing rather than traded for a caption clip. See
    # DIAGRAM-ENGINE-FEEDBACK-1.13.0.md.)
    Edge("e10", "lambda", "bedrock", "10", exit=(1.0, _T), entry=(_C, 0.0),
         points=[(770, 740), (770, 1300), (889, 1300)]),
    # e11 lambda->atlas (1340,530 centre 569). Exit lambda right upper band,
    # rise to the y=569 corridor, run right to x=1250, enter atlas LEFT.
    Edge("e11", "lambda", "atlas", "11", exit=(1.0, _Q), entry=(0.0, _C),
         points=[(730, 710), (730, 569), (1250, 569)]),
    # e12 apigw->ssm: ssm col1 bottom (350,1170). Exit apigw bottom-left, run
    # left at y=660 (below apigw bottom 608, above lambda top 690) to x=300
    # (left of col1), drop, enter ssm LEFT — clears the lambda icon.
    Edge("e12", "apigw", "ssm", "12", exit=(_Q, 1.0), entry=(0.0, _C),
         points=[(640, 660), (300, 660), (300, 1209)]),
    # e14 eventbridge->batch: exit eventbridge right, drop in the x=530 gap
    # corridor, enter batch LEFT (dashed).
    Edge("e14", "eventbridge", "batch", "14", dashed=True, exit=(1.0, _C), entry=(0.0, _C),
         points=[(530, 569), (530, 889)]),
    # e15 eventbridge->cloudwatch: cloudwatch below eventbridge past sqs in the
    # same col. Route via the x=330 corridor (its OWN lane, 3 steps off e12's
    # x=300, between region-left 320 and col1-left 350 — clears sqs's icon left
    # edge at 350) to avoid piercing sqs; run the short jog at y=630 (2 steps off
    # e16's y=610 so the two are no longer collinear) (dashed).
    Edge("e15", "eventbridge", "cloudwatch", "15", dashed=True, exit=(_Q, 1.0), entry=(_C, 0.0),
         points=[(370, 630), (330, 630), (330, 830), (389, 830)]),
    # e16 eventbridge->dynamodb: dynamodb two rows below eventbridge past
    # sqs+cloudwatch. Route in the x=460 corridor (right of col1 icons) (dashed).
    Edge("e16", "eventbridge", "dynamodb", "16", dashed=True, exit=(_T, 1.0), entry=(_C, 0.0),
         points=[(420, 610), (460, 610), (460, 1000), (389, 1000)]),
    # e17 strapi->rds: strapi(850) and rds(1070) same VPC row — straight
    # adjacent write, exit strapi right, enter rds left.
    Edge("e17", "strapi", "rds", "17", exit=(1.0, _C), entry=(0.0, _C)),
    # (no e19: Syndicate Server->SQS stays undrawn; the node is supporting and
    #  Flow step 19 carries "(not drawn)". The edge is drawn in 09.)
]

# --------------------------------------------------------------------------- #
# Flow / Legend (carried over VERBATIM from v10).
# --------------------------------------------------------------------------- #

FLOW = (
    "Flow",
    "1. Route 53 resolves syndicate.education to CloudFront",
    "2. CloudFront fronts ONLY the REST API se-ui-api (7cipwpsrx5); other API Gateways are reached directly, not via CloudFront",
    "3. API Gateway invokes the SEP Lambda handlers",
    "4. Lambda enqueues work on SQS (activation / notification / enrolments)",
    "5. Lambda submits AWS Batch jobs directly (STM / SRE / KTM / ACE / Voiceover); Batch uses its own built-in job queue",
    "6. Batch pulls container images from ECR",
    "7. ECR / CI sync with the CICD account over peering (192.168.254.0/24, acct 884218299410)",
    "8. Batch (SRE/KTM) verifies via EPM-CMTR over peering (192.168.190.0/24, acct 088595288622)",
    "9. Batch writes task artifacts / outputs to S3",
    "10. Lambda calls Bedrock (Angry EdA foundation models)",
    "11. Lambda reads/writes the primary datastore MongoDB Atlas over VPC peering (192.168.246.0/24, acct 781849312837)",
    "12. API Gateway authorizer reads the JWT salt from SSM Parameter Store",
    "13. API / Strapi persist content to RDS sep-strapi-pg (Postgres, VPC-scoped)",
    "14. EventBridge rules + schedules trigger Batch job runs — ONLY for schedulable ACE jobs",
    "15. EventBridge monitors job runs via CloudWatch alarms (async)",
    "16. DynamoDB table CiTerraformStateLocks is the CI/Terraform state-lock (not governance)",
    "17. ECS strapi persists Strapi content to RDS sep-strapi-pg (VPC-scoped)",
    "18. CloudFront is protected by WAF syndicate_education_cloudfront_waf (wafv2, global)",
    "19. Syndicate Server (Education Extension + Syndi) consumes the SEP SQS lifecycle queues — supporting node, drawn in 09 (not drawn)",
)

LEGEND_EXTRA = (
    "Nesting: Account > Region > VPC (se 192.168.128.0/20); RDS is VPC-scoped",
    "Regional services sit in the Region, outside the VPC (endpoint access)",
    "Grey box = external, non-AWS (MongoDB Atlas) or a peered AWS account",
    "VPC endpoints: S3 + DynamoDB (gateway), ECR dkr + api (interface); NAT egress for the rest",
    "Dotted outline = supporting service (GuardDuty, modular-cli admin host, Syndicate Server control plane): not a data-flow step",
    "WAF (global) attaches to CloudFront at the edge, outside the eu-central-1 region/VPC",
    "AWS X-Ray tracing + AWS Config recorder are enabled (not drawn as nodes)",
)


def _build() -> str:
    # Right-margin Flow/Legend, past the right-most external node (atlas/cmtr/
    # cicd right edge = 1340+78 = 1418); the legend clears it by one pad. Sized
    # to content width (>=340) and height from the wrapped FLOW line count so the
    # column stacks tight at the top with no bottom dead space.
    legend_w = 340
    body_right = max(
        [b.x + b.w for b in BOUNDARIES] + [n.x + ICON_SIZE for n in NODES]
    )
    legend_x = int(body_right) + CONTAINER_PAD

    rights = [b.x + b.w for b in BOUNDARIES] + [n.x + ICON_SIZE for n in NODES]
    rights.append(legend_x + legend_w)
    bottoms = [b.y + b.h for b in BOUNDARIES] + [n.y + ICON_SIZE for n in NODES]
    page_w = int(max(rights)) + _PAGE_MARGIN
    page_h = int(max(bottoms)) + _PAGE_MARGIN

    legend_lines = list(legend_lines_for(BOUNDARIES)) + list(LEGEND_EXTRA)

    _CHARS_PER_LINE = max(10, (legend_w - 20) // 6)

    def _visual_lines(lines) -> int:
        n = 0
        for ln in lines:
            n += max(1, -(-len(ln) // _CHARS_PER_LINE))
        return n

    legend_y_flow = 60
    _flow_h = _visual_lines(FLOW) * 16 + 24
    legend_y_legend = legend_y_flow + _flow_h + 20

    return build_diagram(
        diagram_id="aws-sep-landscape",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=BOUNDARIES,
        nodes=NODES,
        edges=EDGES,
        flow_lines=FLOW,
        legend_x=legend_x,
        legend_y_flow=legend_y_flow,
        legend_y_legend=legend_y_legend,
        legend_w=legend_w,
        legend_lines=legend_lines,
        page_w=page_w,
        page_h=page_h,
        skin=NATIVE_SKIN,
        flow_steps="document",
    )


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}, {len(NODES)} nodes, {len(EDGES)} edges, {len(BOUNDARIES)} boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

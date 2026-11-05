#!/usr/bin/env python3
"""Build the SEP CROSS-CLOUD "everything" landscape (09-crosscloud-landscape).

HAND-PINNED build (v21), in the exact style of
``.build-tools/build_01_sep_context.py``: this script declares EXPLICIT
``Node(x=,y=)`` / ``Boundary(x=,y=,w=,h=)`` / ``Edge(exit=,entry=,points=)``
geometry — the owner's manual VPC layout (09-crosscloud-landscape копія) — and
calls the shared ``build_diagram(...)`` DIRECTLY, skipping ``layout()``.

Why hand-pinned (see DIAGRAM-ENGINE-FEEDBACK-1.13.0.md): the owner's reference
draws the ``se`` VPC box to the RIGHT of the compute spine with the Syndicate
Server at its top-right so the server's four external edges exit right/up to the
external bands. The coordinate-free solver cannot reproduce that on this dense
cross-cloud canvas (it places the VPC box left/low or splits the regional
columns on ``vpc_side="right"``, so the external edges rake up across the
account and the build BLOCKS with edge-routing / container-padding /
edge-crossing-excess ERRORs). Per the project rule "never hand-edit the
``.drawio``, change the script" this is a Python script with pinned geometry,
NOT a hand-edited XML — identical in spirit to how 01/02/04/07 are authored.

Node/edge/caption/icon set is IDENTICAL to the v20 coordinate-free spec
(16-node SEP account set + 13 external-band nodes + the WAF edge/global). ONLY
the POSITIONS change to the owner's pinned geometry
(.agents/tasks/09-owner-geometry.txt), snapped to the 10-grid.

Containment is STRUCTURAL: ``build_diagram`` emits each node as a child of the
tightest Boundary that geometrically contains its icon box
(``_node_membership``), so every interior node is a real structural member of
its boundary (clears ``geometric-containment``) — the pinned coordinates place
each node fully inside its intended boundary.

Icon fidelity: AWS SEP services resolve through ``resolve_icon(role,"aws")``;
the ``ecs`` / ``guardduty`` roles fall back to the bundled engine tree (the
top-level ``mappings/aws-icons.yaml`` lacks them). Non-AWS clouds / brands keep
their own glyph (mongodb_atlas, keycloak, dial, education, organizations,
sandbox_multicloud, license_neutral). No engine or ``mappings/`` edit.

Run from the workspace root with the rule-engine tool interpreter:
    python3 .build-tools/build_09_crosscloud_landscape.py
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
BASENAME = "09-crosscloud-landscape"
PROVIDER = "aws"
TITLE = "aws SEP cross-cloud — multi-account / eu-central-1 | 2026-10-28 | v21"

# 1.11.0 native skin (see FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Skin: role -> draw.io style, read from the WORKSPACE mappings (same source the
# v20 coordinate-free script used), with the bundled-tree fallback for roles the
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
    """Resolve a role's style through the bundled engine tree (the 03/08/13
    pattern). 09 uses ECS strapi (role ``ecs``) and GuardDuty (``guardduty``),
    neither present in the workspace top-level ``mappings/aws-icons.yaml`` this
    script reads directly; fall back to the engine resolver so those roles get
    their real official icon with no ``mappings/`` edit."""
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
# Node metadata (role / caption / kind) — IDENTICAL to v20, drives icon choice.
# --------------------------------------------------------------------------- #

NODE_META: Dict[str, Mapping[str, str]] = {}


def _meta(nid: str, role: str, caption: str, kind: str = "aws") -> None:
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind}


# External-band children (OUTSIDE the SEP account; each a member of its ext box)
_meta("actorsbox", "user", "Students / Operators", kind="aws")
_meta("cloudfront", "cdn", "CloudFront (4 dist)")
_meta("waf", "waf", "WAF cloudfront-waf (global)")
_meta("dns", "dns", "Route 53 (323549576358)")
_meta("atlas", "atlas", "MongoDB Atlas (3 DBs)", kind="db")
_meta("edkrsb-eks", "managed_k8s", "EKS cluster")
_meta("keycloak", "keycloak", "Keycloak SSO", kind="keycloak")
_meta("lms", "education", "LMS learn.epam.com", kind="edu")
_meta("lm", "license_neutral", "License Mgr (652063929809)", kind="licneutral")
_meta("dial", "dial", "DIAL AI (ai-proxy.lab.epam)", kind="dial")
_meta("sbmgmt", "organizations", "Sandbox-mgmt + Logging org", kind="org")
_meta("nuke", "batch", "Nuke fleet (aws/azure/gcp)", kind="aws")
_meta("sbfleets", "sandbox_multicloud", "Sandbox fleets (3 clouds)", kind="multicloud")

# SEP compute spine (region members: col1 x=350, col2 x=620) + bedrock
_meta("apigw", "api_gateway", "API Gateway (5 APIs)")
_meta("eventbridge", "eventbridge", "EventBridge (5 rules)")
_meta("sqs", "message_queue", "SQS (14 queues)")
_meta("lambda", "serverless_fn", "Lambda (13 fns)")
_meta("cloudwatch", "cloudwatch", "CloudWatch")
_meta("batch", "batch", "AWS Batch (5 CE)")
_meta("dynamodb", "dynamodb", "DynamoDB (CI locks)")
_meta("ecr", "ecr", "ECR (5 repos)")
_meta("ssm", "ssm", "SSM + KMS")
_meta("s3", "object_store", "S3 (25 buckets)")
_meta("guardduty", "guardduty", "GuardDuty")
_meta("bedrock", "llm_platform", "Bedrock (Angry EdA)")

# se VPC interior (VPC members)
_meta("syndicate-server", "compute_instance",
      "Syndicate Server (Education Extension + Syndi)", kind="ec2")
_meta("strapi", "ecs", "ECS strapi")
_meta("rds", "managed_sql", "RDS sep-strapi-pg")
_meta("modular-cli", "compute_instance", "modular-cli (admin)")


def _renderer_for(nid: str):
    meta = NODE_META[nid]
    kind = meta["kind"]
    if kind == "db":
        return _image_renderer("mongodb_atlas")
    if kind == "keycloak":
        return _image_renderer("keycloak")
    if kind == "ec2":
        return _image_renderer("compute_instance")
    if kind == "licneutral":
        return _image_renderer("license_neutral")
    if kind == "multicloud":
        return _image_renderer("sandbox_multicloud")
    if kind == "edu":
        return _image_renderer("education")
    if kind == "dial":
        return _image_renderer("dial")
    if kind == "org":
        return _image_renderer("organizations")
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
# --------------------------------------------------------------------------- #

NODES: List[Node] = [
    # ---- external bands (OUTSIDE the account) ----------------------------- #
    _node("actorsbox", 130, 120),
    _node("cloudfront", 350, 120),
    _node("waf", 570, 120),
    _node("dns", 800, 120),
    _node("atlas", 1340, 350),
    _node("lm", 1340, 580),
    _node("dial", 1560, 580),
    _node("sbmgmt", 1340, 810),
    _node("nuke", 1560, 810),
    _node("sbfleets", 1780, 810),
    _node("edkrsb-eks", 1340, 1030),
    _node("keycloak", 1340, 1260),
    _node("lms", 1560, 1260),
    # ---- SEP compute spine (region members) ------------------------------- #
    # col1 x=350
    _node("eventbridge", 350, 410),
    _node("sqs", 350, 570),
    _node("cloudwatch", 350, 730),
    _node("dynamodb", 350, 890, overlay="supporting"),
    _node("ssm", 350, 1050),
    # col2 x=620
    _node("apigw", 620, 410),
    _node("lambda", 620, 570),
    _node("batch", 620, 730),
    _node("ecr", 620, 890),
    _node("s3", 620, 1050),
    _node("guardduty", 620, 1210, overlay="supporting"),
    # bedrock
    _node("bedrock", 850, 1210),
    # ---- se VPC interior (VPC members) ------------------------------------ #
    _node("syndicate-server", 1070, 570),
    _node("strapi", 850, 730),
    _node("rds", 1070, 730),
    _node("modular-cli", 850, 890, overlay="supporting"),
]

# --------------------------------------------------------------------------- #
# Containers (pinned Boundary cells). Styles come from the AWS container map
# (same source v20/03 use), NOT the owner's literal style strings, so the
# `container-style` lint rule stays green against the provider profile.
# region->region, vpc->network_boundary, ext boxes->on_premises (neutral).
# --------------------------------------------------------------------------- #

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521",
    "boundary-region-a": "Region eu-central-1",
    "boundary-vpc-a": "se vpc-05cd5663a70d3a65c (192.168.128.0/20)",
    "ext-ingress": "Ingress & identity edge",
    "ext-datastore": "External datastore — MongoDB Atlas",
    "ext-integrations": "External integrations (DIAL / License)",
    "ext-sandbox": "Sandbox management (cleanup fleet)",
    "ext-peeracct": "ED-KRSB (183631338639)",
    "ext-identity": "Identity (LMS / Keycloak)",
}

_CONTAINER_GEOM: Tuple[Tuple[str, str, int, int, int, int], ...] = (
    # id, kind, x, y, w, h
    ("boundary-account", "account", 30, 290, 1180, 1108),
    ("boundary-region-a", "region", 60, 360, 1130, 1010),
    ("boundary-vpc-a", "vpc", 820, 520, 360, 510),
    ("ext-ingress", "peer_account", 30, 60, 940, 198),
    ("ext-datastore", "peer_account", 1240, 290, 290, 198),
    ("ext-integrations", "peer_account", 1240, 520, 500, 198),
    ("ext-sandbox", "peer_account", 1240, 750, 720, 198),
    ("ext-peeracct", "peer_account", 1240, 970, 280, 198),
    ("ext-identity", "peer_account", 1240, 1200, 500, 198),
)

_STYLE_FOR_KIND = {
    "account": "boundary",
    "region": "region",
    "vpc": "network_boundary",
    "peer_account": "on_premises",
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
# Edges (owner exit/entry + points; off-grid exits filled contract-legal).
# exit right/bottom, enter left/top. Every edge pins both contacts (no float).
# --------------------------------------------------------------------------- #

_X = 1.0256410256410255   # owner right-face perimeter-nudge
_B = 1.0256410256410255   # owner bottom-face perimeter-nudge
_C = 0.5128205128205128   # owner centre
_Q = 0.2564102564102564   # owner quarter (upper/left band)
_T = 0.7692307692307693   # owner three-quarter (lower/right band)

EDGES: List[Edge] = [
    # --- ingress edge band ------------------------------------------------- #
    Edge("e1", "actorsbox", "cloudfront", "1", exit=(_X, _C), entry=(0.0, _C)),
    Edge("e2", "cloudfront", "apigw", "2", exit=(_X, _C), entry=(_C, 0.0),
         points=[(460, 160), (460, 380), (660, 380)]),
    Edge("e3", "dns", "cloudfront", "3", dashed=True, exit=(_X, _C), entry=(0.0, _Q),
         points=[(910, 160), (910, 100), (280, 100), (280, 140)]),
    Edge("e28", "waf", "cloudfront", "4", dashed=True, exit=(_X, _C), entry=(0.0, _T),
         points=[(680, 160), (680, 240), (280, 240), (280, 180)]),
    Edge("e4", "keycloak", "lms", "5", dashed=True, exit=(_X, _C), entry=(0.0, _C)),
    # --- SEP internal data-flow ------------------------------------------- #
    Edge("e5", "apigw", "lambda", "6", exit=(_C, _B), entry=(_C, 0.0)),
    # e6 lambda->sqs: owner exit=?; target (sqs) is LEFT of lambda, so exit
    # lambda bottom-left; the owner point route 640->320->up arrives at sqs from
    # the lower-left, so enter sqs's LEFT face (final leg 320->350 horizontal at
    # y=630, entryY=(630-570)/78=0.77).
    Edge("e6", "lambda", "sqs", "7", dashed=True, exit=(_Q, _B), entry=(0.0, _T),
         points=[(640, 700), (320, 700), (320, 630)]),
    Edge("e7", "lambda", "batch", "8", dashed=True, exit=(_C, _B), entry=(_C, 0.0)),
    Edge("e8", "batch", "ecr", "9", exit=(_C, _B), entry=(_C, 0.0)),
    Edge("e9", "eventbridge", "batch", "10", dashed=True, exit=(1.0, _C), entry=(0.0, _C),
         points=[(530, 450), (530, 770)]),
    # e10 lambda->bedrock: owner exit=?; owner first point (770,630) is right of
    # lambda (right edge 698) and slightly above its bottom, so exit lambda's
    # RIGHT face (lower band _T) and drop at x=770 to bedrock's top. Keeps the
    # lambda bottom face clear of e7 (bottom-centre) -> distinct exits.
    Edge("e10", "lambda", "bedrock", "11", exit=(_X, _T), entry=(_C, 0.0),
         points=[(770, 630), (770, 1160), (890, 1160)]),
    Edge("e11", "batch", "s3", "12", exit=(_Q, _B), entry=(0.0, _C),
         points=[(640, 820), (570, 820), (570, 1090)]),
    # e12 lambda->rds: owner exit=?; owner route 990->down to rds top (snapped
    # 772->770). Exit lambda right, enter rds left.
    Edge("e12", "lambda", "rds", "13", exit=(_X, _C), entry=(0.0, _C),
         points=[(990, 610), (990, 770)]),
    Edge("e29", "strapi", "rds", "27", exit=(_X, _T), entry=(0.0, _T)),
    Edge("e13", "sqs", "cloudwatch", "14", dashed=True, exit=(_C, _B), entry=(_C, 0.0)),
    Edge("e14", "cloudwatch", "dynamodb", "15", dashed=True, exit=(_C, _B), entry=(_C, 0.0)),
    Edge("e15", "dynamodb", "ssm", "16", dashed=True, exit=(_C, _B), entry=(_C, 0.0)),
    # --- external integrations (SEP core -> external) --------------------- #
    Edge("e16", "lambda", "atlas", "17", exit=(0.964, 0.257), entry=(0.0, _C),
         points=[(970, 590), (970, 390)]),
    Edge("e27", "syndicate-server", "atlas", "18", dashed=True, exit=(_X, _Q), entry=(0.0, _T),
         points=[(1200, 590), (1200, 410)]),
    Edge("e17", "batch", "edkrsb-eks", "19", dashed=True, exit=(_X, _C), entry=(0.0, _C),
         points=[(730, 770), (730, 1070)]),
    Edge("e20", "syndicate-server", "dial", "20", exit=(_X, _C), entry=(_C, 0.0),
         points=[(1280, 610), (1280, 550), (1600, 550)]),
    # e21 lm->sqs: owner entry=?; owner route ends 280->590 (horizontal arrival
    # at y~590 left of sqs x=350), so enter sqs LEFT.
    Edge("e21", "lm", "sqs", "21", dashed=True, exit=(_X, _C), entry=(0.0, _C),
         points=[(1450, 620), (1450, 500), (280, 500), (280, 590)]),
    # --- sandbox-management context --------------------------------------- #
    Edge("e22", "sbmgmt", "nuke", "22", exit=(_X, _C), entry=(0.0, _C)),
    Edge("e23", "nuke", "sbfleets", "23", dashed=True, exit=(_X, _C), entry=(0.0, _C)),
    # e24 syndicate-server->sbfleets: owner entry=?; owner route runs 1090->1820
    # at y=700 (ABOVE sbfleets at y=810) then down into sbfleets. Enter sbfleets'
    # TOP face so it stays distinct from e23 (nuke->sbfleets, LEFT face) — two
    # arrivals on sbfleets' left face merge (entry-thirds).
    Edge("e24", "syndicate-server", "sbfleets", "24", exit=(_Q, _B), entry=(_C, 0.0),
         points=[(1090, 700), (1820, 700)]),
    Edge("e25", "syndicate-server", "sbmgmt", "25", dashed=True, exit=(_X, _T), entry=(0.0, _C),
         points=[(1310, 630), (1310, 850)]),
    Edge("e26", "sqs", "syndicate-server", "26", dashed=True, exit=(_X, _C), entry=(0.0, _C),
         points=[(460, 610), (460, 550), (1010, 550), (1010, 610)]),
]

# --------------------------------------------------------------------------- #
# Flow / Legend (verbatim from v20).
# --------------------------------------------------------------------------- #

FLOW = (
    "Flow",
    "Ingress & identity (1-5)",
    "1. Students / Operators reach syndicate.education via CloudFront (4 distributions)",
    "2. CloudFront fronts ONLY the REST API se-ui-api (7cipwpsrx5); the other 4 API Gateways are not behind CloudFront",
    "3. Route 53 (acct 323549576358) resolves syndicate.education to CloudFront",
    "4. AWS WAF web ACL syndicate_education_cloudfront_waf (global / us-east-1) protects the CloudFront distribution",
    "5. Keycloak SSO federates identity; LMS (learn.epam.com) launches tasks via LTI to the REST API",
    "SEP internal data-flow (6-16)",
    "6. API Gateway invokes the SEP Lambda handlers (13 functions)",
    "7. Lambda enqueues work on SQS (14 queues) — async",
    "8. Lambda submits AWS Batch jobs directly (STM / SRE / KTM / ACE / Voiceover, 5 CE); Batch uses its own built-in job queue",
    "9. Batch pulls container images from ECR (5 repos)",
    "10. EventBridge rules + schedules trigger Batch runs — ONLY for ACE jobs that can be scheduled (not all Batch)",
    "11. Lambda calls Bedrock foundation models (Angry EdA)",
    "12. Lambda / Batch write task artifacts / outputs to S3 (25 buckets)",
    "13. Lambda / Strapi persist content to RDS sep-strapi-pg (VPC-scoped)",
    "14. Batch / SQS run metrics flow to CloudWatch alarms (async)",
    "15. DynamoDB table CiTerraformStateLocks is the CI/Terraform state-lock (not a CloudWatch/EventBridge governance store)",
    "16. SSM Parameter Store + KMS hold the JWT salt / SSO secret for the authorizer",
    "External integrations (17-21)",
    "17. Lambda reads/writes MongoDB Atlas over peering pcx-0e257b23d337fda0b (781849312837, .246.0/24)",
    "18. EC2 syndicate-server reads/writes the PRIMARY learner data in MongoDB Atlas (PROD_SEP_Server) over peering pcx-0e257b23d337fda0b",
    "19. KTM AWS Batch reaches the EKS student cluster development-dev over the PUBLIC endpoint (ED-KRSB 183631338639)",
    "20. Syndicate Server (Syndi), inside the SEP account, calls the EPAM DIAL AI proxy ai-proxy.lab.epam.com",
    "21. License Manager (652063929809) -> SQS se-lm-synchronization-queue -> se-management-api-handler Lambda (ESM 5fe731e5)",
    "Sandbox-management context (22-26)",
    "22. Sandbox-mgmt org (533267139808) runs the nuke fleet on AWS Batch (eu-west-1); org members forward events to central Logging (650251687330) EventBridge to SQS FIFO",
    "23. Nuke fleet = AWS Batch cleanup of sandbox accounts, driven by the Syndicate Server Education Extension (EE); SEP + Batch verify — purges AWS (222 accts) / Azure (202 subs) / GCP (org 1090110766254)",
    "24. Syndicate Server provisions resources in the sandbox fleet — reads the SEP SQS lifecycle queues to create sandbox resources (AWS / Azure / GCP)",
    "25. Syndicate Server drives the FULL sandbox account lifecycle (provision + cleanup) via the Sandbox-mgmt org",
    "26. Syndicate Server (Syndi) consumes the SEP SQS lifecycle queues (local — inside the SEP account, no peering)",
    "SEP internal data-flow cont. (27)",
    "27. ECS strapi persists Strapi content to RDS sep-strapi-pg (VPC-scoped, intra-VPC)",
)

LEGEND_EXTRA = (
    "Nesting: Account(870325637521) > Region(eu-central-1) > se VPC; RDS is VPC-scoped",
    "Regional services sit in the Region, outside the VPC (endpoint / NAT access)",
    "Grey box = external non-AWS cloud or a whole-fleet abstraction (no faithful glyph)",
    "Service/brand icons name real resources (Syndicate Server EC2 inside SEP, peer-account + Organizations org glyph, DIAL brand, LMS mortarboard)",
    "Syndicate Server (EC2 in SEP acct 870325637521) is the control plane — drives the full sandbox account lifecycle (provision + cleanup)",
    "Neutral license glyph = EPAM License Manager (NOT an AWS service); cloud-with-3-marks = sandbox fleets across AWS / Azure / GCP",
    "AWS WAF web ACL syndicate_education_cloudfront_waf is GLOBAL/edge — it protects CloudFront, never inside the eu-central-1 VPC/region",
    "Nuke fleet = AWS Batch cleanup of sandbox accounts, driven by the Syndicate Server Education Extension (EE); SEP + Batch verify",
    "Sandbox management (cleanup fleet) = CONTEXT, OUT of WAFR scope",
    "Sandbox management is a SEPARATE AWS Organization o-j09uu9d646 (mgmt acct 533267139808, 223 accounts) — distinct from the SEP org o-zizyhj5jga",
    "Dotted ring (supporting) = ops / non-dataflow node: DynamoDB CiTerraformStateLocks (CI/Terraform state-lock), modular-cli (admin host), GuardDuty (1 detector)",
    "draft-assumption (NOTE, 9B Q1) = LM to sync queue proven; the onward CMTR relay path (LM -> Syndicate Server -> SEP) is still open",
)


def _build() -> str:
    # Right-margin Flow/Legend, past the right-most external band (ext-sandbox
    # right edge = 1240+720 = 1960); the legend clears it by one pad. Sized to
    # content width (>=340) and height from the wrapped FLOW line count so the
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
        diagram_id="aws-sep-crosscloud",
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

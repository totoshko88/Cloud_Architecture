#!/usr/bin/env python3
"""Build the SEP CROSS-CLOUD "everything" landscape (09-crosscloud-landscape).

The capstone as-built: the whole SEP world on one wall. Coordinate-free — a
`DiagramSpec` (nodes/edges/containers/flow) handed to the engine's
`layout()` + `build_diagram()` pipeline, no hand-placed geometry.

Structure (North-South bands):
  * `actors` lane  (top, OUTSIDE every account): external actors + global edge
    (Student / Operator / LMS / Keycloak, CloudFront, Route 53 DNS acct).
  * SEP core: the one REAL nested boundary Account(870325637521) > Region
    (eu-central-1) > se VPC. Grouped family nodes (counts in the Flow legend +
    companion), reusing the 03 naming. RDS is the single VPC-scoped node.
  * `on-premises` lane  (bottom, OUTSIDE the SEP account):
      - sub=0  external SEP integrations (Atlas, EPM-CMTR CMTM/SRE/EKS, ED-KRSB
        EKS, License Manager, Syndicate Server, DIAL AI, CICD acct).
      - sub=1  the SANDBOX-MANAGEMENT context band (cleanup fleet — OUT of WAFR
        scope, shown as context): nuke fleet, central Logging, and the three
        sandbox fleets it purges (AWS 222 accts, Azure 202 subs, GCP org).

Icon fidelity: AWS SEP services resolve from the WORKSPACE mappings/aws-icons.yaml.
Every non-AWS cloud, external AWS peer account, EC2-based external, and
whole-fleet abstraction is a NEUTRAL grayscale box — never a faked service icon.

Run from the workspace root with the rule-engine tool interpreter:
    python3 scripts/build_09_crosscloud_landscape.py
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
BASENAME = "09-crosscloud-landscape"
PROVIDER = "aws"
TITLE = "aws SEP cross-cloud — multi-account / eu-central-1 | 2026-10-17 | v6"
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

# Neutral (non-AWS) styles for external nodes — grayscale boxes, NOT fake AWS
# icons (diagram-standards Icon Fidelity). `db` = external managed database
# (MongoDB Atlas) as a cylinder; `acct` = an external AWS peer account / an
# EC2-based external system / a whole sandbox fleet abstraction, as a dashed
# grey box labelled with the system + its count.
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


# Design note (why one external ROW, not stacked bands):
#   The layout engine lays external-lane nodes (actors / on-premises) as a single
#   horizontal row; `sub` shifts within a row but does not stack reliable second
#   rows, and the `on-premises` lane lands mid-account (overlap) when the account
#   band is tall. The `actors` lane is the one lane that reliably sits ABOVE the
#   whole account. So the WHOLE external world is declared in `actors` as one
#   wide row (landscape budget allows a wide 3600px canvas), ORDERED left->right
#   so each external sits roughly above the SEP account column it connects to —
#   this keeps the downward cross-band edges near-vertical and the crossing count
#   under the landscape hard cap. The SEP account hangs below as the one nested
#   core. The "bands" (edge / integrations / sandbox context) are expressed by
#   LEFT->RIGHT grouping + the Legend + the companion, not by stacked rows.
NODES = (
    # ===================================================================== #
    # EXTERNAL WORLD — one row in `actors`, ABOVE the SEP account.
    # Order is chosen so each external that CONNECTS to the account sits as
    # close as possible ABOVE its hub column (account hubs span ~x 400..840),
    # which keeps every cross-band edge a short, near-vertical drop. The
    # self-contained SANDBOX-management band is pushed to the right so its
    # internal fan never crosses the integration edges.
    # ---- ingress + integrations, ORDERED to sit above their hub columns ---
    # Account hubs land at x ~ apigw/sqs 620, lambda 400, batch/ecr 840. The
    # row places slot s at x = 120 + 220*s, so the first ~5 slots sit over the
    # account; those get the account-connected externals, each dropping a short
    # near-vertical edge. The externals that connect only to OTHER externals
    # (Syndi/DIAL/LM) and the self-contained sandbox band trail to the right,
    # so their edges never cross the account drops.
    # Node count is held under the raster width budget (<=3600px landscape) by
    # grouping — NOT dropping — a few boxes: student+operator share one actor
    # box, and the three sandbox fleets collapse to one box carrying all three
    # counts. Every SYSTEM is still named (in the label and the Flow legend);
    # grouping aggressively here is the sanctioned response to a width overflow.
    # Pure-external back-edges (dns->cloudfront, cmtr->eks-dev) are placed
    # ADJACENT to their one partner so each is a SHORT forward hop, not a long
    # back-edge that loops up into the reserved title band (edge-crosses-title,
    # Theme 26). dns sits next to cloudfront; eks-dev next to cmtr. Neither has
    # an account drop, so moving them does not disturb the account-column
    # alignment of the account-connected externals.
    _n("actorsbox", "user", "actors", "", 0, "Students / Operators", kind="aws", container="ext-ingress"),
    _n("cloudfront", "cdn", "actors", "", 1, "CloudFront (4 dist)", container="ext-ingress"),
    _n("dns", "dns", "actors", "", 2, "Route 53 (323549576358)", container="ext-ingress"),
    _n("atlas", "atlas", "actors", "", 3, "MongoDB Atlas (3 DBs)", kind="db", container="ext-ingress"),
    _n("cmtr", "peer_account", "actors", "", 4, "EPM-CMTR CMTM/SRE/EKS (088595288622)", kind="peeracct", container="ext-peeracct"),
    # EPM-CMTR also fronts the KTM student cluster (ED-KRSB) — linked from cmtr.
    _n("eks-dev", "peer_account", "actors", "", 5, "KTM EKS dev (183631338639)", kind="peeracct", container="ext-peeracct"),
    _n("cicd", "peer_account", "actors", "", 6, "CICD acct (884218299410)", kind="peeracct", container="ext-peeracct"),
    # identity that also reaches the APIs (documented in Flow)
    _n("keycloak", "keycloak", "actors", "", 7, "Keycloak SSO", kind="keycloak", container="ext-identity"),
    # LMS -> the mortarboard / graduation-cap education glyph (regen9, owner
    # request). Hand-authored public-domain SVG wired as the `education` role.
    _n("lms", "education", "actors", "", 8, "LMS learn.epam.com", kind="edu", container="ext-identity"),
    # ---- external-to-external integration cluster (Syndi + DIAL + LM) -----
    # Syndicate Server is an external EC2 host drawn as its own node -> the real
    # EC2 service icon (compute_instance), owner feedback 2026-10-17 (e). DIAL AI
    # stays a neutral box — external non-AWS AI proxy, NOT Bedrock. License Mgr
    # -> the real AWS License Manager icon (new license_manager role, feedback g).
    _n("syndicate-server", "compute_instance", "actors", "", 9, "Syndicate Server (Syndi)", kind="ec2", container="ext-integrations"),
    # DIAL AI -> the owner-supplied EPAM DIAL brand mark (regen9). A specific
    # external SaaS brand, wired as the `dial` image role (dial.png in an SVG
    # wrapper), NOT Bedrock and no longer a neutral box.
    _n("dial", "dial", "actors", "", 10, "DIAL AI (ai-proxy.lab.epam)", kind="dial", container="ext-integrations"),
    _n("lm", "license_manager", "actors", "", 11, "License Mgr (652063929809)", kind="licmgr", container="ext-integrations"),
    # ---- sandbox-management context (cleanup fleet — OUT of WAFR scope) ---
    # Ordered sbmgmt | nuke | fleets-box. The sandbox-mgmt org and its central
    # Logging account (650251687330) share one box to hold the row within the
    # raster width budget (both are the same org's control plane).
    # Sandbox-mgmt + Logging ORG -> the AWS Organizations SERVICE icon (regen9,
    # owner request). The org-level glyph (Arch_AWS-Organizations), DISTINCT from
    # the single-account peer_account glyph. Stays in the ext-sandbox band,
    # outside the SEP account.
    _n("sbmgmt", "organizations", "actors", "", 12, "Sandbox-mgmt + Logging org", kind="org", container="ext-sandbox"),
    _n("nuke", "batch", "actors", "", 13, "Nuke fleet (aws/azure/gcp)", kind="aws", container="ext-sandbox"),
    _n("sbfleets", "acct", "actors", "", 14, "Sandbox fleets (3 clouds)", kind="acct", container="ext-sandbox"),

    # ===================================================================== #
    # SEP core: Account(870325637521) > Region(eu-central-1) > se VPC
    # ===================================================================== #
    # edge tier — the front door
    _n("apigw", "api_gateway", "edge", "a", 0, "API Gateway (5 APIs)",
       container="boundary-region-a"),
    # async tier — messaging + eventing
    _n("sqs", "message_queue", "async", "a", 0, "SQS (14 queues)",
       container="boundary-region-a"),
    _n("eventbridge", "eventbridge", "async", "a", 1, "EventBridge (5 rules)",
       container="boundary-region-a"),
    # workers tier — compute
    _n("lambda", "serverless_fn", "workers", "a", 0, "Lambda (13 fns)",
       container="boundary-region-a"),
    _n("batch", "batch", "workers", "a", 1, "AWS Batch (5 CE)",
       container="boundary-region-a"),
    _n("ecr", "ecr", "workers", "a", 2, "ECR (5 repos)",
       container="boundary-region-a"),
    # platform tier — governance + AI
    _n("ssm", "ssm", "platform", "a", 0, "SSM + KMS",
       container="boundary-region-a"),
    _n("bedrock", "llm_platform", "platform", "a", 1, "Bedrock (Angry EdA)",
       container="boundary-region-a"),
    _n("cloudwatch", "cloudwatch", "platform", "a", 2, "CloudWatch",
       container="boundary-region-a"),
    # data tier — stores
    _n("s3", "object_store", "data", "a", 0, "S3 (25 buckets)",
       container="boundary-region-a"),
    _n("dynamodb", "dynamodb", "data", "a", 1, "DynamoDB (CI locks)",
       container="boundary-region-a"),
    # VPC-scoped — RDS is the one node inside the se VPC
    _n("rds", "managed_sql", "data", "a", 2, "RDS sep-strapi-pg",
       container="boundary-vpc-a"),
)

CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None,
                  label_key="account"),
    ContainerSpec(id="boundary-region-a", kind="region", region="a",
                  parent="boundary-account", label_key="region_a"),
    ContainerSpec(id="boundary-vpc-a", kind="vpc", region="a",
                  parent="boundary-region-a", label_key="vpc_a"),
    # Theme 37: the external context systems are grouped into disjoint sibling
    # peer_account boxes so the engine's _wrap_external_bands stacks them into a
    # tidy grid above the account (instead of one 3200px-wide row with ~16%
    # utilisation). Owner's grouping: ingress edge, AWS peer accounts, identity,
    # external integrations, and the sandbox-management cleanup fleet.
    ContainerSpec(id="ext-ingress", kind="peer_account", region="", parent=None, label_key=None),
    ContainerSpec(id="ext-peeracct", kind="peer_account", region="", parent=None, label_key=None),
    ContainerSpec(id="ext-identity", kind="peer_account", region="", parent=None, label_key=None),
    ContainerSpec(id="ext-integrations", kind="peer_account", region="", parent=None, label_key=None),
    ContainerSpec(id="ext-sandbox", kind="peer_account", region="", parent=None, label_key=None),
)

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521",
    "boundary-region-a": "Region eu-central-1",
    "boundary-vpc-a": "se vpc-05cd5663a70d3a65c (192.168.128.0/20)",
    "ext-ingress": "Ingress & identity edge",
    "ext-peeracct": "AWS peer accounts",
    "ext-identity": "Identity (LMS / Keycloak)",
    "ext-integrations": "External integrations (Syndi / DIAL / License)",
    "ext-sandbox": "Sandbox management (cleanup fleet)",
}

# Edges: ONLY the meaningful cross-system paths (not everything-to-everything).
# Keep <= 3 edges per node face. Markers carry per-step detail in the Flow legend.
# Edges: ONLY the meaningful cross-system paths. The external row is wide and
# the account narrow, so cross-band (external<->account) edges are kept to a
# minimal spanning set — one representative edge per external system — and the
# rest of each relationship is described in the Flow legend. The sandbox-context
# edges are local (adjacent nodes, far right) so they add almost no crossings.
EDGES = (
    # --- ingress (actors -> SEP core). Only TWO ingress edges cross into the
    #     account: student->cloudfront->apigw. dns/lms/keycloak/operator link
    #     locally among the edge nodes so they add no account crossings; their
    #     real paths are in the Flow legend. ---
    EdgeSpec(id="e1", source="actorsbox", target="cloudfront", marker="1"),
    EdgeSpec(id="e2", source="cloudfront", target="apigw", marker="2"),
    EdgeSpec(id="e3", source="dns", target="cloudfront", marker="3", dashed=True),
    EdgeSpec(id="e4", source="keycloak", target="lms", marker="4", dashed=True),

    # --- SEP internal data-flow (clean, mostly-vertical skeleton; the full
    #     internal wiring is diagram 03. cloudwatch/dynamodb/ssm stack under sqs
    #     in one column, so the governance links run straight down it). ---
    EdgeSpec(id="e5", source="apigw", target="lambda", marker="5"),
    EdgeSpec(id="e6", source="lambda", target="sqs", marker="6", dashed=True),
    EdgeSpec(id="e7", source="sqs", target="batch", marker="7", dashed=True),
    EdgeSpec(id="e8", source="batch", target="ecr", marker="8"),
    EdgeSpec(id="e9", source="eventbridge", target="batch", marker="9", dashed=True),
    EdgeSpec(id="e10", source="lambda", target="bedrock", marker="10"),
    EdgeSpec(id="e11", source="batch", target="s3", marker="11"),
    EdgeSpec(id="e12", source="lambda", target="rds", marker="12"),
    EdgeSpec(id="e13", source="sqs", target="cloudwatch", marker="13", dashed=True),
    EdgeSpec(id="e14", source="cloudwatch", target="dynamodb", marker="14", dashed=True),
    EdgeSpec(id="e15", source="dynamodb", target="ssm", marker="15", dashed=True),

    # --- SEP core -> external integrations: ONE representative drawn edge
    #     (e16 Lambda->Atlas). The peer-account links (Batch->EPM-CMTR,
    #     ECR->CICD) are described in Flow lines 17/18 but NOT drawn: once the
    #     externals are stacked into the compact grid, those two cross-band legs
    #     rake across the SEP body and push the landscape over its crossing
    #     hard-cap (0.5 x E). Folding them to the legend (the sanctioned
    #     "one representative edge per external system" pattern) keeps marker
    #     coverage 16-18 while the drawn graph stays under the cap. ---
    EdgeSpec(id="e16", source="lambda", target="atlas", marker="16", kind_hint="cross-region"),
    # Intra-group peer-account link (both in ext-peeracct): keeps cicd incident
    # without a cross-band leg. CMTR's CI control plane drives the CICD account.
    EdgeSpec(id="e18", source="cmtr", target="cicd", marker="18", dashed=True, kind_hint="cross-region"),

    # --- external-to-external integration cluster (no account crossings) ---
    # EPM-CMTR control-plane also fronts the KTM student cluster (ED-KRSB).
    EdgeSpec(id="e19", source="cmtr", target="eks-dev", marker="19", dashed=True, kind_hint="cross-region"),
    # Syndi (sandbox lifecycle, consumes SEP SQS over peering) + its DIAL AI call.
    EdgeSpec(id="e20", source="syndicate-server", target="dial", marker="20"),
    # License Manager -> CMTR sync queue (PROVEN LM->CMTR, LM->SEP open). draft.
    EdgeSpec(id="e21", source="lm", target="syndicate-server", marker="21", dashed=True, kind_hint="cross-region"),

    # --- sandbox-management context (cleanup fleet purges the fleets) ---
    # Node order: sbmgmt(+Logging) | nuke | sbfleets.
    EdgeSpec(id="e22", source="sbmgmt", target="nuke", marker="22"),
    EdgeSpec(id="e23", source="nuke", target="sbfleets", marker="23", dashed=True),
)

# Sectioned Flow legend (diagram-standards -> "Sectioned / paged Flow legend"):
# the ~23 steps are grouped under four labelled sub-headers by subsystem so the
# reader navigates by band (Ingress / SEP internal / External integrations /
# Sandbox-mgmt context) rather than scanning one undifferentiated 23-line column.
# Each group is still ascending-numeric and the set covers every marker 1..23,
# so flow-legend coverage is unaffected. The first line stays exactly "Flow".
FLOW = (
    "Flow",
    "Ingress & identity (1-4)",
    "1. Students / Operators reach syndicate.education via CloudFront (4 distributions)",
    "2. CloudFront fronts the REST + WebSocket API Gateways (4 REST + 1 WS)",
    "3. Route 53 (acct 323549576358) resolves syndicate.education to CloudFront",
    "4. Keycloak SSO federates identity; LMS (learn.epam.com) launches tasks via LTI to the REST API",
    "SEP internal data-flow (5-15)",
    "5. API Gateway invokes the SEP Lambda handlers (13 functions)",
    "6. Lambda enqueues work on SQS (14 queues) — async",
    "7. SQS drives AWS Batch jobs (STM / SRE / KTM / ACE / Voiceover, 5 CE)",
    "8. Batch pulls container images from ECR (5 repos)",
    "9. EventBridge rules + schedules trigger Batch runs",
    "10. Lambda calls Bedrock foundation models (Angry EdA)",
    "11. Lambda / Batch write task artifacts / outputs to S3 (25 buckets)",
    "12. Lambda / Strapi persist content to RDS sep-strapi-pg (VPC-scoped)",
    "13. Batch / SQS run metrics flow to CloudWatch alarms (async)",
    "14. CloudWatch / EventBridge governance uses the DynamoDB Terraform state-lock table",
    "15. SSM Parameter Store + KMS hold the JWT salt / SSO secret for the authorizer",
    "External integrations (16-21)",
    "16. Lambda reads/writes MongoDB Atlas over peering pcx-0e257b23d337fda0b (781849312837, .246.0/24)",
    "17. Batch SRE + CMTM + KTM reach EPM-CMTR over peerings pcx-0ba890357ddac7479 (.190.0/24, SRE .190.77) and pcx-0bd56ed835959cbbc (172.31.0.0/16); EKS shared via PUBLIC endpoint",
    "18. ECR / CI sync with the CICD account over peering pcx-0754f6dee2f5bf2fd (884218299410, .254.0/24)",
    "19. KTM also reaches the EKS student cluster development-dev over the PUBLIC endpoint (183631338639)",
    "20. Syndicate Server (Syndi) calls the EPAM DIAL AI proxy ai-proxy.lab.epam.com",
    "21. License Manager (652063929809) sends to the CMTR sep-lm-synchronization-queue — draft assumption; Syndi consumes SEP SQS lifecycle queues over peering",
    "Sandbox-management context (22-23)",
    "22. Sandbox-mgmt org (533267139808) runs the nuke fleet on AWS Batch (eu-west-1); org members forward events to central Logging (650251687330) EventBridge to SQS FIFO",
    "23. Nuke fleet purges the sandbox fleets — AWS (222 accts) / Azure (202 subs) / GCP (org 1090110766254)",
)

LEGEND_EXTRA = (
    "Nesting: Account(870325637521) > Region(eu-central-1) > se VPC; RDS is VPC-scoped",
    "Regional services sit in the Region, outside the VPC (endpoint / NAT access)",
    "Grey box = external non-AWS cloud or a whole-fleet abstraction (no faithful glyph)",
    "Service/brand icons name real resources even when external (EC2 Syndicate Server, License Manager, peer-account + Organizations org glyph, DIAL brand, LMS mortarboard)",
    "Sandbox management (cleanup fleet) = CONTEXT, OUT of WAFR scope",
    "draft-assumption = LM to CMTR queue proven; LM to SEP relay path still open (9B Q1)",
)


def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-sep-crosscloud",
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
        # (mongodb_atlas role), not the grey neutral cylinder.
        return _image_renderer("mongodb_atlas")
    if meta["kind"] == "peeracct":
        # 1.10.11 Theme 34: the AWS peer accounts (EPM-CMTR, CICD, KTM EKS dev)
        # render the real AWS Organizations Account icon (peer_account role),
        # not the grey neutral box.
        return _image_renderer("peer_account")
    if meta["kind"] == "keycloak":
        # 1.10.11 Theme 35: Keycloak SSO renders the colorized Keycloak brand
        # leaf (keycloak role), not the grey neutral box.
        return _image_renderer("keycloak")
    if meta["kind"] == "ec2":
        # Owner feedback (e): the external Syndicate Server is an EC2 host drawn
        # as its own node -> the real EC2 service icon (compute_instance).
        return _image_renderer("compute_instance")
    if meta["kind"] == "licmgr":
        # Owner feedback (g): License Manager -> the real AWS License Manager
        # service icon (new license_manager role, Management & Governance family).
        return _image_renderer("license_manager")
    if meta["kind"] == "edu":
        # regen9: LMS -> the mortarboard / graduation-cap education glyph.
        return _image_renderer("education")
    if meta["kind"] == "dial":
        # regen9: DIAL AI -> the owner-supplied EPAM DIAL brand mark.
        return _image_renderer("dial")
    if meta["kind"] == "org":
        # regen9: Sandbox-mgmt + Logging ORG -> the AWS Organizations SERVICE
        # icon (org-level glyph, distinct from the single-account peer_account).
        return _image_renderer("organizations")
    if meta["kind"] == "acct":
        # Non-AWS / fleet / EC2-based externals keep the neutral box — the pack
        # ships no correct high-level brand/org glyph for them, and a look-alike
        # is forbidden (diagram-standards Icon Fidelity).
        return _flat_style_renderer(NEUTRAL_ACCT_STYLE)
    return _image_renderer(meta["role"])


def _build() -> str:
    spec = _spec()
    placed = layout(spec, strict=False)
    for w in placed.layout_warnings:
        print(f"[layout WARNING] {w}")
    if placed.degraded:
        print("[layout] degraded candidate returned (residual WARNING-level findings)")

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
    style_for_kind = {
        "account": "boundary",
        "region": "region",
        "vpc": "network_boundary",
        "az": "subnet",
        # Theme 37 external group boxes: neutral on-premises style (external,
        # non-SEP-owned context systems drawn as disjoint sibling boundaries).
        "peer_account": "on_premises",
    }
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        boundaries.append(Boundary(
            id=c.id, label=CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=AWS_CONTAINERS[style_for_kind[kind_of[c.id]]], kind=kind_of[c.id],
        ))

    # Band-frame alignment (owner review 2026-10-15): the four stacked pure-
    # external bands (AWS peer accounts / Identity / External integrations /
    # Sandbox management) share one grid-aligned RESOURCE column (every icon at
    # the same x), but the engine's per-box caption-fit widens each box around
    # its own caption and re-centres it, so a wide-caption/narrow-content band
    # (e.g. "External integrations (Syndi / DIAL / License)") pushes its LEFT
    # border out further than a short-caption one — the borders zigzag even
    # though the icons line up. Align the four on one common LEFT edge (the
    # leftmost of the four), keeping each box's own caption-fit WIDTH so the
    # right edge follows content: forcing every box to the widest frame would
    # leave the two-node Identity band mostly empty (container-dead-space). The
    # left borders now agree, which is the alignment the review asked for;
    # content x is untouched (icons stay on the grid, inside each box).
    _STACKED = ("ext-peeracct", "ext-identity", "ext-integrations", "ext-sandbox")
    _frame = [b for b in boundaries if b.id in _STACKED]
    if len(_frame) == len(_STACKED):
        _left = min(b.x for b in _frame)
        for b in _frame:
            # keep right edge fixed, extend left to the common edge
            _right = b.x + b.w
            b.x = _left
            b.w = _right - _left

    edges: List[Edge] = [
        Edge(
            id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
            marker=pe.spec.marker, dashed=pe.spec.dashed,
            exit=pe.exit, entry=pe.entry,
            points=tuple((int(x), int(y)) for x, y in pe.points),
        )
        for pe in placed.edges
    ]

    # 1.10.11 (Theme 33): size the Flow/Legend to content (no narrow 200px pin)
    # so the description boxes are not visually too thin (the user's "опис бокси
    # дуже вузькі" finding). The landscape budget is a generous 3600px, so a
    # content-sized legend fits; the export step applies `--max-width 3600` as a
    # bounded guard rather than re-pinning the legend narrow.
    legend_w = placed.legend_w
    legend_x = placed.legend_x
    rights = [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes]
    rights.append(legend_x + legend_w)
    bottoms = [b.y + b.h for b in boundaries] + [n.y + ICON_SIZE for n in nodes]
    page_w = int(max(rights, default=1600)) + _PAGE_MARGIN
    page_h = int(max(bottoms, default=900)) + _PAGE_MARGIN

    legend_lines = list(legend_lines_for(boundaries)) + list(LEGEND_EXTRA)

    return build_diagram(
        diagram_id="aws-sep-crosscloud",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=FLOW,
        legend_x=legend_x,
        legend_w=legend_w,
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

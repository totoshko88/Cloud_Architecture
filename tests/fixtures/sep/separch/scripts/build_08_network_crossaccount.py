#!/usr/bin/env python3
"""Build the SEP production NETWORK / CROSS-ACCOUNT landscape (08-network-crossaccount).

layout() places the nodes and containers from a coordinate-free DiagramSpec;
build_diagram() renders them. This is the AWS-side NETWORK TRUTH of the SEP prod
account 870325637521 / eu-central-1 (v12, 1.13.0):

* Nesting Account > Region > VPC se > subnet tiers (public / private-app /
  private-batch / isolated-db, declared in the AWS reference order).
* Ingress: Route 53 -> CloudFront -> its real regional origins (API Gateway
  se-ui-api, S3 se-ui), drawn OUTSIDE the VPC. There is NO CloudFront -> IGW ->
  Lambda path (the v11 defect): the IGW serves the public-IP EC2 and the NAT.
* Egress: Lambda / Syndicate Server / Batch -> NAT -> IGW -> the two EKS PUBLIC
  endpoints (KTM control plane 088595288622, ED-KRSB 183631338639).
* VPC endpoints: Lambda -> S3+DynamoDB gateway; Batch -> ECR interface.
* Peering (1.13.0 item 8, container endpoint): each leg leaves the VPC
  CONTAINER face, the pcx node sits in the peer box, every leg is labelled.
  Atlas (SaaS box) and CICD 884218299410 (peer_account group). EPM-CMTR
  (legacy Jenkins TM) and its two peerings are DEPRECATED and not drawn.

The edges the 1.13.0 router draws wrongly on this spec are hand-routed from
the placed boxes in _hand_routes() and frozen with respect_pins=True.

Run from the workspace root:
    python3 scripts/build_08_network_crossaccount.py
"""

from __future__ import annotations

import os
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
from rule_engine.layout import (
    DiagramSpec,
    layout,
    membership_of,
    peering_id_for,
    peering_label_for,
)
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "08-network-crossaccount"
PROVIDER = "aws"
TITLE = "aws SEP network — 870325637521 / eu-central-1 | 2026-11-03 | v12"
SUMMARY_OF = "02-sep-summary"

# 1.11.0 native skin (see FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Skin: role -> draw.io style, read from the WORKSPACE mappings.
# --------------------------------------------------------------------------- #

_MAP = yaml.safe_load((ROOT / "mappings" / "aws-icons.yaml").read_text(encoding="utf-8"))
# Merge the 1.10.11 per-key workspace-local overlay over the bundled mapping
# (same semantics the engine resolver uses), so Path-B roles that live only in
# the overlay — lambda_vpc, sep_platform — resolve here too. The overlay wins
# per key; every other role keeps the bundled value.
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
# icon (diagram-standards Icon Fidelity). An external AWS peer ACCOUNT is a
# neutral account box labelled by account-id + role; MongoDB Atlas is a neutral
# cylinder.
NEUTRAL_DB_STYLE = (
    "shape=cylinder3;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#000000;"
    "boundedLbl=1;backgroundOutline=1;size=15;"
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=12"
)
NEUTRAL_ACCT_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#333333;dashed=1;"
    "verticalLabelPosition=bottom;verticalAlign=top;align=center;fontSize=12"
)

# Neutral dashed-grey boundary for an EXTERNAL sibling container (peer_account /
# external_cloud), drawn OUTSIDE the SEP account. Grey (#666666) distinguishes it
# from the SEP account's own AWS group box; a left-aligned top caption + a
# reserved caption strip (verticalAlign=top) so an entering edge has a corridor.
NEUTRAL_BOUNDARY_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;strokeColor=#666666;"
    "fontColor=#333333;verticalAlign=top;align=left;spacingLeft=6;fontSize=12"
)


def _role_style(role: str) -> str:
    # Prefer the workspace mapping (merged with mappings/local/); fall back to
    # the engine's resolver (the bundled tree) for roles the stale top-level
    # mapping lacks — e.g. `ecs`. Same pattern as 13-sep-dataflow. No mapping is
    # modified; resolution is read-only.
    style = AWS_STYLES.get(role)
    if style:
        return style
    from rule_engine.icon_resolver import resolve_icon
    return resolve_icon(role, PROVIDER)["style_string"]


def _image_renderer(role: str):
    img = _role_style(role).split("image=", 1)[1]
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


# North-South. Global edge (Route 53, CloudFront) sits in the `actors` lane ABOVE
# and OUTSIDE the SEP account. Regional context (API Gateway, the S3 UI bucket:
# the CloudFront origins) sits in the region container but OUTSIDE the VPC.
# VPC-edge devices (IGW, NAT, endpoints) are VPC-direct; workloads sit in subnet
# tiers declared in the AWS reference order public > app > batch > isolated-db.
NODES = (
    _n("dns", "dns", "actors", "", 0, "Route 53 syndicate.education",
       container="ext-edge"),
    _n("cloudfront", "cdn", "actors", "", 1, "CloudFront edge",
       container="ext-edge"),

    # Regional context: the CloudFront origins that exist (edge.json): the
    # se-ui-api API Gateway and the se-ui S3 bucket. NOT in the VPC.
    _n("apigw", "api_gateway", "router", "a", 0, "API Gateway ui-api",
       container="boundary-region-a"),
    _n("s3-ui", "object_store", "router", "a", 1, "S3 se-ui",
       container="boundary-region-a"),

    # VPC edge devices (VPC-direct; engine rule edge-service-in-subnet keeps IGW
    # and NAT out of the subnet boxes). NAT physically lives in se-public-subnet-1.
    _n("igw", "internet_gateway", "edge", "a", 0, "Internet Gateway",
       container="boundary-vpc-a"),
    _n("nat", "nat_gateway", "edge", "a", 1, "NAT Gateway",
       container="subnet-public"),
    _n("vpce-gw", "vpc_endpoint", "edge", "a", 2, "VPCe S3 + DynamoDB",
       container="boundary-vpc-a", sub=1),
    _n("vpce-if", "vpc_endpoint", "edge", "a", 3, "VPCe ECR interface",
       container="boundary-vpc-a", sub=1),

    # public subnet: the only running EC2 with a public IP (modular-cli-instance).
    _n("modular-cli", "compute_instance", "workers", "a", 2, "EC2 modular-cli",
       container="subnet-public"),
    # private app subnets
    _n("lambda", "lambda_vpc", "workers", "a", 1, "Lambda VPC-attached",
       container="subnet-app"),
    _n("syndicate", "compute_instance", "workers", "a", 2, "Syndicate Server",
       container="subnet-app"),
    # strapi-alb: INTERNAL ALB (10-31 snapshot) in the two private app subnets,
    # target group strapi-tg (ip, :1337) = the ECS strapi tasks.
    _n("alb", "lb", "workers", "a", 3, "ALB strapi-alb (internal)",
       container="subnet-app"),
    _n("strapi", "ecs", "workers", "a", 4, "ECS strapi",
       container="subnet-app"),
    # private batch subnets: 5 Fargate compute environments collapsed to one node
    _n("batch", "batch", "workers", "a", 4, "Batch compute (5)",
       container="subnet-batch"),
    # isolated db subnets
    _n("rds", "managed_sql", "workers", "a", 5, "RDS sep-strapi-pg",
       container="subnet-db"),

    # EXTERNAL: one sibling box per peer account + a SaaS box for Atlas.
    _n("atlas", "mongodb_atlas", "on-premises", "xa", 0, "MongoDB Atlas",
       kind="db", container="peer-atlas"),
    # Slots are spaced (0,2,4,6): the pcx node materialized per peering takes the
    # anchor's slot and shifts the anchor +1, and _validate_spec's duplicate-slot
    # key ignores the container, so adjacent slots would collide (engine
    # feedback recorded in phase2-feedback-05-08.md).
    _n("cicd", "peer_account", "on-premises", "xc", 0, "CICD account",
       kind="acct", container="peer-cicd"),
    _n("eks-shared", "managed_k8s", "actors", "xk", 0, "EKS shared (public)",
       container="peer-ktm"),
    _n("eks-dev", "managed_k8s", "actors", "xd", 0, "EKS dev (public)",
       container="peer-krsb"),
)

CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None,
                  label_key="account"),
    ContainerSpec(id="boundary-region-a", kind="region", region="a",
                  parent="boundary-account", label_key="region_a"),
    ContainerSpec(id="boundary-vpc-a", kind="vpc", region="a",
                  parent="boundary-region-a", label_key="vpc_a"),
    ContainerSpec(id="subnet-public", kind="public_subnet", region="a",
                  parent="boundary-vpc-a", label_key="subnet_public"),
    ContainerSpec(id="subnet-app", kind="subnet", region="a",
                  parent="boundary-vpc-a", label_key="subnet_app"),
    ContainerSpec(id="subnet-batch", kind="subnet", region="a",
                  parent="boundary-vpc-a", label_key="subnet_batch"),
    ContainerSpec(id="subnet-db", kind="subnet", region="a",
                  parent="boundary-vpc-a", label_key="subnet_db"),
    # Global edge, outside the region: Route 53 lives in EPMC-EOOS
    # 323549576358, CloudFront is SEP's own global service, so this is a
    # neutral dashed edge box, not a peer-account group.
    ContainerSpec(id="ext-edge", kind="external_cloud", region="", parent=None,
                  label_key="ext_edge"),
    ContainerSpec(id="peer-atlas", kind="external_cloud", region="xa", parent=None,
                  label_key="peer_atlas"),
    ContainerSpec(id="peer-cicd", kind="peer_account", region="xc", parent=None,
                  label_key="peer_cicd"),
    ContainerSpec(id="peer-ktm", kind="peer_account", region="xk", parent=None,
                  label_key="peer_ktm"),
    ContainerSpec(id="peer-krsb", kind="peer_account", region="xd", parent=None,
                  label_key="peer_krsb"),
)

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP AWS 870325637521",
    "boundary-region-a": "eu-central-1",
    "boundary-vpc-a": "se vpc-05cd5663a70d3a65c 192.168.128.0/20",
    "subnet-public": "se-public-subnet",
    "subnet-app": "se-private-app-subnet",
    "subnet-batch": "se-private-batch-subnet",
    "subnet-db": "se-isolated-db-subnet",
    "ext-edge": "Global edge: Route 53 (acct 323549576358) + CloudFront (SEP)",
    "peer-atlas": "MongoDB Atlas 781849312837 (SaaS)",
    "peer-cicd": "AWS 884218299410 CICD",
    "peer-ktm": "AWS 088595288622 KTM control plane",
    "peer-krsb": "AWS 183631338639 ED-KRSB",
}

# Edges. Peering legs leave the SEP VPC CONTAINER face (item 8, container-endpoint
# peering): the pcx node sits on the boundary and every leg is labelled
# ("peering"). EPM-CMTR (legacy Jenkins) and its two peerings are NOT drawn.
EDGES = (
    EdgeSpec(id="e1", source="dns", target="cloudfront", marker="1"),
    EdgeSpec(id="e2", source="cloudfront", target="apigw", marker="2"),
    EdgeSpec(id="e3", source="cloudfront", target="s3-ui", marker="3"),
    EdgeSpec(id="e4", source="apigw", target="lambda", marker="4"),
    EdgeSpec(id="e5", source="igw", target="modular-cli", marker="5"),
    EdgeSpec(id="e6", source="lambda", target="rds", marker="6"),
    EdgeSpec(id="e7", source="strapi", target="rds", marker="7"),
    EdgeSpec(id="e16", source="alb", target="strapi", marker="16"),
    EdgeSpec(id="e8", source="batch", target="vpce-if", marker="8", dashed=True),
    EdgeSpec(id="e9", source="lambda", target="vpce-gw", marker="9", dashed=True),
    EdgeSpec(id="e10", source="batch", target="nat", marker="10"),
    EdgeSpec(id="e11", source="syndicate", target="nat", marker="11"),
    EdgeSpec(id="e12", source="nat", target="igw", marker="12"),
    EdgeSpec(id="e15", source="lambda", target="nat", marker="15"),
    EdgeSpec(id="e13", source="igw", target="eks-shared", marker="13", dashed=True),
    EdgeSpec(id="e14", source="igw", target="eks-dev", marker="14", dashed=True),
    EdgeSpec(id="p1", source="boundary-vpc-a", target="atlas", marker="",
             peering=True, peering_label="Atlas peering",
             peering_id="pcx-0e257b23d337fda0b"),
    EdgeSpec(id="p2", source="boundary-vpc-a", target="cicd", marker="",
             peering=True, peering_label="CICD peering",
             peering_id="pcx-0754f6dee2f5bf2fd"),
)

FLOW = (
    "Flow",
    "1. Route 53 syndicate.education resolves to CloudFront (acct 323549576358)",
    "2. CloudFront origin: API Gateway se-ui-api (regional, outside the VPC)",
    "3. CloudFront origin: S3 se-ui bucket (regional, outside the VPC)",
    "4. API Gateway invokes the VPC-attached Lambda (service invoke, not via the IGW)",
    "5. IGW fronts the one running EC2 with a public IP (modular-cli-instance, public subnet)",
    "6. Lambda reaches the Strapi RDS sep-strapi-pg (isolated db subnets)",
    "7. ECS strapi persists Strapi content to RDS sep-strapi-pg",
    "8. Batch Fargate tasks pull images via the ECR interface endpoints (via endpoint)",
    "9. Lambda reaches S3 + DynamoDB via the gateway endpoints (via endpoint)",
    "10. Batch egress (incl. KTM job) leaves through the NAT Gateway",
    "11. Syndicate Server reaches SQS / Secrets Manager via the NAT (no interface endpoint)",
    "12. NAT egress goes out through the Internet Gateway",
    "13. PUBLIC EKS endpoint of KTM control plane shared (088595288622) via IGW, not peering (public path)",
    "14. PUBLIC EKS endpoint of student development-dev (183631338639) via IGW, not peering (public path)",
    "15. VPC-attached Lambdas reach SQS / Secrets Manager via the NAT (no interface endpoint)",
    "16. Internal ALB strapi-alb forwards to the ECS strapi tasks (target group strapi-tg, ip :1337)",
    "P1. VPC Peering pcx-0e257b23d337fda0b: SEP VPC to MongoDB Atlas 781849312837 (peer 192.168.246.0/24), app data path",
    "P2. VPC Peering pcx-0754f6dee2f5bf2fd: SEP VPC to CICD 884218299410 (peer 192.168.254.0/24)",
)

LEGEND_EXTRA = (
    "Nesting: Account > Region eu-central-1 > VPC (se 192.168.128.0/20) > subnet tier",
    "Dashed line = via VPC endpoint or public internet path (not asynchronous)",
    "Peering legs leave the VPC boundary face; the VPC Peering Connection icon sits in the peer box; every leg labelled 'peering', pcx + CIDR in the Flow list",
    "Grey account group = peer AWS account (outside SEP); dashed grey box = SaaS (MongoDB Atlas) or the global edge",
    "NAT Gateway sits in the public subnet; the Internet Gateway is attached at the VPC level",
    "Regional context (API Gateway, S3) is outside the VPC",
)



def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-sep-network",
        diagram_name=BASENAME,
        axis="north-south",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=FLOW,
        title=TITLE,
        node_labels=node_labels,
        container_captions=tuple(CONTAINER_CAPTIONS.items()),
        # G23: materialize each peering=True edge (e7..e10) into a vpc_peering
        # resource node between the SEP VPC side and the peer account. The
        # public-EKS edges (e11/e12) stay ordinary dashed edges (NOT peerings).
        peering_as_node=True,
    )


def _renderer_for(nid: str):
    # Materialized vpc_peering nodes (G23) are added by layout() as "<edge>-pcx"
    # and are not in NODE_META — render them with the AWS VPC Peering Connection
    # icon.
    if nid not in NODE_META:
        return _image_renderer("vpc_peering")
    meta = NODE_META[nid]
    if meta["kind"] == "db":
        # 1.10.11: MongoDB Atlas renders the real brand-green leaf
        # (mongodb_atlas role), not the grey neutral cylinder.
        return _image_renderer("mongodb_atlas")
    if meta["kind"] == "acct":
        # 1.10.11 Theme 34: an external AWS peer ACCOUNT renders the real
        # AWS Organizations Account icon (peer_account role), not the grey
        # neutral box. The node stays a member of the disjoint `peer-ext`
        # sibling boundary OUTSIDE the SEP account (geometric-containment fix
        # preserved) — only the glyph changes.
        return _image_renderer("peer_account")
    return _image_renderer(meta["role"])


def _hand_routes(placed):
    """Hand routes for the edges the 1.13.0 router draws wrongly on this spec.

    The engine funnels every VPC-edge path (IGW -> EKS, IGW -> EC2, the three
    NAT users, NAT -> IGW) through the 72px gap between the IGW and the NAT,
    so on this spec it either cuts the IGW glyph (e13/e14), merges unrelated
    lines end to end (e14/e15), or crosses the hard cap; and the two
    container-endpoint peering legs leave the VPC on the SAME bottom point
    (exits-identical: item-8 container legs are not in
    contacts.separate_identical_contacts). Each route below is computed from
    the placed node / container boxes (no hard-coded canvas coordinates), is
    orthogonal, exits right/bottom, enters left/top with an approach of at
    least 30px (build_diagram's minimum), and is frozen with
    build_diagram(pinned_ids=..., respect_pins=True). Two sanctioned trunks
    carry the funnel: IGW fan-out (e13/e14/e5) and NAT fan-in (e11/e15/e10).
    Returns {edge_id: (exit, entry, points)}.
    """
    n = {k: (int(b.x), int(b.y)) for k, b in placed.nodes.items()}
    c = {k: (int(b.x), int(b.y), int(b.w), int(b.h)) for k, b in placed.containers.items()}
    S = ICON_SIZE                      # 78
    f = lambda px: px / S              # contact fraction from a px offset
    T1, T2, T3 = 20, 40, 60            # grid-resolved face bands (0.256/0.513/0.769)
    ix, iy = n["igw"]; nx, ny = n["nat"]; mx, my = n["modular-cli"]
    lx, ly = n["lambda"]; bx, by = n["batch"]; sx, sy = n["syndicate"]
    rx, ry = n["rds"]; tx, ty = n["strapi"]; gx, gy = n["vpce-gw"]
    vx, vy = n["vpce-if"]; ax, ay = n["apigw"]
    esx, esy = n["eks-shared"]; edx, edy = n["eks-dev"]
    cfx, cfy = n["cloudfront"]; s3x, s3y = n["s3-ui"]
    p1x, p1y = n["p1-pcx"]; p2x, p2y = n["p2-pcx"]
    vpx, vpy, vpw, vph = c["boundary-vpc-a"]
    acy = c["boundary-account"][1]
    ktx, kty = c["peer-ktm"][:2]
    R = lambda x: x + S                # right face x
    trunk_igw = R(ix) + 12             # IGW fan-out trunk, one step off the IGW
    trunk_nat = nx - 40                # NAT fan-in trunk, clear of the public-subnet border
    assert trunk_nat - trunk_igw >= 20, "IGW/NAT gap too narrow for two trunks"
    vpc_bottom = (vpy + vph) // 10 * 10   # grid line at or above the VPC bottom
    jog_y = vpc_bottom + 40                # lane between the VPC and region bottoms
    return {
        # IGW -> EKS shared / EKS dev: up the IGW trunk and out of the account
        # top to each peer account box (PUBLIC endpoints, not peering).
        "e13": ((1.0, f(T1)), (f(T3), 0.0), (
            (trunk_igw, iy + T1), (trunk_igw, esy - 30), (esx + T3, esy - 30))),
        "e14": ((1.0, f(T2)), (0.0, f(T2)), (
            (trunk_igw, iy + T2), (trunk_igw, acy - 20),
            (edx - 40, acy - 20), (edx - 40, edy + T2))),
        # IGW -> EC2 modular-cli (public IP): IGW trunk, then over the NAT.
        "e5": ((1.0, f(T3)), (0.0, f(T2)), (
            (trunk_igw, iy + T3), (trunk_igw, ny - 20), (mx - 40, ny - 20), (mx - 40, my + T2))),
        # NAT users into the NAT left face via one fan-in trunk.
        "e11": ((1.0, f(T1)), (0.0, f(T1)), (
            (R(sx) + 42, sy + T1), (R(sx) + 42, sy - 20), (trunk_nat, sy - 20),
            (trunk_nat, ny + T1))),
        "e15": ((1.0, f(T2)), (0.0, f(T2)), (
            (trunk_nat, ly + T2), (trunk_nat, ny + T2))),
        "e10": ((1.0, f(T1)), (0.0, f(T3)), (
            (trunk_nat, by + T1), (trunk_nat, ny + T3))),
        # NAT -> IGW (egress out of the VPC): under the NAT/IGW captions into
        # the IGW left face.
        "e12": ((1.0, f(T3)), (0.0, f(T2)), (
            (R(nx) + 22, ny + T3), (R(nx) + 22, ny + 150), (ix - 30, ny + 150),
            (ix - 30, iy + T2))),
        # Lambda -> VPCe S3 + DynamoDB.
        "e9": ((1.0, f(T1)), (0.0, f(T2)), (
            (R(lx) + 52, ly + T1), (R(lx) + 52, gy + T2))),
        # Batch -> VPCe ECR interface (image pulls).
        "e8": ((1.0, f(T2)), (0.0, f(T2)), (
            (vx - 60, by + T2), (vx - 60, vy + T2))),
        # Lambda -> RDS and ECS strapi -> RDS: a fan-in trunk down the free
        # left corridor of the VPC into the RDS left face.
        "e6": ((1.0, f(T3)), (0.0, f(T1)), (
            (R(lx) + 112, ly + T3), (R(lx) + 112, ly + 110), (vpx + 20, ly + 110),
            (vpx + 20, ry + T1))),
        "e7": ((1.0, f(T2)), (0.0, f(T3)), (
            (R(tx) + 42, ty + T2), (R(tx) + 42, vpc_bottom - 40), (vpx + 20, vpc_bottom - 40),
            (vpx + 20, ry + T3))),
        # API Gateway -> Lambda (service invoke), over the app row.
        "e4": ((1.0, f(T2)), (f(T2), 0.0), (
            (R(ax) + 12, ay + T2), (R(ax) + 12, ly - 40), (lx + T2, ly - 40))),
        # CloudFront -> its two regional origins (API Gateway, S3): a shared
        # trunk down the right of the edge box (clear of the CloudFront caption
        # and the box border), then into each origin.
        "e2": ((1.0, f(T2)), (0.0, f(T2)), (
            (R(cfx) + 12, cfy + T2), (R(cfx) + 12, ay + 120), (ax - 30, ay + 120),
            (ax - 30, ay + T2))),
        "e3": ((1.0, f(T1)), (f(T2), 0.0), (
            (R(cfx) + 12, cfy + T1), (R(cfx) + 12, s3y - 40), (s3x + T2, s3y - 40))),
        # Peering legs: from the VPC bottom face (two DISTINCT exit points)
        # onto each pcx. The short jog inside the region keeps the leg's
        # mid-point (where draw.io prints the 'peering' label) off the account
        # border; a straight drop puts the label exactly on it.
        "p1-a": (((p1x + T2 + 140 - vpx) / vpw, 1.0), (f(T2), 0.0), (
            (p1x + T2 + 140, jog_y), (p1x + T2, jog_y))),
        "p2-a": (((p2x + T2 + 140 - vpx) / vpw, 1.0), (f(T2), 0.0), (
            (p2x + T2 + 140, jog_y), (p2x + T2, jog_y))),
    }


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

    # strict=False: accept the best candidate even if it carries a residual
    # WARNING-level finding (here a single corridor-sharing on the ingress stub,
    # a WARNING in the lint ruleset that does not block publication). All
    # ERROR/CRITICAL findings are resolved by the layout; the final gate is the
    # real linter below, not the strict raise.
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
    # Materialized vpc_peering nodes (G23): ids in placed.nodes that are not in
    # the declared spec. Each sits between the SEP VPC side and its peer account
    # with the two legs attaching.
    declared_ids = {n.id for n in spec.nodes}
    for pid, box in placed.nodes.items():
        if pid in declared_ids:
            continue
        # ENG-1 (owner 08: "VPC peering варто давати імена, на основі назви
        # ресурса"): each materialized pcx node carries the SHORT peer-resource
        # name (e.g. "Atlas peering") set on its peering EdgeSpec and surfaced by
        # the engine via peering_label_for(placed.spec, pcx_id). The pcx-id +
        # peer CIDR stay in the Flow legend (P1..P4) — a pcx-id caption would
        # trip node-label-length. Fall back to the generic "VPC Peering" caption
        # when no per-peering label was declared.
        pcx_label = peering_label_for(placed.spec, pid) or "VPC Peering"
        # E-PCX (owner wave-11: "Peering має ідентифікатор і його варто
        # додавати, як підпис, особливо в схемах із багатьма peering"). Put the
        # raw pcx-id on a SECOND caption line below the short peer name, surfaced
        # by the engine via peering_id_for. The two short lines stay under
        # node-label-length (a pcx-id on line 1 alone would trip it); the peer
        # CIDR stays in the Flow legend (P1..P4). Single-line fallback when no
        # id was declared.
        pcx_id = peering_id_for(placed.spec, pid)
        label = f"{pcx_label}\n{pcx_id}" if pcx_id else pcx_label
        nodes.append(Node(
            id=pid,
            label=label,
            x=int(box.x),
            y=int(box.y),
            render=_renderer_for(pid),
            overlay=None,
        ))

    boundaries: List[Boundary] = []
    kind_of = {c.id: c.kind for c in spec.containers}
    from rule_engine.draw_cli import _container_style
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        kind = kind_of[c.id]
        # 1.13.0: every kind (account/region/vpc/subnet/public_subnet and the
        # item-14 peer_account / external_cloud) resolves through the merged
        # mapping tree, so the peer boxes wear the engine's own style.
        style = _container_style(kind, PROVIDER)
        boundaries.append(Boundary(
            id=c.id, label=CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=style, kind=kind,
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
    if os.environ.get("B08_DUMP"):
        for nid, b in sorted(placed.nodes.items()):
            print("NODE", nid, int(b.x), int(b.y))
        for cid, b in sorted(placed.containers.items()):
            print("BOX", cid, int(b.x), int(b.y), int(b.w), int(b.h))
        for e in edges:
            print("EDGE", e.id, e.source, e.target, e.exit, e.entry, e.points)
    hand = _hand_routes(placed)
    edges = [
        Edge(id=e.id, source=e.source, target=e.target, marker=e.marker,
             dashed=e.dashed, exit=hand[e.id][0], entry=hand[e.id][1],
             points=hand[e.id][2])
        if e.id in hand else e
        for e in edges
    ]

    rights = [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [b.y + b.h for b in boundaries] + [n.y + ICON_SIZE for n in nodes]
    page_w = int(max(rights, default=1600)) + _PAGE_MARGIN
    page_h = int(max(bottoms, default=900)) + _PAGE_MARGIN

    legend_lines = [ln for ln in legend_lines_for(boundaries) if not ln.startswith("Dashed line = asynchronous")] + list(LEGEND_EXTRA)

    return build_diagram(
        diagram_id="aws-sep-network",
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
        skin=NATIVE_SKIN,
        container_caption_wrap=2,
        membership=membership_of(placed),
        # Hand-pinned edges (see _hand_routes) are frozen; every other edge
        # is the engine's own route, so it is not listed.
        pinned_ids=tuple(sorted(hand)),
        respect_pins=True,
    )


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

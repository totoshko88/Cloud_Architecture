#!/usr/bin/env python3
"""Build the SEP NETWORK TOPOLOGY landscape (10-network-topology).

HAND-PINNED build (v8), in the exact style of
``.build-tools/build_09_crosscloud_landscape.py``: this script declares EXPLICIT
``Node(x=,y=)`` / ``Boundary(x=,y=,w=,h=)`` / ``Edge(exit=,entry=,points=)``
geometry — the owner's compact copy (``10-network-topology копія.drawio``) — and
calls the shared ``build_diagram(...)`` DIRECTLY, skipping ``layout()``.

Why hand-pinned (see ENGINE-TODO-for-release.md, G40-follow-up / L6): the
coordinate-free solver OVER-STRETCHES the two AZ boxes — it cannot reproduce the
owner's compact AZ layout (narrower AZ boxes, AZ-b pulled left) on this depth-5
network canvas. Per the project rule "never hand-edit the ``.drawio``, change the
script" this is a Python script with pinned geometry, NOT a hand-edited XML —
identical in spirit to how 01/02/04/07/09 are authored.

The node set, captions, roles, container membership, overlays, edges, Flow /
Legend text and the icon fallback (incl. the ``ecs`` strapi
``_style_for_role`` / ``resolve_icon`` fallback) are REUSED VERBATIM from the v7
coordinate-free build — ONLY the POSITIONS change to the owner's compact
geometry (``.agents/tasks/10-owner-geometry.txt``), snapped to the 10-grid.

Depth-5 structure preserved 1:1:

    Account(870325637521)
    └── VPC se 192.168.128.0/20   (region eu-central-1, folded into the caption)
        ├── AZ eu-central-1a            (side-by-side LEFT, x=90 w=510)
        │   ├── subnet public 1a        192.168.128.0/25      (public — edge tier)
        │   ├── subnet private-app 1a   192.168.130.0/23      (private)
        │   ├── subnet private-batch 1a 192.168.136.0/22      (private)
        │   └── subnet isolated-db 1a   192.168.129.0/26      (isolated)
        └── AZ eu-central-1b            (side-by-side RIGHT, x=960 w=480)
            ├── subnet public 1b        192.168.128.128/25    (public)
            ├── subnet private-app 1b   subnet-0198dec2       (private)
            ├── subnet private-batch 1b 192.168.140.0/22      (private)
            └── subnet isolated-db 1b   192.168.129.64/26     (isolated)

The VPC-edge devices (Internet Gateway, the single REGIONAL NAT) are drawn at the
VPC edge OUTSIDE every subnet, between the two AZ boxes. S3/DynamoDB gateway
endpoints sit in the public tiers; the ECR api/dkr INTERFACE endpoints in the
private-batch tiers. The external MongoDB Atlas AWS account 781849312837 and the
Atlas VPC peering pcx-0e257b23d337fda0b sit in a disjoint grey sibling boundary
OUTSIDE the SEP account.

Containment is STRUCTURAL: ``build_diagram`` emits each node as a child of the
tightest Boundary that geometrically contains its icon box (``_node_membership``),
so every interior node is a real structural member of its boundary (clears
``geometric-containment``) — the pinned coordinates place each node fully inside
its intended boundary; no ``parent=`` is set. nat / igw land between the AZ boxes
so they are members of boundary-vpc (not of any subnet / AZ).

Icons resolve from the WORKSPACE mappings/aws-icons.yaml via ``_style_for_role``,
falling back to the engine bundled tree (``resolve_icon``) for roles the workspace
YAML omits — ``ecs`` (strapi) is the one such role; KEEP that fallback.

Run from the workspace root:
    python3 .build-tools/build_10_network_topology.py
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
    overlay_legend_lines,
)

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "10-network-topology"
PROVIDER = "aws"
TITLE = "aws SEP network topology — 870325637521 / eu-central-1 | 2026-10-28 | v8"
SUMMARY_OF = "02-sep-summary"

# 1.11.0 native skin (FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Styles: role -> draw.io style, read from the WORKSPACE mappings (with bundled
# fallback via the engine resolver for roles the workspace YAML omits, e.g. ecs).
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


def _style_for_role(role: str) -> str:
    """Full draw.io style for a role: the workspace YAML, else the engine
    resolver (bundled tree) for a role the workspace omits (e.g. ecs)."""
    if role in AWS_STYLES:
        return AWS_STYLES[role]
    from rule_engine.icon_resolver import resolve_icon
    resolved = resolve_icon(role, PROVIDER)
    return resolved["style_string"] if isinstance(resolved, dict) else resolved


def _image_renderer(role: str):
    img = _style_for_role(role).split("image=", 1)[1]
    return image_icon(img)


# --------------------------------------------------------------------------- #
# Node metadata (role / caption / kind / overlay / scope) — IDENTICAL to v7.
# --------------------------------------------------------------------------- #

NODE_META: Dict[str, Mapping] = {}


def _meta(nid: str, role: str, caption: str, *, kind: str = "aws",
          overlay: Optional[str] = None, scope: Optional[str] = None) -> None:
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind,
                      "overlay": overlay, "scope": scope}


# --- VPC EDGE (outside every subnet, between the two AZ boxes). ------------- #
_meta("igw", "internet_gateway", "Internet Gateway igw-06f4f5e6")
_meta("nat", "nat_gateway", "NAT regional nat-11699e9f")
# --- AZ-a: public (gateway endpoint), private-app, private-batch, db. ------ #
_meta("vpce-s3", "vpc_endpoint", "VPCe S3 gateway", overlay="supporting")
_meta("lambda", "serverless_fn", "Lambda VPC-attached (app 1a)", scope="network")
_meta("ec2-syndi", "compute_instance", "EC2 syndicate-server 192.168.130.138")
_meta("batch-a", "batch", "Batch Fargate (batch 1a)")
_meta("vpce-ecr-api", "vpc_endpoint", "VPCe ECR api interface")
_meta("rds-standby", "managed_sql", "RDS strapi standby", overlay="standby")
# --- AZ-b: public (gateway endpoint), private-app, private-batch, db. ------ #
_meta("vpce-ddb", "vpc_endpoint", "VPCe DynamoDB gateway", overlay="supporting")
_meta("strapi", "ecs", "ECS strapi")
_meta("batch-b", "batch", "Batch Fargate 1b")
_meta("vpce-ecr-dkr", "vpc_endpoint", "VPCe ECR dkr interface")
_meta("rds-primary", "managed_sql", "RDS strapi primary")
# --- EXTERNAL: the Atlas peering RESOURCE node + the Atlas DB. ------------- #
_meta("pcx-atlas", "vpc_peering", "Atlas peering\npcx-0e257b23d337fda0b")
_meta("atlas", "atlas", "MongoDB Atlas (learner datastore)", kind="db")


def _renderer_for(nid: str):
    meta = NODE_META[nid]
    # ADD-1: MongoDB Atlas renders the real brand-green leaf (mongodb_atlas
    # role), not the raw `atlas` role which has no icon of its own.
    if meta["kind"] == "db":
        return _image_renderer("mongodb_atlas")
    return _image_renderer(meta["role"])


def _node(nid: str, x: int, y: int) -> Node:
    meta = NODE_META[nid]
    return Node(
        id=nid,
        label=meta["caption"],
        x=x,
        y=y,
        render=_renderer_for(nid),
        overlay=meta["overlay"],
        scope=meta["scope"],
    )


# --------------------------------------------------------------------------- #
# Pinned node geometry (ABSOLUTE x,y) — owner compact layout, grid-snapped.
# All icons are 78x78. Membership is by geometry (the node box sits inside the
# listed boundary); no parent= is set.
# --------------------------------------------------------------------------- #

NODES: List[Node] = [
    # --- VPC EDGE (boundary-vpc members, between the AZ boxes) ------------- #
    _node("igw", 660, 300),
    _node("nat", 800, 300),
    # --- AZ-a ------------------------------------------------------------- #
    _node("vpce-s3", 360, 300),        # sub-pub-a (310..500); snapped 358->360
    _node("lambda", 150, 530),         # sub-app-a
    _node("ec2-syndi", 390, 530),      # sub-app-a
    _node("batch-a", 150, 760),        # sub-batch-a
    _node("vpce-ecr-api", 390, 760),   # sub-batch-a
    _node("rds-standby", 150, 990),    # sub-db-a
    # --- AZ-b ------------------------------------------------------------- #
    _node("vpce-ddb", 1020, 300),      # sub-pub-b
    _node("strapi", 1020, 530),        # sub-app-b
    _node("batch-b", 1020, 760),       # sub-batch-b
    _node("vpce-ecr-dkr", 1260, 760),  # sub-batch-b
    _node("rds-primary", 1020, 990),   # sub-db-b
    # --- external peer-atlas box ------------------------------------------ #
    _node("pcx-atlas", 60, 1370),      # peer-atlas
    _node("atlas", 300, 1370),         # peer-atlas
]

# --------------------------------------------------------------------------- #
# Containers (pinned Boundary cells) — depth 5: Account > VPC > { AZ-a | AZ-b }
# > subnet tiers, plus the disjoint external peer-atlas sibling. Styles come
# from the AWS container map (NOT the owner's literal style strings) so the
# `container-style` lint rule stays green against the AWS provider profile.
#
# Same-tier subnet widths are MATCHED across AZ-a/AZ-b so sibling-size-uniformity
# clears: sub-pub 190 both, sub-app 378 both, sub-batch 378 both, sub-db 150 both.
# --------------------------------------------------------------------------- #

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521 / eu-central-1",
    "boundary-vpc": "se vpc-05cd5663a70d3a65c (192.168.128.0/20, IPv6 /56)",
    "az-a": "AZ eu-central-1a",
    "az-b": "AZ eu-central-1b",
    "sub-pub-a": "public 1a 128.0/25",
    "sub-app-a": "private-app 1a 130.0/23",
    "sub-batch-a": "private-batch 1a subnet-0def0185 136.0/22",
    "sub-db-a": "db 1a 129.0/26",
    "sub-pub-b": "public 1b 128.128/25",
    "sub-app-b": "private-app 1b subnet-0198dec2",
    "sub-batch-b": "private-batch 1b subnet-0fb5aa20 140.0/22",
    "sub-db-b": "db 1b 129.64/26",
    "peer-atlas": "MongoDB Atlas — AWS 781849312837 (VPC 192.168.246.0/24)",
}

# id, kind, x, y, w, h  (owner compact geometry; sub-pub-a x snapped 308->310)
_CONTAINER_GEOM: Tuple[Tuple[str, str, int, int, int, int], ...] = (
    ("boundary-account", "account", 30, 60, 1470, 1220),
    ("boundary-vpc", "vpc", 60, 120, 1410, 1128),
    ("az-a", "az", 90, 180, 510, 1008),
    ("az-b", "az", 960, 180, 480, 1008),
    ("sub-pub-a", "public_subnet", 310, 240, 190, 198),
    ("sub-pub-b", "public_subnet", 990, 240, 190, 198),
    ("sub-app-a", "subnet", 120, 470, 378, 198),
    ("sub-app-b", "subnet", 990, 470, 378, 198),
    ("sub-batch-a", "subnet", 120, 700, 378, 198),
    ("sub-batch-b", "subnet", 990, 700, 378, 198),
    ("sub-db-a", "subnet", 120, 930, 150, 198),
    ("sub-db-b", "subnet", 990, 930, 150, 198),
    ("peer-atlas", "external_cloud", 30, 1310, 430, 198),
)

# AZ reuses the availability_domain dashed #00A4A6 style (classify_container_kinds
# recognisable); subnet / public_subnet keep their own padlock styles.
STYLE_FOR_KIND = {
    "account": "boundary",
    "region": "region",
    "vpc": "network_boundary",
    "az": "availability_domain",
    "subnet": "subnet",
    "public_subnet": "public_subnet",
}

# Neutral dashed-grey boundary for the EXTERNAL Atlas peer account (ADD-1),
# drawn OUTSIDE the SEP account — grey (#666666) distinguishes it from the SEP
# AWS group box. Same convention as 08's peer-ext box.
NEUTRAL_BOUNDARY_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;strokeColor=#666666;"
    "fontColor=#333333;verticalAlign=top;align=left;spacingLeft=6;fontSize=12"
)


def _container_style(kind: str) -> str:
    if kind in ("external_cloud", "peer_account"):
        return NEUTRAL_BOUNDARY_STYLE
    key = STYLE_FOR_KIND[kind]
    if key in AWS_CONTAINERS:
        return AWS_CONTAINERS[key]
    from rule_engine.icon_resolver import resolve_container
    return resolve_container(key, PROVIDER)["style_string"]


BOUNDARIES: List[Boundary] = [
    Boundary(
        id=cid,
        label=CONTAINER_CAPTIONS[cid],
        x=x,
        y=y,
        w=w,
        h=h,
        style=_container_style(kind),
        kind=kind,
    )
    for (cid, kind, x, y, w, h) in _CONTAINER_GEOM
]

# --------------------------------------------------------------------------- #
# Edges (owner exit/entry + ABSOLUTE points; off-grid exits filled
# contract-legal). exit right/bottom, enter left/top. Every edge pins both
# contacts (no float). Points are MODEL (ABSOLUTE) coords; build_diagram
# relativises them at emit.
# --------------------------------------------------------------------------- #

_X = 1.0256410256410255   # owner right-face perimeter-nudge
_B = 1.0256410256410255   # owner bottom-face perimeter-nudge
_C = 0.5128205128205128   # owner centre
_T = 0.7692307692307693   # owner three-quarter (lower/right band)

EDGES: List[Edge] = [
    # e1 igw->lambda: owner FLOATS the exit; igw bottom (378) sits above the
    # first waypoint row (y=450) and the route leaves downward, so pin the
    # contract-legal bottom-centre exit. entry top-centre (owner).
    Edge("e1", "igw", "lambda", "1", exit=(_C, _B), entry=(_C, 0.0),
         points=[(700, 450), (190, 450)]),
    Edge("e2", "lambda", "vpce-s3", "2", dashed=True, exit=(_X, _C), entry=(0.0, _C),
         points=[(260, 570), (260, 340)]),
    Edge("e3", "batch-a", "vpce-ecr-api", "3", dashed=True, exit=(_X, _C), entry=(0.0, _C)),
    Edge("e4", "batch-b", "vpce-ecr-dkr", "4", dashed=True, exit=(_X, _C), entry=(0.0, _C)),
    # e5 nat->batch-b: owner FLOATS the exit; nat bottom (378) sits above the
    # first waypoint row (y=730), route leaves downward -> bottom-centre exit.
    # owner waypoint 839 snapped to 840 (grid).
    Edge("e5", "nat", "batch-b", "5", exit=(_C, _B), entry=(_C, 0.0),
         points=[(840, 730), (1060, 730)]),
    Edge("e6", "lambda", "rds-primary", "6", exit=(_X, _T), entry=(0.0, _T),
         points=[(310, 590), (310, 1050)]),
    Edge("e8", "lambda", "pcx-atlas", "7", exit=(_C, _B), entry=(_C, 0.0),
         points=[(190, 690), (100, 690)]),
    # e9 ec2-syndi->pcx-atlas: owner third waypoint (None,880) -> absolute x at
    # sub-app-a origin (120), y resolved to 1350.
    Edge("e9", "ec2-syndi", "pcx-atlas", "8", exit=(_X, _T), entry=(_T, 0.0),
         points=[(570, 590), (570, 1350), (120, 1350)]),
    Edge("e10", "pcx-atlas", "atlas", "", exit=(_X, _C), entry=(0.0, _C)),
    Edge("e11", "strapi", "rds-primary", "9", exit=(_X, _T), entry=(0.0, _C),
         points=[(1180, 590), (1180, 640), (980, 640), (980, 1030)]),
]

# --------------------------------------------------------------------------- #
# Flow / Legend (verbatim from v7).
# --------------------------------------------------------------------------- #

FLOW = (
    "Flow",
    "1. Internet Gateway igw-06f4f5e6797fb83bc fronts the public path into the VPC",
    "2. Lambda reaches S3 via the gateway VPC endpoint (no NAT hop)",
    "3. Batch 1a reaches ECR api via the interface VPC endpoint",
    "4. Batch 1b reaches ECR dkr via the interface VPC endpoint",
    "5. NAT nat-11699e9f181a77012 is the single regional egress for the private tier",
    "6. Lambda persists Strapi content to RDS sep-strapi-pg primary (isolated-db 1b)",
    "7. Lambda reads/writes the MongoDB Atlas learner datastore over the Atlas peering",
    "8. EC2 syndicate-server reads/writes MongoDB Atlas (DB PROD_SEP_Server) over the Atlas peering — it does NOT use the Strapi RDS",
    "9. ECS strapi (private-app 1b) persists Strapi content to the RDS sep-strapi-pg primary (isolated-db 1b, intra-AZ)",
    "P1. Atlas peering = pcx-0e257b23d337fda0b to Atlas AWS 781849312837 (peer 192.168.246.0/24)",
    "P2. PEERING pcx-0ba890357ddac7479 to EPM-CMTR SRE 088595288622 (peer 192.168.190.0/24)",
    "P3. PEERING pcx-0bd56ed835959cbbc to CMTR-CloudMentor 088595288622 (peer 172.31.0.0/16)",
    "P4. PEERING pcx-0754f6dee2f5bf2fd to CICD 884218299410 (peer 192.168.254.0/24)",
)

LEGEND_EXTRA = (
    "Nesting: Account > VPC se (192.168.128.0/20) > AZ 1a | 1b > subnet tiers",
    "Dashed #00A4A6 box = Availability Zone (eu-central-1a / 1b, side-by-side)",
    "public_subnet / subnet boxes hold the VPC-scoped workloads in their real CIDRs",
    "VPC edge (outside every subnet): Internet Gateway igw-06f4f5e6 + the single regional NAT nat-11699e9f",
    "ECR api/dkr are INTERFACE endpoints in the private-batch tier (subnet-0def0185 1a / subnet-0fb5aa20 1b, sg-0b18cd10)",
    "Private-subnet routing (E4): 0/0->NAT, ::/0->egress-only IGW, S3/DDB->gateway vpce, +4 peering CIDRs",
    "Isolated-db subnets: local only (no 0/0 route)",
    "Single REGIONAL NAT nat-11699e9f (VPC-edge, ENIs 1a+1b) — both AZs' private route tables send 0/0 to it (not a per-AZ NAT)",
    "Dual-stack IPv6: ::/0 via the egress-only IGW eigw-06e7690a (VPC-edge route-level device; not drawn as a node)",
    "ECS strapi (private-app 1b, subnet-0198dec2) writes RDS sep-strapi-pg primary (intra-AZ)",
    "standby = RDS Multi-AZ passive peer in AZ-a (edges omitted); primary in AZ-b",
    "Grey dashed box = external MongoDB Atlas AWS account 781849312837 (OUTSIDE SEP)",
    "VPC Peering Connection icon = the Atlas peering pcx-0e257b23d337fda0b, between the SEP VPC and Atlas; both Lambda and syndicate-server use it",
    "Atlas = PRIMARY learner datastore (over peering); RDS = Strapi content datastore — different stores",
    "The 3 non-data peerings (pcx + peer CIDR) stay on the Flow list P2-P4, drawn as nodes on 08",
    "No transit gateway / VPN / Direct Connect / network firewall in this account",
    "Public subnets + the default VPC 172.31.0.0/16 hold no SEP workload and are not drawn",
)


def _build() -> str:
    # Right-margin Flow/Legend, pinned to the owner's compact geometry: the
    # owner puts flow-legend at (1560,40,280,...) and legend at (1560,534,...).
    legend_x = 1560
    legend_w = 280
    legend_y_flow = 40
    legend_y_legend = 534

    rights = [b.x + b.w for b in BOUNDARIES] + [n.x + ICON_SIZE for n in NODES]
    rights.append(legend_x + legend_w)
    bottoms = [b.y + b.h for b in BOUNDARIES] + [n.y + ICON_SIZE for n in NODES]
    page_w = int(max(rights)) + _PAGE_MARGIN
    page_h = int(max(bottoms)) + _PAGE_MARGIN

    legend_lines = (list(legend_lines_for(BOUNDARIES))
                    + list(overlay_legend_lines(NODES))
                    + list(LEGEND_EXTRA))

    return build_diagram(
        diagram_id="aws-sep-network-topology",
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

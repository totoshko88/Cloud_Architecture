#!/usr/bin/env python3
"""Generate the AWS **North–South infrastructure** golden example (v1.6.0, D4).

Why this example exists
-----------------------
``diagram-standards.md`` → *Diagram Orientation* specifies two layout axes: a
**left→right** axis for flow / application / data-flow diagrams, and a
**North–South (top→bottom)** axis for infrastructure / network / deployment
diagrams, with external actors at the top, traffic descending into progressively
more internal tiers, and redundant peers (AZ-a / AZ-b) side by side on the same
row. Until 1.6.0 **no shipped golden exercised that axis for an infrastructure
diagram** — the first Open gap in ``docs/REVIEW.md`` (audit finding D4). The rule
was specified and the geometry checks are orientation-agnostic, but the render
path had never been through the gate, so nothing regressed it.

This diagram closes that gap and, in doing so, is the only golden that exercises
two further rules no other example covers:

* **External actors and on-premises sit OUTSIDE the cloud boundaries.** The
  corporate user is placed left of the Account box, and the on-premises database
  gets its **own** boundary container (an AWS ``group_on_premise`` group) drawn
  outside and separate from the Account — never inside it, and never as a bare
  floating icon. The hybrid edge then visibly crosses from the cloud boundary
  into the on-prem boundary, which is the point.
* **East–West redundancy on the North–South axis.** ``az-a`` and ``az-b`` are
  peer containers sharing one top edge and height, side by side, each holding an
  application node and a database node — the availability dimension read
  horizontally while traffic reads vertically.

Geometry comes from the shared standard (``rule_engine.diagram_layout``): 78×78
icons, grid step 10, column step 220, row step 160, ≥ 30px container padding,
right-margin Flow/Legend. Icons are built-in ``mxgraph.aws4.*`` stencils, so the
diagram renders without the fetched vendor packs.

Usage::

    python scripts/build_aws_infra_example.py            # write the .drawio
    python scripts/build_aws_infra_example.py --stdout
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rule_engine.diagram_layout import (  # noqa: E402
    Boundary,
    Edge,
    Node,
    build_diagram,
    builtin_icon,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "examples" / "aws" / "03-aws-hybrid-infrastructure.drawio"

TITLE = "aws hybrid-infrastructure — Account 111122223333 / eu-central-1 | 2026-09-25 | v1"

# Built-in AWS stencil style per node, verified against mappings/aws4-icons.json
# (an unknown resIcon renders as an empty box → icon-resolved ERROR).
_AWS = "shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4"
_TAIL = "strokeColor=#ffffff;aspect=fixed;html=1"


def _icon(res: str, fill: str) -> str:
    return f"{_AWS}.{res};fillColor={fill};{_TAIL}"


# ---------------------------------------------------------------------------
# Geometry — North–South: lanes are ROWS (top→bottom), redundancy reads across.
# ---------------------------------------------------------------------------
# Rows (y), top→bottom, one per lane in the canonical lane order:
#   actors 150 · edge 150 · router 390 · workers 550 · data 710 · on-prem 710
# Columns (x): the actor sits OUTSIDE the Account at x=60; the Account body runs
# from x=300; az-a occupies x=380, az-b x=660 (peers side by side); the two
# regional (non-VPC) services sit in their own column at x=1020, clear of the VPC
# band. The on-premises boundary is a disjoint sibling of the Account at x=1240.
ROW_EDGE = 150
ROW_ROUTER = 390
ROW_APP = 590
ROW_DATA = 750

# (node id, label, resIcon, brand fill, x, y)
NODE_SPECS = [
    # actors lane — OUTSIDE every cloud boundary (left of the Account).
    ("corp-user", "corporate-user", "user", "#232F3E", 60, ROW_ROUTER),
    # edge lane — global services, inside the Account but outside the VPC.
    ("dns", "route53-public-zone", "route_53", "#8C4FFF", 380, ROW_EDGE),
    ("cdn", "cloudfront-edge", "cloudfront", "#8C4FFF", 660, ROW_EDGE),
    # router lane — the public-subnet load balancer, inside the VPC.
    ("alb", "alb-public", "application_load_balancer", "#8C4FFF", 520, ROW_ROUTER),
    # workers lane — one application node per Availability Zone (East–West).
    ("app-a", "ec2-app-az-a", "ec2", "#ED7100", 380, ROW_APP),
    ("app-b", "ec2-app-az-b", "ec2", "#ED7100", 660, ROW_APP),
    # data lane — the writer and its cross-AZ standby.
    ("db-a", "rds-writer-az-a", "rds", "#527FFF", 380, ROW_DATA),
    ("db-b", "rds-standby-az-b", "rds", "#527FFF", 660, ROW_DATA),
    # regional services — in the Account, OUTSIDE the VPC, own column.
    ("efs", "efs-shared-state", "efs_standard", "#7AA116", 1020, ROW_APP),
    ("logs", "s3-access-logs", "s3", "#7AA116", 1020, ROW_EDGE),
    # on-premises — in its OWN boundary, outside the Account.
    ("onprem-db", "onprem-oracle", "traditional_server", "#232F3E", 1300, ROW_DATA),
]

# Node centres (icon 78 → +39): corp-user(99,429) dns(419,189) cdn(699,189)
# alb(559,429) app-a(419,589) app-b(699,589) db-a(419,749) db-b(699,749)
# efs(1059,589) logs(1059,189) onprem-db(1339,749)
EDGES: List[Edge] = [
    # 1: the external actor resolves the public zone. Actor → cloud: exits right,
    # enters left, crossing the Account boundary (the whole point of drawing the
    # actor outside it).
    Edge("e1", "corp-user", "dns", "1", exit=(1.0, 0.25), entry=(0.0, 0.5),
         points=[(240, 410), (240, 189)]),
    # 2: DNS answers with the CDN distribution (same row, straight).
    Edge("e2", "dns", "cdn", "2", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 3: CDN origin fetch descends into the VPC's public load balancer. Bottom
    # exit → top entry: a clean vertical drop through the VPC's caption-free
    # entry corridor.
    Edge("e3", "cdn", "alb", "3", exit=(0.5, 1.0), entry=(0.5, 0.0),
         points=[(699, 320), (559, 320)]),
    # 4/5: the load balancer fans out to both AZs — the East–West redundancy
    # dimension. The straight-down branch is not available (neither app node
    # shares the ALB's column), so both branches leave the bottom face on
    # distinct bands and turn in the gap before their target.
    Edge("e4", "alb", "app-a", "4", exit=(0.25, 1.0), entry=(0.5, 0.0),
         points=[(539, 510), (419, 510)]),
    Edge("e5", "alb", "app-b", "5", exit=(0.75, 1.0), entry=(0.5, 0.0),
         points=[(579, 510), (699, 510)]),
    # 6/7: each AZ's application writes to its own database tier (straight down).
    Edge("e6", "app-a", "db-a", "6", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    Edge("e7", "app-b", "db-b", "7", exit=(0.5, 1.0), entry=(0.5, 0.0)),
    # 8: synchronous cross-AZ replication — the availability edge, read across.
    Edge("e8", "db-a", "db-b", "8", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 9: both application nodes mount the shared regional file system. Only
    # az-b's is drawn (az-a mirrors it) so the fan-out stays legible; EFS sits
    # outside the VPC in its own column, so the edge crosses the VPC border.
    Edge("e9", "app-b", "efs", "9", exit=(1.0, 0.5), entry=(0.0, 0.5)),
    # 10: the load balancer ships access logs to the regional bucket (async).
    Edge("e10", "alb", "logs", "10", dashed=True, exit=(1.0, 0.25), entry=(0.0, 0.5),
         points=[(880, 410), (880, 189)]),
    # 11: the hybrid edge — an in-VPC application replicating to the on-premises
    # database. It visibly crosses OUT of the VPC, out of the Account, and INTO
    # the on-premises boundary.
    Edge("e11", "db-b", "onprem-db", "11", dashed=True, exit=(1.0, 0.5), entry=(0.0, 0.5)),
]

FLOW_LINES = [
    "Flow",
    "1. Corporate user resolves the public hosted zone",
    "2. Route 53 answers with the CloudFront distribution",
    "3. CloudFront origin fetch to the public ALB",
    "4. ALB routes to the AZ-a application tier",
    "5. ALB routes to the AZ-b application tier",
    "6. AZ-a application writes to the AZ-a writer",
    "7. AZ-b application writes to the AZ-b standby",
    "8. Synchronous cross-AZ database replication",
    "9. Application tier mounts the shared file system",
    "10. ALB ships access logs to the bucket (async)",
    "11. Database replicates to on-premises Oracle (async)",
]

# AWS provider container styles (mappings/aws-icons.yaml). The on-premises group
# uses the dedicated ``group_on_premise`` container icon so it reads as a
# non-cloud boundary rather than a second account.
_GROUP = "shape=mxgraph.aws4.group;grStroke=1;fillColor=none;dashed=0;verticalAlign=top;align=left;spacingLeft=30;fontSize=12;html=1"
STYLE_ACCOUNT = (
    f"{_GROUP};grIcon=mxgraph.aws4.group_account;strokeColor=#232F3E;fontColor=#232F3E"
)
STYLE_VPC = (
    f"{_GROUP};grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fontColor=#8C4FFF"
)
STYLE_ONPREM = (
    f"{_GROUP};grIcon=mxgraph.aws4.group_on_premise;strokeColor=#5A6C7D;fontColor=#5A6C7D"
)
# Availability Zones are dashed rectangles (AWS ships no AZ group stencil), in
# the AWS teal used by the reference architectures.
STYLE_AZ = (
    "rounded=0;dashed=1;dashPattern=8 8;fillColor=none;strokeColor=#00A4A6;"
    "verticalAlign=top;align=center;fontColor=#00A4A6;fontSize=12;html=1"
)


def build() -> str:
    boundaries = [
        # Account ⊃ VPC ⊃ (az-a | az-b). Top padding reserves each container's
        # own caption strip (30) plus one grid-step of clearance (30).
        Boundary("boundary-account", "Account 111122223333",
                 x=300, y=60, w=840, h=890, style=STYLE_ACCOUNT),
        Boundary("boundary-vpc", "vpc-hybrid 10.0.0.0/16",
                 x=330, y=280, w=600, h=640, style=STYLE_VPC),
        # Peer AZ bands: same top edge and height, side by side — the East–West
        # redundancy dimension of a North–South layout.
        Boundary("boundary-az-a", "az-eu-central-1a",
                 x=360, y=530, w=258, h=360, style=STYLE_AZ),
        Boundary("boundary-az-b", "az-eu-central-1b",
                 x=640, y=530, w=258, h=360, style=STYLE_AZ),
        # Disjoint sibling of the Account — the on-premises estate is not in the
        # cloud, so it never nests inside the Account boundary.
        Boundary("boundary-onprem", "on-premises datacenter",
                 x=1220, y=650, w=238, h=300, style=STYLE_ONPREM),
    ]
    nodes: List[Node] = [
        Node(id=nid, label=label, x=x, y=y, render=builtin_icon(_icon(res, fill)))
        for (nid, label, res, fill, x, y) in NODE_SPECS
    ]
    return build_diagram(
        diagram_id="aws-hybrid-infrastructure",
        diagram_name="aws-hybrid-infrastructure",
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=EDGES,
        flow_lines=FLOW_LINES,
        legend_x=1490,
        page_w=2000,
        page_h=1000,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build_aws_infra_example")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    xml = build()
    if args.stdout:
        sys.stdout.write(xml)
        return 0
    Path(args.out).write_text(xml, encoding="utf-8")
    print(f"build_aws_infra_example: wrote {args.out} ({len(NODE_SPECS)} nodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

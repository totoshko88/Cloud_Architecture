#!/usr/bin/env python3
"""Build the SEP production NETWORK / CROSS-ACCOUNT landscape (08-network-crossaccount).

Coordinate-free: declares a `DiagramSpec` (nodes/edges/containers/flow) and hands
it to the engine's `layout()` + `build_diagram()` pipeline — no hand-placed
geometry. This is the AWS-side NETWORK TRUTH of the SEP prod account: the se VPC,
its NAT/IGW/VPC-endpoints, the one VPC-scoped tier (private subnet with the
VPC-attached Lambda + the Strapi RDS), the FOUR cross-account VPC peerings, and
the external targets SEP reaches over the PUBLIC internet (the two EKS clusters,
CloudFront + DNS at the edge).

Nesting:  Account(SEP) > Region(eu-central-1) > VPC(se) > subnet tier (az kind).
External peer ACCOUNTS and the EKS clusters and CloudFront/DNS sit OUTSIDE the SEP
account boundary — each a neutral box (an external AWS account is NOT drawn inside
SEP's account; MongoDB Atlas is a neutral cylinder, never a faked AWS icon).

Every peering edge is labelled with its pcx-id + peer CIDR.
Icons resolve from the WORKSPACE `mappings/aws-icons.yaml` (which carries the
workspace-local nat_gateway / internet_gateway / vpc_endpoint networking roles
added for this run — RE gap).

Run from the workspace root:
    python3 scripts/build_08_network_crossaccount.py
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
    Skin,
    build_diagram,
    image_icon,
    legend_lines_for,
    overlay_suffix,
)
from rule_engine.layout import (
    DiagramSpec,
    layout,
    peering_id_for,
    peering_label_for,
)
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "08-network-crossaccount"
PROVIDER = "aws"
TITLE = "aws SEP network — 870325637521 / eu-central-1 | 2026-10-28 | v11"
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


# North-South: ALL external/edge nodes sit in the `actors` lane (the top edge),
# so the engine draws them ABOVE and OUTSIDE the SEP account boundary (the proven
# 03-landscape pattern). SEP VPC-internal tiers descend below. Nesting is kept to
# the proven 3-level depth Account > VPC > subnet (no region container), which
# avoids the account/region tightness overlap a 4-level nest triggers.
NODES = (
    # --- EDGE (very top): global CloudFront + DNS ingress only (acct
    #     323549576358), so every egress edge runs downward with no up-crossing.
    _n("dns", "dns", "actors", "", 0, "Route 53 syndicate.education"),
    _n("cloudfront", "cdn", "actors", "", 1, "CloudFront edge"),

    # --- Everything INSIDE the SEP VPC. The VPC edge/access devices (IGW, NAT,
    #     the 2 VPC-endpoint nodes = 4 endpoints collapsed) sit on the upper VPC
    #     row; the in-network workload (VPC-attached Lambda + Strapi RDS) on the
    #     lower row. Both rows are kept compact (two lanes) so the VPC box nests
    #     cleanly inside the account — see the companion's modelling note. ------
    # One VPC row, ordered so each egress source sits above the peer columns it
    # serves: Lambda above atlas/sre (left), RDS above cmtm/cicd (middle), NAT
    # above the two EKS columns (right). IGW (ingress) and the merged VPC-
    # endpoint node fill the gaps on the upper sub-row.
    # Main workers sub-row: igw, lambda, rds, nat left->right (egress sources
    # above the peer columns they serve). The 2 VPC-endpoint nodes sit on a
    # lower sub-row (sub=1) so nothing sits between lambda and rds.
    _n("igw", "internet_gateway", "workers", "a", 0, "Internet Gateway",
       container="boundary-vpc-a"),
    _n("lambda", "lambda_vpc", "workers", "a", 1, "Lambda VPC-attached",
       container="boundary-vpc-a"),
    _n("rds", "managed_sql", "workers", "a", 2, "RDS sep-strapi-pg",
       container="boundary-vpc-a"),
    _n("nat", "nat_gateway", "workers", "a", 3, "NAT nat-11699e9f181a77012",
       container="boundary-vpc-a"),
    _n("vpce-gw", "vpc_endpoint", "workers", "a", 4, "VPCe S3 + DynamoDB",
       container="boundary-vpc-a", sub=1),
    # Strapi content host, migrating EC2 -> ECS (drawn as ECS in the private
    # app/batch subnet tier). Its DB write path is strapi -> RDS sep-strapi-pg,
    # so the RDS is no longer a producer-less node. VPC-scoped (ecs effective
    # scope = network), so it is scope-placement-clean inside the se VPC. Placed
    # on the lower sub-row left of the RDS column so strapi -> RDS reads forward
    # (exit right, enter left/top) instead of piercing the target from below.
    # wave-13 C.1: slot/order sweeps (peer swap, strapi slot 4) each traded the
    # e13/e8-a collinear for a worse pairing or an extra crossing on this dense
    # cross-account layout, so strapi keeps its slot-5 sub-row position and the
    # single residual collinear:1 (e13, e8-a) + the e8-a peer-ext caption
    # crossing are left as a 1.13.0 engine routing limitation (recorded in
    # DIAGRAM-ENGINE-FEEDBACK-1.13.0.md). Both are WARNINGs and do not block.
    _n("strapi", "ecs", "workers", "a", 5, "ECS strapi",
       container="boundary-vpc-a", sub=1),
    _n("vpce-if", "vpc_endpoint", "workers", "a", 6, "VPCe ECR interface",
       container="boundary-vpc-a", sub=1),

    # --- EXTERNAL peers (1.10.11, Theme 27): every external node is a MEMBER of
    #     ONE disjoint sibling boundary (`peer-ext`) drawn OUTSIDE the SEP
    #     account, so no node is ever geometrically inside a boundary it is not a
    #     structural member of (geometric-containment ERROR on a network diagram
    #     — the headline 1.10.11 defect). Membership is what the lint checks, so
    #     the box IS the fix. One sibling box (not four) keeps all six external
    #     targets on ONE row directly below the account, so every peering /
    #     public-endpoint edge is a short near-vertical drop and the crossing
    #     count stays within the landscape cap (four stacked peer bands blow the
    #     hard crossing cap on this dense cross-account network). Each node still
    #     carries its own identity in its caption + the Flow legend; Atlas keeps
    #     its distinct brand-green leaf, the two EKS keep the AWS EKS icon, so a
    #     reader still tells them apart inside the shared external boundary.
    _n("atlas", "atlas", "on-premises", "", 0, "MongoDB Atlas 781849312837",
       kind="db", container="peer-ext"),
    _n("cmtr-sre", "acct", "on-premises", "", 1, "EPM-CMTR SRE EC2 088595288622",
       kind="acct", container="peer-ext"),
    _n("cmtr-cmtm", "acct", "on-premises", "", 2, "EPM-CMTR CMTM 088595288622",
       kind="acct", container="peer-ext"),
    # The two EKS clusters KTM reaches over PUBLIC endpoints (NOT peering).
    # eks-shared lives in the EPM-CMTR account; eks-dev in ED-KRSB.
    _n("eks-shared", "managed_k8s", "on-premises", "", 3, "EKS shared (public) 088595288622",
       container="peer-ext"),
    _n("cicd", "acct", "on-premises", "", 4, "CICD acct 884218299410",
       kind="acct", container="peer-ext"),
    _n("eks-dev", "managed_k8s", "on-premises", "", 5, "EKS dev (public) 183631338639",
       container="peer-ext"),
)

CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None,
                  label_key="account"),
    ContainerSpec(id="boundary-vpc-a", kind="vpc", region="a",
                  parent="boundary-account", label_key="vpc_a"),
    # ONE external sibling boundary — disjoint, OUTSIDE the SEP account. Holds
    # every external peer / non-AWS target as a structural member.
    ContainerSpec(id="peer-ext", kind="external_cloud", region="", parent=None,
                  label_key="peer_ext"),
)

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521 / eu-central-1",
    "boundary-vpc-a": "se vpc-05cd5663a70d3a65c (192.168.128.0/20) private app/batch subnets",
    "peer-ext": "External peers OUTSIDE SEP — MongoDB Atlas 781849312837 / EPM-CMTR 088595288622 / CICD 884218299410 / ED-KRSB 183631338639",
}

# Edges: the network paths. Peering edges carry pcx-id + peer CIDR in the Flow
# legend (numeric marker on the edge). Public-endpoint edges to EKS are marked.
EDGES = (
    # Ingress (top -> into the VPC workload). IGW and NAT are parallel VPC edge
    # devices, not a chain, so there is no IGW->NAT edge.
    EdgeSpec(id="e1", source="dns", target="cloudfront", marker="1"),
    EdgeSpec(id="e2", source="cloudfront", target="igw", marker="2"),
    EdgeSpec(id="e3", source="igw", target="lambda", marker="3"),
    # In-VPC: the workload reaches S3/DynamoDB and ECR via the VPC endpoints on
    # the lower sub-row (edge flows DOWN from the workload into the endpoint, so
    # it enters the endpoint's top face — the directional contract). Lambda<->RDS.
    EdgeSpec(id="e4", source="lambda", target="vpce-gw", marker="4", dashed=True),
    EdgeSpec(id="e5", source="rds", target="vpce-if", marker="5", dashed=True),
    EdgeSpec(id="e6", source="lambda", target="rds", marker="6"),
    # Strapi content host persists to RDS sep-strapi-pg (the RDS producer).
    EdgeSpec(id="e13", source="strapi", target="rds", marker="7"),
    # The 4 VPC peerings (down to the peer accounts; sources above their
    # targets). peering=True + DiagramSpec.peering_as_node (G23) materializes
    # each into a vpc_peering RESOURCE node between the SEP VPC side and the peer
    # account, with two legs attaching. Empty marker so no 'peering' word prints;
    # the pcx id + peer CIDR stay in the Flow legend (steps 7..10).
    EdgeSpec(id="e7", source="lambda", target="atlas", marker="",
             peering=True, peering_label="Atlas peering",
             peering_id="pcx-0e257b23d337fda0b", kind_hint="cross-region"),
    EdgeSpec(id="e8", source="lambda", target="cmtr-sre", marker="",
             peering=True, peering_label="CMTR-SRE peering",
             peering_id="pcx-0ba890357ddac7479", kind_hint="cross-region"),
    EdgeSpec(id="e9", source="rds", target="cmtr-cmtm", marker="",
             peering=True, peering_label="CMTR-CloudMentor",
             peering_id="pcx-0bd56ed835959cbbc", kind_hint="cross-region"),
    EdgeSpec(id="e10", source="rds", target="cicd", marker="",
             peering=True, peering_label="CICD peering",
             peering_id="pcx-0754f6dee2f5bf2fd", kind_hint="cross-region"),
    # Public EKS endpoints (NAT egress over the internet, NOT peering). Markers
    # 8/9 keep the numbered flow contiguous (1..9) now the four peerings are
    # resource NODES carried as P1..P4 in the Flow legend, not numbered steps.
    EdgeSpec(id="e11", source="nat", target="eks-shared", marker="8", dashed=True, kind_hint="cross-region"),
    EdgeSpec(id="e12", source="nat", target="eks-dev", marker="9", dashed=True, kind_hint="cross-region"),
)

FLOW = (
    "Flow",
    "1. Route 53 syndicate.education resolves to CloudFront (acct 323549576358)",
    "2. CloudFront / clients ingress to the se VPC via the Internet Gateway",
    "3. IGW fronts the public path into the VPC-attached Lambda tier",
    "4. S3 + DynamoDB reached via gateway VPC endpoints (no NAT hop)",
    "5. ECR dkr + api reached via interface VPC endpoints",
    "6. Lambda reaches the Strapi RDS sep-strapi-pg (VPC-scoped)",
    "7. ECS strapi persists Strapi content to RDS sep-strapi-pg",
    "8. PUBLIC EKS endpoint to control-plane shared (088595288622) via NAT over the internet — not peering",
    "9. PUBLIC EKS endpoint to student development-dev (183631338639) via NAT over the internet — not peering",
    "P1. VPC Peering pcx-0e257b23d337fda0b to MongoDB Atlas 781849312837 (peer 192.168.246.0/24) — app data path",
    "P2. VPC Peering pcx-0ba890357ddac7479 to EPM-CMTR SRE 088595288622 (peer 192.168.190.0/24, SRE EC2 .190.77)",
    "P3. VPC Peering pcx-0bd56ed835959cbbc to EPM-CMTR CloudMentor 088595288622 (peer 172.31.0.0/16)",
    "P4. VPC Peering pcx-0754f6dee2f5bf2fd to CICD 884218299410 (peer 192.168.254.0/24)",
)

LEGEND_EXTRA = (
    "Nesting: Account > Region > VPC (se 192.168.128.0/20) > private subnet tier",
    "VPC Peering Connection icon = an active VPC peering drawn as a resource node, between the SEP VPC side and the peer account (pcx + peer CIDR on the Flow list)",
    "Grey box = external, non-AWS (MongoDB Atlas) or an external peer AWS account",
    "VPC endpoints: S3 + DynamoDB gateway, ECR dkr + api interface; NAT egress for the rest",
    "EKS clusters reached over PUBLIC endpoints (not peering); student peering pcx-0fc81284930ddf8e4 is route-less",
    "No SQS / Secrets interface endpoints — those regional services egress via NAT",
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
    style_for_kind = {
        "account": "boundary",
        "region": "region",
        "vpc": "network_boundary",
        "az": "subnet",
    }
    for c in spec.containers:
        box = placed.containers.get(c.id)
        if box is None:
            continue
        kind = kind_of[c.id]
        if kind in ("peer_account", "external_cloud"):
            # Disjoint sibling boundary, OUTSIDE the SEP account. A NEUTRAL grey
            # dashed box (not an AWS account group) — these are peer accounts /
            # a non-AWS cloud, so they must not wear the SEP account's own group
            # style; the neutral box also keeps `container-style` from judging a
            # colour it does not own (unrecognised container → skipped).
            style = NEUTRAL_BOUNDARY_STYLE
        else:
            style = AWS_CONTAINERS[style_for_kind[kind]]
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

    rights = [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes]
    rights.append(placed.legend_x + placed.legend_w)
    bottoms = [b.y + b.h for b in boundaries] + [n.y + ICON_SIZE for n in nodes]
    page_w = int(max(rights, default=1600)) + _PAGE_MARGIN
    page_h = int(max(bottoms, default=900)) + _PAGE_MARGIN

    legend_lines = list(legend_lines_for(boundaries)) + list(LEGEND_EXTRA)

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
    )


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

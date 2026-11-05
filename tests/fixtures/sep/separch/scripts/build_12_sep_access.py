#!/usr/bin/env python3
"""Build the SEP IAM ACCESS diagram (12-sep-access) — WS7 access type.

Coordinate-free: declares a `DiagramSpec` (nodes/edges/containers/flow) and hands
it to the engine's `layout()` + `build_diagram()` pipeline — no hand-placed
geometry. This is the security-review view of the SEP production account's IAM:
the 27 IAM roles in `iam.json` AGGREGATED into a small principal -> policy ->
resource chain read left-to-right, so the drawn node count stays at or below the
access profile's node_cap (12) — the `access-aggregation` lint rule enforces it.

Aggregation (from iam.json `execution_role_map` + `external_trust_analysis`):
  * the 27 roles collapse to FIVE service-principal families by their trust
    principal (who may assume the role): lambda.amazonaws.com (13),
    ecs-tasks.amazonaws.com (8 Batch job+exec), ec2.amazonaws.com (3),
    apigateway.amazonaws.com (1), scheduler.amazonaws.com (1);
  * plus ONE human-assumable principal, se-sandbox-admin, restricted to a
    same-account StringLike aws:userid allow-list of 9 EPAM user principals —
    drawn in a neutral TRUST-BOUNDARY leaf box (the `trust_boundary` special
    container the access profile introduces) because its trust is scoped to
    named human principals, not an AWS service;
  * the grants collapse to TWO policy families (service-execution vs data/
    resource-access), and the objects to TWO resource families (platform data
    stores vs compute/container resources).

Trust FACT preserved from the inventory: NO SEP role trust policy references an
EXTERNAL account principal — every cross-account relationship (CMTR / Atlas /
student cluster) is realised via VPC PEERING, not IAM role trust (see
08-network-crossaccount). That finding is stated in the Flow + Legend so the
reader does not mistake the trust-boundary box for cross-account IAM trust.

diagram_class: flow ; diagram_type: access ; axis left-right.
Icons resolve from the WORKSPACE `mappings/aws-icons.yaml` merged with
`mappings/local/aws-icons.yaml` (overlay wins per key) — principal (IAM Role),
policy (IAM Permissions); the two resource families draw with the ECR service
icon and the AWS General Database glyph (workspace role `data_store_family`).

Run from the workspace root:
    python3 scripts/build_12_sep_access.py
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
from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.pipeline import membership_of
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "12-sep-access"
PROVIDER = "aws"
TITLE = "aws SEP access — 870325637521 / eu-central-1 | 2026-11-04 | v4"

# 1.11.0 native skin (see FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# Skin: role -> draw.io style, read from the WORKSPACE mappings (merged overlay).
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

# Neutral dashed-grey boundary for the TRUST-BOUNDARY leaf box (the `access`
# profile's special container). Grey (#666666) distinguishes it from any AWS
# group box; a left-aligned top caption + reserved caption strip so an entering
# edge has a corridor. Drawn as a disjoint sibling boundary (external_cloud
# kind, which the layout engine supports) because the human-principal trust
# scope sits OUTSIDE the service-assumed IAM graph.
NEUTRAL_BOUNDARY_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;strokeColor=#666666;"
    "fontColor=#333333;verticalAlign=top;align=left;spacingLeft=6;fontSize=12"
)


def _role_style(role: str) -> str:
    """The draw.io style for a role: the workspace mapping first, else the
    engine resolver (the authoritative resolution the verifier/linter use), so
    post-bootstrap roles — principal / policy / resource — resolve even before
    the workspace top-level mapping copy is refreshed."""
    style = AWS_STYLES.get(role)
    if style:
        return style
    from rule_engine.icon_resolver import resolve_icon
    return resolve_icon(role, PROVIDER)["style_string"]


def _image_renderer(role: str):
    img = _role_style(role).split("image=", 1)[1]
    return image_icon(img)


# --------------------------------------------------------------------------- #
# Spec declaration (coordinate-free).
# --------------------------------------------------------------------------- #

NODE_META: Dict[str, Mapping[str, str]] = {}


def _n(nid, role, lane, region, slot, caption, kind="aws", sub=0, container=None,
       overlay=None, icon=None):
    # ``icon`` (optional): the presentation role whose glyph draws this node,
    # when it differs from the access-semantic ``role`` (principal / policy /
    # resource). The spec role stays ``resource`` so the access profile and
    # access-aggregation read the node correctly.
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind,
                      "icon": icon or role}
    return NodeSpec(id=nid, role=role, lane=lane, region=region, slot=slot,
                    sub=sub, container=container, overlay=overlay)


# Left-right chain in CONSECUTIVE lanes: principals (actors, rank 0) ->
# policies (edge, rank 1) -> resources (router, rank 2). Using adjacent lanes
# (not actors/router/data with empty lanes between) keeps the chain tight with
# no horizontal dead space. Ten nodes + one trust-boundary leaf box = within
# the node_cap of 12.
# Phase-2 (1.13.0) layout, declared top-down and laid out verbatim
# (`order="manual"` on the spec):
#   * principals ordered by the policy they attach so the fan-in reads without
#     raking: Scheduler / EC2 (execution only) on top, Lambda / Batch (both) in
#     the middle, API Gateway / se-sandbox-admin (data only) at the bottom;
#   * the Scheduler service principal (p-sched) sits at the TOP slot, far from
#     the human Trust boundary, so its e7 is a short straight-then-drop top
#     entry into the execution policy (no longer raking up through the title);
#   * the Trust boundary box holds ONLY p-admin (the one human-assumable
#     principal). `sub=1` gives the box its 60px caption strip below the API
#     Gateway caption; membership is passed explicitly to `build_diagram` via
#     `membership_of(placed)` so no service principal is parented to the box;
#   * the execution policy/resource pair sits on the upper rows (slot 1, sub -1)
#     and the data policy/resource pair on the human principal's row (slot 5,
#     sub 1), so e8 se-sandbox-admin -> data policies and e9 / e10 are straight
#     horizontals.
# Ten nodes + one trust-boundary leaf box = within the access node_cap of 12.
NODES = (
    # --- PRINCIPALS (the access subjects — IAM Role glyph) -----------------
    _n("p-sched", "principal", "actors", "", 0, "Scheduler role"),
    _n("p-ec2", "principal", "actors", "", 1, "EC2 roles (3)"),
    _n("p-lambda", "principal", "actors", "", 2, "Lambda roles (13)"),
    _n("p-batch", "principal", "actors", "", 3, "Batch roles (8)"),
    _n("p-apigw", "principal", "actors", "", 4, "API Gateway role"),
    # Human-assumable, restricted to 9 EPAM users via aws:userid — the only
    # member of the trust-boundary leaf box (the allow-list is in Flow/Legend).
    _n("p-admin", "principal", "actors", "", 5,
       "se-sandbox-admin", container="trust-box", sub=1),

    # --- POLICIES (the grants — IAM Permissions glyph) ---------------------
    _n("pol-exec", "policy", "edge", "", 1, "Service-execution policies", sub=-1),
    _n("pol-data", "policy", "edge", "", 5, "Data-access policies", sub=1),

    # --- RESOURCES (the objects) -------------------------------------------
    # Spec role stays `resource` (access semantics); the glyph names the family:
    # ECR service icon for the container/compute grants, the AWS General
    # "Database" resource glyph (workspace role `data_store_family`, see
    # mappings/local/aws-icons.yaml) for the aggregated data stores, instead of
    # the uninformative generic-application glyph.
    _n("r-compute", "resource", "router", "", 1, "ECR + EKS (containers)",
       sub=-1, icon="ecr"),
    _n("r-data", "resource", "router", "", 5, "S3, DynamoDB, RDS, Secrets",
       sub=1, icon="data_store_family"),
)

CONTAINERS = (
    # The access profile's trust-boundary leaf box (drawn via external_cloud,
    # the supported disjoint-sibling kind) — holds the human-principal that is
    # scoped to named users rather than an AWS service.
    ContainerSpec(id="trust-box", kind="external_cloud", region="", parent=None,
                  label_key="trust_box"),
)

CONTAINER_CAPTIONS = {
    # wave-2: the caption is kept SHORT so the single-member trust-box is not
    # sized to a ~1100px-wide box by caption-fit (min_w), which was pushing the
    # whole policy/resource chain far right (the 1571px "too wide" defect). The
    # full detail — the same-account root + aws:userid allow-list of 9 EPAM
    # users — stays in the Legend trust-boundary line, so nothing is lost.
    "trust-box": "Trust boundary (humans)",
}

# Edges: principal -> policy -> resource. Each service principal family assumes
# both policy families is over-stated; map each family to the policy it actually
# attaches (exec for compute families, data for the API/handler families), then
# both policies grant onto the resource families.
EDGES = (
    EdgeSpec(id="e1", source="p-lambda", target="pol-exec", marker="1"),
    EdgeSpec(id="e2", source="p-lambda", target="pol-data", marker="2"),
    EdgeSpec(id="e3", source="p-batch", target="pol-exec", marker="3"),
    EdgeSpec(id="e4", source="p-batch", target="pol-data", marker="4"),
    EdgeSpec(id="e5", source="p-ec2", target="pol-exec", marker="5"),
    EdgeSpec(id="e6", source="p-apigw", target="pol-data", marker="6"),
    EdgeSpec(id="e7", source="p-sched", target="pol-exec", marker="7"),
    EdgeSpec(id="e8", source="p-admin", target="pol-data", marker="8"),
    # policies grant onto the resource families.
    EdgeSpec(id="e9", source="pol-exec", target="r-compute", marker="9"),
    EdgeSpec(id="e10", source="pol-data", target="r-data", marker="10"),
)

FLOW = (
    "Flow",
    "1. Lambda service principals assume execution roles (CloudWatch Logs, ECR pull)",
    "2. Lambda roles also carry data-access grants (S3 / DynamoDB / SQS / Secrets)",
    "3. Batch (ecs-tasks) job+execution roles carry execution grants",
    "4. Batch roles carry data-access grants (artifacts, task I/O, EKS DescribeCluster)",
    "5. EC2 instance roles (strapi, syndicate-server, sep_default_cf_ec2) carry execution grants",
    "6. API Gateway role (se-AWSGatewayRoleForSQS) grants SQS SendMessage",
    "7. EventBridge Scheduler role (se-one-time-scheduler-role) carries execution grants",
    "8. se-sandbox-admin is assumed by 9 named EPAM users and carries data/resource grants",
    "9. Execution policies grant onto compute / container resources (ECR, EKS DescribeCluster on local arn)",
    "10. Data policies grant onto the platform data stores (S3, DynamoDB, RDS, Secrets/SSM)",
)

LEGEND_EXTRA = (
    "Aggregation: 27 IAM roles -> 5 service-principal families + 1 human principal (grouped by trust principal)",
    "NO external-account IAM trust exists: every cross-account link (CMTR / Atlas / student cluster) is via VPC peering, not role trust (see 08-network-crossaccount)",
    "Trust boundary box = se-sandbox-admin (same-account root + aws:userid allow-list of 9 EPAM users), assumable by named humans, not by an AWS service",
    "principal = IAM Role (access subject); policy = IAM Permissions (grant); resource = object the grant reaches",
    "Resource glyphs: ECR icon = container/compute family (ECR repos, EKS DescribeCluster); Database glyph = aggregated data stores (S3, DynamoDB, RDS, Secrets Manager, SSM)",
    "Source: inventory iam.json (role_count=27, external_trust_analysis, execution_role_map)",
)


def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-sep-access",
        diagram_name=BASENAME,
        axis="left-right",
        nodes=NODES,
        edges=EDGES,
        containers=CONTAINERS,
        flow_lines=FLOW,
        title=TITLE,
        # wave-2 (owner review 2026-10-23: "незрозуміло чого така широка").
        # The access chain previously used actors(0) / router(2) / data(6), so
        # with compact=False each occupied lane sat at lane_index * col_step,
        # leaving the empty lanes 1/3/4/5 as wide dead horizontal gaps (the
        # 1571px canvas). compact=True was rejected: it collapses non-banded
        # lanes but mis-sizes the single-member trust-box (external_cloud
        # sibling) so the box no longer wraps p-admin and e8 pierces its target.
        # The coordinate-free narrowing lever that works is lane REORDERING: the
        # three tiers now live in CONSECUTIVE lanes principal=actors(0) ->
        # policy=edge(1) -> resource=router(2), so the ranks are already
        # adjacent with no empty lanes between them — the chain reads tightly at
        # col_step 220 and the trust-box stays correctly wrapped around p-admin.
        node_labels=node_labels,
        order="manual",
        container_captions=tuple(CONTAINER_CAPTIONS.items()),
    )


def _renderer_for(nid: str):
    return _image_renderer(NODE_META[nid]["icon"])


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
        # external_cloud -> neutral grey dashed trust-boundary box (unrecognised
        # by container-style, so it is skipped by that rule).
        boundaries.append(Boundary(
            id=c.id, label=CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=NEUTRAL_BOUNDARY_STYLE, kind=kind_of[c.id],
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
        diagram_id="aws-sep-access",
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
        membership=membership_of(placed),
        # The layout's routes are seeds, not owner hand-pins: letting
        # build_diagram re-route them (caption-safe + crossing repair) clears
        # the e7 title/label crossings and drops the crossings 4 -> 0.
        respect_pins=False,
    )


def main() -> int:
    out = ROOT / f"{BASENAME}.drawio"
    out.write_text(_build(), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

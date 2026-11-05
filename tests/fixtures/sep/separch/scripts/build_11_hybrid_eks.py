#!/usr/bin/env python3
"""Build the 11-hybrid-eks diagram triple (.drawio) — cross-account EKS.

v4: renamed from "hybrid" (there is no on-prem). The EKS cluster account
183631338639 is a PEER AWS account (peer_account kind). sep-batch uses the
``batch`` role; S3/SQS are regional (declared region container, outside the VPC).

TASK G of the 1.11.0 regeneration. DIAG-11 v2 (owner variant b, 2026-10-22):
11 is NATIVE AWS + BRAND-SERVICE icons — NOT a k8s-profile hybrid. Every AWS-side
node draws with the NATIVE-colour ``image=assets/vendor/aws-icons/...`` SVG via
``resolve_icon(role, "aws")`` (the path every other SEP diagram uses), so the S3
is green, the Lambda orange, the ALB purple, etc. The two EKS clusters render as
the NATIVE AWS EKS service box (``managed_k8s`` -> Amazon-Elastic-Kubernetes-
Service), NOT a blue kubernetes-profile glyph. The in-cluster services carry
their OWN brand marks: ArgoCD its octopus mascot (owner-supplied asset), Keycloak
its brand mark (the same ``keycloak`` role diagram 01 uses); Gitbud has no
faithful asset so it is NAMED in the label, never a look-alike.

NESTING CAVEAT (unchanged, foreign-leaf nesting still DEFERRED): the student EKS
block is NOT nested inside the AWS VPC. It is drawn as its OWN boundary ADJACENT
to the AWS account (a disjoint peer/sibling boundary), connected by
cross-account / public-endpoint edges — EKS is reached via the public endpoint
per inventory (containers.json: 0 in-account EKS; endpointPublicAccess true,
publicAccessCidrs 0.0.0.0/0; fronted by development-dev-ingress-alb). Since no
node is ``provider="kubernetes"`` any more, the block is an ACCOUNT-style
(neutral) boundary, not the k8s-blue cluster box.

Coordinate-free: DiagramSpec -> layout() -> build_diagram, native skin.

Run from the workspace root:
    python3 scripts/build_11_hybrid_eks.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping

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
from rule_engine.icon_resolver import resolve_icon, resolve_container
from rule_engine.layout import DiagramSpec, layout
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "11-hybrid-eks"
PROVIDER = "aws"
TITLE = "aws SEP cross-account EKS — 870325637521 / eu-central-1 | 2026-10-31 | v4"
SUMMARY_OF = "02-sep-summary"

# 1.11.0 native skin (FEAT-001): light furniture, grey edges, circle badges.
NATIVE_SKIN = Skin(furniture_stroke="light", edge_stroke="#5A6B7B", marker_badge="circle")

_PAGE_MARGIN = 2 * CONTAINER_PAD

# --------------------------------------------------------------------------- #
# DIAG-11 v2: EVERY node draws with the NATIVE-colour AWS / brand image icon via
# resolve_icon(role, "aws") — the image=assets/vendor/... path every other SEP
# diagram uses. managed_k8s -> native AWS EKS box; object_store -> green S3;
# argocd -> owner-supplied octopus mascot; keycloak -> its brand mark. No
# mxgraph.aws4 stencils, no kubernetes-profile glyphs.
# --------------------------------------------------------------------------- #


def _image_renderer(role: str):
    """A native-colour brand/service image icon for ``role`` on provider aws.

    Same shape as build_02's renderer: resolve the role to its
    ``image=assets/vendor/...`` style and embed the asset via ``image_icon`` so
    it renders in the draw.io editor (native colour, not a monochrome stencil)."""
    style = resolve_icon(role, "aws")["style_string"]
    img = style.split("image=", 1)[1]
    return image_icon(img)


# --------------------------------------------------------------------------- #
# Spec declaration (coordinate-free).
# --------------------------------------------------------------------------- #

NODE_META: Dict[str, Mapping[str, str]] = {}


def _n(nid, role, lane, region, slot, caption, provider=None, sub=0, container=None, overlay=None, scope=None):
    NODE_META[nid] = {"role": role, "caption": caption, "provider": provider}
    return NodeSpec(id=nid, role=role, lane=lane, region=region, slot=slot,
                    sub=sub, container=container, overlay=overlay, provider=provider,
                    scope=scope)


# North-South. SEP AWS account tier on top; the student Kubernetes clusters in
# their OWN sibling boundary below (the WS3 foreign-leaf-nesting deferral — not
# nested in the AWS VPC).
NODES = (
    # --- SEP AWS side (primary provider aws, built-in aws4 glyphs). ------- #
    _n("sep-batch", "batch", "workers", "a", 0, "SEP Batch se-ktm-job-def",
       container="boundary-vpc"),
    _n("sep-lambda", "serverless_fn", "workers", "a", 1, "SEP Lambda orchestrator",
       container="boundary-region"),
    _n("sep-sqs", "message_queue", "workers", "a", 2, "SQS ktm queue",
       container="boundary-region"),
    _n("sep-s3", "object_store", "workers", "a", 3, "S3 task artifacts",
       container="boundary-region"),

    # --- Student EKS clusters (NATIVE AWS EKS box) in their OWN sibling boundary
    #     — reached over the PUBLIC EKS endpoint / ingress ALB. In-cluster
    #     ArgoCD / Keycloak carry their own BRAND marks (DIAG-11 v2).
    _n("alb", "lb", "on-premises", "", 0, "dev-ingress-alb (public)",
       container="k8s-block", scope="regional"),
    _n("eks-dev", "managed_k8s", "on-premises", "", 1, "EKS development-dev",
       container="k8s-block"),
    _n("eks-ktm", "managed_k8s", "on-premises", "", 2, "EKS KTM shared",
       container="k8s-block"),
    _n("k8s-argocd", "argocd", "on-premises", "", 3, "ArgoCD (in-cluster)",
       container="k8s-block"),
    _n("k8s-sts", "keycloak", "on-premises", "", 4, "Keycloak/Gitbud sts",
       container="k8s-block"),
)

CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None,
                  label_key="account"),
    ContainerSpec(id="boundary-region", kind="region", region="a",
                  parent="boundary-account", label_key="region"),
    ContainerSpec(id="boundary-vpc", kind="vpc", region="a",
                  parent="boundary-region", label_key="vpc"),
    # The student EKS block is a DISJOINT SIBLING boundary (NOT nested in the AWS
    # VPC) — the foreign-leaf-nesting deferral. DIAG-11 v2: it is drawn with the
    # NATIVE AWS Account group style (a neutral AWS boundary), NOT the k8s-blue
    # cluster box (no node is a kubernetes-profile node any more). The
    # ``external_cloud`` kind keeps it a membership-eligible leaf boundary that
    # sits OUTSIDE the primary account (nodes may belong to it directly, unlike
    # an ``account``-kind envelope).
    ContainerSpec(id="k8s-block", kind="peer_account", region="", parent=None,
                  label_key="k8s_block"),
)

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521 / eu-central-1",
    "boundary-region": "eu-central-1",
    "boundary-vpc": "se vpc-05cd5663a70d3a65c (192.168.128.0/20)",
    "k8s-block": "Peer account 183631338639 (ED-KRSB / KTM EKS)",
}

EDGES = (
    # SEP AWS workflow.
    EdgeSpec(id="e1", source="sep-lambda", target="sep-sqs", marker="1"),
    # Owner step 7 (CONFIRMED FALSE): the SEP Lambda submits the AWS Batch job
    # directly; Batch uses its own built-in job queue. e1 (lambda->sqs) stays
    # the async enqueue; e2 is the direct lambda->batch submit (was sqs->batch).
    EdgeSpec(id="e2", source="sep-lambda", target="sep-batch", marker="2"),
    EdgeSpec(id="e3", source="sep-batch", target="sep-s3", marker="3", dashed=True),
    # Cross-account / public-endpoint hops into the k8s block (NOT nested).
    EdgeSpec(id="e4", source="sep-batch", target="alb", marker="4",
             dashed=True, kind_hint="cross-region"),
    EdgeSpec(id="e5", source="alb", target="eks-dev", marker="5"),
    EdgeSpec(id="e6", source="alb", target="eks-ktm", marker="6"),
    # In-cluster workloads behind each cluster.
    EdgeSpec(id="e7", source="k8s-argocd", target="eks-dev", marker="7"),
    EdgeSpec(id="e8", source="eks-dev", target="k8s-sts", marker="8"),
    # SQS consumer: the KTM shared verification cluster polls the queue.
    EdgeSpec(id="e9", source="sep-sqs", target="eks-ktm", marker="9", dashed=True),
)

FLOW = (
    "Flow",
    "1. SEP Lambda orchestrator enqueues async work on SQS (ktm verification queue)",
    "2. SEP Lambda submits the AWS Batch job directly (se-ktm-job-definition); Batch uses its own built-in job queue",
    "3. Batch stores task artifacts in S3 (task-scoped bucket)",
    "4. Batch reaches the student cluster over the PUBLIC EKS endpoint / ingress ALB",
    "5. dev-ingress-alb fronts the EKS development-dev cluster (183631338639)",
    "6. dev-ingress-alb also fronts the KTM shared verification cluster",
    "7. In-cluster ArgoCD reconciles (deploys to) the EKS development-dev cluster",
    "8. Keycloak / Gitbud run as in-cluster StatefulSets behind the cluster",
    "9. The KTM shared verification cluster consumes the SQS ktm verification queue",
)

LEGEND_EXTRA = (
    "AWS nodes = native-colour AWS service icons (green S3, orange Lambda, purple ALB, ...)",
    "EKS clusters are native AWS EKS; in-cluster ArgoCD/Keycloak carry their own brand marks; Gitbud named in label",
    "Peer account 183631338639 is a sibling account group (no on-prem), NOT nested in the SEP account",
    "EKS reached over PUBLIC endpoint (publicAccessCidrs 0.0.0.0/0) — not peering",
    "In-cluster ArgoCD / Keycloak / Gitbud are in-cluster workloads, not separate EC2/LB resources",
)


def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-k8s-hybrid-eks",
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
    # DIAG-11 v2: every node is a native AWS / brand image icon resolved by role.
    return _image_renderer(NODE_META[nid]["role"])


def _build() -> str:
    spec = _spec()

    # Clarify gate (WS5): read-only, byte-inert for the .drawio.
    from rule_engine.layout.clarify import scan_uncertainties, format_assumptions_markdown
    def _rr(role):
        try:
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
        print("[layout] degraded candidate returned (residual WARNING-level findings)")

    nodes: List[Node] = [
        Node(
            id=n.id,
            label=NODE_META[n.id]["caption"],
            x=int(placed.nodes[n.id].x),
            y=int(placed.nodes[n.id].y),
            render=_renderer_for(n.id),
            overlay=n.overlay,
            scope=n.scope,
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
        kind = kind_of[c.id]
        # DIAG-11 v2: every boundary is a native AWS container style. The student
        # EKS block (external_cloud leaf) is drawn with the native AWS Account
        # group style — a neutral AWS sibling boundary, NOT the k8s-blue cluster
        # box.
        if kind == "account":
            style = resolve_container("boundary", "aws")["style_string"]
        elif kind == "vpc":
            style = resolve_container("network_boundary", "aws")["style_string"]
        else:
            style = resolve_container(kind, "aws")["style_string"]
        boundaries.append(Boundary(
            id=c.id, label=CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=style, kind=kind,
        ))

    edges: List[Edge] = [
        Edge(
            id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
            marker=pe.spec.marker, dashed=pe.spec.dashed, peering=pe.spec.peering,
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
        diagram_id="aws-k8s-hybrid-eks",
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

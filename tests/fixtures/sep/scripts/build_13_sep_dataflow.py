#!/usr/bin/env python3
"""Build the SEP DATA-FLOW / GDPR-WAFR diagram (13-sep-dataflow) — WS8 dataflow type.

Coordinate-free: declares a `DiagramSpec` (nodes/edges/containers/flow) and hands
it to the engine's `layout()` + `build_diagram()` pipeline — no hand-placed
geometry. This is the data-protection view of the Syndicate Education Platform
(SEP): where SEP data lives, how it moves, what is PII, and where encryption
boundaries sit — the GDPR / AWS Well-Architected (Security pillar) lens.

Sources (ingress) -> processing (Lambda / Batch / EC2) -> data stores. Each data
store node carries a DATA-CLASSIFICATION marker in its caption (the token the
`data-classification` lint rule reads): a PII store MUST carry a classification
marker (`encrypted` / `confidential` / `restricted` / ...) or it is an ERROR on a
landscape.

FACTS (from the frozen inventory — never invented):
  * RDS sep-strapi-pg: StorageEncrypted=True (database.json)              -> encrypted
  * MongoDB Atlas PROD_SEP* clusters: encryption-at-rest NONE, hold the
    primary SEP learner / CDM data (INVENTORY-STATE.md section 3)         -> PII, confidential, enc-at-rest NONE (GDPR finding)
  * Secrets: 6 KMS keys + 245 SSM params, metadata-only snapshot          -> KMS-encrypted
  * DynamoDB CiTerraformStateLocks: CI state locks, not learner data      -> non-PII operational
  * S3: 25 buckets                                                        -> see DRAFT-ASSUMPTION below

DRAFT-ASSUMPTIONS (inventory is SILENT; clearly labelled in the Legend, NOT
presented as confirmed facts — per diagram-standards):
  * S3 default encryption + DynamoDB SSE: the snapshot captured no per-bucket
    encryption config and no DynamoDB SSEDescription, so their encryption state
    is UNVERIFIED. AWS applies SSE-S3 / DynamoDB SSE by default, so these are
    drawn `encrypted (draft — unverified)` pending an owner / config-audit
    confirmation.
  * PII scope of se-* buckets (support attachments, verification outputs,
    reports) is assumed from bucket naming, not from a data-classification scan.

diagram_class: landscape ; diagram_type: dataflow ; axis left-right ;
summary_of: 02-sep-summary (avoids orphan-landscape).

Run from the workspace root:
    python3 scripts/build_13_sep_dataflow.py
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
from rule_engine.layout.model import ContainerSpec, EdgeSpec, NodeSpec

ROOT = Path(__file__).resolve().parent.parent
BASENAME = "13-sep-dataflow"
PROVIDER = "aws"
TITLE = "aws SEP dataflow — 870325637521 / eu-central-1 | 2026-10-28 | v9"
SUMMARY_OF = "02-sep-summary"

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

NEUTRAL_BOUNDARY_STYLE = (
    "rounded=0;whiteSpace=wrap;html=1;dashed=1;fillColor=none;strokeColor=#666666;"
    "fontColor=#333333;verticalAlign=top;align=left;spacingLeft=6;fontSize=12"
)


def _role_style(role: str) -> str:
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
       overlay=None, scope=None, external=False, exit_face=None):
    NODE_META[nid] = {"role": role, "caption": caption, "kind": kind}
    return NodeSpec(id=nid, role=role, lane=lane, region=region, slot=slot,
                    sub=sub, container=container, overlay=overlay, scope=scope,
                    external=external, exit_face=exit_face)


# Left-right dataflow: ingress -> processing -> data stores. The processing +
# AWS data stores nest inside the SEP account / region; MongoDB Atlas is an
# EXTERNAL store drawn OUTSIDE the account in its own encryption-boundary box.
# Every data-store caption carries a PII / encryption classification marker the
# `data-classification` rule reads.
NODES = (
    # --- INGRESS (sources of data; external, OUTSIDE the account) ----------
    # FEAT-002 ITEM G (owner: "студент lms sep cf api gw і також напряму без lms"):
    # the single flat `clients` ingress is expanded into the REAL ingress chain
    # Student -> LMS -> CloudFront -> API Gateway -> Lambda, PLUS a direct
    # Student -> CloudFront path that bypasses the LMS (a learner who opens the
    # Syndicate UI directly rather than launching from a course). This fills the
    # empty left of the canvas with the honest ingress topology. Student + LMS
    # are actors; CloudFront + API Gateway are the edge tier. PII travels over
    # TLS on every ingress hop (classification kept in the Student caption).
    _n("student", "user", "actors", "", 0,
       "Learner (PII in transit, encrypted TLS)", kind="aws"),
    _n("lms", "education", "actors", "", 1, "LMS learn.epam.com (LTI launch)", kind="edu"),
    # WAF fronts CloudFront at the GLOBAL edge (NEVER inside the region/VPC;
    # scope-placement: waf default scope=global, a WAF inside a region fires
    # global-in-region). Placed in the `edge` lane next to CloudFront, no
    # container, consistent with 01/02/03/09. Matches the real
    # syndicate_education_cloudfront_waf web ACL (wafv2 global).
    _n("waf", "waf", "edge", "", 0, "WAF (CloudFront)"),
    _n("cloudfront", "cdn", "edge", "", 1, "CloudFront (TLS edge)"),
    # SPEC-13 (owner 13: "API GW це регіональний сервіс тож він повинен бути в
    # регіоні"): API Gateway is a REGIONAL managed service, so it is drawn INSIDE
    # the region box (but OUTSIDE the VPC) rather than at the global/edge tier.
    # `api_gateway` is not in ROLE_SCOPE (unjudged), so the sanctioned way to
    # permit regional-in-region placement is the per-node scope override
    # (scope="regional") — NOT a change to the shared role. CloudFront stays at
    # the edge (global). The empty CloudFront->region gap closes automatically,
    # and marker 3 (CloudFront -> API GW) reads as a straight-down drop (SYS-A).
    _n("apigw", "api_gateway", "router", "a", 0, "API Gateway (regional, TLS ingress)",
       container="boundary-region-a", scope="regional"),

    # --- PROCESSING (inside the account/region) ----------------------------
    # Lambda is the hub; Batch and Strapi stack below it so their store edges
    # run forward-right with the Lambda fanout rather than crossing it.
    _n("lambda", "serverless_fn", "workers", "a", 0, "Lambda handlers",
       container="boundary-region-a"),
    # Batch sits in the `platform` lane (its own column, right of the Lambda
    # workers column) rather than stacked directly below Lambda. This keeps the
    # column BELOW Lambda clear, so the Lambda->Atlas back-edge (e10) can exit
    # bottom and run DOWN-then-LEFT to the bottom-left Atlas box without its drop
    # leg crossing the Batch icon (ADD-2: no right-side hook, no knee-through).
    _n("batch", "batch", "platform", "a", 0, "AWS Batch jobs",
       container="boundary-region-a"),
    # Owner wave-10 B2: Strapi and the Syndicate Server are TWO DIFFERENT EC2s
    # (inventory: syndicate-server, strapi-server, modular-cli — three distinct
    # instances). The Syndicate Server is the account-orchestration control
    # plane and is NOT a dataflow participant here, so it is NOT drawn. This node
    # is the Strapi content-server EC2 only; its datastore is RDS sep-strapi-pg
    # (INVENTORY-STATE: "Strapi content only").
    _n("strapi", "ecs", "workers", "a", 2, "ECS strapi-server",
       container="boundary-vpc-a"),

    # --- DATA STORES (classification in caption) ---------------------------
    # RDS is the one VPC-scoped store, so it anchors the VPC band at data slot 0
    # (keeping Account > Region > VPC nesting valid). The regional stores follow.
    _n("rds", "managed_sql", "data", "a", 0,
       "RDS strapi-pg (Postgres, encrypted KMS)", container="boundary-vpc-a"),
    # S3: encryption silent in snapshot -> DRAFT-ASSUMPTION; PII in some buckets.
    _n("s3", "object_store", "data", "a", 1,
       "S3 (25 buckets; PII attachments/reports; encrypted draft-unverified)",
       container="boundary-region-a"),
    # DynamoDB: CI state locks, non-PII operational; SSE silent -> draft.
    _n("dynamodb", "dynamodb", "data", "a", 2,
       "DynamoDB CiTerraformStateLocks (Terraform state-lock; operational)",
       container="boundary-region-a"),
    # Secrets / KMS: KMS-encrypted keys + SSM params.
    _n("secrets", "secrets_store", "data", "a", 3,
       "Secrets / SSM + KMS (encrypted; secret material not read)",
       container="boundary-region-a"),

    # --- EXTERNAL data store (OUTSIDE the account) -------------------------
    # MongoDB Atlas: primary SEP learner / CDM data; encryption-at-rest NONE
    # (confirmed finding). PII + confidential classification; the NONE finding
    # is the GDPR point, stated in the caption and the Flow/Legend.
    _n("atlas", "mongodb_atlas", "on-premises", "", 0,
       "MongoDB Atlas PROD_SEP (PII learner data, confidential, enc-at-rest NONE)",
       kind="db", container="atlas-box"),
)

CONTAINERS = (
    ContainerSpec(id="boundary-account", kind="account", region="", parent=None,
                  label_key="account"),
    ContainerSpec(id="boundary-region-a", kind="region", region="a",
                  parent="boundary-account", label_key="region_a"),
    ContainerSpec(id="boundary-vpc-a", kind="vpc", region="a",
                  parent="boundary-region-a", label_key="vpc_a"),
    # External encryption-boundary box for the non-AWS primary store.
    ContainerSpec(id="atlas-box", kind="external_cloud", region="", parent=None,
                  label_key="atlas_box"),
)

CONTAINER_CAPTIONS = {
    "boundary-account": "SEP — AWS 870325637521 / eu-central-1 (data at rest in-region; KMS encryption boundary)",
    "boundary-region-a": "Region eu-central-1 — regional managed data stores",
    "boundary-vpc-a": "se VPC (192.168.128.0/20) — VPC-scoped stores (RDS, Strapi)",
    "atlas-box": "External encryption boundary — MongoDB Atlas (EU_CENTRAL_1, Atlas-managed acct, VPC-peered; NO Atlas enc-at-rest)",
}

# Data-flow edges: ingress chain + direct bypass -> processing -> stores.
# Markers renumbered in lockstep with the Flow legend below (contiguous 1..N
# with the new WAF->CloudFront step).
EDGES = (
    # ingress chain: WAF -> CloudFront; Student -> LMS -> CloudFront -> API GW
    # -> Lambda. WAF->CloudFront is a short forward hop in the edge band
    # (wave-13 B.3).
    EdgeSpec(id="e13", source="waf", target="cloudfront", marker="1"),
    EdgeSpec(id="e1", source="student", target="lms", marker="2"),
    EdgeSpec(id="e2", source="lms", target="cloudfront", marker="3"),
    EdgeSpec(id="e3", source="cloudfront", target="apigw", marker="4"),
    # direct learner path, bypassing the LMS (Student -> CloudFront)
    EdgeSpec(id="e4", source="student", target="cloudfront", marker="5", dashed=True),
    EdgeSpec(id="e5", source="apigw", target="lambda", marker="6"),
    # wave-13 B.1 (owner: "10 може вийти ліворуч внизу і тоді не буде перетинів
    # із 7"). e10 (Lambda -> MongoDB Atlas, bottom-LEFT outside the account) is
    # declared immediately after the ingress hop into Lambda and before the
    # rightward store fan, biasing the engine's direction-spread to give the
    # Atlas edge a down-left band and the store edges the forward-right bands.
    # NOTE: on this engine (1.13.0) the heavy 5-way Lambda fan-out still routes
    # e10 out of Lambda's bottom-right and e7 (Lambda->RDS, climbing UP to the
    # top of the data column) stays in 4 of the 5 residual crossings; the
    # owner-requested LEFT-face exit for e10 is not reachable through the spec
    # (see DIAGRAM-ENGINE-FEEDBACK-1.13.0.md). The reorder is retained because it
    # is the correct declarative intent and is byte-equivalent to the store-first
    # order.
    EdgeSpec(id="e10", source="lambda", target="atlas", marker="7"),
    # processing -> stores (rightward fan)
    EdgeSpec(id="e6", source="lambda", target="batch", marker="8", dashed=True),
    EdgeSpec(id="e7", source="lambda", target="rds", marker="9"),
    EdgeSpec(id="e8", source="lambda", target="dynamodb", marker="10", dashed=True),
    EdgeSpec(id="e9", source="lambda", target="secrets", marker="11"),
    EdgeSpec(id="e11", source="batch", target="s3", marker="12"),
    # Owner wave-10 B2: the Strapi content-server EC2 persists Strapi content to
    # RDS sep-strapi-pg (INVENTORY-STATE: "RDS = sep-strapi-pg, Strapi content
    # only"). Atlas keeps exactly one writer in this view: the Lambda handlers
    # (e10).
    EdgeSpec(id="e12", source="strapi", target="rds", marker="13"),
)

FLOW = (
    "Flow",
    "1. WAF (global) inspects requests at the CloudFront edge before they reach the origin",
    "2. Learner launches a task from the LMS (LTI); PII travels over TLS",
    "3. LMS redirects the learner to SEP via CloudFront",
    "4. CloudFront (TLS) forwards the request to API Gateway",
    "5. Learner also opens the Syndicate UI directly via CloudFront (bypasses the LMS)",
    "6. API Gateway (TLS) forwards requests to the Lambda handlers",
    "7. Lambda reads/writes the PRIMARY learner datastore MongoDB Atlas over VPC peering",
    "8. Lambda submits AWS Batch jobs directly; Batch uses its own built-in job queue",
    "9. Lambda persists content to RDS strapi-pg (encrypted at rest, KMS)",
    "10. Lambda uses the DynamoDB CI state-lock table (operational, non-PII)",
    "11. Lambda reads Secrets / SSM parameters (KMS-encrypted; values never read)",
    "12. Batch writes task artifacts / verification outputs (incl. PII) to S3",
    "13. ECS strapi-server persists Strapi content to RDS sep-strapi-pg (encrypted at rest, KMS)",
)

LEGEND_EXTRA = (
    "WAF (global) protects CloudFront at the edge, outside the region/VPC (syndicate_education_cloudfront_waf web ACL)",
    "Classification markers (in node captions): PII = personal data; confidential/encrypted = data posture",
    "GDPR FINDING (confirmed): MongoDB Atlas holds the primary SEP learner data with encryption-at-rest NONE — the key data-protection gap",
    "CONFIRMED encryption: RDS strapi-pg StorageEncrypted=True; Secrets/SSM via KMS (6 keys)",
    "DRAFT-ASSUMPTION (inventory silent — verify with owner / config audit): S3 default encryption + DynamoDB SSE drawn as 'encrypted draft-unverified'; the snapshot captured no per-bucket encryption or SSEDescription",
    "DRAFT-ASSUMPTION: PII scope of se-* buckets assumed from naming (support attachments, verification outputs, reports), not a data-classification scan",
    "Data residency: AWS eu-central-1 + MongoDB Atlas EU_CENTRAL_1 (Frankfurt) — EU region",
    "Source: inventory storage.json / database.json / secrets.json + INVENTORY-STATE.md section 3 (Atlas)",
)


def _spec() -> DiagramSpec:
    node_labels = tuple((nid, meta["caption"]) for nid, meta in NODE_META.items())
    return DiagramSpec(
        diagram_id="aws-sep-dataflow",
        diagram_name=BASENAME,
        axis="left-right",
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
        return _image_renderer("mongodb_atlas")
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

    placed = layout(spec, strict=False)
    for w in placed.layout_warnings:
        print(f"[layout WARNING] {w}")
    if placed.degraded:
        print("[layout] degraded candidate returned")

    # wave-2 DEFECT 6a (owner review 2026-10-23: "9 наклалась на account бокс").
    # The engine places the single external `atlas` node just LEFT of the
    # workers column (x~850, left of lambda/strapi at x~910), so the two edges
    # that drop to it (e7 lambda->atlas, e9 strapi->atlas) loop left and ride
    # the account box's LEFT border down (edge-on-container-border). Shifting the
    # atlas node RIGHT so it sits under the WORKERS->DATA gap gives those drops a
    # clear inter-column corridor instead of the border. This is the same
    # builder-side atlas node-position nudge the 09 landscape applies (a cosmetic
    # grid placement, not a layout-geometry hand-hack — the edge contacts
    # re-align at render time via _orthogonalised, which we let re-route by
    # clearing the stale atlas-edge waypoints below). The x is snapped to the
    # grid and chosen as the mid-gap between the workers column and the data
    # column so the drop clears every icon and both container borders.
    # FEAT-002 ITEM G: the expanded ingress (Student / LMS / CloudFront) changed
    # the layout, so the old builder-side atlas node-position nudge (which forced
    # atlas left/right of the workers column and cleared its edge waypoints) now
    # fights the engine's route and pierces an intermediate glyph. The 1.11.0
    # engine places and routes the external atlas node cleanly on its own, so the
    # nudge is dropped: atlas keeps its engine x/y and e10/e12 keep their engine
    # routes verbatim (coordinate-free). The atlas-box width is still aligned to
    # the account box below so it does not run under the right-margin Legend.
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
        kind = kind_of[c.id]
        if kind == "external_cloud":
            style = NEUTRAL_BOUNDARY_STYLE
        else:
            style_kind = {"account": "boundary", "region": "region", "vpc": "network_boundary"}[kind]
            style = AWS_CONTAINERS[style_kind]
        boundaries.append(Boundary(
            id=c.id, label=CONTAINER_CAPTIONS[c.id],
            x=int(box.x), y=int(box.y), w=int(box.w), h=int(box.h),
            style=style, kind=kind,
        ))

    # wave-2 DEFECT 6b (owner review 2026-10-23: "Mongo Atlas Box вирівняти по
    # ширині із акаунтом, бо зараз накладається на легенду"). The external
    # `atlas-box` is the ONLY external sibling, so the engine's
    # `_external_groups`/`_repitch_external_bands` (which need >=2 bands) never
    # run and the box is sized tight to its single `atlas` node — narrower than,
    # and offset from, the SEP account box, which pushed its right edge under the
    # right-side Legend. Align its LEFT edge and WIDTH to the SEP account box
    # (`boundary-account`) so the two boundaries share one left edge and one
    # right edge (the sanctioned builder-side Boundary alignment, 09 precedent —
    # a right-margin/furniture alignment on the emitted Boundary, NOT a
    # node-geometry hand-hack). legend_x is then recomputed from the final body
    # extents so the Flow/Legend clears the widened Atlas box.
    _acct = next((b for b in boundaries if b.id == "boundary-account"), None)
    _atlas = next((b for b in boundaries if b.id == "atlas-box"), None)
    if _acct is not None and _atlas is not None:
        _atlas.x = _acct.x
        _atlas.w = _acct.w

    # Every edge keeps its engine route verbatim (coordinate-free).
    edges: List[Edge] = [
        Edge(
            id=pe.spec.id, source=pe.spec.source, target=pe.spec.target,
            marker=pe.spec.marker, dashed=pe.spec.dashed,
            exit=pe.exit, entry=pe.entry,
            points=tuple((int(x), int(y)) for x, y in pe.points),
        )
        for pe in placed.edges
    ]

    # Recompute legend_x from the FINAL body extents (incl. the widened
    # atlas-box above), so the Flow/Legend column sits past the right edge of
    # every boundary and node footprint (09 precedent, diagram-standards
    # "Reserve the right margin for Flow/Legend"). Using the engine's
    # placed.legend_x would leave the column overlapping the now-wider Atlas box.
    _body_right = max(
        [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes],
        default=1600,
    )
    legend_x = max(int(placed.legend_x), int(_body_right) + CONTAINER_PAD)

    rights = [b.x + b.w for b in boundaries] + [n.x + ICON_SIZE for n in nodes]
    rights.append(legend_x + placed.legend_w)
    bottoms = [b.y + b.h for b in boundaries] + [n.y + ICON_SIZE for n in nodes]
    page_w = int(max(rights, default=1600)) + _PAGE_MARGIN
    page_h = int(max(bottoms, default=900)) + _PAGE_MARGIN

    legend_lines = list(legend_lines_for(boundaries)) + list(LEGEND_EXTRA)

    return build_diagram(
        diagram_id="aws-sep-dataflow",
        diagram_name=BASENAME,
        title=TITLE,
        boundaries=boundaries,
        nodes=nodes,
        edges=edges,
        flow_lines=FLOW,
        legend_x=legend_x,
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
